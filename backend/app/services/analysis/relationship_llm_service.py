"""LLM 关系评估维度：窗口采样交互对 → 注入统计概要 → 脱敏 → 大模型关系判断。

作为独立维度参与好感度加权（缺席时权重归一自动剔除）：
- 四窗分层采样（起源 / 高冲突 / 近期 / 破冰，替换旧极性九桶），
  渲染为带月份/时差的双方对话样本；
- EngagementMetrics 统计概要注入提示词，约束推导纪律（子分与统计一致、
  证据必须引用原文、risk_evidence 找不到证据必须 found=false）；
- RelationshipContext（关系类型/时长/沟通风格）注入提示词；
- 远程模型必经 PrivacyRedactor（脱敏器不可用=整维缺席，绝不发原文，
  对齐 rag/fact_llm 的红线模式）；本地 loopback 模型免脱敏；
- 每次分析恰好一次 HTTP 调用（max_retries=1），超时/解析失败=缺席。

跨域依赖全部构造器注入/函数内延迟导入，便于测试与避免循环。
"""

from __future__ import annotations

import logging
import math
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...db.connection import get_db
from ..realtime.llm_http import apply_deep_call_effort
from .engagement_metrics import EngagementMetrics

logger = logging.getLogger(__name__)

# 预算与采样常量
MAX_PAIRS = 40
MIN_PAIRS = 10
MAX_TOTAL_INPUT_CHARS = 8000
PER_UNIT_CHAR_LIMIT = 120
TIMEOUT_SECONDS = 90
# 思考模型（实测 Qwen3.5-9B）把推理写进 content：1024 会被 think 段
# 耗尽导致 JSON 未闭合即截断（finish_reason=length）——真答案在最后
MAX_TOKENS = 3072

# 四窗采样配额（批 3：极性九桶退役——中性对占绝对多数，九桶配额大多
# 浪费；窗口覆盖关系演变/冲突段/恢复段，信息密度更高）
WINDOW_ORIGIN_QUOTA = 12        # 起源窗：最早对话
WINDOW_CONFLICT_QUOTA = 12      # 高冲突窗：负向密度最高的 7 天桶
WINDOW_RECENT_QUOTA = 12        # 近期窗：最近 30 天
WINDOW_ICEBREAK_QUOTA = 6       # 破冰窗：>24h 沉默后恢复的首轮交流
WINDOW_RECENT_DAYS = 30
CONFLICT_BUCKET_SECONDS = 7 * 86400
ICEBREAK_SESSION_GAP_SECONDS = 24 * 3600
MIN_PER_WINDOW = 2              # 预算裁剪时每窗保底

# 风险对话证据键（与风险预警模块的信号 key 一一对应）
RISK_EVIDENCE_KEYS = ("hot_cold", "one_sided", "reality_denial", "warm_then_cold")

SYSTEM_PROMPT = """你是一位关系分析专家。基于给出的【统计概要】与两人聊天交互对样本（[对方] 与 [我]），
评估这两人的关系质量。注意：衡量的不是单方情绪，而是双方关系的亲密与
健康程度。

严格按以下 JSON 输出，不要输出任何其他文字：
{"score": 0-100 的整数（关系质量总分，50 为中性）,
 "sub_scores": {"communication_quality": 0-100（沟通质量：互相理解与回应质量）,
                "relationship_warmth": 0-100（关系温度：亲近与信任程度）},
 "risk_evidence": {"hot_cold": {"found": true/false, "quotes": ["原文短句（≤30字）"]},
                   "one_sided": {"found": true/false, "quotes": [...]},
                   "reality_denial": {"found": true/false, "quotes": [...]},
                   "warm_then_cold": {"found": true/false, "quotes": [...]}},
 "evidence": [{"quote": "支撑判断的原文短句（≤30字）", "month": "出现月份"}]（最多5条）,
 "insight": "一段不超过120字的关系洞察，指出最关键的关系特征"}

risk_evidence 四类的含义：hot_cold=忽冷忽热（时而热情时而冷淡）；
one_sided=单向投入（一方持续付出另一方敷衍）；reality_denial=现实否认
（否定对方感受或记忆，如"你记错了""你太敏感"）；warm_then_cold=先热后冷
（早期热情、近期明显降温）。

推导纪律：
1. sub_scores 必须与【统计概要】一致——概要中敷衍回复率、长时未回应、
   连发未回等反向指标明显偏高时，communication_quality 不应给高分；
2. evidence 与 risk_evidence.quotes 只能引用样本原文，禁止编造；
3. risk_evidence 每类找不到对应对话证据时必须 found=false，禁止臆测。"""


