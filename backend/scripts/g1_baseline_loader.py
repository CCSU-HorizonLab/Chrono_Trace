"""G0 基线样例装载器:从真实检索日志/建议/会话生成 24 条诊断样例。

用法(仓库根目录)::

    python backend/scripts/g1_baseline_loader.py \
        --db backend/data/chrono_trace.db \
        --out docs/goals/g1-baseline-samples.json

产出结构::

    meta:    冻结记录(代码 commit、DB 指纹、活跃模型、装载器版本)
    samples: 24 条样例,六维覆盖(任务切换/联系人绑定/通知污染/
             脱敏误伤/策略适配/缺失降级)

样例来源两种:

- ``real_log``  : 直接取自 rag_retrieval_logs(+关联 realtime_suggestions),
                  带改造前判定(旧二分任务、召回 fact_ids、prompt hash、模型输出);
- ``authored``  : 绑定真实 account/conversation 的施工单验证句式,预期标注
                  由当前任务路由器自动给出,``annotation=auto_pending_human``
                  表示待人工确认后才能作为门禁依据。

只读源库,不做任何写入。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOADER_VERSION = "g1-baseline-loader-v1"
SAMPLE_TARGET = 24
MIN_PER_DIMENSION = 3

DIMENSIONS = (
    "task_routing",           # 任务识别与切换
    "contact_binding",        # 联系人范围绑定
    "notification_pollution", # 系统通知/转账污染
    "redaction_misfire",      # 脱敏误伤
    "policy_adaptation",      # 关系策略适配
    "missing_scope_degrade",  # 缺失范围安全降级
)

# 施工单/目标样例驱动的 authored 输入。(dimension, user_context, note)
AUTHORED_INPUTS: tuple[tuple[str, list[dict[str, str]], str], ...] = (
    ("task_routing", [{"role": "user", "content": "我想约她打游戏"}], "施工单首个目标样例:邀约"),
    ("task_routing", [{"role": "user", "content": "怎么回她关于周末的邀约"}], "显式回复求助,话题与邀约相关"),
    ("task_routing", [{"role": "user", "content": "她喜欢什么"}], "偏好查询→记忆问答"),
    (
        "task_routing",
        [
            {"role": "user", "content": "怎么回她关于游戏的邀约比较好?"},
            {"role": "assistant", "content": "可以顺着游戏聊,给出话术。"},
            {"role": "user", "content": "没有建议么"},
        ],
        "三轮任务切换:求助→追问",
    ),
    ("task_routing", [{"role": "user", "content": "你好呀"}], "普通闲聊→安全直答"),
    ("task_routing", [{"role": "user", "content": "我们玩过什么游戏"}], "历史问答(如有真实日志则优先 real_log)"),
    ("contact_binding", [{"role": "user", "content": "我想约她打游戏"}], "歧义同名:需在回放副本注入同名会话"),
    ("contact_binding", [{"role": "user", "content": "怎么回她"}], "无效会话 ID:跨账号会话"),
    ("contact_binding", [{"role": "user", "content": "怎么回她"}], "有效显式会话 ID:正对照"),
    ("notification_pollution", [{"role": "user", "content": "她是不是不想理我了"}], "转账密集窗口的关系推断"),
    ("notification_pollution", [{"role": "user", "content": "怎么回她"}], "通知混入窗口的建议生成"),
    ("notification_pollution", [{"role": "user", "content": "现在聊什么好"}], "纯通知窗口守卫"),
    ("redaction_misfire", [{"role": "user", "content": "我们玩过什么游戏"}], "游戏事实脱敏完整性(绑事实最密的会话)"),
    ("redaction_misfire", [{"role": "user", "content": "她说过她家在哪吗"}], "真实地址脱敏(应脱敏且标记不可引用)"),
    ("redaction_misfire", [{"role": "user", "content": "她电话多少"}], "电话号码脱敏"),
    ("policy_adaptation", [{"role": "user", "content": "她是不是讨厌我"}], "关系讨论:允许画像+关系信号"),
    ("policy_adaptation", [{"role": "user", "content": "我们算什么关系了,我该怎么推进"}], "关系讨论+行动求助"),
    ("policy_adaptation", [{"role": "user", "content": "怎么开玩笑不越界"}], "边界适配"),
    ("missing_scope_degrade", [{"role": "user", "content": "怎么回她"}], "无账号范围:空 account"),
    ("missing_scope_degrade", [{"role": "user", "content": "怎么回她"}], "无联系人范围:空 display/conversation"),
    ("missing_scope_degrade", [{"role": "user", "content": "怎么约她出来"}], "查无此联系人"),
)

_TRANSFER_TOKENS = ("转账", "已收款", "已被接收", "红包", "微信转账", "收款")
_GAME_TOKENS = ("游戏", "switch", "Switch", "PS", "ps5", "王者", "原神", "塞尔达", "马里奥", "路易吉", "杀戮尖塔", "联机", "开黑")


def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, cwd=str(Path(__file__).resolve().parents[2]),
        ).stdout.strip()
    except Exception:
        return "unknown"


def _latest_user_text(user_context: Any) -> str:
    if isinstance(user_context, list):
        for msg in reversed(user_context):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return str(msg.get("content") or "")
    elif isinstance(user_context, str):
        return user_context
    return ""


def load_samples(db_path: str) -> dict[str, Any]:
    """主入口:挖掘真实日志 + authored 补齐 → 24 条样例与冻结 meta。"""
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row

    conversations = {
        int(row["id"]): dict(row)
        for row in source.execute(
            "SELECT id, account_wxid, display_name, username, message_count FROM conversations WHERE is_deleted = 0"
        )
    }
    logs = [dict(row) for row in source.execute(
        "SELECT * FROM rag_retrieval_logs ORDER BY created_at ASC"
    )]
    suggestions = [dict(row) for row in source.execute(
        "SELECT id, account_wxid, batch_id, trigger_type, summary, speeches, trigger_context, created_at "
        "FROM realtime_suggestions ORDER BY created_at ASC"
    )]
    model_row = source.execute(
        "SELECT name, provider, model_id FROM llm_models WHERE is_active = 1 LIMIT 1"
    ).fetchone()

    # 每个会话的"事实画像":事实数、游戏事实占比、近期消息的转账密度。
    fact_stats: dict[int, dict[str, Any]] = {}
    for row in source.execute(
        "SELECT conversation_id, COUNT(*) n, "
        "SUM(CASE WHEN kind = 'hobby_or_game' THEN 1 ELSE 0 END) game_n "
        "FROM rag_facts WHERE status = 'active' GROUP BY conversation_id"
    ):
        fact_stats[int(row["conversation_id"])] = {
            "facts": int(row["n"]), "game_facts": int(row["game_n"] or 0),
        }
    transfer_density: dict[int, int] = {}
    for row in source.execute(
        "SELECT conversation_id, content FROM messages "
        "WHERE timestamp > (SELECT MAX(timestamp) - 30*24*3600 FROM messages)"
    ):
        content = str(row["content"] or "")
        if any(token in content for token in _TRANSFER_TOKENS) and len(content) <= 60:
            transfer_density[int(row["conversation_id"])] = transfer_density.get(int(row["conversation_id"]), 0) + 1

    source.close()

    # 选择 authored 样例绑定的会话:事实最密(游戏维度另选游戏事实最密)。
    by_facts = sorted(
        (cid for cid in fact_stats if cid in conversations),
        key=lambda cid: fact_stats[cid]["facts"], reverse=True,
    )
    game_conv = max(
        (cid for cid in fact_stats if cid in conversations),
        key=lambda cid: fact_stats[cid]["game_facts"], default=None,
    )
    transfer_conv = max(transfer_density, key=lambda cid: transfer_density.get(cid, 0), default=None)
    primary = conversations.get(by_facts[0]) if by_facts else None
    primary_id = by_facts[0] if by_facts else None

    samples: list[dict[str, Any]] = []

    # ---- 1) 真实日志样例 ----
    for log in logs:
        conv = conversations.get(int(log.get("conversation_id") or -1))
        if not conv:
            continue
        user_context = [{"role": "user", "content": str(log.get("query_text") or "")}]
        dimension = _classify_log_dimension(log, conv, transfer_density, fact_stats)
        suggestion = _match_suggestion(suggestions, log)
        samples.append({
            "sample_id": f"real-{log['id']}",
            "dimension": dimension,
            "source": "real_log",
            "input": user_context,
            "account_wxid": conv["account_wxid"],
            "conversation_id": int(conv["id"]),
            "display_name": conv["display_name"],
            "requires_ambiguous_twin": False,
            "expected": None,  # 真实样例的预期任务必须人工判定
            "expected_annotation": "human_required",
            "baseline": {
                "retrieval_log_id": int(log["id"]),
                "legacy_task": _legacy_classify(user_context),
                "memory_intent_mode": log.get("memory_intent_mode"),
                "gate_decision": log.get("rag_gate_decision"),
                "fact_ids": _json(log.get("fact_ids_json"), []),
                "policy_ids": _json(log.get("policy_ids_json"), []),
                "contact_preference_ids": _json(log.get("contact_preference_ids_json"), []),
                "prompt_context_hash": log.get("prompt_context_hash"),
                "redaction_status": log.get("redaction_status"),
                "degraded_reason": log.get("rag_degraded_reason"),
                "suggestion_id": suggestion["id"] if suggestion else None,
                "suggestion_summary": suggestion["summary"] if suggestion else None,
                "suggestion_speeches": _json(suggestion["speeches"], []) if suggestion else [],
                "created_at": log.get("created_at"),
            },
            "replay": {},
        })

    # ---- 2) authored 样例补齐维度 ----
    conv_rotation = [primary_id, game_conv, transfer_conv]
    for index, (dimension, user_context, note) in enumerate(AUTHORED_INPUTS):
        anchor = _pick_anchor(dimension, conv_rotation, index, conversations, by_facts)
        sample: dict[str, Any] = {
            "sample_id": f"authored-{dimension}-{index:02d}",
            "dimension": dimension,
            "source": "authored",
            "input": user_context,
            "note": note,
            "requires_ambiguous_twin": dimension == "contact_binding" and "歧义" in note,
            "expected": None,
            "expected_annotation": "auto_pending_human",
            "baseline": None,
            "replay": {},
        }
        if dimension == "missing_scope_degrade":
            sample["account_wxid"] = "" if "无账号" in note else (anchor["account_wxid"] if anchor else "")
            sample["conversation_id"] = None
            sample["display_name"] = "" if "无联系人" in note else "查无此人-9x7q"
        elif dimension == "contact_binding" and "无效" in note:
            # 跨账号:绑定另一账号下存在的会话 ID,回放应判 invalid_conversation
            foreign = next(
                (c for c in conversations.values() if anchor and c["account_wxid"] != anchor["account_wxid"]),
                None,
            )
            sample["account_wxid"] = anchor["account_wxid"] if anchor else ""
            sample["conversation_id"] = int(foreign["id"]) if foreign else 999999
            sample["display_name"] = anchor["display_name"] if anchor else ""
        elif anchor:
            sample["account_wxid"] = anchor["account_wxid"]
            sample["conversation_id"] = int(anchor["id"])
            sample["display_name"] = anchor["display_name"]
            if sample["requires_ambiguous_twin"]:
                # 歧义场景必须走显示名解析:显式会话 ID 会直连目标会话,
                # 绕过同名判定,验证不到"不自动选取"契约。
                sample["conversation_id"] = None
        else:
            continue  # 库里没有可绑定会话,放弃该条
        sample["expected"] = _auto_expected(user_context, sample)
        samples.append(sample)

    # ---- 3) 每维裁剪/补齐到目标 ----
    samples = _balance_to_target(samples, conversations, primary)

    coverage = {dim: sum(1 for s in samples if s["dimension"] == dim) for dim in DIMENSIONS}
    stat = Path(db_path)
    meta = {
        "loader_version": LOADER_VERSION,
        "frozen_at": int(time.time()),
        "code_commit": _git_commit(),
        "db": {
            "path": str(stat),
            "size_bytes": stat.stat().st_size if stat.exists() else None,
            "mtime": int(stat.stat().st_mtime) if stat.exists() else None,
            "conversations": len(conversations),
            "retrieval_logs": len(logs),
            "suggestions": len(suggestions),
        },
        "active_model": dict(model_row) if model_row else None,
        "sample_count": len(samples),
        "dimension_coverage": coverage,
        "notes": [
            "expected_annotation=human_required 的样例在人工判定前不得作为门禁依据。",
            "authored 样例预期由任务路由器自动给出(auto_pending_human),供人工确认。",
        ],
    }
    return {"meta": meta, "samples": samples}


def _classify_log_dimension(log: dict, conv: dict, transfer_density: dict, fact_stats: dict) -> str:
    if str(log.get("rag_degraded_reason") or "") == "missing_scope":
        return "missing_scope_degrade"
    fact_ids = _json(log.get("fact_ids_json"), [])
    conv_id = int(conv["id"])
    if fact_ids and fact_stats.get(conv_id, {}).get("game_facts", 0) > 0:
        query = str(log.get("query_text") or "")
        if any(token in query for token in ("游戏", "玩过", "switch", "Switch")):
            return "redaction_misfire"
    if _json(log.get("policy_ids_json"), []) or _json(log.get("contact_preference_ids_json"), []):
        if transfer_density.get(conv_id, 0) >= 2:
            return "notification_pollution"
        return "policy_adaptation"
    if transfer_density.get(conv_id, 0) >= 2:
        return "notification_pollution"
    return "task_routing"


def _match_suggestion(suggestions: list[dict], log: dict) -> dict | None:
    query = str(log.get("query_text") or "")
    for suggestion in suggestions:
        trigger_context = str(suggestion.get("trigger_context") or "")
        user_ctx = _json(trigger_context, {}).get("user_context") if trigger_context else None
        text = _latest_user_text(user_ctx) if user_ctx else ""
        if text and text in query:
            if abs(int(suggestion["created_at"] or 0) - int(log.get("created_at") or 0)) <= 120:
                return suggestion
    return None


def _legacy_classify(user_context: list[dict[str, str]]) -> str:
    """改造前二分判定的忠实重建(与旧 _classify_manual_request 同关键词表)。"""
    from app.services.realtime.task_router import ADVICE_KEYWORDS

    latest = _latest_user_text(user_context)
    if not latest:
        return "advice_request"
    import re as _re
    normalized = _re.sub(r"\s+", "", latest)
    if any(keyword in normalized for keyword in ADVICE_KEYWORDS):
        return "advice_request"
    return "direct_reply"


def _auto_expected(user_context: list[dict[str, str]], sample: dict[str, Any]) -> dict[str, Any] | None:
    """用当前任务路由器给 authored 样例自动生成预期(待人工确认)。"""
    from app.services.realtime.task_router import route_generation_task

    scopeless = sample.get("dimension") == "missing_scope_degrade" or sample.get("requires_ambiguous_twin")
    try:
        routing = route_generation_task({"user_context": user_context}, "manual_request")
    except Exception:
        return None
    needs = list(routing.knowledge_needs)
    expected = {
        "task": routing.task,
        "output": routing.output,
        "knowledge_needs": needs,
        "scope": "missing_or_ambiguous" if scopeless else "ok",
        "must_use": [],
        "forbidden": [],
        "safety": [],
        "auto_reason": routing.reason,
    }
    if routing.task == "invitation_planning":
        expected["must_use"] = ["共同游戏/对方游戏偏好类事实(若存在)"]
        expected["forbidden"] = ["无游戏关联的偏好抢占预算"]
    if routing.task == "memory_qa":
        expected["forbidden"] = ["用户口头禅/建议风格块", "建议卡片"]
    if scopeless:
        expected["safety"] = ["不得注入任何联系人历史知识", "RAG 必须 missing_scope 跳过", "仍生成通用帮助回复"]
    return expected


def _pick_anchor(dimension, conv_rotation, index, conversations, by_facts):
    if dimension in {"redaction_misfire", "task_routing"} and conv_rotation[1]:
        return conversations.get(conv_rotation[1])
    if dimension == "notification_pollution" and conv_rotation[2]:
        return conversations.get(conv_rotation[2])
    anchor_id = conv_rotation[index % len(conv_rotation)] if conv_rotation else None
    if anchor_id is None and by_facts:
        anchor_id = by_facts[index % len(by_facts)]
    return conversations.get(anchor_id) if anchor_id is not None else None


def _balance_to_target(samples, conversations, primary) -> list[dict[str, Any]]:
    """每维裁到不超配额,再全局补 authored 通用样例到 24 条。"""
    per_dim_cap = max(MIN_PER_DIMENSION, SAMPLE_TARGET // len(DIMENSIONS))
    kept: list[dict[str, Any]] = []
    counts = {dim: 0 for dim in DIMENSIONS}
    for sample in samples:  # real_log 优先保留
        dim = sample["dimension"]
        if counts[dim] < per_dim_cap + 2:
            kept.append(sample)
            counts[dim] += 1
    filler_inputs = (
        ("task_routing", [{"role": "user", "content": "帮我看看怎么回"}]),
        ("policy_adaptation", [{"role": "user", "content": "我该不该跟她表白"}]),
        ("task_routing", [{"role": "user", "content": "换个说法,短一点"}]),
        ("notification_pollution", [{"role": "user", "content": "她最近是不是很忙"}]),
    )
    filler_index = 0
    while len(kept) < SAMPLE_TARGET and primary and filler_index < len(filler_inputs) * 3:
        dimension, user_context = filler_inputs[filler_index % len(filler_inputs)]
        sample = {
            "sample_id": f"authored-filler-{filler_index:02d}",
            "dimension": dimension,
            "source": "authored",
            "input": user_context,
            "account_wxid": primary["account_wxid"],
            "conversation_id": int(primary["id"]),
            "display_name": primary["display_name"],
            "requires_ambiguous_twin": False,
            "expected": _auto_expected(user_context, {"dimension": dimension}),
            "expected_annotation": "auto_pending_human",
            "baseline": None,
            "replay": {},
        }
        kept.append(sample)
        filler_index += 1
    return kept[: max(SAMPLE_TARGET, len([s for s in kept if s["source"] == "real_log"]) + SAMPLE_TARGET)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "chrono_trace.db"))
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "docs" / "goals" / "g1-baseline-samples.json"))
    args = parser.parse_args()

    payload = load_samples(args.db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = payload["meta"]
    print(f"[G0 Loader] 样例 {meta['sample_count']} 条 → {out}")
    for dim, count in meta["dimension_coverage"].items():
        flag = "OK " if count >= MIN_PER_DIMENSION else "LOW"
        print(f"  [{flag}] {dim}: {count}")
    print(f"[G0 Loader] 冻结: commit={meta['code_commit'][:12]} db={meta['db']['path']}")
    if meta["active_model"]:
        print(f"[G0 Loader] 模型: {meta['active_model']['name']} / {meta['active_model']['model_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
