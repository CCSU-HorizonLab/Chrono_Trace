"""
隐式反馈对比 + 动态规则提取器

当用户发送了一条消息后，系统将该消息与最近的 AI 建议进行对比；
如果偏差较大，则调用 LLM 深度分析原因并提炼出行为规则，
存入 contact_rules 表，供后续建议生成时作为最高戒律注入 Prompt。
"""

import json
import logging
import time
import urllib.request
import urllib.error
import re
from typing import Optional

logger = logging.getLogger(__name__)

TEXT_MESSAGE_TYPE = 1
IMAGE_MESSAGE_TYPES = {3, 47, "image", "img", "sticker", "emoji"}
VOICE_MESSAGE_TYPES = {34, "voice", "audio"}
SHORT_ACK_MARKERS = {
    "嗯",
    "嗯嗯",
    "哦",
    "哦哦",
    "好",
    "好的",
    "好吧",
    "行",
    "行吧",
    "可",
    "可以",
    "ok",
    "okay",
    "收到",
    "知道了",
}
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)


def _print(msg: str):
    """统一打印"""
    print(msg, flush=True)


# ==================== 轻量文本相似度 ====================

def _simple_similarity(text_a: str, text_b: str) -> float:
    """
    使用字符级 bigram Jaccard 相似度做轻量判断。
    返回 0.0-1.0；> 0.6 视为"大致采纳"。
    """
    if not text_a or not text_b:
        return 0.0

    def bigrams(s: str) -> set:
        s = s.strip().lower()
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    a_set = bigrams(text_a)
    b_set = bigrams(text_b)
    if not a_set or not b_set:
        return 0.0
    intersection = a_set & b_set
    union = a_set | b_set
    return len(intersection) / len(union) if union else 0.0


# ==================== 规则提取 Prompt ====================

COMPARE_SYSTEM_PROMPT = """你是一个行为分析专家。你的任务是对比 AI 给用户的建议话术与用户最终实际发出的消息，
从中提炼出一条简短的行为规则，帮助 AI 下次更准确地模仿用户。

规则应当描述用户在此类场景下的真实偏好或习惯。
优先提炼表达风格、字数长短、表情/语音/图片偏好、口语化程度，不要总结具体聊天话题。
规则要简短、具体、可执行（不超过30字），例如：
- "用户回复提问时只用两三个字打发"
- "用户从不用成语，只用大白话"
- "用户喜欢用表情包代替文字回复"
- "用户对这个人从不主动表达关心"

严格按 JSON 格式输出，禁止输出任何其他内容：
{"rule": "...", "confidence": 0.0-1.0, "scope": "contact"}
"""


def _normalize_message_type(message_type: Optional[int | str]) -> str:
    if message_type is None:
        return "text"
    if isinstance(message_type, str):
        normalized = message_type.strip().lower()
        if normalized in {"text", "txt", "1"}:
            return "text"
        if normalized in IMAGE_MESSAGE_TYPES:
            return "image"
        if normalized in VOICE_MESSAGE_TYPES:
            return "voice"
        return normalized or "text"
    try:
        numeric_type = int(message_type)
    except (TypeError, ValueError):
        return "text"
    if numeric_type == TEXT_MESSAGE_TYPE:
        return "text"
    if numeric_type in {3, 47}:
        return "image"
    if numeric_type == 34:
        return "voice"
    return str(numeric_type)


def _compact_text(text: str) -> str:
    return str(text or "").strip().replace(" ", "")


def _count_emojis(text: str) -> int:
    return len(EMOJI_PATTERN.findall(text or ""))


def _best_matching_speech(ai_speeches: list[str], user_actual_message: str) -> tuple[str, float]:
    best_speech = ""
    best_similarity = -1.0
    for speech in ai_speeches:
        similarity = _simple_similarity(speech, user_actual_message)
        if similarity > best_similarity:
            best_similarity = similarity
            best_speech = speech
    return best_speech, max(best_similarity, 0.0)


