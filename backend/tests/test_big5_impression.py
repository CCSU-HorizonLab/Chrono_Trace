"""大五人格印象测试：纯函数基础层 / 双侧单调性 / LLM 有界钳制 / 脱敏红线。

内存真形表 + 构造器注入 FakeHTTP/FakeRedactor（不触发真实网络与 ONNX）。
"""
import json
import os
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.engagement_metrics as emmod
import app.services.analysis.personality_impression_service as bimod
from app.services.analysis.big5_proxies import DIMENSIONS, compute_big5_base
from app.services.analysis.personality_impression_service import (
    BIG5_LLM_ADJUST_LIMIT,
    PersonalityImpressionService,
)


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, "
        "is_sender INT, message_type INT DEFAULT 1, content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE sentiment_cache (message_id INTEGER UNIQUE, polarity INT, "
        "intensity REAL, created_at INT)"
    )
    monkeypatch.setattr(bimod, "get_db", lambda: conn)
    monkeypatch.setattr(emmod, "get_db", lambda: conn)
    yield conn
    conn.close()


def seed(db, conversation_id=1, n_each=60, start_ts=1_700_000_000):
    """双方交替文本消息；返回 (me_ids, other_ids)。"""
    me_ids, other_ids = [], []
    for i in range(n_each):
        for side, store in ((1, me_ids), (0, other_ids)):
            cur = db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (?, ?, 1, ?, ?)",
                (conversation_id, side, f"消息内容{i}", start_ts + i * 600 + side * 300),
            )
            store.append(cur.lastrowid)
    db.commit()
    return me_ids, other_ids


def seed_sentiment(db, ids, polarities, intensity=0.3):
    """给消息批量写情感缓存；polarities 循环取用。"""
    for index, mid in enumerate(ids):
        db.execute(
            "INSERT OR REPLACE INTO sentiment_cache (message_id, polarity, intensity, created_at)"
            " VALUES (?, ?, ?, 1)",
            (mid, polarities[index % len(polarities)], intensity),
        )
    db.commit()


class _FakeHTTP:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def __call__(self, *, url, payload, timeout, log, log_prefix, headers=None, max_retries=3, **kw):
        self.calls.append({"url": url, "payload": payload})
        return {"choices": [{"message": {"content": self.content}}]}


class _FakeRedactor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def redact(self, text, **kw):
        if self.fail:
            raise RuntimeError("redactor broken")
        self.calls.append(text)
        return SimpleNamespace(redacted_text=text)


def make_service(db, http=None, remote=False, redactor=None, redactor_factory=None, model=None, provider=None):
    return PersonalityImpressionService(
        http=http,
        is_remote=lambda config: remote,
        redactor_factory=redactor_factory if redactor_factory is not None else (
            (lambda: redactor) if redactor is not None else None
        ),
        model_config_provider=provider if provider is not None else (
            lambda: model if model is not None else None
        ),
    )


class TestProxies:
    def test_all_dimensions_in_range(self):
        result = compute_big5_base({
            "daily_avg": 10, "icebreak_ratio": 0.5, "emoji_exclaim_density": 0.1,
            "unanswered_rate": 0.05, "daily_cv": 0.6, "topic_continuation": 0.5,
            "intensity_variance": 0.05, "negative_ratio": 0.1, "late_night_ratio": 0.02,
            "revoke_rate": 0.005, "pos_neg_ratio": 0.8, "positive_response_rate": 0.5,
            "empathy_density": 0.03, "ttr": 0.45, "topic_entropy": 0.6, "share_density": 0.05,
        })
        assert set(result.keys()) == set(DIMENSIONS)
        for dim in DIMENSIONS:
            assert result[dim]["score"] is not None
            assert 0 <= result[dim]["score"] <= 100

    def test_missing_indicators_renormalized(self):
        """情感类指标全缺席时神经质维度仍出分（在场指标重归一）。"""
        result = compute_big5_base({
            "intensity_variance": None, "negative_ratio": None,
            "late_night_ratio": 0.3, "revoke_rate": 0.1,
        })
        assert result["neuroticism"]["score"] is not None
        used = {
            name for name, part in result["neuroticism"]["indicators"].items() if part["used"]
        }
        assert used == {"late_night_ratio", "revoke_rate"}

    def test_all_missing_dimension_none(self):
        result = compute_big5_base({})
        for dim in DIMENSIONS:
            assert result[dim]["score"] is None


