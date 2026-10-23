"""章节摘要金字塔：月摘要 → 章节摘要（LLM，增量缓存）。

C1 的章节检测是纯统计层；本模块补语义层——把全量语料按月压成结构化
月报（话题/动态/事件/语气），再按 C1 章节归并成章节叙事。产出注入
画像 prompt（profile_chapter_digest），让 rolling 画像看得到全部
年份的语义（此前 90 天窗只罩住长会话尾部）。

口径与纪律（详见 docs/goals/persona-chapters-goal.md C2）：
- **增量缓存**：月摘要按 (conversation_id, month_key, version) 唯一键
  落库，任务重跑/续跑自动跳过已就绪月；月是稳态单位，新月份才补算
  （验收：首跑 ~30 次调用后增量 1-2 次/月）。
- **版本失明**：SUMMARY_VERSION +1 时旧月/章摘要自然失明重算（KISS
  不迁移）；章节摘要另带章节边界指纹，C1 章节口径变化或边界漂移即
  失明（月摘要不浪费）。
- **脱敏红线**：远程模型必经 PrivacyRedactor——月摘要输入是全时段
  原文（比画像窗口样本暴露面大得多），脱敏器构造失败整任务阻断
  （fail-closed，绝不降级发原文）；单条脱敏异常丢条继续。本地
  loopback 模型免脱敏。
- **采样等距稀释**：单月喂 LLM 的原文按字符预算（24k）与条数上限
  （3000）等距抽稀，保时间分布（对齐大五增强层纪律，不做头截断）。
- **任务三件套**：全局单飞（LLM 调用串行，并发打爆 API 无意义）、
  按任务独立取消事件、取消保留已落库月；状态机沿用
  running/completed/failed/cancelled。
- **观察叙事**：摘要措辞只描述可观察事实，不做关系诊断（prompt 纪律
  与 C1 归因一致）。
"""
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...db.connection import get_db
from .relationship_chapters import CHAPTERS_VERSION

logger = logging.getLogger(__name__)

# 摘要口径版本：月/章 prompt 字段、采样预算、归并规则变化时 +1（旧摘要失明重算）
SUMMARY_VERSION = 1
# 单月喂 LLM 的原文预算（字符）：超预算等距抽稀保时间分布
MONTH_CHAR_BUDGET = 24000
# 单月条数上限（主力期单月可上万条，先按条抽稀再进字符预算）
MONTH_MAX_MESSAGES = 3000
# 单次 LLM 调用超时（秒）
SUMMARY_LLM_TIMEOUT = 120

_MONTH_SYSTEM_PROMPT = (
    "你是对话记录分析助手。把一个月的聊天记录压缩成结构化月报，供后续"
    "长期关系画像引用。只描述记录中可观察到的事实，不做心理诊断或关系"
    "评判，不猜测记录之外的事。直接输出 JSON，不要输出其他文字。"
)

_CHAPTER_SYSTEM_PROMPT = (
    "你是关系叙事助手。把连续数月的月报归并成一段章节叙事，供长期画像"
    "引用。用观察叙事措辞（描述互动与走向，不下关系结论）。直接输出 "
    "JSON，不要输出其他文字。"
)


def _json_candidates(text: str) -> List[str]:
    """按出现序返回可解析的 JSON 对象串（思考模型真答案在末尾，倒序尝试）。

    与 rag/fact_llm 同策略：思考模型把推理写进 content 且会回显模板 JSON，
    「首个 { 到末个 }」跨度必然拼出非法串。"""
    objs: List[str] = []
    depth = 0
    start: Optional[int] = None
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objs.append(text[start:i + 1])
                start = None
    parsed = []
    for cand in objs:
        try:
            json.loads(cand)
        except Exception:
            continue
        parsed.append(cand)
    if not parsed:
        return []
    if "</think>" in text:
        tail = text.rsplit("</think>", 1)[-1]
        tail_ok = [c for c in parsed if tail.find(c) >= 0]
        if tail_ok:
            return tail_ok
    return parsed


def _summary_fp(from_ts: int, to_ts: int) -> str:
    """章节摘要指纹：章节边界 + C1 口径版本（边界漂移/升版即失明重算）。"""
    return f"v{CHAPTERS_VERSION}:{int(from_ts)}-{int(to_ts)}"


