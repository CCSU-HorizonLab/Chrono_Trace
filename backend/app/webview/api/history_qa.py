"""问问微信（历史问答 + 引用溯源）——独立 API 域 mixin。

Bridge 继承此 Mixin；问答为一次性 LLM 调用，沿用画像生成的同步
调用约定（前端 await + 加载态 + 可取消），不走任务轮询。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class HistoryQaApiMixin:
    """问问微信：当前联系人历史自然语言问答"""

    def ask_history(self, conversation_id: int, question: str) -> dict[str, Any]:
        """对当前联系人的聊天记录提问，返回带引用溯源的回答

        Returns:
            {"ok": True, "answer": "...", "citations": [{index, message_id, timestamp, is_sender, text}]}
            失败时 {"ok": False, "error": "..."}（error 面向用户展示）
        """
        try:
            from ...services.analysis.history_qa_service import (
                HistoryQAError,
                HistoryQAService,
            )

            result = HistoryQAService().ask(int(conversation_id), str(question or ""))
            return {"ok": True, **result}
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
