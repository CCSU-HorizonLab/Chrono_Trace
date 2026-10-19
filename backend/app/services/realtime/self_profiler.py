"""
用户本体画像分析服务 (Self Profiler)

通过 LLM 总结长对话中"我"（is_sender=1）的发言，生成用户本体克隆画像：
- 打字风格体态、常用口头禅/语气词、双方共有事实记忆、沟通角色
- 用于在生成回复时反向注入，使得生成的建议具备真实的"用户味"（千人千面）
- 7 天缓存有效期
"""

import json
import logging
import math
import time
from typing import Callable, Optional
from .llm_http import apply_interactive_fast_mode, post_json_with_retries
from .profile_llm_retry import call_profile_llm_with_budget_retry
from ..wechat.account_settings import get_active_wechat_account_wxid, load_settings_from_file
from ..wechat.contact_filters import is_excluded_contact_username

logger = logging.getLogger(__name__)
def _print(msg: str):
    """统一打印"""
    logger.debug(msg)


# 画像档位只定义回看跨度（包含到哪层分桶）；不做 token 预算截断。
PROFILE_TIME_WINDOWS = {
    'low': 7 * 86400,
    'medium': 30 * 86400,
    'high': 90 * 86400,
    # 兼容旧客户端的 custom 参数，不再把它当作固定 token 预算。
    'custom': 90 * 86400,
}

# 采样时间分桶（近期优先，逐层向历史回溯）。档位决定包含到哪一层：
# 简略=最近7天，普通=到最近30天，精细=到最近90天。桶内消息全量保留，
# 不按 token 预算截断。
PROFILE_SAMPLE_BUCKETS = (
    (7 * 86400, '最近7天'),
    (30 * 86400, '到最近30天'),
    (90 * 86400, '到最近90天'),
)

# 各档位目标采样量（按字符计，不按 token）：回看跨度内的内容不足时，
# 向更早的聊天逐段顺延补充，直到填满目标或历史取尽——不做时间硬截断。
PROFILE_TARGET_CHARS = {
    'low': 8000,
    'medium': 16000,
    'high': 30000,
    'custom': 30000,
}

# 采样字符安全上限：只有聊天量极大时才会从最旧的桶开始收敛，正常
# 规模完全不触发；按字符计数，不按 token 预算截断。
MAX_SAMPLE_CHARS = 80000

# 输出额度重试上限：混合推理模型的思考计入 completion 且长度波动极大，
# 首次请求按保守额度发出，被截断时逐级加倍直到该上限。
# 输出预算上限移至 profile_llm_retry（与 contact_profiler 共用单点）

# 缓存有效期（秒）
PROFILE_TTL = 7 * 86400  # 7 天

# 快照结构版本（窗口键多快照）：表结构/画像口径再变时 +1，口径记录见
# docs/analysis/profile-window.md。旧结构不做迁移——画像是可再生缓存，
# _ensure_table 探查到旧结构直接 DROP 重建。版本随行落库并在所有读取
# 处过滤（同 big5 的 prompt_version 机制）：升版后旧口径快照自然失明，
# 不再以「历史快照」徽标混入新口径结果。
# 与 contact_profiler.PROFILE_SNAPSHOT_SCHEMA 同值同升（两张表同构）。
# v2：prompt 新增【长期背景】全时段基线块（profile_baseline），与 contact 同批。
# v3：prompt 新增【长期记忆事实】块（profile_facts，RAG 事实层注入画像）。
PROFILE_SNAPSHOT_SCHEMA = 3

