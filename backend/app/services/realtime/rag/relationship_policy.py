"""P1.1 contact-scoped relationship state shadow derivation.

把 contact_profiler 的 LLM 画像与 rag_facts（校准后置信度）派生为结构化
关系状态影子行（stage / closeness_band / initiative_pattern / boundary）。

纪律（对应改造计划 P1.1）：
- 只读非敏感、active/enabled 事实；sensitive 事实仅计 ID 不取内容。
- 影子写入 ADD-only，evidence_hash 未变化不产生新版本。
- 本模块只做影子，不参与任何读侧注入（P1.3 另行接通并门控）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
from typing import Any

from .config import load_rag_settings
from .store import RagStore

logger = logging.getLogger(__name__)

BOUNDARY_KINDS = {
    # 原型路径长名
    "relationship_boundary",
    "preference_dislike",
    # LLM 结构化抽取短名（normalize_fact_kind 规范化后）
    "boundary",
}
EVIDENCE_KINDS = BOUNDARY_KINDS | {
    "preference_like",
    "preference",
    "personal_profile",
    "personal_fact",
    "relation_state",
    "relationship_state",
}
# 边界聚合的主体分组：subject 字段区分"对方的边界"与"我的边界"
BOUNDARY_SUBJECT_LABELS = {"对方": "对方的边界", "我": "我的边界"}
# 摘要中各主体的条数上限（对方优先——建议场景更依赖对方的雷区）
BOUNDARY_SUBJECT_LIMITS = {"对方": 2, "我": 1}

INITIATIVE_OTHER_DOMINANT = "对方更主动"
INITIATIVE_SELF_DOMINANT = "我更主动"
INITIATIVE_BALANCED = "双方均衡"


@dataclass
class RelationshipStateDraft:
    stage: str
    closeness_band: str
    initiative_pattern: str
    boundary_summary: str = ""
    communication_tips: str = ""
    relationship_note: str = ""
    evidence_fact_ids: list[int] = field(default_factory=list)
    evidence_message_ids: list[int] = field(default_factory=list)
    confidence: float = 0.0
    summary_method: str = "derived_shadow"


def derive_relationship_state(
    *,
    profile: dict[str, Any] | None,
    features_snapshot: dict[str, Any] | None,
    facts: list[dict[str, Any]],
    message_count: int,
) -> RelationshipStateDraft | None:
    """Derive a structured relationship snapshot from profile + calibrated facts.

    profile / features_snapshot 来自 contact_profiles 缓存；facts 为
    rag_store.list_facts 输出（含 confidence、kind、sensitivity）。
    无画像且无事实时返回 None（不生成空影子行）。
    """
    profile = profile or {}
    features_snapshot = features_snapshot or {}

    initiative = features_snapshot.get("initiative") or {}
    total_sessions = int(initiative.get("total_sessions") or 0)
    other_initiated = int(initiative.get("other_initiated") or 0)

    if total_sessions >= 5 and other_initiated / total_sessions >= 0.6:
        initiative_pattern = INITIATIVE_OTHER_DOMINANT
    elif total_sessions >= 5 and other_initiated / total_sessions <= 0.4:
        initiative_pattern = INITIATIVE_SELF_DOMINANT
    elif total_sessions >= 5:
        initiative_pattern = INITIATIVE_BALANCED
    else:
        initiative_pattern = "样本不足"

    if message_count >= 2000:
        closeness_band = "high"
    elif message_count >= 300:
        closeness_band = "medium"
    else:
        closeness_band = "low"

    band_label = {"high": "高频互动", "medium": "常规往来", "low": "低频联系"}.get(
        closeness_band, closeness_band
    )
    stage = f"{band_label}/{initiative_pattern}"

    boundary_facts = [
        fact for fact in facts
        if str(fact.get("kind") or "").strip().lower() in BOUNDARY_KINDS
        and str(fact.get("sensitivity") or "normal") != "sensitive"
    ]
    boundary_summary = _summarize_boundaries_by_subject(boundary_facts)

    evidence_facts = [
        fact for fact in facts
        if str(fact.get("kind") or "").strip().lower() in EVIDENCE_KINDS
    ][:20]
    evidence_fact_ids = [int(fact["id"]) for fact in evidence_facts if fact.get("id")]
    evidence_message_ids = sorted({
        int(mid)
        for fact in evidence_facts
        for mid in _parse_evidence_ids(fact.get("evidence_message_ids_json"))
    })[:40]

    if evidence_facts:
        confidence = round(
            sum(float(fact.get("confidence") or 0.0) for fact in evidence_facts)
            / len(evidence_facts),
            4,
        )
        summary_method = "derived_shadow_profile_and_facts"
    else:
        confidence = 0.5
        summary_method = "derived_shadow_profile_only"

    if not profile and not evidence_facts:
        return None

    return RelationshipStateDraft(
        stage=stage,
        closeness_band=closeness_band,
        initiative_pattern=initiative_pattern,
        boundary_summary=boundary_summary,
        communication_tips=str(profile.get("communication_tips") or ""),
        relationship_note=str(profile.get("relationship_note") or ""),
        evidence_fact_ids=evidence_fact_ids,
        evidence_message_ids=evidence_message_ids,
        confidence=confidence,
        summary_method=summary_method,
    )


def _summarize_boundaries_by_subject(boundary_facts: list[dict[str, Any]]) -> str:
    """按 subject 分组聚合边界，避免把"我的边界"当成"对方的边界"输出。

    事实表的 subject 在原型路径（发送方标签）与 LLM 抽取路径（提示词
    契约）中一致为 "我"/"对方"；未知主体归入其原文标签，不吞不猜。
    """
    grouped: dict[str, list[str]] = {}
    for fact in boundary_facts:
        subject = str(fact.get("subject") or "").strip() or "对方"
        content = str(fact.get("content") or "").split("\n")[0].strip()
        if content:
            grouped.setdefault(subject, []).append(content)

    parts: list[str] = []
    # 对方优先；未知主体排在已知主体之后，各自独立成段
    ordered = sorted(
        grouped.items(),
        key=lambda item: (item[0] != "对方", item[0] != "我", item[0]),
    )
    for subject, contents in ordered:
        limit = BOUNDARY_SUBJECT_LIMITS.get(subject, 1)
        label = BOUNDARY_SUBJECT_LABELS.get(subject, f"{subject}的边界")
        parts.append(label + "：" + "；".join(contents[:limit]))
    return "；".join(parts)


def _parse_evidence_ids(raw: Any) -> list[int]:
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [int(v) for v in values if isinstance(v, int) and v > 0]


def _evidence_hash(
    profile: dict[str, Any] | None,
    features_snapshot: dict[str, Any] | None,
    evidence_fact_ids: list[int],
) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(profile or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    digest.update(b"\x1f")
    digest.update(
        json.dumps(features_snapshot or {}, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
    )
    digest.update(b"\x1f")
    digest.update(",".join(str(i) for i in sorted(evidence_fact_ids)).encode("utf-8"))
    return digest.hexdigest()


def refresh_relationship_state_shadow(
    store: RagStore,
    *,
    account_wxid: str,
    conversation_id: int,
    display_name: str,
) -> dict[str, Any]:
    """One-shot shadow refresh; guarded by rag_relationship_policy_shadow_enabled.

    画像缓存缺失或派生为 None 时返回 skipped，不写影子、不抛异常——
    影子层失败绝不影响索引主链路。
    """
    if not load_rag_settings().get("rag_relationship_policy_shadow_enabled"):
        return {"ok": True, "skipped": "disabled"}
    try:
        profile_cache = _load_profile_cache(account_wxid, display_name, conn=store.conn)
        facts = store.list_facts(account_wxid, conversation_id)
        # 亲密度用真实消息量（document_count 是切块后的文档数，会低估）
        message_count = _load_message_count(store, account_wxid, conversation_id)

        draft = derive_relationship_state(
            profile=profile_cache.get("profile") if profile_cache else None,
            features_snapshot=profile_cache.get("features_snapshot") if profile_cache else None,
            facts=facts,
            message_count=message_count,
        )
        if draft is None:
            return {"ok": True, "skipped": "no_profile_and_no_facts"}

        evidence_hash = _evidence_hash(
            profile_cache.get("profile") if profile_cache else None,
            profile_cache.get("features_snapshot") if profile_cache else None,
            draft.evidence_fact_ids,
        )
        result = store.upsert_relationship_state(
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            stage=draft.stage,
            closeness_band=draft.closeness_band,
            initiative_pattern=draft.initiative_pattern,
            boundary_summary=draft.boundary_summary,
            communication_tips=draft.communication_tips,
            relationship_note=draft.relationship_note,
            evidence_hash=evidence_hash,
            evidence_fact_ids=draft.evidence_fact_ids,
            evidence_message_ids=draft.evidence_message_ids,
            confidence=draft.confidence,
            summary_method=draft.summary_method,
        )
        store.conn.commit()
        logger.debug(
            "[RelationshipState] conv=%s changed=%s stage=%s confidence=%.2f",
            conversation_id,
            result.get("changed"),
            draft.stage,
            draft.confidence,
        )
        return result
    except Exception as exc:
        logger.warning("[RelationshipState] shadow refresh failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def refresh_after_fact_feedback(store: RagStore, fact_id: int, *, action: str = "inaccurate") -> dict[str, Any]:
    """用户纠错（不准确/忘记/还原）后刷新策略层并记录 P2.1 影子信号。

    真实库场景（5385）：用户标注不准确后旧 state 仍引用——刷新走
    refresh_relationship_state_shadow（受 shadow 开关保护、list_facts
    只取 active+enabled，禁用事实自动出证据集）。P2.1 信号：先回查
    该事实被哪些活跃策略引用（关系 state + 偏好槽），刷新后把结果
    写 rag_feedback_policy_signals——只记录不决策。任何异常只记日志，
    绝不阻塞反馈落库。
    """
    try:
        row = store.conn.execute(
            """
            SELECT account_wxid, conversation_id FROM rag_facts WHERE id = ?
            """,
            (int(fact_id),),
        ).fetchone()
        if row is None:
            return {"ok": False, "skipped": "fact_not_found"}
        account_wxid = str(row["account_wxid"] or "")
        conversation_id = int(row["conversation_id"] or 0)
        if not account_wxid or conversation_id <= 0:
            return {"ok": False, "skipped": "missing_scope"}

        # 回查引用该事实的活跃策略（信号审计用；restore 不需要前置引用）
        affected_policy_ids: list[int] = []
        if action != "restore":
            state = store.get_latest_relationship_state(account_wxid, conversation_id)
            if state and fact_id in _parse_evidence_ids(state.get("evidence_fact_ids_json")):
                affected_policy_ids.append(int(state["id"]))
            for pref in store.list_contact_preferences(account_wxid, conversation_id):
                if fact_id in _parse_evidence_ids(pref.get("evidence_fact_ids_json")):
                    affected_policy_ids.append(int(pref["id"]))

        display_name = ""
        try:
            conv = store.conn.execute(
                "SELECT display_name FROM conversations WHERE id = ? AND account_wxid = ?",
                (conversation_id, account_wxid),
            ).fetchone()
            display_name = str(conv["display_name"] or "") if conv else ""
        except Exception:
            display_name = ""
        result = refresh_relationship_state_shadow(
            store,
            account_wxid=account_wxid,
            conversation_id=conversation_id,
            display_name=display_name,
        )
        # 同步刷新对方偏好策略影子（P1.2 槽位级，剔除禁用事实同理）；
        # 单独捕获——偏好刷新失败不影响关系状态刷新结果
        try:
            from .contact_preference import refresh_contact_preferences_shadow

            # G4：纠错触发的定向刷新此前不带 embedding，derive 侧退化成
            # "每事实一槽"，会把索引轮聚好的槽拆散。这里复用本地 embedding
            # 服务聚槽；模型缺失/构造失败时保持降级派生并告警，不阻塞反馈。
            pref_embedding_service = None
            try:
                from .embedding import RagEmbeddingService

                pref_embedding_service = RagEmbeddingService()
            except Exception as emb_exc:
                logger.warning(
                    "[RelationshipState] preference embedding unavailable; "
                    "slots degrade to per-fact: %s",
                    emb_exc,
                )
            refresh_contact_preferences_shadow(
                store,
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                touched_fact_id=None if action == "restore" else int(fact_id),
                embedding_service=pref_embedding_service,
            )
        except Exception as pref_exc:
            logger.debug(
                "[RelationshipState] post-feedback preference refresh skipped: %s", pref_exc
            )
        if result.get("ok"):
            logger.info(
                "[RelationshipState] refreshed after fact feedback fact=%s conv=%s changed=%s",
                fact_id,
                conversation_id,
                result.get("changed"),
            )
        # P2.1 影子信号：反馈对策略层的实际影响，append-only
        try:
            store.record_feedback_policy_signal(
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                fact_id=int(fact_id),
                action=action,
                signal_kind="fact_feedback",
                affected_policy_ids=affected_policy_ids,
                outcome=(
                    result.get("skipped")
                    or ("refreshed" if result.get("changed") else "no_change")
                ),
                detail={"relationship_changed": bool(result.get("changed"))},
            )
        except Exception as signal_exc:
            logger.debug("[RelationshipState] feedback signal write skipped: %s", signal_exc)
        return result
    except Exception as exc:
        logger.warning("[RelationshipState] post-feedback refresh failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _load_profile_cache(
    account_wxid: str,
    display_name: str,
    conn: Any | None = None,
) -> dict[str, Any] | None:
    if not display_name:
        return None
    try:
        if conn is None:
            from ....db.connection import get_db

            conn = get_db()
        row = conn.execute(
            """
            SELECT profile_json, features_snapshot FROM contact_profiles
            WHERE account_wxid = ? AND display_name = ?
            ORDER BY id DESC LIMIT 1
            """,
            (account_wxid, display_name),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        profile = json.loads(row["profile_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        profile = {}
    try:
        features = json.loads(row["features_snapshot"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        features = {}
    return {"profile": profile, "features_snapshot": features}


def _load_message_count(store: RagStore, account_wxid: str, conversation_id: int) -> int:
    """Prefer conversations.message_count; fall back to index document count."""
    try:
        row = store.conn.execute(
            "SELECT message_count FROM conversations WHERE id = ? AND account_wxid = ?",
            (int(conversation_id), account_wxid),
        ).fetchone()
        if row and int(row["message_count"] or 0) > 0:
            return int(row["message_count"])
    except Exception:
        pass
    try:
        status = store.get_status(account_wxid, conversation_id) or {}
        return int(status.get("document_count") or 0)
    except Exception:
        return 0
