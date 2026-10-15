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
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
            else:
                return {
                    'ok': True,
                    'has_profile': False,
                    'expired': False,
                    'profile': None,
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
    ) -> dict[str, Any]:
        """
        生成联系人画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: token 预算档位 (low/medium/high/custom)
            custom_budget: 自定义 token 预算
            cancel_key: 取消键（传 conversation_id；弹窗关闭时经
                cancel_profile_generation 终止本次生成）

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
                    'estimated_tokens': estimate.get('estimated_total_tokens', 0),
                }
            else:
                return {
                    'ok': True,
                    'has_profile': False,
                    'expired': False,
                    'profile': None,
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
    ) -> dict[str, Any]:
        """生成用户本体的聊天克隆画像（取消机制同联系人画像）"""
        try:
            from ...services.realtime.self_profiler import SelfProfiler
            return self._run_profile_cancelable(
                lambda abort: SelfProfiler().generate_profile(
                    display_name,
                    budget_level,
                    custom_budget,
                    self._resolve_account_wxid(account_wxid),
                    should_abort=abort,
                ),
                cancel_key,
                log_prefix="[Bridge] 生成本体画像",
            )
        except Exception as e:
            logger.error(f"[Bridge] 生成本体画像失败: {e}")
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

