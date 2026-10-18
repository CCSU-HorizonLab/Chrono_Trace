"""时光深度·画像演变：前后半窗双画像对比。

口径与词云演变严格同式——``mid_ts = (from_ts + to_ts) // 2``，前半窗
``[from_ts, mid_ts - 1]``、后半窗 ``[mid_ts, to_ts]`` 闭区间，同窗同分，
画像演变与词云演变可直接对照。

半窗画像落为 custom 快照（唯一键 (账号, 显示名, 'custom', f, t)），二次
调用精确键命中即跳过 LLM——增量续跑只补缺的半窗；``force=True`` 无视
缓存全部重算。取消事件在每次 generate_profile 调用前检查，HTTP 层经
should_abort 在尝试边界退出，已完成半窗随结果带回（已落缓存，重试免费）。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from ...db.connection import get_db

logger = logging.getLogger(__name__)


class ProfileEvolutionService:
    """前后半窗画像对比（快照缓存命中增量续跑；可取消）"""

    def generate(
        self,
        conversation_id: int,
        from_ts: int,
        to_ts: int,
        account_wxid: str = "",
        include_self: bool = False,
        force: bool = False,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        conversation_id = int(conversation_id or 0)
        from_ts, to_ts = int(from_ts), int(to_ts)
        mid_ts = (from_ts + to_ts) // 2
        if mid_ts - 1 < from_ts:
            return {"ok": False, "error": "时间窗太短，无法对半分段（至少需两天跨度）"}

        row = self._load_conversation(conversation_id, account_wxid)
        if row is None:
            return {"ok": False, "error": "未找到会话，请先导入微信数据"}
        display_name = str(row["display_name"] or "")

        from ..realtime.contact_profiler import ContactProfiler
        from ..realtime.self_profiler import SelfProfiler

        kinds: list[tuple[str, Any, str]] = [("contact", ContactProfiler(), "contact_profiles")]
        if include_self:
            kinds.append(("self", SelfProfiler(), "self_profiles"))

        def _aborted() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        halves: list[dict[str, Any]] = []
        for index, (half_from, half_to) in enumerate(
            ((from_ts, mid_ts - 1), (mid_ts, to_ts))
        ):
            if _aborted():
                return self._cancelled(halves, from_ts, to_ts, mid_ts, display_name)
            half: dict[str, Any] = {
                "from_ts": half_from,
                "to_ts": half_to,
                "label": "前半段" if index == 0 else "后半段",
            }
            for kind, profiler, table in kinds:
                if _aborted():
                    return self._cancelled(halves, from_ts, to_ts, mid_ts, display_name)
                half[kind] = self._half_profile(
                    profiler, table, display_name, account_wxid,
                    half_from, half_to, force, _aborted,
                )
            halves.append(half)

        return {
            "ok": True,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "mid_ts": mid_ts,
            "display_name": display_name,
            "halves": halves,
            "generated_at": int(time.time()),
        }

    @staticmethod
    def _load_conversation(conversation_id: int, account_wxid: str):
        sql = "SELECT display_name FROM conversations WHERE id = ? AND is_deleted = 0"
        params: list[Any] = [conversation_id]
        if account_wxid:
            sql += " AND account_wxid = ?"
            params.append(account_wxid)
        try:
            return get_db().execute(sql, params).fetchone()
        except Exception as exc:
            logger.warning("[ProfileEvolution] 会话查询失败: %s", exc)
            return None

    def _half_profile(
        self,
        profiler: Any,
        table: str,
        display_name: str,
        account_wxid: str,
        half_from: int,
        half_to: int,
        force: bool,
        aborted: Callable[[], bool],
    ) -> Optional[dict[str, Any]]:
        """单半窗画像：先查 custom 快照精确键，未命中再生成（失败不中断整体）。"""
        if not force:
            cached = self._load_snapshot(table, display_name, account_wxid, half_from, half_to)
            if cached is not None:
                return cached
        result = profiler.generate_profile(
            display_name,
            account_wxid=account_wxid,
            should_abort=aborted,
            from_ts=half_from,
            to_ts=half_to,
        )
        if aborted():
            return None
        if not result.get("ok"):
            return {
                "profile": None,
                "created_at": 0,
                "cached": False,
                "error": str(result.get("error") or "生成失败"),
            }
        # 生成路径直接用返回画像（真实链路会把同一画像落为 custom 快照）；
        # cached=False 如实标识「本次调了 AI」，不误标历史快照
        return {
            "profile": result.get("profile"),
            "created_at": int(time.time()),
            "cached": False,
        }

    @staticmethod
    def _load_snapshot(
        table: str, display_name: str, account_wxid: str,
        half_from: int, half_to: int,
    ) -> Optional[dict[str, Any]]:
        """按 custom 快照精确键查缓存（含 profile 全文）。"""
        try:
            row = get_db().execute(
                f"SELECT profile_json, created_at FROM {table} "
                "WHERE account_wxid = ? AND display_name = ? AND window_kind = 'custom' "
                "AND window_from = ? AND window_to = ?",
                (account_wxid, display_name, half_from, half_to),
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        try:
            profile = json.loads(row["profile_json"] or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            profile = None
        return {
            "profile": profile,
            "created_at": int(row["created_at"] or 0),
            "cached": True,
        }

    @staticmethod
    def _cancelled(
        halves: list[dict[str, Any]], from_ts: int, to_ts: int,
        mid_ts: int, display_name: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "cancelled": True,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "mid_ts": mid_ts,
            "display_name": display_name,
            "halves": halves,
        }
