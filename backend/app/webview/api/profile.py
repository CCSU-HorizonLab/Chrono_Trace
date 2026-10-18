"""联系人/自我画像——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# 画像生成取消作用域（key 用 conversation_id，与问问微信/群日报同款机制）：
# 生成中关闭弹窗 → cancel_profile_generation 置位 → run_cancelable 立即
# 返回「已取消」，HTTP 工作线程经 should_abort 在尝试边界自行退出
PROFILE_CANCEL_SCOPE = "profile_generation"


def _format_profile_window(cached: dict) -> dict[str, Any]:
    """把 get_profile 返回的窗口元信息格式化为前端可直接展示的 window 对象。

    rolling → 「最近 N 天」（N 为档位名义窗天数）；custom → 「起 ~ 止」日期区间。
    """
    from datetime import datetime

    kind = str(cached.get('window_kind') or 'rolling')
    window_from = int(cached.get('window_from') or 0)
    window_to = int(cached.get('window_to') or 0)
    days = max(0, (window_to - window_from) // 86400) if window_from and window_to else 0
    if kind == 'custom' and window_from and window_to:
        fmt = lambda ts: datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')  # noqa: E731
        label = f"{fmt(window_from)} ~ {fmt(window_to)}"
    else:
        label = f"最近 {days} 天" if days > 0 else "最近滚动窗"
    return {'kind': kind, 'from': window_from, 'to': window_to, 'days': days, 'label': label}


class ProfileApiMixin:
    """联系人/自我画像"""

    def get_contact_profile(self, display_name: str, account_wxid: str = "") -> dict[str, Any]:
        """
        获取联系人画像（查缓存）

        Returns:
            {
                "ok": True,
                "has_profile": True/False,
                "expired": True/False,
                "profile": {...} or None,
                "estimated_tokens": int,  # 生成所需预估 token
            }
        """
        try:
            from ...services.realtime.contact_profiler import ContactProfiler
            profiler = ContactProfiler()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cached = profiler.get_profile(display_name, resolved_account_wxid)
            estimate = profiler.estimate_tokens(display_name, account_wxid=resolved_account_wxid)

            if cached:
                return {
                    'ok': True,
                    'has_profile': True,
                    'expired': cached['expired'],
                    'profile': cached['profile'],
                    'created_at': cached['created_at'],
                    'expires_at': cached['expires_at'],
                    'window': _format_profile_window(cached),
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
            else:
                return {
                    'ok': True,
                    'has_profile': False,
                    'expired': False,
                    'profile': None,
                    'window': None,
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
        except Exception as e:
            logger.error(f"[Bridge] 获取联系人画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def generate_contact_profile(
        self,
        display_name: str,
        budget_level: str = 'medium',
        custom_budget: int = 0,
        account_wxid: str = "",
        cancel_key: int = 0,
        from_ts: int = 0,
        to_ts: int = 0,
    ) -> dict[str, Any]:
        """
        生成联系人画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: token 预算档位 (low/medium/high/custom)
            custom_budget: 自定义 token 预算
            cancel_key: 取消键（传 conversation_id；弹窗关闭时经
                cancel_profile_generation 终止本次生成）
            from_ts/to_ts: 可选历史时间窗（秒级时间戳，闭区间）；缺省为
                滚动窗模式。指定窗口时存为 custom 快照，budget_level 只
                决定采样目标量

        Returns:
            {"ok": True, "profile": {...}} 或 {"ok": False, "error": "..."} 或
            {"ok": False, "cancelled": True, "error": "本次画像生成已取消"}
        """
        try:
            from ...services.realtime.contact_profiler import ContactProfiler
            return self._run_profile_cancelable(
                lambda abort: ContactProfiler().generate_profile(
                    display_name,
                    budget_level,
                    custom_budget,
                    self._resolve_account_wxid(account_wxid),
                    should_abort=abort,
                    from_ts=from_ts,
                    to_ts=to_ts,
                ),
                cancel_key,
                log_prefix="[Bridge] 生成联系人画像",
            )
        except Exception as e:
            logger.error(f"[Bridge] 生成联系人画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def get_self_profile(self, display_name: str, account_wxid: str = "") -> dict[str, Any]:
        """获取用户本人的专属克隆画像缓存"""
        try:
            from ...services.realtime.self_profiler import SelfProfiler
            profiler = SelfProfiler()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cached = profiler.get_profile(display_name, resolved_account_wxid)
            estimate = profiler.estimate_tokens(display_name, account_wxid=resolved_account_wxid)

            if cached:
                return {
                    'ok': True,
                    'has_profile': True,
                    'expired': cached['expired'],
                    'profile': cached['profile'],
                    'created_at': cached['created_at'],
                    'expires_at': cached['expires_at'],
                    'window': _format_profile_window(cached),
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
            else:
                return {
                    'ok': True,
                    'has_profile': False,
                    'expired': False,
                    'profile': None,
                    'window': None,
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
        except Exception as e:
            logger.error(f"[Bridge] 获取本体克隆画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def generate_self_profile(
        self,
        display_name: str,
        budget_level: str = 'medium',
        custom_budget: int = 0,
        account_wxid: str = "",
        cancel_key: int = 0,
        from_ts: int = 0,
        to_ts: int = 0,
    ) -> dict[str, Any]:
        """生成用户本体的聊天克隆画像（取消机制同联系人画像；from_ts/to_ts
        指定历史时间窗时存为 custom 快照，语义同联系人画像）"""
        try:
            from ...services.realtime.self_profiler import SelfProfiler
            return self._run_profile_cancelable(
                lambda abort: SelfProfiler().generate_profile(
                    display_name,
                    budget_level,
                    custom_budget,
                    self._resolve_account_wxid(account_wxid),
                    should_abort=abort,
                    from_ts=from_ts,
                    to_ts=to_ts,
                ),
                cancel_key,
                log_prefix="[Bridge] 生成本体画像",
            )
        except Exception as e:
            logger.error(f"[Bridge] 生成本体画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    def list_profile_snapshots(
        self,
        display_name: str,
        account_wxid: str = "",
        profile_kind: str = "contact",
        window_kind: str = "",
    ) -> dict[str, Any]:
        """历史画像快照列表（created_at 降序，最多 24 条），供画像档案回看。

        Args:
            profile_kind: 'contact' 联系人画像 / 'self' 本体画像
            window_kind: 可选过滤 'rolling' / 'custom'，空为全部
        """
        try:
            if profile_kind == 'self':
                from ...services.realtime.self_profiler import SelfProfiler as profiler_cls
            else:
                from ...services.realtime.contact_profiler import ContactProfiler as profiler_cls
            snapshots = profiler_cls().list_snapshots(
                display_name,
                account_wxid=self._resolve_account_wxid(account_wxid),
                window_kind=window_kind,
            )
            for snap in snapshots:
                snap['window'] = _format_profile_window(snap)
            return {'ok': True, 'snapshots': snapshots}
        except Exception as e:
            logger.error(f"[Bridge] 查询画像快照列表失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    # ---- 生成取消（弹窗生成中可关闭） ----

    def _run_profile_cancelable(self, run, cancel_key: int, log_prefix: str) -> dict[str, Any]:
        """画像生成跑守护工作线程并轮询取消标记（在途 socket 无法强断，
        HTTP 经 should_abort 在尝试边界退出；结果被丢弃）。"""
        from ...services.realtime.llm_http import (
            LLMRequestAborted,
            run_cancelable,
            take_llm_cancel,
        )

        key = int(cancel_key or 0)
        if key:
            take_llm_cancel(PROFILE_CANCEL_SCOPE, key)  # 清掉上一轮遗留取消
        abort = threading.Event()
        try:
            return run_cancelable(
                lambda: run(abort.is_set),
                cancelled=lambda: take_llm_cancel(PROFILE_CANCEL_SCOPE, key) if key else False,
                on_cancel=abort.set,
                cancel_message="本次画像生成已取消",
            )
        except LLMRequestAborted as exc:
            logger.info("%s 已被用户取消", log_prefix)
            return {'ok': False, 'cancelled': True, 'error': str(exc)}

    def cancel_profile_generation(self, cancel_key: int) -> dict[str, Any]:
        """终止进行中的画像生成（弹窗关闭时调用；key 同 generate 的 cancel_key）"""
        from ...services.realtime.llm_http import request_llm_cancel

        key = int(cancel_key or 0)
        if not key:
            return {"ok": False, "error": "缺少取消键"}
        request_llm_cancel(PROFILE_CANCEL_SCOPE, key)
        return {"ok": True}

