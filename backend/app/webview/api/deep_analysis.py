"""时光深度分析（分桶情绪演变/词云演变/里程碑/情感补算）Bridge API。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# 任务注册锁：本 mixin 内所有「互斥检查 + 任务注册」临界区共用，消除
# 检查-后-注册（TOCTOU）竞态——start_sentiment_backfill 与 analyze_affinity
# 的互斥、大五增强与画像演变的同会话单飞。
# 放本模块——affinity.py 的服务类每次 analyze_affinity 都被热 reload，
# 锁放那边会随模块重建而失效；本模块不参与 reload，进程内唯一。
# 临界区只包检查+注册（微秒级），重活（LLM/ONNX）在锁外跑，无嵌套死锁。
_ONNX_TASK_LOCK = threading.Lock()


class DeepAnalysisApiMixin:
    """时光深度：Analytics 第六 tab 的后端入口"""

    def get_deep_analysis(
        self,
        conversation_id: int,
        from_date: str,
        to_date: str,
        bucket: str = "week",
        word_segments: int = 4,
    ) -> dict:
        """获取时光深度聚合数据（分桶情绪序列+覆盖率、拐点、词云演变、里程碑、好感度落点）。

        Args:
            conversation_id: 会话ID
            from_date: 开始日期 "2025-01-01"
            to_date: 结束日期 "2025-12-31"
            bucket: 分桶粒度 day/week/month/year（默认 week）
            word_segments: 词云演变分段数 2~6（默认 4）

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
                int(conversation_id), from_ts, to_ts, bucket=bucket,
                word_segments=int(word_segments),
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

        互斥：与全面分析共用 ONNX 推理会话，任一侧运行中即拒绝启动；
        补算自身也全局单飞（不同会话并发会争抢推理资源并互相覆盖取消事件）。
        缺口为 0 时直接返回 complete，不建任务。「守卫检查 + 任务注册」整体
        持 _ONNX_TASK_LOCK（与 analyze_affinity 同锁），杜绝并发双注册。
        """
        try:
            conversation_id = int(conversation_id)

            service = getattr(self, "_sentiment_backfill_service", None)
            with _ONNX_TASK_LOCK:
                if service is not None:
                    # 复用守卫：本会话已有补算任务时不重复启动（防取消事件被替换；
                    # 含问答触发的语义索引任务——它同样在写情感+向量缓存）
                    running = service.find_running_task(conversation_id)
                    if running:
                        return {
                            "ok": True, "task_id": running, "status": "started",
                            "message": "已有进行中的补算任务，已复用",
                        }
                    # 互斥守卫 0：任一会话的补算运行中（全局单飞，含问答触发的
                    # 语义索引懒补——两类任务共用本服务实例与任务字典）——并发
                    # 补算既争抢 ONNX 会话，也互相覆盖取消事件使先发任务停不掉
                    if service.has_running_task():
                        return {"ok": False, "error": "另一会话的补算进行中（情感/语义索引），请等待其完成"}

                # 互斥守卫 1：全面分析进行中（它会自己补齐情感缓存）——必须
                # 检查全部历史服务实例：analyze_affinity 每次重建实例，旧实例
                # 上运行中的任务对最新实例不可见
                for affinity_service in self._all_affinity_services():
                    if affinity_service.has_running_task():
                        return {"ok": False, "error": "全面分析进行中，请等待其完成后再补算情感"}

                if service is None:
                    from ...services.analysis.sentiment_backfill_service import SentimentBackfillService

                    service = SentimentBackfillService()
                    self._sentiment_backfill_service = service

                service.prune_finished()  # 顺带清理过期终态任务，防字典无界增长

                coverage = service.get_coverage(conversation_id)
                if not coverage["need_backfill"]:
                    return {"ok": True, "status": "complete", "coverage": coverage}

                task_id = f"sentibf_{conversation_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                service.register_task(task_id, conversation_id)
                # 每任务独立取消事件：单实例属性会被后发任务覆盖，先发任务将无法取消
                cancel_event = threading.Event()
                if not hasattr(self, "_sentiment_backfill_cancel_events"):
                    self._sentiment_backfill_cancel_events = {}
                self._sentiment_backfill_cancel_events[task_id] = cancel_event

            def _run():
                try:
                    service.run_backfill(conversation_id, cancel_event, task_id)
                except Exception as e:
                    logger.error(f"[Bridge] 异步情感补算失败: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    self._sentiment_backfill_cancel_events.pop(task_id, None)

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

    def cancel_sentiment_backfill(self, task_id: str = "") -> dict:
        """取消情感补算任务（已写入批次的缓存保留，续跑自动跳过）。

        按任务 id 精确取消；不带 id 时回退取消最近启动的运行中任务
        （取消事件按任务独立存储，不再有被覆盖的单实例属性）。
        """
        events = getattr(self, "_sentiment_backfill_cancel_events", None) or {}
        task_id = str(task_id or "")
        if task_id:
            event = events.get(task_id)
            if event is None:
                return {"ok": False, "error": "指定任务不在运行中"}
            event.set()
            return {"ok": True}
        if not events:
            return {"ok": False, "error": "没有进行中的补算任务"}
        # dict 保插入序：末位即最新启动且仍在运行的任务
        events[next(reversed(events))].set()
        return {"ok": True}

    # ------------------------------------------------------------------
    # 大五人格印象（双层：本地统计基础层 + LLM 增强层）
    # ------------------------------------------------------------------

    def get_big5_impressions(
        self, conversation_id: int, account_wxid: str = "",
        from_ts: int = 0, to_ts: int = 0,
    ) -> dict:
        """读取双方大五画像（未过期缓存优先，无模型也总有基础层）。

        可选 from_ts/to_ts（秒级闭区间）为指定时间窗——大五演变面板按段
        取数/逐段增强用，须与 _big5_evolution 的段边界一致（缓存键含窗维）；
        缺省为全会话（TA 画像页静态大五）。
        """
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
            win_from, win_to = self._optional_window_ts(from_ts, to_ts)
            return service.get_impressions(
                int(conversation_id), account_wxid or "", from_ts=win_from, to_ts=win_to
            )
        except ValueError as e:
            return {"ok": False, "error": f"参数格式错误: {e}"}
        except Exception as e:
            logger.error(f"[Bridge] 获取大五画像失败: {e}")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _optional_window_ts(from_ts, to_ts):
        """可选秒级窗归一：双缺省 (None, None)=全会话；只给一半视为参数错误。"""
        if not from_ts and not to_ts:
            return None, None
        if not from_ts or not to_ts:
            raise ValueError("时间窗需同时提供起止时间戳")
        return int(from_ts), int(to_ts)

    def enhance_big5_impressions(
        self, conversation_id: int, account_wxid: str = "",
        from_ts: int = 0, to_ts: int = 0,
    ) -> dict:
        """LLM 增强大五画像（±15 有界校正附证据；远程模型过脱敏红线，失败即阻断）。

        同会话同窗单飞（请求最长 90s，重复点击直接拒）；带取消事件——
        cancel_big5_impressions 可中断进行中的增强（需传同一时间窗）。
        可选 from_ts/to_ts 为指定时间窗（大五演变逐段增强）。
        """
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

            win_from, win_to = self._optional_window_ts(from_ts, to_ts)
            key = (int(conversation_id), account_wxid or "", win_from or 0, win_to or 0)
            # 「已在运行检查 + 注册」临界区持锁（并发双击防双注册互相覆盖取消事件）
            with _ONNX_TASK_LOCK:
                running = getattr(self, "_big5_enhance_events", None)
                if running is None:
                    running = {}
                    self._big5_enhance_events = running
                if key in running:
                    return {"ok": False, "reason": "already_running",
                            "message": "AI 校正进行中，请稍候或先取消"}
                cancel_event = threading.Event()
                running[key] = cancel_event
            try:
                return service.enhance(
                    int(conversation_id), account_wxid or "", cancel_event=cancel_event,
                    from_ts=win_from, to_ts=win_to,
                )
            finally:
                running.pop(key, None)
        except ValueError as e:
            return {"ok": False, "error": f"参数格式错误: {e}"}
        except Exception as e:
            logger.error(f"[Bridge] 增强大五画像失败: {e}")
            return {"ok": False, "error": str(e)}

    def cancel_big5_impressions(
        self, conversation_id: int, account_wxid: str = "",
        from_ts: int = 0, to_ts: int = 0,
    ) -> dict:
        """取消进行中的大五 AI 校正（LLM 请求最长 90s，不能让用户只能干等）。

        时间窗需与启动增强时一致（单飞键含窗维）。
        """
        try:
            win_from, win_to = self._optional_window_ts(from_ts, to_ts)
        except ValueError:
            win_from, win_to = None, None
        running = getattr(self, "_big5_enhance_events", None) or {}
        event = running.get(
            (int(conversation_id or 0), account_wxid or "", win_from or 0, win_to or 0)
        )
        if event is None:
            return {"ok": False, "error": "没有进行中的 AI 校正"}
        event.set()
        return {"ok": True}

    # ------------------------------------------------------------------
    # 画像演变（前后半窗双画像对比，单飞可取消）
    # ------------------------------------------------------------------

    def generate_profile_evolution(
        self,
        conversation_id: int,
        from_date: str,
        to_date: str,
        include_self: bool = False,
        force: bool = False,
        account_wxid: str = "",
        segments: int = 2,
    ) -> dict:
        """生成画像演变：时间窗均分 segments 段（2~6 默认 2），分别取/生成 custom 快照画像。

        同会话单飞（一次最多 segments×(1+含我) 次 LLM 调用，重复点击直接拒）；
        快照缓存精确键命中即跳过 LLM 增量续跑；``force=True`` 全部重算。
        """
        try:
            if not conversation_id:
                return {"ok": False, "error": "缺少参数: conversation_id"}
            if not from_date or not to_date:
                return {"ok": False, "error": "缺少日期参数，请先选择时间范围"}
            from ...services.analysis.profile_evolution_service import ProfileEvolutionService

            from_ts = int(datetime.strptime(from_date, "%Y-%m-%d").timestamp())
            to_ts = int(
                datetime.strptime(to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
            )

            key = (int(conversation_id), account_wxid or "")
            # 「已在运行检查 + 注册」临界区持锁（并发双击防双注册互相覆盖取消事件）
            with _ONNX_TASK_LOCK:
                running = getattr(self, "_profile_evolution_events", None)
                if running is None:
                    running = {}
                    self._profile_evolution_events = running
                if key in running:
                    return {"ok": False, "reason": "already_running",
                            "message": "画像演变生成中，请稍候或先取消"}
                cancel_event = threading.Event()
                running[key] = cancel_event
            try:
                return ProfileEvolutionService().generate(
                    int(conversation_id), from_ts, to_ts,
                    account_wxid=account_wxid or "",
                    include_self=bool(include_self),
                    force=bool(force),
                    cancel_event=cancel_event,
                    segments=int(segments),
                )
            finally:
                running.pop(key, None)
        except ValueError as e:
            return {"ok": False, "error": f"参数格式错误: {e}"}
        except Exception as e:
            logger.error(f"[Bridge] 生成画像演变失败: {e}")
            return {"ok": False, "error": str(e)}

    def cancel_profile_evolution(self, conversation_id: int, account_wxid: str = "") -> dict:
        """取消进行中的画像演变（一次最多 segments×(1+含我) 次 LLM 调用，不能让用户只能干等）。"""
        running = getattr(self, "_profile_evolution_events", None) or {}
        event = running.get((int(conversation_id or 0), account_wxid or ""))
        if event is None:
            return {"ok": False, "error": "没有进行中的画像演变"}
        event.set()
        return {"ok": True}

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
            if not from_date or not to_date:
                return {"ok": False, "error": "缺少日期参数，请先选择时间范围"}
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
