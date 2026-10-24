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

from .task_registry import TERMINAL_STATUSES, is_running

import logging

logger = logging.getLogger(__name__)


class SentimentBackfillService:
    """情感补算：覆盖率查询 + 任务注册/进度/取消 + 执行。

    两类任务共用本服务与 _tasks 字典：sentiment（情感缓存缺口，走编排器）
    与 embedding（问答向量缺口，直嵌补 NULL 行）。共用字典使「全局单飞」
    与「与全面分析互斥」对两类任务同时成立，无需另起注册表。
    """

    def __init__(self, orchestrator=None, sentiment_service=None):
        # 构造器注入（测试传桩）；生产路径走真实编排器
        if orchestrator is None:
            from .preprocessing_orchestrator import PreprocessingOrchestrator

            orchestrator = PreprocessingOrchestrator()
        self._orchestrator = orchestrator
        # 情感服务懒构造：纯 sentiment 任务用不到嵌入，构造即建会拖起
        # SentimentService 单例的实时情感预加载
        self._sentiment_service = sentiment_service

        self._lock = threading.Lock()
        # task_id -> {conversation_id, kind, status, progress_percent, current_step, error}
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def _embedding_service(self):
        if self._sentiment_service is None:
            from .sentiment_service import SentimentService

            self._sentiment_service = SentimentService()
        return self._sentiment_service

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

    @staticmethod
    def get_embedding_coverage(conversation_id: int) -> Dict[str, Any]:
        """统计会话文本消息的向量覆盖情况（问答语义索引懒补的缺口依据）。"""
        row = get_db().execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN sc.embedding_vector IS NOT NULL THEN 1 ELSE 0 END)
            FROM messages m
            LEFT JOIN sentiment_cache sc ON sc.message_id = m.id
            WHERE m.conversation_id = ?
                AND m.message_type = 1
                AND m.content IS NOT NULL
                AND TRIM(m.content) != ''
        """, (conversation_id,)).fetchone()
        total = int(row[0] or 0)
        embedded = int(row[1] or 0)
        missing = total - embedded
        return {
            "total": total,
            "embedded": embedded,
            "missing": missing,
            "ratio": round(embedded / total, 3) if total else 1.0,
            "need_backfill": missing > 0,
        }

    # ------------------------------------------------------------------
    # 任务三件套（口径对齐 AffinityAnalysisService.register_task/find_running_task）
    # ------------------------------------------------------------------

    def register_task(
        self, task_id: str, conversation_id: int, kind: str = "sentiment"
    ) -> Dict[str, Any]:
        task = {
            "conversation_id": int(conversation_id),
            "kind": str(kind or "sentiment"),
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
                if task["conversation_id"] == int(conversation_id) and is_running(task["status"]):
                    return task_id
        return None

    def has_running_task(self) -> bool:
        """任一会话的补算是否仍在运行（与全面分析互斥的全局守卫）。"""
        with self._lock:
            return any(is_running(task["status"]) for task in self._tasks.values())

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
        def _on_progress(fraction: float) -> None:
            percent = int(5 + min(fraction, 1.0) * 90)
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

    def run_embedding_backfill(
        self,
        conversation_id: int,
        cancel_event: threading.Event,
        task_id: str,
    ) -> Dict[str, Any]:
        """嵌入懒补：补齐 sentiment_cache 向量缺口（问答向量通道数据源）。

        阶段 B 先行（无 sentiment 行的消息走完整 analyze_batch——真极性
        +向量，不用假极性污染情感统计）；阶段 A 补存量行的 NULL 向量
        （embed_texts_batch 直嵌 + UPDATE）。取消保留已写批次，续跑自动
        跳过；终态收尾不查库（后台线程与 sqlite 连接线程绑定冲突）。
        """
        try:
            self._update(task_id, progress_percent=2, current_step="读取向量缺口")
            filled = self._embedding_backfill_pass(conversation_id, cancel_event, task_id)
        except Exception as e:
            if cancel_event.is_set() or "已被用户取消" in str(e):
                self._update(task_id, status="cancelled", current_step="已取消", finished_at=time.time())
                logger.info(f"[语义索引补算] 会话 {conversation_id} 被用户取消")
            else:
                self._update(
                    task_id, status="failed", error=str(e), current_step="失败", finished_at=time.time()
                )
                logger.error(f"[语义索引补算] 会话 {conversation_id} 失败: {e}")
            return self.get_progress(task_id)

        self._update(
            task_id,
            status="completed",
            progress_percent=100,
            current_step="完成",
            finished_at=time.time(),
        )
        logger.info(f"[语义索引补算] 会话 {conversation_id} 完成（补 {filled} 条向量）")
        return self.get_progress(task_id)

    _EMBED_BATCH_SIZE = 500

    def _embedding_backfill_pass(
        self,
        conversation_id: int,
        cancel_event: threading.Event,
        task_id: str,
    ) -> int:
        """两阶段补齐；返回成功写入的向量条数（含阶段 B 新建行）。"""
        service = self._embedding_service()
        text_filter = """
            m.conversation_id = ?
            AND m.message_type = 1
            AND m.content IS NOT NULL
            AND TRIM(m.content) != ''
        """
        coverage = self.get_embedding_coverage(conversation_id)
        total_missing = coverage["missing"]
        filled = 0
        done = 0

        def _report(step: str) -> None:
            percent = int(5 + min(done / total_missing, 1.0) * 90) if total_missing else 95
            self._update(task_id, progress_percent=percent, current_step=step)

        # 阶段 B：无 sentiment_cache 行的消息——完整情感+向量分析。
        # m.id 水位游标推进（ORDER BY m.id 顺序处理）：写入失败行被
        # 水位跳过（缺口保留，环境恢复后续跑覆盖查询会再捞到），
        # 每轮反连接只扫未处理前缀而非全量重扫。
        cursor_id = 0
        while True:
            if cancel_event.is_set():
                raise Exception("分析已被用户取消")
            rows = get_db().execute(
                f"""
                SELECT m.id, m.content
                FROM messages m
                LEFT JOIN sentiment_cache sc ON sc.message_id = m.id
                WHERE {text_filter} AND sc.message_id IS NULL AND m.id > ?
                ORDER BY m.id
                LIMIT ?
                """,
                (conversation_id, cursor_id, self._EMBED_BATCH_SIZE),
            ).fetchall()
            if not rows:
                break
            cursor_id = rows[-1]["id"]
            results = service.analyze_batch(
                [row["content"] for row in rows], include_embeddings=True
            )
            service.batch_cache_sentiments([
                {
                    "message_id": row["id"],
                    "polarity": result["polarity"],
                    "intensity": result["intensity"],
                    "embedding": result.get("embedding"),
                }
                for row, result in zip(rows, results)
            ])
            filled += len(rows)
            done += len(rows)
            _report("语义索引推理（新消息）")

        # 阶段 A：行在但向量为 NULL 的存量消息——只补嵌入（水位游标同 B）
        from .sentiment_service import pack_embedding

        cursor_id = 0
        while True:
            if cancel_event.is_set():
                raise Exception("分析已被用户取消")
            rows = get_db().execute(
                f"""
                SELECT m.id, m.content
                FROM messages m
                JOIN sentiment_cache sc ON sc.message_id = m.id
                WHERE {text_filter} AND sc.embedding_vector IS NULL AND m.id > ?
                ORDER BY m.id
                LIMIT ?
                """,
                (conversation_id, cursor_id, self._EMBED_BATCH_SIZE),
            ).fetchall()
            if not rows:
                break
            cursor_id = rows[-1]["id"]
            vectors = service.embed_texts_batch([row["content"] for row in rows])
            updates = [
                (blob, row["id"])
                for row, vector in zip(rows, vectors)
                if (blob := pack_embedding(vector)) is not None
            ]
            if updates:
                get_db().executemany(
                    "UPDATE sentiment_cache SET embedding_vector = ? WHERE message_id = ?",
                    updates,
                )
                get_db().commit()
            filled += len(updates)
            done += len(rows)
            _report("语义索引推理（存量补嵌）")
            if not updates:
                # 零向量等退化输出写不进（pack 落 None）——整批无进展即收工，
                # 残留行等下次覆盖查询再试，避免同批反复捞回死循环
                break
        return filled

    # ------------------------------------------------------------------
    # 过期任务清理（防字典无界增长；终态任务保留近期一段供前端收尾查询）
    # ------------------------------------------------------------------

    def prune_finished(self, keep_seconds: int = 3600) -> None:
        cutoff = time.time() - keep_seconds
        with self._lock:
            stale = [
                task_id for task_id, task in self._tasks.items()
                if task["status"] in TERMINAL_STATUSES
                and task.get("finished_at", 0) and task["finished_at"] < cutoff
            ]
            for task_id in stale:
                self._tasks.pop(task_id, None)
