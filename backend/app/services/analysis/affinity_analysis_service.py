"""好感度分析编排器 - 协调4个维度服务并计算综合评分

功能:
- analyze(): 主入口，触发完整分析流程
- get_scores(): 获取缓存分数
- reanalyze(): 重新分析（清除缓存）

维度权重(动态调整):
有喜好关键词时:
- 情感共振率: 35%
- 聊天积极度: 35%
- 态度倾向: 20%
- 喜好兼容度: 10%

无喜好关键词时:
- 情感共振率: 40%
- 聊天积极度: 35%
- 态度倾向: 25%
- 喜好兼容度: 0%
"""

import time
import json
import logging
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any, List

from ...db.connection import get_db
from .preprocessing_orchestrator import PreprocessingOrchestrator, PreprocessedStatistics
from .chat_positivity_service import ChatPositivityService, ChatPositivityResult
from .preference_compatibility_service import PreferenceCompatibilityService, PreferenceCompatibilityResult
from .emotional_resonance_service import EmotionalResonanceService
from .attitude_tendency_service import AttitudeTendencyService
from .affinity_config import AffinityConfigService, AffinityConfig
from .affinity_debug_logger import affinity_debug_log

# 配置日志
logger = logging.getLogger(__name__)


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
    
    # 元数据
    conversation_id: int = 0
    analysis_timestamp: int = 0
    analysis_duration_ms: int = 0
    task_id: str = ""
    
    # 状态
    status: str = "pending"  # pending, running, completed, failed
    progress_percent: int = 0
    current_step: str = ""
    error: Optional[str] = None


