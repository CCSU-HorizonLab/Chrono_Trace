"""大五人格印象服务——双层架构（本地统计基础层 + LLM 增强层）。

基础层（永远可用，无模型依赖）：big5_proxies 纯统计代理 × 双方独立计算。
增强层（可选）：LLM 读基础五维 + 子指标概要 + 采样对话，输出逐维
{adjustment, reason, evidence_quote}，**双重钳制**
final = clamp(clamp(base + adjustment, base ± BIG5_LLM_ADJUST_LIMIT), 0, 100)，
evidence 必须是（脱敏后）采样语料的子串否则丢弃该证据（分数保留）。

红线（对齐 relationship_llm_service）：
- 远程模型必经 PrivacyRedactor；脱敏器构造失败 = 整次增强阻断，
  绝不发原文，且不落任何 llm_enhanced 行；
- 本地 loopback 模型免脱敏（不构造脱敏器）；
- 无激活模型 = 基础层照常返回，enhance 返回 reason=no_model。

缓存：big5_impressions 表（_ensure_table 轻迁移，不动 schema.sql，
沿 contact_profiles 先例）。UNIQUE(conversation_id, account_wxid, subject,
prompt_version, source)；BIG5_PROMPT_VERSION 变更即旧行失效重算。
"""

import json
import logging
import math
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...db.connection import get_db
from .big5_proxies import DIMENSIONS, compute_big5_base
from .engagement_metrics import EngagementMetricsService

logger = logging.getLogger(__name__)

BIG5_PROMPT_VERSION = 1          # prompt/指标权重结构性变化 +1，旧行自动失效
BIG5_LLM_ADJUST_LIMIT = 15       # LLM 校正上界（绝对分）
BIG5_TTL_SECONDS = 30 * 86400    # 缓存 30 天
BIG5_SAMPLE_TARGET_CHARS = 12000  # 增强层采样语料目标字符数
BIG5_SAMPLE_TURN_LIMIT = 400     # 采样消息条数上限
BIG5_TOKENIZE_LIMIT = 5000       # TTR/熵计算的抽样上限（分词代价约束）
BIG5_MIN_MESSAGES = 30           # 低于该条数不出画像（样本过薄）
BIG5_RESPONSE_MAX_TOKENS = 2048
BIG5_TIMEOUT_SECONDS = 90

SUBJECTS = ("me", "other")

# 表情/感叹/叠词密度（外向性代理）：微信原生表情占位、常见 emoji 段、感叹号、中文叠词
_EMOJI_EXCLAIM_PATTERN = re.compile(
    r"\[[一-龥]{1,4}\]"       # [微笑] [捂脸] 等微信表情
    r"|[\U0001F300-\U0001FAFF]"       # emoji 常用段
    r"|[☀-➿]"               # 杂项符号（☀✨❤ 等）
    r"|!|！"                          # 感叹号
    r"|([一-龥])\1{1,}"       # 中文叠词（哈哈、呜呜）
)

SYSTEM_PROMPT = """你是一位语言行为分析专家。下面给你一段双方微信聊天记录样本，以及从完整
聊天统计中计算出的「大五人格印象」基础分数（0-100 连续值，纯行为统计）。
你的任务是在基础分数上做**有界校正**：结合对话中可观察的语言风格证据，
对每个维度给出 -15 到 +15 的调整量。

纪律要求：
1. 调整量必须保守：统计基础已经吸收了大部分信号，只在对话中有明确证据时才调整；
2. evidence_quote 必须逐字摘抄样本中的原文（不超过 40 字），找不到就不给证据（空字符串），
   绝不允许编造或改写；
3. 这是「语言风格印象」，不是心理测评，reason 措辞避免诊断性断言；
4. 严格按以下 JSON 输出，不要输出任何其他文字：
{"extraversion": {"adjustment": -15~15, "reason": "一句话", "evidence_quote": ""},
 "conscientiousness": {...}, "neuroticism": {...}, "agreeableness": {...}, "openness": {...}}"""


