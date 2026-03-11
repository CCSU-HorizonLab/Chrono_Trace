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
规则要简短、具体、可执行（不超过30字），例如：
- "用户回复提问时只用两三个字打发"
- "用户从不用成语，只用大白话"
- "用户喜欢用表情包代替文字回复"
- "用户对这个人从不主动表达关心"

严格按 JSON 格式输出，禁止输出任何其他内容：
{"rule": "...", "confidence": 0.0-1.0, "scope": "contact"}
"""


class FeedbackRuleExtractor:
    """隐式反馈规则提取器"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    # ==================== 核心方法 ====================

    def compare_and_extract(
        self,
        ai_speeches: list[str],
        user_actual_message: str,
        display_name: str,
        suggestion_id: Optional[int] = None,
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
        if not ai_speeches or not user_actual_message:
            return None

        # 第一步：轻量相似度筛查
        max_sim = max(
            _simple_similarity(speech, user_actual_message)
            for speech in ai_speeches
        )

        _print(f"[FeedbackRule] 📊 相似度最高: {max_sim:.2f} (阈值: 0.55)")

        if max_sim > 0.55:
            _print(f"[FeedbackRule] ✅ 判定为采纳（相似度 {max_sim:.2f}），跳过规则提取")
            return None

        # 第二步：调用 LLM 深度对比
        _print(f"[FeedbackRule] 🔍 偏差较大，启动 LLM 深度对比分析...")
        rule = self._llm_compare(ai_speeches, user_actual_message)

        if rule:
            # 第三步：保存规则
            self.save_rule(
                display_name=display_name,
                rule_text=rule.get('rule', ''),
                confidence=rule.get('confidence', 0.7),
                scope=rule.get('scope', 'contact'),
                source_suggestion_id=suggestion_id,
            )
            return rule

        return None

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
                f"请分析用户拒绝AI建议的根本原因，并提炼一条规则。"
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
