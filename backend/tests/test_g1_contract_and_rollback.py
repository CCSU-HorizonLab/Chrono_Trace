"""复审修复回归:输出契约校验层、NLI 指纹一致性、按联系人回滚。"""

import os
import sqlite3
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.suggestion_engine import SuggestionResult
from app.services.realtime.rag.store import RagStore
from backend.scripts.g1_e2e_report import (
    _outputs_fingerprint,
    check_quality_redline,
)
from backend.scripts.g1_rollback_contact import (
    apply_rollback,
    list_conversations,
    resolve_conversation,
)


def _result(reply="", summary="", speeches=None):
    return SuggestionResult(
        trigger_type="manual_request", intent="maintain",
        summary=summary, speeches=speeches or [], reply=reply,
    )


def _ctx(transfer_count=2):
    return {"_window_transfer_event_count": transfer_count}


def test_transfer_inference_violation_detected():
    engine = LLMSuggestionEngine()
    result = _result(reply="不讨厌。你俩还来回转了49.52，关系正常得很。")
    violations = engine._check_output_contracts(result, _ctx())
    assert any("资金推断" in v for v in violations)


def test_transfer_inference_in_speeches_detected():
    engine = LLMSuggestionEngine()
    result = _result(speeches=["她都收你转账了,说明态度挺好的"])
    assert engine._check_output_contracts(result, _ctx())


def test_factual_transfer_statement_not_flagged():
    engine = LLMSuggestionEngine()
    result = _result(reply="她已经收了转账。态度要看她文字回复,别拿钱判断。")
    # 第二句是元规则说明(转账+判断但无关系结论词)——不应误报
    assert engine._check_output_contracts(result, _ctx()) == []


def test_no_transfer_events_skips_check():
    engine = LLMSuggestionEngine()
    result = _result(reply="她收了转账,关系正常得很。")
    assert engine._check_output_contracts(result, _ctx(transfer_count=0)) == []


def test_repair_prompt_contains_hard_constraint():
    engine = LLMSuggestionEngine()
    prompt = engine._build_contract_repair_prompt("原prompt", ["资金推断(reply):「xx」"])
    assert "硬性约束" in prompt
    assert "不能用来推断对方态度" in prompt
    assert "原prompt" in prompt


def test_fingerprint_consistent_between_judge_subset_and_report_subset():
    """复审 1:judge 对 g1 子集算指纹;报告比对必须用同一子集。"""
    results = {
        ("s1", "g1"): {"output": {"summary": "a", "speeches": ["x"]}},
        ("s1", "legacy"): {"output": {"summary": "b"}},
        ("s2", "g1"): {"output": {"summary": "c"}},
        ("s2", "no_rag"): {"output": {"summary": "d"}},
    }
    judge_side = _outputs_fingerprint({"s1": results[("s1", "g1")], "s2": results[("s2", "g1")]})
    report_side = _outputs_fingerprint({k: v for k, v in results.items() if k[1] == "g1"})
    assert judge_side == report_side  # 修复前:报告对全链路计算,永不相等


def test_quality_redline_catches_engine_warnings_and_scan():
    results = {
        ("s1", "g1"): {
            "output": {
                "summary": "ok", "reply": "", "speeches": [],
                "contract_warnings": ["资金推断(reply):「转账,关系正常」"],
            },
            "context_snapshot": {"recent_window": []},
        },
        ("s2", "g1"): {
            "output": {"summary": "她收了钱", "reply": "", "speeches": []},
            "context_snapshot": {"recent_window": [{"sender": "friend", "content": "￥40.00 已收款 微信转账"}]},
        },
        ("s3", "g1"): {
            "output": {"summary": "正常回答", "reply": "正常", "speeches": []},
            "context_snapshot": {"recent_window": [{"sender": "friend", "content": "在忙"}]},
        },
    }
    check = check_quality_redline(results)
    assert check["status"] == "fail"
    sources = {v["source"] for v in check["violations"]}
    assert "engine_contract" in sources
    # s2:窗口有资金事件,但输出无关系结论词 → 不算违规
    assert not any(v["sample_id"] == "s2" for v in check["violations"])


def test_quality_redline_incomplete_when_missing():
    check = check_quality_redline({})
    assert check["status"] == "incomplete"
    assert check["pass"] is False


def _rollback_db(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, account_wxid TEXT, display_name TEXT,
            username TEXT, is_deleted INTEGER DEFAULT 0, message_count INTEGER DEFAULT 0
        );
        INSERT INTO conversations (account_wxid, display_name, username) VALUES ('wxid_a', '甲', 'u1');
        """
    )
    conn.commit()
    from app.services.realtime.rag.store import RagStore

    RagStore(conn)  # 建齐 rag_index_status 等 RAG 表
    conn.commit()
    conn.close()


def test_rollback_dry_run_does_not_write(tmp_path, capsys):
    db = tmp_path / "rb.db"
    _rollback_db(db)
    apply_rollback(str(db), "wxid_a", 1, mode="documents", disable=False, enable=False, yes=False)
    out = capsys.readouterr().out
    assert "dry-run" in out
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM rag_index_status").fetchone()[0] == 0  # 未写入任何行
    conn.close()


def test_rollback_sets_fact_read_mode_and_keeps_data(tmp_path):
    db = tmp_path / "rb.db"
    _rollback_db(db)
    # 预置一行状态与事实,验证回滚只改模式不删数据
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("wxid_a", 1, status="ready", fact_read_mode="facts")
    store.upsert_fact(account_wxid="wxid_a", conversation_id=1, subject="共同", kind="event", content="一起玩过游戏")
    conn.commit()
    conn.close()

    apply_rollback(str(db), "wxid_a", 1, mode="documents", disable=False, enable=False, yes=True)

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    status = dict(conn.execute("SELECT fact_read_mode FROM rag_index_status WHERE conversation_id=1").fetchone())
    facts = conn.execute("SELECT COUNT(*) c FROM rag_facts").fetchone()["c"]
    conn.close()
    assert status["fact_read_mode"] == "documents"
    assert facts == 1  # 回滚不删事实

    # 恢复 inherit
    apply_rollback(str(db), "wxid_a", 1, mode="inherit", disable=False, enable=False, yes=True)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT fact_read_mode FROM rag_index_status WHERE conversation_id=1").fetchone()["fact_read_mode"] == "inherit"
    conn.close()


def test_resolve_conversation_rejects_foreign_and_ambiguous(tmp_path):
    db = tmp_path / "rb2.db"
    _rollback_db(db)
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO conversations (account_wxid, display_name, username) VALUES ('wxid_a', '甲', 'u2')")  # 同名第二个
    conn.commit()
    conn.close()

    assert resolve_conversation(str(db), "wxid_a", 1, "") == 1
    try:
        resolve_conversation(str(db), "wxid_a", 999, "")
        raise AssertionError("应拒绝不属于该账号的会话")
    except SystemExit:
        pass
    try:
        resolve_conversation(str(db), "wxid_a", None, "甲")
        raise AssertionError("应拒绝同名歧义")
    except SystemExit:
        pass


def test_list_conversations_shows_modes(tmp_path):
    db = tmp_path / "rb3.db"
    _rollback_db(db)
    rows = list_conversations(str(db), "wxid_a")
    assert len(rows) == 1
    assert rows[0]["fact_read_mode"] is None  # 未建索引 → 显示为 inherit 语义
