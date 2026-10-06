"""好感度分析编排服务：汇总各维度评分结果。

六维点数制权重 + 归一引擎（affinity_weights）：
- 情感共振率 / 聊天积极度 / 态度倾向 / 喜好兼容度（配关键词时启用）
  / 亲密度信号 / LLM 关系评估（配模型且开关开时启用）
- 各维 declared 权重不要求和为 1；总分阶段按在场集合归一（缺席维度
  自动从分母剔除），再经置信度收缩得到总分。
"""

import time
import json
import logging
import threading
import math
import hashlib
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any

from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessingOrchestrator, PreprocessedStatistics
from .chat_positivity_service import ChatPositivityService
from .preference_compatibility_service import PreferenceCompatibilityService
from .emotional_resonance_service import EmotionalResonanceService
from .attitude_tendency_service import AttitudeTendencyService
from .affinity_config import AffinityConfigService, AffinityConfig
from .affinity_debug_logger import affinity_debug_log

# 配置日志
logger = logging.getLogger(__name__)


class AnalysisCancelled(Exception):
    """分析被用户取消"""
    pass


@dataclass
class DimensionScore:
    """维度评分"""
    name: str = ""
    score: float = 0.0
    weight: float = 0.0
    weighted_score: float = 0.0
    interpretation: str = ""
    sub_scores: Dict[str, float] = field(default_factory=dict)
    bonus_scores: Dict[str, float] = field(default_factory=dict)
    confidence_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AffinityAnalysisResult:
    """好感度分析结果"""
    
    # 综合评分 (0-100)
    overall_score: float = 0.0
    overall_interpretation: str = ""
    
    # 4个维度评分
    emotional_resonance: Optional[DimensionScore] = None
    chat_positivity: Optional[DimensionScore] = None
    attitude_tendency: Optional[DimensionScore] = None
    preference_compatibility: Optional[DimensionScore] = None
    intimacy_signals: Optional[DimensionScore] = None
    llm_relationship: Optional[DimensionScore] = None
    llm_relationship_absent_reason: Optional[str] = None
    
    # 元数据
    conversation_id: int = 0
    analysis_timestamp: int = 0
    analysis_duration_ms: int = 0
    task_id: str = ""
    cache_version: int = 0
    cache_updated_at: int = 0
    analysis_caliber: int = 0
    
    # 状态
    status: str = "pending"  # pending, running, completed, failed
    progress_percent: int = 0
    current_step: str = ""
    error: Optional[str] = None


