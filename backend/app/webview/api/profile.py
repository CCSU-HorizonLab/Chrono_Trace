"""联系人/自我画像——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
    ) -> dict[str, Any]:
        """
        生成联系人画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: token 预算档位 (low/medium/high/custom)
            custom_budget: 自定义 token 预算

        Returns:
            {"ok": True, "profile": {...}} 或 {"ok": False, "error": "..."}
        """
        try:
            from ...services.realtime.contact_profiler import ContactProfiler
            profiler = ContactProfiler()
            result = profiler.generate_profile(
                display_name,
                budget_level,
                custom_budget,
                self._resolve_account_wxid(account_wxid),
            )
            return result
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
    ) -> dict[str, Any]:
        """生成用户本体的聊天克隆画像"""
        try:
            from ...services.realtime.self_profiler import SelfProfiler
            profiler = SelfProfiler()
            result = profiler.generate_profile(
                display_name,
                budget_level,
                custom_budget,
                self._resolve_account_wxid(account_wxid),
            )
            return result
        except Exception as e:
            logger.error(f"[Bridge] 生成本体画像失败: {e}")
            import traceback
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

