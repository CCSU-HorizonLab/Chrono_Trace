"""时光深度分析（分桶情绪演变/词云演变/里程碑）Bridge API。"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DeepAnalysisApiMixin:
    """时光深度：Analytics 第六 tab 的后端入口"""

    def get_deep_analysis(
        self,
        conversation_id: int,
        from_date: str,
        to_date: str,
        bucket: str = "week",
    ) -> dict:
        """获取时光深度聚合数据（分桶情绪序列+覆盖率、拐点、词云演变、里程碑、好感度落点）。

        Args:
            conversation_id: 会话ID
            from_date: 开始日期 "2025-01-01"
            to_date: 结束日期 "2025-12-31"
            bucket: 分桶粒度 day/week/month/year（默认 week）

        Returns:
            {ok, version, bucket, buckets, turning_points, wordcloud_evolution,
             milestones, affinity_history}
        """
        try:
            if not conversation_id:
                return {"ok": False, "error": "缺少参数: conversation_id"}
            if not from_date or not to_date:
                return {"ok": False, "error": "缺少日期参数"}

            # 日期口径与 get_analysis 一致：闭区间（to 含当日全天）
            from_ts = int(datetime.strptime(from_date, "%Y-%m-%d").timestamp())
            to_ts = int(
                datetime.strptime(to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
            )

            from ...services.analysis.deep_analysis_service import DeepAnalysisService

            service = DeepAnalysisService()
            return service.get_deep_analysis(
                int(conversation_id), from_ts, to_ts, bucket=bucket
            )
        except ValueError as e:
            return {"ok": False, "error": f"参数格式错误: {e}"}
        except Exception as e:
            logger.error(f"[Bridge] 获取时光深度数据失败: {e}")
            return {"ok": False, "error": str(e)}