class AffinityAnalysisService:
    """好感度分析编排器"""

    CACHE_SCHEMA_VERSION = 12
    # 口径版本：评分口径结构性变化时 +1（落历史行与缓存，跨口径趋势不可比）
    CALIBER_VERSION = 4
    NEUTRAL_OVERALL_BASELINE = 35.0
    OVERALL_SESSION_CONFIDENCE_TARGET = 30
    OVERALL_ACTIVE_DAY_CONFIDENCE_TARGET = 30
    OVERALL_MESSAGE_CONFIDENCE_TARGET = 400
    OVERALL_CONTACT_INITIATION_TARGET = 12
    CONFIDENCE_SHRINKAGE_POWER = 1.5
    SCORE_SIGMOID_MIDPOINT = 55.0
    SCORE_SIGMOID_STEEPNESS = 0.07
    PREFERENCE_BONUS_FACTOR = 0.10
    
    def __init__(self):
        pass  # get_db() removed for thread safety

        # 初始化所有服务
        self.preprocessing = PreprocessingOrchestrator()
        self.config_service = AffinityConfigService()
        self.resonance_service = EmotionalResonanceService()
        self.positivity_service = ChatPositivityService()
        self.attitude_service = AttitudeTendencyService()
        self.preference_service = PreferenceCompatibilityService()
        from .intimacy_signals_service import IntimacySignalsService
        self.intimacy_service = IntimacySignalsService()

        # 任务状态存储
        self._task_status: Dict[str, AffinityAnalysisResult] = {}
    
    def register_task(self, task_id: str, conversation_id: int) -> AffinityAnalysisResult:
        """预注册任务状态，供调用方在启动后台线程前就能用该 task_id 查询进度。

        analyze() 处理传入的 task_id 时会覆盖同键条目，因此预注册不会残留脏状态。
        """
        result = AffinityAnalysisResult()
        result.conversation_id = conversation_id
        result.task_id = task_id
        result.cache_version = self.CACHE_SCHEMA_VERSION
        result.status = "running"
        result.current_step = "初始化"
        self._task_status[task_id] = result
        return result

    def find_running_task(self, conversation_id: int) -> Optional[str]:
        """返回该会话仍在进行中的任务 ID（重复启动时复用，防取消事件被替换）。"""
        for task_id, result in self._task_status.items():
            if result.conversation_id != conversation_id:
                continue
            if result.status not in {"completed", "failed", "cancelled"}:
                return task_id
        return None

    def analyze(
        self,
        conversation_id: int,
        force_reanalyze: bool = False,
        config_overrides: Optional[Dict[str, Any]] = None,
        cancel_event: Optional[threading.Event] = None,
        task_id: Optional[str] = None
    ) -> AffinityAnalysisResult:
        """
        主入口 - 触发完整分析流程

        Args:
            conversation_id: 会话 ID
            force_reanalyze: 是否强制重新分析
            config_overrides: 配置覆盖
            cancel_event: 取消事件
            task_id: 显式任务 ID（优先使用）；None 时保持原有按时间生成逻辑

        Returns:
            AffinityAnalysisResult: 分析结果
        """
        start_time = time.time()

        # 生成任务 ID（优先使用调用方显式传入的 task_id，避免按秒生成撞号或前后端猜测不一致）
        if not task_id:
            task_id = f"affinity_{conversation_id}_{int(start_time)}"
        
        # 初始化结果
        result = AffinityAnalysisResult()
        result.conversation_id = conversation_id
        result.task_id = task_id
        result.cache_version = self.CACHE_SCHEMA_VERSION
        result.status = "running"
        result.current_step = "初始化"
        
        self._task_status[task_id] = result
        
        try:
            if force_reanalyze:
                logger.info(f"[好感度分析] 强制重算，先删除旧缓存 (会话 {conversation_id})")
                self._invalidate_cache(conversation_id)
            # 1. 检查缓存
            if not force_reanalyze:
                cached = self._load_cached_scores(conversation_id)
                if cached:
                    cached.task_id = task_id
                    cached.conversation_id = conversation_id
                    cached.status = "completed"
                    cached.progress_percent = 100
                    cached.current_step = "完成"
                    self._task_status[task_id] = cached
                    logger.info(f"使用缓存的分析结果 (会话 {conversation_id})")
                    return cached
            
            # 2. 加载配置
            result.current_step = "加载配置"
            self._check_cancelled(cancel_event)
            result.progress_percent = 10
            logger.info("[好感度分析] 步骤 1/5: 加载配置...")
            config = self._load_config(conversation_id, config_overrides)
            
            # 3. 执行预处理
            result.current_step = "预处理数据"
            self._check_cancelled(cancel_event)
            result.progress_percent = 20
            logger.info("[好感度分析] 步骤 2/5: 预处理数据 (这可能需要较长时间)...")
            def _preprocess_progress(fraction: float) -> None:
                # 预处理阶段 20→40%：语义相似度嵌入真实进度（此前一跳 3 分钟）
                frac = min(1.0, max(0.0, fraction))
                result.progress_percent = 20 + int(20 * frac)
                result.current_step = f"预处理数据 (语义相似度 {int(frac * 100)}%)"
            stats = self._preprocess_conversation(
                conversation_id, force_reanalyze, cancel_event, _preprocess_progress
            )
            logger.info("[好感度分析] 步骤 2/5: 预处理完成")
            
            # 4. 计算各维度
            result.current_step = "计算维度评分"
            self._check_cancelled(cancel_event)
            result.progress_percent = 40
            logger.info("[好感度分析] 步骤 3/5: 计算四大维度评分...")
            self._calculate_all_dimensions(result, conversation_id, stats, config, cancel_event)
            
            # 5. 计算综合评分
            self._check_cancelled(cancel_event)
            result.current_step = "计算综合评分"
            result.progress_percent = 80
            logger.info("[好感度分析] 步骤 4/5: 计算综合评分...")
            self._calculate_overall_score(result, config)
            
            # 6. 生成解释
            result.overall_interpretation = self._generate_overall_interpretation(
                result.overall_score
            )
            
            # 完成
            result.status = "completed"
            self._check_cancelled(cancel_event)
            result.progress_percent = 100
            result.current_step = "完成"
            result.analysis_timestamp = int(time.time())
            result.analysis_duration_ms = int((time.time() - start_time) * 1000)
            result.cache_version = self.CACHE_SCHEMA_VERSION

            # 7. 保存结果
            logger.info("[好感度分析] 步骤 5/5: 保存结果...")
            self._save_results(conversation_id, result)

            # 全流程终点：清 stale + 快照消息集规模（此后 UI「待更新」消失）
            try:
                from .analysis_state import mark_analysis_complete

                mark_analysis_complete(conversation_id)
            except Exception as state_e:
                logger.debug("[分析状态] 完成标记跳过: %s", state_e)

            # 全面分析完成点：构建该联系人记忆索引。导入后默认冷构建
            # （不自动建），此处是主动构建入口——分析完成后用户预期记忆
            # 随即可用；联系人画像仍由用户在洞察页手动触发生成。
            try:
                from ...db.connection import get_db
                from ..realtime.rag.indexer import RagIndexQueue

                row = get_db().execute(
                    "SELECT account_wxid FROM conversations WHERE id = ? LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                if row and str(row["account_wxid"] or "").strip():
                    RagIndexQueue.enqueue(str(row["account_wxid"]), int(conversation_id))
            except Exception as rag_e:
                logger.debug("[分析完成] 记忆索引构建入队跳过: %s", rag_e)

            logger.info(
                f"好感度分析完成: {result.overall_score:.1f} 分, "
                f"耗时 {result.analysis_duration_ms}ms (会话 {conversation_id})"
            )
            
        except AnalysisCancelled:
            result.status = "cancelled"
            result.current_step = "已停止"
            result.error = "分析已被用户停止"
            logger.info(f"[好感度分析] 分析被中止 (会话 {conversation_id})")
        except Exception as e:
            if "取消" in str(e):
                result.status = "cancelled"
                result.current_step = "已停止"
                result.error = "分析已被用户停止"
                logger.info(f"[好感度分析] 分析被中止 (会话 {conversation_id})")
            else:
                result.status = "failed"
                result.error = str(e)
                logger.error(f"好感度分析失败: {e}", exc_info=True)
        
        # 添加调试日志
        logger.info("=== 好感度分析结果 ===")
        logger.info(f"总分: {result.overall_score:.1f}")
        if result.emotional_resonance:
            logger.info(f"情感共振率: score={result.emotional_resonance.score:.1f}, weight={result.emotional_resonance.weight}, weighted={result.emotional_resonance.weighted_score:.1f}")
        if result.chat_positivity:
            logger.info(f"聊天积极度: score={result.chat_positivity.score:.1f}, weight={result.chat_positivity.weight}, weighted={result.chat_positivity.weighted_score:.1f}")
        if result.attitude_tendency:
            logger.info(f"态度倾向: score={result.attitude_tendency.score:.1f}, weight={result.attitude_tendency.weight}, weighted={result.attitude_tendency.weighted_score:.1f}")
        if result.preference_compatibility:
            logger.info(f"喜好兼容度: score={result.preference_compatibility.score:.1f}, weight={result.preference_compatibility.weight}, weighted={result.preference_compatibility.weighted_score:.1f}")
        
        return result
    
    def get_scores(self, conversation_id: int) -> Optional[AffinityAnalysisResult]:
        """
        获取缓存的分析结果
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            AffinityAnalysisResult 或 None
        """
        return self._load_cached_scores(conversation_id)
    
    def reanalyze(self, conversation_id: int) -> AffinityAnalysisResult:
        """
        重新分析（清除缓存）
        
        Args:
            conversation_id: 会话 ID
            
        Returns:
            AffinityAnalysisResult: 分析结果
        """
        logger.info(f"[好感度分析] 开始重新分析会话 {conversation_id}，准备清理缓存...")

        # 清除预处理缓存
        self.preprocessing.invalidate_cache(conversation_id)
        
        # 清除分析结果缓存
        self.preprocessing.invalidate_cache(conversation_id)
        self._invalidate_cache(conversation_id)
        logger.info(f"[好感度分析] 缓存清理完成，开始重新计算 (会话 {conversation_id})")
        
        # 重新分析
        return self.analyze(conversation_id, force_reanalyze=True)
    
    def get_progress(self, task_id: str) -> Optional[AffinityAnalysisResult]:
        """
        获取任务进度
        
        Args:
            task_id: 任务 ID
            
        Returns:
            AffinityAnalysisResult 或 None
        """
        return self._task_status.get(task_id)
    
    # ========================================
    # 内部方法
    # ========================================
    
    def _load_config(
        self,
        conversation_id: int,
        overrides: Optional[Dict[str, Any]] = None
    ) -> AffinityConfig:
        """加载配置"""
        config = self.config_service.get_config(conversation_id)
        
        if overrides:
            for key, value in overrides.items():
                if hasattr(config, key):
                    setattr(config, key, value)
        
        return config
    
    def _preprocess_conversation(
        self,
        conversation_id: int,
        force_reprocess: bool = False,
        cancel_event: Optional[threading.Event] = None,
        progress_cb=None,
    ) -> PreprocessedStatistics:
        """执行预处理"""
        return self.preprocessing.orchestrate_preprocessing(
            conversation_id, force_reprocess, cancel_event, progress_cb=progress_cb
        )
    

    def _check_cancelled(self, cancel_event: Optional[threading.Event]):
        """检查取消信号"""
        if cancel_event and cancel_event.is_set():
            raise AnalysisCancelled("分析已被用户取消")

    def _calculate_all_dimensions(
        self,
        result: AffinityAnalysisResult,
        conversation_id: int,
        stats: PreprocessedStatistics,
        config: AffinityConfig,
        cancel_event: Optional[threading.Event] = None
    ):
        """计算所有维度评分"""

        # 解析六维权重计划（config 覆盖默认；缺席维度 declared 置 0）。
        # LLM 维可用性 = 激活模型存在（构造不发起网络调用；真正的调用
        # 失败在维度计算期按缺席处理，归一时自动剔除）
        from .affinity_weights import resolve_dimension_plan
        from .relationship_llm_service import (
            RelationshipLLMAbsent,
            build_relationship_llm_service,
        )
        # probe 容错：测试/异常环境下构建失败按"无 LLM"处理，不影响主流程
        try:
            llm_service = build_relationship_llm_service()
        except Exception as probe_e:
            logger.debug("[关系评估] 服务构建失败按缺席处理: %s", probe_e)
            llm_service = None
        plan = resolve_dimension_plan(config, llm_available=llm_service is not None)
        logger.info(
            "维度权重计划: %s",
            {k: (v["declared"] if v["enabled"] else 0.0) for k, v in plan.items()},
        )
        weights = {
            key: (entry["declared"] if entry["enabled"] else 0.0)
            for key, entry in plan.items()
        }
        
        # 1. 情感共振率
        self._check_cancelled(cancel_event)
        result.progress_percent = 45
        result.progress_percent = 45
        result.current_step = "计算维度评分: 情感共振率"
        logger.info("[好感度分析] 维度 1/4: 情感共振率...")
        resonance_result = self.resonance_service.calculate_overall_resonance(
            conversation_id
        )
        result.emotional_resonance = DimensionScore(
            name="情感共振率",
            score=resonance_result['overall_score'],
            weight=weights['emotional_resonance'],
            weighted_score=resonance_result['overall_score'] * weights['emotional_resonance'],
            interpretation=resonance_result['interpretation'],
            sub_scores={
                "bidirectional_positive": resonance_result['sub_scores']['bidirectional_positive_response'],
                "polarity_consistency": resonance_result['sub_scores']['polarity_consistency'],
                "intensity_matching": resonance_result['sub_scores']['intensity_matching'],
                "empathy_recognition": resonance_result['sub_scores']['empathy_recognition'],
                "negative_resolution": resonance_result['sub_scores']['negative_resolution'],
            },
            bonus_scores=resonance_result.get('bonus_scores', {}),
            confidence_meta=resonance_result.get('confidence_meta', {}),
        )
        logger.info(f"情感共振率计算完成: {resonance_result['overall_score']:.1f}分 (权重: {weights['emotional_resonance']*100}%)")
        
        # 2. 聊天积极度
        self._check_cancelled(cancel_event)
        result.progress_percent = 55
        result.progress_percent = 55
        result.current_step = "计算维度评分: 聊天积极度"
        logger.info("[好感度分析] 维度 2/4: 聊天积极度...")
        self.positivity_service.timeliness_threshold = config.reply_timeliness_threshold_seconds
        positivity_result = self.positivity_service.calculate_scores(
            conversation_id, stats
        )
        result.chat_positivity = DimensionScore(
            name="聊天积极度",
            score=positivity_result.overall_score,
            weight=weights['chat_positivity'],
            weighted_score=positivity_result.overall_score * weights['chat_positivity'],
            interpretation=positivity_result.interpretation,
            sub_scores={
                "daily_message": positivity_result.daily_message_score,
                "reply_timeliness": positivity_result.reply_timeliness_score,
                "topic_continuity": positivity_result.topic_continuity_score,
                "active_initiation": positivity_result.active_initiation_score,
            },
            bonus_scores={
                "long_text_bonus": positivity_result.long_text_bonus
            }
        )
        logger.info(f"聊天积极度计算完成: {positivity_result.overall_score:.1f}分 (权重: {weights['chat_positivity']*100}%)")
        
        # 3. 态度倾向
        self._check_cancelled(cancel_event)
        result.progress_percent = 65
        result.progress_percent = 65
        result.current_step = "计算维度评分: 态度倾向"
        logger.info("[好感度分析] 维度 3/4: 态度倾向...")
        attitude_result = self.attitude_service.calculate_overall_attitude(
            conversation_id
        )
        result.attitude_tendency = DimensionScore(
            name="态度倾向",
            score=attitude_result['overall_score'],
            weight=weights['attitude_tendency'],
            weighted_score=attitude_result['overall_score'] * weights['attitude_tendency'],
            interpretation=attitude_result['interpretation'],
            sub_scores={
                "positive_emotion_frequency": attitude_result['sub_scores']['positive_emotion_frequency'],
                "negative_emotion_frequency": attitude_result['sub_scores']['negative_emotion_frequency'],
            },
            bonus_scores=attitude_result.get('bonus_scores', {})
        )
        logger.info(f"态度倾向计算完成: {attitude_result['overall_score']:.1f}分 (权重: {weights['attitude_tendency']*100}%)")
        
        # 4. 喜好兼容度
        self._check_cancelled(cancel_event)
        result.progress_percent = 75
        result.progress_percent = 75
        result.current_step = "计算维度评分: 喜好兼容度"
        logger.info("[好感度分析] 维度 4/4: 喜好兼容度...")
        self.preference_service.set_preference_keywords(config.preference_keywords)
        preference_result = self.preference_service.calculate_scores(
            conversation_id, stats
        )
        raw_bonus = (
            preference_result.overall_score
            * getattr(config, "preference_bonus_factor", self.PREFERENCE_BONUS_FACTOR)
        )
        result.preference_compatibility = DimensionScore(
            name="喜好兼容度",
            score=preference_result.overall_score,
            weight=weights['preference_compatibility'],
            weighted_score=preference_result.overall_score * weights['preference_compatibility'],
            interpretation=preference_result.interpretation,
            sub_scores={
                "topic_mention": preference_result.topic_mention_score,
                "topic_continuity": preference_result.topic_continuity_score,
            },
            bonus_scores={
                "preference_bonus": round(raw_bonus, 2),
            }
        )
        logger.info(
            "喜好兼容度计算完成: %.1f分 (raw_bonus=%.2f)",
            preference_result.overall_score,
            raw_bonus,
        )

        # 5. 亲密度信号（称谓演变/时段投入/回复对称性）
        self._check_cancelled(cancel_event)
        result.progress_percent = 77
        result.current_step = "计算维度评分: 亲密度信号"
        logger.info("[好感度分析] 维度 5/6: 亲密度信号...")
        intimacy_result = self.intimacy_service.calculate_overall_intimacy(
            conversation_id,
            stats,
            long_text_threshold=int(getattr(config, "long_text_threshold", 100)),
        )
        result.intimacy_signals = DimensionScore(
            name="亲密度信号",
            score=intimacy_result['overall_score'],
            weight=weights['intimacy_signals'],
            weighted_score=intimacy_result['overall_score'] * weights['intimacy_signals'],
            interpretation=intimacy_result['interpretation'],
            sub_scores=intimacy_result['sub_scores'],
            confidence_meta=intimacy_result.get('confidence_meta', {}),
        )
        logger.info(
            "亲密度信号计算完成: %.1f分 (权重: %.1f%%)",
            intimacy_result['overall_score'],
            weights['intimacy_signals'] * 100,
        )

        # 6. LLM 关系评估（缺席不阻断：权重归一自动剔除该维）
        if llm_service is not None and weights.get('llm_relationship', 0.0) > 0:
            self._check_cancelled(cancel_event)
            result.progress_percent = 79
            result.current_step = "LLM 关系评估（可能需要约1分钟）"
            logger.info("[好感度分析] 维度 6/6: LLM 关系评估...")
            try:
                context: Dict[str, str] = {}
                try:
                    from .relationship_context_service import RelationshipContextService
                    ctx_obj = RelationshipContextService().get_context(conversation_id)
                    if ctx_obj is not None:
                        context = {
                            "relationship_type": str(getattr(ctx_obj, "relationship_type", "") or ""),
                            "interaction_duration": str(getattr(ctx_obj, "interaction_duration", "") or ""),
                            "communication_style": str(getattr(ctx_obj, "communication_style", "") or ""),
                        }
                except Exception as ctx_e:
                    logger.debug("[关系评估] 关系背景读取跳过: %s", ctx_e)
                llm_result = llm_service.evaluate(
                    conversation_id,
                    account_wxid=str(getattr(config, "_account_wxid", "") or ""),
                    context=context,
                )
                confidence_meta = dict(llm_result.get("meta") or {})
                confidence_meta["evidence"] = llm_result.get("evidence") or []
                result.llm_relationship = DimensionScore(
                    name="AI 关系评估",
                    score=llm_result['score'],
                    weight=weights['llm_relationship'],
                    weighted_score=llm_result['score'] * weights['llm_relationship'],
                    interpretation=llm_result.get('insight') or "LLM 关系评估完成",
                    sub_scores=llm_result['sub_scores'],
                    confidence_meta=confidence_meta,
                )
                logger.info(
                    "LLM 关系评估完成: %.1f分 (模型: %s)",
                    llm_result['score'],
                    (llm_result.get("meta") or {}).get("model_name", ""),
                )
            except RelationshipLLMAbsent as absent:
                result.llm_relationship = None
                result.llm_relationship_absent_reason = str(absent)
                logger.info("[关系评估] 缺席: %s", absent)
        else:
            if llm_service is None:
                result.llm_relationship_absent_reason = "未配置 LLM 模型"
    
    def _calculate_overall_score(
        self,
        result: AffinityAnalysisResult,
        config: AffinityConfig
    ):
        # 权重归一：在场维度（declared>0 且结果非 None）按点数归一，
        # 覆写各维 weight/weighted_score——LLM 维缺席在此自动剔除
        from .affinity_weights import apply_weight_normalization
        effective_weights = apply_weight_normalization(result)

        base_score = 0.0
        for dim_key in (
            "emotional_resonance",
            "chat_positivity",
            "attitude_tendency",
            "preference_compatibility",
            "intimacy_signals",
            "llm_relationship",
        ):
            dim = getattr(result, dim_key, None)
            if dim:
                base_score += dim.weighted_score

        stats = self.preprocessing.get_preprocessed_statistics(result.conversation_id)
        relationship_stability_confidence = self._calculate_relationship_stability_confidence(stats)
        shrunk_score = self._apply_confidence_shrinkage(
            base_score,
            relationship_stability_confidence,
            self.NEUTRAL_OVERALL_BASELINE,
        )
        # 去掉 sigmoid 校准（双重压缩根因）：置信度收缩已是唯一保守化步骤
        # 此前 60.8 → 收缩39 → sigmoid25 的管线与维度分严重不一致
        result.overall_score = round(max(0.0, min(100.0, shrunk_score)), 2)
        logger.info(
            "综合评分计算完成: %.1f分 (base=%.1f, confidence=%.2f, effective_weights=%s)",
            result.overall_score,
            base_score,
            relationship_stability_confidence,
            {k: round(v, 3) for k, v in effective_weights.items()},
        )
        affinity_debug_log(
            "[Affinity Overall] "
            f"base={base_score:.2f}, "
            f"shrunk={shrunk_score:.2f}, "
            f"total={result.overall_score:.2f}, "
            f"confidence={relationship_stability_confidence:.2f}, "
            f"weights={ {k: round(v, 3) for k, v in effective_weights.items()} }"
        )
        self._log_debug_summary(result)
        return

    def _calculate_relationship_stability_confidence(
        self, stats: PreprocessedStatistics
    ) -> float:
        session_confidence = min(
            1.0, (stats.total_sessions or 0) / self.OVERALL_SESSION_CONFIDENCE_TARGET
        )
        active_day_confidence = min(
            1.0, (stats.chat_days_count or 0) / self.OVERALL_ACTIVE_DAY_CONFIDENCE_TARGET
        )
        message_confidence = min(
            1.0, (stats.total_message_count or 0) / self.OVERALL_MESSAGE_CONFIDENCE_TARGET
        )
        contact_initiation_confidence = min(
            1.0,
            (stats.contact_initiated_count or 0) / self.OVERALL_CONTACT_INITIATION_TARGET,
        )
        confidence = (
            session_confidence * 0.35
            + active_day_confidence * 0.35
            + message_confidence * 0.20
            + contact_initiation_confidence * 0.10
        )
        affinity_debug_log(
            "[好感度分析] 关系稳定性收缩: "
            f"sessions={stats.total_sessions}, active_days={stats.chat_days_count}, "
            f"messages={stats.total_message_count}, contact_initiated={stats.contact_initiated_count}, "
            f"confidence={confidence:.2f}"
        )
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _apply_confidence_shrinkage(
        raw_score: float, confidence: float, neutral_score: float
    ) -> float:
        effective_confidence = (
            max(0.0, min(1.0, confidence))
            ** AffinityAnalysisService.CONFIDENCE_SHRINKAGE_POWER
        )
        adjusted = raw_score * effective_confidence + neutral_score * (1 - effective_confidence)
        return max(0.0, min(100.0, adjusted))

    @classmethod
    def _sigmoid_calibrate(cls, raw_score: float) -> float:
        x = (raw_score - cls.SCORE_SIGMOID_MIDPOINT) * cls.SCORE_SIGMOID_STEEPNESS
        sigmoid = 1.0 / (1.0 + math.exp(-x))
        return round(max(0.0, min(100.0, sigmoid * 100.0)), 2)
        
    def _log_debug_summary(self, result: AffinityAnalysisResult):
        """将好感度四大维度的详细得分输出到独立的物理日志文件"""
        affinity_debug_log(f"\n{'='*80}")
        affinity_debug_log(f"好感度分析结果汇总 (总分: {result.overall_score:.2f})")
        affinity_debug_log(f"{'='*80}")
        
        dimensions = [
            result.emotional_resonance,
            result.chat_positivity,
            result.attitude_tendency,
            result.preference_compatibility,
        ]
        
        for dim in dimensions:
            if not dim:
                continue
            if dim is result.preference_compatibility:
                affinity_debug_log(
                    f"[加分项] {dim.name}: 原始分 {dim.score:.2f} | "
                    f"额外加分 +{dim.bonus_scores.get('preference_bonus', 0):.2f}"
                )
            else:
                affinity_debug_log(
                    f"[维度] {dim.name}: {dim.score:.2f}分 | "
                    f"权重: {dim.weight*100:.0f}% -> 最终贡献: {dim.weighted_score:.2f}分"
                )
            
            # 输出子维度
            if dim.sub_scores:
                affinity_debug_log("  ├─ [基础维度详情]")
                for sub_key, sub_val in dim.sub_scores.items():
                    if isinstance(sub_val, (int, float)):
                        affinity_debug_log(f"  │  ├─ {sub_key}: {sub_val:.2f}")
                    else:
                        affinity_debug_log(f"  │  ├─ {sub_key}: {sub_val}")
                        
            # 输出附加加分项
            if hasattr(dim, 'bonus_scores') and dim.bonus_scores:
                affinity_debug_log("  ├─ [额外加分详情]")
                for sub_key, sub_val in dim.bonus_scores.items():
                    if isinstance(sub_val, (int, float)):
                        affinity_debug_log(f"  │  ├─ {sub_key}: +{sub_val:.2f}")
                    else:
                        affinity_debug_log(f"  │  ├─ {sub_key}: +{sub_val}")
            
            # 输出解释
            affinity_debug_log(f"  └─ [解释]: {dim.interpretation}\n")
            
        affinity_debug_log(f"{'='*80}\n")
    
    def _generate_overall_interpretation(self, score: float) -> str:
        """生成综合解释（区间按去掉 sigmoid 后的新分数分布调整）"""
        if score >= 75:
            return "总体好感度非常高，对方对这段关系非常重视，表现出强烈的情感投入"
        elif score >= 60:
            return "总体好感度较高，对方对这段关系较为重视，愿意投入时间和精力"
        elif score >= 45:
            return "总体好感度中等，对方有基本好感，关系有发展空间"
        elif score >= 35:
            return "总体好感度一般，对方态度较为平淡，可能需要更多互动来培养感情"
        elif score >= 25:
            return "总体好感度较低，对方可能兴趣不大，建议观察更多互动信号"
        else:
            return "总体好感度很低，对方可能对这段关系不太感兴趣"
    
    def _config_fingerprint(self, conversation_id: int) -> str:
        """计算影响评分的配置指纹（sha1 前 12 位），用于结果缓存失效判定。

        覆盖会改变四维得分的配置项：喜好关键词、回复及时阈值、喜好加分系数，
        以及其余参与各维度计算的调优参数。用户改配置后指纹变化，旧缓存即视为脏数据。
        config_service 不可用（如测试中未经 __init__ 构造）时退化为默认配置指纹。
        """
        config_service = getattr(self, "config_service", None)
        try:
            config = (
                config_service.get_config(conversation_id)
                if config_service is not None
                else AffinityConfig()
            )
        except Exception as e:
            logger.warning(f"读取好感度配置失败，配置指纹退化为默认配置: {e}")
            config = AffinityConfig()

        # 不含 conversation_id / updated_at 等元数据。权重参与计分，
        # 必须入指纹（改权重后旧缓存失效自动重算）；新增影响分数的
        # 配置项必须同步登记到这里
        fingerprint_payload = json.dumps({
            "preference_keywords": sorted(config.preference_keywords or []),
            "reply_timeliness_threshold_seconds": config.reply_timeliness_threshold_seconds,
            "preference_bonus_factor": config.preference_bonus_factor,
            "topic_continuity_window_days": config.topic_continuity_window_days,
            "similarity_threshold": config.similarity_threshold,
            "sliding_window_size": config.sliding_window_size,
            "long_text_threshold": config.long_text_threshold,
            "weight_emotional_resonance": config.weight_emotional_resonance,
            "weight_chat_positivity": config.weight_chat_positivity,
            "weight_attitude_tendency": config.weight_attitude_tendency,
            "weight_preference_compatibility": config.weight_preference_compatibility,
            "weight_intimacy_signals": config.weight_intimacy_signals,
            "weight_llm_relationship": config.weight_llm_relationship,
            "llm_relationship_enabled": bool(config.llm_relationship_enabled),
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(fingerprint_payload.encode("utf-8")).hexdigest()[:12]

    def _save_results(self, conversation_id: int, result: AffinityAnalysisResult):
        """保存分析结果到数据库"""
        try:
            cache_updated_at = int(time.time())
            result.cache_version = self.CACHE_SCHEMA_VERSION
            result.cache_updated_at = cache_updated_at
            result.analysis_caliber = self.CALIBER_VERSION

            # 记录生成结果时的配置指纹，读取时校验，配置变更后旧缓存失效
            config_fingerprint = self._config_fingerprint(conversation_id)

            # 序列化结果
            result_dict = {
                "overall_score": result.overall_score,
                "overall_interpretation": result.overall_interpretation,
                "emotional_resonance": asdict(result.emotional_resonance) if result.emotional_resonance else None,
                "chat_positivity": asdict(result.chat_positivity) if result.chat_positivity else None,
                "attitude_tendency": asdict(result.attitude_tendency) if result.attitude_tendency else None,
                "preference_compatibility": asdict(result.preference_compatibility) if result.preference_compatibility else None,
                "intimacy_signals": asdict(result.intimacy_signals) if result.intimacy_signals else None,
                "llm_relationship": asdict(result.llm_relationship) if result.llm_relationship else None,
                "llm_relationship_absent_reason": result.llm_relationship_absent_reason,
                "conversation_id": result.conversation_id,
                "analysis_timestamp": result.analysis_timestamp,
                "analysis_duration_ms": result.analysis_duration_ms,
                "task_id": result.task_id,
                "status": result.status,
                "cache_version": result.cache_version,
                "cache_updated_at": result.cache_updated_at,
                "analysis_caliber": self.CALIBER_VERSION,
                "config_fingerprint": config_fingerprint,
            }
            
            result_json = json.dumps(result_dict, ensure_ascii=False)
            key = f"affinity_scores_{conversation_id}"
            
            get_db().execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, result_json, cache_updated_at))
            
            get_db().commit()
            logger.debug(f"分析结果已保存 (会话 {conversation_id})")

            # 历史分数落库（只增不删；失败不影响主流程）
            try:
                from .affinity_history import record_score_history

                stats = self.preprocessing.get_preprocessed_statistics(conversation_id)
                record_score_history(
                    conversation_id,
                    result,
                    stats=stats,
                    config_snapshot={"config_fingerprint": config_fingerprint},
                )
            except Exception as hist_e:
                logger.debug(f"[历史分数] 落库跳过: {hist_e}")

        except Exception as e:
            logger.error(f"保存分析结果失败: {e}")
    
    def _load_cached_scores(
        self,
        conversation_id: int
    ) -> Optional[AffinityAnalysisResult]:
        """从缓存加载分析结果"""
        try:
            key = f"affinity_scores_{conversation_id}"
            cursor = get_db().execute("""
                SELECT value, updated_at FROM settings WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            result_dict = json.loads(row[0])

            # 只信任已完成的缓存结果，避免把运行中的半成品展示给前端
            if result_dict.get("status") != "completed":
                logger.info(f"忽略未完成的好感度缓存结果 (会话 {conversation_id})")
                return None

            if result_dict.get("cache_version") != self.CACHE_SCHEMA_VERSION:
                logger.info(
                    f"忽略过期的好感度缓存结果 "
                    f"(会话 {conversation_id}, version={result_dict.get('cache_version')}, "
                    f"expected={self.CACHE_SCHEMA_VERSION})"
                )
                return None

            # 校验配置指纹：配置（喜好关键词/阈值/加分系数等）变更后旧缓存视为失效
            # （不含指纹字段的历史缓存同样视为失效）
            cached_fingerprint = result_dict.get("config_fingerprint")
            expected_fingerprint = self._config_fingerprint(conversation_id)
            if cached_fingerprint != expected_fingerprint:
                logger.info(
                    f"忽略配置已变更的好感度缓存结果 "
                    f"(会话 {conversation_id}, fingerprint={cached_fingerprint}, "
                    f"expected={expected_fingerprint})"
                )
                return None
            
            # 重建结果对象
            result = AffinityAnalysisResult()
            result.overall_score = result_dict.get("overall_score", 0.0)
            result.overall_interpretation = result_dict.get("overall_interpretation", "")
            result.conversation_id = result_dict.get("conversation_id", 0)
            result.analysis_timestamp = result_dict.get("analysis_timestamp", 0)
            result.analysis_duration_ms = result_dict.get("analysis_duration_ms", 0)
            result.task_id = result_dict.get("task_id", "")
            result.status = result_dict.get("status", "completed")
            result.cache_version = result_dict.get("cache_version", 0)
            result.cache_updated_at = result_dict.get("cache_updated_at", row[1] or 0)
            result.analysis_caliber = result_dict.get("analysis_caliber", 0)
            
            # 重建维度分数
            for dim_name in ["emotional_resonance", "chat_positivity",
                           "attitude_tendency", "preference_compatibility",
                           "intimacy_signals", "llm_relationship"]:
                dim_dict = result_dict.get(dim_name)
                if dim_dict:
                    dim = DimensionScore(**dim_dict)
                    setattr(result, dim_name, dim)
            result.llm_relationship_absent_reason = result_dict.get(
                "llm_relationship_absent_reason"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"加载缓存失败: {e}")
            return None
    
    def _invalidate_cache(self, conversation_id: int):
        """清除分析结果缓存"""
        try:
            key = f"affinity_scores_{conversation_id}"
            get_db().execute("""
                DELETE FROM settings WHERE key = ?
            """, (key,))
            get_db().commit()
            logger.debug(f"分析缓存已清除 (会话 {conversation_id})")
        except Exception as e:
            logger.error(f"清除缓存失败: {e}")
