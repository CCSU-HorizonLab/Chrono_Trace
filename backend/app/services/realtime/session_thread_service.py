"""
会话线程归档与长期记忆检索服务

功能：
1. archive_thread：退出悬浮窗时自动打包 AI 指导会话，调 LLM 生成一句话总结
2. get_latest_thread / load_thread_context：支持"继续上次指导"功能
3. retrieve_relevant_memories：轻量 TF-IDF 检索历史线程，实现 RAG 长期记忆唤醒
"""

import json
import logging
import math
import re
import time
import urllib.request
import urllib.error
from collections import Counter
from typing import Optional
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file

logger = logging.getLogger(__name__)


def _print(msg: str):
    """统一打印"""
    print(msg, flush=True)


# LLM 总结用 System Prompt
SUMMARY_SYSTEM_PROMPT = """你是一个聊天记录总结专家。
请只根据双方真实聊天内容，总结这段对话本身在聊什么，忽略 AI 建议、系统提示和分析过程。

要求：
1. 用一句话总结，50 字以内
2. 优先概括话题、事件、情绪变化或推进结果
3. 不要提及 AI、建议、系统、辅助、分析
4. 同时提取 3-5 个关键词，用逗号分隔

输出格式（纯 JSON）：
{"summary": "一句话总结", "keywords": "关键词1,关键词2,关键词3"}"""


# ==================== 轻量 TF-IDF 工具 ====================

# 中文分词：按标点和空格粗切 + 2-gram
def _tokenize(text: str) -> list[str]:
    """简单中文分词（标点切分 + bigram）"""
    # 去除标点，按空格和标点切分
    segments = re.split(r'[，。！？、；：\s,.!?;:\n\r]+', text.strip())
    tokens = []
    for seg in segments:
        seg = seg.strip()
        if len(seg) <= 1:
            continue
        # 对每个片段提取 bigram
        for i in range(len(seg) - 1):
            tokens.append(seg[i:i+2])
        if len(seg) >= 3:
            tokens.append(seg)  # 整段也作为一个 token
    return tokens


def _tf(tokens: list[str]) -> dict[str, float]:
    """计算词频"""
    counter = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {t: c / total for t, c in counter.items()}


def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """计算两个稀疏向量的余弦相似度"""
    if not vec_a or not vec_b:
        return 0.0
    
    common_keys = set(vec_a.keys()) & set(vec_b.keys())
    if not common_keys:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in common_keys)
    norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ==================== 核心服务 ====================

