"""
联系人画像服务

通过 LLM 总结联系人历史聊天，生成对方画像：
- 性格标签、聊天风格、兴趣话题、关系总结、沟通注意事项
- 支持 token 预算制采样（低/中/高/自定义）
- 模块化收集已有特征数据
- 7 天缓存有效期
"""

import json
import logging
import math
import time
import random
from typing import Optional
from .llm_http import post_json_with_retries
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file
from ..wechat.contact_filters import is_excluded_contact_username

logger = logging.getLogger(__name__)
def _print(msg: str):
    """统一打印"""
    logger.debug(msg)


# 画像档位只定义回看跨度；实际输入和输出 token 由真实消息量、prompt 长度动态决定。
PROFILE_TIME_WINDOWS = {
    'low': 7 * 86400,
    'medium': 30 * 86400,
    'high': 90 * 86400,
    'custom': 90 * 86400,
}

# 时间分桶权重（近期优先）
TIME_BUCKETS = [
    (7 * 86400, 0.50),     # 最近 7 天 → 50% 预算
    (30 * 86400, 0.30),    # 8-30 天 → 30% 预算
    (90 * 86400, 0.20),    # 31-90 天 → 20% 预算
    (None, 0.0),           # 90天以前 → 兜底回收所有被顺延的剩余预算
]

# 缓存有效期（秒）
PROFILE_TTL = 7 * 86400  # 7 天

# 画像生成用 System Prompt
PROFILE_SYSTEM_PROMPT = """你是一个社交关系分析师。根据提供的聊天数据和统计特征，总结"对方"的信息画像。

规则：
1. 仅基于提供的数据进行分析，不要编造细节
2. 性格标签精炼准确，3-5 个
3. 注意区分"我"和"对方"的发言
4. 严格按 JSON 格式输出，不要输出其他内容

输出格式（纯 JSON，无 markdown）：
{
  "personality_tags": ["标签1", "标签2", "标签3"],
  "chat_style": "对方的聊天风格描述（回复速度、消息长度偏好、表情使用等）",
  "interests": ["兴趣1", "兴趣2"],
  "relationship_note": "对你们关系状态的一句话总结",
  "communication_tips": "与此人沟通的注意事项和建议"
}"""


