"""G7 三路回放器:对 G0 冻结样例运行 no_rag / legacy / g1 链路对照。

用法(仓库根目录)::

    # dry-run(默认):装配到最终 prompt 为止,不调模型、零 API 成本
    python backend/scripts/g1_baseline_replay.py --chain all
    python backend/scripts/g1_baseline_replay.py --chain g1 --sample real-2

    # live:真实调用当前激活模型(产生 API 费用,输出计入报告)
    python backend/scripts/g1_baseline_replay.py --chain g1 --live

安全设计:

- 源库只读;回放在临时副本上运行(sqlite backup API 复制),检索日志/
  发送清单等写操作全部落在副本,真实数据库零写入。
- ``legacy`` 链路是行为等价重建:复用旧二分关键词表映射任务三元组,
  并置 ``_legacy_prompt_chain`` 跳过窗口净化——不是逐字节复刻,报告里
  以 ``chain_note`` 显式声明。
- ``requires_ambiguous_twin`` 样例会在副本注入同名会话行,验证
  歧义联系人不自动选取。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPLAY_VERSION = "g1-baseline-replay-v1"
CHAINS = ("no_rag", "legacy", "g1")
KN_ALL = ["facts", "contact_profile", "user_style", "relationship_signals"]


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def copy_database(db_path: str, workdir: Path) -> str:
    """sqlite backup API 复制(连同 WAL 状态),源库保持只读。"""
    copy_path = str(workdir / "replay-copy.db")
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dest = sqlite3.connect(copy_path)
    with dest:
        source.backup(dest)
    source.close()
    dest.close()
    return copy_path


def build_recent_messages(conn: sqlite3.Connection, conversation_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """从 messages 表回放近期窗口(映射到生成侧消息结构)。"""
    rows = conn.execute(
        "SELECT id, talker, is_sender, message_type, content, timestamp FROM messages "
        "WHERE conversation_id = ? ORDER BY timestamp DESC, id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    messages: list[dict[str, Any]] = []
    for row in reversed(rows):
        message_type = str(row["message_type"] or "").lower()
        if message_type in {"10000", "system"} or str(row["is_sender"]) == "2":
            sender_attr = "system"
        elif row["is_sender"]:
            sender_attr = "self"
        else:
            sender_attr = "friend"
        messages.append({
            "id": row["id"],
            "timestamp": row["timestamp"],
            "sender_attr": sender_attr,
            "content": str(row["content"] or ""),
            "message_type": "text",
        })
    return messages


def inject_ambiguous_twin(conn: sqlite3.Connection, sample: dict[str, Any], chain: str) -> None:
    """在副本里造一个同名联系人,验证 scope 解析拒绝自动选取。

    username 带链路后缀:三条链路各自插入自己的孪生,避免同秒 UNIQUE 冲突。
    """
    now = int(time.time())
    conn.execute(
        "INSERT INTO conversations (account_wxid, display_name, username, is_deleted, updated_at, created_at) "
        "VALUES (?, ?, ?, 0, ?, ?)",
        (
            sample["account_wxid"],
            sample["display_name"],
            f"wxid_twin_{chain}_{now}",
            now,
            now,
        ),
    )
    conn.commit()


def legacy_routing(engine: Any, context: dict[str, Any]) -> dict[str, Any]:
    """旧二分判定 → 三元组等价映射:direct_reply 压制一切知识块。"""
    classification = _legacy_two_way(context)
    if classification == "direct_reply":
        return {
            "task": "general_qa",
            "output": "direct_answer",
            "knowledge_needs": [],
            "confidence": 0.6,
            "reason": "legacy_direct_reply",
            "wants_speeches": False,
            "manual_request": True,
        }
    return {
        "task": "reply_suggestion",
        "output": "suggestion_card",
        "knowledge_needs": KN_ALL,
        "confidence": 0.8,
        "reason": "legacy_advice_request",
        "wants_speeches": True,
        "manual_request": True,
    }


def _legacy_two_way(context: dict[str, Any]) -> str:
    from app.services.realtime.task_router import ADVICE_KEYWORDS
    import re as _re

    user_context = context.get("user_context")
    latest = ""
    if isinstance(user_context, list):
        for msg in reversed(user_context):
            if isinstance(msg, dict) and msg.get("role") == "user":
                latest = str(msg.get("content") or "").strip()
                break
    elif isinstance(user_context, str):
        latest = user_context.strip()
    if not latest:
        return "advice_request"
    normalized = _re.sub(r"\s+", "", latest)
    if any(keyword in normalized for keyword in ADVICE_KEYWORDS):
        return "advice_request"
    return "direct_reply"


def _routing_for_chain(chain: str, engine: Any, context: dict[str, Any]) -> dict[str, Any]:
    if chain == "legacy":
        return legacy_routing(engine, context)
    from app.services.realtime.task_router import route_generation_task

    return route_generation_task(context, "manual_request").to_dict()


def replay_sample(
    sample: dict[str, Any],
    *,
    chain: str,
    conn: sqlite3.Connection,
    live: bool,
) -> dict[str, Any]:
    from app.services.realtime.generation_context import assemble_generation_context
    from app.services.realtime.llm_engine import LLMSuggestionEngine
    from app.services.realtime.rag.context_builder import RagContextBuilder

    engine = LLMSuggestionEngine()
    model_config = engine._get_active_model()

    context: dict[str, Any] = {"user_context": sample["input"]}
    if sample.get("conversation_id") and chain != "no_rag":
        context["recent_messages"] = build_recent_messages(conn, int(sample["conversation_id"]))

    if sample.get("requires_ambiguous_twin") and chain != "no_rag":
        inject_ambiguous_twin(conn, sample, chain)

    started = time.perf_counter()
    scope = assemble_generation_context(
        context,
        entrypoint=f"replay_{chain}",
        account_wxid=sample.get("account_wxid") or "",
        conversation_id=sample.get("conversation_id"),
        display_name=sample.get("display_name") or "",
        username="",
        emotion_summary=None,
        prewarm_rag_index=False,
    )

    routing = _routing_for_chain(chain, engine, context)
    context["_task_routing"] = routing
    context["_rag_output_mode"] = "reply" if routing["output"] == "direct_answer" else "suggestion"
    if chain == "legacy":
        context["_legacy_prompt_chain"] = True

    result: dict[str, Any] = {
        "sample_id": sample["sample_id"],
        "dimension": sample["dimension"],
        "chain": chain,
        "chain_note": "行为等价重建(旧二分路由+未净化窗口)" if chain == "legacy" else "",
        "routing": routing,
        "scope": {
            "status": scope.status,
            "reason": scope.reason,
            "conversation_id": scope.conversation_id,
            "request_id": scope.request_id,
        },
        "model": (model_config or {}).get("model_id"),
    }

    if chain == "no_rag":
        import app.services.realtime.rag.context_builder as cb_module

        original = cb_module.load_rag_settings
        cb_module.load_rag_settings = lambda: {**original(), "rag_enabled": False}
        try:
            _run_dry(context, engine, model_config, result, started)
        finally:
            cb_module.load_rag_settings = original
    elif live:
        try:
            suggestion = engine.generate("manual_request", "maintain", context)
            result["output"] = {
                "summary": suggestion.summary,
                "speeches": suggestion.speeches,
                "reply": suggestion.reply,
                "rag_badge": getattr(suggestion, "rag_context", None),
            }
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        _collect_manifest(context, result)
    else:
        _run_dry(context, engine, model_config, result, started)
    return result


def _run_dry(context, engine, model_config, result, started) -> None:
    from app.services.realtime.rag.context_builder import RagContextBuilder

    try:
        RagContextBuilder().enrich_context(
            context, trigger_type="manual_request", intent="maintain", model_config=model_config,
        )
    except Exception as exc:
        result["rag_error"] = f"{type(exc).__name__}: {exc}"
    prompt = engine._build_prompt("manual_request", "maintain", context, model_config=model_config)
    result["prompt_chars"] = len(prompt)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    _collect_manifest(context, result)


def _collect_manifest(context: dict[str, Any], result: dict[str, Any]) -> None:
    manifest = context.get("_rag_sent_manifest") or {}
    debug = context.get("_rag_debug") or {}
    result["manifest"] = {
        "fact_ids": manifest.get("fact_ids") or [],
        "document_ids": manifest.get("document_ids") or [],
        "policy_ids": manifest.get("policy_ids") or [],
        "contact_preference_ids": manifest.get("contact_preference_ids") or [],
        "blocks": manifest.get("blocks") or [],
        "excluded": manifest.get("excluded") or [],
        "prompt_hash": manifest.get("prompt_hash"),
    }
    result["rag"] = {
        "log_id": context.get("_rag_log_id"),
        "hit_count": debug.get("rag_hit_count"),
        "gate_decision": debug.get("rag_gate_decision"),
        "degraded_reason": debug.get("rag_degraded_reason"),
        "memory_intent_mode": debug.get("memory_intent_mode"),
    }
    badge = None
    try:
        from app.services.realtime.llm_engine import LLMSuggestionEngine

        badge = LLMSuggestionEngine()._build_rag_context_summary(context)
    except Exception:
        badge = None
    result["badge"] = badge


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-baseline-samples.json"))
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "chrono_trace.db"))
    parser.add_argument("--chain", default="all", choices=[*CHAINS, "all"])
    parser.add_argument("--sample", action="append", default=None, help="样例 ID,可重复;缺省全部")
    parser.add_argument("--live", action="store_true", help="真实调用激活模型(产生 API 费用)")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-replay-results.json"))
    args = parser.parse_args()

    payload = _json(Path(args.samples).read_text(encoding="utf-8"), None)
    if not payload or not payload.get("samples"):
        print(f"[G7 Replay] 样例文件缺失或为空: {args.samples}(先运行 g1_baseline_loader)")
        return 1
    samples = payload["samples"]
    if args.sample:
        wanted = set(args.sample)
        samples = [s for s in samples if s["sample_id"] in wanted]
        missing = wanted - {s["sample_id"] for s in samples}
        if missing:
            print(f"[G7 Replay] 未找到样例: {sorted(missing)}")
            return 1

    chains = CHAINS if args.chain == "all" else (args.chain,)

    with tempfile.TemporaryDirectory(prefix="g1-replay-", ignore_cleanup_errors=True) as tmp:
        copy_path = copy_database(args.db, Path(tmp))
        from app.db.connection import DatabaseConnection

        DatabaseConnection.initialize(copy_path)
        conn = DatabaseConnection.get_connection()

        results: list[dict[str, Any]] = []
        failures = 0
        for sample in samples:
            for chain in chains:
                try:
                    result = replay_sample(sample, chain=chain, conn=conn, live=args.live)
                except Exception as exc:
                    result = {
                        "sample_id": sample["sample_id"],
                        "chain": chain,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    failures += 1
                results.append(result)
                manifest = result.get("manifest") or {}
                scope = result.get("scope") or {}
                routing = result.get("routing") or {}
                print(
                    f"  {result.get('sample_id', '?'):>24} | {chain:>6} | "
                    f"task={routing.get('task', '-'):>22} | out={routing.get('output', '-'):>20} | "
                    f"scope={scope.get('status', '-'):>20} | facts={len(manifest.get('fact_ids') or [])} | "
                    f"{result.get('elapsed_ms', '-')}ms"
                    + (f" | ERR={result['error']}" if result.get("error") else "")
                )

        # Windows 下线程本地连接可能已被组件重新初始化,尽力关闭后
        # 交由 ignore_cleanup_errors 兜底,避免临时目录删除报错。
        try:
            DatabaseConnection.close()
        except Exception:
            pass

    report = {
        "replay_version": REPLAY_VERSION,
        "ran_at": int(time.time()),
        "live": bool(args.live),
        "chains": list(chains),
        "sample_file": args.samples,
        "source_db_frozen_at": (payload.get("meta") or {}).get("frozen_at"),
        "baseline_code_commit": (payload.get("meta") or {}).get("code_commit"),
        "failures": failures,
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = _json(out.read_text(encoding="utf-8"), None) if out.exists() else None
    if isinstance(existing, dict):
        existing.setdefault("runs", []).append(report)
        report_to_write = existing
    else:
        report_to_write = {"runs": [report]}
    out.write_text(json.dumps(report_to_write, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[G7 Replay] {len(results)} 条链路结果({failures} 失败)已追加 → {out}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