class SessionThreadService:
    """会话线程归档与检索服务"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def _resolve_account_wxid(self, account_wxid: Optional[str]) -> str:
        normalized = str(account_wxid or "").strip()
        if normalized:
            return normalized
        try:
            return get_active_wechat_account_wxid(load_settings_from_file())
        except Exception:
            return ""

    # ---------- 归档 ----------

    def archive_thread(
        self,
        batch_id: str,
        display_name: str,
        messages: list[dict],
        suggestions: list[dict],
        start_time: Optional[int] = None,
        user_chat_history: Optional[list[dict]] = None,
        account_wxid: str = "",
    ) -> Optional[int]:
        """
        归档一次 AI 辅助指导会话。

        Args:
            batch_id: 监听批次 ID
            display_name: 联系人显示名
            messages: 微信消息列表
            suggestions: AI 建议列表
            start_time: 会话开始时间戳

        Returns:
            新线程的 ID，失败返回 None
        """
        if not messages and not suggestions:
            _print("[SessionThread] 无消息和建议，跳过归档")
            return None

        _print(f"[SessionThread] 📦 开始归档: {display_name}, "
               f"{len(messages)} 条消息, {len(suggestions)} 条建议")

        # 生成总结
        summary_data = self._generate_summary(messages, suggestions)
        summary = summary_data.get('summary', '（无总结）') if summary_data else '（无总结）'
        keywords = summary_data.get('keywords', '') if summary_data else ''

        # 计算持续时长
        now = int(time.time())
        duration = now - start_time if start_time else 0

        # 截断快照（避免存储过大）
        msg_snapshot = json.dumps(
            messages[-30:],  # 最多保留最近 30 条
            ensure_ascii=False
        )
        sug_snapshot = json.dumps(
            suggestions[-10:],  # 最多保留最近 10 条建议
            ensure_ascii=False
        )
        chat_snapshot = json.dumps(
            user_chat_history if user_chat_history else [],
            ensure_ascii=False
        )

        # 写入数据库
        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cursor = conn.execute('''
                INSERT INTO session_threads
                (account_wxid, batch_id, display_name, summary, keywords,
                 messages_snapshot, suggestions_snapshot,
                 message_count, suggestion_count, created_at, duration_seconds,
                 user_chat_history_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                resolved_account_wxid,
                batch_id, display_name, summary, keywords,
                msg_snapshot, sug_snapshot,
                len(messages), len(suggestions),
                now, duration,
                chat_snapshot
            ))
            conn.commit()
            thread_id = cursor.lastrowid

            _print(f"[SessionThread] ✅ 归档完成! thread_id={thread_id}, "
                   f"总结: {summary}")
            return thread_id

        except Exception as e:
            _print(f"[SessionThread] ❌ 归档失败: {e}")
            return None

    # ---------- 查询 ----------

    def get_latest_thread(self, display_name: str, max_age_hours: int = 24, account_wxid: str = "") -> Optional[dict]:
        """
        获取该联系人最近一个线程（24 小时内）。

        Returns:
            线程数据 dict 或 None
        """
        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cutoff = int(time.time()) - max_age_hours * 3600
            row = conn.execute('''
                SELECT id, account_wxid, batch_id, display_name, summary, keywords,
                       message_count, suggestion_count, created_at, duration_seconds
                FROM session_threads
                WHERE account_wxid = ? AND display_name = ? AND created_at >= ?
                ORDER BY created_at DESC LIMIT 1
            ''', (resolved_account_wxid, display_name, cutoff)).fetchone()

            if row:
                return dict(row)
            return None

        except Exception as e:
            _print(f"[SessionThread] ❌ 查询最近线程失败: {e}")
            return None

    def load_thread_context(self, thread_id: int) -> Optional[dict]:
        """
        加载线程的完整上下文（用于继续上次指导）。

        Returns:
            {"messages": [...], "suggestions": [...], "summary": "...", ...}
        """
        try:
            from ...db.connection import get_db
            conn = get_db()

            row = conn.execute(
                'SELECT * FROM session_threads WHERE id = ?', (thread_id,)
            ).fetchone()

            if not row:
                return None

            data = dict(row)
            # 解析 JSON 快照
            data['messages'] = json.loads(data.get('messages_snapshot') or '[]')
            data['suggestions'] = json.loads(data.get('suggestions_snapshot') or '[]')
            data['user_chat_history'] = json.loads(data.get('user_chat_history_snapshot') or '[]')
            # 清理大字段
            data.pop('messages_snapshot', None)
            data.pop('suggestions_snapshot', None)
            data.pop('user_chat_history_snapshot', None)

            _print(f"[SessionThread] 📂 已加载线程 #{thread_id}: "
                   f"{len(data['messages'])} 消息, {len(data['suggestions'])} 建议")
            return data

        except Exception as e:
            _print(f"[SessionThread] ❌ 加载线程失败: {e}")
            return None

    # ---------- RAG: 记忆检索 ----------

    def retrieve_relevant_memories(
        self,
        display_name: str,
        current_messages: list[dict],
        top_k: int = 2,
        min_score: float = 0.15,
        account_wxid: str = "",
    ) -> list[dict]:
        """
        根据当前对话内容，从历史线程中检索相关记忆。

        Args:
            display_name: 联系人显示名
            current_messages: 最近的微信消息列表
            top_k: 返回最多几条相关记忆
            min_score: 最低相似度阈值

        Returns:
            [{"summary": "...", "keywords": "...", "created_at": ..., "score": ...}, ...]
        """
        if not current_messages:
            return []

        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            # 读取该联系人所有历史线程
            rows = conn.execute('''
                SELECT id, summary, keywords, created_at, duration_seconds
                FROM session_threads
                WHERE account_wxid = ? AND display_name = ?
                ORDER BY created_at DESC
                LIMIT 50
            ''', (resolved_account_wxid, display_name)).fetchall()

            if not rows:
                return []

            # 构建当前对话的 TF 向量
            current_text = ' '.join(
                msg.get('content', '') for msg in current_messages[-5:]
                if msg.get('content')
            )
            if not current_text.strip():
                return []

            current_tokens = _tokenize(current_text)
            current_tf = _tf(current_tokens)

            # 对每条历史线程计算相似度
            scored = []
            for row in rows:
                thread_text = f"{row['summary'] or ''} {row['keywords'] or ''}"
                thread_tokens = _tokenize(thread_text)
                thread_tf = _tf(thread_tokens)

                score = _cosine_similarity(current_tf, thread_tf)
                if score >= min_score:
                    scored.append({
                        'id': row['id'],
                        'summary': row['summary'],
                        'keywords': row['keywords'],
                        'created_at': row['created_at'],
                        'score': round(score, 3),
                    })

            # 按相似度排序，取 top_k
            scored.sort(key=lambda x: x['score'], reverse=True)
            results = scored[:top_k]

            if results:
                _print(f"[SessionThread] 🧠 RAG 匹配到 {len(results)} 条相关记忆 "
                       f"(top: {results[0]['score']:.3f})")

            return results

        except Exception as e:
            _print(f"[SessionThread] ❌ 记忆检索失败: {e}")
            return []

    # ---------- 内部方法 ----------

    def _generate_summary(self, messages: list[dict], suggestions: list[dict]) -> Optional[dict]:
        """调用 LLM 生成一句话总结"""
        try:
            model_config = self._get_active_model()
            if not model_config:
                _print("[SessionThread] 无激活模型，使用默认总结")
                return {'summary': f'与对方的一次聊天（{len(messages)}条消息）', 'keywords': ''}

            chat_messages = [
                msg for msg in messages
                if msg.get('sender_attr') != 'system' and (msg.get('content') or '').strip()
            ]
            if not chat_messages:
                return {'summary': f'与对方的一次聊天（{len(messages)}条消息）', 'keywords': ''}

            # 构建待总结的文本，聊天记录为主体，AI 建议仅作为弱背景
            parts = []
            parts.append("【聊天记录】")
            for msg in chat_messages[-20:]:
                sender = "我" if msg.get('sender_attr') == 'self' else "对方"
                content = (msg.get('content') or '')[:60]
                if content:
                    parts.append(f"  {sender}：{content}")

            if suggestions:
                parts.append("\n【辅助背景（不要作为总结重点）】")
                parts.append("  以下内容仅供理解上下文，不要在总结中直接提及 AI 建议。")
                for s in suggestions[-3:]:
                    summary = s.get('summary', '')
                    speeches = s.get('speeches', [])
                    if isinstance(speeches, str):
                        try:
                            speeches = json.loads(speeches)
                        except:
                            speeches = [speeches]
                    if summary:
                        parts.append(f"  背景摘要: {summary[:50]}")
                    if speeches:
                        parts.append(f"  背景话术: {'; '.join(str(sp)[:30] for sp in speeches[:1])}")

            user_prompt = '\n'.join(parts)

            # 调用 LLM
            base_url = model_config['api_base_url'].rstrip('/')
            api_key = model_config.get('api_key', '')
            model_id = model_config['model_id']

            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 150,
                "temperature": 0.3,
            }

            data = json.dumps(payload).encode('utf-8')
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            url = f"{base_url}/chat/completions"
            _print(f"[SessionThread] 📤 POST {url} (生成总结)")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode('utf-8'))

            content = ''
            choices = body.get('choices', [])
            if choices:
                msg = choices[0].get('message', {})
                content = msg.get('content', '') or ''

            if not content:
                return {'summary': f'与对方的一次聊天（{len(messages)}条消息）', 'keywords': ''}

            # 解析 JSON
            return self._parse_summary_json(content, len(messages))

        except Exception as e:
            _print(f"[SessionThread] ⚠️ LLM 总结失败: {e}")
            return {'summary': f'与对方的一次聊天（{len(messages)}条消息）', 'keywords': ''}

    def _parse_summary_json(self, text: str, msg_count: int) -> dict:
        """解析总结 JSON"""
        try:
            cleaned = text.strip()
            if '```json' in cleaned:
                cleaned = cleaned.split('```json', 1)[1].split('```', 1)[0]
            elif '```' in cleaned:
                cleaned = cleaned.split('```', 1)[1].split('```', 1)[0]

            data = json.loads(cleaned.strip())
            return {
                'summary': data.get('summary', f'聊天指导（{msg_count}条消息）'),
                'keywords': data.get('keywords', ''),
            }
        except (json.JSONDecodeError, KeyError):
            # 如果不是 JSON，直接用原文当总结
            return {'summary': text[:50], 'keywords': ''}

    def _ensure_table(self, conn):
        """确保 session_threads 表存在"""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS session_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                summary TEXT NOT NULL,
                keywords TEXT,
                messages_snapshot TEXT,
                suggestions_snapshot TEXT,
                user_chat_history_snapshot TEXT,
                message_count INTEGER,
                suggestion_count INTEGER,
                created_at INTEGER NOT NULL,
                duration_seconds INTEGER
            )
        ''')
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_session_threads_account_display_created
            ON session_threads(account_wxid, display_name, created_at DESC)
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
            _print(f"[SessionThread] 获取模型配置失败: {e}")
            return None