class AffinityAnalysisService:
    """好感度分析编排器"""
    
    # 默认维度权重(已废弃,使用动态权重)
    # 实际权重由 AffinityConfigService.get_dimension_weights() 动态返回
    DEFAULT_WEIGHT_EMOTIONAL = 0.35
    DEFAULT_WEIGHT_POSITIVITY = 0.35
    DEFAULT_WEIGHT_ATTITUDE = 0.20
    DEFAULT_WEIGHT_PREFERENCE = 0.10
    
    def __init__(self):
        pass  # get_db() removed for thread safety

        # 初始化所有服务
        self.preprocessing = PreprocessingOrchestrator()
        self.config_service = AffinityConfigService()
        self.resonance_service = EmotionalResonanceService()
        self.positivity_service = ChatPositivityService()
        self.attitude_service = AttitudeTendencyService()
        self.preference_service = PreferenceCompatibilityService()

        # 任务状态存储
        self._task_status: Dict[str, AffinityAnalysisResult] = {}
    
    def analyze(
        self,
        conversation_id: int,
        force_reanalyze: bool = False,
        config_overrides: Optional[Dict[str, Any]] = None
    ) -> AffinityAnalysisResult:
        """
        主入口 - 触发完整分析流程
        
        Args:
            conversation_id: 会话 ID
            force_reanalyze: 是否强制重新分析
            config_overrides: 配置覆盖
            
        Returns:
            AffinityAnalysisResult: 分析结果
        """
        start_time = time.time()
        
        # 生成任务 ID
        task_id = f"affinity_{conversation_id}_{int(start_time)}"
        
        # 初始化结果
        result = AffinityAnalysisResult()
        result.conversation_id = conversation_id
        result.task_id = task_id
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
            result.progress_percent = 10
            logger.info(f"[好感度分析] 步骤 1/5: 加载配置...")
            config = self._load_config(conversation_id, config_overrides)
            
            # 3. 执行预处理
            result.current_step = "预处理数据"
            result.progress_percent = 20
            logger.info(f"[好感度分析] 步骤 2/5: 预处理数据 (这可能需要较长时间)...")
            stats = self._preprocess_conversation(conversation_id, force_reanalyze)
            logger.info(f"[好感度分析] 步骤 2/5: 预处理完成")
            
            # 4. 计算各维度
            result.current_step = "计算维度评分"
            result.progress_percent = 40
            logger.info(f"[好感度分析] 步骤 3/5: 计算四大维度评分...")
            self._calculate_all_dimensions(result, conversation_id, stats, config)
            
            # 5. 计算综合评分
            result.current_step = "计算综合评分"
            result.progress_percent = 80
            logger.info(f"[好感度分析] 步骤 4/5: 计算综合评分...")
            self._calculate_overall_score(result, config)
            
            # 6. 生成解释
            result.overall_interpretation = self._generate_overall_interpretation(
                result.overall_score
            )
            
            # 7. 保存结果
            result.current_step = "保存结果"
            result.progress_percent = 90
            logger.info(f"[好感度分析] 步骤 5/5: 保存结果...")
            self._save_results(conversation_id, result)
            
            # 完成
            result.status = "completed"
            result.progress_percent = 100
            result.current_step = "完成"
            result.analysis_timestamp = int(time.time())
            result.analysis_duration_ms = int((time.time() - start_time) * 1000)
            
            logger.info(
                f"好感度分析完成: {result.overall_score:.1f} 分, "
                f"耗时 {result.analysis_duration_ms}ms (会话 {conversation_id})"
            )
            
        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.error(f"好感度分析失败: {e}", exc_info=True)
        
        # 添加调试日志
        logger.info(f"=== 好感度分析结果 ===")
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
        force_reprocess: bool = False
    ) -> PreprocessedStatistics:
        """执行预处理"""
        return self.preprocessing.orchestrate_preprocessing(
            conversation_id, force_reprocess
        )
    
    def _calculate_all_dimensions(
        self,
        result: AffinityAnalysisResult,
        conversation_id: int,
        stats: PreprocessedStatistics,
        config: AffinityConfig
    ):
        """计算所有维度评分"""
        
        # 获取动态权重
        weights = self.config_service.get_dimension_weights(conversation_id)
        logger.info(f"使用动态权重: {weights}")
        
        # 1. 情感共振率
        result.progress_percent = 45
        result.progress_percent = 45
        result.current_step = "计算维度评分: 情感共振率"
        logger.info(f"[好感度分析] 维度 1/4: 情感共振率...")
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
            }
        )
        logger.info(f"情感共振率计算完成: {resonance_result['overall_score']:.1f}分 (权重: {weights['emotional_resonance']*100}%)")
        
        # 2. 聊天积极度
        result.progress_percent = 55
        result.progress_percent = 55
        result.current_step = "计算维度评分: 聊天积极度"
        logger.info(f"[好感度分析] 维度 2/4: 聊天积极度...")
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
        result.progress_percent = 65
        result.progress_percent = 65
        result.current_step = "计算维度评分: 态度倾向"
        logger.info(f"[好感度分析] 维度 3/4: 态度倾向...")
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
        result.progress_percent = 75
        result.progress_percent = 75
        result.current_step = "计算维度评分: 喜好兼容度"
        logger.info(f"[好感度分析] 维度 4/4: 喜好兼容度...")
        self.preference_service.set_preference_keywords(config.preference_keywords)
        preference_result = self.preference_service.calculate_scores(
            conversation_id, stats
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
            }
        )
        logger.info(f"喜好兼容度计算完成: {preference_result.overall_score:.1f}分 (权重: {weights['preference_compatibility']*100}%)")
    
    def _calculate_overall_score(
        self,
        result: AffinityAnalysisResult,
        config: AffinityConfig
    ):
        """计算综合评分(使用动态权重)"""
        # 收集所有维度的加权分数
        total_weighted = 0.0
        
        dimensions = [
            result.emotional_resonance,
            result.chat_positivity,
            result.attitude_tendency,
            result.preference_compatibility,
        ]
        
        # 直接累加加权分数(权重已在维度计算时设置)
        for dim in dimensions:
            if dim:
                total_weighted += dim.weighted_score
        
        result.overall_score = round(total_weighted, 2)
        logger.info(f"综合评分计算完成: {result.overall_score:.1f}分")
        
        # 统一输出四大维度的明细日志到文件
        self._log_debug_summary(result)
        
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
            affinity_debug_log(f"► 【{dim.name}】: {dim.score:.2f}分 | 权重: {dim.weight*100:.0f}% -> 最终贡献: {dim.weighted_score:.2f}分")
            
            # 输出子维度
            if dim.sub_scores:
                affinity_debug_log(f"  ├─ [基础维度详情]")
                for sub_key, sub_val in dim.sub_scores.items():
                    if isinstance(sub_val, (int, float)):
                        affinity_debug_log(f"  │  ├─ {sub_key}: {sub_val:.2f}")
                    else:
                        affinity_debug_log(f"  │  ├─ {sub_key}: {sub_val}")
                        
            # 输出附加加分项
            if hasattr(dim, 'bonus_scores') and dim.bonus_scores:
                affinity_debug_log(f"  ├─ [额外加分详情 (已计算入该维度得分)]")
                for sub_key, sub_val in dim.bonus_scores.items():
                    if isinstance(sub_val, (int, float)):
                        affinity_debug_log(f"  │  ├─ {sub_key}: +{sub_val:.2f}")
                    else:
                        affinity_debug_log(f"  │  ├─ {sub_key}: +{sub_val}")
            
            # 输出解释
            affinity_debug_log(f"  └─ [解释]: {dim.interpretation}\n")
            
        affinity_debug_log(f"{'='*80}\n")
    
    def _generate_overall_interpretation(self, score: float) -> str:
        """生成综合解释"""
        if score >= 80:
            return "总体好感度非常高，对方对这段关系非常重视，表现出强烈的情感投入"
        elif score >= 60:
            return "总体好感度较高，对方对这段关系较为重视，愿意投入时间和精力"
        elif score >= 40:
            return "总体好感度一般，对方态度较为平淡，可能需要更多互动来培养感情"
        elif score >= 20:
            return "总体好感度较低，对方可能兴趣不大，建议观察更多互动信号"
        else:
            return "总体好感度很低，对方可能对这段关系不太感兴趣"
    
    def _save_results(self, conversation_id: int, result: AffinityAnalysisResult):
        """保存分析结果到数据库"""
        try:
            # 序列化结果
            result_dict = {
                "overall_score": result.overall_score,
                "overall_interpretation": result.overall_interpretation,
                "emotional_resonance": asdict(result.emotional_resonance) if result.emotional_resonance else None,
                "chat_positivity": asdict(result.chat_positivity) if result.chat_positivity else None,
                "attitude_tendency": asdict(result.attitude_tendency) if result.attitude_tendency else None,
                "preference_compatibility": asdict(result.preference_compatibility) if result.preference_compatibility else None,
                "conversation_id": result.conversation_id,
                "analysis_timestamp": result.analysis_timestamp,
                "analysis_duration_ms": result.analysis_duration_ms,
                "task_id": result.task_id,
                "status": result.status,
            }
            
            result_json = json.dumps(result_dict, ensure_ascii=False)
            key = f"affinity_scores_{conversation_id}"
            
            get_db().execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, result_json, int(time.time())))
            
            get_db().commit()
            logger.debug(f"分析结果已保存 (会话 {conversation_id})")
            
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
                SELECT value FROM settings WHERE key = ?
            """, (key,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            result_dict = json.loads(row[0])
            
            # 重建结果对象
            result = AffinityAnalysisResult()
            result.overall_score = result_dict.get("overall_score", 0.0)
            result.overall_interpretation = result_dict.get("overall_interpretation", "")
            result.conversation_id = result_dict.get("conversation_id", 0)
            result.analysis_timestamp = result_dict.get("analysis_timestamp", 0)
            result.analysis_duration_ms = result_dict.get("analysis_duration_ms", 0)
            result.task_id = result_dict.get("task_id", "")
            result.status = result_dict.get("status", "completed")
            
            # 重建维度分数
            for dim_name in ["emotional_resonance", "chat_positivity", 
                           "attitude_tendency", "preference_compatibility"]:
                dim_dict = result_dict.get(dim_name)
                if dim_dict:
                    dim = DimensionScore(**dim_dict)
                    setattr(result, dim_name, dim)
            
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