def _looks_like_short_ack(text: str) -> bool:
    compact = _compact_text(text)
    if not compact:
        return False
    return compact.casefold() in SHORT_ACK_MARKERS


class FeedbackRuleExtractor:
    """隐式反馈规则提取器"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    # ==================== 核心方法 ====================

    def analyze_feedback(
        self,
        ai_speeches: list[str],
        user_actual_message: str,
        display_name: str = "",
        suggestion_id: Optional[int] = None,
        user_message_type: Optional[int | str] = None,
    ) -> dict:
        """Compare suggestion vs actual message and return a structured outcome."""
        result = {
            "outcome": "skipped",
            "max_similarity": 0.0,
            "selected_speech": "",
            "actual_message_type": _normalize_message_type(user_message_type),
            "rules": [],
            "rule_source": None,
        }
        if not ai_speeches or not user_actual_message:
            return result

        best_speech, max_sim = _best_matching_speech(ai_speeches, user_actual_message)
        result["max_similarity"] = round(max_sim, 3)
        result["selected_speech"] = best_speech

        _print(f"[FeedbackRule] 📊 相似度最高: {max_sim:.2f} (阈值: 0.55)")

        heuristic_rules = self._extract_heuristic_rules(
            ai_speeches=ai_speeches,
            user_actual_message=user_actual_message,
            user_message_type=user_message_type,
            best_speech=best_speech,
        )
        if heuristic_rules:
            _print(
                "[FeedbackRule] 🧭 命中结构化偏差信号，直接沉淀规则: "
                + " / ".join(rule["rule"] for rule in heuristic_rules)
            )
            for rule in heuristic_rules:
                self.save_rule(
                    display_name=display_name,
                    rule_text=rule.get("rule", ""),
                    confidence=rule.get("confidence", 0.7),
                    scope=rule.get("scope", "contact"),
                    source_suggestion_id=suggestion_id,
                )
            result["outcome"] = "rewritten"
            result["rules"] = heuristic_rules
            result["rule_source"] = "heuristic"
            return result

        if max_sim > 0.55:
            _print(f"[FeedbackRule] ✅ 判定为采纳（相似度 {max_sim:.2f}），跳过规则提取")
            result["outcome"] = "adopted"
            return result

        _print(f"[FeedbackRule] 🔍 偏差较大，启动 LLM 深度对比分析...")
        rule = self._llm_compare(ai_speeches, user_actual_message)
        if rule:
            self.save_rule(
                display_name=display_name,
                rule_text=rule.get('rule', ''),
                confidence=rule.get('confidence', 0.7),
                scope=rule.get('scope', 'contact'),
                source_suggestion_id=suggestion_id,
            )
            result["outcome"] = "rewritten"
            result["rules"] = [rule]
            result["rule_source"] = "llm"
            return result

        result["outcome"] = "rewritten"
        return result

    def compare_and_extract(
        self,
        ai_speeches: list[str],
        user_actual_message: str,
        display_name: str,
        suggestion_id: Optional[int] = None,
        user_message_type: Optional[int | str] = None,
    ) -> Optional[dict]:
        """
        对比 AI 建议与用户实际发送，提取调教规则。

        Args:
            ai_speeches: AI 给出的话术列表
            user_actual_message: 用户最终实际发送的消息
            display_name: 联系人显示名
            suggestion_id: 触发提取的建议记录 ID

        Returns:
            提取到的规则 dict 或 None（若判断为采纳）
        """
        analysis = self.analyze_feedback(
            ai_speeches=ai_speeches,
            user_actual_message=user_actual_message,
            display_name=display_name,
            suggestion_id=suggestion_id,
            user_message_type=user_message_type,
        )
        rules = analysis.get("rules") or []
        if not rules:
            return None

        primary_rule = dict(rules[0])
        primary_rule["rules"] = rules
        primary_rule["source"] = analysis.get("rule_source")
        primary_rule["best_similarity"] = analysis.get("max_similarity", 0.0)
        primary_rule["outcome"] = analysis.get("outcome")
        primary_rule["selected_speech"] = analysis.get("selected_speech", "")
        return primary_rule

    def _extract_heuristic_rules(
        self,
        *,
        ai_speeches: list[str],
        user_actual_message: str,
        user_message_type: Optional[int | str] = None,
        best_speech: str = "",
    ) -> list[dict]:
        """优先提取稳定的表达风格差异，减少对 LLM 发挥的依赖。"""
        actual_message = str(user_actual_message or "").strip()
        if not actual_message:
            return []

        message_type = _normalize_message_type(user_message_type)
        rules: list[dict] = []

        def add_rule(rule_text: str, confidence: float) -> None:
            rule_text = str(rule_text or "").strip()
            if not rule_text:
                return
            if any(existing["rule"] == rule_text for existing in rules):
                return
            rules.append(
                {
                    "rule": rule_text,
                    "confidence": confidence,
                    "scope": "contact",
                }
            )

        if message_type == "image":
            add_rule("用户这类场景更爱用图片/表情回复，不会打长文字", 0.9)
            return rules

        if message_type == "voice":
            add_rule("用户这类场景更爱用语音回复，不会打长文字", 0.88)
            return rules

        reference_speech = str(best_speech or "").strip()
        if not reference_speech:
            return []

        actual_length = len(_compact_text(actual_message))
        reference_length = len(_compact_text(reference_speech))
        actual_emoji_count = _count_emojis(actual_message)
        reference_emoji_count = _count_emojis(reference_speech)

        if actual_emoji_count == 0 and reference_emoji_count > 0:
            add_rule("用户给这个人发消息基本不用表情", 0.82)
        elif actual_emoji_count > 0 and reference_emoji_count == 0:
            add_rule("用户给这个人回复会自然带表情", 0.78)

        if (
            _looks_like_short_ack(actual_message)
            and reference_length >= 7
            and not _looks_like_short_ack(reference_speech)
        ):
            add_rule("用户在这类场景只会简短肯定，不展开解释", 0.86)
        elif (
            actual_length > 0
            and reference_length >= 8
            and actual_length <= max(4, int(reference_length * 0.55))
            and reference_length - actual_length >= 4
        ):
            add_rule("用户更常用更短的短句回复，不会铺垫太多", 0.8)

        return rules[:2]

    def _llm_compare(self, ai_speeches: list[str], user_message: str) -> Optional[dict]:
        """调用 LLM 对比分析"""
        try:
            model_config = self._get_active_model()
            if not model_config:
                _print("[FeedbackRule] ❌ 无激活模型，跳过 LLM 对比")
                return None

            speeches_text = "\n".join(
                f"  {i+1}. {s}" for i, s in enumerate(ai_speeches)
            )
            user_prompt = (
                f"【AI当时的建议话术】\n{speeches_text}\n\n"
                f"【用户最终实际发送的消息】\n  {user_message}\n\n"
                "请优先分析表达风格差异，例如：字数长短、短句/长句、"
                "表情或语音/图片偏好、口语化程度、是否只做简短肯定。"
                "不要总结具体聊了什么话题，只提炼下次还能复用的表达规则。"
            )

            base_url = model_config['api_base_url'].rstrip('/')
            api_key = model_config.get('api_key', '')
            model_id = model_config['model_id']

            url = f"{base_url}/chat/completions"
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": COMPARE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 200,
                "temperature": 0.3,
            }

            data = json.dumps(payload).encode('utf-8')
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            _print(f"[FeedbackRule] 📤 POST {url}")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode('utf-8'))

            # 提取响应内容
            content = ''
            choices = body.get('choices', [])
            if choices:
                msg = choices[0].get('message', {})
                content = msg.get('content', '') or msg.get('reasoning_content', '') or ''

            if not content:
                _print("[FeedbackRule] ⚠️ LLM 返回空内容")
                return None

            _print(f"[FeedbackRule] 📥 LLM 响应: {content[:200]}")

            # 解析 JSON
            return self._parse_rule_json(content)

        except Exception as e:
            _print(f"[FeedbackRule] ❌ LLM 对比失败: {e}")
            return None

    def _parse_rule_json(self, text: str) -> Optional[dict]:
        """解析 LLM 返回的规则 JSON"""
        try:
            cleaned = text.strip()
            if '```json' in cleaned:
                cleaned = cleaned.split('```json', 1)[1].split('```', 1)[0]
            elif '```' in cleaned:
                cleaned = cleaned.split('```', 1)[1].split('```', 1)[0]

            data = json.loads(cleaned.strip())
            if 'rule' not in data or not data['rule']:
                _print(f"[FeedbackRule] ⚠️ 规则内容为空")
                return None
            return data
        except (json.JSONDecodeError, KeyError) as e:
            _print(f"[FeedbackRule] JSON 解析失败: {e}, 原文: {text[:200]}")
            return None

    # ==================== 数据库操作 ====================

    def save_rule(
        self,
        display_name: str,
        rule_text: str,
        confidence: float = 0.7,
        scope: str = 'contact',
        source_suggestion_id: Optional[int] = None,
    ):
        """保存规则到数据库（自动去重合并）"""
        if not rule_text or not rule_text.strip():
            return

        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)

            now = int(time.time())

            # 去重检查：与已有规则做文本相似度
            existing = conn.execute(
                'SELECT id, rule_text, confidence, hit_count FROM contact_rules WHERE display_name = ?',
                (display_name,)
            ).fetchall()

            for row in existing:
                sim = _simple_similarity(rule_text, row['rule_text'])
                if sim > 0.6:
                    # 高度相似 → 合并：提升置信度和命中次数
                    new_conf = min(1.0, row['confidence'] + 0.1)
                    new_hits = row['hit_count'] + 1
                    conn.execute(
                        'UPDATE contact_rules SET confidence = ?, hit_count = ?, updated_at = ? WHERE id = ?',
                        (new_conf, new_hits, now, row['id'])
                    )
                    conn.commit()
                    _print(f"[FeedbackRule] 🔄 规则已合并 (id={row['id']}, conf={new_conf:.2f}, hits={new_hits})")
                    return

            # 全新规则 → 插入
            conn.execute('''
                INSERT INTO contact_rules
                (display_name, rule_text, confidence, scope, source_suggestion_id, hit_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ''', (display_name, rule_text.strip(), confidence, scope, source_suggestion_id, now, now))
            conn.commit()
            _print(f"[FeedbackRule] 💾 新规则已保存: \"{rule_text.strip()}\" (conf={confidence:.2f})")

        except Exception as e:
            _print(f"[FeedbackRule] ❌ 保存规则失败: {e}")

    def get_active_rules(self, display_name: str) -> list[str]:
        """获取该联系人的有效规则列表（置信度 >= 0.5）"""
        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)

            cursor = conn.execute('''
                SELECT rule_text FROM contact_rules
                WHERE (display_name = ? OR scope = 'global')
                  AND confidence >= 0.5
                ORDER BY confidence DESC, hit_count DESC
                LIMIT 10
            ''', (display_name,))

            rules = [row['rule_text'] for row in cursor.fetchall()]
            if rules:
                _print(f"[FeedbackRule] 📋 已加载 {len(rules)} 条调教规则")
            return rules

        except Exception as e:
            _print(f"[FeedbackRule] ❌ 获取规则失败: {e}")
            return []

    def _ensure_table(self, conn):
        """确保 contact_rules 表存在"""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contact_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                rule_text TEXT NOT NULL,
                confidence REAL DEFAULT 0.7,
                scope TEXT DEFAULT 'contact',
                source_suggestion_id INTEGER,
                hit_count INTEGER DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        ''')

    def _get_active_model(self) -> Optional[dict]:
        """从数据库获取当前激活的 LLM 模型配置"""
        try:
            from ...db.connection import get_db
            conn = get_db()
            cursor = conn.execute(
                'SELECT * FROM llm_models WHERE is_active = 1 LIMIT 1'
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            _print(f"[FeedbackRule] 获取模型配置失败: {e}")
            return None
