"""RAG 记忆管理（状态/重建/清空/回填/纠错）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import json
from typing import Any

logger = logging.getLogger(__name__)


class RagAdminApiMixin:
    """RAG 记忆管理（状态/重建/清空/回填/纠错）"""

    def get_rag_log_detail(self, log_id: int) -> dict[str, Any]:
        """Return what one retrieval log actually injected, for badge drill-down.

        只读、本地展示给用户本人；注入列表本身经过敏感门控，此处对
        sensitivity=sensitive 的行做深度防御过滤，绝不回传敏感原文。
        """
        try:
            from ...db.connection import get_db
            from ...services.realtime.rag.store import RagStore

            conn = get_db()
            store = RagStore(conn)

            row = conn.execute(
                "SELECT * FROM rag_retrieval_logs WHERE id = ?", (int(log_id),)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "log_not_found"}

            def _load_json_ids(raw: Any) -> list[int]:
                try:
                    values = json.loads(raw or "[]")
                except Exception:
                    return []
                ids: list[int] = []
                for value in values:
                    try:
                        parsed = int(value)
                    except (TypeError, ValueError):
                        continue
                    if parsed > 0:
                        ids.append(parsed)
                return ids

            fact_ids = _load_json_ids(row["fact_ids_json"])
            injected_ids = _load_json_ids(row["document_ids_json"])
            candidate_ids = _load_json_ids(row["candidate_ids_json"]) or injected_ids
            evidence_ids_all = _load_json_ids(row["evidence_ids_json"])

            # fact 与 document 是两张表的自增主键，数字可能撞号；必须用与
            # document_ids_json 同源同序的 selected_doc_types_json 区分类型，
            # 不能只靠 fact_ids_json 推断。
            try:
                selected_types = [str(t or "") for t in json.loads(row["selected_doc_types_json"] or "[]")]
            except Exception:
                selected_types = []
            if len(selected_types) == len(injected_ids):
                fact_ids = [
                    i for i, t in zip(injected_ids, selected_types) if t == "fact_memory"
                ]
                doc_ids = [
                    i for i, t in zip(injected_ids, selected_types) if t != "fact_memory"
                ]
            else:
                fact_id_set = set(fact_ids)
                fact_ids = [i for i in injected_ids if i in fact_id_set]
                doc_ids = [i for i in injected_ids if i not in fact_id_set]

            def _evidence_excerpts(evidence_ids: list[int], limit: int = 3) -> list[str]:
                if not evidence_ids:
                    return []
                placeholders = ",".join("?" for _ in evidence_ids)
                try:
                    rows = conn.execute(
                        f"SELECT CAST(content AS BLOB) AS content FROM messages WHERE id IN ({placeholders})",
                        evidence_ids,
                    ).fetchall()
                except Exception:
                    return []
                excerpts = []
                for r in rows[:limit]:
                    value = r[0]
                    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
                    text = " ".join(text.split())
                    if text:
                        excerpts.append(text[:120] + ("…" if len(text) > 120 else ""))
                return excerpts

            def _evidence_messages(evidence_ids: list[int], limit: int = 6) -> list[dict[str, Any]]:
                if not evidence_ids:
                    return []
                ids = [i for i in evidence_ids if i > 0][:limit]
                if not ids:
                    return []
                placeholders = ",".join("?" for _ in ids)
                try:
                    cols = {
                        r["name"]
                        for r in conn.execute("PRAGMA table_info(messages)").fetchall()
                    }
                    sender_col = "is_sender" if "is_sender" in cols else "0 AS is_sender"
                    time_col = (
                        "timestamp"
                        if "timestamp" in cols
                        else ("created_at" if "created_at" in cols else "0 AS timestamp")
                    )
                    rows = conn.execute(
                        f"""
                        SELECT id, {sender_col}, {time_col}, CAST(content AS BLOB) AS content
                        FROM messages
                        WHERE id IN ({placeholders})
                        ORDER BY {time_col} ASC, id ASC
                        """,
                        ids,
                    ).fetchall()
                    msgs: list[dict[str, Any]] = []
                    for msg_row in rows:
                        value = msg_row["content"]
                        text_val = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
                        text_val = " ".join(text_val.split())
                        if text_val:
                            ts_val = (
                                msg_row["timestamp"]
                                if "timestamp" in msg_row.keys()
                                else (msg_row["created_at"] if "created_at" in msg_row.keys() else 0)
                            )
                            msgs.append({
                                "id": int(msg_row["id"]),
                                "is_sender": bool(msg_row["is_sender"]),
                                "timestamp": int(ts_val or 0),
                                "text": text_val[:180] + ("…" if len(text_val) > 180 else ""),
                            })
                    return msgs
                except Exception:
                    return []

            injected_items: list[dict[str, Any]] = []

            # 事实条目（document_id 即 rag_facts.id）
            if fact_ids:
                placeholders = ",".join("?" for _ in fact_ids)
                fact_rows = conn.execute(
                    f"""
                    SELECT id, subject, kind, content, as_of, confidence, sensitivity,
                           enabled, evidence_message_ids_json
                    FROM rag_facts WHERE id IN ({placeholders})
                    """,
                    fact_ids,
                ).fetchall()
                feedback_map: dict[int, str] = {}
                try:
                    fb_rows = conn.execute(
                        f"""
                        SELECT fact_id, action FROM rag_fact_user_feedback
                        WHERE fact_id IN ({placeholders})
                        ORDER BY updated_at ASC, id ASC
                        """,
                        fact_ids,
                    ).fetchall()
                    for fbr in fb_rows:
                        feedback_map[int(fbr["fact_id"])] = str(fbr["action"] or "")
                except Exception:
                    pass
                for fr in fact_rows:
                    if str(fr["sensitivity"] or "normal") == "sensitive":
                        continue
                    evidence_ids = [
                        i for i in json.loads(fr["evidence_message_ids_json"] or "[]")
                        if isinstance(i, int)
                    ] if fr["evidence_message_ids_json"] else []
                    fid = int(fr["id"])
                    ev_msgs = _evidence_messages(evidence_ids)
                    injected_items.append(
                        {
                            "source": "fact",
                            "id": fid,
                            "doc_type": "fact_memory",
                            "content": fr["content"],
                            "subject": fr["subject"],
                            "kind": fr["kind"],
                            "as_of": fr["as_of"],
                            "confidence": fr["confidence"],
                            "sensitive": False,
                            "enabled": bool(fr["enabled"]),
                            "user_action": feedback_map.get(fid),
                            "evidence_messages": ev_msgs,
                            "evidence_excerpts": [m["text"] for m in ev_msgs[:3]] or _evidence_excerpts(evidence_ids),
                        }
                    )

            # 文档条目（shared_memory / dialogue_turn 等）
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                doc_rows = conn.execute(
                    f"""
                    SELECT id, doc_type, content, source_ts, sensitivity
                    FROM rag_documents WHERE id IN ({placeholders})
                    """,
                    doc_ids,
                ).fetchall()
                for dr in doc_rows:
                    if str(dr["sensitivity"] or "normal") == "sensitive":
                        continue
                    injected_items.append(
                        {
                            "source": "document",
                            "id": dr["id"],
                            "doc_type": dr["doc_type"],
                            "content": dr["content"],
                            "subject": None,
                            "kind": dr["doc_type"],
                            "as_of": dr["source_ts"],
                            "confidence": None,
                            "sensitive": False,
                            "enabled": True,
                            "evidence_messages": [],
                            "evidence_excerpts": [],
                        }
                    )

            order = {fact_id: idx for idx, fact_id in enumerate(injected_ids)}
            injected_items.sort(key=lambda item: order.get(item["id"], 10**9))

            log_conv_id = int(row["conversation_id"]) if "conversation_id" in row.keys() and row["conversation_id"] else 0
            log_account = str(row["account_wxid"] or "") if "account_wxid" in row.keys() else ""
            resolved_account = self._resolve_account_wxid(log_account)

            contact_avatar = ""
            if log_conv_id > 0:
                try:
                    conv_row = conn.execute(
                        "SELECT avatar_path FROM conversations WHERE id = ?",
                        (log_conv_id,),
                    ).fetchone()
                    if conv_row and conv_row["avatar_path"]:
                        contact_avatar = str(conv_row["avatar_path"] or "").strip()
                    if not contact_avatar:
                        c_row = conn.execute(
                            """
                            SELECT avatar_path FROM contacts
                            WHERE account_wxid = ? AND username = (SELECT username FROM conversations WHERE id = ?)
                            LIMIT 1
                            """,
                            (resolved_account, log_conv_id),
                        ).fetchone()
                        if c_row and c_row["avatar_path"]:
                            contact_avatar = str(c_row["avatar_path"] or "").strip()
                except Exception:
                    pass

            user_avatar = ""
            try:
                user_prof = self.get_current_user_profile(account_wxid=resolved_account)
                if user_prof.get("ok") and user_prof.get("profile"):
                    user_avatar = str(user_prof["profile"].get("avatar") or "").strip()
            except Exception:
                pass

            not_injected_ids = [i for i in candidate_ids if i not in set(injected_ids)]
            return {
                "ok": True,
                "conversation_id": log_conv_id,
                "account_wxid": resolved_account,
                "contact_avatar": contact_avatar,
                "user_avatar": user_avatar,
                "log": {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "suggestion_id": row["suggestion_id"],
                    "gate_decision": row["rag_gate_decision"],
                    "gate_reason": row["rag_gate_reason"],
                    "strategy": row["rag_strategy"],
                    "injection_mode": row["rag_injection_mode"],
                    "elapsed_ms": row["rag_latency_ms"],
                    "hit_count": row["rag_hit_count"],
                    "hot_context_only": bool(row["hot_context_only"]) if "hot_context_only" in row.keys() else False,
                    "degrade_reason": row["rag_degraded_reason"],
                    "run_provenance": row["run_provenance"] if "run_provenance" in row.keys() else "production",
                },
                "injected": injected_items,
                "candidates": {
                    "count": len(candidate_ids),
                    "injected_count": len(injected_ids),
                    "not_injected_ids": not_injected_ids[:20],
                    "evidence_total": len(evidence_ids_all),
                },
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取 RAG 日志详情失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_contact_facts(
        self, conversation_id: int, account_wxid: str = "", limit: int = 200,
        offset: int = 0, sort: str = "time_desc", kind: str = "",
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """List contact memory facts with evidence for user review/correction.

        sort: time_desc / time_asc / conf_desc；kind 为空返回全部；
        返回 kinds 聚合（含计数）供前端 tag 筛选器构建。
        """
        try:
            from ...db.connection import get_db
            from ...services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            conn = get_db()
            store = RagStore(conn)
            page_limit = max(1, min(int(limit), 200))
            page_offset = max(0, int(offset))
            kind_filter = str(kind or "").strip()
            kind_clause = "AND kind = ?" if kind_filter else ""
            kind_args = (kind_filter,) if kind_filter else ()
            enabled_clause = "AND enabled = ?" if enabled is not None else ""
            enabled_args = (int(bool(enabled)),) if enabled is not None else ()

            order_by = {
                "time_asc": "enabled DESC, as_of ASC, id ASC",
                "conf_desc": "enabled DESC, confidence DESC, as_of DESC, id DESC",
            }.get(str(sort or "time_desc"), "enabled DESC, as_of DESC, id DESC")

            rows = conn.execute(
                f"""
                SELECT id, subject, kind, content, as_of, confidence, sensitivity, enabled,
                       evidence_message_ids_json
                FROM rag_facts
                WHERE account_wxid = ? AND conversation_id = ? AND status = 'active'
                  {kind_clause} {enabled_clause}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                (resolved_account, int(conversation_id), *kind_args, *enabled_args, page_limit, page_offset),
            ).fetchall()
            count_row = conn.execute(
                f"""
                SELECT COUNT(*) AS fact_count,
                       COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled_fact_count
                FROM rag_facts
                WHERE account_wxid = ? AND conversation_id = ? AND status = 'active'
                  {kind_clause}
                """,
                (resolved_account, int(conversation_id), *kind_args),
            ).fetchone()
            raw_count_row = conn.execute(
                "SELECT COUNT(*) FROM rag_facts WHERE account_wxid = ? AND conversation_id = ?",
                (resolved_account, int(conversation_id)),
            ).fetchone()
            raw_fact_count = int(raw_count_row[0]) if raw_count_row else 0
            logger.debug(
                "[Bridge] get_contact_facts conv=%s account=%s raw=%s listed=%s",
                conversation_id,
                resolved_account,
                raw_fact_count,
                len(rows),
            )
            feedback = store.list_fact_user_feedback(resolved_account, int(conversation_id))

            contact_avatar = ""
            try:
                conv_row = conn.execute(
                    "SELECT avatar_path FROM conversations WHERE id = ?",
                    (int(conversation_id),),
                ).fetchone()
                if conv_row and conv_row["avatar_path"]:
                    contact_avatar = str(conv_row["avatar_path"] or "").strip()
                if not contact_avatar:
                    c_row = conn.execute(
                        """
                        SELECT avatar_path FROM contacts
                        WHERE account_wxid = ? AND username = (SELECT username FROM conversations WHERE id = ?)
                        LIMIT 1
                        """,
                        (resolved_account, int(conversation_id)),
                    ).fetchone()
                    if c_row and c_row["avatar_path"]:
                        contact_avatar = str(c_row["avatar_path"] or "").strip()
            except Exception:
                pass

            user_avatar = ""
            try:
                user_prof = self.get_current_user_profile(account_wxid=resolved_account)
                if user_prof.get("ok") and user_prof.get("profile"):
                    user_avatar = str(user_prof["profile"].get("avatar") or "").strip()
            except Exception:
                pass

            evidence_ids_by_fact: dict[int, list[int]] = {}
            all_evidence_ids: set[int] = set()
            for row in rows:
                try:
                    ids = [int(v) for v in json.loads(row["evidence_message_ids_json"] or "[]") if str(v).isdigit()]
                except Exception:
                    ids = []
                ids = [i for i in ids if i > 0][:6]
                evidence_ids_by_fact[int(row["id"])] = ids
                all_evidence_ids.update(ids)

            evidence_msg_by_id: dict[int, dict[str, Any]] = {}
            if all_evidence_ids:
                ids = list(all_evidence_ids)
                placeholders = ",".join("?" for _ in ids)
                try:
                    cols = {
                        r["name"]
                        for r in conn.execute("PRAGMA table_info(messages)").fetchall()
                    }
                    sender_col = "is_sender" if "is_sender" in cols else "0 AS is_sender"
                    time_col = (
                        "timestamp"
                        if "timestamp" in cols
                        else ("created_at" if "created_at" in cols else "0 AS timestamp")
                    )
                    msg_rows = conn.execute(
                        f"""
                        SELECT id, {sender_col}, {time_col}, CAST(content AS BLOB) AS content
                        FROM messages
                        WHERE id IN ({placeholders})
                        ORDER BY {time_col} ASC, id ASC
                        """,
                        ids,
                    ).fetchall()
                    for msg_row in msg_rows:
                        value = msg_row["content"]
                        text_val = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
                        text_val = " ".join(text_val.split())
                        if text_val:
                            ts_val = (
                                msg_row["timestamp"]
                                if "timestamp" in msg_row.keys()
                                else (msg_row["created_at"] if "created_at" in msg_row.keys() else 0)
                            )
                            evidence_msg_by_id[int(msg_row["id"])] = {
                                "id": int(msg_row["id"]),
                                "is_sender": bool(msg_row["is_sender"]),
                                "timestamp": int(ts_val or 0),
                                "text": text_val[:180] + ("…" if len(text_val) > 180 else ""),
                            }
                except Exception as ex:
                    logger.warning("[Bridge] 查询证据消息失败: %s", ex)
                    evidence_msg_by_id = {}

            facts = []
            for row in rows:
                fact_msg_ids = evidence_ids_by_fact.get(int(row["id"]), [])
                fact_evidence_msgs = [
                    evidence_msg_by_id[i]
                    for i in fact_msg_ids
                    if i in evidence_msg_by_id
                ]
                fact_evidence_msgs.sort(key=lambda m: (m.get("timestamp") or 0, m.get("id") or 0))

                facts.append(
                    {
                        "id": row["id"],
                        "subject": row["subject"],
                        "kind": row["kind"],
                        "content": row["content"],
                        "as_of": row["as_of"],
                        "confidence": row["confidence"],
                        "sensitive": str(row["sensitivity"] or "normal") == "sensitive",
                        "enabled": bool(row["enabled"]),
                        "user_action": feedback.get(int(row["id"])),
                        "evidence_messages": fact_evidence_msgs,
                        "evidence_excerpts": [m["text"] for m in fact_evidence_msgs],
                    }
                )
            return {
                "ok": True,
                "conversation_id": int(conversation_id),
                "resolved_account_wxid": resolved_account,
                "contact_avatar": contact_avatar,
                "user_avatar": user_avatar,
                "raw_fact_count": raw_fact_count,
                "fact_count": int(count_row["fact_count"]),
                "enabled_fact_count": int(count_row["enabled_fact_count"]),
                "selected_fact_count": (
                    int(count_row["fact_count"])
                    if enabled is None else (
                        int(count_row["enabled_fact_count"])
                        if enabled else int(count_row["fact_count"]) - int(count_row["enabled_fact_count"])
                    )
                ),
                "offset": page_offset,
                "limit": page_limit,
                "total": len(facts),
                "disabled_count": sum(1 for f in facts if not f["enabled"]),
                "document_count": int(
                    (
                        conn.execute(
                            """
                            SELECT document_count FROM rag_index_status
                            WHERE account_wxid = ? AND conversation_id = ?
                            """,
                            (resolved_account, int(conversation_id)),
                        ).fetchone()
                        or {"document_count": 0}
                    )["document_count"]
                    or 0
                ),
                "kinds": [
                    {"kind": row["kind"], "count": int(row["n"])}
                    for row in conn.execute(
                        """
                        SELECT kind, COUNT(*) AS n FROM rag_facts
                        WHERE account_wxid = ? AND conversation_id = ? AND status = 'active'
                        GROUP BY kind ORDER BY n DESC
                        """,
                        (resolved_account, int(conversation_id)),
                    ).fetchall()
                ],
                "facts": facts,
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取联系人记忆列表失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_fact_feedback(
        self, fact_id: int, action: str, reason: str = ""
    ) -> dict[str, Any]:
        """Apply user correction to one memory fact: inaccurate / forget / restore."""
        try:
            from ...db.connection import get_db
            from ...services.realtime.rag.store import RagStore

            conn = get_db()
            store = RagStore(conn)
            action = str(action or "").strip()
            if action == "restore":
                result = store.restore_fact(int(fact_id))
            else:
                result = store.set_fact_user_feedback(int(fact_id), action, reason or "")
            store.conn.commit()
            # 用户纠错后刷新关系策略影子：剔除已禁用事实的 evidence 引用
            # （P2.1 闭环；刷新受 shadow 开关保护，失败绝不阻塞反馈）
            if result.get("ok"):
                try:
                    from ...services.realtime.rag.relationship_policy import (
                        refresh_after_fact_feedback,
                    )

                    normalized = "restore" if action == "restore" else action
                    refresh_result = refresh_after_fact_feedback(
                        store, int(fact_id), action=normalized
                    )
                    store.conn.commit()
                    logger.debug(
                        "[Bridge] 记忆反馈后策略刷新 fact=%s result=%s",
                        fact_id,
                        refresh_result,
                    )
                except Exception as refresh_exc:
                    logger.warning(
                        "[Bridge] 记忆反馈后关系策略刷新失败（不影响反馈）: %s", refresh_exc
                    )
            return result
        except Exception as e:
            logger.error(f"[Bridge] 记忆反馈失败: {e}")
            return {"ok": False, "error": str(e)}

    def get_rag_status(self, account_wxid: str = "", limit: int = 1000) -> dict[str, Any]:
        """Return per-contact RAG status summary for the settings page."""
        try:
            from ...db.connection import get_db
            from ...services.realtime.rag.store import RagStore
            from ...services.wechat.contact_filters import is_excluded_contact_username

            resolved_account = self._resolve_account_wxid(account_wxid)
            conn = get_db()
            RagStore(conn)

            # 检查表和列结构，确保兼容测试环境的精简 schema
            has_contacts_table = False
            conv_cols = set()
            ct_cols = set()
            try:
                table_check = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='contacts'"
                ).fetchone()
                has_contacts_table = bool(table_check)
                conv_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
                if has_contacts_table:
                    ct_cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
            except Exception:
                pass

            c_avatar_expr = "NULLIF(TRIM(c.avatar_path), '')" if "avatar_path" in conv_cols else "NULL"
            ct_avatar_expr = "NULLIF(TRIM(ct.avatar_path), '')" if "avatar_path" in ct_cols else "NULL"
            c_display_expr = "NULLIF(TRIM(c.display_name), '')" if "display_name" in conv_cols else "NULL"
            ct_remark_expr = "NULLIF(TRIM(ct.remark), '')" if "remark" in ct_cols else "NULL"
            ct_nickname_expr = "NULLIF(TRIM(ct.nickname), '')" if "nickname" in ct_cols else "NULL"

            if has_contacts_table:
                query = f"""
                SELECT
                    c.id AS conversation_id,
                    COALESCE(
                        {ct_remark_expr},
                        {ct_nickname_expr},
                        {c_display_expr},
                        NULLIF(TRIM(c.username), ''),
                        '未知联系人'
                    ) AS display_name,
                    c.username,
                    COALESCE(
                        {c_avatar_expr},
                        {ct_avatar_expr}
                    ) AS avatar,
                    COALESCE(s.status, 'pending') AS status,
                    COALESCE(s.document_count, 0) AS document_count,
                    COALESCE(s.vector_count, 0) AS vector_count,
                    s.last_indexed_at,
                    s.last_error,
                    COALESCE(s.storage_bytes, 0) AS storage_bytes,
                    COALESCE(s.enabled, 1) AS enabled,
                    COALESCE(s.fact_read_mode, 'inherit') AS fact_read_mode,
                    c.updated_at
                FROM conversations c
                LEFT JOIN contacts ct
                  ON ct.account_wxid = c.account_wxid AND ct.username = c.username
                LEFT JOIN rag_index_status s
                  ON s.account_wxid = c.account_wxid AND s.conversation_id = c.id
                WHERE c.account_wxid = ? AND c.is_deleted = 0
                ORDER BY c.updated_at DESC
                LIMIT ?
                """
            else:
                query = f"""
                SELECT
                    c.id AS conversation_id,
                    COALESCE({c_display_expr}, NULLIF(TRIM(c.username), ''), '未知联系人') AS display_name,
                    c.username,
                    {c_avatar_expr} AS avatar,
                    COALESCE(s.status, 'pending') AS status,
                    COALESCE(s.document_count, 0) AS document_count,
                    COALESCE(s.vector_count, 0) AS vector_count,
                    s.last_indexed_at,
                    s.last_error,
                    COALESCE(s.storage_bytes, 0) AS storage_bytes,
                    COALESCE(s.enabled, 1) AS enabled,
                    COALESCE(s.fact_read_mode, 'inherit') AS fact_read_mode,
                    c.updated_at
                FROM conversations c
                LEFT JOIN rag_index_status s
                  ON s.account_wxid = c.account_wxid AND s.conversation_id = c.id
                WHERE c.account_wxid = ? AND c.is_deleted = 0
                ORDER BY c.updated_at DESC
                LIMIT ?
                """

            rows = conn.execute(query, (resolved_account, max(1, int(limit)))).fetchall()
            fact_counts_by_conv: dict[int, tuple[int, int]] = {}
            try:
                for f_row in conn.execute(
                    """
                    SELECT conversation_id,
                           COUNT(*) AS fact_count,
                           COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled_fact_count
                    FROM rag_facts
                    WHERE account_wxid = ? AND status = 'active'
                    GROUP BY conversation_id
                    """,
                    (resolved_account,),
                ).fetchall():
                    fact_counts_by_conv[int(f_row["conversation_id"])] = (
                        int(f_row["fact_count"] or 0),
                        int(f_row["enabled_fact_count"] or 0),
                    )
            except Exception:
                pass

            from ...services.realtime.rag.indexer import get_active_and_queued
            live_states = get_active_and_queued()
            items = []
            for row in rows:
                item = dict(row)
                if is_excluded_contact_username(item.get("username")):
                    continue
                conv_id = int(item.get("conversation_id") or 0)
                f_total, f_enabled = fact_counts_by_conv.get(conv_id, (0, 0))
                item["fact_count"] = f_total
                item["enabled_fact_count"] = f_enabled
                live = live_states.get((resolved_account, conv_id))
                if live:
                    # 后台真值优先：构建中/排队中（DB status 在此期间不更新）
                    item["status"] = live
                items.append(item)
            return {
                "ok": True,
                "has_live": bool(live_states),
                "settings": {
                    key: self.settings.get(key)
                    for key in (
                        "rag_enabled",
                        "rag_remote_context_redaction",
                        "rag_allow_remote_embedding",
                        "rag_embedding_model",
                        "rag_embedding_dim",
                        "rag_privacy_mode",
                        "rag_fact_shadow_enabled",
                        "rag_fact_read_enabled",
                        "rag_fact_score_threshold",
                    )
                },
                "items": items,
                "total_facts": sum(int(item.get("fact_count") or 0) for item in items),
                "total_documents": sum(int(item.get("document_count") or 0) for item in items),
                "total_storage_bytes": sum(int(item.get("storage_bytes") or 0) for item in items),
            }
        except Exception as e:
            logger.error(f"[Bridge] 获取 RAG 状态失败: {e}")
            return {"ok": False, "error": str(e), "items": []}

    def get_monitor_rag_status(self, account_wxid: str = "") -> dict[str, Any]:
        """当前监听联系人的 RAG 索引状态（悬浮面板「建议依据」提醒用）。

        没有索引时 AI 建议只靠近期对话（记忆槽为空），前端需提醒并可
        一键构建。监听启动虽有 prewarm，但 RAG 关闭/解析失败/空历史时
        仍然缺索引。
        """
        try:
            from ...services.realtime.monitor_service import RealtimeMonitorService
            from ...services.realtime.rag.config import load_rag_settings

            monitor = RealtimeMonitorService()
            rag_enabled = bool(load_rag_settings().get("rag_enabled"))
            base = {
                "ok": True,
                "monitoring": bool(getattr(monitor, "is_monitoring", False)),
                "display_name": getattr(monitor, "current_display_name", "") or "",
                "enabled": rag_enabled,
                "conversation_id": None,
                "status": "none",
                "document_count": 0,
                "vector_count": 0,
                "has_index": False,
            }
            if not base["monitoring"] or not rag_enabled:
                return base

            resolved_account = self._resolve_account_wxid(
                account_wxid or getattr(monitor, "current_account_wxid", "") or ""
            )
            conversation_id = self._resolve_current_conversation_id(
                account_wxid=resolved_account,
                display_name=base["display_name"],
                username=getattr(monitor, "current_talker", "") or "",
            )
            if not conversation_id:
                return base
            base["conversation_id"] = int(conversation_id)

            from ...db.connection import get_db

            row = get_db().execute(
                """
                SELECT status, document_count, vector_count
                FROM rag_index_status
                WHERE account_wxid = ? AND conversation_id = ?
                """,
                (resolved_account, int(conversation_id)),
            ).fetchone()
            if row:
                base["status"] = str(row["status"] or "none")
                base["document_count"] = int(row["document_count"] or 0)
                base["vector_count"] = int(row["vector_count"] or 0)
            # 有向量才算可用索引：document_count>0 但 vector_count=0 的
            # 半成品状态同样视为不可用（检索拿不到任何东西）
            base["has_index"] = base["document_count"] > 0 and base["vector_count"] > 0
            return base
        except Exception as e:
            logger.error(f"[Bridge] 获取监听 RAG 状态失败: {e}")
            return {"ok": False, "error": str(e), "has_index": False, "enabled": False}

    def rebuild_rag_index(self, conversation_id: int, account_wxid: str = "") -> dict[str, Any]:
        """Rebuild one contact RAG index (always async via the single-worker queue).

        原实现锁空闲时在端点内联同步重建（阻塞分钟级且 UI 无构建中真值），
        现统一入队：状态经 get_rag_status 的 building/queued 覆盖可查。
        """
        try:
            from ...services.realtime.rag.config import load_rag_settings
            from ...services.realtime.rag.indexer import RagIndexQueue, get_active_and_queued
            from ...services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            if not load_rag_settings().get("rag_enabled"):
                # 主开关关闭时队列 worker 会丢弃任务——保持旧行为内联同步重建
                from ...services.realtime.rag.indexer import RagIndexer
                status = RagIndexer().rebuild_contact_index(
                    account_wxid=resolved_account,
                    conversation_id=int(conversation_id),
                )
                failed = str((status or {}).get("status") or "") == "failed"
                return {
                    "ok": not failed,
                    "status": status,
                    "error": (status or {}).get("last_error") if failed else None,
                }
            key = (resolved_account, int(conversation_id))
            live = get_active_and_queued().get(key)
            if live:
                return {
                    "ok": True,
                    "queued": True,
                    "already": True,
                    "state": live,
                    "message": "该联系人正在构建索引，无需重复发起" if live == "building"
                    else "该联系人已在索引队列中",
                }
            # 手动「立即构建」= 用户显式选择开启：clear 后停用的联系人
            # 重新启用（队列 worker 对停用联系人跳过，防自动复活）
            try:
                from ...db.connection import get_db as _get_db

                RagStore(_get_db()).set_conversation_enabled(
                    resolved_account, int(conversation_id), True
                )
            except Exception as enable_e:
                logger.debug("[Bridge] 重新启用联系人跳过: %s", enable_e)
            RagIndexQueue.enqueue(resolved_account, int(conversation_id))
            return {
                "ok": True,
                "queued": True,
                "state": "queued",
                "message": "已加入索引队列（单 worker 串行执行）",
            }
        except Exception as e:
            logger.error(f"[Bridge] 重建 RAG 索引失败: {e}")
            return {"ok": False, "error": str(e)}

    def clear_rag_index(self, conversation_id: int, account_wxid: str = "") -> dict[str, Any]:
        """Clear one contact RAG data without touching original messages."""
        try:
            from ...services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            store = RagStore()
            deleted = store.clear_conversation(resolved_account, int(conversation_id))
            # 清空后停用该联系人记忆：否则 ensure_contact_index 检测到
            # 无状态会在下次建议时自动排队重建，事实被重抽复活——违背
            # "清空"语义。用户可重新启用并手动重建。
            store.set_conversation_enabled(resolved_account, int(conversation_id), False)
            store.conn.commit()
            from ...services.realtime.rag.retriever import invalidate_vector_cache
            invalidate_vector_cache(resolved_account, int(conversation_id))
            return {"ok": True, "deleted": deleted}
        except Exception as e:
            logger.error(f"[Bridge] 清空 RAG 索引失败: {e}")
            return {"ok": False, "error": str(e)}

    def backfill_all_rag_extraction(self, account_wxid: str = "") -> dict[str, Any]:
        """为全部有抽取欠账的联系人排队回补 LLM 记忆抽取（用户主动触发）。

        欠账 = 消息水位已推进但抽取水位未覆盖（含从未抽取）。队列单
        worker 串行消化，回补未完成自动续轮，直至全部抽平。成本与
        AI 抽取开关同级（每段一次远程调用），由前端确认弹窗明示。
        """
        try:
            from ...db.connection import get_db
            from ...services.realtime.rag.indexer import RagIndexer, RagIndexQueue

            resolved_account = self._resolve_account_wxid(account_wxid)
            conn = get_db()
            rows = conn.execute(
                """
                SELECT s.conversation_id,
                       s.message_watermark_ts, s.fact_extract_watermark_ts,
                       s.fact_extract_prompt_version, s.enabled
                FROM rag_index_status s
                WHERE s.account_wxid = ?
                  AND s.message_watermark_ts > 0
                  AND s.enabled = 1
                """,
                (resolved_account,),
            ).fetchall()
            queued = 0
            for row in rows:
                msg_wm = int(row["message_watermark_ts"] or 0)
                ext_wm = int(row["fact_extract_watermark_ts"] or 0)
                version = str(row["fact_extract_prompt_version"] or "")
                if version != RagIndexer.FACT_EXTRACT_PROMPT_VERSION or ext_wm < msg_wm:
                    RagIndexQueue.enqueue(resolved_account, int(row["conversation_id"]))
                    queued += 1
            logger.info("[Bridge] 批量回补记忆抽取: 排队 %s 个联系人", queued)
            return {"ok": True, "queued": queued}
        except Exception as e:
            logger.error(f"[Bridge] 批量回补失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_rag_conversation_enabled(
        self,
        conversation_id: int,
        enabled: bool,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Enable or disable one contact's RAG candidates."""
        try:
            from ...services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            store = RagStore()
            store.set_conversation_enabled(resolved_account, int(conversation_id), bool(enabled))
            store.conn.commit()
            return {"ok": True, "enabled": bool(enabled)}
        except Exception as e:
            logger.error(f"[Bridge] 更新联系人 RAG 启用状态失败: {e}")
            return {"ok": False, "error": str(e)}

    def set_rag_fact_read_mode(
        self,
        conversation_id: int,
        mode: str,
        account_wxid: str = "",
    ) -> dict[str, Any]:
        """Switch one contact between fact-first and document rollback reads."""
        try:
            from ...services.realtime.rag.store import RagStore

            resolved_account = self._resolve_account_wxid(account_wxid)
            normalized_mode = str(mode or "").strip().lower()
            store = RagStore()
            store.set_fact_read_mode(resolved_account, int(conversation_id), normalized_mode)
            store.conn.commit()
            return {"ok": True, "fact_read_mode": normalized_mode}
        except Exception as e:
            logger.error(f"[Bridge] 更新联系人事实读侧模式失败: {e}")
            return {"ok": False, "error": str(e)}

