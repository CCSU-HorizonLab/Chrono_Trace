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
# 输出预算上限移至 profile_llm_retry（与 self_profiler 共用单点）

# 缓存有效期（秒）
PROFILE_TTL = 7 * 86400  # 7 天

# 快照结构版本（窗口键多快照）：表结构/画像口径再变时 +1，口径记录见
# docs/analysis/profile-window.md。旧结构不做迁移——画像是可再生缓存，
# _ensure_table 探查到旧结构直接 DROP 重建。版本随行落库并在所有读取
# 处过滤（同 big5 的 prompt_version 机制）：升版后旧口径快照自然失明，
# 不再以「历史快照」徽标混入新口径结果。
# v2：prompt 新增【长期背景】全时段基线块（profile_baseline），rolling
#     对长关系只覆盖尾部的问题在 prompt 层给 LLM 全局坐标。
# v3：prompt 新增【长期记忆事实】块（profile_facts，RAG 事实层注入画像）。
# v4：prompt 新增【关系章节摘要】块（profile_chapter_digest，月摘要→章节
#     归并的全量语料语义层注入画像）。
# v5：新增 origin 列（''=滚动/手动指定窗，'evolution'=画像演变章节段快照），
#     回看列表按来源区分徽标，不再把演变段混作手动存档。
PROFILE_SNAPSHOT_SCHEMA = 5