class ContactProfiler:
    """联系人画像服务"""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def _resolve_account_wxid(self, account_wxid: str = "") -> str:
        normalized = str(account_wxid or "").strip()
        if normalized:
            return normalized
        try:
            return get_active_wechat_account_wxid(load_settings_from_file())
        except Exception:
            return ""

    def get_profile(self, display_name: str, account_wxid: str = "") -> Optional[dict]:
        """
        获取缓存的联系人画像

        Returns:
            {
                'profile': {...画像JSON...},
                'created_at': int,
                'expires_at': int,
                'expired': bool,
            } 或 None（无缓存）
        """
        try:
            from ...db.connection import get_db
            conn = get_db()

            # 确保表存在
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cursor = conn.execute(
                'SELECT profile_json, created_at, expires_at '
                'FROM contact_profiles WHERE account_wxid = ? AND display_name = ?',
                (resolved_account_wxid, display_name)
            )
            row = cursor.fetchone()
            if not row:
                return None

            now = int(time.time())
            return {
                'profile': json.loads(row['profile_json']),
                'created_at': row['created_at'],
                'expires_at': row['expires_at'],
                'expired': now > row['expires_at'],
            }
        except Exception as e:
            _print(f"[ContactProfiler] 查询缓存失败: {e}")
            return None

    def estimate_tokens(self, display_name: str, budget_level: str = 'medium', custom_budget: int = 0, account_wxid: str = "") -> dict:
        """
        预估生成画像所需的 token 量

        Returns:
            {
                'conversation_id': int or None,
                'message_count': int,
                'sample_budget': int,
                'estimated_total_tokens': int,
            }
        """
        window_seconds = PROFILE_TIME_WINDOWS.get(budget_level, PROFILE_TIME_WINDOWS['medium'])

        try:
            from ...db.connection import get_db
            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            conv = self._find_conversation(conn, display_name, resolved_account_wxid)
            if not conv:
                return {
                    'conversation_id': None,
                    'message_count': 0,
                    'time_window_days': window_seconds // 86400,
                    'sample_budget': 0,
                    'estimated_total_tokens': 0,
                }

            return {
                'conversation_id': conv['id'],
                'message_count': conv['message_count'],
                'time_window_days': window_seconds // 86400,
                'sample_budget': 0,
                'estimated_total_tokens': 0,
            }
        except Exception as e:
            _print(f"[ContactProfiler] 预估 token 失败: {e}")
            return {
                'conversation_id': None,
                'message_count': 0,
                'time_window_days': window_seconds // 86400,
                'estimated_total_tokens': 0,
            }

    def generate_profile(
        self,
        display_name: str,
        budget_level: str = 'medium',
        custom_budget: int = 0,
        account_wxid: str = "",
    ) -> dict:
        """
        生成联系人画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: token 预算档位 (low/medium/high/custom)
            custom_budget: 自定义 token 预算（budget_level='custom' 时生效）

        Returns:
            {'ok': True, 'profile': {...}} 或 {'ok': False, 'error': '...'}
        """
        window_seconds = PROFILE_TIME_WINDOWS.get(budget_level, PROFILE_TIME_WINDOWS['medium'])

        _print(f"\n{'='*60}")
        _print(f"[ContactProfiler] 开始生成画像: {display_name}")
        _print(f"[ContactProfiler] 回看范围: 最近 {window_seconds // 86400} 天 ({budget_level})；token 按实际内容动态计算")
        _print(f"{'='*60}")

        try:
            from ...db.connection import get_db
            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            # 1. 查找 conversation_id
            _print(f"[ContactProfiler] 步骤1: 查找会话...")
            conv = self._find_conversation(conn, display_name, resolved_account_wxid)
            if not conv:
                _print(f"[ContactProfiler] ⚠️ 未找到精确匹配的会话，尝试模糊匹配...")
                conv = self._find_conversation_fuzzy(conn, display_name, resolved_account_wxid)
            if not conv:
                _print(f"[ContactProfiler] ❌ 未找到联系人「{display_name}」的历史聊天记录")
                return {'ok': False, 'error': f'未找到联系人「{display_name}」的历史聊天记录，请先导入微信数据'}

            conversation_id = conv['id']
            _print(f"[ContactProfiler] 找到会话: id={conversation_id}, 消息数={conv['message_count']}")

            # 2. 收集特征数据
            features = self._collect_features(conn, conversation_id)
            _print(f"[ContactProfiler] 特征数据收集完成: {list(features.keys())}")

            # 3. 采样对话轮次
            sample = self._sample_conversation_turns(conn, conversation_id, window_seconds)
            _print(f"[ContactProfiler] 采样完成: {len(sample)} 条消息, 约 {self._count_tokens(sample)} tokens")

            # 4. 构造 prompt
            user_prompt = self._build_profile_prompt(display_name, conv, features, sample)
            _print(f"[ContactProfiler] Prompt 长度: {len(user_prompt)} 字符")

            # 5. 调用 LLM，传入预算以动态决定输出额度
            profile_data = self._call_llm(user_prompt)

            _print(f"[ContactProfiler] ✅ 画像生成成功!")
            _print(f"[ContactProfiler] 标签: {profile_data.get('personality_tags', [])}")

            # 6. 缓存
            self._save_cache(conn, display_name, conversation_id, profile_data,
                             len(sample), features, resolved_account_wxid)

            return {'ok': True, 'profile': profile_data}

        except Exception as e:
            import traceback
            _print(f"[ContactProfiler] ❌ 生成画像失败: {e}")
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    # ==================== 内部方法 ====================

    def _find_conversation(self, conn, display_name: str, account_wxid: str) -> Optional[dict]:
        """通过 display_name / nickname / remark / contacts反查 查找会话

        查找策略（按优先级）：
        1. 直接匹配 conversations 表的 nickname / remark / display_name
        2. 从 contacts 表通过 nickname / remark 反查 username(wxid)，
           再用 wxid 匹配 conversations.username
        """
        # 策略1: 直接匹配 conversations 表的多个字段
        cursor = conn.execute(
            'SELECT id, display_name, username, nickname, remark, message_count, created_at, updated_at '
            'FROM conversations '
            'WHERE account_wxid = ? AND (display_name = ? OR nickname = ? OR remark = ? OR username = ?) '
            'AND is_deleted = 0 '
            'ORDER BY message_count DESC LIMIT 1',
            (account_wxid, display_name, display_name, display_name, display_name)
        )
        row = cursor.fetchone()
        if row:
            if is_excluded_contact_username(row['username']):
                _print(f"[ContactProfiler] 跳过系统联系人会话: username={row['username']}")
            else:
                _print(f"[ContactProfiler] ✅ 直接匹配成功: id={row['id']}, "
                       f"username={row['username']}, "
                       f"nickname={row['nickname']}, remark={row['remark']}, "
                       f"messages={row['message_count']}")
                return dict(row)

        # 策略2: 通过 contacts 表反查 username(wxid)
        _print(f"[ContactProfiler] 直接匹配失败，尝试通过 contacts 表反查...")
        contact_cursor = conn.execute(
            'SELECT username, nickname, remark FROM contacts '
            'WHERE account_wxid = ? AND (nickname = ? OR remark = ?) '
            'LIMIT 5',
            (account_wxid, display_name, display_name)
        )
        contacts = [
            contact for contact in contact_cursor.fetchall()
            if not is_excluded_contact_username(contact['username'])
        ]
        if contacts:
            _print(f"[ContactProfiler] 找到 {len(contacts)} 个匹配的联系人: "
                   f"{[(c['username'], c['nickname'], c['remark']) for c in contacts]}")
            # 用找到的 username(wxid) 去匹配 conversations 表
            for contact in contacts:
                wxid = contact['username']
                conv_cursor = conn.execute(
                    'SELECT id, display_name, username, nickname, remark, '
                    'message_count, created_at, updated_at '
                    'FROM conversations '
                    'WHERE account_wxid = ? AND (username = ? OR display_name = ?) AND is_deleted = 0 '
                    'ORDER BY message_count DESC LIMIT 1',
                    (account_wxid, wxid, wxid)
                )
                conv_row = conv_cursor.fetchone()
                if conv_row:
                    if is_excluded_contact_username(conv_row['username']):
                        _print(f"[ContactProfiler] 跳过系统联系人反查结果: username={conv_row['username']}")
                        continue
                    _print(f"[ContactProfiler] ✅ contacts 反查匹配成功: "
                           f"contact={contact['nickname']}({wxid}) → "
                           f"conv_id={conv_row['id']}, messages={conv_row['message_count']}")
                    return dict(conv_row)

        _print(f"[ContactProfiler] ⚠️ 精确匹配全部失败: {display_name}")
        return None

    def _find_conversation_fuzzy(self, conn, display_name: str, account_wxid: str) -> Optional[dict]:
        """模糊匹配会话（精确匹配失败时的回退方案）

        查找策略：
        1. 模糊匹配 conversations 表的 nickname / remark / display_name
        2. 模糊匹配 contacts 表反查 username，再匹配 conversations
        """
        search_key = display_name[:4] if len(display_name) >= 4 else display_name

        # 策略1: 模糊匹配 conversations 表的多个字段
        cursor = conn.execute(
            'SELECT id, display_name, username, nickname, remark, message_count, created_at, updated_at '
            'FROM conversations '
            'WHERE account_wxid = ? AND (nickname LIKE ? OR remark LIKE ? OR display_name LIKE ?) '
            'AND is_deleted = 0 '
            'ORDER BY message_count DESC LIMIT 5',
            (account_wxid, f'%{search_key}%', f'%{search_key}%', f'%{search_key}%')
        )
        rows = cursor.fetchall()
        if rows:
            valid_rows = [
                row for row in rows
                if not is_excluded_contact_username(row['username'])
            ]
            if valid_rows:
                _print(f"[ContactProfiler] 模糊匹配 conversations 结果: "
                       f"{[(r['nickname'] or r['display_name'], r['message_count']) for r in valid_rows]}")
                return dict(valid_rows[0])

        # 策略2: 模糊匹配 contacts 表反查
        contact_cursor = conn.execute(
            'SELECT username, nickname, remark FROM contacts '
            'WHERE account_wxid = ? AND (nickname LIKE ? OR remark LIKE ?) '
            'LIMIT 5',
            (account_wxid, f'%{search_key}%', f'%{search_key}%')
        )
        contacts = [
            contact for contact in contact_cursor.fetchall()
            if not is_excluded_contact_username(contact['username'])
        ]
        if contacts:
            _print(f"[ContactProfiler] 模糊匹配 contacts 结果: "
                   f"{[(c['nickname'], c['remark']) for c in contacts]}")
            for contact in contacts:
                wxid = contact['username']
                conv_cursor = conn.execute(
                    'SELECT id, display_name, username, nickname, remark, '
                    'message_count, created_at, updated_at '
                    'FROM conversations '
                    'WHERE account_wxid = ? AND (username = ? OR display_name = ?) AND is_deleted = 0 '
                    'ORDER BY message_count DESC LIMIT 1',
                    (account_wxid, wxid, wxid)
                )
                conv_row = conv_cursor.fetchone()
                if conv_row:
                    if is_excluded_contact_username(conv_row['username']):
                        _print(f"[ContactProfiler] 跳过系统联系人模糊反查结果: username={conv_row['username']}")
                        continue
                    _print(f"[ContactProfiler] ✅ 模糊反查匹配成功: "
                           f"contact={contact['nickname']}({wxid}) → "
                           f"conv_id={conv_row['id']}, messages={conv_row['message_count']}")
                    return dict(conv_row)

        # 完全找不到，打印调试信息
        cursor2 = conn.execute(
            'SELECT username, display_name, nickname, remark, message_count '
            'FROM conversations '
            'WHERE account_wxid = ? AND is_deleted = 0 ORDER BY message_count DESC LIMIT 10',
            (account_wxid,)
        )
        all_convs = [(dict(r)['nickname'] or dict(r)['display_name'],
                       dict(r)['username'], dict(r)['message_count'])
                      for r in cursor2.fetchall()]
        _print(f"[ContactProfiler] 数据库中的会话列表 (top10): {all_convs}")
        return None

    def _collect_features(self, conn, conversation_id: int) -> dict:
        """
        模块化收集已有特征数据，逐项 try/except
        """
        features = {}

        # 主动性统计
        try:
            row = conn.execute(
                'SELECT total_sessions, user_initiated_sessions, '
                'other_initiated_sessions, initiative_rate '
                'FROM initiative_stats WHERE conversation_id = ?',
                (conversation_id,)
            ).fetchone()
            if row:
                rate = row['initiative_rate']
                features['initiative'] = {
                    'total_sessions': row['total_sessions'],
                    'other_initiated': row['other_initiated_sessions'],
                    'user_initiated': row['user_initiated_sessions'],
                    'initiative_rate': rate,
                    'desc': f"对方主动发起{rate:.0%}的会话" if rate else None,
                }
        except Exception as e:
            _print(f"[ContactProfiler] 跳过主动性统计: {e}")

        # 响应时间
        try:
            row = conn.execute(
                'SELECT COUNT(*) as cnt, AVG(response_time_seconds) as avg_rt, '
                'MIN(response_time_seconds) as min_rt, MAX(response_time_seconds) as max_rt '
                'FROM response_times WHERE conversation_id = ? AND is_abnormal = 0',
                (conversation_id,)
            ).fetchone()
            if row and row['cnt'] > 0:
                features['response_time'] = {
                    'count': row['cnt'],
                    'avg_seconds': round(row['avg_rt'], 1),
                    'min_seconds': round(row['min_rt'], 1),
                    'max_seconds': round(row['max_rt'], 1),
                }
        except Exception as e:
            _print(f"[ContactProfiler] 跳过响应时间: {e}")

        # 字数统计
        try:
            row = conn.execute(
                'SELECT user_char_count, other_char_count, char_ratio '
                'FROM word_counts WHERE conversation_id = ? AND session_id IS NULL',
                (conversation_id,)
            ).fetchone()
            if row:
                features['word_counts'] = {
                    'user_chars': row['user_char_count'],
                    'other_chars': row['other_char_count'],
                    'ratio': round(row['char_ratio'], 2),
                }
        except Exception as e:
            _print(f"[ContactProfiler] 跳过字数统计: {e}")

        # 好感度评分
        try:
            row = conn.execute(
                'SELECT overall_score, emotional_resonance_score, '
                'chat_positivity_score, attitude_tendency_score, '
                'preference_compatibility_score '
                'FROM affinity_scores WHERE conversation_id = ? '
                'ORDER BY created_at DESC LIMIT 1',
                (conversation_id,)
            ).fetchone()
            if row:
                features['affinity'] = {
                    'overall': round(row['overall_score'], 1),
                    'emotional_resonance': round(row['emotional_resonance_score'], 1),
                    'chat_positivity': round(row['chat_positivity_score'], 1),
                    'attitude_tendency': round(row['attitude_tendency_score'], 1),
                    'preference_compatibility': round(row['preference_compatibility_score'], 1),
                }
        except Exception as e:
            _print(f"[ContactProfiler] 跳过好感度评分: {e}")

        return features

    def _sample_conversation_turns(
        self, conn, conversation_id: int, time_window_seconds: int
    ) -> list[dict]:
        """
        按画像档位选取最近时间窗内的完整对话。

        档位只影响时间范围，不再预先写死输入 token 消耗；请求 token
        由实际命中的消息和最终 prompt 动态计算。
        """
        now = int(time.time())
        cursor = conn.execute(
            'SELECT content, is_sender, timestamp '
            'FROM messages '
            'WHERE conversation_id = ? AND message_type = 1 '
            'AND timestamp > ? AND timestamp <= ? '
            'AND content IS NOT NULL AND content != "" '
            'ORDER BY timestamp ASC',
            (conversation_id, now - max(1, int(time_window_seconds)), now),
        )
        messages = [dict(row) for row in cursor.fetchall()]
        if messages:
            return messages

        # 时间窗内没有消息（如不常联系的人）时回退取最近的历史消息：
        # 没有任何真实聊天样本，模型只能看到统计特征，会生成空口头禅/
        # 空句式的退化画像。200 条约等于旧低档预算的采样规模。
        cursor = conn.execute(
            'SELECT content, is_sender, timestamp '
            'FROM messages '
            'WHERE conversation_id = ? AND message_type = 1 '
            'AND content IS NOT NULL AND content != "" '
            'ORDER BY timestamp DESC '
            'LIMIT 200',
            (conversation_id,),
        )
        fallback = [dict(row) for row in cursor.fetchall()]
        fallback.reverse()
        if fallback:
            _print(f"[ContactProfiler] ⚠️ 时间窗内没有消息，回退使用最近 {len(fallback)} 条历史消息")
        return fallback

    def _build_turns(self, messages: list[dict]) -> list[list[dict]]:
        """将消息列表切分为对话轮次（连续消息按发送者分组后配对）"""
        if not messages:
            return []

        turns = []
        current_turn = [messages[0]]

        for i in range(1, len(messages)):
            prev = messages[i - 1]
            curr = messages[i]

            # 如果发送者切换了，说明轮次可能完成
            if prev['is_sender'] != curr['is_sender']:
                current_turn.append(curr)
                # 一来一回完成一个轮次
                if len(current_turn) >= 2:
                    turns.append(current_turn)
                    current_turn = []
            else:
                # 同一发送者连续消息，归入当前轮次
                current_turn.append(curr)

            # 单轮最多 6 条消息（防止超长连续消息）
            if len(current_turn) >= 6:
                turns.append(current_turn)
                current_turn = []

        if current_turn:
            turns.append(current_turn)

        return turns

    def _estimate_msg_tokens(self, content: str) -> int:
        """粗估单条消息的 token 数（中文 ~1.5 token/字）"""
        if not content:
            return 0
        return max(1, int(len(content) * 1.5))

    def _count_tokens(self, messages: list[dict]) -> int:
        """统计消息列表的总 token 数"""
        return sum(self._estimate_msg_tokens(m.get('content', '')) for m in messages)

    def _build_profile_prompt(
        self,
        display_name: str,
        conv: dict,
        features: dict,
        sample: list[dict]
    ) -> str:
        """组装画像生成的 user prompt"""
        parts = []

        # 基础信息
        from datetime import datetime
        first_date = datetime.fromtimestamp(conv.get('created_at', 0)).strftime('%Y-%m-%d')
        last_date = datetime.fromtimestamp(conv.get('updated_at', 0)).strftime('%Y-%m-%d')

        parts.append(f"【基础信息】")
        parts.append(f"- 联系人名称: {display_name}")
        parts.append(f"- 消息总数: {conv.get('message_count', 0)}")
        parts.append(f"- 时间跨度: {first_date} ~ {last_date}")

        # 互动特征
        feat_lines = []

        initiative = features.get('initiative')
        if initiative:
            feat_lines.append(
                f"- 会话总数: {initiative['total_sessions']}，"
                f"对方主动发起: {initiative['initiative_rate']:.0%}"
            )

        rt = features.get('response_time')
        if rt:
            avg_min = rt['avg_seconds'] / 60
            feat_lines.append(f"- 平均响应时间: {avg_min:.1f}分钟（样本: {rt['count']}对）")

        wc = features.get('word_counts')
        if wc:
            feat_lines.append(
                f"- 字数: 我={wc['user_chars']}字, 对方={wc['other_chars']}字, "
                f"比值(对方/我)={wc['ratio']}"
            )

        if feat_lines:
            parts.append("")
            parts.append("【互动特征】")
            parts.extend(feat_lines)

        # 好感度
        aff = features.get('affinity')
        if aff:
            parts.append("")
            parts.append("【好感度评分】")
            parts.append(f"- 总体: {aff['overall']}/100")
            parts.append(f"- 情感共振: {aff['emotional_resonance']}, "
                         f"聊天积极度: {aff['chat_positivity']}, "
                         f"态度倾向: {aff['attitude_tendency']}")

        # 对话样本
        if sample:
            parts.append("")
            parts.append(f"【聊天记录样本（{len(sample)}条）】")
            for msg in sample:
                sender = "我" if msg.get('is_sender') else "对方"
                content = str(msg.get('content', ''))[:150]
                parts.append(f"  {sender}：{content}")

        parts.append("")
        parts.append("请根据以上数据生成联系人画像（纯 JSON 输出）：")

        return "\n".join(parts)

    def _call_llm(self, user_prompt: str, _legacy_sample_budget: int | None = None) -> dict:
        """调用 LLM 生成画像"""

        # 获取激活的模型配置
        try:
            from ...db.connection import get_db
            conn = get_db()

            conn.execute('''
                CREATE TABLE IF NOT EXISTS llm_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL, provider TEXT NOT NULL,
                    model_id TEXT NOT NULL, api_base_url TEXT NOT NULL,
                    api_key TEXT, is_active INTEGER DEFAULT 0,
                    max_tokens INTEGER DEFAULT 512, temperature REAL DEFAULT 0.7,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                )
            ''')

            cursor = conn.execute('SELECT * FROM llm_models WHERE is_active = 1 LIMIT 1')
            model_config = cursor.fetchone()
        except Exception as e:
            _print(f"[ContactProfiler] 获取模型配置失败: {e}")
            raise RuntimeError(f'获取模型配置失败: {e}') from e

        if not model_config:
            raise ValueError('未配置激活的 LLM 模型')
        model_config = dict(model_config)

        # 构造请求
        base_url = model_config['api_base_url'].rstrip('/')
        url = f"{base_url}/chat/completions"

        # 输出额度随真实 prompt 变动；模型配置值是可调的下限。
        # 混合推理模型（deepseek-flash/reasoner 等）把 reasoning_content 也
        # 计入 completion token，小预算会在最终 JSON 输出前耗尽，画像解析
        # 必然失败，因此推理模型保留下限 8192、普通模型保留下限 4096。
        prompt_tokens = self._estimate_msg_tokens(PROFILE_SYSTEM_PROMPT + user_prompt)
        configured_floor = max(1, int(model_config.get('max_tokens') or 0))
        dynamic_max_tokens = max(configured_floor, 384 + math.ceil(prompt_tokens * 0.22))
        model_id = str(model_config.get('model_id') or '').lower()
        hybrid_reasoning_model = 'flash' in model_id or 'reason' in model_id
        dynamic_max_tokens = max(dynamic_max_tokens, 8192 if hybrid_reasoning_model else 4096)

        payload = {
            'model': model_config['model_id'],
            'messages': [
                {'role': 'system', 'content': PROFILE_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt},
            ],
            'max_tokens': dynamic_max_tokens,
            'temperature': 0.5,  # 画像生成用较低温度
            'response_format': {'type': 'json_object'},
        }

        headers = {}
        api_key = model_config.get('api_key', '')
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        body = post_json_with_retries(
            url=url,
            payload=payload,
            headers=headers,
            timeout=self.timeout,
            log=_print,
            log_prefix='[ContactProfiler]',
        )

        message_obj = body.get('choices', [{}])[0].get('message', {})
        content = message_obj.get('content', '') or ''
        reasoning = message_obj.get('reasoning_content', '')

        # 部分模型（如 deepseek-reasoner）可能将内容放在 reasoning_content 中，或者由于 max_tokens 限制没能输出 content
        if not content and reasoning:
            reasoning_candidate = self._extract_json_candidate(reasoning)
            if reasoning_candidate.lstrip().startswith("{") and reasoning_candidate.rstrip().endswith("}"):
                content = reasoning_candidate
                _print("[ContactProfiler] ⚠️ content 为空，使用 reasoning_content 中的 JSON 回退")
            else:
                _print("[ContactProfiler] ⚠️ content 为空且 reasoning_content 没有完整 JSON")

        usage = body.get('usage', {})
        _print(
            f"[ContactProfiler] 📥 tokens: prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')}, "
            f"total={usage.get('total_tokens', '?')}"
        )

        parsed = self._parse_profile_json(content)
        if not parsed:
            raise ValueError('LLM 返回内容解析失败：未得到合法画像 JSON')

        return parsed

    def _parse_profile_json(self, text: str) -> Optional[dict]:
        """解析 LLM 返回的画像 JSON"""
        try:
            cleaned = text.strip()
            if '```json' in cleaned:
                cleaned = cleaned.split('```json', 1)[1].split('```', 1)[0]
            elif '```' in cleaned:
                cleaned = cleaned.split('```', 1)[1].split('```', 1)[0]

            data = json.loads(cleaned.strip())

            # 校验必要字段
            required = ['personality_tags', 'chat_style', 'relationship_note']
            for field in required:
                if field not in data:
                    _print(f"[ContactProfiler] ⚠️ 缺少字段: {field}")

            return data
        except (json.JSONDecodeError, KeyError) as e:
            _print(f"[ContactProfiler] JSON 解析失败: {e}, 原文: {text[:200]}")
            return None

    def _extract_json_candidate(self, text: str) -> str:
        """Extract a JSON object from a reasoning-enabled model response."""
        cleaned = (text or "").strip()
        if "```json" in cleaned:
            return cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        if "```" in cleaned:
            return cleaned.split("```", 1)[1].split("```", 1)[0].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        return cleaned[start:end + 1].strip() if start >= 0 and end > start else cleaned

    def _save_cache(
        self, conn, display_name: str, conversation_id: int,
        profile: dict, sample_count: int, features: dict, account_wxid: str
    ):
        """保存画像到缓存表"""
        try:
            self._ensure_table(conn)

            now = int(time.time())
            conn.execute(
                'INSERT OR REPLACE INTO contact_profiles '
                '(account_wxid, display_name, conversation_id, profile_json, features_snapshot, '
                'message_sample_count, token_usage, created_at, expires_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    account_wxid,
                    display_name,
                    conversation_id,
                    json.dumps(profile, ensure_ascii=False),
                    json.dumps(features, ensure_ascii=False),
                    sample_count,
                    0,  # 实际 token 消耗可从 LLM 响应中提取
                    now,
                    now + PROFILE_TTL,
                )
            )
            conn.commit()
            _print(f"[ContactProfiler] 画像已缓存，有效至 {time.strftime('%Y-%m-%d', time.localtime(now + PROFILE_TTL))}")
        except Exception as e:
            _print(f"[ContactProfiler] ⚠️ 缓存保存失败: {e}")

    def _ensure_table(self, conn):
        """确保缓存表存在"""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contact_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                display_name TEXT NOT NULL,
                conversation_id INTEGER,
                profile_json TEXT NOT NULL,
                features_snapshot TEXT,
                message_sample_count INTEGER,
                token_usage INTEGER,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                UNIQUE(account_wxid, display_name)
            )
        ''')
