"""问问微信（历史问答 + 引用溯源）——独立 API 域 mixin。

Bridge 继承此 Mixin；问答为一次性 LLM 调用，沿用画像生成的同步
调用约定（前端 await + 加载态 + 可取消），不走任务轮询。

问答成功后顺带探测该会话的语义向量缺口，不足则后台补建（不阻塞
当次回答）——sentiment_cache.embedding_vector 是问答向量通道的唯一
数据源，未跑过分析的老会话靠这条懒补通道自愈。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# 语义索引懒补触发阈值：覆盖率低于八成且缺口不少于 50 条才起任务——
# 高覆盖时向量池已够 RRF 融合用，小缺口反复起任务徒增抖动
EMBEDDING_BACKFILL_RATIO = 0.8
EMBEDDING_BACKFILL_MIN_MISSING = 50


class HistoryQaApiMixin:
    """问问微信：当前联系人历史自然语言问答"""

    def ask_history(
        self,
        conversation_id: int,
        question: str,
        history: list | None = None,
    ) -> dict[str, Any]:
        """对当前联系人的聊天记录提问，返回带引用溯源的回答

        history：近期问答 [{question, answer}]（时间升序），用于多轮指代；
        service 侧清洗与截断，异常输入按无历史处理。

        Returns:
            {"ok": True, "answer": "...", "citations": [...],
             "semantic_indexing": bool}
            失败时 {"ok": False, "error": "..."}（error 面向用户展示）
        """
        try:
            from ...services.analysis.history_qa_service import (
                HistoryQAError,
                HistoryQAService,
            )

            result = HistoryQAService().ask(
                int(conversation_id), str(question or ""), history or []
            )
            semantic_indexing = self._maybe_start_embedding_backfill(int(conversation_id))
            return {"ok": True, "semantic_indexing": semantic_indexing, **result}
        except HistoryQAError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Bridge] 历史问答失败: {e}")
            return {"ok": False, "error": f"问答失败：{e}"}

    def cancel_history_qa(self, conversation_id: int) -> dict[str, Any]:
        """取消该联系人进行中的提问（下一次轮询点生效，在途请求在工作线程退出）。"""
        try:
            from ...services.analysis.history_qa_service import request_cancel

            request_cancel(int(conversation_id))
            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 取消历史问答失败: {e}")
            return {"ok": False, "error": str(e)}

    def _maybe_start_embedding_backfill(self, conversation_id: int) -> bool:
        """问答成功后探测向量缺口，不足则后台补建语义索引。

        整体 try/except：触发链路任何异常只记录，绝不波及问答主路径。
        守卫纪律与 start_sentiment_backfill 同源（_ONNX_TASK_LOCK 临界区 +
        本会话复用 / 全局单飞 / 全面分析互斥 / 模型可用四层）；嵌入任务与
        情感补算共用 Bridge 上的同一服务实例与任务字典，互斥天然覆盖。

        Returns:
            是否有语义索引补算在途（含复用已运行的情感补算——它同样写向量）。
        """
        try:
            from .deep_analysis import _ONNX_TASK_LOCK

            service = getattr(self, "_sentiment_backfill_service", None)
            with _ONNX_TASK_LOCK:
                # 守卫 0a：本会话已有补算在途（情感/语义索引皆在写向量）→ 复用
                if service is not None and service.find_running_task(conversation_id):
                    return True
                # 守卫 0b：全局单飞——另一会话补算中，本会话下次提问再试
                if service is not None and service.has_running_task():
                    return False
                # 守卫 1：全面分析进行中（它会自己补齐向量）——须查全部历史
                # 服务实例：analyze_affinity 每次 reload 重建，旧实例任务对
                # 最新实例不可见
                for affinity_service in self._all_affinity_services():
                    if affinity_service.has_running_task():
                        return False
                # 守卫 2：嵌入模型可用（只查嵌入产物，分类器缺失不影响）
                from ...services.analysis.onnx_inference import has_embedding_model

                if not has_embedding_model():
                    return False

                if service is None:
                    from ...services.analysis.sentiment_backfill_service import (
                        SentimentBackfillService,
                    )

                    service = SentimentBackfillService()
                    self._sentiment_backfill_service = service
                service.prune_finished()

                coverage = service.get_embedding_coverage(conversation_id)
                if (
                    coverage["missing"] < EMBEDDING_BACKFILL_MIN_MISSING
                    or coverage["ratio"] >= EMBEDDING_BACKFILL_RATIO
                ):
                    return False

                task_id = f"embbf_{conversation_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                service.register_task(task_id, conversation_id, kind="embedding")
                # 每任务独立取消事件（与情感补算同一注册表，cancel API 通用）
                cancel_event = threading.Event()
                if not hasattr(self, "_sentiment_backfill_cancel_events"):
                    self._sentiment_backfill_cancel_events = {}
                self._sentiment_backfill_cancel_events[task_id] = cancel_event

            def _run():
                try:
                    service.run_embedding_backfill(conversation_id, cancel_event, task_id)
                except Exception as e:
                    logger.error(f"[Bridge] 异步语义索引补算失败: {e}")
                finally:
                    self._sentiment_backfill_cancel_events.pop(task_id, None)

            threading.Thread(target=_run, daemon=True).start()
            logger.info(f"[Bridge] 语义索引懒补已启动: conv={conversation_id}")
            return True
        except Exception as e:
            logger.debug(f"[Bridge] 语义索引懒补触发跳过: {e}")
            return False
