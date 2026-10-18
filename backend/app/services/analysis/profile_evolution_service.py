"""时光深度·画像演变：时间窗均分多段画像对比。

切窗与词云演变共用 ``split_window_evenly``（段数 2~6 默认 2——每段是
独立 LLM 快照，成本随段数线性涨，故独立于词云分段自选）：前三段
``[b_i, b_{i+1}-1]``、末段含终点闭区间，同窗同分，画像演变与词云
演变可直接对照。

分段画像落为 custom 快照（唯一键 (账号, 显示名, 'custom', f, t)），二次
调用精确键命中即跳过 LLM——增量续跑只补缺的段（换段数切回旧档免费）；
``force=True`` 无视缓存全部重算。取消事件在每次 generate_profile 调用前
检查，HTTP 层经 should_abort 在尝试边界退出，已完成段随结果带回
（已落缓存，重试免费）。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from ...db.connection import get_db
# 仅引常量（profiler 无 analysis 模块级依赖，无环）；profiler 实例仍在
# generate() 内延迟导入，保持 analysis←realtime 单向
from ..realtime.contact_profiler import PROFILE_SNAPSHOT_SCHEMA
from .deep_analysis_service import split_window_evenly

logger = logging.getLogger(__name__)

# 分段数界限（前端选择器同域；每段一次 LLM 快照，成本随段数线性涨）
PROFILE_EVOLUTION_SEGMENTS_MIN = 2
PROFILE_EVOLUTION_SEGMENTS_MAX = 6
PROFILE_EVOLUTION_SEGMENTS_DEFAULT = 2


class ProfileEvolutionService:
    """分段画像对比（快照缓存命中增量续跑；可取消）"""

    def generate(
        self,
        conversation_id: int,
        from_ts: int,
        to_ts: int,
        account_wxid: str = "",
        include_self: bool = False,
        force: bool = False,
        cancel_event: Optional[threading.Event] = None,
        segments: int = PROFILE_EVOLUTION_SEGMENTS_DEFAULT,
    ) -> dict[str, Any]:
        conversation_id = int(conversation_id or 0)
        from_ts, to_ts = int(from_ts), int(to_ts)
        try:
            segments = int(segments)
        except (TypeError, ValueError):
            segments = 0
        if not (PROFILE_EVOLUTION_SEGMENTS_MIN <= segments <= PROFILE_EVOLUTION_SEGMENTS_MAX):
            return {
                "ok": False,
                "error": (
                    f"分段数需在 {PROFILE_EVOLUTION_SEGMENTS_MIN}"
                    f"~{PROFILE_EVOLUTION_SEGMENTS_MAX} 之间"
                ),
            }
        # 与词云演变共用切窗公式；任一空段（窗口秒数不足段数）直接拒绝
        spans = split_window_evenly(from_ts, to_ts, segments)
        if any(seg_to < seg_from for seg_from, seg_to in spans):
            return {
                "ok": False,
                "error": f"时间窗太短，无法均分为 {segments} 段（至少需 {segments} 天跨度）",
            }

        from ..realtime.contact_profiler import ContactProfiler
        from ..realtime.self_profiler import SelfProfiler

        kinds: list[tuple[str, Any, str]] = [("contact", ContactProfiler(), "contact_profiles")]
        if include_self:
            kinds.append(("self", SelfProfiler(), "self_profiles"))

        # 账号与生成侧同源解析（profiler 内部 _save_cache 按解析后账号落库，
        # 快照查询键必须一致，否则生产链路 account_wxid="" 永远查不中缓存）
        account_wxid = kinds[0][1]._resolve_account_wxid(account_wxid)
        if not account_wxid:
            # 解析不到活跃账号时不允许去掉账号过滤兜底——那会跨账号取会话
            return {"ok": False, "error": "无法确定当前微信账号，请先导入微信数据"}

        row = self._load_conversation(conversation_id, account_wxid)
        if row is None:
            return {"ok": False, "error": "未找到会话，请先导入微信数据"}
        display_name = str(row["display_name"] or "")

        def _aborted() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        segment_results: list[dict[str, Any]] = []
        for index, (seg_from, seg_to) in enumerate(spans):
            if _aborted():
                return self._cancelled(segment_results, from_ts, to_ts, display_name)
            segment: dict[str, Any] = {
                "from_ts": seg_from,
                "to_ts": seg_to,
                "label": f"第 {index + 1} 段",
            }
            for kind, profiler, table in kinds:
                if _aborted():
                    return self._cancelled(segment_results, from_ts, to_ts, display_name)
                segment[kind] = self._segment_profile(
                    profiler, table, display_name, account_wxid,
                    seg_from, seg_to, force, _aborted,
                )
            segment_results.append(segment)

        return {
            "ok": True,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "display_name": display_name,
            "segments": segment_results,
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

    def _segment_profile(
        self,
        profiler: Any,
        table: str,
        display_name: str,
        account_wxid: str,
        seg_from: int,
        seg_to: int,
        force: bool,
        aborted: Callable[[], bool],
    ) -> Optional[dict[str, Any]]:
        """单段画像：先查 custom 快照精确键，未命中再生成（失败不中断整体）。"""
        if not force:
            cached = self._load_snapshot(table, display_name, account_wxid, seg_from, seg_to)
            if cached is not None:
                return cached
        result = profiler.generate_profile(
            display_name,
            account_wxid=account_wxid,
            should_abort=aborted,
            from_ts=seg_from,
            to_ts=seg_to,
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
        seg_from: int, seg_to: int,
    ) -> Optional[dict[str, Any]]:
        """按 custom 快照精确键查缓存（含 profile 全文）。

        行存在但 profile_json 损坏/为空（写库中断的残行）视作未命中——
        走生成路径并以 INSERT OR REPLACE 覆盖坏行，不让空画像带
        「历史快照」徽标卡死缓存。
        """
        try:
            row = get_db().execute(
                f"SELECT profile_json, created_at FROM {table} "
                "WHERE account_wxid = ? AND display_name = ? AND window_kind = 'custom' "
                "AND window_from = ? AND window_to = ? AND schema_version = ?",
                (account_wxid, display_name, seg_from, seg_to, PROFILE_SNAPSHOT_SCHEMA),
            ).fetchone()
        except Exception:
            return None
        if not row:
            return None
        try:
            profile = json.loads(row["profile_json"] or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            profile = None
        if not isinstance(profile, dict) or not profile:
            return None
        return {
            "profile": profile,
            "created_at": int(row["created_at"] or 0),
            "cached": True,
        }

    @staticmethod
    def _cancelled(
        segment_results: list[dict[str, Any]], from_ts: int, to_ts: int,
        display_name: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "cancelled": True,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "display_name": display_name,
            "segments": segment_results,
        }