class RelationshipLLMAbsent(RuntimeError):
    """LLM 关系评估缺席（未配置/样本不足/脱敏不可用/调用失败/解析失败）。"""


class RelationshipLLMService:
    """LLM 关系评估（构造器注入依赖，便于测试）。"""

    def __init__(
        self,
        model_config: dict,
        http: Optional[Callable[..., dict]] = None,
        is_remote: Optional[Callable[[dict], bool]] = None,
        redactor_factory: Optional[Callable[[], Any]] = None,
    ):
        self.model_config = model_config
        if http is None:
            from ..realtime.llm_http import post_json_with_retries

            self._http = post_json_with_retries
        else:
            self._http = http
        if is_remote is None:
            from ..realtime.rag.config import is_remote_llm_model

            self._is_remote = is_remote_llm_model
        else:
            self._is_remote = is_remote
        self._redactor_factory = redactor_factory

    # ---------- 对外 ----------

    def evaluate(
        self,
        conversation_id: int,
        account_wxid: str = "",
        context: Optional[Dict[str, str]] = None,
        metrics: Optional[EngagementMetrics] = None,
    ) -> Dict[str, Any]:
        """评估并返回 {score, sub_scores, risk_evidence, evidence, insight, meta}。

        metrics 为编排器单次计算的会话投入特征，注入提示词约束推导纪律。
        任何失败抛 RelationshipLLMAbsent（调用方置缺席，不阻断其余维度）。
        """
        started = time.monotonic()
        pairs = self._sample_interaction_pairs(conversation_id)
        if len(pairs) < MIN_PAIRS:
            raise RelationshipLLMAbsent(
                f"交互对样本不足（{len(pairs)} < {MIN_PAIRS}），无法可靠评估"
            )

        remote = bool(self._is_remote(self.model_config))
        pair_texts = self._render_pair_texts(pairs)
        if remote:
            pair_texts = self._redact_pair_texts(
                pair_texts, account_wxid=account_wxid, conversation_id=conversation_id
            )

        messages = self._render_prompt(pair_texts, context or {}, metrics)
        # 解析失败自动重试一次：本地模型面对复杂 schema 偶发不吐 JSON
        # ——同输入重跑即恢复（实测 conv 重放一次即成功），网络层失败
        # 已由 llm_http 自行重试，这里只兜解析形态
        result: Optional[Dict[str, Any]] = None
        content = ""
        finish_reason = ""
        last_absent_reason = ""
        for attempt in (1, 2):
            body = self._call_chat(messages)
            content = self._extract_content(body)
            finish_reason = ""
            try:
                finish_reason = str(body["choices"][0].get("finish_reason") or "")
            except (KeyError, IndexError, TypeError):
                pass
            if finish_reason == "length":
                raise RelationshipLLMAbsent(
                    f"LLM 输出被 max_tokens={MAX_TOKENS} 截断（思考模型推理段过长）"
                )
            try:
                result = self._parse_response(content)
                break
            except RelationshipLLMAbsent as absent_exc:
                # 保留具体原因（如「无效分值」）供最终报错——统一替换成
                # 「未包含可解析的 JSON」会把真实病因误报成解析失败
                last_absent_reason = str(absent_exc)
                # WARNING 级留现场：打包版文件日志为 INFO，DEBUG 不落盘，
                # 偶发失败曾无从诊断（content/reasoning 长度可判 think 分离形态）
                reasoning_len = 0
                try:
                    reasoning_len = len(body["choices"][0]["message"].get("reasoning_content") or "")
                except (KeyError, IndexError, TypeError):
                    pass
                logger.warning(
                    "[关系评估] 解析失败(第%d次) content(len=%d, reasoning=%d, finish=%s) 前200字: %s",
                    attempt, len(content), reasoning_len, finish_reason or "unknown", content[:200],
                )
        if result is None:
            raise RelationshipLLMAbsent(
                f"{last_absent_reason or 'LLM 输出未包含可解析的 JSON 评估'}"
                f"（已重试，finish={finish_reason or 'unknown'}, len={len(content)}）"
            ) from None

        # 推导纪律的事后校验：引文必须真的出现在采样原文里
        result["risk_evidence"] = self._verify_risk_evidence(
            result["risk_evidence"], pair_texts
        )

        result["meta"] = {
            "model_name": str(self.model_config.get("name") or self.model_config.get("model_id") or ""),
            "model_id": str(self.model_config.get("model_id") or ""),
            "remote": remote,
            "sampled_pairs": len(pair_texts),
            "input_chars": sum(len(t["from_text"]) + len(t["to_text"]) for t in pair_texts),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
        return result

    # ---------- 采样（四窗分层） ----------

    # 交互对行模板（from 侧附带单元 id 作去重键）
    _PAIR_SELECT = """
        SELECT ip.from_polarity, ip.to_polarity, ip.time_gap,
               fs.message_ids AS from_ids, fs.sender AS from_sender,
               fs.first_message_timestamp AS from_ts, fs.id AS from_unit_id,
               ts.message_ids AS to_ids, ts.sender AS to_sender
        FROM interaction_pairs ip
        JOIN speech_units fs ON fs.id = ip.from_speech_unit_id
        JOIN speech_units ts ON ts.id = ip.to_speech_unit_id
        WHERE ip.conversation_id = ?
    """

    def _sample_interaction_pairs(self, conversation_id: int) -> List[Dict[str, Any]]:
        """四窗分层采样：起源 / 高冲突 / 近期 / 破冰。

        speech_units 不存内容（只有 message_ids/sender/时间戳），单元
        文本经 message_ids 回查 messages 拼接。窗内极性均衡（轮转取数），
        窗口间共享 8000 字符预算（超出从最大窗裁边，端点方向按窗语义：
        起源窗保最老端、其余窗保最新端；每窗保底 2 对）。
        """
        origin_rows = self._balance_polarity(
            self._fetch_pairs(conversation_id, " ORDER BY from_ts ASC LIMIT ?",
                              (WINDOW_ORIGIN_QUOTA * 2,)),
            WINDOW_ORIGIN_QUOTA,
        )
        conflict_rows = self._fetch_conflict_window(conversation_id)
        recent_rows = self._fetch_recent_window(conversation_id)
        icebreak_rows = self._fetch_icebreak_window(conversation_id)

        # 跨窗去重（同一 from 单元只出现在一个窗）
        seen: set = set()
        windows: List[Tuple[str, List[Any]]] = []
        for name, rows in (
            ("origin", origin_rows),
            ("conflict", conflict_rows),
            ("recent", recent_rows),
            ("icebreak", icebreak_rows),
        ):
            unique = []
            for row in rows:
                key = int(row["from_unit_id"] or 0)
                if key and key in seen:
                    continue
                seen.add(key)
                unique.append(row)
            if unique:
                # 各窗取数方向不一（origin/conflict 升序、recent/icebreak 降序），
                # 统一升序后裁剪端点才有确定语义
                unique.sort(key=lambda r: int(r["from_ts"] or 0))
                windows.append((name, unique))

        # 裁剪选窗：占用最大者优先，平局时起源窗最后动（关系起点基线最稀缺）
        def _biggest(
            cands: List[Tuple[str, List[Any]]], metric: Callable[[List[Any]], int]
        ) -> Tuple[str, List[Any]]:
            return max(cands, key=lambda w: (metric(w[1]), w[0] != "origin"))

        # 总量上限 40
        while sum(len(rows) for _, rows in windows) > MAX_PAIRS:
            biggest = _biggest(windows, len)
            if len(biggest[1]) <= MIN_PER_WINDOW:
                break
            self._drop_window_edge(biggest)

        pairs_by_window = [(name, self._rows_to_pairs(rows)) for name, rows in windows]

        # 字符预算（每窗保底）
        def _chars(pair: Dict[str, Any]) -> int:
            return len(pair["from_text"]) + len(pair["to_text"])

        total = sum(_chars(p) for _, w in pairs_by_window for p in w)
        while total > MAX_TOTAL_INPUT_CHARS:
            trimmable = [w for w in pairs_by_window if len(w[1]) > MIN_PER_WINDOW]
            if not trimmable:
                break
            biggest = _biggest(
                trimmable, lambda rows: sum(_chars(p) for p in rows)
            )
            total -= _chars(self._drop_window_edge(biggest))

        pairs = [p for _, w in pairs_by_window for p in w]
        # 时间正序渲染（旧→新，便于读演变）
        pairs.sort(key=lambda p: p["_ts"])
        for p in pairs:
            del p["_ts"]
        return pairs

    @staticmethod
    def _drop_window_edge(window: Tuple[str, List[Any]]) -> Any:
        """按窗语义裁掉一端并返回被裁样本：起源窗保最老端（关系起点
        基线）裁新端，其余窗保最新端裁最旧。"""
        name, items = window
        if name == "origin":
            return items.pop()
        return items.pop(0)

    def _fetch_pairs(
        self, conversation_id: int, tail: str, params: tuple
    ) -> List[Any]:
        """按模板取交互对行；表缺失等异常按空窗降级。"""
        try:
            return get_db().execute(
                self._PAIR_SELECT + tail,
                (conversation_id, *params),
            ).fetchall()
        except Exception as exc:
            logger.debug("[关系评估] 窗口取数跳过: %s", exc)
            return []

    def _fetch_recent_window(self, conversation_id: int) -> List[Any]:
        """近期窗：最近 30 天；窗口内无样本时回退最新一批（保持近期语义）。"""
        threshold = int(time.time()) - WINDOW_RECENT_DAYS * 86400
        rows = [
            r for r in self._fetch_pairs(
                conversation_id,
                " AND from_ts >= ? ORDER BY from_ts DESC LIMIT ?",
                (threshold, WINDOW_RECENT_QUOTA * 2),
            )
        ]
        if not rows:
            rows = self._fetch_pairs(
                conversation_id,
                " ORDER BY from_ts DESC LIMIT ?",
                (WINDOW_RECENT_QUOTA * 2,),
            )
        return self._balance_polarity(rows, WINDOW_RECENT_QUOTA)

    def _fetch_conflict_window(self, conversation_id: int) -> List[Any]:
        """高冲突窗：负向（from_polarity=-1）密度最高的 7 天桶内的对。"""
        try:
            bucket = get_db().execute(
                """
                SELECT from_ts / ? AS wk, COUNT(*) AS c
                FROM (
                    SELECT fs.first_message_timestamp AS from_ts
                    FROM interaction_pairs ip
                    JOIN speech_units fs ON fs.id = ip.from_speech_unit_id
                    WHERE ip.conversation_id = ? AND ip.from_polarity = -1
                )
                GROUP BY wk ORDER BY c DESC, wk DESC LIMIT 1
                """,
                (CONFLICT_BUCKET_SECONDS, conversation_id),
            ).fetchone()
        except Exception as exc:
            logger.debug("[关系评估] 冲突窗定位跳过: %s", exc)
            return []
        if not bucket:
            return []
        start = int(bucket["wk"]) * CONFLICT_BUCKET_SECONDS
        return self._fetch_pairs(
            conversation_id,
            " AND from_ts >= ? AND from_ts < ? ORDER BY from_ts ASC LIMIT ?",
            (start, start + CONFLICT_BUCKET_SECONDS, WINDOW_CONFLICT_QUOTA),
        )

    def _fetch_icebreak_window(self, conversation_id: int) -> List[Any]:
        """破冰窗：与上一会话间隔 >24h 的会话的首个交互对（恢复轮）。"""
        try:
            sessions = get_db().execute(
                """
                SELECT s.start_time AS start_time,
                       (SELECT MAX(s2.end_time) FROM sessions s2
                        WHERE s2.conversation_id = s.conversation_id
                          AND s2.end_time < s.start_time) AS prev_end
                FROM sessions s
                WHERE s.conversation_id = ?
                ORDER BY s.start_time DESC
                """,
                (conversation_id,),
            ).fetchall()
        except Exception as exc:
            logger.debug("[关系评估] 破冰窗取会话跳过: %s", exc)
            return []

        gaps = [
            int(r["start_time"]) for r in sessions
            if r["prev_end"] is not None
            and int(r["start_time"]) - int(r["prev_end"]) > ICEBREAK_SESSION_GAP_SECONDS
        ][:WINDOW_ICEBREAK_QUOTA]

        rows = []
        for start_time in gaps:
            first = self._fetch_pairs(
                conversation_id,
                " AND from_ts >= ? ORDER BY from_ts ASC LIMIT 1",
                (start_time,),
            )
            if first:
                rows.append(first[0])
        return rows

    @staticmethod
    def _balance_polarity(rows: List[Any], quota: int) -> List[Any]:
        """窗内极性均衡：按 from_polarity 分组轮转取数（保持各组内次序）。"""
        groups: Dict[int, List[Any]] = {}
        for row in rows:
            groups.setdefault(int(row["from_polarity"] or 0), []).append(row)
        order = sorted(groups, key=lambda k: -len(groups[k]))
        picked: List[Any] = []
        index = {k: 0 for k in groups}
        while len(picked) < quota:
            advanced = False
            for k in order:
                if index[k] < len(groups[k]):
                    picked.append(groups[k][index[k]])
                    index[k] += 1
                    advanced = True
                    if len(picked) >= quota:
                        break
            if not advanced:
                break
        return picked

    def _rows_to_pairs(self, rows: List[Any]) -> List[Dict[str, Any]]:
        """交互对行 → 渲染对（文本经 message_ids 回查，详见 _sample 注释）。"""
        # message_ids 实际存在两种形态：纯逗号分隔（schema 注释口径）与
        # Python list 的 repr（'[123, 124]'，部分写入路径产出）——统一剥
        # 方括号解析（此前取数循环漏剥，全库 list-repr 形态下采样恒为空）
        def _parse_message_ids(ids_raw: Any) -> List[int]:
            ids: List[int] = []
            for part in str(ids_raw or "").split(","):
                part = part.strip().strip("[]").strip()
                if part.isdigit():
                    ids.append(int(part))
            return ids

        all_ids: List[int] = []
        for row in rows:
            for field in ("from_ids", "to_ids"):
                all_ids.extend(_parse_message_ids(row[field]))
        content_by_id: Dict[int, str] = {}
        if all_ids:
            placeholders = ",".join("?" * len(all_ids))
            msg_rows = get_db().execute(
                f"""
                SELECT m.id, COALESCE(NULLIF(TRIM(mp.cleaned_content), ''), m.content) AS text
                FROM messages m
                LEFT JOIN message_preprocessed mp ON mp.message_id = m.id
                WHERE m.id IN ({placeholders})
                """,
                tuple(all_ids),
            ).fetchall()
            content_by_id = {int(r["id"]): str(r["text"] or "") for r in msg_rows}

        def _unit_text(ids_raw: Any) -> str:
            parts = []
            for mid in _parse_message_ids(ids_raw):
                if mid in content_by_id:
                    text = content_by_id[mid].strip()
                    if text:
                        parts.append(text)
            return " ".join(parts)[:PER_UNIT_CHAR_LIMIT]

        pairs: List[Dict[str, Any]] = []
        for row in rows:
            from_text = _unit_text(row["from_ids"])
            to_text = _unit_text(row["to_ids"])
            if not from_text and not to_text:
                continue
            pairs.append({
                "_ts": int(row["from_ts"] or 0),
                "month": datetime.fromtimestamp(
                    int(row["from_ts"] or 0)
                ).strftime("%Y-%m"),
                "time_gap": int(row["time_gap"] or 0),
                "from_is_sender": str(row["from_sender"] or "") == "user",
                "from_text": from_text,
                "to_text": to_text,
            })
        return pairs

    # ---------- 渲染 ----------

    def _render_pair_texts(self, pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [dict(p) for p in pairs]

    def _redact_pair_texts(
        self,
        pairs: List[Dict[str, Any]],
        *,
        account_wxid: str,
        conversation_id: int,
    ) -> List[Dict[str, Any]]:
        """远程模型逐条脱敏（红线：脱敏器不可用=整维缺席）。"""
        if self._redactor_factory is None:
            raise RelationshipLLMAbsent("远程模型缺少脱敏器，按红线缺席")
        try:
            redactor = self._redactor_factory()
        except Exception as exc:
            raise RelationshipLLMAbsent(f"脱敏器构造失败: {exc}") from exc

        redacted: List[Dict[str, Any]] = []
        for pair in pairs:
            cleaned = dict(pair)
            ok = True
            for field in ("from_text", "to_text"):
                try:
                    result = redactor.redact(
                        str(pair[field]),
                        account_wxid=account_wxid,
                        conversation_id=conversation_id,
                        source_table="affinity_relationship_llm",
                        source_id=str(pair.get("month") or ""),
                    )
                    cleaned[field] = result.redacted_text
                except Exception as exc:
                    # 单条失败丢弃该条（对齐 fact_llm 口径），不阻断整维
                    logger.debug("[关系评估] 单条脱敏失败丢弃: %s", exc)
                    ok = False
                    break
            if ok:
                redacted.append(cleaned)
        if len(redacted) < MIN_PAIRS:
            raise RelationshipLLMAbsent(
                f"脱敏后可用样本不足（{len(redacted)} < {MIN_PAIRS}）"
            )
        return redacted

    def _render_prompt(
        self,
        pairs: List[Dict[str, Any]],
        context: Dict[str, str],
        metrics: Optional[EngagementMetrics] = None,
    ) -> List[dict]:
        lines: List[str] = []
        if context:
            ctx_parts = []
            if context.get("relationship_type"):
                ctx_parts.append(f"关系类型：{context['relationship_type']}")
            if context.get("interaction_duration"):
                ctx_parts.append(f"认识时长：{context['interaction_duration']}")
            if context.get("communication_style"):
                ctx_parts.append(f"沟通风格：{context['communication_style']}")
            if ctx_parts:
                lines.append("【关系背景】" + "；".join(ctx_parts))
        if metrics is not None:
            summary = self._render_metrics_summary(metrics)
            if summary:
                lines.append("【统计概要】" + summary)
        lines.append("【交互对样本】（时间从早到晚；格式：月份 | 回应间隔秒 | 发言）")
        for p in pairs:
            from_label = "我" if p["from_is_sender"] else "对方"
            to_label = "对方" if p["from_is_sender"] else "我"
            lines.append(
                f"{p['month']} | {p['time_gap']}s | [{from_label}] {p['from_text']}"
            )
            lines.append(f"{' ' * len(p['month'])} | → [{to_label}] {p['to_text']}")
        user_content = "\n".join(lines)
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content[:MAX_TOTAL_INPUT_CHARS + 2000]},
        ]

    @staticmethod
    def _render_metrics_summary(metrics: EngagementMetrics) -> str:
        """统计概要单行化（跳过空值字段；用于约束 LLM 推导纪律）。"""
        parts = [f"文本消息 {metrics.text_message_count} 条（我 {metrics.self_text_count} / 对方 {metrics.other_text_count}）"]
        if metrics.long_unanswered_other or metrics.long_unanswered_self:
            parts.append(
                f"长时未回应：对方 {metrics.long_unanswered_other} 次、我方 {metrics.long_unanswered_self} 次"
            )
        if metrics.burst_unanswered_other or metrics.burst_unanswered_self:
            parts.append(
                f"连发未回：对方 {metrics.burst_unanswered_other} 次、我方 {metrics.burst_unanswered_self} 次"
            )
        if metrics.perfunctory_rate_other or metrics.perfunctory_rate_self:
            parts.append(
                f"敷衍回复率：对方 {metrics.perfunctory_rate_other:.0%}、我方 {metrics.perfunctory_rate_self:.0%}"
            )
        if metrics.icebreak_total:
            parts.append(
                f"主动破冰：对方 {metrics.icebreak_other} / 我方 {metrics.icebreak_self}（共 {metrics.icebreak_total} 次）"
            )
        greeting_total = (
            metrics.morning_greeting_self + metrics.morning_greeting_other
            + metrics.night_greeting_self + metrics.night_greeting_other
        )
        if greeting_total:
            other_greetings = metrics.morning_greeting_other + metrics.night_greeting_other
            parts.append(f"早晚安发起：对方 {other_greetings} / 我方 {greeting_total - other_greetings}")
        if metrics.community_ratio_other is not None:
            parts.append(f"共同体表达（对方「我们」类占比）：{metrics.community_ratio_other:.0%}")
        if metrics.revoke_other or metrics.revoke_self:
            parts.append(f"撤回消息：对方 {metrics.revoke_other} 条、我方 {metrics.revoke_self} 条")
        if metrics.daily_cv_active is not None:
            parts.append(f"日消息量波动系数：{metrics.daily_cv_active}")
        if metrics.positive_other or metrics.negative_other:
            parts.append(
                f"带极性消息（对方）：正 {metrics.positive_other} / 负 {metrics.negative_other}"
            )
        return "；".join(parts)

    # ---------- 调用与解析 ----------

    def _call_chat(self, messages: List[dict]) -> dict:
        model = self.model_config
        base_url = str(model.get("api_base_url") or "").rstrip("/")
        if not base_url:
            raise RelationshipLLMAbsent("模型配置缺少 api_base_url")
        headers = {}
        api_key = str(model.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model.get("model_id"),
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": MAX_TOKENS,
            "stream": False,
        }
        # 深度调用思考量定档：思考模型附 reasoning_effort:"medium"，
        # 模型级 extra_body 显式配置优先（详见 llm_http）
        apply_deep_call_effort(payload, model)
        try:
            return self._http(
                url=f"{base_url}/chat/completions",
                payload=payload,
                headers=headers,
                timeout=TIMEOUT_SECONDS,
                max_retries=1,
                log=logger.debug,
                log_prefix="[关系评估]",
            )
        except RelationshipLLMAbsent:
            raise
        except Exception as exc:
            raise RelationshipLLMAbsent(f"LLM 调用失败: {exc}") from exc

    @staticmethod
    def _extract_content(body: dict) -> str:
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RelationshipLLMAbsent("LLM 响应缺少 choices") from exc
        content = message.get("content")
        if not content and message.get("reasoning_content"):
            content = message["reasoning_content"]
        return str(content or "")

    def _parse_response(self, content: str) -> Dict[str, Any]:
        from ..realtime.rag.fact_llm import LLMFactExtractorAdapter

        parsed: Optional[dict] = None
        for candidate in LLMFactExtractorAdapter._json_candidates(content):
            try:
                import json as _json

                obj = _json.loads(candidate)
            except Exception:
                continue
            if isinstance(obj, dict) and "score" in obj:
                parsed = obj
                break
        if parsed is None:
            raise RelationshipLLMAbsent("LLM 输出未包含可解析的 JSON 评估")

        def _parse_score(value) -> Optional[float]:
            """LLM 分值解析：缺失/NaN/Inf/非数值 → None。

            此前 _clamp 对无效值静默落默认（null→50；NaN 经 min/max 比较
            短路得 100）——坏输出被包装成看似正常的分数写进缓存与总分。
            无效即缺席：Absent 语义下本维不参与归一、可经补评通道重试。
            """
            try:
                num = float(value)
            except (TypeError, ValueError):
                return None
            return num if math.isfinite(num) else None

        score = _parse_score(parsed.get("score"))
        sub_raw = parsed.get("sub_scores") or {}
        sub_scores = {
            "communication_quality": _parse_score(sub_raw.get("communication_quality")),
            "relationship_warmth": _parse_score(sub_raw.get("relationship_warmth")),
        }
        if score is None or any(v is None for v in sub_scores.values()):
            raise RelationshipLLMAbsent(
                "LLM 评估输出含无效分值（缺失/NaN/非数值），按缺席处理"
            )

        def _clamp(value: float) -> float:
            return max(0.0, min(100.0, value))

        evidence = []
        for item in (parsed.get("evidence") or [])[:5]:
            if isinstance(item, dict) and item.get("quote"):
                evidence.append({
                    "quote": str(item["quote"])[:60],
                    "month": str(item.get("month") or ""),
                })
        return {
            "score": _clamp(score),
            "sub_scores": {key: _clamp(val) for key, val in sub_scores.items()},
            "risk_evidence": self._normalize_risk_evidence(parsed.get("risk_evidence")),
            "evidence": evidence,
            "insight": str(parsed.get("insight") or "")[:300],
        }

    @staticmethod
    def _normalize_risk_evidence(raw: Any) -> Dict[str, Dict[str, Any]]:
        """风险对话证据归一：{key: {found, quotes[]}}，四键齐全。"""
        normalized: Dict[str, Dict[str, Any]] = {}
        source = raw if isinstance(raw, dict) else {}
        for key in RISK_EVIDENCE_KEYS:
            item = source.get(key)
            found = False
            quotes: List[str] = []
            if isinstance(item, dict):
                found = bool(item.get("found"))
                for quote in (item.get("quotes") or [])[:3]:
                    if quote:
                        quotes.append(str(quote)[:60])
            elif isinstance(item, list):
                # 宽容形态：直接给引文列表（视为 found 且带证据）
                for quote in item[:3]:
                    if quote:
                        quotes.append(str(quote)[:60])
                found = bool(quotes)
            normalized[key] = {"found": found, "quotes": quotes}
        return normalized

    @staticmethod
    def _verify_risk_evidence(
        risk_evidence: Dict[str, Dict[str, Any]],
        pair_texts: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """引文与采样原文比对（模型实际看到的文本）：对不上即丢弃，全部
        失效则降为 found=False——编造引文不得进风险信号卡与体检报告。"""

        def _squash(text: Any) -> str:
            return re.sub(r"\s+", "", str(text or ""))

        corpus = _squash(
            "".join(
                f"{t.get('from_text', '')}{t.get('to_text', '')}" for t in pair_texts
            )
        )
        dropped = 0
        for item in risk_evidence.values():
            kept = []
            for quote in (item.get("quotes") or []):
                squashed = _squash(quote)
                if squashed and squashed in corpus:
                    kept.append(quote)
                else:
                    dropped += 1
            item["quotes"] = kept
            if not kept:
                item["found"] = False
        if dropped:
            logger.info(
                "[关系评估] 风险引文校验丢弃 %d 条与采样原文不符的引文", dropped
            )
        return risk_evidence


def build_relationship_llm_service() -> Optional[RelationshipLLMService]:
    """从激活模型构造服务；未配置返回 None（延迟导入避免循环）。"""
    from ..realtime.rag.fact_llm import get_active_model_config

    model_config = get_active_model_config()
    if not model_config:
        return None

    def _redactor_factory():
        from ..realtime.privacy_redactor import PrivacyRedactor

        return PrivacyRedactor(get_db())

    return RelationshipLLMService(
        model_config, redactor_factory=_redactor_factory
    )
