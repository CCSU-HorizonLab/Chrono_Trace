"""LLM 关系评估服务测试（构造器注入 Fake，不 patch 模块）。"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.relationship_llm_service as rlmod
from app.services.analysis.engagement_metrics import EngagementMetrics
from app.services.analysis.relationship_llm_service import (
    RelationshipLLMAbsent,
    RelationshipLLMService,
)


class _FakeHTTP:
    """返回预置响应体的假 HTTP 通道。"""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    def __call__(self, *, url, payload, timeout, log, log_prefix, headers=None, max_retries=3, **kw):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeRedactor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls: list[dict] = []

    def redact(self, text, *, account_wxid, conversation_id, source_table, source_id):
        if self.fail:
            raise RuntimeError("redactor broken")
        self.calls.append({
            "text": text,
            "account_wxid": account_wxid,
            "conversation_id": conversation_id,
            "source_table": source_table,
        })
        from types import SimpleNamespace

        return SimpleNamespace(redacted_text=text.replace("13800001111", "[手机号]"))


def _model(remote_url="http://192.168.1.9:11434/v1"):
    return {"api_base_url": remote_url, "api_key": "", "model_id": "qwen", "name": "测试模型"}


def _ok_content(score=72):
    return json.dumps({
        "score": score,
        "sub_scores": {"communication_quality": 80, "relationship_warmth": 70, "risk_signals": 20},
        "evidence": [{"quote": "老王今晚吃饭不", "month": "2026-09"}],
        "insight": "双方互动频繁且积极。",
    }, ensure_ascii=False)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # 真实结构：speech_units 只存 message_ids/sender/时间戳，内容回查 messages
    conn.execute("CREATE TABLE speech_units (id INTEGER PRIMARY KEY, conversation_id INT, message_ids TEXT, sender TEXT, first_message_timestamp INT, last_message_timestamp INT, message_count INT)")
    conn.execute("CREATE TABLE interaction_pairs (id INTEGER PRIMARY KEY, conversation_id INT, from_speech_unit_id INT, to_speech_unit_id INT, time_gap INT, from_polarity INT, to_polarity INT)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, is_sender INT, content TEXT, timestamp INT)")
    conn.execute("CREATE TABLE message_preprocessed (message_id INTEGER PRIMARY KEY, cleaned_content TEXT)")
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, conversation_id INT, start_time INT, end_time INT, initiator TEXT)")
    yield conn
    conn.close()


def seed_pair(db, pid, ts, polarity=1, text="样本"):
    """按指定时间/极性/文本种一对交互（from=对方，to=我）。"""
    mid_f, mid_t = 10_000 + 2 * pid, 10_001 + 2 * pid
    db.execute(
        "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
        (mid_f, f"{text}{pid}", ts),
    )
    db.execute(
        "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
        (mid_t, f"回复{pid}", ts + 30),
    )
    db.execute(
        "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 1)",
        (2 * pid + 1, str(mid_f), ts, ts),
    )
    db.execute(
        "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 1)",
        (2 * pid + 2, str(mid_t), ts + 30, ts + 30),
    )
    db.execute(
        "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 30, ?, ?)",
        (pid, 2 * pid + 1, 2 * pid + 2, polarity, polarity),
    )


def seed_pairs(db, n=20, base_ts=None):
    base = base_ts or int(datetime(2026, 9, 1, 10, 0).timestamp())
    for i in range(n):
        # 每个单元两条消息，验证 message_ids 回查与拼接
        f_ids, t_ids = [], []
        for j, text in enumerate((f"对方消息{i}甲", f"对方消息{i}乙：最近怎么样")):
            mid = 4 * i + j + 1
            db.execute(
                "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
                (mid, text, base + 3600 * i + j * 5),
            )
            db.execute(
                "INSERT INTO message_preprocessed (message_id, cleaned_content) VALUES (?, ?)",
                (mid, text),
            )
            f_ids.append(mid)
        for j, text in enumerate((f"我方回复{i}甲", "挺好的")):
            mid = 4 * i + 2 + j + 1
            db.execute(
                "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
                (mid, text, base + 3600 * i + 60 + j * 5),
            )
            db.execute(
                "INSERT INTO message_preprocessed (message_id, cleaned_content) VALUES (?, ?)",
                (mid, text),
            )
            t_ids.append(mid)
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 2)",
            (2 * i + 1, ",".join(map(str, f_ids)), base + 3600 * i, base + 3600 * i + 5),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 2)",
            (2 * i + 2, ",".join(map(str, t_ids)), base + 3600 * i + 60, base + 3600 * i + 65),
        )
        db.execute(
            "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 60, 1, 1)",
            (i + 1, 2 * i + 1, 2 * i + 2),
        )
    db.commit()


@pytest.fixture(autouse=True)
def patch_db(db, monkeypatch):
    monkeypatch.setattr(rlmod, "get_db", lambda: db)


def test_evaluate_parses_score_and_subscores(db):
    seed_pairs(db)
    http = _FakeHTTP(_ok_content())
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 72
    assert result["sub_scores"]["communication_quality"] == 80
    assert result["evidence"][0]["quote"] == "老王今晚吃饭不"
    assert result["meta"]["sampled_pairs"] >= 10


def test_thinking_model_content_parses(db):
    seed_pairs(db)
    content = "<think>推理过程省略 {\"score\": 10}</think>" + _ok_content(65)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 65


def test_invalid_json_raises_absent(db):
    seed_pairs(db)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP("抱歉我无法输出"), is_remote=lambda m: False)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)


def test_parse_failure_retries_once_and_recovers(db):
    """解析失败自动重试一次：小模型偶发不吐 JSON，同输入重跑即恢复。"""
    seed_pairs(db)

    class _FlakyHTTP(_FakeHTTP):
        def __call__(self, **kw):
            if len(self.calls) == 0:
                super().__call__(**kw)
                self.content = _ok_content()  # 第二次起返回合法 JSON
            return super().__call__(**kw)

    http = _FlakyHTTP("这次我先啰嗦几句不输出 JSON")
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] > 0
    assert len(http.calls) == 2


def test_parse_failure_after_retry_raises_absent(db):
    """重试仍不吐 JSON 才判缺席，错误信息注明已重试。"""
    seed_pairs(db)
    http = _FakeHTTP("抱歉我无法输出")
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    with pytest.raises(RelationshipLLMAbsent, match="已重试"):
        svc.evaluate(1)
    assert len(http.calls) == 2


def test_remote_without_redactor_raises_absent(db):
    seed_pairs(db)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: True, redactor_factory=None)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)


def test_remote_redacts_each_message_with_scope_ids(db):
    seed_pairs(db, n=15)
    redactor = _FakeRedactor()
    svc = RelationshipLLMService(
        _model(),
        http=_FakeHTTP(_ok_content()),
        is_remote=lambda m: True,
        redactor_factory=lambda: redactor,
    )
    result = svc.evaluate(1, account_wxid="wxid_a")
    assert result["score"] == 72
    assert len(redactor.calls) >= 20  # 每对两条均脱敏
    assert all(c["source_table"] == "affinity_relationship_llm" for c in redactor.calls)
    assert all(c["account_wxid"] == "wxid_a" for c in redactor.calls)


def test_local_model_skips_redaction(db):
    seed_pairs(db)
    redactor = _FakeRedactor()
    svc = RelationshipLLMService(
        _model(remote_url="http://127.0.0.1:11434/v1"),
        http=_FakeHTTP(_ok_content()),
        is_remote=lambda m: False,
        redactor_factory=lambda: redactor,
    )
    svc.evaluate(1)
    assert redactor.calls == []


def test_sampling_windows_cover_origin_conflict_recent_and_icebreak(db):
    """四窗分层：起源（极性均衡）/ 高冲突 / 近期 / 破冰各窗均有代表。"""
    # 起源：2026-01 前三周，正负交替、负向分散（单周负向 ≤4）
    base = datetime(2026, 1, 5, 10, 0)
    for i in range(16):
        polarity = 1 if i % 2 == 0 else -1
        text = "正向" if polarity == 1 else "负向"
        seed_pair(db, i + 1, int((base + timedelta(hours=30 * i)).timestamp()),
                  polarity=polarity, text=text)
    # 高冲突：2026-05-10 起一周内 10 条负向（密度最高周桶）
    conflict_base = datetime(2026, 5, 10, 10, 0)
    for i in range(10):
        seed_pair(db, 100 + i, int((conflict_base + timedelta(hours=4 * i)).timestamp()),
                  polarity=-1, text="高冲突")
    # 近期：5 天前 5 条正向
    recent_base = datetime.now() - timedelta(days=5)
    for i in range(5):
        seed_pair(db, 200 + i, int((recent_base + timedelta(hours=i)).timestamp()),
                  polarity=1, text="近期样本")
    # 破冰：1/20 与 1/25 两会话间隔 5 天 > 24h，恢复轮在 1/25
    db.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, initiator) VALUES (1, 1, ?, ?, 'other')",
        (int(datetime(2026, 1, 20, 20, 0).timestamp()), int(datetime(2026, 1, 20, 21, 0).timestamp())),
    )
    db.execute(
        "INSERT INTO sessions (id, conversation_id, start_time, end_time, initiator) VALUES (2, 1, ?, ?, 'other')",
        (int(datetime(2026, 1, 25, 20, 0).timestamp()), int(datetime(2026, 1, 25, 21, 0).timestamp())),
    )
    seed_pair(db, 300, int(datetime(2026, 1, 25, 20, 5).timestamp()),
              polarity=1, text="破冰恢复")
    db.commit()

    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    pairs = svc._sample_interaction_pairs(1)

    assert len(pairs) <= rlmod.MAX_PAIRS
    months = {p["month"] for p in pairs}
    joined = " ".join(p["from_text"] for p in pairs)
    assert "2026-01" in months          # 起源窗在场
    assert "高冲突" in joined            # 高冲突窗（负向密度最高周）
    assert "近期样本" in joined          # 近期窗
    assert "破冰恢复" in joined          # 破冰窗
    # 起源窗内极性均衡：正负样本都在
    jan_texts = " ".join(p["from_text"] for p in pairs if p["month"] == "2026-01")
    assert "正向" in jan_texts and "负向" in jan_texts


def test_prompt_includes_metrics_summary_when_provided(db):
    seed_pairs(db)
    http = _FakeHTTP(_ok_content())
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    metrics = EngagementMetrics(
        text_message_count=520, self_text_count=200, other_text_count=320,
        long_unanswered_other=9, perfunctory_rate_other=0.22,
    )
    svc.evaluate(1, metrics=metrics)
    with_summary = http.calls[0]["payload"]["messages"][1]["content"]
    assert "【统计概要】" in with_summary
    assert "长时未回应：对方 9 次" in with_summary
    assert "敷衍回复率：对方 22%" in with_summary

    svc.evaluate(1)
    without_summary = http.calls[1]["payload"]["messages"][1]["content"]
    assert "【统计概要】" not in without_summary


def test_risk_evidence_normalized_with_all_four_keys(db):
    seed_pairs(db)
    content = json.dumps({
        "score": 60,
        "sub_scores": {"communication_quality": 60, "relationship_warmth": 55},
        "risk_evidence": {
            # 一条真引文（采样语料含「最近怎么样」）+ 一条编造：编造被校验丢弃
            "hot_cold": {"found": True, "quotes": ["最近怎么样", "我编造的引文"]},
            "one_sided": {"found": False, "quotes": []},
            "reality_denial": ["挺好的"],
        },
        "evidence": [],
        "insight": "x",
    }, ensure_ascii=False)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)

    evidence = result["risk_evidence"]
    assert set(evidence) == set(rlmod.RISK_EVIDENCE_KEYS)
    # 真引文保留、编造引文丢弃，found 不受影响
    assert evidence["hot_cold"]["found"] is True
    assert evidence["hot_cold"]["quotes"] == ["最近怎么样"]
    assert evidence["one_sided"]["found"] is False
    # 宽容形态：直接给引文列表视为 found 且带证据（语料含「挺好的」）
    assert evidence["reality_denial"]["found"] is True
    assert evidence["reality_denial"]["quotes"] == ["挺好的"]
    # 缺席键补 false；risk_signals 子分已随口径升级移除
    assert evidence["warm_then_cold"]["found"] is False
    assert "risk_signals" not in result["sub_scores"]


def test_risk_evidence_fabricated_quotes_dropped_and_downgraded(db):
    """引文全部与采样原文对不上（或给不出引文）：不得作为对话证据。"""
    seed_pairs(db)
    content = json.dumps({
        "score": 60,
        "sub_scores": {"communication_quality": 60, "relationship_warmth": 55},
        "risk_evidence": {
            "hot_cold": {"found": True, "quotes": ["完全编造的引文"]},
            "reality_denial": {"found": True, "quotes": []},
        },
        "evidence": [],
        "insight": "x",
    }, ensure_ascii=False)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)

    evidence = result["risk_evidence"]
    # 编造引文丢弃且 found 降级——双证据判定的「对话证据」一方不成立
    assert evidence["hot_cold"]["found"] is False
    assert evidence["hot_cold"]["quotes"] == []
    # found=True 但给不出任何引文：同样不算对话证据
    assert evidence["reality_denial"]["found"] is False


def test_prompt_includes_relationship_context_labels(db):
    seed_pairs(db)
    http = _FakeHTTP(_ok_content())
    svc = RelationshipLLMService(_model(), http=http, is_remote=lambda m: False)
    svc.evaluate(1, context={"relationship_type": "朋友", "interaction_duration": "1-3年", "communication_style": "轻松"})
    user_content = http.calls[0]["payload"]["messages"][1]["content"]
    assert "关系类型：朋友" in user_content
    assert "认识时长：1-3年" in user_content
    assert "沟通风格：轻松" in user_content


def test_score_clamped_and_evidence_capped(db):
    seed_pairs(db)
    content = json.dumps({
        "score": 250,
        "sub_scores": {"communication_quality": -5, "relationship_warmth": 999, "risk_signals": 40},
        "evidence": [{"quote": f"证据{i}", "month": "2026-09"} for i in range(9)],
        "insight": "x",
    }, ensure_ascii=False)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 100
    assert result["sub_scores"]["communication_quality"] == 0
    assert result["sub_scores"]["relationship_warmth"] == 100
    assert len(result["evidence"]) == 5


def test_insufficient_pairs_raises_absent(db):
    seed_pairs(db, n=5)
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)


def test_input_char_budget_drops_oldest_pairs(db):
    # 单元文本超长，触发预算裁剪：保留的是较新的对
    base = int(datetime(2026, 9, 30).timestamp())
    for i in range(60):
        ts = base + 3600 * i
        mid_f, mid_t = 4 * i + 1, 4 * i + 2
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
            (mid_f, f"很长的消息内容{'x' * 200}编号{i}", ts),
        )
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
            (mid_t, f"很长的回复{'y' * 200}编号{i}", ts + 30),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 1)",
            (2 * i + 1, str(mid_f), ts, ts),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 1)",
            (2 * i + 2, str(mid_t), ts + 30, ts + 30),
        )
        db.execute(
            "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 30, 0, 0)",
            (i + 1, 2 * i + 1, 2 * i + 2),
        )
    db.commit()
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    pairs = svc._sample_interaction_pairs(1)
    total = sum(len(p["from_text"]) + len(p["to_text"]) for p in pairs)
    assert total <= rlmod.MAX_TOTAL_INPUT_CHARS
    assert len(pairs) >= rlmod.MIN_PAIRS


def test_budget_trim_in_recent_window_keeps_newest(db):
    """近期窗预算裁剪丢最旧：降序取数的窗不得因 pop(0) 丢掉最新样本。

    四窗全满（12+12+12+6=42 对）先触发 MAX_PAIRS=40，再触发 8000 字符
    预算；所有文本饱和到单元截断上限（120×2/对），近期窗 12 对满额为
    严格最大占用窗，预算裁剪首轮必动近期窗——修复前其降序排列会让
    pop(0) 丢掉最新样本。
    """
    now = int(datetime.now().timestamp())
    day = 86400

    def seed_pair_full(pid, ts, polarity=0):
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 0, ?, ?)",
            (4 * pid + 1, f"编号{pid}：{'x' * 300}", ts),
        )
        db.execute(
            "INSERT INTO messages (id, conversation_id, is_sender, content, timestamp) VALUES (?, 1, 1, ?, ?)",
            (4 * pid + 2, f"编号{pid}回：{'y' * 300}", ts + 30),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'other', ?, ?, 1)",
            (2 * pid + 1, str(4 * pid + 1), ts, ts),
        )
        db.execute(
            "INSERT INTO speech_units (id, conversation_id, message_ids, sender, first_message_timestamp, last_message_timestamp, message_count) VALUES (?, 1, ?, 'user', ?, ?, 1)",
            (2 * pid + 2, str(4 * pid + 2), ts + 30, ts + 30),
        )
        db.execute(
            "INSERT INTO interaction_pairs (id, conversation_id, from_speech_unit_id, to_speech_unit_id, time_gap, from_polarity, to_polarity) VALUES (?, 1, ?, ?, 30, ?, 0)",
            (pid + 1, 2 * pid + 1, 2 * pid + 2, polarity),
        )

    # 起源窗（最老 24 取数内的前 12）：i0-11 + 12 个垫底对（均衡后丢弃）
    for i in range(12):
        seed_pair_full(i, now - 60 * day + i * 60)
    for i in range(54, 66):
        seed_pair_full(i, now - 59 * day + (i - 54) * 60)
    # 高冲突窗：i12-23 全负向、同一时刻（7 天桶不跨界）
    for i in range(12, 24):
        seed_pair_full(i, now - 20 * day, polarity=-1)
    # 近期窗候选：i24-47（近 5 天内，降序取最新 12 = i36-47）
    for i in range(24, 48):
        seed_pair_full(i, now - 5 * day + (i - 24) * 3600)
    # 破冰窗：i48-53 为 6 个 >24h 间隔会话的首对（降序产出）
    for k in range(6):
        seed_pair_full(48 + k, now - (45 - 3 * k) * day)
    db.execute(
        "INSERT INTO sessions (conversation_id, start_time, end_time, initiator) VALUES (1, ?, ?, 'other')",
        (now - 47 * day, now - 47 * day + 3600),
    )
    for k in range(6):
        start = now - (45 - 3 * k) * day
        db.execute(
            "INSERT INTO sessions (conversation_id, start_time, end_time, initiator) VALUES (1, ?, ?, 'user')",
            (start, start + 3600),
        )
    db.commit()

    svc = RelationshipLLMService(_model(), http=_FakeHTTP(_ok_content()), is_remote=lambda m: False)
    pairs = svc._sample_interaction_pairs(1)
    texts = "\n".join(p["from_text"] for p in pairs)
    total = sum(len(p["from_text"]) + len(p["to_text"]) for p in pairs)

    assert total <= rlmod.MAX_TOTAL_INPUT_CHARS
    assert "编号47：" in texts  # 近期窗最新样本必须保留
    assert "编号36：" not in texts  # 近期窗最旧样本被裁
    assert "编号0：" in texts  # 起源窗最老样本（关系起点基线）必须保留
    assert "编号11：" not in texts  # 起源窗从新端裁
    assert "编号53：" in texts  # 破冰窗最新一次恢复轮保留


def test_drop_window_edge_per_window_semantics():
    """裁剪端点按窗语义：起源窗保最老端，其余窗保最新端。"""
    origin = ("origin", ["最老", "中间", "最新"])
    recent = ("recent", ["最老", "中间", "最新"])
    conflict = ("conflict", ["最老", "中间", "最新"])
    icebreak = ("icebreak", ["最老", "中间", "最新"])

    assert RelationshipLLMService._drop_window_edge(origin) == "最新"
    assert RelationshipLLMService._drop_window_edge(recent) == "最老"
    assert RelationshipLLMService._drop_window_edge(conflict) == "最老"
    assert RelationshipLLMService._drop_window_edge(icebreak) == "最老"


def test_nan_or_null_scores_raise_absent_not_default(db):
    """无效分值（NaN/null/缺字段）判缺席，不再静默落默认分。

    此前 _clamp：null→50（编造中位分）、NaN 经 min/max 比较短路→100
    （虚高满分）——坏输出被包装成正常分数写进缓存与总分。
    """
    import math as _math

    def _content_with(score, sub):
        return json.dumps({
            "score": score,
            "sub_scores": {"communication_quality": sub, "relationship_warmth": 70},
            "evidence": [],
            "insight": "x",
        })

    cases = [
        ("主分 NaN", _content_with(float("nan"), 80)),
        ("主分 null", _content_with(None, 80)),
        ("子分 NaN", _content_with(72, float("nan"))),
        ("子分 null", _content_with(72, None)),
        ("子分字符串", _content_with(72, "很高")),
    ]
    seed_pairs(db)  # evaluate 只读库，一次 seed 全用例复用
    for label, content in cases:
        svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
        with pytest.raises(RelationshipLLMAbsent, match="无效分值"):
            svc.evaluate(1)

    # 主分整个键缺失：候选筛选层即拒（消息为「未包含可解析的 JSON」），同判缺席
    no_score = json.dumps({"sub_scores": {"communication_quality": 80, "relationship_warmth": 70}})
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(no_score), is_remote=lambda m: False)
    with pytest.raises(RelationshipLLMAbsent):
        svc.evaluate(1)
        # 结果里绝不出现编造的默认分（50）或 NaN 短路满分（100）
        del svc


def test_out_of_range_scores_still_clamped(db):
    """正常数值越界仍按 [0,100] 截断（原 clamp 语义保留）。"""
    seed_pairs(db)
    content = json.dumps({
        "score": 250,
        "sub_scores": {"communication_quality": -30, "relationship_warmth": 70},
        "evidence": [],
        "insight": "x",
    })
    svc = RelationshipLLMService(_model(), http=_FakeHTTP(content), is_remote=lambda m: False)
    result = svc.evaluate(1)
    assert result["score"] == 100
    assert result["sub_scores"]["communication_quality"] == 0