# 每个分组保留的快照条数上限。rolling 每次续期产生新窗口键快照自然累积，
# 靠此上限防膨胀；custom 是存档品（画像演变半窗 + 手动指定窗共用分组），
# 上限对齐 list_snapshots 的 24 条——回廊能展示的快照不会被裁剪逐出，
# 画像演变的「快照命中增量续跑」承诺才不随窗口数量累积失效。
PROFILE_SNAPSHOT_KEEP = 8
PROFILE_SNAPSHOT_KEEP_CUSTOM = 24

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
        获取当前滚动窗画像（rolling 最新一条；custom 历史快照走 list_snapshots）

        Returns:
            {
                'profile': {...画像JSON...},
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
                'SELECT profile_json, created_at, expires_at, conversation_id, '
                'window_kind, window_from, window_to, budget_level '
                'FROM contact_profiles '
                'WHERE account_wxid = ? AND display_name = ? AND window_kind = \'rolling\' '
                'AND schema_version = ? '
                'ORDER BY created_at DESC, id DESC LIMIT 1',
                (resolved_account_wxid, display_name, PROFILE_SNAPSHOT_SCHEMA)
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
                'conversation_id': row['conversation_id'],
                'window_kind': row['window_kind'],
                'window_from': row['window_from'],
                'window_to': row['window_to'],
                'budget_level': row['budget_level'],
            }
        except Exception as e:
            _print(f"[ContactProfiler] 查询缓存失败: {e}")
            return None

    def list_snapshots(self, display_name: str, account_wxid: str = "", window_kind: str = "") -> list:
        """历史快照列表（created_at 降序，最多 24 条），供前端回看"""
        try:
            from ...db.connection import get_db
            conn = get_db()
            self._ensure_table(conn)
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            sql = ('SELECT id, conversation_id, window_kind, window_from, window_to, '
                   'budget_level, origin, profile_json, message_sample_count, '
                   'created_at, expires_at '
                   'FROM contact_profiles '
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
                    'conversation_id': row['conversation_id'],
                    'window_kind': row['window_kind'],
                    'window_from': row['window_from'],
                    'window_to': row['window_to'],
                    'budget_level': row['budget_level'],
                    'origin': row['origin'] or '',
                    'message_sample_count': row['message_sample_count'],
                    'created_at': row['created_at'],
                    'expires_at': row['expires_at'],
                    'profile': profile,
                })
            return snapshots
        except Exception as e:
            _print(f"[ContactProfiler] 查询快照列表失败: {e}")
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
        should_abort: Optional[Callable[[], bool]] = None,
        from_ts: int = 0,
        to_ts: int = 0,
        origin: str = '',
    ) -> dict:
        """
        生成联系人画像（调 LLM）

        Args:
            display_name: 联系人显示名
            budget_level: 采样档位 (low/medium/high/custom)
            custom_budget: 自定义预算（budget_level='custom' 时生效）
            from_ts/to_ts: 指定历史时间窗（秒级时间戳，闭区间）；缺省 0
                为滚动窗模式（now 锚定档位窗，不足向更早顺延）。指定窗口
                时 budget_level 只决定采样目标量，不再决定回看跨度。
            origin: 快照来源标记（''=默认，'evolution'=画像演变章节段），
                回看列表按来源区分徽标

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
        _print(f"[ContactProfiler] 开始生成画像: {display_name}")
        if custom_window:
            _print(f"[ContactProfiler] 指定历史窗口: {from_ts} ~ {to_ts}（闭区间，不顺延）")
        else:
            _print(f"[ContactProfiler] 回看范围: 最近 {window_seconds // 86400} 天 ({budget_level})；内容不足时自动向更早聊天顺延，不做时间硬截断")
        _print(f"{'='*60}")

        try:
            from ...db.connection import get_db
            conn = get_db()
            resolved_account_wxid = self._resolve_account_wxid(account_wxid)

            # 1. 查找 conversation_id
            _print("[ContactProfiler] 步骤1: 查找会话...")
            conv = self._find_conversation(conn, display_name, resolved_account_wxid)
            if not conv:
                _print("[ContactProfiler] ⚠️ 未找到精确匹配的会话，尝试模糊匹配...")
                conv = self._find_conversation_fuzzy(conn, display_name, resolved_account_wxid)
            if not conv:
                _print(f"[ContactProfiler] ❌ 未找到联系人「{display_name}」的历史聊天记录")
                return {'ok': False, 'error': f'未找到联系人「{display_name}」的历史聊天记录，请先导入微信数据'}

            conversation_id = conv['id']
            _print(f"[ContactProfiler] 找到会话: id={conversation_id}, 消息数={conv['message_count']}")

            # 2. 特征与采样共用同一窗口口径（rolling 用名义窗，采样可顺延）
            if custom_window:
                feature_from, feature_to = from_ts, to_ts
            else:
                feature_from, feature_to = now - window_seconds, now
            features = self._collect_features(conn, conversation_id, feature_from, feature_to)
            _print(f"[ContactProfiler] 特征数据收集完成: {list(features.keys())}")

            # 全时段基线：rolling 长关系只覆盖尾部的失真，在 prompt 层补全局坐标
            from .profile_baseline import collect_full_period_baseline
            baseline = collect_full_period_baseline(conn, conversation_id, feature_from, feature_to)

            # 长期事实：RAG 事实层是全时段的（supersede 链顶端），注入
            # 后画像可引用窗口外沉淀的结构化记忆，零新增 LLM 调用
            from .profile_facts import collect_profile_facts
            long_term_facts = collect_profile_facts(conn, resolved_account_wxid, conversation_id)
            if long_term_facts:
                _print(f"[ContactProfiler] 长期记忆事实: {len(long_term_facts)} 条注入")

            # 章节摘要：全量语料经月摘要→章节归并的语义层（章节摘要任务
            # 产出落库，纯 SQL 读取零 LLM 调用）；rolling 注入全部章节
            # （全时段坐标），custom 只注入与窗口交叠的章
            from .profile_chapter_digest import collect_chapter_digest
            chapter_digest = collect_chapter_digest(
                conn, conversation_id,
                feature_from if custom_window else 0, feature_to if custom_window else 0,
            )
            if chapter_digest:
                _print(f"[ContactProfiler] 关系章节摘要: {len(chapter_digest)} 章注入")

            # 3. 采样对话轮次
            sample = self._sample_conversation_turns(
                conn, conversation_id, window_seconds,
                PROFILE_TARGET_CHARS.get(budget_level, PROFILE_TARGET_CHARS['high']),
                from_ts=from_ts if custom_window else 0,
                to_ts=to_ts if custom_window else 0,
            )
            _print(f"[ContactProfiler] 采样完成: {len(sample)} 条消息, 约 {self._count_tokens(sample)} tokens")

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
            user_prompt = self._build_profile_prompt(
                display_name, conv, features, sample, window_desc,
                baseline, long_term_facts, chapter_digest,
            )
            _print(f"[ContactProfiler] Prompt 长度: {len(user_prompt)} 字符")

            # 5. 调用 LLM，传入预算以动态决定输出额度
            profile_data = self._call_llm(
                user_prompt, should_abort=should_abort,
                account_wxid=resolved_account_wxid,
            )

            _print("[ContactProfiler] ✅ 画像生成成功!")
            _print(f"[ContactProfiler] 标签: {profile_data.get('personality_tags', [])}")

            # 6. 缓存为快照（rolling 记名义窗，custom 记精确窗）
            self._save_cache(
                conn, display_name, conversation_id, profile_data,
                len(sample), features, resolved_account_wxid,
                window_kind='custom' if custom_window else 'rolling',
                window_from=from_ts if custom_window else feature_from,
                window_to=to_ts if custom_window else feature_to,
                budget_level=budget_level,
                origin=origin,
            )

            return {'ok': True, 'profile': profile_data}

        except Exception as e:
            import traceback
            _print(f"[ContactProfiler] ❌ 生成画像失败: {e}")
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
                _print(f"[ContactProfiler] 跳过系统联系人会话: username={row['username']}")
            else:
                _print(f"[ContactProfiler] ✅ 直接匹配成功: id={row['id']}, "
                       f"username={row['username']}, "
                       f"nickname={row['nickname']}, remark={row['remark']}, "
                       f"messages={row['message_count']}")
                return dict(row)

        # 策略2: 通过 contacts 表反查 username(wxid)
        _print("[ContactProfiler] 直接匹配失败，尝试通过 contacts 表反查...")
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
                    if is_excluded_contact_username(conv_row['username'], exclude_chatroom=False):
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
                if not is_excluded_contact_username(row['username'], exclude_chatroom=False)
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
                    if is_excluded_contact_username(conv_row['username'], exclude_chatroom=False):
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
            _print(f"[ContactProfiler] 跳过主动性统计: {e}")

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
            _print(f"[ContactProfiler] 跳过响应时间: {e}")

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
            _print(f"[ContactProfiler] 跳过字数统计: {e}")

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
            _print(f"[ContactProfiler] 跳过好感度评分: {e}")

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
                _print(f"[ContactProfiler] ⚠️ 指定窗口聊天量超出采样字符上限，已从最旧消息收敛至 {total_chars} 字符")
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
                f"[ContactProfiler] ⚠️ 回看跨度内内容不足，已顺延至 "
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
            _print(f"[ContactProfiler] ⚠️ 聊天量超出采样字符上限，已从最旧消息开始收敛至 {total_chars} 字符")

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
        chapter_digest: list | None = None,
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

        # 关系章节摘要（全量语料的章节叙事，语义层补窗口盲区）
        if chapter_digest:
            from .profile_chapter_digest import render_chapter_digest_block
            block = render_chapter_digest_block(chapter_digest)
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
        account_wxid: str = "",
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
            _print(f"[ContactProfiler] 获取模型配置失败: {e}")
            raise RuntimeError(f'获取模型配置失败: {e}') from e

        if not model_config:
            raise ValueError('未配置激活的 LLM 模型')
        model_config = dict(model_config)

        # 远程模型出网前整段脱敏（红线：聊天样本含原文与联系人姓名，
        # 失败即阻断，绝不降级发原文；本地模型豁免）
        from .rag.config import is_remote_llm_model
        if is_remote_llm_model(model_config):
            try:
                from .privacy_redactor import PrivacyRedactor
                redacted = PrivacyRedactor(conn).redact(
                    user_prompt,
                    account_wxid=self._resolve_account_wxid(account_wxid),
                    conversation_id=None,
                    source_table="contact_profiler",
                ).redacted_text
            except Exception as redact_e:
                raise RuntimeError(f'脱敏失败，按红线阻断画像远程调用: {redact_e}') from redact_e
            user_prompt = redacted

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
        # 画像 JSON 大小不随聊天量增长，输出额度不随 prompt 无限放大，
        # 避免超出模型 max_tokens 上限导致请求被拒。
        dynamic_max_tokens = min(dynamic_max_tokens, 8192)
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
            'response_format': {'type': 'json_object'},
        }
        # 交互调用快速模式：思考模型附 reasoning_effort:"low" 兜底（含
        # glm-4.5+ 特例；压低思考量，避免命中「思考耗尽输出预算」），模型级 extra_body 优先
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
            log_prefix='[ContactProfiler]',
        )
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
        profile: dict, sample_count: int, features: dict, account_wxid: str,
        window_kind: str = 'rolling', window_from: int = 0, window_to: int = 0,
        budget_level: str = 'medium', origin: str = '',
    ):
        """保存画像快照（窗口键多快照共存），写后按窗口分组裁剪上限"""
        try:
            self._ensure_table(conn)

            now = int(time.time())
            # 历史窗快照是存档品：不参与 7 天 TTL，仅由数量上限裁剪
            expires_at = now + (365 * 86400 if window_kind == 'custom' else PROFILE_TTL)
            conn.execute(
                'INSERT OR REPLACE INTO contact_profiles '
                '(account_wxid, display_name, conversation_id, window_kind, window_from, '
                'window_to, budget_level, origin, schema_version, profile_json, '
                'features_snapshot, message_sample_count, token_usage, created_at, expires_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    account_wxid,
                    display_name,
                    conversation_id,
                    window_kind,
                    int(window_from),
                    int(window_to),
                    budget_level,
                    origin,
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
                'DELETE FROM contact_profiles '
                'WHERE account_wxid = ? AND display_name = ? AND window_kind = ? '
                'AND id NOT IN ('
                '  SELECT id FROM contact_profiles '
                '  WHERE account_wxid = ? AND display_name = ? AND window_kind = ? '
                '  ORDER BY created_at DESC, id DESC LIMIT ?'
                ')',
                (account_wxid, display_name, window_kind,
                 account_wxid, display_name, window_kind, keep),
            )
            conn.commit()
            _print(f"[ContactProfiler] 画像快照已缓存（{window_kind} 窗口分组保留最近 {keep} 条）")
        except Exception as e:
            _print(f"[ContactProfiler] ⚠️ 缓存保存失败: {e}")

    def _ensure_table(self, conn):
        """确保缓存表存在（快照结构：窗口键多快照 + 结构版本列；旧结构 DROP 重建不迁移）"""
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'contact_profiles'"
        ).fetchone()
        if exists:
            cols = {row[1] for row in conn.execute('PRAGMA table_info(contact_profiles)')}
            if 'window_kind' in cols and 'schema_version' in cols and 'origin' in cols:
                return  # 已是当前快照结构，零 DDL
            _print("[ContactProfiler] 旧结构画像表，DROP 重建为快照结构，不迁移")
            conn.execute('DROP TABLE contact_profiles')
            conn.commit()
        conn.execute(f'''
            CREATE TABLE IF NOT EXISTS contact_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_wxid TEXT NOT NULL,
                display_name TEXT NOT NULL,
                conversation_id INTEGER,
                window_kind TEXT NOT NULL DEFAULT 'rolling',
                window_from INTEGER NOT NULL DEFAULT 0,
                window_to INTEGER NOT NULL DEFAULT 0,
                budget_level TEXT NOT NULL DEFAULT 'medium',
                origin TEXT NOT NULL DEFAULT '',
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