class TestBaseLayer:
    def test_local_layer_without_model(self, db):
        """无 LLM：get_impressions 出双方基础层，无异常。"""
        seed(db)
        service = make_service(db)
        payload = service.get_impressions(1)
        assert payload["ok"] is True
        assert payload["source"] == "local"
        for subject in ("me", "other"):
            assert payload["subjects"][subject] is not None
            scores = payload["subjects"][subject]["scores"]
            for dim in DIMENSIONS:
                assert scores[dim]["score"] is not None

    def test_neuroticism_monotonic_seed(self, db):
        """对方高负面+高撤回+深夜 → N(other) 显著高于 N(me)。"""
        me_ids, other_ids = seed(db, n_each=80)
        seed_sentiment(db, me_ids, [1, 0])            # 我方基本正向
        seed_sentiment(db, other_ids, [-1, -1, 0])    # 对方高负面
        for i in range(15):  # 对方深夜消息
            db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, 0, 1, '深夜消息', ?)",
                (1_700_000_000 + i * 3600 + 3 * 3600,),  # 0-6 点视本地时区近似，量级已够
            )
        for i in range(10):  # 对方撤回
            db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, 0, 10000, '对方昵称撤回了一条消息', ?)",
                (1_700_100_000 + i,),
            )
        db.commit()

        service = make_service(db)
        payload = service.get_impressions(1)
        n_me = payload["subjects"]["me"]["scores"]["neuroticism"]["score"]
        n_other = payload["subjects"]["other"]["scores"]["neuroticism"]["score"]
        assert n_other > n_me

    def test_too_few_messages_returns_none(self, db):
        seed(db, n_each=10)  # 单侧 10 条 < 30
        service = make_service(db)
        payload = service.get_impressions(1)
        assert payload["subjects"]["me"] is None
        assert payload["subjects"]["other"] is None

    def test_positive_response_rate_boundaries(self, db):
        """正向回应率（归并实现）：30 分钟窗含边界、正向占比口径、无回应 None。"""
        base = 1_700_000_000
        # 对方消息作为回应锚点
        db.execute(
            "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (1, 0, 1, '锚点', ?)", (base,)
        )
        # 我方三条文本：恰 1800s（边界内，计）、1801s（窗外，不计）、同秒（计）
        cases = [(base + 1800, 1), (base + 1801, -1), (base, 1)]
        mine_ids = []
        for offset, _pol in cases:
            cur = db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, 1, 1, '回应', ?)", (offset,)
            )
            mine_ids.append((cur.lastrowid, offset, _pol))
        # 一条无情感缓存的回应消息：不进分母（JOIN sentiment_cache 口径）
        cur = db.execute(
            "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (1, 1, 1, '无缓存', ?)", (base + 60,)
        )
        assert cur.lastrowid is not None
        for mid, _offset, pol in mine_ids:
            db.execute(
                "INSERT INTO sentiment_cache (message_id, polarity, intensity, created_at)"
                " VALUES (?, ?, 0.3, 1)", (mid, pol)
            )
        db.commit()

        rate = PersonalityImpressionService._positive_response_rate(1, 1)
        # 计入回应：1800s 正向 + 同秒正向（1801s 窗外、无缓存消息不进 JOIN）
        assert rate == pytest.approx(1.0)

        # 把边界内一条改成负面：正向占比 1/2
        db.execute(
            "UPDATE sentiment_cache SET polarity = -1 WHERE message_id = ?",
            (mine_ids[0][0],)
        )
        db.commit()
        rate = PersonalityImpressionService._positive_response_rate(1, 1)
        assert rate == pytest.approx(0.5)

    def test_positive_response_rate_none_without_sentiment(self, db):
        """我方消息无情感缓存：缺缓存返回 None（不造数）。"""
        base = 1_700_000_000
        db.execute(
            "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (1, 0, 1, '锚点', ?)", (base,)
        )
        db.execute(
            "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
            " VALUES (1, 1, 1, '回应', ?)", (base + 60,)
        )
        db.commit()
        assert PersonalityImpressionService._positive_response_rate(1, 1) is None


def llm_content(adjustment=5, quote="消息内容1"):
    return json.dumps({
        dim: {"adjustment": adjustment, "reason": "证据充分", "evidence_quote": quote}
        for dim in DIMENSIONS
    }, ensure_ascii=False)