class ChapterSummaryService:
    """月摘要 + 章节摘要：任务三件套 + 执行 + 覆盖查询。"""

    def __init__(
        self,
        llm_call: Optional[Callable[[str, str], str]] = None,
        redactor_factory: Optional[Callable[[], Any]] = None,
        chapters_provider: Optional[Callable[[int], dict]] = None,
    ):
        """构造注入（测试传桩）。生产路径：llm_call 走活动模型 chat 接口。

        - llm_call(system_prompt, user_prompt) -> content 文本
        - redactor_factory() -> PrivacyRedactor 或 None（本地模型传 () -> None）
        - chapters_provider(conversation_id) -> C1 章节 payload（缺省用
          RelationshipChapterService，服务实例内带缓存）
        """
        self._llm_call = llm_call
        self._redactor_factory = redactor_factory
        self._chapters_provider = chapters_provider
        self._model_config: Optional[dict] = None
        self._is_remote: Optional[bool] = None

        # RLock：start_task 持锁调 register_task/cancel_task（锁内再取锁），不可重入会死锁
        self._lock = threading.RLock()
        # task_id -> {conversation_id, status, progress_percent, current_step,
        #             months_done, months_total, error}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._cancel_events: Dict[str, threading.Event] = {}

    # ------------------------------------------------------------------
    # 模型 / 脱敏器装配
    # ------------------------------------------------------------------

    def _resolve_model(self) -> Optional[dict]:
        if self._model_config is None and self._llm_call is None:
            from ..realtime.rag.fact_llm import get_active_model_config

            self._model_config = get_active_model_config()
        return self._model_config

    def _resolve_remote(self) -> bool:
        if self._is_remote is None:
            from ..realtime.rag.config import is_remote_llm_model

            config = self._resolve_model() or {}
            self._is_remote = bool(is_remote_llm_model(config)) if config else False
        return self._is_remote

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if self._llm_call is not None:
            return self._llm_call(system_prompt, user_prompt)

        from ..realtime.llm_http import apply_deep_call_effort, post_json_with_retries

        model = self._resolve_model() or {}
        base_url = str(model.get("api_base_url") or "").rstrip("/")
        headers = {}
        api_key = str(model.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model.get("model_id"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 1024,
            "stream": False,
        }
        apply_deep_call_effort(payload, model)
        body = post_json_with_retries(
            url=f"{base_url}/chat/completions",
            payload=payload,
            headers=headers,
            timeout=SUMMARY_LLM_TIMEOUT,
            log=logger.debug,
            log_prefix="[ChapterSummary]",
        )
        message = (body.get("choices") or [{}])[0].get("message", {})
        content = str(message.get("content") or "")
        if not content:
            # 思考模型偶发把应答写进 reasoning_content——从推理段捞 JSON 候选兜底
            content = _json_candidates(str(message.get("reasoning_content") or ""))[-1] \
                if _json_candidates(str(message.get("reasoning_content") or "")) else ""
        return content

    def _require_redactor(self) -> Optional[Any]:
        """远程模型必须有可用脱敏器，否则阻断（红线：绝不降级发原文）。"""
        if not self._resolve_remote():
            return None  # 本地 loopback 免脱敏
        if self._redactor_factory is None:
            from ..realtime.privacy_redactor import PrivacyRedactor

            self._redactor_factory = lambda: PrivacyRedactor(get_db())
        try:
            redactor = self._redactor_factory()
        except Exception as exc:
            raise RuntimeError(f"脱敏器构造失败，摘要任务阻断: {exc}") from exc
        if redactor is None:
            raise RuntimeError("脱敏器不可用，摘要任务阻断（远程模型不发明文）")
        return redactor

    def _chapters_payload(self, conversation_id: int) -> dict:
        if self._chapters_provider is not None:
            return self._chapters_provider(conversation_id)
        from .relationship_chapters import RelationshipChapterService

        service = getattr(self, "_chapters_service", None) or RelationshipChapterService()
        self._chapters_service = service
        return service.get_chapters(conversation_id)

    # ------------------------------------------------------------------
    # 表
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_tables(conn) -> None:
        existing = {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for name, ddl in (
            (
                "chapter_month_summaries",
                """
                CREATE TABLE chapter_month_summaries(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    month_key TEXT NOT NULL,
                    from_ts INTEGER NOT NULL,
                    to_ts INTEGER NOT NULL,
                    me_count INTEGER NOT NULL DEFAULT 0,
                    other_count INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    model_id TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    UNIQUE(conversation_id, month_key, version)
                )
                """,
            ),
            (
                "chapter_summaries",
                """
                CREATE TABLE chapter_summaries(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    from_ts INTEGER NOT NULL,
                    to_ts INTEGER NOT NULL,
                    summary_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    model_id TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    UNIQUE(conversation_id, fingerprint, version)
                )
                """,
            ),
        ):
            if name not in existing:
                conn.execute(ddl)
        conn.commit()

    @staticmethod
    def _chapter_fingerprint(from_ts: int, to_ts: int) -> str:
        return _summary_fp(from_ts, to_ts)

    # ------------------------------------------------------------------
    # 任务三件套（口径对齐 sentiment_backfill）
    # ------------------------------------------------------------------

    def register_task(self, task_id: str, conversation_id: int) -> Dict[str, Any]:
        task = {
            "conversation_id": int(conversation_id),
            "status": "running",
            "progress_percent": 0,
            "current_step": "准备摘要",
            "months_done": 0,
            "months_total": 0,
            "error": None,
            "finished_at": None,
        }
        with self._lock:
            self._tasks[task_id] = task
            self._cancel_events[task_id] = threading.Event()
        return dict(task)

    def find_running_task(self, conversation_id: int) -> Optional[str]:
        with self._lock:
            for task_id, task in self._tasks.items():
                if task["conversation_id"] == int(conversation_id) and task["status"] == "running":
                    return task_id
        return None

    def has_running_task(self) -> bool:
        with self._lock:
            return any(t["status"] == "running" for t in self._tasks.values())

    def get_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def _update(self, task_id: str, **fields) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task.update(fields)

    def cancel_task(self, task_id: str = "") -> dict:
        """按任务 id 精确取消；缺省取消最近启动的运行中任务。"""
        with self._lock:
            if task_id:
                event = self._cancel_events.get(str(task_id))
                if event is None:
                    return {"ok": False, "error": "指定任务不在运行中"}
                event.set()
                return {"ok": True}
            running = [tid for tid, t in self._tasks.items() if t["status"] == "running"]
            if not running:
                return {"ok": False, "error": "没有进行中的摘要任务"}
            self._cancel_events[running[-1]].set()
            return {"ok": True}

    def _cancelled(self, task_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(task_id)
            return bool(event and event.is_set())

    def prune_finished(self, keep_seconds: int = 3600) -> None:
        cutoff = time.time() - keep_seconds
        with self._lock:
            stale = [
                tid for tid, t in self._tasks.items()
                if t["status"] != "running" and (t.get("finished_at") or 0) and t["finished_at"] < cutoff
            ]
            for tid in stale:
                self._tasks.pop(tid, None)
                self._cancel_events.pop(tid, None)

    # ------------------------------------------------------------------
    # 启动（bridge 入口）
    # ------------------------------------------------------------------

    def start_task(self, conversation_id: int) -> Dict[str, Any]:
        """原子「检查 + 注册 + 起线程」。重复启动复用运行中任务。"""
        conversation_id = int(conversation_id)
        if self._llm_call is None and not self._resolve_model():
            return {"ok": False, "error": "未配置 LLM 模型，请先在设置中添加并启用模型"}
        try:
            self._require_redactor()  # 远程模型脱敏器构造失败在此即拒（不建任务）
        except Exception as exc:
            logger.error("[章节摘要] 启动阻断: %s", exc)
            return {"ok": False, "error": str(exc)}

        with self._lock:
            running = None
            for task_id, task in self._tasks.items():
                if task["conversation_id"] == conversation_id and task["status"] == "running":
                    running = task_id
                    break
            if running:
                return {"ok": True, "task_id": running, "status": "started",
                        "message": "已有进行中的摘要任务，已复用"}
            task_id = f"chsum_{conversation_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            self.register_task(task_id, conversation_id)
            event = self._cancel_events[task_id]

        def _run():
            try:
                self.run(conversation_id, event, task_id)
            except Exception as exc:
                logger.error("[章节摘要] 会话 %s 失败: %s", conversation_id, exc)
                self._update(task_id, status="failed", error=str(exc),
                             current_step="失败", finished_at=time.time())
            finally:
                with self._lock:
                    self._cancel_events.pop(task_id, None)

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True, "task_id": task_id, "status": "started"}

    # ------------------------------------------------------------------
    # 执行（后台线程）
    # ------------------------------------------------------------------

    def run(self, conversation_id: int, cancel_event: threading.Event, task_id: str) -> Dict[str, Any]:
        conn = get_db()
        self._ensure_tables(conn)

        # 0. 脱敏器（远程模型段级阻断语义：构造失败 = 任务失败）
        redactor = self._require_redactor()

        # 1. 章节检测（C1 复用，服务实例内有缓存）
        self._update(task_id, progress_percent=2, current_step="章节检测")
        chapters_payload = self._chapters_payload(conversation_id)
        chapters = chapters_payload.get("chapters") or []

        # 2. 月清单（增量：表里 version 匹配的月跳过）
        self._update(task_id, progress_percent=5, current_step="读取月份")
        months = self._list_months(conn, conversation_id)
        ready_keys = self._ready_month_keys(conn, conversation_id)
        pending = [m for m in months if m["month_key"] not in ready_keys]
        total = len(months)
        self._update(task_id, months_total=total, months_done=total - len(pending))

        # 3. 逐月摘要
        for i, month in enumerate(pending):
            if self._cancelled(task_id):
                self._update(task_id, status="cancelled", current_step="已取消",
                             finished_at=time.time())
                return self.get_progress(task_id)
            self._update(
                task_id,
                current_step=f"月报 {month['month_key']}（{total - len(pending) + i + 1}/{total}）",
                progress_percent=int(5 + 85 * (total - len(pending) + i) / max(total, 1)),
            )
            summary = self._summarize_month(conn, conversation_id, month, redactor)
            conn.execute(
                "INSERT OR REPLACE INTO chapter_month_summaries"
                "(conversation_id, month_key, from_ts, to_ts, me_count, other_count,"
                " summary_json, version, model_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (conversation_id, month["month_key"], month["from_ts"], month["to_ts"],
                 month["me_count"], month["other_count"], json.dumps(summary, ensure_ascii=False),
                 SUMMARY_VERSION, str((self._resolve_model() or {}).get("model_id") or ""),
                 int(time.time())),
            )
            conn.commit()
            self._update(task_id, months_done=total - len(pending) + i + 1)

        # 4. 逐章归并（该章覆盖月份全就绪才归并；指纹命中跳过）
        for ci, chapter in enumerate(chapters):
            if self._cancelled(task_id):
                self._update(task_id, status="cancelled", current_step="已取消",
                             finished_at=time.time())
                return self.get_progress(task_id)
            fingerprint = self._chapter_fingerprint(chapter["from_ts"], chapter["to_ts"])
            if self._chapter_summary_row(conn, conversation_id, fingerprint):
                continue
            month_rows = self._month_rows_for_window(
                conn, conversation_id, chapter["from_ts"], chapter["to_ts"])
            if not month_rows:
                continue  # 章节落在无文本区间（沉默章）：无月报可归并，跳过
            self._update(
                task_id, current_step=f"章节归并 {ci + 1}/{len(chapters)}",
                progress_percent=int(90 + 10 * ci / max(len(chapters), 1)),
            )
            summary = self._summarize_chapter(chapter, month_rows, redactor)
            conn.execute(
                "INSERT OR REPLACE INTO chapter_summaries"
                "(conversation_id, fingerprint, from_ts, to_ts, summary_json,"
                " version, model_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (conversation_id, fingerprint, int(chapter["from_ts"]), int(chapter["to_ts"]),
                 json.dumps(summary, ensure_ascii=False), SUMMARY_VERSION,
                 str((self._resolve_model() or {}).get("model_id") or ""), int(time.time())),
            )
            conn.commit()

        self._update(task_id, status="completed", progress_percent=100,
                     current_step="完成", finished_at=time.time())
        logger.info("[章节摘要] 会话 %s 完成（%d 月 / %d 章）", conversation_id, total, len(chapters))
        return self.get_progress(task_id)

    # ------------------------------------------------------------------
    # 取数
    # ------------------------------------------------------------------

    @staticmethod
    def _list_months(conn, conversation_id: int) -> List[Dict[str, Any]]:
        """有文本消息的月份清单（本地时区 'YYYY-MM'，与情绪分桶同时区口径）。"""
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m', m.timestamp, 'unixepoch', 'localtime') AS mk,
                   MIN(m.timestamp) AS from_ts, MAX(m.timestamp) AS to_ts,
                   SUM(CASE WHEN m.is_sender = 1 THEN 1 ELSE 0 END) AS me_count,
                   COUNT(*) AS total
            FROM messages m
            WHERE m.conversation_id = ?
              AND m.message_type = 1
              AND m.content IS NOT NULL
              AND TRIM(m.content) != ''
            GROUP BY mk
            ORDER BY mk
            """,
            (conversation_id,),
        ).fetchall()
        months = []
        for row in rows:
            total = int(row["total"] or 0)
            me = int(row["me_count"] or 0)
            months.append({
                "month_key": str(row["mk"]),
                "from_ts": int(row["from_ts"] or 0),
                "to_ts": int(row["to_ts"] or 0),
                "me_count": me,
                "other_count": total - me,
            })
        return months

    @staticmethod
    def _ready_month_keys(conn, conversation_id: int) -> set:
        rows = conn.execute(
            "SELECT month_key FROM chapter_month_summaries"
            " WHERE conversation_id = ? AND version = ?",
            (conversation_id, SUMMARY_VERSION),
        ).fetchall()
        return {str(row["month_key"]) for row in rows}

    @staticmethod
    def _month_rows_for_window(
        conn, conversation_id: int, from_ts: int, to_ts: int,
    ) -> List[Dict[str, Any]]:
        """窗口（章节）覆盖的月报行：月 [from_ts,to_ts] 与窗口有交叠即入。

        章边界落在月中时该月进相邻两章——归并 LLM 按月序自权衡。"""
        rows = conn.execute(
            """
            SELECT month_key, from_ts, to_ts, me_count, other_count, summary_json
            FROM chapter_month_summaries
            WHERE conversation_id = ? AND version = ?
              AND from_ts <= ? AND to_ts >= ?
            ORDER BY month_key
            """,
            (conversation_id, SUMMARY_VERSION, int(to_ts), int(from_ts)),
        ).fetchall()
        out = []
        for row in rows:
            try:
                summary = json.loads(row["summary_json"])
            except Exception:
                continue
            out.append({
                "month_key": str(row["month_key"]),
                "me_count": int(row["me_count"] or 0),
                "other_count": int(row["other_count"] or 0),
                "summary": summary if isinstance(summary, dict) else {},
            })
        return out

    @staticmethod
    def _chapter_summary_row(conn, conversation_id: int, fingerprint: str) -> Optional[dict]:
        row = conn.execute(
            "SELECT summary_json FROM chapter_summaries"
            " WHERE conversation_id = ? AND fingerprint = ? AND version = ?",
            (conversation_id, fingerprint, SUMMARY_VERSION),
        ).fetchone()
        if not row:
            return None
        try:
            parsed = json.loads(row["summary_json"])
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _summarize_month(
        self, conn, conversation_id: int, month: Dict[str, Any], redactor: Any,
    ) -> Dict[str, Any]:
        """单月：采样（等距抽稀）→ 逐条脱敏 → LLM 结构化月报。"""
        messages = self._sample_month(conn, conversation_id, month["from_ts"], month["to_ts"])
        lines = []
        dropped = 0
        for is_sender, content in messages:
            if redactor is not None:
                try:
                    content = redactor.redact(
                        content,
                        conversation_id=conversation_id,
                        source_table="chapter_month_summary",
                        source_id=month["month_key"],
                    ).redacted_text
                except Exception:
                    dropped += 1  # 单条脱敏失败丢条（宁可不发），月报继续
                    continue
            if not content:
                dropped += 1
                continue
            lines.append(f"{'我' if is_sender else 'TA'}：{content}")
        sample_text = "\n".join(lines)

        user_prompt = (
            f"【月份】{month['month_key']}\n"
            f"【本月消息】{month['me_count'] + month['other_count']} 条"
            f"（我 {month['me_count']} / TA {month['other_count']}），"
            f"以下为抽样原文{('，脱敏失败已丢弃 ' + str(dropped) + ' 条') if dropped else ''}：\n"
            f"{sample_text}\n\n"
            '请输出 JSON：{"topics": ["本月主要话题，≤5个短语"], '
            '"dynamics": "一句话关系动态（观察措辞）", '
            '"highlights": ["重要事件/约定/情绪节点，≤3条"], '
            '"style": "双方语气/称呼/默契的要点，一句话"}\n'
            "约束：只基于本月内容；总字数 ≤150；空月份字段给空值。"
        )
        content = self._call_llm(_MONTH_SYSTEM_PROMPT, user_prompt)
        return self._parse_summary(content, {"topics": [], "dynamics": "", "highlights": [], "style": ""})

    @staticmethod
    def _sample_month(
        conn, conversation_id: int, from_ts: int, to_ts: int,
    ) -> List[Tuple[int, str]]:
        """月内文本消息，条数与字符双预算等距抽稀（保时间分布）。"""
        rows = conn.execute(
            """
            SELECT m.is_sender, m.content
            FROM messages m
            WHERE m.conversation_id = ?
              AND m.message_type = 1
              AND m.content IS NOT NULL
              AND TRIM(m.content) != ''
              AND m.timestamp >= ? AND m.timestamp <= ?
            ORDER BY m.timestamp ASC, m.id ASC
            """,
            (conversation_id, int(from_ts), int(to_ts)),
        ).fetchall()
        messages: List[Tuple[int, str]] = []
        for row in rows:
            content = row["content"]
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            text = (content or "").strip()
            if text:
                messages.append((1 if row["is_sender"] else 0, text))
        if len(messages) <= MONTH_MAX_MESSAGES:
            picked = messages
        else:  # 等距抽稀：保条数上限内的均匀时间分布
            step = len(messages) / MONTH_MAX_MESSAGES
            picked = [messages[int(i * step)] for i in range(MONTH_MAX_MESSAGES)]
        total_chars = sum(len(t) for _, t in picked)
        if total_chars <= MONTH_CHAR_BUDGET:
            return picked
        keep_ratio = MONTH_CHAR_BUDGET / total_chars
        target_n = max(50, int(len(picked) * keep_ratio))
        step = len(picked) / target_n
        return [picked[int(i * step)] for i in range(target_n)]

    def _summarize_chapter(
        self, chapter: Dict[str, Any], month_rows: List[Dict[str, Any]], redactor: Any,
    ) -> Dict[str, Any]:
        """章节：月报序列 + 章统计 + 前章变化 → 归并叙事。"""
        changes = "、".join(
            f"{c['label']}{'↑' if c['direction'] == 'up' else '↓'}" for c in chapter.get("changes") or []
        ) or "节奏平稳"
        month_lines = []
        for row in month_rows:
            s = row["summary"]
            month_lines.append(
                f"{row['month_key']}（{row['me_count'] + row['other_count']} 条）："
                f"话题 {('、'.join(s.get('topics') or []) or '无')}；"
                f"{s.get('dynamics') or ''}"
                + (f"；{'; '.join(s.get('highlights') or [])}" if s.get("highlights") else "")
            )
        user_prompt = (
            f"【章节】{_fmt_range(chapter['from_ts'], chapter['to_ts'])}"
            f"（{chapter['stats']['weeks']} 周，{chapter['stats']['texts']} 条消息，"
            f"TA 占比 {_pct(chapter['stats'].get('other_share'))}）\n"
            f"【相对前章变化】{changes}\n"
            f"【月报】\n" + "\n".join(month_lines) + "\n\n"
            '请输出 JSON：{"summary": "2~3 句章节叙事：这段关系在做什么、怎么互动、'
            '有什么走向（观察措辞，引用具体话题）", "phase": "阶段一句话'
            '（如：熟络升温期/平稳陪伴期/疏远冷却期，观察措辞）"}\n'
            "约束：只基于月报内容；总字数 ≤160。"
        )
        content = self._call_llm(_CHAPTER_SYSTEM_PROMPT, user_prompt)
        return self._parse_summary(content, {"summary": "", "phase": ""})

    @staticmethod
    def _parse_summary(content: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        candidates = _json_candidates(content)
        for cand in reversed(candidates):
            try:
                parsed = json.loads(cand)
            except Exception:
                continue
            if isinstance(parsed, dict) and parsed:
                cleaned = {}
                for key, default in fallback.items():
                    value = parsed.get(key)
                    if isinstance(default, list):
                        cleaned[key] = [str(v)[:60] for v in value][:5] if isinstance(value, list) else []
                    elif isinstance(default, str):
                        cleaned[key] = str(value or "")[:400]
                return cleaned
        raise ValueError(f"摘要响应无 JSON 对象（len={len(content)}, head={content[:120]!r}）")


def _fmt_range(from_ts: int, to_ts: int) -> str:
    from datetime import datetime

    return (
        f"{datetime.fromtimestamp(int(from_ts)).strftime('%Y-%m-%d')}"
        f" ~ {datetime.fromtimestamp(int(to_ts)).strftime('%Y-%m-%d')}"
    )


def _pct(ratio: Optional[float]) -> str:
    return f"{ratio * 100:.0f}%" if ratio is not None else "—"