class PersonalityImpressionService:
    """大五双层画像：指标采集 → 基础层合成 →（可选）LLM 有界增强 → 表缓存。"""

    def __init__(
        self,
        http: Optional[Callable[..., dict]] = None,
        is_remote: Optional[Callable[[dict], bool]] = None,
        redactor_factory: Optional[Callable[[], Any]] = None,
        model_config_provider: Optional[Callable[[], Optional[dict]]] = None,
    ):
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
        if model_config_provider is None:
            from ..realtime.rag.fact_llm import get_active_model_config

            self._model_config_provider = get_active_model_config
        else:
            self._model_config_provider = model_config_provider

    # ------------------------------------------------------------------
    # 对外：读取（带缓存）与增强
    # ------------------------------------------------------------------

    def get_impressions(
        self, conversation_id: int, account_wxid: str = "", force_refresh: bool = False
    ) -> Dict[str, Any]:
        """双方大五印象。优先返回未过期的 llm_enhanced，其次 local；都缺则现算 local。"""
        now = int(time.time())
        result: Dict[str, Any] = {}
        metrics = None  # 会话投入特征只算一遍，双侧共用
        for subject in SUBJECTS:
            row = self._load_cached(conversation_id, account_wxid, subject, now)
            if row and not force_refresh:
                result[subject] = row
                continue
            if metrics is None:
                metrics = EngagementMetricsService().compute(conversation_id)
            computed = self._compute_local(conversation_id, subject, metrics)
            if computed is None:
                result[subject] = None
                continue
            self._save_cache(conversation_id, account_wxid, subject, computed, "local", None)
            result[subject] = computed

        return {
            "ok": True,
            "prompt_version": BIG5_PROMPT_VERSION,
            "source": "llm_enhanced" if any(
                item and item.get("source") == "llm_enhanced" for item in result.values()
            ) else "local",
            "subjects": result,
            "disclaimer": "语言风格印象，非心理测评；大五为连续维度（0-100），不构成人格结论",
        }

    def enhance(
        self, conversation_id: int, account_wxid: str = ""
    ) -> Dict[str, Any]:
        """LLM 增强层：双方基础分 + 采样对话 → 有界校正 → 落 llm_enhanced 行。"""
        model_config = self._model_config_provider()
        if not model_config:
            return {"ok": False, "reason": "no_model", "message": "未配置 LLM 模型，基础层仍然可用"}

        # 基础层必须先在（现算不缓存本地行也无妨——get_impressions 已落 local）
        base_payload = self.get_impressions(conversation_id, account_wxid)
        subjects = base_payload.get("subjects") or {}
        if not any(subjects.get(s) for s in SUBJECTS):
            return {"ok": False, "reason": "insufficient_data", "message": "会话消息过少，无法生成画像"}

        sample = self._sample_conversation(conversation_id)
        if not sample:
            return {"ok": False, "reason": "insufficient_data", "message": "无可用文本样本"}

        remote = bool(self._is_remote(model_config))
        redactor = None
        if remote:
            if self._redactor_factory is None:
                return {"ok": False, "reason": "redactor_unavailable",
                        "message": "远程模型缺少脱敏器，按红线阻断本次增强"}
            try:
                redactor = self._redactor_factory()
            except Exception as exc:
                logger.error("[大五增强] 脱敏器构造失败，阻断: %s", exc)
                return {"ok": False, "reason": "redactor_unavailable",
                        "message": "脱敏器不可用，按红线阻断本次增强"}

        # 脱敏红线：逐条脱敏，单条失败丢弃该条；全部失败则阻断
        redacted_texts: List[str] = []
        for is_sender, text in sample:
            if remote:
                try:
                    outcome = redactor.redact(
                        text, account_wxid=account_wxid, conversation_id=conversation_id,
                        source_table="big5_impression", source_id="sample",
                    )
                    redacted_texts.append(outcome.redacted_text)
                except Exception as exc:
                    logger.debug("[大五增强] 单条脱敏失败丢弃: %s", exc)
                    continue
            else:
                redacted_texts.append(text)
        if not redacted_texts:
            return {"ok": False, "reason": "redaction_failed",
                    "message": "脱敏后无可用样本，已阻断（未发送原文）"}

        messages = self._render_prompt(subjects, redacted_texts)
        base_url = str(model_config.get("api_base_url") or model_config.get("base_url") or "").rstrip("/")
        headers = {}
        api_key = str(model_config.get("api_key") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            body = self._http(
                url=f"{base_url}/chat/completions",
                payload={
                    "model": model_config.get("model_id") or model_config.get("model_name"),
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": BIG5_RESPONSE_MAX_TOKENS,
                    "stream": False,
                },
                headers=headers,
                timeout=BIG5_TIMEOUT_SECONDS,
                max_retries=1,
                log=logger.debug,
                log_prefix="[大五增强]",
            )
        except Exception as exc:
            logger.error("[大五增强] LLM 调用失败: %s", exc)
            return {"ok": False, "reason": "llm_failed", "message": f"模型调用失败: {exc}"}

        content = self._extract_content(body)
        adjustments = self._parse_adjustments(content)
        if adjustments is None:
            return {"ok": False, "reason": "parse_failed", "message": "模型输出无法解析"}

        corpus = "\n".join(redacted_texts)
        for subject in SUBJECTS:
            base = subjects.get(subject)
            if not base:
                continue
            enhanced = self._apply_adjustments(base, adjustments, corpus)
            self._save_cache(
                conversation_id, account_wxid, subject, enhanced, "llm_enhanced",
                model_name=str(model_config.get("model_name") or ""),
            )

        payload = self.get_impressions(conversation_id, account_wxid, force_refresh=False)
        # 增强行刚落库，读回应为 llm_enhanced
        payload["enhanced"] = True
        return payload

    # ------------------------------------------------------------------
    # 指标采集 → 基础层
    # ------------------------------------------------------------------

    def _compute_local(
        self, conversation_id: int, subject: str, metrics=None
    ) -> Optional[Dict[str, Any]]:
        """单侧基础层：子指标采集 + big5_proxies 合成。样本过薄返回 None。"""
        raw = self._collect_raw_indicators(conversation_id, subject, metrics)
        if raw is None:
            return None
        scores = compute_big5_base(raw)
        return {
            "source": "local",
            "scores": scores,
            "indicators": raw,
        }

    def _collect_raw_indicators(
        self, conversation_id: int, subject: str, metrics=None
    ) -> Optional[Dict[str, Optional[float]]]:
        """采集单侧原始子指标（me → is_sender=1 / other → is_sender=0）。"""
        side_flag = 1 if subject == "me" else 0
        rows = get_db().execute(
            "SELECT is_sender, content, timestamp FROM messages "
            "WHERE conversation_id = ? AND message_type = 1 ORDER BY timestamp ASC, id ASC",
            (conversation_id,),
        ).fetchall()

        def _text(content: Any) -> str:
            if content is None:
                return ""
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return str(content)

        own_texts: List[str] = []
        late_night = 0
        reply_hits = 0
        reply_chances = 0

        # 交互扫描：对方发言后本方在 30 分钟内的首个回应（话题延续）
        last_other_ts: Optional[int] = None
        for row in rows:
            is_sender = int(row[0] or 0)
            text = _text(row[1]).strip()
            ts = int(row[2] or 0)
            if not text:
                continue
            if is_sender == side_flag:
                own_texts.append(text)
                if 0 <= time.localtime(ts).tm_hour < 6:
                    late_night += 1
                if last_other_ts is not None:
                    reply_chances += 1
                    if ts - last_other_ts <= 1800:
                        reply_hits += 1
                    last_other_ts = None
            else:
                last_other_ts = ts

        if len(own_texts) < BIG5_MIN_MESSAGES:
            return None

        # 情感子指标（缺 sentiment_cache → None，维度重归一）
        intensity_variance, negative_ratio, pos_neg_ratio = self._sentiment_indicators(
            conversation_id, side_flag
        )
        positive_response_rate = self._positive_response_rate(conversation_id, side_flag)

        # 词法子指标：表情/感叹/叠词密度、TTR、话题熵（抽样约束分词代价）
        emoji_hits = sum(1 for text in own_texts if _EMOJI_EXCLAIM_PATTERN.search(text))
        sample_texts = own_texts[:BIG5_TOKENIZE_LIMIT]
        ttr, entropy = self._lexical_indicators(sample_texts)

        empathy_density = self._empathy_density(own_texts)

        # 分享密度：图片/视频/链接 ÷ 文本
        share_row = get_db().execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND is_sender = ? "
            "AND (message_type IN (3, 43) OR (message_type = 1 AND content LIKE '%http%'))",
            (conversation_id, side_flag),
        ).fetchone()
        share_count = int(share_row[0] or 0)

        if metrics is None:
            metrics = EngagementMetricsService().compute(conversation_id)
        if subject == "me":
            icebreak_ratio = (
                metrics.icebreak_self / metrics.icebreak_total
                if metrics.icebreak_total else None
            )
            unanswered_rate = (
                (metrics.burst_unanswered_self + metrics.long_unanswered_self)
                / max(metrics.self_text_count, 1)
            )
            revoke_rate = metrics.revoke_self / max(metrics.self_text_count, 1)
            positive, negative = metrics.positive_self, metrics.negative_self
        else:
            icebreak_ratio = (
                metrics.icebreak_other / metrics.icebreak_total
                if metrics.icebreak_total else None
            )
            unanswered_rate = (
                (metrics.burst_unanswered_other + metrics.long_unanswered_other)
                / max(metrics.other_text_count, 1)
            )
            revoke_rate = metrics.revoke_other / max(metrics.other_text_count, 1)
            positive, negative = metrics.positive_other, metrics.negative_other

        # 正负比（sentiment_cache 缺席时用极性计数；两者都缺 → None）
        if pos_neg_ratio is None and (positive + negative) > 0:
            pos_neg_ratio = positive / (positive + negative)

        active_days = max(metrics.span_days, 1.0)
        daily_avg = len(own_texts) / active_days

        return {
            "daily_avg": round(daily_avg, 3),
            "icebreak_ratio": round(icebreak_ratio, 4) if icebreak_ratio is not None else None,
            "emoji_exclaim_density": round(emoji_hits / len(own_texts), 4),
            "unanswered_rate": round(unanswered_rate, 4),
            "daily_cv": round(metrics.daily_cv_active, 4) if metrics.daily_cv_active is not None else None,
            "topic_continuation": round(reply_hits / reply_chances, 4) if reply_chances else None,
            "intensity_variance": intensity_variance,
            "negative_ratio": negative_ratio,
            "late_night_ratio": round(late_night / len(own_texts), 4),
            "revoke_rate": round(revoke_rate, 4),
            "pos_neg_ratio": round(pos_neg_ratio, 4) if pos_neg_ratio is not None else None,
            "positive_response_rate": positive_response_rate,
            "empathy_density": empathy_density,
            "ttr": ttr,
            "topic_entropy": entropy,
            "share_density": round(share_count / len(own_texts), 4),
        }

    @staticmethod
    def _positive_response_rate(
        conversation_id: int, side_flag: int
    ) -> Optional[float]:
        """正向回应率：本方「30 分钟内回应对方」的消息中正向消息占比。

        近似口径：本方消息且此前 30 分钟内出现过对方消息即视为回应；
        依赖 sentiment_cache，缺缓存返回 None。
        """
        row = get_db().execute(
            """
            SELECT SUM(CASE WHEN sc.polarity = 1 THEN 1 ELSE 0 END), COUNT(*)
            FROM messages m
            JOIN sentiment_cache sc ON sc.message_id = m.id
            WHERE m.conversation_id = ? AND m.is_sender = ? AND m.message_type = 1
                AND EXISTS (
                    SELECT 1 FROM messages p
                    WHERE p.conversation_id = m.conversation_id
                        AND p.is_sender != m.is_sender
                        AND p.timestamp <= m.timestamp
                        AND m.timestamp - p.timestamp <= 1800
                )
            """,
            (conversation_id, side_flag),
        ).fetchone()
        if not row or not row[1]:
            return None
        return round(int(row[0] or 0) / int(row[1]), 4)

    @staticmethod
    def _sentiment_indicators(
        conversation_id: int, side_flag: int
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """本方情感子指标：intensity 方差 / 负面占比 / 正负比（缺缓存全 None）。"""
        rows = get_db().execute(
            "SELECT sc.polarity, sc.intensity FROM sentiment_cache sc "
            "JOIN messages m ON sc.message_id = m.id "
            "WHERE m.conversation_id = ? AND m.is_sender = ?",
            (conversation_id, side_flag),
        ).fetchall()
        if not rows:
            return None, None, None
        polarities = [int(r[0] or 0) for r in rows]
        intensities = [float(r[1] or 0) for r in rows]
        mean = sum(intensities) / len(intensities)
        variance = sum((v - mean) ** 2 for v in intensities) / len(intensities)
        positive = sum(1 for p in polarities if p == 1)
        negative = sum(1 for p in polarities if p == -1)
        # 正负比：正向占非中性比（与 EngagementMetrics 路径同口径）
        return (
            round(variance, 5),
            round(negative / len(polarities), 4),
            round(positive / (positive + negative), 4) if (positive + negative) else None,
        )

    @staticmethod
    def _lexical_indicators(texts: List[str]) -> Tuple[Optional[float], Optional[float]]:
        """TTR 与词频分布熵（jieba 分词，熵除以 log(词表大小) 归一）。"""
        if not texts:
            return None, None
        try:
            import jieba
        except ImportError:
            return None, None
        tokens: List[str] = []
        for text in texts:
            tokens.extend(t.strip() for t in jieba.cut(text) if len(t.strip()) > 1)
        if not tokens:
            return None, None
        counts: Dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        total = len(tokens)
        vocab = len(counts)
        ttr = round(vocab / total, 4)
        entropy_raw = -sum((c / total) * math.log(c / total) for c in counts.values())
        entropy = round(entropy_raw / math.log(vocab), 4) if vocab > 1 else 0.0
        return ttr, entropy

    @staticmethod
    def _empathy_density(texts: List[str]) -> Optional[float]:
        """宜人性词表密度：empathy/soothing 词命中的消息占比。"""
        from .keyword_libraries import KeywordLibraries

        try:
            lib = KeywordLibraries()
            keywords = lib.get_keywords(KeywordLibraries.EMPATHY) + lib.get_keywords(
                KeywordLibraries.SOOTHING
            )
        except Exception as exc:
            logger.warning("[大五基础层] 词表加载失败，宜人性密度缺席: %s", exc)
            return None
        if not keywords or not texts:
            return None
        hits = sum(1 for text in texts if any(k in text for k in keywords))
        return round(hits / len(texts), 4)

    # ------------------------------------------------------------------
    # LLM 增强层辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _sample_conversation(conversation_id: int) -> List[Tuple[int, str]]:
        """时间均匀分桶抽样双方消息，目标 ~12000 字符（带 [我]/[TA] 标记由渲染层加）。"""
        rows = get_db().execute(
            "SELECT is_sender, content, timestamp FROM messages "
            "WHERE conversation_id = ? AND message_type = 1 "
            "AND content IS NOT NULL AND TRIM(content) != '' "
            "ORDER BY timestamp ASC, id ASC",
            (conversation_id,),
        ).fetchall()
        if not rows:
            return []
        decoded = [
            (int(r[0] or 0), (r[1].decode("utf-8", "replace") if isinstance(r[1], bytes) else str(r[1])).strip(), int(r[2] or 0))
            for r in rows
        ]
        if len(decoded) <= BIG5_SAMPLE_TURN_LIMIT:
            return [(s, t) for s, t, _ in decoded]
        step = (len(decoded) - 1) / (BIG5_SAMPLE_TURN_LIMIT - 1)
        sampled = [decoded[round(i * step)] for i in range(BIG5_SAMPLE_TURN_LIMIT)]
        # 字符预算：从头按目标长度截取（保留抽样分布）
        result: List[Tuple[int, str]] = []
        used = 0
        for is_sender, text, _ in sampled:
            if used + len(text) > BIG5_SAMPLE_TARGET_CHARS and result:
                break
            result.append((is_sender, text))
            used += len(text)
        return result

    def _render_prompt(
        self, subjects: Dict[str, Any], sample_texts: List[str]
    ) -> List[dict]:
        lines: List[str] = ["【大五基础分数（纯统计，0-100）】"]
        for subject, label in (("me", "我"), ("other", "TA")):
            data = subjects.get(subject)
            if not data:
                continue
            lines.append(f"[{label}]")
            for dim in DIMENSIONS:
                item = (data.get("scores") or {}).get(dim) or {}
                if item.get("score") is None:
                    continue
                lines.append(f"- {item.get('label', dim)}: {item['score']}")
        lines.append("")
        lines.append(f"【聊天记录样本（{len(sample_texts)} 条，已按需脱敏）】")
        for text in sample_texts:
            lines.append(text)
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

    @staticmethod
    def _extract_content(body: dict) -> str:
        try:
            return str(body["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _parse_adjustments(content: str) -> Optional[Dict[str, Dict[str, Any]]]:
        """解析模型输出；容忍 ```json 包裹；五维缺任一维即视为解析失败。"""
        text = content.strip()
        fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
        result: Dict[str, Dict[str, Any]] = {}
        for dim in DIMENSIONS:
            item = data.get(dim)
            if not isinstance(item, dict):
                return None
            try:
                adjustment = int(item.get("adjustment", 0))
            except (TypeError, ValueError):
                return None
            result[dim] = {
                "adjustment": adjustment,
                "reason": str(item.get("reason") or "")[:120],
                "evidence_quote": str(item.get("evidence_quote") or "")[:80],
            }
        return result

    @staticmethod
    def _apply_adjustments(
        base: Dict[str, Any], adjustments: Dict[str, Dict[str, Any]], corpus: str
    ) -> Dict[str, Any]:
        """双重钳制 + 证据子串校验，产出增强层行。"""
        scores = base.get("scores") or {}
        enhanced_scores: Dict[str, Any] = {}
        evidence: Dict[str, Any] = {}
        for dim in DIMENSIONS:
            item = dict(scores.get(dim) or {})
            adj_item = adjustments.get(dim) or {}
            base_score = item.get("score")
            if base_score is None:
                enhanced_scores[dim] = item
                continue
            adjustment = adj_item.get("adjustment", 0)
            # 钳 1：校正量绝对值 ≤ 15；钳 2：落点 0-100
            bounded = max(-BIG5_LLM_ADJUST_LIMIT, min(BIG5_LLM_ADJUST_LIMIT, adjustment))
            final = max(0.0, min(100.0, base_score + bounded))
            item["score"] = round(final, 1)
            item["base_score"] = base_score
            item["adjustment"] = bounded
            enhanced_scores[dim] = item
            quote = str(adj_item.get("evidence_quote") or "")
            # 证据必须是（脱敏后）语料子串，否则丢弃证据（分数保留）
            if quote and quote in corpus:
                evidence[dim] = {
                    "quote": quote,
                    "reason": adj_item.get("reason", ""),
                }
            else:
                evidence[dim] = {"quote": "", "reason": adj_item.get("reason", "")}
        return {
            "source": "llm_enhanced",
            "scores": enhanced_scores,
            "evidence": evidence,
            "indicators": base.get("indicators"),
        }

    # ------------------------------------------------------------------
    # 表缓存（_ensure_table 轻迁移，沿 contact_profiles 先例）
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_table(conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS big5_impressions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                account_wxid TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL,
                source TEXT NOT NULL,
                prompt_version INTEGER NOT NULL,
                scores_json TEXT NOT NULL,
                base_scores_json TEXT,
                evidence_json TEXT,
                indicators_json TEXT,
                model_name TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                UNIQUE(conversation_id, account_wxid, subject, prompt_version, source)
            )
            """
        )
        conn.commit()

    def _save_cache(
        self,
        conversation_id: int,
        account_wxid: str,
        subject: str,
        payload: Dict[str, Any],
        source: str,
        model_name: Optional[str],
    ) -> None:
        now = int(time.time())
        conn = get_db()
        self._ensure_table(conn)
        scores = payload.get("scores") or {}
        conn.execute(
            """
            INSERT OR REPLACE INTO big5_impressions
            (conversation_id, account_wxid, subject, source, prompt_version,
             scores_json, base_scores_json, evidence_json, indicators_json,
             model_name, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(conversation_id), account_wxid, subject, source, BIG5_PROMPT_VERSION,
                json.dumps(scores, ensure_ascii=False),
                json.dumps(
                    {d: (scores.get(d) or {}).get("base_score") for d in DIMENSIONS},
                    ensure_ascii=False,
                ) if source == "llm_enhanced" else None,
                json.dumps(payload.get("evidence"), ensure_ascii=False) if source == "llm_enhanced" else None,
                json.dumps(payload.get("indicators"), ensure_ascii=False),
                model_name,
                now, now + BIG5_TTL_SECONDS,
            ),
        )
        conn.commit()

    def _load_cached(
        self, conversation_id: int, account_wxid: str, subject: str, now: int
    ) -> Optional[Dict[str, Any]]:
        """读未过期缓存：llm_enhanced 优先于 local。"""
        conn = get_db()
        try:
            self._ensure_table(conn)
        except Exception:
            return None
        for source in ("llm_enhanced", "local"):
            row = conn.execute(
                "SELECT scores_json, evidence_json, indicators_json, model_name, created_at "
                "FROM big5_impressions WHERE conversation_id = ? AND account_wxid = ? "
                "AND subject = ? AND source = ? AND prompt_version = ? AND expires_at > ?",
                (conversation_id, account_wxid, subject, source, BIG5_PROMPT_VERSION, now),
            ).fetchone()
            if not row:
                continue
            try:
                scores = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                continue
            payload: Dict[str, Any] = {
                "source": source,
                "scores": scores,
                "indicators": json.loads(row[2]) if row[2] else None,
                "created_at": int(row[4] or 0),
            }
            if source == "llm_enhanced":
                payload["evidence"] = json.loads(row[1]) if row[1] else {}
                payload["model_name"] = row[3]
            return payload
        return None
