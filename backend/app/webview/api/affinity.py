"""好感度分析（四维评分/关系上下文/偏好关键词）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


import importlib, uuid


def _auto_enqueue_rag_index(conversation_id: int) -> None:
    """好感度分析完成后，为该联系人自动排队构建 RAG 记忆索引。

    跳过条件（任一命中即不排队）：
    - RAG 主开关关闭（队列 worker 也会丢弃，提前省一趟）
    - 联系人记忆被显式停用（清空记忆的语义不被分析动作复活）
    - 已在构建/排队中，或已有 ready/stale 索引（增量刷新由监听
      prewarm/建议 ensure 负责，此处只补「从未建过」的空档）
    """
    try:
        from ...db.connection import get_db
        from ...services.realtime.rag.config import load_rag_settings
        from ...services.realtime.rag.indexer import RagIndexQueue, get_active_and_queued
        from ...services.realtime.rag.store import RagStore

        if not load_rag_settings().get("rag_enabled"):
            return
        row = get_db().execute(
            "SELECT account_wxid FROM conversations WHERE id = ?",
            (int(conversation_id),),
        ).fetchone()
        if not row:
            return
        account = str(row["account_wxid"] or "").strip()
        if not account:
            return
        key = (account, int(conversation_id))
        if key in get_active_and_queued():
            return
        status = RagStore(get_db()).get_status(account, int(conversation_id)) or {}
        if not status.get("enabled", 1):
            return
        if str(status.get("status") or "") in {"ready", "stale"}:
            return
        RagIndexQueue.enqueue(account, int(conversation_id))
        logger.info("[Bridge] 分析完成，已排队构建 RAG 记忆索引: conv=%s", conversation_id)
    except Exception as exc:
        logger.debug("[Bridge] 分析后 RAG 自动排队跳过: %s", exc)


class AffinityApiMixin:
    """好感度分析（四维评分/关系上下文/偏好关键词）"""

    def _all_affinity_services(self):
        """曾经创建的全部好感度服务实例（含当前）。互斥守卫用：analyze_affinity
        每次重建实例，旧实例上运行中的任务只存在于旧实例。"""
        services = list(getattr(self, "_affinity_services", None) or [])
        current = getattr(self, "_affinity_service", None)
        if current is not None and not any(s is current for s in services):
            services.append(current)
        return services

    def _get_fresh_affinity_service_class(self):
        """Reload affinity analysis modules so updated scoring code takes effect immediately."""
        module_names = [
            "backend.app.services.analysis.emotional_resonance_service",
            "backend.app.services.analysis.affinity_analysis_service",
            "backend.app.services.analysis.affinity_config",
            "backend.app.services.analysis.affinity_weights",
            "backend.app.services.analysis.engagement_metrics",
            "backend.app.services.analysis.interaction_investment_service",
            "backend.app.services.analysis.closeness_signals_service",
            "backend.app.services.analysis.relationship_llm_service",
            "backend.app.services.analysis.risk_signal_service",
            "backend.app.services.analysis.affinity_history",
        ]
        reloaded = None
        for module_name in module_names:
            module = importlib.import_module(module_name)
            importlib.reload(module)
            # 返回类取自编排器模块本身——列表追加模块后 reloaded 会指向
            # 最后一个（affinity_history），后者没有 AffinityAnalysisService
            if module_name.endswith("affinity_analysis_service"):
                reloaded = module
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
            # 词库已入库：同步刷新进程级共享实例——共享缓存只懒加载一次，
            # 不刷新则同进程后续好感度分析仍用旧词库，重启才生效
            from ...services.analysis.keyword_libraries import get_shared_keyword_libraries

            get_shared_keyword_libraries().reload_cache()
            
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
            # 同上：删除也要刷新共享实例，防同进程分析读到已删词
            from ...services.analysis.keyword_libraries import get_shared_keyword_libraries

            get_shared_keyword_libraries().reload_cache()
            
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
        """取消正在进行的好感度分析 / 特征提取（取消全部运行中任务）"""
        try:
            # 按 task_id 隔离后此处逐个 set（W5）：此前共享单事件只停得掉
            # 最后启动的任务，先启动的提取/分析停不掉
            events = list(getattr(self, "_analysis_cancel_events", {}).values())
            for event in events:
                event.set()
            if events:
                logger.info("[Bridge] 已发送取消分析信号（%d 个任务）", len(events))
                return {"ok": True, "message": "已发送取消指令"}
            return {"ok": False, "message": "当前没有正在运行的分析"}
        except Exception as e:
            logger.error(f"[Bridge] 取消分析失败: {e}")
            return {"ok": False, "error": str(e)}

    def analyze_affinity(self, conversation_id: int, force_reanalyze: bool = True, config_overrides: dict = None) -> dict[str, Any]:
        """执行好感度分析（异步，立即返回 task_id 供轮询）"""
        try:
            import time as _time

            from .deep_analysis import _ONNX_TASK_LOCK

            # 「互斥检查 + 任务注册」临界区（与 start_sentiment_backfill 同锁）：
            # 不加锁时对向检查-后-注册存在 TOCTOU 窗口，两侧可同时通过对方
            # 检查再各自注册，ONNX 推理并发争抢——正是互斥要防的场景。
            # 锁内含模块 reload 与短路判定的几次 DB 读（均亚秒级）。
            with _ONNX_TASK_LOCK:
                # 复用守卫：旧服务实例上仍有本会话的运行中任务时不重复启动。
                # 此处必须查旧实例（本方法每次 reload 出新类，新实例看不到旧任务）；
                # 重复启动会替换取消事件，导致运行中的任务再也停不掉
                prev_service = getattr(self, "_affinity_service", None)
                if prev_service is not None:
                    running = prev_service.find_running_task(conversation_id)
                    if running:
                        # 补评任务不能被当作全面分析复用（其结果不含新消息），
                        # 只能让用户等它结束（补评通常一次 LLM 调用即完）
                        if running.startswith("affinity_llm_"):
                            return {
                                "ok": False,
                                "error": "AI 关系评估补评进行中，请等待完成后再开始全面分析",
                            }
                        return {
                            "ok": True,
                            "task_id": running,
                            "status": "started",
                            "message": "已有进行中的好感度分析，已复用",
                        }

                # 互斥守卫：情感补算与全面分析共用 ONNX 推理会话，并发会争抢
                # 模型资源；补算进行中时拒绝启动分析（补算通常分钟级即完成）
                backfill_service = getattr(self, "_sentiment_backfill_service", None)
                if backfill_service is not None and backfill_service.has_running_task():
                    return {
                        "ok": False,
                        "error": "时光深度情感补算进行中，请等待其完成后再开始全面分析",
                    }

                AffinityAnalysisService = self._get_fresh_affinity_service_class()
                service = AffinityAnalysisService()            # 保存服务实例引用，供 get_affinity_progress 查询进度
                self._affinity_service = service
                # 本方法每次 reload 出新类、新实例——旧实例上仍运行的任务对
                # 新实例不可见。登记前先剔除已无运行任务的旧实例：列表只保
                # 留活任务持有者，防长会话中每次分析（含缓存短路命中）都
                # 累积一个携带完整结果载荷的实例（慢内存泄漏）
                self._affinity_services = [
                    s for s in getattr(self, "_affinity_services", None) or []
                    if s.has_running_task()
                ]
                self._affinity_services.append(service)

                # 短路判定：无新消息且配置指纹未变 → 直接返回缓存（亚秒级），
                # 跳过全链路重算。用户点「重新分析」且数据没变时不再白跑
                # 五分钟。有新消息（stale）或首次分析时照常全量。
                # config_overrides 例外：缓存指纹不含临时覆盖项，带覆盖调用
                # 必须走全量，否则会返回"无覆盖口径"的旧缓存
                effective_force_reanalyze = False
                if config_overrides:
                    effective_force_reanalyze = True
                    logger.info("[Bridge] 好感度短路判定：携带 config_overrides，走全量")
                else:
                    try:
                        from ...services.analysis.analysis_state import get_analysis_freshness

                        freshness = get_analysis_freshness(int(conversation_id))
                        if freshness.get("stale") or freshness.get("pending_message_count"):
                            effective_force_reanalyze = True
                            logger.info(
                                "[Bridge] 好感度短路判定：有 %s 条新消息，走全量",
                                freshness.get("pending_message_count"),
                            )
                        else:
                            # 消息未变，再查配置指纹（改权重/阈值后仍需重算）——
                            # 直接用 _load_cached_scores：它内部已含指纹校验，
                            # 返回 None 即缓存不可用（版本/指纹不匹配）
                            fingerprint_ok = False
                            try:
                                cached_result = service.get_scores(conversation_id)
                                fingerprint_ok = cached_result is not None
                            except Exception as fp_e:
                                logger.debug("[Bridge] 缓存指纹探测失败，按全量处理: %s", fp_e)
                            if not fingerprint_ok:
                                effective_force_reanalyze = True
                                logger.info("[Bridge] 好感度短路判定：配置已变更，走全量")
                            else:
                                logger.info("[Bridge] 好感度短路判定：数据与配置均未变，使用缓存")
                    except Exception as short_circuit_e:
                        logger.debug("[Bridge] 好感度短路判定失败，按全量处理: %s", short_circuit_e)
                        effective_force_reanalyze = True

                # 显式生成 task_id（带 uuid 后缀防撞号）并传给 analyze()，
                # 保证返回给前端的 task_id 与服务内注册的完全一致，无需 sleep+扫描猜测
                task_id = f"affinity_{conversation_id}_{int(_time.time())}_{uuid.uuid4().hex[:6]}"
                service.register_task(task_id, conversation_id)
                # 取消事件按 task_id 隔离（W5），与 bridge 的特征提取共用
                # 注册表——此前共享单事件被后启动的任务覆盖，先启动的停不掉
                cancel_event = threading.Event()
                self._analysis_cancel_events[task_id] = cancel_event

            def _run_analysis():
                try:
                    service.analyze(
                        conversation_id,
                        effective_force_reanalyze,
                        config_overrides,
                        cancel_event=cancel_event,
                        task_id=task_id,
                    )
                    # 分析完成自动补建 RAG 记忆索引：纯历史分析用户不开
                    # 监听时记忆管理会一直停在 pending（建索引入口只有监听
                    # prewarm/建议 ensure/手动构建三个）。失败只记日志，
                    # 不影响分析结果本身
                    _auto_enqueue_rag_index(int(conversation_id))
                except Exception as e:
                    logger.error(f"[Bridge] 异步好感度分析失败: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    self._analysis_cancel_events.pop(task_id, None)

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

    def retry_llm_relationship(self, conversation_id: int) -> dict[str, Any]:
        """补评 AI 关系评估（异步，立即返回 task_id 供轮询）。

        LLM 维因网络抖动等瞬时原因缺席后的恢复通道：复用缓存的四个本地
        维度（数据未变时它们确定不变），只重跑 LLM 维与汇总装配。与全面
        分析互斥（复用守卫同款），但无 ONNX 推理不占补算锁。
        """
        try:
            import time as _time

            # 复用守卫：该会话的全面分析仍在运行时拒绝补评（缓存将被覆盖，
            # 补评结果会一起丢）；不同会话互不影响
            prev_service = getattr(self, "_affinity_service", None)
            if prev_service is not None:
                running = prev_service.find_running_task(int(conversation_id))
                if running:
                    return {
                        "ok": False,
                        "error": "好感度分析进行中，请等待完成后再补评 AI 关系评估",
                    }

            AffinityAnalysisService = self._get_fresh_affinity_service_class()
            service = AffinityAnalysisService()
            self._affinity_service = service

            task_id = (
                f"affinity_llm_{conversation_id}_{int(_time.time())}_{uuid.uuid4().hex[:6]}"
            )

            def _run_retry():
                try:
                    service.retry_llm_relationship(int(conversation_id), task_id)
                except Exception as e:
                    logger.error(f"[Bridge] 补评 AI 关系评估失败: {e}")
                    import traceback
                    traceback.print_exc()

            t = threading.Thread(target=_run_retry, daemon=True)
            t.start()

            return {"ok": True, "task_id": task_id}
        except Exception as e:
            logger.error(f"[Bridge] 补评启动失败: {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}


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

            # 只读路径不 reload（此前每次打开联系人页都重编译 7 个分析
            # 模块+重建正则/词库，纯浪费；热重载语义仅分析写入路径需要）
            from ...services.analysis.affinity_analysis_service import AffinityAnalysisService
            service = AffinityAnalysisService()
            result = service.get_scores(conversation_id)

            freshness = {"stale": False, "pending_message_count": 0}
            try:
                from ...services.analysis.analysis_state import get_analysis_freshness

                freshness = get_analysis_freshness(int(conversation_id))
            except Exception as fresh_e:
                logger.debug("[Bridge] 分析新鲜度读取跳过: %s", fresh_e)

            history: dict[str, Any] = {}
            try:
                from ...services.analysis.affinity_history import compute_trend

                history = compute_trend(int(conversation_id))
            except Exception as hist_e:
                logger.debug("[Bridge] 历史趋势读取跳过: %s", hist_e)

            return {
                "ok": True,
                "result": asdict(result) if result else None,
                "analysis_stale": freshness.get("stale", False),
                "pending_message_count": freshness.get("pending_message_count", 0),
                "history": history,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取好感度结果失败: {e}")
            return {
                "ok": False,
                "error": str(e)
            }

    def export_affinity_report(self, conversation_id: int) -> dict[str, Any]:
        """导出关系体检报告（单文件 HTML，写入 chrono_trace_export 目录）"""
        try:
            from ...services.analysis.affinity_report_export import (
                AffinityReportExportError,
                export_affinity_report,
            )

            return export_affinity_report(int(conversation_id))
        except AffinityReportExportError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Bridge] 体检报告导出失败: {e}")
            return {"ok": False, "error": f"报告导出失败：{e}"}

