"""情感补算任务服务：sentiment_cache 缺口探测与后台补算的任务三件套。

背景：凡跑过「全面分析」的会话 sentiment_cache 全量覆盖；未分析过的会话
（真实库占绝大多数）在时光深度页需要先补算逐条情感（ONNX 本地推理，
大会话首跑数分钟），结果永久缓存、后续全面分析直接复用。

任务状态机与互斥：
- 与全面分析共用同一 ONNX 模型会话，并发会争抢推理资源——两侧互设守卫
  （start 见全面分析活任务即拒，analyze_affinity 见补算活任务即拒）。
- 状态沿用好感度任务口径：running / completed / failed / cancelled；
  find_running_task 语义一致（重复启动复用，防取消事件被替换）。
"""
import threading
import time
from typing import Any, Dict, Optional

from ...db.connection import get_db

import logging

logger = logging.getLogger(__name__)

# 终态集合：到达后任务不再占用「运行中」名额
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class SentimentBackfillService:
    """情感补算：覆盖率查询 + 任务注册/进度/取消 + 执行。"""

    def __init__(self, orchestrator=None):
        # 构造器注入（测试传桩）；生产路径走真实编排器
        if orchestrator is None:
            from .preprocessing_orchestrator import PreprocessingOrchestrator

            orchestrator = PreprocessingOrchestrator()
        self._orchestrator = orchestrator

        self._lock = threading.Lock()
        # task_id -> {conversation_id, status, progress_percent, current_step, error}
        self._tasks: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 覆盖率
    # ------------------------------------------------------------------

    @staticmethod
    def get_coverage(conversation_id: int) -> Dict[str, Any]:
        """统计会话文本消息的 sentiment_cache 覆盖情况（补算缺口的依据）。"""
        row = get_db().execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN sc.message_id IS NOT NULL THEN 1 ELSE 0 END)
            FROM messages m
            LEFT JOIN sentiment_cache sc ON sc.message_id = m.id
            WHERE m.conversation_id = ?
                AND m.message_type = 1
                AND m.content IS NOT NULL
                AND TRIM(m.content) != ''
        """, (conversation_id,)).fetchone()
        total = int(row[0] or 0)
        cached = int(row[1] or 0)
        missing = total - cached
        return {
            "total": total,
            "cached": cached,
            "missing": missing,
            "ratio": round(cached / total, 3) if total else 1.0,
            "need_backfill": missing > 0,
        }

    # ------------------------------------------------------------------
    # 任务三件套（口径对齐 AffinityAnalysisService.register_task/find_running_task）
    # ------------------------------------------------------------------

    def register_task(self, task_id: str, conversation_id: int) -> Dict[str, Any]:
        task = {
            "conversation_id": int(conversation_id),
            "status": "running",
            "progress_percent": 0,
            "current_step": "准备补算",
            "error": None,
        }
        with self._lock:
            self._tasks[task_id] = task
        return task

    def find_running_task(self, conversation_id: int) -> Optional[str]:
        """该会话仍在运行的补算任务 ID（重复启动时复用）。"""
        with self._lock:
            for task_id, task in self._tasks.items():
                if task["conversation_id"] == int(conversation_id) and task["status"] not in _TERMINAL_STATUSES:
                    return task_id
        return None

    def has_running_task(self) -> bool:
        """任一会话的补算是否仍在运行（与全面分析互斥的全局守卫）。"""
        with self._lock:
            return any(task["status"] not in _TERMINAL_STATUSES for task in self._tasks.values())

    def get_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def _update(self, task_id: str, **fields) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.update(fields)

    # ------------------------------------------------------------------
    # 执行（后台线程内调用；不直接查库——覆盖率由调用方线程先查）
    # ------------------------------------------------------------------

    def run_backfill(
        self,
        conversation_id: int,
        cancel_event: threading.Event,
        task_id: str,
    ) -> Dict[str, Any]:
        """跑补算并维护任务状态。取消时已写入批次的缓存保留（续跑自动跳过）。"""
        progress_records = []

        def _on_progress(fraction: float) -> None:
            percent = int(5 + min(fraction, 1.0) * 90)
            progress_records.append(percent)
            self._update(task_id, progress_percent=percent, current_step="逐条情感推理")

        try:
            self._update(task_id, progress_percent=2, current_step="读取消息")
            self._orchestrator.run_sentiment_backfill(
                conversation_id, cancel_event=cancel_event, progress_cb=_on_progress
            )
        except Exception as e:
            if cancel_event.is_set() or "已被用户取消" in str(e):
                self._update(task_id, status="cancelled", current_step="已取消", finished_at=time.time())
                logger.info(f"[情感补算] 会话 {conversation_id} 被用户取消")
            else:
                self._update(
                    task_id, status="failed", error=str(e), current_step="失败", finished_at=time.time()
                )
                logger.error(f"[情感补算] 会话 {conversation_id} 失败: {e}")
            return self.get_progress(task_id)

        # 终态收尾只更新任务字典——不再查库（后台线程与 sqlite 连接的
        # 线程绑定冲突；覆盖率由前端完成后自行刷新 get_sentiment_coverage）
        self._update(
            task_id,
            status="completed",
            progress_percent=100,
            current_step="完成",
            finished_at=time.time(),
        )
        logger.info(f"[情感补算] 会话 {conversation_id} 完成")
        return self.get_progress(task_id)

    # ------------------------------------------------------------------
    # 过期任务清理（防字典无界增长；终态任务保留近期一段供前端收尾查询）
    # ------------------------------------------------------------------

    def prune_finished(self, keep_seconds: int = 3600) -> None:
        cutoff = time.time() - keep_seconds
        with self._lock:
            stale = [
                task_id for task_id, task in self._tasks.items()
                if task["status"] in _TERMINAL_STATUSES
                and task.get("finished_at", 0) and task["finished_at"] < cutoff
            ]
            for task_id in stale:
                self._tasks.pop(task_id, None)
