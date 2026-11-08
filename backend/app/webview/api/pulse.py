"""脉搏页聚合 API（指标直白化层）。

门面指标只翻译不新算（docs/product-redesign-2026-11.md §五）：关系温度/
主动天平/回应温度/本月速览/冷淡预警全部来自既有引擎产物（affinity 缓存与
历史表、initiative_stats、response_times、messages），本模块只做聚合与
话术化，不引入新的计算口径——查询与翻译函数的单一事实来源在
services/analysis/pulse_metrics.py（与关系周报共用）。

依赖说明：get_affinity_scores 由 Bridge 多继承组合提供（affinity.py 的
读出口带 sentinel 改写与 stale 标记，必须复用不可绕过）。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ...services.analysis.pulse_metrics import (
    directional_response_medians,
    initiative_summary,
    medians_to_minutes,
    monthly_overview,
    temperature_label,
    template_verdict,
    trend_line,
    warning_from_risk,
)

logger = logging.getLogger(__name__)

_DAY = 86400


# ----------------------------------------------------------------------
# Bridge Mixin
# ----------------------------------------------------------------------

class PulseApiMixin:
    """脉搏页：门面指标聚合（关系温度/主动天平/回应温度/本月速览/预警/判读）。"""

    def get_pulse_overview(self, conversation_id: int) -> dict:
        """单点聚合。professional 字段透传完整好感度结果供专业视图折叠层
        复用（四维雷达/风险卡/权重入口），前端无需二次调 get_affinity_scores。"""
        try:
            # 同 Bridge 上其它 mixin 方法（由 Bridge 多继承组合提供）
            base = self.get_affinity_scores(conversation_id)
            result = base.get("result")
            history = base.get("history") or {}
            now = int(time.time())

            temperature = None
            if result:
                delta = history.get("score_trend") if history.get("comparable") else None
                temperature = {
                    "score": result["overall_score"],
                    "label": temperature_label(result["overall_score"]),
                    "delta": delta,
                    "trend_line": trend_line(
                        conversation_id, result.get("analysis_caliber") or 0
                    ),
                }

            initiative = initiative_summary(conversation_id)
            recent = medians_to_minutes(
                directional_response_medians(conversation_id, now - 30 * _DAY, now)
            )
            prev = medians_to_minutes(
                directional_response_medians(conversation_id, now - 60 * _DAY, now - 30 * _DAY)
            )
            response = (
                {"recent": recent, "prev": prev} if (recent or prev) else None
            )

            warning = warning_from_risk(result.get("risk_assessment")) if result else None

            verdict = None
            if result:
                llm = result.get("llm_relationship")
                if llm and llm.get("interpretation"):
                    verdict = {"text": llm["interpretation"], "source": "llm"}
                else:
                    verdict = {
                        "text": template_verdict(temperature, initiative, recent),
                        "source": "template",
                    }

            return {
                "ok": True,
                "analyzed": result is not None,
                "verdict": verdict,
                "temperature": temperature,
                "initiative": initiative,
                "response": response,
                "monthly": monthly_overview(conversation_id, now),
                "warning": warning,
                "professional": {
                    "result": result,
                    "analysis_stale": base.get("analysis_stale", False),
                    "pending_message_count": base.get("pending_message_count", 0),
                    "absent_reason": (
                        result.get("llm_relationship_absent_reason") if result else None
                    ),
                },
            }
        except Exception as e:
            logger.error(f"[Pulse] 聚合失败 conversation={conversation_id}: {e}")
            return {"ok": False, "error": str(e)}

    def get_weekly_report(self, conversation_id: int) -> dict:
        """读本周关系周报（无则同步落一版模板句，秒级）。

        返回 {ok, report: {week_start, verdict, source, snapshot, updated_at} | None,
        llm_configured}——report 为 None 表示该会话从未做过全面分析（无基线）。
        """
        try:
            from ...services.analysis import weekly_report_service

            report = weekly_report_service.ensure_template(conversation_id)
            return {
                "ok": True,
                "report": report,
                "llm_configured": weekly_report_service.llm_configured(),
            }
        except Exception as e:
            logger.error(f"[周报] 读取失败 conversation={conversation_id}: {e}")
            return {"ok": False, "error": str(e)}

    def request_weekly_llm(self, conversation_id: int) -> dict:
        """请求把本周周报升级为 LLM 版（后台线程，前端轮询 get_weekly_report）。"""
        try:
            from ...services.analysis import weekly_report_service

            return weekly_report_service.request_llm_upgrade(conversation_id)
        except Exception as e:
            logger.error(f"[周报] LLM 升级请求失败 conversation={conversation_id}: {e}")
            return {"ok": False, "error": str(e)}