# 每个分组保留的快照条数上限。rolling 每次续期产生新窗口键快照自然累积，
# 靠此上限防膨胀；custom 是存档品（画像演变半窗 + 手动指定窗共用分组），
# 上限对齐 list_snapshots 的 24 条——回廊能展示的快照不会被裁剪逐出，
# 画像演变的「快照命中增量续跑」承诺才不随窗口数量累积失效。
PROFILE_SNAPSHOT_KEEP = 8
PROFILE_SNAPSHOT_KEEP_CUSTOM = 24

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
        获取当前滚动窗画像（rolling 最新一条；custom 历史快照走 list_snapshots）

        Returns:
            {
                'conversation_id': int,
                'profile': {...画像JSON...},
                'features_snapshot': {...},
                'created_at': int,
                'expires_at': int,
                'expired': bool,
                'window_kind': str,
                'window_from': int,
                'window_to': int,
                'budget_level': str,
            } 或 None（无缓存）
        """
        try:
            from ...db.connection import get_db
            conn = get_db()

            # 确保表存在
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            cursor = conn.execute(
                'SELECT conversation_id, profile_json, features_snapshot, created_at, expires_at, '
                'window_kind, window_from, window_to, budget_level '
                'FROM self_profiles '
                'WHERE account_wxid = ? AND display_name = ? AND window_kind = \'rolling\' '
                'AND schema_version = ? '
                'ORDER BY created_at DESC, id DESC LIMIT 1',
                (resolved_account_wxid, display_name, PROFILE_SNAPSHOT_SCHEMA)
            )
            row = cursor.fetchone()
            if not row:
                return None

            now = int(time.time())
            features_snapshot = {}
            if row['features_snapshot']:
                try:
                    features_snapshot = json.loads(row['features_snapshot'])
                except Exception:
                    features_snapshot = {}
            return {
                'conversation_id': row['conversation_id'],
                'profile': json.loads(row['profile_json']),
                'features_snapshot': features_snapshot,
                'created_at': row['created_at'],
                'expires_at': row['expires_at'],
                'expired': now > row['expires_at'],
                'window_kind': row['window_kind'],
                'window_from': row['window_from'],
                'window_to': row['window_to'],
                'budget_level': row['budget_level'],
            }
        except Exception as e:
            _print(f"[SelfProfiler] 查询缓存失败: {e}")
            return None

    def list_snapshots(self, display_name: str, account_wxid: str = "", window_kind: str = "") -> list:
        """历史快照列表（created_at 降序，最多 24 条），供前端回看"""
        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            sql = ('SELECT id, window_kind, window_from, window_to, budget_level, '
                   'profile_json, message_sample_count, created_at, expires_at '
                   'FROM self_profiles '
                   'WHERE account_wxid = ? AND display_name = ? AND schema_version = ?')
            params: list = [resolved_account_wxid, display_name, PROFILE_SNAPSHOT_SCHEMA]
            if window_kind:
                sql += ' AND window_kind = ?'
                params.append(window_kind)
            sql += ' ORDER BY created_at DESC, id DESC LIMIT 24'
            snapshots = []
            for row in conn.execute(sql, params).fetchall():
                try:
                    profile = json.loads(row['profile_json'])
                except Exception:
                    profile = None
                if not isinstance(profile, dict) or not profile:
                    continue  # 损坏/空残行不进列表——回廊不该展示空画像卡
                snapshots.append({
                    'id': row['id'],
                    'window_kind': row['window_kind'],
                    'window_from': row['window_from'],
                    'window_to': row['window_to'],
                    'budget_level': row['budget_level'],
                    'message_sample_count': row['message_sample_count'],
                    'created_at': row['created_at'],
                    'expires_at': row['expires_at'],
                    'profile': profile,
                })
            return snapshots
        except Exception as e:
            _print(f"[SelfProfiler] 查询快照列表失败: {e}")
            return []

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
            _print(f"[SelfProfiler] 预估 token 失败: {e}")
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
        should_abort: Optional[Callable[[], bool]] = None,
        from_ts: int = 0,
        to_ts: int = 0,
    ) -> dict:
        """
        生成我的画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: 采样档位 (low/medium/high/custom)
            custom_budget: 自定义预算（budget_level='custom' 时生效）
            from_ts/to_ts: 指定历史时间窗（秒级时间戳，闭区间）；缺省 0
                为滚动窗模式（now 锚定档位窗，不足向更早顺延）。指定窗口
                时 budget_level 只决定采样目标量，不再决定回看跨度。

        Returns:
            {'ok': True, 'profile': {...}} 或 {'ok': False, 'error': '...'}
        """
        window_seconds = PROFILE_TIME_WINDOWS.get(budget_level, PROFILE_TIME_WINDOWS['medium'])

        # 指定历史窗（custom）：硬边界，不足不顺延——顺延会篡改用户指定窗口的语义
        custom_window = bool(from_ts or to_ts)
        if custom_window:
            try:
                from_ts, to_ts = int(from_ts), int(to_ts)
            except (TypeError, ValueError):
                return {'ok': False, 'error': '时间窗参数无效：需要秒级整数时间戳'}
            if from_ts <= 0 or to_ts <= 0 or from_ts >= to_ts:
                return {'ok': False, 'error': '时间窗无效：起止需为正数且起点早于终点'}
            if to_ts > int(time.time()) + 86400:
                return {'ok': False, 'error': '时间窗无效：终点不能晚于当前时间'}
            # 不设跨度上限：按调用方切分的时窗如实生成（采样量按档位固定，
            # 窗口越长画像粒度越粗，由 UI 展示窗口标注，不做硬拦）

        now = int(time.time())

        _print(f"\n{'='*60}")
        _print(f"[SelfProfiler] 开始生成画像: {display_name}")
        if custom_window:
            _print(f"[SelfProfiler] 指定历史窗口: {from_ts} ~ {to_ts}（闭区间，不顺延）")
        else:
            _print(f"[SelfProfiler] 回看范围: 最近 {window_seconds // 86400} 天 ({budget_level})；内容不足时自动向更早聊天顺延，不做时间硬截断")
        _print(f"{'='*60}")

        try:
            from ...db.connection import get_db
            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            # 1. 查找 conversation_id
            _print("[SelfProfiler] 步骤1: 查找会话...")
            conv = self._find_conversation(conn, display_name, resolved_account_wxid)
            if not conv:
                _print("[SelfProfiler] ⚠️ 未找到精确匹配的会话，尝试模糊匹配...")
                conv = self._find_conversation_fuzzy(conn, display_name, resolved_account_wxid)
            if not conv:
                _print(f"[SelfProfiler] ❌ 未找到联系人「{display_name}」的历史聊天记录")
                return {'ok': False, 'error': f'未找到联系人「{display_name}」的历史聊天记录，请先导入微信数据'}

            conversation_id = conv['id']
            _print(f"[SelfProfiler] 找到会话: id={conversation_id}, 消息数={conv['message_count']}")

            # 2. 特征与采样共用同一窗口口径（rolling 用名义窗，采样可顺延）
            if custom_window:
                feature_from, feature_to = from_ts, to_ts
            else:
                feature_from, feature_to = now - window_seconds, now
            features = self._collect_features(conn, conversation_id, feature_from, feature_to)
            _print(f"[SelfProfiler] 特征数据收集完成: {list(features.keys())}")

            # 全时段基线：rolling 长关系只覆盖尾部的失真，在 prompt 层补全局坐标
            from .profile_baseline import collect_full_period_baseline
            baseline = collect_full_period_baseline(conn, conversation_id, feature_from, feature_to)

            # 长期事实：事实层多为对方/关系向事实，对自我画像提供关系
            # 语境与共有记忆线索（shared_memories 槽的直接素材）
            from .profile_facts import collect_profile_facts
            long_term_facts = collect_profile_facts(conn, resolved_account_wxid, conversation_id)
            if long_term_facts:
                _print(f"[SelfProfiler] 长期记忆事实: {len(long_term_facts)} 条注入")

            # 3. 采样对话轮次
            sample = self._sample_conversation_turns(
                conn, conversation_id, window_seconds,
                PROFILE_TARGET_CHARS.get(budget_level, PROFILE_TARGET_CHARS['high']),
                from_ts=from_ts if custom_window else 0,
                to_ts=to_ts if custom_window else 0,
            )
            _print(f"[SelfProfiler] 采样完成: {len(sample)} 条消息, 约 {self._count_tokens(sample)} tokens")

            if not sample:
                if custom_window:
                    return {'ok': False, 'error': '该时间窗内没有可用的文本消息，请调整窗口范围'}
                return {'ok': False, 'error': '没有可用的文本消息，无法生成画像'}

            # 4. 构造 prompt（窗口口径按样本实际范围披露，LLM 才知道这是窗口分析）
            sample_from = min(m['timestamp'] for m in sample)
            sample_to = max(m['timestamp'] for m in sample)
            if custom_window:
                window_desc = (
                    f"{self._fmt_date(sample_from)} 至 {self._fmt_date(sample_to)}"
                    f"（约 {(sample_to - sample_from) // 86400 + 1} 天，指定历史窗口）"
                )
            else:
                window_desc = (
                    f"{self._fmt_date(sample_from)} 至 {self._fmt_date(sample_to)}"
                    f"（最近滚动窗采样，内容不足时已向更早顺延）"
                )
            user_prompt = self._build_profile_prompt(display_name, conv, features, sample, window_desc, baseline, long_term_facts)
            _print(f"[SelfProfiler] Prompt 长度: {len(user_prompt)} 字符")

            # 5. 调用 LLM，传入预算以动态决定输出额度
            profile_data = self._call_llm(user_prompt, should_abort=should_abort)

            _print("[SelfProfiler] ✅ 画像生成成功!")
            _print(f"[SelfProfiler] 标签: {profile_data.get('personality_tags', [])}")

            # 6. 缓存为快照（rolling 记名义窗，custom 记精确窗）
            self._save_cache(
                conn, display_name, conversation_id, profile_data,
                len(sample), features, resolved_account_wxid,
                window_kind='custom' if custom_window else 'rolling',
                window_from=from_ts if custom_window else feature_from,
                window_to=to_ts if custom_window else feature_to,
                budget_level=budget_level,
            )

            return {'ok': True, 'profile': profile_data}

        except Exception as e:
            import traceback
            _print(f"[SelfProfiler] ❌ 生成画像失败: {e}")
            traceback.print_exc()
            return {'ok': False, 'error': str(e)}

    @staticmethod
    def _fmt_date(ts: int) -> str:
        """时间戳转 YYYY-MM-DD（本地时区）"""
        from datetime import datetime
        return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')

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
            if is_excluded_contact_username(row['username'], exclude_chatroom=False):
                _print(f"[SelfProfiler] 跳过系统联系人会话: username={row['username']}")
            else:
                _print(f"[SelfProfiler] ✅ 直接匹配成功: id={row['id']}, "
                       f"username={row['username']}, "
                       f"nickname={row['nickname']}, remark={row['remark']}, "
                       f"messages={row['message_count']}")
                return dict(row)

        # 策略2: 通过 contacts 表反查 username(wxid)
        _print("[SelfProfiler] 直接匹配失败，尝试通过 contacts 表反查...")
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
            _print(f"[SelfProfiler] 找到 {len(contacts)} 个匹配的联系人: "
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
                    if is_excluded_contact_username(conv_row['username'], exclude_chatroom=False):
                        _print(f"[SelfProfiler] 跳过系统联系人反查结果: username={conv_row['username']}")
                        continue
                    _print(f"[SelfProfiler] ✅ contacts 反查匹配成功: "
                           f"contact={contact['nickname']}({wxid}) → "
                           f"conv_id={conv_row['id']}, messages={conv_row['message_count']}")
                    return dict(conv_row)

        _print(f"[SelfProfiler] ⚠️ 精确匹配全部失败: {display_name}")
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
                if not is_excluded_contact_username(row['username'], exclude_chatroom=False)
            ]
            if valid_rows:
                _print(f"[SelfProfiler] 模糊匹配 conversations 结果: "
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
            _print(f"[SelfProfiler] 模糊匹配 contacts 结果: "
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
                    if is_excluded_contact_username(conv_row['username'], exclude_chatroom=False):
                        _print(f"[SelfProfiler] 跳过系统联系人模糊反查结果: username={conv_row['username']}")
                        continue
                    _print(f"[SelfProfiler] ✅ 模糊反查匹配成功: "
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
        _print(f"[SelfProfiler] 数据库中的会话列表 (top10): {all_convs}")
        return None

    def _collect_features(self, conn, conversation_id: int, from_ts: int = 0, to_ts: int = 0) -> dict:
        """
        收集特征数据，逐项 try/except。

        from_ts/to_ts 成对非 0 时统计范围限定在闭区间 [from_ts, to_ts]，
        与采样同一窗口口径；缺省 0 为全时段。
        """
        features = {}
        windowed = bool(from_ts and to_ts)

        # 主动性统计：按 sessions 会话开始时间统计（initiative_stats 是
        # 全时段单行聚合，无法窗口化，不再回退使用）
        try:
            sql = (
                'SELECT COUNT(*) AS total_sessions, '
                'SUM(initiator = \'user\') AS user_initiated, '
                'SUM(initiator = \'other\') AS other_initiated '
                'FROM sessions WHERE conversation_id = ?'
            )
            params: list = [conversation_id]
            if windowed:
                sql += ' AND start_time >= ? AND start_time <= ?'
                params.extend([from_ts, to_ts])
            row = conn.execute(sql, params).fetchone()
            total = row[0] or 0
            user_initiated = row[1] or 0
            other_initiated = row[2] or 0
            if total > 0:
                rate = other_initiated / total
                features['initiative'] = {
                    'total_sessions': total,
                    'other_initiated': other_initiated,
                    'user_initiated': user_initiated,
                    'initiative_rate': rate,
                    'desc': f"对方主动发起{rate:.0%}的会话",
                }
        except Exception as e:
            _print(f"[SelfProfiler] 跳过主动性统计: {e}")

        # 响应时间：按发送消息时间窗过滤（JOIN messages 取 timestamp）
        try:
            sql = (
                'SELECT COUNT(*) AS cnt, AVG(rt.response_time_seconds) AS avg_rt, '
                'MIN(rt.response_time_seconds) AS min_rt, MAX(rt.response_time_seconds) AS max_rt '
                'FROM response_times rt '
                'JOIN messages m ON m.id = rt.sent_message_id '
                'WHERE rt.conversation_id = ? AND rt.is_abnormal = 0'
            )
            params: list = [conversation_id]
            if windowed:
                sql += ' AND m.timestamp >= ? AND m.timestamp <= ?'
                params.extend([from_ts, to_ts])
            row = conn.execute(sql, params).fetchone()
            if row and row['cnt'] > 0:
                features['response_time'] = {
                    'count': row['cnt'],
                    'avg_seconds': round(row['avg_rt'], 1),
                    'min_seconds': round(row['min_rt'], 1),
                    'max_seconds': round(row['max_rt'], 1),
                }
        except Exception as e:
            _print(f"[SelfProfiler] 跳过响应时间: {e}")

        # 字数统计：直接从 messages 按窗口统计（word_counts 聚合行无法窗口化）
        try:
            sql = (
                'SELECT is_sender, SUM(LENGTH(content)) AS chars '
                'FROM messages '
                'WHERE conversation_id = ? AND message_type = 1 '
                'AND content IS NOT NULL AND content != \'\''
            )
            params: list = [conversation_id]
            if windowed:
                sql += ' AND timestamp >= ? AND timestamp <= ?'
                params.extend([from_ts, to_ts])
            rows = conn.execute(sql + ' GROUP BY is_sender', params).fetchall()
            user_chars = 0
            other_chars = 0
            for r in rows:
                if r['is_sender']:
                    user_chars += r['chars'] or 0
                else:
                    other_chars += r['chars'] or 0
            if user_chars or other_chars:
                features['word_counts'] = {
                    'user_chars': user_chars,
                    'other_chars': other_chars,
                    # 比值（对方/我）；我方窗口内零字时无定义
                    'ratio': round(other_chars / user_chars, 2) if user_chars else None,
                }
        except Exception as e:
            _print(f"[SelfProfiler] 跳过字数统计: {e}")

        # 用户消息长度风格（按窗口过滤我方消息）
        try:
            sql = (
                'SELECT COUNT(*) AS cnt, AVG(LENGTH(content)) AS avg_len '
                'FROM messages '
                'WHERE conversation_id = ? AND is_sender = 1 '
                'AND message_type = 1 AND content IS NOT NULL AND content != \'\''
            )
            params: list = [conversation_id]
            if windowed:
                sql += ' AND timestamp >= ? AND timestamp <= ?'
                params.extend([from_ts, to_ts])
            row = conn.execute(sql, params).fetchone()
            if row and row['cnt'] > 0:
                features['user_msg_style'] = {
                    'msg_count': row['cnt'],
                    'avg_chars_per_msg': round(row['avg_len'] or 0, 1),
                }
        except Exception as e:
            _print(f"[SelfProfiler] 跳过用户消息长度统计: {e}")

        # 好感度评分：全时段分析产物，无法窗口化——保留注入但如实标注口径
        try:
            from ..analysis.affinity_analysis_service import AffinityAnalysisService

            row = conn.execute(
                'SELECT overall_score, emotional_resonance_score, '
                'chat_positivity_score, attitude_tendency_score, '
                'preference_compatibility_score '
                'FROM affinity_scores WHERE conversation_id = ? '
                'AND analysis_version = ? '
                'ORDER BY created_at DESC LIMIT 1',
                (conversation_id, AffinityAnalysisService.CALIBER_VERSION)
            ).fetchone()
            if row:
                # 列名为口径 4 遗留：chat_positivity_score 现承载互动投入、
                # attitude_tendency_score 现承载亲近信号（后继语义映射）
                features['affinity'] = {
                    'overall': round(row['overall_score'], 1),
                    'emotional_resonance': round(row['emotional_resonance_score'], 1),
                    'interaction_investment': round(row['chat_positivity_score'], 1),
                    'closeness_signals': round(row['attitude_tendency_score'], 1),
                    'preference_compatibility': round(row['preference_compatibility_score'], 1),
                    'caliber': 'full_period',
                }
        except Exception as e:
            _print(f"[SelfProfiler] 跳过好感度评分: {e}")

        return features

    def _sample_conversation_turns(
        self, conn, conversation_id: int, time_window_seconds: int, target_chars: int,
        from_ts: int = 0, to_ts: int = 0,
    ) -> list[dict]:
        """
        按时间分桶采样回看跨度内的完整对话。

        指定历史窗（from_ts/to_ts 闭区间）：硬边界单次采样，不做分桶、
        不向更早顺延——顺延会篡改用户指定窗口的语义；仅保留
        MAX_SAMPLE_CHARS 收敛兜底。

        滚动窗（缺省）：跨度内消息全量保留；内容不足 target_chars 时向
        更早逐段顺延补充，直到填满目标量或历史取尽——不按时间硬截断。
        """
        if from_ts and to_ts:
            samples = [dict(row) for row in conn.execute(
                'SELECT content, is_sender, timestamp '
                'FROM messages '
                'WHERE conversation_id = ? AND message_type = 1 '
                'AND timestamp >= ? AND timestamp <= ? '
                'AND content IS NOT NULL AND content != \'\' '
                'ORDER BY timestamp ASC',
                (conversation_id, int(from_ts), int(to_ts)),
            ).fetchall()]
            total_chars = sum(len(m.get('content') or '') for m in samples)
            if total_chars > MAX_SAMPLE_CHARS:
                while len(samples) > 1 and total_chars > MAX_SAMPLE_CHARS:
                    total_chars -= len(samples.pop(0).get('content') or '')
                _print(f"[SelfProfiler] ⚠️ 指定窗口聊天量超出采样字符上限，已从最旧消息收敛至 {total_chars} 字符")
            return samples

        now = int(time.time())
        window = max(1, int(time_window_seconds))
        buckets = [b for b in PROFILE_SAMPLE_BUCKETS if b[0] <= window]
        if not buckets:
            buckets = [PROFILE_SAMPLE_BUCKETS[0]]

        def _fetch_range(range_start: int, range_end: int) -> list[dict]:
            cursor = conn.execute(
                'SELECT content, is_sender, timestamp '
                'FROM messages '
                'WHERE conversation_id = ? AND message_type = 1 '
                'AND timestamp > ? AND timestamp <= ? '
                'AND content IS NOT NULL AND content != "" '
                'ORDER BY timestamp ASC',
                (conversation_id, range_start, range_end),
            )
            return [dict(row) for row in cursor.fetchall()]

        bucket_lists: list[list[dict]] = []
        total_chars = 0
        prev_end = now
        for boundary, _label in buckets:
            bucket_start = now - boundary
            bucket_messages = _fetch_range(bucket_start, prev_end)
            prev_end = bucket_start
            if not bucket_messages:
                continue
            bucket_lists.append(bucket_messages)
            total_chars += sum(len(m.get('content') or '') for m in bucket_messages)

        # 跨度内内容不足目标量：以 30 天为段向后顺延补充，直到填满或
        # 历史取尽。空段（聊天断档）跳过继续往前找。
        row = conn.execute(
            'SELECT MIN(timestamp) FROM messages '
            'WHERE conversation_id = ? AND message_type = 1 '
            'AND content IS NOT NULL AND content != ""',
            (conversation_id,),
        ).fetchone()
        oldest_ts = row[0] if row else None
        segment = 30 * 86400
        extended_from = None
        while total_chars < target_chars and oldest_ts is not None and prev_end > oldest_ts:
            seg_start = prev_end - segment
            seg_messages = _fetch_range(seg_start, prev_end)
            prev_end = seg_start
            if not seg_messages:
                continue
            bucket_lists.append(seg_messages)
            extended_from = seg_start
            total_chars += sum(len(m.get('content') or '') for m in seg_messages)

        if extended_from is not None:
            _print(
                f"[SelfProfiler] ⚠️ 回看跨度内内容不足，已顺延至 "
                f"{(now - extended_from) // 86400} 天前补充采样，共 {total_chars} 字符"
            )

        if not bucket_lists:
            return []

        # 极大聊天量的兜底：从最旧的桶开始收敛，避免 prompt 无界膨胀；
        # 正常聊天量不会触发。按字符计数，不按 token 预算截断。
        if total_chars > MAX_SAMPLE_CHARS:
            for bucket in reversed(bucket_lists):
                while len(bucket) > 1 and total_chars > MAX_SAMPLE_CHARS:
                    total_chars -= len(bucket.pop(0).get('content') or '')
                if total_chars <= MAX_SAMPLE_CHARS:
                    break
            _print(f"[SelfProfiler] ⚠️ 聊天量超出采样字符上限，已从最旧消息开始收敛至 {total_chars} 字符")

        samples = [m for bucket in bucket_lists for m in bucket]
        samples.sort(key=lambda m: m['timestamp'])
        return samples

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
        sample: list[dict],
        window_desc: str = '',
        baseline: dict | None = None,
        long_term_facts: list | None = None,
    ) -> str:
        """组装画像生成的 user prompt"""
        parts = []

        # 基础信息
        from datetime import datetime
        first_date = datetime.fromtimestamp(conv.get('created_at', 0)).strftime('%Y-%m-%d')
        last_date = datetime.fromtimestamp(conv.get('updated_at', 0)).strftime('%Y-%m-%d')

        parts.append("【基础信息】")
        parts.append(f"- 联系人名称: {display_name}")
        parts.append(f"- 消息总数: {conv.get('message_count', 0)}")
        parts.append(f"- 时间跨度: {first_date} ~ {last_date}")
        if window_desc:
            parts.append(f"- 样本时间范围: {window_desc}")

        # 长期背景（全时段基线，先全局后窗口的阅读顺序）
        if baseline:
            from .profile_baseline import render_baseline_block
            block = render_baseline_block(baseline)
            if block:
                parts.append("")
                parts.append(block)

        # 长期记忆事实（全时段结构化记忆，语义层补窗口盲区）
        if long_term_facts:
            from .profile_facts import render_facts_block
            block = render_facts_block(long_term_facts)
            if block:
                parts.append("")
                parts.append(block)

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
            ratio_text = f", 比值(对方/我)={wc['ratio']}" if wc.get('ratio') is not None else ""
            feat_lines.append(
                f"- 字数: 我={wc['user_chars']}字, 对方={wc['other_chars']}字{ratio_text}"
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

        # 好感度（全时段分析产物，仅供背景参考）
        aff = features.get('affinity')
        if aff:
            parts.append("")
            parts.append("【好感度评分】（全时段评分，仅供背景参考）")
            parts.append(f"- 总体: {aff['overall']}/100")
            parts.append(f"- 情感共鸣: {aff['emotional_resonance']}, "
                         f"互动投入: {aff['interaction_investment']}, "
                         f"亲近信号: {aff['closeness_signals']}")

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

    def _call_llm(
        self, user_prompt: str, _legacy_sample_budget: int | None = None,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> dict:
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
                    extra_body TEXT,
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

        # 输出额度随真实 prompt 变动：画像 JSON 通常远短于聊天样本，保留
        # 约 22% 的输入规模加 JSON 固定结构余量；模型配置值只作为下限。
        prompt_tokens = self._estimate_msg_tokens(PROFILE_SYSTEM_PROMPT + user_prompt)
        configured_floor = max(1, int(model_config.get('max_tokens') or 0))
        dynamic_max_tokens = max(configured_floor, 384 + math.ceil(prompt_tokens * 0.22))
        # 画像 JSON 大小不随聊天量增长，输出额度不随 prompt 无限放大，
        # 避免超出模型 max_tokens 上限导致请求被拒。
        dynamic_max_tokens = min(dynamic_max_tokens, 8192)
        # 混合推理模型（deepseek-flash/reasoner 等）把 reasoning_content 也计入
        # completion token，小预算会在最终 JSON 输出前耗尽，画像解析必然失败，
        # 因此推理模型保留下限 8192、普通模型保留下限 4096。
        model_id = str(model_config.get('model_id') or '').lower()
        hybrid_reasoning_model = 'flash' in model_id or 'reason' in model_id
        dynamic_max_tokens = max(dynamic_max_tokens, 8192 if hybrid_reasoning_model else 4096)

        payload = {
            'model': model_config['model_id'],
            'messages': [
                {'role': 'system', 'content': PROFILE_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.5,  # 画像生成用较低温度
            # 画像必须落在 message.content，不能只生成 reasoning_content。
            'response_format': {'type': 'json_object'},
        }
        # 交互调用快速模式：思考模型附 reasoning_effort:"low"（压低思考
        # 量，避免命中「思考耗尽输出预算」），模型级 extra_body 优先
        apply_interactive_fast_mode(payload, model_config)

        headers = {}
        api_key = model_config.get('api_key', '')
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        post = post_json_with_retries
        if should_abort is not None:
            # 弹窗关闭取消：should_abort 传入 HTTP 层，在尝试边界中止
            def post(**kw):
                return post_json_with_retries(should_abort=should_abort, **kw)

        parsed = call_profile_llm_with_budget_retry(
            url=url,
            payload=payload,
            headers=headers,
            timeout=self.timeout,
            initial_budget=dynamic_max_tokens,
            parse_json=self._parse_profile_json,
            extract_json_candidate=self._extract_json_candidate,
            post_json=post,
            log=_print,
            log_prefix='[SelfProfiler]',
        )
        if not parsed:
            raise ValueError('LLM 返回内容解析失败：未得到合法画像 JSON')

        return parsed

    def _parse_profile_json(self, text: str) -> Optional[dict]:
        """解析 LLM 返回的画像 JSON"""
        try:
            cleaned = self._extract_json_candidate(text)
            sanitized = self._strip_trailing_json_commas(
                self._sanitize_json_candidate(cleaned)
            )
            data = json.loads(sanitized)
            if not isinstance(data, dict):
                raise ValueError('画像 JSON 根节点不是对象')

            # 校验必要字段
            required = ['typing_style', 'attitude_and_role', 'do_and_donts']
            for field in required:
                if field not in data:
                    _print(f"[SelfProfiler] ⚠️ 缺少字段: {field}")

            if 'sentence_patterns' not in data or not isinstance(data.get('sentence_patterns'), list):
                data['sentence_patterns'] = []

            return data
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            _print(f"[SelfProfiler] JSON 解析失败: {e}, 原文: {text[:200]}")
            return None

    def _extract_json_candidate(self, text: str) -> str:
        """尽量从模型输出中提取一个 JSON 对象字符串。"""
        cleaned = (text or '').strip()
        if not cleaned:
            return ''

        lowered = cleaned.lower()
        if '```json' in lowered:
            start = lowered.find('```json') + len('```json')
            candidate = cleaned[start:]
            return candidate.split('```', 1)[0].strip()

        if '```' in cleaned:
            candidate = cleaned.split('```', 1)[1]
            return candidate.split('```', 1)[0].strip()

        if cleaned.startswith('{') and cleaned.endswith('}'):
            return cleaned

        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1].strip()

        return cleaned

    def _sanitize_json_candidate(self, text: str) -> str:
        """修正常见的 JSON 非法控制字符，尤其是字符串中的裸换行。"""
        if not text:
            return ''

        result: list[str] = []
        in_string = False
        escape = False

        for char in text:
            if in_string:
                if escape:
                    result.append(char)
                    escape = False
                    continue
                if char == '\\':
                    result.append(char)
                    escape = True
                    continue
                if char == '"':
                    result.append(char)
                    in_string = False
                    continue
                if char == '\n':
                    result.append('\\n')
                    continue
                if char == '\r':
                    result.append('\\r')
                    continue
                if char == '\t':
                    result.append('\\t')
                    continue
                result.append(char)
                continue

            result.append(char)
            if char == '"':
                in_string = True

        return ''.join(result)

    def _strip_trailing_json_commas(self, text: str) -> str:
        """去掉对象或数组闭合符前的尾逗号，避免常见 LLM JSON 变体解析失败。"""
        if not text:
            return ''

        result: list[str] = []
        in_string = False
        escape = False

        for char in text:
            if in_string:
                result.append(char)
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                result.append(char)
                in_string = True
                continue

            if char in '}]':
                whitespace: list[str] = []
                while result and result[-1] in ' \t\r\n':
                    whitespace.append(result.pop())
                if result and result[-1] == ',':
                    result.pop()
                result.extend(reversed(whitespace))

            result.append(char)

        return ''.join(result)

    def _save_cache(
        self, conn, display_name: str, conversation_id: int,
        profile: dict, sample_count: int, features: dict, account_wxid: str,
        window_kind: str = 'rolling', window_from: int = 0, window_to: int = 0,
        budget_level: str = 'medium',
    ):
        """保存画像快照（窗口键多快照共存），写后按窗口分组裁剪上限"""
        try:
            self._ensure_table(conn)

            now = int(time.time())
            # 历史窗快照是存档品：不参与 7 天 TTL，仅由数量上限裁剪
            expires_at = now + (365 * 86400 if window_kind == 'custom' else PROFILE_TTL)
            conn.execute(
                'INSERT OR REPLACE INTO self_profiles '
                '(account_wxid, display_name, conversation_id, window_kind, window_from, '
                'window_to, budget_level, schema_version, profile_json, features_snapshot, '
                'message_sample_count, token_usage, created_at, expires_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    account_wxid,
                    display_name,
                    conversation_id,
                    window_kind,
                    int(window_from),
                    int(window_to),
                    budget_level,
                    PROFILE_SNAPSHOT_SCHEMA,
                    json.dumps(profile, ensure_ascii=False),
                    json.dumps(features, ensure_ascii=False),
                    sample_count,
                    0,  # 实际 token 消耗可从 LLM 响应中提取
                    now,
                    expires_at,
                )
            )
            # 分组只保留最近 N 条：rolling 用 KEEP 防续期累积，custom 用
            # KEEP_CUSTOM（存档语义，见常量注释）
            keep = PROFILE_SNAPSHOT_KEEP_CUSTOM if window_kind == 'custom' else PROFILE_SNAPSHOT_KEEP
            conn.execute(
                'DELETE FROM self_profiles '
                'WHERE account_wxid = ? AND display_name = ? AND window_kind = ? '
                'AND id NOT IN ('
                '  SELECT id FROM self_profiles '
                '  WHERE account_wxid = ? AND display_name = ? AND window_kind = ? '
                '  ORDER BY created_at DESC, id DESC LIMIT ?'
                ')',
                (account_wxid, display_name, window_kind,
                 account_wxid, display_name, window_kind, keep),
            )
            conn.commit()
            _print(f"[SelfProfiler] 画像快照已缓存（{window_kind} 窗口分组保留最近 {keep} 条）")
        except Exception as e:
            _print(f"[SelfProfiler] ⚠️ 缓存保存失败: {e}")

    def _ensure_table(self, conn):
        """确保缓存表存在（快照结构：窗口键多快照 + 结构版本列；旧结构 DROP 重建不迁移）"""
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'self_profiles'"
        ).fetchone()
        if exists:
            cols = {row[1] for row in conn.execute('PRAGMA table_info(self_profiles)')}
            if 'window_kind' in cols and 'schema_version' in cols:
                return  # 已是当前快照结构，零 DDL
            _print("[SelfProfiler] 旧结构画像表，DROP 重建为快照结构，不迁移")
            conn.execute('DROP TABLE self_profiles')
            conn.commit()
        conn.execute(f'''
            CREATE TABLE IF NOT EXISTS self_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                display_name TEXT NOT NULL,
                conversation_id INTEGER,
                window_kind TEXT NOT NULL DEFAULT 'rolling',
                window_from INTEGER NOT NULL DEFAULT 0,
                window_to INTEGER NOT NULL DEFAULT 0,
                budget_level TEXT NOT NULL DEFAULT 'medium',
                schema_version INTEGER NOT NULL DEFAULT {PROFILE_SNAPSHOT_SCHEMA},
                profile_json TEXT NOT NULL,
                features_snapshot TEXT,
                message_sample_count INTEGER,
                token_usage INTEGER,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                UNIQUE(account_wxid, display_name, window_kind, window_from, window_to)
            )
        ''')
