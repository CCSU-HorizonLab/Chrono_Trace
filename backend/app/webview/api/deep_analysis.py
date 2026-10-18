"""时光深度分析（分桶情绪演变/词云演变/里程碑/情感补算）Bridge API。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
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

    # ------------------------------------------------------------------
    # 情感补算（sentiment_cache 缺口 → 后台任务）
    # ------------------------------------------------------------------

    def get_sentiment_coverage(self, conversation_id: int) -> dict:
        """查询会话文本消息的 sentiment_cache 覆盖率。"""
        try:
            from ...services.analysis.sentiment_backfill_service import SentimentBackfillService

            return {"ok": True, **SentimentBackfillService.get_coverage(int(conversation_id))}
        except Exception as e:
            logger.error(f"[Bridge] 查询情感覆盖率失败: {e}")
            return {"ok": False, "error": str(e)}

    def start_sentiment_backfill(self, conversation_id: int) -> dict:
        """启动情感补算后台任务（立即返回 task_id 供轮询）。

        互斥：与全面分析共用 ONNX 推理会话，任一侧运行中即拒绝启动。
        缺口为 0 时直接返回 complete，不建任务。
        """
        try:
            conversation_id = int(conversation_id)

            # 复用守卫：本会话已有补算任务时不重复启动（防取消事件被替换）
            service = getattr(self, "_sentiment_backfill_service", None)
            if service is not None:
                running = service.find_running_task(conversation_id)
                if running:
                    return {
                        "ok": True, "task_id": running, "status": "started",
                        "message": "已有进行中的情感补算，已复用",
                    }

            # 互斥守卫 1：全面分析进行中（它会自己补齐情感缓存）
            affinity_service = getattr(self, "_affinity_service", None)
            if affinity_service is not None and affinity_service.has_running_task():
                return {"ok": False, "error": "全面分析进行中，请等待其完成后再补算情感"}

            from ...services.analysis.sentiment_backfill_service import SentimentBackfillService

            if service is None:
                service = SentimentBackfillService()
                self._sentiment_backfill_service = service

            coverage = service.get_coverage(conversation_id)
            if not coverage["need_backfill"]:
                return {"ok": True, "status": "complete", "coverage": coverage}

            task_id = f"sentibf_{conversation_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            service.register_task(task_id, conversation_id)
            self._sentiment_backfill_cancel_event = threading.Event()

            def _run():
                try:
                    service.run_backfill(
                        conversation_id, self._sentiment_backfill_cancel_event, task_id
                    )
                except Exception as e:
                    logger.error(f"[Bridge] 异步情感补算失败: {e}")
                    import traceback
                    traceback.print_exc()

            threading.Thread(target=_run, daemon=True).start()
            return {"ok": True, "task_id": task_id, "status": "started", "coverage": coverage}
        except Exception as e:
            logger.error(f"[Bridge] 启动情感补算失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_sentiment_backfill_progress(self, task_id: str) -> dict:
        """查询情感补算任务进度（running/completed/failed/cancelled）。"""
        service = getattr(self, "_sentiment_backfill_service", None)
        if not service:
            return {
                "ok": False, "error": "补算服务未初始化", "status": "not_found",
                "progress_percent": 0, "current_step": "",
            }
        progress = service.get_progress(task_id)
        if not progress:
            return {
                "ok": False, "error": "补算任务不存在或已失效", "status": "not_found",
                "progress_percent": 0, "current_step": "",
            }
        response = {
            "ok": True,
            "status": progress["status"],
            "progress_percent": progress["progress_percent"],
            "current_step": progress["current_step"],
        }
        if progress["status"] == "failed":
            response["error"] = progress.get("error") or "未知错误"
        return response

    def cancel_sentiment_backfill(self) -> dict:
        """取消正在进行的情感补算（已写入批次的缓存保留，续跑自动跳过）。"""
        cancel_event = getattr(self, "_sentiment_backfill_cancel_event", None)
        if cancel_event is None:
            return {"ok": False, "error": "没有进行中的补算任务"}
        cancel_event.set()
        return {"ok": True}

    # ------------------------------------------------------------------
    # 大五人格印象（双层：本地统计基础层 + LLM 增强层）
    # ------------------------------------------------------------------

    def get_big5_impressions(self, conversation_id: int, account_wxid: str = "") -> dict:
        """读取双方大五画像（未过期缓存优先，无模型也总有基础层）。"""
        try:
            if not conversation_id:
                return {"ok": False, "error": "缺少参数: conversation_id"}
            from ...services.analysis.personality_impression_service import (
                PersonalityImpressionService,
            )

            service = getattr(self, "_big5_service", None)
            if service is None:
                service = PersonalityImpressionService()
                self._big5_service = service
            return service.get_impressions(int(conversation_id), account_wxid or "")
        except Exception as e:
            logger.error(f"[Bridge] 获取大五画像失败: {e}")
            return {"ok": False, "error": str(e)}

    def enhance_big5_impressions(self, conversation_id: int, account_wxid: str = "") -> dict:
        """LLM 增强大五画像（±15 有界校正附证据；远程模型过脱敏红线，失败即阻断）。"""
        try:
            if not conversation_id:
                return {"ok": False, "error": "缺少参数: conversation_id"}
            from ...services.analysis.personality_impression_service import (
                PersonalityImpressionService,
            )

            service = getattr(self, "_big5_service", None)
            if service is None:
                service = PersonalityImpressionService()
                self._big5_service = service
            return service.enhance(int(conversation_id), account_wxid or "")
        except Exception as e:
            logger.error(f"[Bridge] 增强大五画像失败: {e}")
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 分享海报（前端 html2canvas 合成 → save_share_image 落盘）
    # ------------------------------------------------------------------

    def get_poster_payload(
        self, conversation_id: int, from_date: str, to_date: str, account_wxid: str = ""
    ) -> dict:
        """组装海报数据（统计/迷你曲线/top词/里程碑/金句/大五/头像 base64）。"""
        try:
            if not conversation_id:
                return {"ok": False, "error": "缺少参数: conversation_id"}
            from ...services.analysis.deep_analysis_service import DeepAnalysisService

            from_ts = int(datetime.strptime(from_date, "%Y-%m-%d").timestamp())
            to_ts = int(
                datetime.strptime(to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
            )
            service = DeepAnalysisService()
            return service.build_poster_payload(
                int(conversation_id), from_ts, to_ts, account_wxid or ""
            )
        except ValueError as e:
            return {"ok": False, "error": f"参数格式错误: {e}"}
        except Exception as e:
            logger.error(f"[Bridge] 获取海报数据失败: {e}")
            return {"ok": False, "error": str(e)}

    def save_share_image(self, image_data: str, file_name: str = "") -> dict:
        """保存 html2canvas 合成的 PNG 到导出目录（chrono_trace_export）。

        校验：PNG magic、≤20MB、文件名白名单化（剥离路径穿越）。
        """
        import base64
        import tempfile
        from pathlib import Path

        try:
            data = str(image_data or "")
            if "," in data:
                data = data.split(",", 1)[1]
            try:
                blob = base64.b64decode(data, validate=False)
            except Exception:
                return {"ok": False, "error": "图像数据不是有效的 base64"}
            if not blob.startswith(b"\x89PNG"):
                return {"ok": False, "error": "仅支持 PNG 图像"}
            if len(blob) > 20 * 1024 * 1024:
                return {"ok": False, "error": "图像超过 20MB 上限"}
            # 白名单化文件名：仅保留常见安全字符，杜绝路径穿越
            safe_name = "".join(
                c for c in str(file_name or "分享海报") if c.isalnum() or c in "（）()-_ ."
            ).strip() or "分享海报"
            if not safe_name.lower().endswith(".png"):
                safe_name += ".png"
            out_dir = Path(tempfile.gettempdir()) / "chrono_trace_export"
            out_dir.mkdir(exist_ok=True)
            file_path = out_dir / safe_name
            file_path.write_bytes(blob)
            logger.info(f"[Bridge] 分享图已保存: {file_path}")
            return {"ok": True, "file_path": str(file_path), "file_name": file_path.name}
        except Exception as e:
            logger.error(f"[Bridge] 保存分享图失败: {e}")
            return {"ok": False, "error": str(e)}

    def open_export_folder(self) -> dict:
        """在系统文件管理器中打开导出目录（chrono_trace_export）。"""
        import tempfile
        import webbrowser
        from pathlib import Path

        try:
            folder = Path(tempfile.gettempdir()) / "chrono_trace_export"
            folder.mkdir(exist_ok=True)
            webbrowser.open(folder.as_uri())
            return {"ok": True, "path": str(folder)}
        except Exception as e:
            logger.error(f"[Bridge] 打开导出目录失败: {e}")
            return {"ok": False, "error": str(e)}
