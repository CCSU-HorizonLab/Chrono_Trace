"""P1.2 contact-scoped preference policy shadow derivation.

把 rag_facts 中 subject=对方的偏好类事实聚合成槽位级策略行
（slot = 同主题聚类，代表=最高置信），ADD-only 版本链写入
rag_contact_preferences。与关系状态（rag_relationship_state）
分槽：关系策略管阶段/边界/沟通，本模块管喜欢/讨厌/忌口——
"怎么做/避免什么"的最小安全摘要。

纪律（对应改造计划 P1.2）：
- 只读非敏感、active/enabled、subject=对方的事实——把"用户自己
  的习惯"误当"对方偏好"是本层最大风险，schema 层面强制排除。
- 影子写入 ADD-only，evidence_hash 未变化不产生新版本。
- 不改变原 fact 的 sensitivity 与门控；敏感事实仅跳过。
- 开关复用 rag_relationship_policy_shadow_enabled（关系策略链路
  含偏好策略；关闭即全链路停用，回滚单一开关）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
import math
import time
from typing import Any

from .config import load_rag_settings
from .store import RagStore

logger = logging.getLogger(__name__)

# 偏好类 kind（长短名并认，同 T3 口径）；boundary 留在关系策略槽不重复注入
PREFERENCE_KINDS = {"preference", "preference_like", "food_or_place"}
AVOID_KINDS = {"preference_dislike"}
SLOT_KIND_BY_RAW = {kind: "preference" for kind in PREFERENCE_KINDS}
SLOT_KIND_BY_RAW.update({kind: "avoid" for kind in AVOID_KINDS})

SUBJECT_CONTACT = "对方"
# 聚槽相似度阈值与上限：同主题事实合并为单一策略，防止碎片重复
SLOT_SIMILARITY_THRESHOLD = 0.72
MAX_SLOTS = 10
SLOT_SUMMARY_MAX_CHARS = 120


@dataclass
class PreferenceSlotDraft:
    slot_key: str
    slot_kind: str
    summary: str
    evidence_fact_ids: list[int] = field(default_factory=list)
    evidence_message_ids: list[int] = field(default_factory=list)
    support_count: int = 1
    confidence: float = 0.0


def derive_contact_preferences(
    *,
    facts: list[dict[str, Any]],
    embedding_service: Any = None,
) -> list[PreferenceSlotDraft]:
    """Aggregate contact-side preference facts into topic slots.

    facts 为 rag_store.list_facts 输出（active+enabled）。embedding 不可
    用时退化为"每事实一槽"（仍可用，仅不聚合同主题重复表达）。
    """
    candidates = [
        fact for fact in facts
        if str(fact.get("subject") or "").strip() == SUBJECT_CONTACT
        and str(fact.get("kind") or "").strip().lower() in SLOT_KIND_BY_RAW
        and str(fact.get("sensitivity") or "normal") != "sensitive"
    ]
    # 槽位代表必须过质量门（宽松模式）：已隔离质量的碎片（"没那么想要"
    # 类）不因聚槽而洗白成策略。词表驱动的拦截随 fact_quality_patterns
    # 演化，此处不新增语言规则。
    from .fact_quality import fact_quality_reason

    candidates = [
        fact for fact in candidates
        if fact_quality_reason(
            str(fact.get("kind") or ""), fact.get("content"), require_kind_signal=False
        )
        is None
    ]
    if not candidates:
        return []
    candidates.sort(key=lambda f: (-float(f.get("confidence") or 0.0), -int(f.get("id") or 0)))

    vectors: dict[int, list[float]] = {}
    if embedding_service is not None:
        try:
            embedded = embedding_service.embed_texts(
                [str(fact.get("content") or "") for fact in candidates]
            )
            if len(embedded) == len(candidates):
                vectors = {
                    int(fact.get("id") or 0): vec for fact, vec in zip(candidates, embedded)
                }
        except Exception as exc:
            logger.debug("[ContactPreference] slot embedding unavailable: %s", exc)
            vectors = {}

    slots: list[dict[str, Any]] = []
    for fact in candidates:
        fact_id = int(fact.get("id") or 0)
        vector = vectors.get(fact_id) or []
        target = None
        if vector:
            for slot in slots:
                similarity = _cosine(vector, slot["vector"])
                if similarity >= SLOT_SIMILARITY_THRESHOLD:
                    target = slot
                    break
        if target is None:
            if len(slots) >= MAX_SLOTS:
                continue
            slots.append(
                {
                    "representative": fact,
                    "vector": vector,
                    "members": [fact],
                }
            )
        else:
            target["members"].append(fact)

    drafts: list[PreferenceSlotDraft] = []
    for slot in slots:
        representative = slot["representative"]
        members = slot["members"]
        summary = str(representative.get("content") or "").split("\n")[0].strip()
        summary = summary[:SLOT_SUMMARY_MAX_CHARS]
        if not summary:
            continue
        evidence_fact_ids = sorted({int(f.get("id") or 0) for f in members if f.get("id")})
        evidence_message_ids = sorted({
            int(mid)
            for f in members
            for mid in _parse_evidence_ids(f.get("evidence_message_ids_json"))
        })
        drafts.append(
            PreferenceSlotDraft(
                slot_key=f"{SLOT_KIND_BY_RAW.get(str(representative.get('kind') or '').strip().lower(), 'preference')}:{int(representative.get('id') or 0)}",
                slot_kind=SLOT_KIND_BY_RAW.get(
                    str(representative.get("kind") or "").strip().lower(), "preference"
                ),
                summary=summary,
                evidence_fact_ids=evidence_fact_ids,
                evidence_message_ids=evidence_message_ids,
                support_count=len(members),
                confidence=round(
                    sum(float(f.get("confidence") or 0.0) for f in members) / len(members), 4
                ),
            )
        )
    return drafts


def _slot_evidence_hash(draft: PreferenceSlotDraft) -> str:
    digest = hashlib.sha256()
    digest.update(draft.slot_key.encode("utf-8"))
    digest.update(b"\x1f")
    digest.update(draft.summary.encode("utf-8"))
    digest.update(b"\x1f")
    digest.update(",".join(str(i) for i in sorted(draft.evidence_fact_ids)).encode("utf-8"))
    return digest.hexdigest()


def refresh_contact_preferences_shadow(
    store: RagStore,
    *,
    account_wxid: str,
    conversation_id: int,
    embedding_service: Any = None,
    touched_fact_id: int | None = None,
) -> dict[str, Any]:
    """One-shot shadow refresh; guarded by rag_relationship_policy_shadow_enabled.

    生命周期语义（全量对比）：本轮派生的槽集合是当前真相——
    - 同槽同证据 hash → 不产生新版本；
    - 同槽新证据 → 关旧版本、追加新行（supersedes 链）；
    - 本轮消失的槽（证据被禁用/融合退役）→ 关闭活跃行，读侧不再注入，
      行保留审计（ADD-only：不删行）。
    touched_fact_id 用于反馈触发的定向刷新：该事实不在任何活跃槽证据
    中时直接跳过，避免无 embedding 的退化派生拆散已聚好的槽。
    派生为空（无对方偏好事实）同样关闭全部活跃槽。
    """
    if not load_rag_settings().get("rag_relationship_policy_shadow_enabled"):
        return {"ok": True, "skipped": "disabled"}
    try:
        if touched_fact_id is not None:
            referenced = False
            for row in store.list_contact_preferences(account_wxid, conversation_id):
                if touched_fact_id in _parse_evidence_ids(row.get("evidence_fact_ids_json")):
                    referenced = True
                    break
            if not referenced:
                return {"ok": True, "skipped": "fact_not_referenced"}

        facts = store.list_facts(account_wxid, conversation_id)
        drafts = derive_contact_preferences(
            facts=facts, embedding_service=embedding_service
        )
        written = 0
        active_slot_keys = set()
        for draft in drafts:
            result = store.upsert_contact_preference(
                account_wxid=account_wxid,
                conversation_id=conversation_id,
                slot_key=draft.slot_key,
                slot_kind=draft.slot_kind,
                summary=draft.summary,
                evidence_hash=_slot_evidence_hash(draft),
                evidence_fact_ids=draft.evidence_fact_ids,
                evidence_message_ids=draft.evidence_message_ids,
                support_count=draft.support_count,
                confidence=draft.confidence,
            )
            active_slot_keys.add(draft.slot_key)
            if result.get("changed"):
                written += 1
        retired = _retire_absent_slots(
            store, account_wxid, conversation_id, active_slot_keys
        )
        logger.debug(
            "[ContactPreference] conv=%s slots=%s written=%s retired=%s",
            conversation_id,
            len(drafts),
            written,
            retired,
        )
        return {"ok": True, "slots": len(drafts), "written": written, "retired": retired}
    except Exception as exc:
        logger.warning("[ContactPreference] shadow refresh failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _retire_absent_slots(
    store: RagStore,
    account_wxid: str,
    conversation_id: int,
    active_slot_keys: set[str],
) -> int:
    """Close active slots absent from this round's derivation (keep audit rows)."""
    rows = store.conn.execute(
        """
        SELECT id, slot_key FROM rag_contact_preferences
        WHERE account_wxid = ? AND conversation_id = ? AND valid_to IS NULL
        """,
        (account_wxid, int(conversation_id)),
    ).fetchall()
    now = int(time.time())
    retired = 0
    for row in rows:
        if str(row["slot_key"]) not in active_slot_keys:
            store.conn.execute(
                "UPDATE rag_contact_preferences SET valid_to = ?, updated_at = ? WHERE id = ?",
                (now, now, int(row["id"])),
            )
            retired += 1
    return retired


def _parse_evidence_ids(raw: Any) -> list[int]:
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [int(v) for v in values if isinstance(v, int) and v > 0]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(float(a[i]) * float(b[i]) for i in range(size))
    norm_a = math.sqrt(sum(float(x) ** 2 for x in a[:size]))
    norm_b = math.sqrt(sum(float(x) ** 2 for x in b[:size]))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)
