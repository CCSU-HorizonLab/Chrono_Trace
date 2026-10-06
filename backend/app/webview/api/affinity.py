"""好感度分析（四维评分/关系上下文/偏好关键词）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


import importlib, uuid

class AffinityApiMixin:
    """好感度分析（四维评分/关系上下文/偏好关键词）"""

    def _get_fresh_affinity_service_class(self):
        """Reload affinity analysis modules so updated scoring code takes effect immediately."""
        module_names = [
            "backend.app.services.analysis.emotional_resonance_service",
            "backend.app.services.analysis.affinity_analysis_service",
            "backend.app.services.analysis.affinity_config",
            "backend.app.services.analysis.affinity_weights",
            "backend.app.services.analysis.intimacy_signals_service",
        ]
        reloaded = None
        for module_name in module_names:
            module = importlib.import_module(module_name)
            reloaded = importlib.reload(module)
        return reloaded.AffinityAnalysisService

    def get_relationship_context(self, conversation_id: int) -> dict[str, Any]:
        """获取会话的关系上下文信息"""
        try:
            from ...services.analysis.relationship_context_service import (
                RelationshipContextService
            )
            from dataclasses import asdict

            service = RelationshipContextService()
            ctx = service.get_context(conversation_id)

            return {
                "ok": True,
                "context": asdict(ctx) if ctx else None,
                "has_context": ctx is not None,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取关系上下文失败: {e}")
            return {"ok": False, "error": str(e)}

    def save_relationship_context(
        self, conversation_id: int, context: dict
    ) -> dict[str, Any]:
        """保存会话的关系上下文信息"""
        try:
            from ...services.analysis.relationship_context_service import (
                RelationshipContextService
            )
            from dataclasses import asdict

            service = RelationshipContextService()
            ctx = service.save_context(
                conversation_id=conversation_id,
                relationship_type=context.get("relationship_type", "friend"),
                interaction_duration=context.get("interaction_duration", "1_to_6_months"),
                communication_style=context.get("communication_style", "normal"),
            )

            return {
                "ok": True,
                "context": asdict(ctx),
                "message": "关系信息已保存",
            }
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Bridge] 保存关系上下文失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_relationship_field_options(self) -> dict[str, Any]:
        """获取关系信息表单的字段选项"""
        try:
            from ...services.analysis.relationship_context_service import (
                RelationshipContextService
            )

            options = RelationshipContextService.get_field_options()
            return {"ok": True, "options": options}
        except Exception as e:
            logger.error(f"[Bridge] 获取字段选项失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_affinity_config(self, conversation_id: int) -> dict[str, Any]:
        """获取好感度分析配置 (T018)"""
        try:
            from ...services.analysis.affinity_config import AffinityConfigService
            from dataclasses import asdict
            
            service = AffinityConfigService()
            config = service.get_config(conversation_id)
            
            return {
                "ok": True,
                "config": asdict(config)
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取好感度配置失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

    def update_affinity_config(self, conversation_id: int, config: dict) -> dict[str, Any]:
        """更新好感度分析配置 (T019)"""
        try:
            from ...services.analysis.affinity_config import AffinityConfigService
            from dataclasses import asdict
            
            service = AffinityConfigService()
            updated_config = service.update_config(conversation_id, **config)
            
            return {
                "ok": True,
                "config": asdict(updated_config),
                "message": "配置已更新"
            }
        except ValueError as e:
            logger.error(f"[Bridge] 配置验证失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }
        except Exception as e:
            logger.error(f"[Bridge] 更新好感度配置失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

    def get_affinity_keywords(self) -> dict[str, Any]:
        """获取所有关键词分类 (T020)"""
        try:
            from ...services.analysis.keyword_libraries import KeywordLibraries
            
            service = KeywordLibraries()
            keywords = service.get_all_keywords()
            
            return {
                "ok": True,
                "keywords": keywords
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "keywords": {}
            }

    def add_affinity_keywords(self, category: str, keywords: list) -> dict[str, Any]:
        """添加自定义关键词 (T021)"""
        try:
            from ...services.analysis.keyword_libraries import KeywordLibraries
            
            valid_categories = ["positive", "negative", "empathy", "soothing", 
                              "privacy", "holiday", "nickname"]
            if category not in valid_categories:
                return {
                    "ok": False,
                    "error": f"无效的分类: {category}，有效值: {valid_categories}"
                }
            
            service = KeywordLibraries()
            added_count = service.add_keywords(category, keywords)
            updated_keywords = service.get_keywords(category)
            
            return {
                "ok": True,
                "added_count": added_count,
                "keywords": updated_keywords
            }
        except Exception as e:
            logger.error(f"[Bridge] 添加关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "added_count": 0
            }

    def remove_affinity_keywords(self, category: str, keywords: list) -> dict[str, Any]:
        """删除关键词 (T022)"""
        try:
            from ...services.analysis.keyword_libraries import KeywordLibraries
            
            valid_categories = ["positive", "negative", "empathy", "soothing", 
                              "privacy", "holiday", "nickname"]
            if category not in valid_categories:
                return {
                    "ok": False,
                    "error": f"无效的分类: {category}"
                }
            
            service = KeywordLibraries()
            removed_count = service.remove_keywords(category, keywords)
            updated_keywords = service.get_keywords(category)
            
            return {
                "ok": True,
                "removed_count": removed_count,
                "keywords": updated_keywords
            }
        except Exception as e:
            logger.error(f"[Bridge] 删除关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "removed_count": 0
            }

    def get_preference_keywords(self, conversation_id: int) -> dict[str, Any]:
        """获取喜好关键词 (T023)"""
        try:
            from ...services.analysis.affinity_config import AffinityConfigService
            
            service = AffinityConfigService()
            keywords = service.get_preference_keywords(conversation_id)
            
            return {
                "ok": True,
                "keywords": keywords or []
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取喜好关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "keywords": []
            }

    def update_preference_keywords(self, conversation_id: int, keywords: list) -> dict[str, Any]:
        """更新喜好关键词 (T024)"""
        try:
            from ...services.analysis.affinity_config import AffinityConfigService
            
            service = AffinityConfigService()
            updated_keywords = service.update_preference_keywords(conversation_id, keywords)
            
            return {
                "ok": True,
                "keywords": updated_keywords,
                "message": "喜好关键词已更新"
            }
        except Exception as e:
            logger.error(f"[Bridge] 更新喜好关键词失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

    def cancel_analysis(self) -> dict[str, Any]:
        """取消正在进行的好感度分析 / 特征提取"""
        try:
            if self._analysis_cancel_event:
                self._analysis_cancel_event.set()
                logger.info("[Bridge] 已发送取消分析信号")
                return {"ok": True, "message": "已发送取消指令"}
            return {"ok": False, "message": "当前没有正在运行的分析"}
        except Exception as e:
            logger.error(f"[Bridge] 取消分析失败: {e}")
            return {"ok": False, "error": str(e)}

    def analyze_affinity(self, conversation_id: int, force_reanalyze: bool = True, config_overrides: dict = None) -> dict[str, Any]:
        """执行好感度分析（异步，立即返回 task_id 供轮询）"""
        try:
            import time as _time

            # 复用守卫：旧服务实例上仍有本会话的运行中任务时不重复启动。
            # 此处必须查旧实例（本方法每次 reload 出新类，新实例看不到旧任务）；
            # 重复启动会替换取消事件，导致运行中的任务再也停不掉
            prev_service = getattr(self, "_affinity_service", None)
            if prev_service is not None:
                running = prev_service.find_running_task(conversation_id)
                if running:
                    return {
                        "ok": True,
                        "task_id": running,
                        "status": "started",
                        "message": "已有进行中的好感度分析，已复用",
                    }

            AffinityAnalysisService = self._get_fresh_affinity_service_class()
            service = AffinityAnalysisService()            # 保存服务实例引用，供 get_affinity_progress 查询进度
            self._affinity_service = service
            self._analysis_cancel_event = threading.Event()
            effective_force_reanalyze = True

            # 显式生成 task_id（带 uuid 后缀防撞号）并传给 analyze()，
            # 保证返回给前端的 task_id 与服务内注册的完全一致，无需 sleep+扫描猜测
            task_id = f"affinity_{conversation_id}_{int(_time.time())}_{uuid.uuid4().hex[:6]}"
            service.register_task(task_id, conversation_id)

            def _run_analysis():
                try:
                    service.analyze(
                        conversation_id,
                        effective_force_reanalyze,
                        config_overrides,
                        cancel_event=self._analysis_cancel_event,
                        task_id=task_id,
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 异步好感度分析失败: {e}")
                    import traceback
                    traceback.print_exc()

            t = threading.Thread(target=_run_analysis, daemon=True)
            t.start()

            return {
                "ok": True,
                "task_id": task_id
            }
        except Exception as e:
            logger.error(f"[Bridge] 好感度分析启动失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "ok": False,
                "error": str(e)
            }

    def get_affinity_progress(self, task_id: str) -> dict[str, Any]:
        """
        查询好感度分析进度

        Args:
            task_id: 从 analyze_affinity 返回的任务 ID

        Returns:
            {
                "ok": True,
                "status": "running" | "completed" | "failed",
                "progress_percent": 40,
                "current_step": "计算维度评分",
                "result": {...}  // 仅当 status == "completed" 时返回完整结果
            }
        """
        try:
            from dataclasses import asdict

            service = getattr(self, '_affinity_service', None)
            if not service:
                return {
                    "ok": False,
                    "error": "分析服务未初始化",
                    "status": "failed",
                    "progress_percent": 0,
                    "current_step": ""
                }

            progress = service.get_progress(task_id)
            if not progress:
                # 未注册的 task_id（典型：切会话再分析后 _affinity_service 被
                # 整体替换，旧任务失联）：必须显式 not_found 让前端停轮询，
                # 此前伪装成 pending 会让前端 500ms 死轮询、分析按钮卡死
                return {
                    "ok": False,
                    "error": "分析任务不存在或已失效",
                    "status": "not_found",
                    "progress_percent": 0,
                    "current_step": ""
                }

            response = {
                "ok": True,
                "status": progress.status,
                "progress_percent": progress.progress_percent,
                "current_step": progress.current_step
            }

            # 分析完成时，返回完整结果
            if progress.status == "completed":
                response["result"] = asdict(progress)

            # 分析失败时，返回错误信息
            if progress.status == "failed":
                response["error"] = progress.error or "未知错误"

            return response
        except Exception as e:
            logger.error(f"[Bridge] 查询好感度进度失败: {e}")
            return {
                "ok": False,
                "error": str(e),
                "status": "failed",
                "progress_percent": 0,
                "current_step": ""
            }

    def get_affinity_scores(self, conversation_id: int) -> dict[str, Any]:
        """获取好感度分析结果（附分析新鲜度：导入新消息后前端提示重分析）"""
        try:
            from dataclasses import asdict

            AffinityAnalysisService = self._get_fresh_affinity_service_class()
            service = AffinityAnalysisService()
            result = service.get_scores(conversation_id)

            freshness = {"stale": False, "pending_message_count": 0}
            try:
                from ...services.analysis.analysis_state import get_analysis_freshness

                freshness = get_analysis_freshness(int(conversation_id))
            except Exception as fresh_e:
                logger.debug("[Bridge] 分析新鲜度读取跳过: %s", fresh_e)

            return {
                "ok": True,
                "result": asdict(result) if result else None,
                "analysis_stale": freshness.get("stale", False),
                "pending_message_count": freshness.get("pending_message_count", 0),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取好感度结果失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

