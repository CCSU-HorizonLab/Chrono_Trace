"""G1 统一联系人上下文:所有生成入口共用的范围解析与上下文装配。

设计约束(上游文档 docs/goals/g1-generation-goal.md 第三节 G1):

- 每次生成必须绑定稳定的 ``account_wxid + conversation_id``;显示名只用于展示
  与兼容解析,同名歧义时绝不自动选取。
- 缺失联系人范围时安全降级为通用帮助:剥离画像/历史记忆注入,RAG 走既有
  ``missing_scope`` 跳过路径,但生成本身不失败。
- 自动、手动、开场、全自动入口使用同一装配函数,保证同一联系人在不同入口
  的 fact / profile / policy 来源一致。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 范围状态:ok 之外都视为"缺失范围",走安全降级。
SCOPE_OK = "ok"
SCOPE_MISSING = "missing_scope"
SCOPE_AMBIGUOUS = "ambiguous_contact"
SCOPE_INVALID_CONVERSATION = "invalid_conversation"

_SCOPE_HISTORICAL_KEYS = (
    "contact_profile",
    "self_profile",
    "_contact_profile_stale",
    "_self_profile_stale",
    "relevant_memories",
    "relationship_policy",
    "contact_preferences",
    "self_profile_features",
    "affinity_result",
)


def new_request_id() -> str:
    """每次生成请求的短 uuid,用于 request_id → suggestion_id → retrieval_log_id 审计链。"""
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True)
class GenerationScope:
    """一次生成请求的联系人范围解析结果。"""

    account_wxid: str = ""
    conversation_id: int | None = None
    display_name: str = ""
    username: str = ""
    entrypoint: str = ""
    request_id: str = field(default_factory=new_request_id)
    status: str = SCOPE_MISSING
    reason: str = ""

    @property
    def valid(self) -> bool:
        return self.status == SCOPE_OK and bool(self.account_wxid) and self.conversation_id is not None


def _normalize_conversation_id(raw: Any) -> int | None:
    try:
        if raw is None or raw == "":
            return None
        return int(raw)
    except (TypeError, ValueError):
        return None


def _query_conversation_rows(
    account_wxid: str,
    *,
    conversation_id: int | None = None,
    display_name: str = "",
    username: str = "",
) -> list[dict[str, Any]]:
    """按账号查询会话行;失败时抛异常由调用方降级。"""
    from ...db.connection import get_db

    if conversation_id is not None:
        rows = get_db().execute(
            """
            SELECT id, display_name, username
            FROM conversations
            WHERE account_wxid = ? AND id = ? AND is_deleted = 0
            """,
            (account_wxid, conversation_id),
        ).fetchall()
        return [dict(row) for row in rows]

    clauses: list[str] = []
    params: list[Any] = []
    if username:
        clauses.append("username = ?")
        params.append(username)
    if display_name:
        clauses.append("display_name = ?")
        params.append(display_name)
    if not clauses:
        return []
    rows = get_db().execute(
        f"""
        SELECT id, display_name, username
        FROM conversations
        WHERE account_wxid = ? AND is_deleted = 0 AND ({" OR ".join(clauses)})
        """,
        (account_wxid, *params),
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_generation_scope(
    *,
    account_wxid: str = "",
    conversation_id: int | str | None = None,
    display_name: str = "",
    username: str = "",
    entrypoint: str = "",
    request_id: str = "",
) -> GenerationScope:
    """解析并校验生成请求的联系人范围。

    优先级:显式 conversation_id(必须属于当前账号)> username(唯一键)>
    display_name(唯一命中才可用)。同名多命中返回 ``ambiguous_contact``,
    不自动选取。
    """
    account = str(account_wxid or "").strip()
    display = str(display_name or "").strip()
    user = str(username or "").strip()
    entry = str(entrypoint or "").strip()
    request = str(request_id or "").strip() or new_request_id()
    explicit_conversation_id = _normalize_conversation_id(conversation_id)

    def _scope(status: str, reason: str, **overrides: Any) -> GenerationScope:
        return GenerationScope(
            account_wxid=account,
            conversation_id=overrides.get("conversation_id"),
            display_name=display or str(overrides.get("display_name") or ""),
            username=user or str(overrides.get("username") or ""),
            entrypoint=entry,
            request_id=request,
            status=status,
            reason=reason,
        )

    if not account:
        return _scope(SCOPE_MISSING, "no_account_scope")

    try:
        if explicit_conversation_id is not None:
            rows = _query_conversation_rows(account, conversation_id=explicit_conversation_id)
            if len(rows) == 1:
                row = rows[0]
                # 审核返工 1:校验成功后以数据库身份为准——调用方传错的
                # display_name 不得继续用于画像/记忆读取(串用风险)。
                return GenerationScope(
                    account_wxid=account,
                    conversation_id=int(row["id"]),
                    display_name=str(row.get("display_name") or "") or display,
                    username=str(row.get("username") or "") or user,
                    entrypoint=entry,
                    request_id=request,
                    status=SCOPE_OK,
                    reason="explicit_conversation_id",
                )
            # 显式给出但查不到(或不属于当前账号):不得回退显示名猜一个。
            return _scope(
                SCOPE_INVALID_CONVERSATION,
                "conversation_not_owned_or_missing",
                conversation_id=explicit_conversation_id,
            )

        if not display and not user:
            return _scope(SCOPE_MISSING, "no_contact_scope")

        rows = _query_conversation_rows(account, display_name=display, username=user)
        distinct_ids = {int(row["id"]) for row in rows}
        if not rows:
            return _scope(SCOPE_MISSING, "no_matching_contact")
        if len(distinct_ids) > 1:
            # username 唯一命中优先;纯显示名多命中视为歧义。
            username_rows = [row for row in rows if user and str(row.get("username") or "") == user]
            if len(username_rows) == 1:
                row = username_rows[0]
                return GenerationScope(
                    account_wxid=account,
                    conversation_id=int(row["id"]),
                    display_name=str(row.get("display_name") or "") or display,
                    username=user,
                    entrypoint=entry,
                    request_id=request,
                    status=SCOPE_OK,
                    reason="username_unique_match",
                )
            return _scope(SCOPE_AMBIGUOUS, f"ambiguous_display_name_matches={len(distinct_ids)}")
        row = rows[0]
        return GenerationScope(
            account_wxid=account,
            conversation_id=int(row["id"]),
            display_name=str(row.get("display_name") or "") or display,
            username=str(row.get("username") or "") or user,
            entrypoint=entry,
            request_id=request,
            status=SCOPE_OK,
            reason="unique_contact_match",
        )
    except Exception as exc:
        logger.warning("[GenerationScope] 解析失败,安全降级: %s", exc)
        return _scope(SCOPE_MISSING, "scope_lookup_failed")


def apply_generation_scope(context: dict[str, Any], scope: GenerationScope) -> None:
    """把解析后的范围写入 context;缺失时执行安全降级。"""

    context["_generation_request_id"] = scope.request_id
    context["_generation_entrypoint"] = scope.entrypoint
    context["_generation_scope_status"] = scope.status
    context["_generation_scope_reason"] = scope.reason

    if scope.account_wxid:
        context["account_wxid"] = scope.account_wxid
    if scope.valid:
        context["conversation_id"] = scope.conversation_id
        if scope.display_name:
            # 数据库身份覆盖调用方传入的显示名(审核返工 1)
            context["display_name"] = scope.display_name
        context.pop("_generation_scope_missing", None)
        return

    # 缺失范围:降级为通用帮助。清掉所有按联系人键控的历史知识,
    # 防止"画像属于当前联系人,RAG 却没有联系人范围"的错配注入。
    context["account_wxid"] = scope.account_wxid
    context.pop("conversation_id", None)
    context.pop("_rag_conversation_id", None)
    context["_generation_scope_missing"] = True
    for key in _SCOPE_HISTORICAL_KEYS:
        context.pop(key, None)
    logger.debug(
        "[GenerationScope] 安全降级 entrypoint=%s status=%s reason=%s",
        scope.entrypoint,
        scope.status,
        scope.reason,
    )


def _display_name_unique_for_account(account_wxid: str, display_name: str, except_conversation_id: int | None) -> bool:
    """显示名在账号内是否唯一(排除当前会话自身)。

    contact_profiles / session_threads 只按 account+display_name 键控,
    同名联系人的画像与线程记忆天然歧义——唯一时才允许读取。
    """
    if not account_wxid or not display_name:
        return False
    try:
        from ...db.connection import get_db

        rows = get_db().execute(
            """
            SELECT COUNT(DISTINCT id) AS n
            FROM conversations
            WHERE account_wxid = ? AND display_name = ? AND is_deleted = 0
              AND id != COALESCE(?, -1)
            """,
            (account_wxid, display_name, except_conversation_id),
        ).fetchone()
        return int(rows["n"]) == 0
    except Exception as exc:
        logger.debug("[GenerationScope] 显示名唯一性检查失败,按不唯一处理: %s", exc)
        return False


def assemble_generation_context(
    ctx: dict[str, Any],
    *,
    entrypoint: str,
    account_wxid: str = "",
    conversation_id: int | str | None = None,
    display_name: str = "",
    username: str = "",
    batch_id: str = "",
    emotion_summary: dict[str, Any] | None = None,
    recent_limit: int = 50,
    renew_stale_profiles: Callable[[str, str], None] | None = None,
    include_session_memories: bool = True,
    prewarm_rag_index: bool = False,
) -> GenerationScope:
    """统一上下文装配:范围 → 情绪 → 最近消息 → 双画像 → 历史增强 → 会话记忆。

    所有生成入口(手动/半自动/全自动/开场)共用本函数;scope 缺失时仍会
    装配当前窗口上下文(最近消息、情绪),但按联系人键控的历史知识一律不注入。
    """
    # 进程级预热:任何入口的第一次装配就触发 embedding 后台加载,
    # 消除首查冷窗口(事实因向量分缺失被门禁丢弃的问题)。
    try:
        from .rag.embedding import kick_background_prewarm

        kick_background_prewarm()
    except Exception:
        pass

    scope = resolve_generation_scope(
        account_wxid=account_wxid,
        conversation_id=conversation_id,
        display_name=display_name,
        username=username,
        entrypoint=entrypoint,
    )
    apply_generation_scope(ctx, scope)

    if emotion_summary is not None and "emotion_summary" not in ctx:
        ctx["emotion_summary"] = emotion_summary

    # 最近消息来自当前监控窗口(batch),属于"当前上下文"而非历史知识,
    # 范围缺失时保留——这是安全降级后模型唯一可用的对话依据。
    if "recent_messages" not in ctx and batch_id and scope.account_wxid:
        try:
            from .message_query import get_messages_with_sentiment

            ctx["recent_messages"] = get_messages_with_sentiment(
                batch_id,
                recent_limit,
                account_wxid=scope.account_wxid,
            )
        except Exception as exc:
            logger.warning("[GenerationContext] 获取最近消息失败: %s", exc)

    # 画像与历史增强只在范围有效时注入(审核返工 1):
    # - contact_profiles / session_threads 按 account+display_name 键控,
    #   同名联系人的数据天然歧义 → 显示名不唯一时跳过;
    # - self_profiles 带 conversation_id → 与本次范围不一致时丢弃,
    #   防止拿到别的会话的自我画像/量化风格;
    # - 好感/预处理缓存按 conversation_id 读取,以解析出的会话为准,
    #   不再依赖画像缓存里带的会话号。
    self_profile_cache = None
    if scope.valid and scope.display_name and "contact_profile" not in ctx:
        name_unique = _display_name_unique_for_account(
            scope.account_wxid, scope.display_name, scope.conversation_id
        )
        if not name_unique:
            logger.debug(
                "[GenerationContext] 显示名在账号内不唯一,跳过画像/线程记忆(conversation=%s)",
                scope.conversation_id,
            )
        try:
            from .contact_profiler import ContactProfiler
            from .self_profiler import SelfProfiler

            if name_unique:
                c_cached = ContactProfiler().get_profile(scope.display_name, scope.account_wxid)
                if c_cached:
                    ctx["contact_profile"] = c_cached["profile"]
                    if c_cached.get("expired"):
                        ctx["_contact_profile_stale"] = True
                        if renew_stale_profiles:
                            renew_stale_profiles(scope.display_name, scope.account_wxid)

                if "self_profile" not in ctx:
                    s_cached = SelfProfiler().get_profile(scope.display_name, scope.account_wxid)
                    if s_cached and int(s_cached.get("conversation_id") or 0) == int(scope.conversation_id or 0):
                        ctx["self_profile"] = s_cached["profile"]
                        self_profile_cache = s_cached
                        if s_cached.get("expired"):
                            ctx["_self_profile_stale"] = True
                            if renew_stale_profiles:
                                renew_stale_profiles(scope.display_name, scope.account_wxid)
                    elif s_cached:
                        logger.debug(
                            "[GenerationContext] 自我画像会话不匹配(profile=%s scope=%s),已丢弃",
                            s_cached.get("conversation_id"), scope.conversation_id,
                        )
        except Exception as exc:
            logger.warning("[GenerationContext] 提取画像失败: %s", exc)

    try:
        from .historical_context import augment_context_with_historical_data

        augment_context_with_historical_data(
            ctx,
            self_profile_cache=self_profile_cache,
            conversation_id=scope.conversation_id if scope.valid else None,
        )
    except Exception as exc:
        logger.warning("[GenerationContext] 构建 historical_context 失败: %s", exc)

    if (
        scope.valid
        and scope.display_name
        and include_session_memories
        and "relevant_memories" not in ctx
        and _display_name_unique_for_account(scope.account_wxid, scope.display_name, scope.conversation_id)
    ):
        try:
            from .session_thread_service import SessionThreadService

            memories = SessionThreadService().retrieve_relevant_memories(
                scope.display_name,
                ctx.get("recent_messages") or [],
                account_wxid=scope.account_wxid,
            )
            if memories:
                ctx["relevant_memories"] = memories
        except Exception as exc:
            logger.warning("[GenerationContext] 会话线程记忆检索失败: %s", exc)

    if scope.valid and prewarm_rag_index:
        try:
            from .rag.indexer import RagIndexer

            RagIndexer().ensure_contact_index(
                account_wxid=scope.account_wxid,
                conversation_id=int(scope.conversation_id or 0),
            )
        except Exception as exc:
            logger.debug("[GenerationContext] RAG 预热跳过: %s", exc)

    return scope
