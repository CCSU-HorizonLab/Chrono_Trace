"""
用户本体画像分析服务 (Self Profiler)

通过 LLM 总结长对话中"我"（is_sender=1）的发言，生成用户本体克隆画像：
- 打字风格体态、常用口头禅/语气词、双方共有事实记忆、沟通角色
- 用于在生成回复时反向注入，使得生成的建议具备真实的"用户味"（千人千面）
- 7 天缓存有效期
"""

import json
import logging
import time
import random
from typing import Optional
from .llm_http import post_json_with_retries

logger = logging.getLogger(__name__)
def _print(msg: str):
    """统一打印"""
    logger.debug(msg)


# Token 预算档位
TOKEN_BUDGETS = {
    'low': 2000,
    'medium': 4000,
    'high': 8000,
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
PROFILE_SYSTEM_PROMPT = """你是一个语言风格与行为克隆分析专家。根据提供的聊天记录（其中"我"是 `is_sender=1` 的发送者，"对方"是 `is_sender=0` 的发送者），提取"我"在这段特定关系中的专属语言画风与共同记忆。

关注点：
1. **语言风格识别**：我（本用户）喜欢发短句还是连发长段落？标点符号使用习惯（是否完全不加标点？或者喜欢连用波浪号~~~、感叹号!!!）？有什么特定的口头禅或语气词（哈、呢、哦、卧槽、啊这）？
   - 额外提取 3-5 个最具代表性的句式模板，例如“哈哈[内容]”“就[事情]而已”“[动词]一下就好了”。
   - 说明我更偏向直问、反问还是陈述，是否习惯多条短消息连续发送，以及通常一条消息大约多少字。
2. **共有记忆与事实（身份方向性极其重要！）**：在这段聊天中透露的事实和共有经历。
   - ❗ **必须明确标注“谁做了什么”，严禁混淆主语**。例如应写“我给对方买了裙子”，绝不能写成“对方给我买了裙子”。
   - ❗ **必须标注大致时间段**（如“最近一周”“约一个月前”“很久以前”）。记忆的新鲜度很重要。
   - 只记录**聊天中明确提到过的事实**，绝对不能编造。
3. **态度与防备心**：在这段关系中，我是什么态度？是热情谄媚、还是极度冷淡敷衍、或是互怒打趣的口吻？

规则：
1. 分析对象**仅限我（本用户，is_sender=1）**的聊天记录特征。
2. 绝对不能编造我们没有讨论过的细节。
3. shared_memories 中每条记忆必须以"我"或"对方"开头，明确标注动作主体和时间。
4. 严格按 JSON 格式输出，不要输出其他内容，必须确保输出。

输出格式（纯 JSON）：
{
  "typing_style": "我的详细打字排版与语言风格特征（例如：极简直白，从不打标点，喜欢用'哈哈'垫底）",
  "frequent_catchphrases": ["常用词或语气词1", "常用词或语气词2"],
  "sentence_patterns": ["句式模板1", "句式模板2", "句式模板3"],
  "shared_memories": ["我给对方买了裙子(最近一周)", "对方上周末来找我玩(约两周前)", "我养了只猫(很久以前提过)"],
  "attitude_and_role": "在这段特定关系中我扮演的角色与沟通态度（如：冷淡/敷衍/热情讨好/爹味说教等）",
  "do_and_donts": "如果让你来完全模仿我说话，必须做的事和绝对不能做的事，并明确写出建议话术应控制在多少字范围"
}"""


class SelfProfiler:
    """联系人画像服务"""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def get_profile(self, display_name: str) -> Optional[dict]:
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

            cursor = conn.execute(
                'SELECT profile_json, created_at, expires_at '
                'FROM self_profiles WHERE display_name = ?',
                (display_name,)
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
            _print(f"[SelfProfiler] 查询缓存失败: {e}")
            return None

    def estimate_tokens(self, display_name: str, budget_level: str = 'medium', custom_budget: int = 0) -> dict:
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
        budget = custom_budget if budget_level == 'custom' and custom_budget > 0 else TOKEN_BUDGETS.get(budget_level, 4000)

        try:
            from ...db.connection import get_db
            conn = get_db()

            conv = self._find_conversation(conn, display_name)
            if not conv:
                return {
                    'conversation_id': None,
                    'message_count': 0,
                    'sample_budget': budget,
                    'estimated_total_tokens': 0,
                }

            return {
                'conversation_id': conv['id'],
                'message_count': conv['message_count'],
                'sample_budget': budget,
                # 粗估：采样 tokens + system prompt (~300) + 特征数据 (~500) + 输出 (~300)
                'estimated_total_tokens': budget + 1100,
            }
        except Exception as e:
            _print(f"[SelfProfiler] 预估 token 失败: {e}")
            return {
                'conversation_id': None,
                'message_count': 0,
                'sample_budget': budget,
                'estimated_total_tokens': budget + 1100,
            }

    def generate_profile(
        self,
        display_name: str,
        budget_level: str = 'medium',
        custom_budget: int = 0
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
        budget = custom_budget if budget_level == 'custom' and custom_budget > 0 else TOKEN_BUDGETS.get(budget_level, 4000)

        _print(f"\n{'='*60}")
        _print(f"[SelfProfiler] 开始生成画像: {display_name}")
        _print(f"[SelfProfiler] Token 预算: {budget} ({budget_level})")
        _print(f"{'='*60}")

        try:
            from ...db.connection import get_db
            conn = get_db()

            # 1. 查找 conversation_id
            _print(f"[SelfProfiler] 步骤1: 查找会话...")
            conv = self._find_conversation(conn, display_name)
            if not conv:
                _print(f"[SelfProfiler] ⚠️ 未找到精确匹配的会话，尝试模糊匹配...")
                conv = self._find_conversation_fuzzy(conn, display_name)
            if not conv:
                _print(f"[SelfProfiler] ❌ 未找到联系人「{display_name}」的历史聊天记录")
                return {'ok': False, 'error': f'未找到联系人「{display_name}」的历史聊天记录，请先导入微信数据'}

            conversation_id = conv['id']
            _print(f"[SelfProfiler] 找到会话: id={conversation_id}, 消息数={conv['message_count']}")

            # 2. 收集特征数据
            features = self._collect_features(conn, conversation_id)
            _print(f"[SelfProfiler] 特征数据收集完成: {list(features.keys())}")

            # 3. 采样对话轮次
            sample = self._sample_conversation_turns(conn, conversation_id, budget)
            _print(f"[SelfProfiler] 采样完成: {len(sample)} 条消息, 约 {self._count_tokens(sample)} tokens")

            # 4. 构造 prompt
            user_prompt = self._build_profile_prompt(display_name, conv, features, sample)
            _print(f"[SelfProfiler] Prompt 长度: {len(user_prompt)} 字符")

            # 5. 调用 LLM，传入预算以动态决定输出额度
            profile_data = self._call_llm(user_prompt, budget)

            _print(f"[SelfProfiler] ✅ 画像生成成功!")
            _print(f"[SelfProfiler] 标签: {profile_data.get('personality_tags', [])}")

            # 6. 缓存
            self._save_cache(conn, display_name, conversation_id, profile_data,
                             len(sample), features)

            return {'ok': True, 'profile': profile_data}

        except Exception as e:
            import traceback
            _print(f"[SelfProfiler] ❌ 生成画像失败: {e}")
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    # ==================== 内部方法 ====================

    def _find_conversation(self, conn, display_name: str) -> Optional[dict]:
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
            'WHERE (display_name = ? OR nickname = ? OR remark = ? OR username = ?) '
            'AND is_deleted = 0 '
            'ORDER BY message_count DESC LIMIT 1',
            (display_name, display_name, display_name, display_name)
        )
        row = cursor.fetchone()
        if row:
            _print(f"[SelfProfiler] ✅ 直接匹配成功: id={row['id']}, "
                   f"username={row['username']}, "
                   f"nickname={row['nickname']}, remark={row['remark']}, "
                   f"messages={row['message_count']}")
            return dict(row)

        # 策略2: 通过 contacts 表反查 username(wxid)
        _print(f"[SelfProfiler] 直接匹配失败，尝试通过 contacts 表反查...")
        contact_cursor = conn.execute(
            'SELECT username, nickname, remark FROM contacts '
            'WHERE nickname = ? OR remark = ? '
            'LIMIT 5',
            (display_name, display_name)
        )
        contacts = contact_cursor.fetchall()
        if contacts:
            _print(f"[SelfProfiler] 找到 {len(contacts)} 个匹配的联系人: "
                   f"{[(c['username'], c['nickname'], c['remark']) for c in contacts]}")
            # 用找到的 username(wxid) 去匹配 conversations 表
            for contact in contacts:
                wxid = contact['username']
                conv_cursor = conn.execute(
                    'SELECT id, display_name, username, nickname, remark, '
                    'message_count, created_at, updated_at '
                    'FROM conversations '
                    'WHERE (username = ? OR display_name = ?) AND is_deleted = 0 '
                    'ORDER BY message_count DESC LIMIT 1',
                    (wxid, wxid)
                )
                conv_row = conv_cursor.fetchone()
                if conv_row:
                    _print(f"[SelfProfiler] ✅ contacts 反查匹配成功: "
                           f"contact={contact['nickname']}({wxid}) → "
                           f"conv_id={conv_row['id']}, messages={conv_row['message_count']}")
                    return dict(conv_row)

        _print(f"[SelfProfiler] ⚠️ 精确匹配全部失败: {display_name}")
        return None

    def _find_conversation_fuzzy(self, conn, display_name: str) -> Optional[dict]:
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
            'WHERE (nickname LIKE ? OR remark LIKE ? OR display_name LIKE ?) '
            'AND is_deleted = 0 '
            'ORDER BY message_count DESC LIMIT 5',
            (f'%{search_key}%', f'%{search_key}%', f'%{search_key}%')
        )
        rows = cursor.fetchall()
        if rows:
            _print(f"[SelfProfiler] 模糊匹配 conversations 结果: "
                   f"{[(r['nickname'] or r['display_name'], r['message_count']) for r in rows]}")
            return dict(rows[0])

        # 策略2: 模糊匹配 contacts 表反查
        contact_cursor = conn.execute(
            'SELECT username, nickname, remark FROM contacts '
            'WHERE nickname LIKE ? OR remark LIKE ? '
            'LIMIT 5',
            (f'%{search_key}%', f'%{search_key}%')
        )
        contacts = contact_cursor.fetchall()
        if contacts:
            _print(f"[SelfProfiler] 模糊匹配 contacts 结果: "
                   f"{[(c['nickname'], c['remark']) for c in contacts]}")
            for contact in contacts:
                wxid = contact['username']
                conv_cursor = conn.execute(
                    'SELECT id, display_name, username, nickname, remark, '
                    'message_count, created_at, updated_at '
                    'FROM conversations '
                    'WHERE (username = ? OR display_name = ?) AND is_deleted = 0 '
                    'ORDER BY message_count DESC LIMIT 1',
                    (wxid, wxid)
                )
                conv_row = conv_cursor.fetchone()
                if conv_row:
                    _print(f"[SelfProfiler] ✅ 模糊反查匹配成功: "
                           f"contact={contact['nickname']}({wxid}) → "
                           f"conv_id={conv_row['id']}, messages={conv_row['message_count']}")
                    return dict(conv_row)

        # 完全找不到，打印调试信息
        cursor2 = conn.execute(
            'SELECT username, display_name, nickname, remark, message_count '
            'FROM conversations '
            'WHERE is_deleted = 0 ORDER BY message_count DESC LIMIT 10'
        )
        all_convs = [(dict(r)['nickname'] or dict(r)['display_name'],
                       dict(r)['username'], dict(r)['message_count'])
                      for r in cursor2.fetchall()]
        _print(f"[SelfProfiler] 数据库中的会话列表 (top10): {all_convs}")
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
            _print(f"[SelfProfiler] 跳过主动性统计: {e}")

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
            _print(f"[SelfProfiler] 跳过响应时间: {e}")

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
            _print(f"[SelfProfiler] 跳过字数统计: {e}")

        # 用户消息长度风格
        try:
            row = conn.execute(
                'SELECT COUNT(*) as cnt, AVG(LENGTH(content)) as avg_len '
                'FROM messages '
                'WHERE conversation_id = ? AND is_sender = 1 '
                'AND message_type = 1 AND content IS NOT NULL AND content != ""',
                (conversation_id,)
            ).fetchone()
            if row and row['cnt'] > 0:
                features['user_msg_style'] = {
                    'msg_count': row['cnt'],
                    'avg_chars_per_msg': round(row['avg_len'] or 0, 1),
                }
        except Exception as e:
            _print(f"[SelfProfiler] 跳过用户消息长度统计: {e}")

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
            _print(f"[SelfProfiler] 跳过好感度评分: {e}")

        return features

    def _sample_conversation_turns(
        self, conn, conversation_id: int, token_budget: int
    ) -> list[dict]:
        """
        token 预算制对话轮次采样（含动态顺延剩余预算）
        
        按时间分桶（7天/30天/90天/更早），将上一桶未消耗尽的预算顺延到下一桶，
        桶内随机选取完整对话轮次。
        """
        now = int(time.time())
        all_samples = []
        carry_over_budget = 0
        prev_bucket_end = now

        for max_age_seconds, weight in TIME_BUCKETS:
            # 基础预算再加上一个桶顺延下来的没用完的预算
            bucket_budget = int(token_budget * weight) + carry_over_budget
            
            if max_age_seconds is not None:
                bucket_start = now - max_age_seconds
            else:
                bucket_start = 0

            # 查询该时间桶内所有文本消息
            cursor = conn.execute(
                'SELECT content, is_sender, timestamp '
                'FROM messages '
                'WHERE conversation_id = ? AND message_type = 1 '
                'AND timestamp > ? AND timestamp <= ? '
                'AND content IS NOT NULL AND content != "" '
                'ORDER BY timestamp ASC',
                (conversation_id, bucket_start, prev_bucket_end)
            )
            messages = [dict(r) for r in cursor.fetchall()]

            # 更新结束时间给下一次迭代使用
            prev_bucket_end = bucket_start

            if not messages:
                # 整个桶完全没有消息，预算全额顺延
                carry_over_budget = bucket_budget
                continue

            # 构建对话轮次（连续的一来一回）
            turns = self._build_turns(messages)

            # 随机打乱轮次顺序后按 budget 选取
            random.shuffle(turns)

            bucket_tokens = 0
            for turn in turns:
                turn_tokens = sum(self._estimate_msg_tokens(m['content']) for m in turn)
                if bucket_tokens + turn_tokens > bucket_budget:
                    break
                all_samples.extend(turn)
                bucket_tokens += turn_tokens
            
            # 将没用完的预算顺延给更早的时间桶
            carry_over_budget = bucket_budget - bucket_tokens

        # 按时间排序最终采样
        all_samples.sort(key=lambda m: m['timestamp'])
        return all_samples

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

        user_msg_style = features.get('user_msg_style')
        if user_msg_style:
            feat_lines.append(
                f"- 我方文本消息: {user_msg_style['msg_count']}条, "
                f"平均每条约 {user_msg_style['avg_chars_per_msg']} 字"
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

    def _call_llm(self, user_prompt: str, sample_budget: int) -> dict:
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
            _print(f"[SelfProfiler] 获取模型配置失败: {e}")
            raise RuntimeError(f'获取模型配置失败: {e}') from e

        if not model_config:
            raise ValueError('未配置激活的 LLM 模型')
        model_config = dict(model_config)

        # 构造请求
        base_url = model_config['api_base_url'].rstrip('/')
        url = f"{base_url}/chat/completions"

        # 根据输入的采样预算动态决定输出上限 (至少 4096，若预算极高则成比例放大，比如预算是 8000 时，输出上限放到 8000 以给足 reasoning 空间)
        dynamic_max_tokens = max(4096, sample_budget)

        payload = {
            'model': model_config['model_id'],
            'messages': [
                {'role': 'system', 'content': PROFILE_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt},
            ],
            # 画像生成和可能的推理过程需要较多 token，使用动态计算的上限
            'max_tokens': max(model_config.get('max_tokens', 4096), dynamic_max_tokens),
            'temperature': 0.5,  # 画像生成用较低温度
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
            log_prefix='[SelfProfiler]',
        )

        message_obj = body.get('choices', [{}])[0].get('message', {})
        content = message_obj.get('content', '')
        reasoning = message_obj.get('reasoning_content', '')

        # 部分模型（如 deepseek-reasoner）可能将内容放在 reasoning_content 中，或者由于 max_tokens 限制没能输出 content
        if not content and reasoning:
            content = reasoning
            _print("[SelfProfiler] ⚠️ 最终 content 为空，尝试回退使用 reasoning_content")

        usage = body.get('usage', {})
        _print(
            f"[SelfProfiler] 📥 tokens: prompt={usage.get('prompt_tokens', '?')}, "
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
            required = ['typing_style', 'attitude_and_role', 'do_and_donts']
            for field in required:
                if field not in data:
                    _print(f"[SelfProfiler] ⚠️ 缺少字段: {field}")

            if 'sentence_patterns' not in data or not isinstance(data.get('sentence_patterns'), list):
                data['sentence_patterns'] = []

            return data
        except (json.JSONDecodeError, KeyError) as e:
            _print(f"[SelfProfiler] JSON 解析失败: {e}, 原文: {text[:200]}")
            return None

    def _save_cache(
        self, conn, display_name: str, conversation_id: int,
        profile: dict, sample_count: int, features: dict
    ):
        """保存画像到缓存表"""
        try:
            self._ensure_table(conn)

            now = int(time.time())
            conn.execute(
                'INSERT OR REPLACE INTO self_profiles '
                '(display_name, conversation_id, profile_json, features_snapshot, '
                'message_sample_count, token_usage, created_at, expires_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
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
            _print(f"[SelfProfiler] 画像已缓存，有效至 {time.strftime('%Y-%m-%d', time.localtime(now + PROFILE_TTL))}")
        except Exception as e:
            _print(f"[SelfProfiler] ⚠️ 缓存保存失败: {e}")

    def _ensure_table(self, conn):
        """确保缓存表存在"""
        conn.execute('''
            CREATE TABLE IF NOT EXISTS self_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL UNIQUE,
                conversation_id INTEGER,
                profile_json TEXT NOT NULL,
                features_snapshot TEXT,
                message_sample_count INTEGER,
                token_usage INTEGER,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        ''')