class TestEnhanceLayer:
    def test_no_model_reason(self, db):
        seed(db)
        service = make_service(db, provider=lambda: None)
        result = service.enhance(1)
        assert result["ok"] is False
        assert result["reason"] == "no_model"

    def test_adjustment_clamped(self, db):
        """模型给 +30 → 钳到 +15。"""
        seed(db)
        http = _FakeHTTP(llm_content(adjustment=30))
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        result = service.enhance(1)
        assert result["ok"] is True
        for subject in ("me", "other"):
            scores = result["subjects"][subject]["scores"]
            for dim in DIMENSIONS:
                assert scores[dim]["adjustment"] <= BIG5_LLM_ADJUST_LIMIT

    def test_evidence_not_substring_dropped(self, db):
        """evidence 非语料子串 → 证据置空，分数保留。"""
        seed(db)
        http = _FakeHTTP(llm_content(adjustment=-3, quote="这句原文里根本不存在"))
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        result = service.enhance(1)
        assert result["ok"] is True
        evidence = result["subjects"]["me"]["evidence"]
        for dim in DIMENSIONS:
            assert evidence[dim]["quote"] == ""
            assert evidence[dim]["reason"]  # reason 保留

    def test_local_model_skips_redactor(self, db):
        """本地模型免脱敏：redactor 一次都不被调用。"""
        seed(db)
        redactor = _FakeRedactor()
        http = _FakeHTTP(llm_content())
        service = make_service(
            db, http=http, remote=False, redactor=redactor,
            model={"api_base_url": "http://127.0.0.1:11434", "model_id": "qwen"},
        )
        result = service.enhance(1)
        assert result["ok"] is True
        assert redactor.calls == []

    def test_remote_redactor_failure_blocks(self, db):
        """远程 + 脱敏器构造失败 → 阻断，不落任何 llm_enhanced 行。"""
        seed(db)
        http = _FakeHTTP(llm_content())

        def broken_factory():
            raise RuntimeError("no redactor")

        service = make_service(
            db, http=http, remote=True, redactor_factory=broken_factory,
            model={"api_base_url": "https://api.example.com", "model_id": "gpt"},
        )
        result = service.enhance(1)
        assert result["ok"] is False
        assert result["reason"] == "redactor_unavailable"
        assert http.calls == []  # 未发任何请求
        rows = db.execute(
            "SELECT COUNT(*) FROM big5_impressions WHERE source = 'llm_enhanced'"
        ).fetchone()
        assert rows[0] == 0

    def test_remote_redacts_all_samples(self, db):
        """远程模型：采样逐条过脱敏器。"""
        seed(db)
        redactor = _FakeRedactor()
        http = _FakeHTTP(llm_content())
        service = make_service(
            db, http=http, remote=True, redactor=redactor,
            model={"api_base_url": "https://api.example.com", "model_id": "gpt"},
        )
        result = service.enhance(1)
        assert result["ok"] is True
        assert len(redactor.calls) > 0

    def test_cache_prefers_enhanced_and_version_invalidates(self, db):
        """llm_enhanced 未过期优先；prompt_version 旧行查不到 → 视为无缓存。"""
        seed(db)
        http = _FakeHTTP(llm_content())
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        assert service.enhance(1)["ok"] is True

        again = service.get_impressions(1)
        assert again["source"] == "llm_enhanced"
        assert len(http.calls) == 1  # 缓存命中，get_impressions 未发新请求

        # 增强行未过期：_load_cached 优先返回 llm_enhanced
        cached = service._load_cached(1, "", "me", now=int(time.time()))
        assert cached is not None and cached["source"] == "llm_enhanced"

        # 版本过滤：清掉当前版本行、只剩 version=0 的旧增强行 →
        # _load_cached 绝不能把旧版本行当当前口径缓存返回
        db.execute(
            "DELETE FROM big5_impressions WHERE prompt_version = ?",
            (bimod.BIG5_PROMPT_VERSION,),
        )
        db.execute(
            "INSERT OR REPLACE INTO big5_impressions (conversation_id, account_wxid, subject,"
            " source, prompt_version, scores_json, indicators_json, created_at, expires_at)"
            " VALUES (1, '', 'me', 'llm_enhanced', 0, '{}', NULL, 1, 9999999999)"
        )
        db.commit()
        stale = service._load_cached(1, "", "me", now=int(time.time()))
        assert stale is None or stale["source"] != "llm_enhanced"

    def test_parse_failure_returns_reason(self, db):
        seed(db)
        http = _FakeHTTP("这不是 JSON")
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        result = service.enhance(1)
        assert result["ok"] is False
        assert result["reason"] == "parse_failed"

    def test_repeated_enhance_no_drift(self, db):
        """重复增强不复合漂移：基点永远取 local 层，第二次结果与第一次一致。"""
        seed(db)
        http = _FakeHTTP(llm_content(adjustment=15, quote="消息内容1"))
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        first = service.enhance(1)
        second = service.enhance(1)
        assert len(http.calls) == 2  # 第二次真发了请求，不是缓存早退
        for subject in ("me", "other"):
            for dim in DIMENSIONS:
                assert (second["subjects"][subject]["scores"][dim]["score"]
                        == first["subjects"][subject]["scores"][dim]["score"])

    def test_prompt_preserves_sender_prefix(self, db):
        """采样行带 [我]/[TA] 前缀——丢失发送方会让 LLM 无法区分双方语言风格。"""
        seed(db)
        http = _FakeHTTP(llm_content())
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        service.enhance(1)
        user_content = http.calls[0]["payload"]["messages"][1]["content"]
        assert "[我] 消息内容" in user_content
        assert "[TA] 消息内容" in user_content

    def test_sample_dilution_keeps_late_messages(self, db):
        """抽样超字符预算时等距稀释——从头截断会让语料系统性偏向早期消息。"""
        for i in range(500):
            db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, ?, 1, ?, ?)",
                (i % 2, f"消息{i}" + "字" * 100, 1_700_000_000 + i * 3600),
            )
        db.commit()
        sample = PersonalityImpressionService._sample_conversation(1)
        assert 2 <= len(sample) <= 400
        assert sum(len(t) for _, t in sample) <= int(bimod.BIG5_SAMPLE_TARGET_CHARS * 1.1)
        # 时间分布保持：末条抽样必须是最后一条消息（关系后期语言在场）
        assert sample[-1][1].startswith("消息499")

    def test_cancel_event_blocks_before_request(self, db):
        """取消事件预先置位：不发请求直接返回 cancelled。"""
        seed(db)
        http = _FakeHTTP(llm_content())
        service = make_service(db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"})
        cancel = threading.Event()
        cancel.set()
        result = service.enhance(1, cancel_event=cancel)
        assert result["ok"] is False
        assert result["reason"] == "cancelled"
        assert http.calls == []


class _BlockingEnhanceService:
    """enhance 阻塞到放行——模拟慢 LLM 请求（90s 超时窗口）。"""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancel_events = []

    def enhance(self, conversation_id, account_wxid="", cancel_event=None, from_ts=None, to_ts=None):
        self.cancel_events.append(cancel_event)
        self.started.set()
        self.release.wait(5)
        return {"ok": True}


class TestEnhanceBridge:
    def test_single_flight_and_cancel(self):
        """同会话增强单飞：进行中重复点击拒绝；cancel_big5_impressions 置位取消事件。"""
        from app.webview.api.deep_analysis import DeepAnalysisApiMixin

        bridge = DeepAnalysisApiMixin()
        slow = _BlockingEnhanceService()
        bridge._big5_service = slow

        results = []
        t1 = threading.Thread(target=lambda: results.append(bridge.enhance_big5_impressions(1)))
        t1.start()
        assert slow.started.wait(5)

        # 单飞：第一个请求未返回期间，重复点击直接拒绝（不排队阻塞）
        second = bridge.enhance_big5_impressions(1)
        assert second["ok"] is False
        assert second["reason"] == "already_running"

        # 取消：置位进行中请求的取消事件
        assert bridge.cancel_big5_impressions(1)["ok"] is True
        assert slow.cancel_events[0].is_set()
        assert bridge.cancel_big5_impressions(2)["ok"] is False  # 无该会话任务

        slow.release.set()
        t1.join(5)
        assert results and results[0]["ok"] is True
        # 完成后事件表清空，可再次发起
        assert not bridge._big5_enhance_events

    def test_single_flight_keyed_by_window(self):
        """单飞键含窗维：同会话不同窗可并行，同窗才互斥；按窗取消只命中对应窗。"""
        from app.webview.api.deep_analysis import DeepAnalysisApiMixin

        bridge = DeepAnalysisApiMixin()
        slow = _BlockingEnhanceService()
        bridge._big5_service = slow

        t1 = threading.Thread(target=lambda: bridge.enhance_big5_impressions(1, "", 100, 200))
        t1.start()
        assert slow.started.wait(5)

        t2 = threading.Thread(target=lambda: bridge.enhance_big5_impressions(1, "", 300, 400))
        t2.start()
        deadline = time.time() + 5
        while len(slow.cancel_events) < 2 and time.time() < deadline:
            time.sleep(0.01)
        assert len(slow.cancel_events) == 2  # 不同窗并行启动，不被单飞挡住

        dup = bridge.enhance_big5_impressions(1, "", 100, 200)
        assert dup["ok"] is False and dup["reason"] == "already_running"

        assert bridge.cancel_big5_impressions(1, "", 300, 400)["ok"] is True
        assert slow.cancel_events[1].is_set()
        assert not slow.cancel_events[0].is_set()

        slow.release.set()
        t1.join(5)
        t2.join(5)
        assert not bridge._big5_enhance_events


class TestWindowedImpressions:
    """时间窗档位（表 v2）：full/custom 缓存隔离、采集穿窗、旧表 DROP 重建。"""

    def test_full_and_custom_cache_isolated(self, db):
        """full 与 custom 窗各自落行互不污染；二次调用缓存命中不重算。"""
        seed(db)
        service = make_service(db)
        w_from, w_to = 1_700_000_000, 1_700_000_000 + 3600 * 200
        full = service.get_impressions(1)
        custom = service.get_impressions(1, from_ts=w_from, to_ts=w_to)

        rows = dict(db.execute(
            "SELECT window_kind, COUNT(*) FROM big5_impressions WHERE source = 'local'"
            " GROUP BY window_kind"
        ).fetchall())
        assert rows == {"full": 2, "custom": 2}
        assert full["window"] == {"kind": "full", "from": 0, "to": 0}
        assert custom["window"] == {"kind": "custom", "from": w_from, "to": w_to}

        # 清空消息后二次调用仍原样返回（缓存命中，不重算）
        db.execute("DELETE FROM messages")
        again_full = service.get_impressions(1)
        again_custom = service.get_impressions(1, from_ts=w_from, to_ts=w_to)
        for subject in ("me", "other"):
            assert again_full["subjects"][subject]["scores"] == full["subjects"][subject]["scores"]
            assert again_custom["subjects"][subject]["scores"] == custom["subjects"][subject]["scores"]

    def test_windowed_revoke_not_counted(self, db):
        """custom 窗的撤回子指标只算窗内（内层系统消息查询穿窗）。"""
        seed(db)
        # 窗外（30 天前）对方撤回 8 次：只应进 full 的 revoke_rate
        for i in range(8):
            db.execute(
                "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (1, 0, 10000, '对方昵称撤回了一条消息', ?)",
                (1_700_000_000 - 86400 * 30 + i,),
            )
        db.commit()
        service = make_service(db)
        w_from, w_to = 1_700_000_000, 1_700_000_000 + 3600 * 200
        full = service.get_impressions(1)
        windowed = service.get_impressions(1, from_ts=w_from, to_ts=w_to)
        assert full["subjects"]["other"]["indicators"]["revoke_rate"] > 0
        assert windowed["subjects"]["other"]["indicators"]["revoke_rate"] == 0

    def test_enhance_samples_window_only(self, db):
        """按窗增强：采样语料只含窗内文本（窗外话题词绝不进 prompt）。"""
        early = 1_700_000_000
        later = early + 86400 * 30
        for i in range(40):
            for side in (1, 0):
                db.execute(
                    "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                    " VALUES (1, ?, 1, ?, ?)",
                    (side, f"早期暗号{i}", early + i * 600 + side * 300),
                )
                db.execute(
                    "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
                    " VALUES (1, ?, 1, ?, ?)",
                    (side, f"后期暗号{i}", later + i * 600 + side * 300),
                )
        db.commit()
        http = _FakeHTTP(llm_content(quote="后期暗号1"))
        service = make_service(
            db, http=http, remote=False, model={"api_base_url": "http://x", "model_id": "m"}
        )
        result = service.enhance(1, from_ts=later, to_ts=later + 86400)
        assert result["ok"] is True
        user_content = http.calls[0]["payload"]["messages"][1]["content"]
        assert "后期暗号" in user_content
        assert "早期暗号" not in user_content

    def test_old_schema_dropped_and_rebuilt(self, db):
        """v1 表（无 window 档位列）DROP 重建：旧行不复活，可继续写入查询。"""
        db.execute(
            "CREATE TABLE big5_impressions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " conversation_id INTEGER, account_wxid TEXT, subject TEXT, source TEXT,"
            " prompt_version INTEGER, scores_json TEXT, base_scores_json TEXT,"
            " evidence_json TEXT, indicators_json TEXT, model_name TEXT,"
            " created_at INTEGER, expires_at INTEGER)"
        )
        db.execute(
            "INSERT INTO big5_impressions (conversation_id, subject, source, prompt_version,"
            " scores_json, created_at, expires_at) VALUES (1, 'me', 'local', 1, '{}', 1, 9999999999)"
        )
        db.commit()
        seed(db)
        service = make_service(db)
        payload = service.get_impressions(1)
        assert payload["ok"] is True

        cols = {r[1] for r in db.execute("PRAGMA table_info(big5_impressions)")}
        assert {"window_kind", "window_from", "window_to"} <= cols
        # 重建后只剩本次新算的 local 行（旧 v1 行随 DROP 消失）
        count = db.execute("SELECT COUNT(*) FROM big5_impressions").fetchone()
        assert count[0] == 2
