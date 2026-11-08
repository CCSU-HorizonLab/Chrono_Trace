"""年度报告/纪念册数据服务测试（docs/product-redesign-2026-11.md §6.2）。

窗口口径聚合 / 专属梗两段式挖掘 / 早安晚安节奏 / 好感温度封皮降级；
§4.3 画像页的梗词典与镜像对照统计（同夹具）。
夹具与 test_share_poster_export 同款（真形表 + get_db 打桩）。
"""

import os
import sqlite3
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.deep_analysis_service as deepmod
import app.services.analysis.report_service as rmod
from app.services.analysis.report_service import ReportService
from app.webview.api.deep_analysis import DeepAnalysisApiMixin

_DAY = 86400


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE conversations (id INTEGER PRIMARY KEY, account_wxid TEXT DEFAULT '',"
        " username TEXT, display_name TEXT, nickname TEXT, avatar_path TEXT,"
        " conversation_type TEXT DEFAULT 'single', message_count INT DEFAULT 0,"
        " updated_at INT DEFAULT 0, is_deleted INT DEFAULT 0, analysis_stale INT DEFAULT 0,"
        " analysis_message_count INT DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE contacts (id INTEGER PRIMARY KEY, account_wxid TEXT DEFAULT '',"
        " username TEXT, nickname TEXT, remark TEXT, avatar_path TEXT)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT,"
        " is_sender INT, message_type INT DEFAULT 1, content TEXT, timestamp INT)"
    )
    conn.execute(
        "CREATE TABLE sentiment_cache (message_id INTEGER UNIQUE, polarity INT,"
        " intensity REAL, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INT, start_time INT, end_time INT, message_count INT,"
        " initiator TEXT, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE response_times (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " conversation_id INT, sent_message_id INT, reply_message_id INT,"
        " response_time_seconds REAL, is_abnormal INT DEFAULT 0, created_at INT)"
    )
    conn.execute(
        "CREATE TABLE affinity_scores (id INTEGER PRIMARY KEY, conversation_id INT,"
        " overall_score REAL, analysis_version INT, created_at INT)"
    )
    return conn


@pytest.fixture
def db(monkeypatch):
    conn = _make_db()
    # deep 聚合器走模块级 get_db；report/pulse/emoji 走 app.db.connection.get_db
    monkeypatch.setattr(deepmod, "get_db", lambda: conn)
    monkeypatch.setattr("app.db.connection.get_db", lambda: conn)
    yield conn
    conn.close()


def _local_noon(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").timestamp())


def _msg(conn, is_sender: int, content: str, ts: int, mtype: int = 1):
    conn.execute(
        "INSERT INTO messages (conversation_id, is_sender, message_type, content, timestamp)"
        " VALUES (1, ?, ?, ?, ?)",
        (is_sender, mtype, content, ts),
    )


class TestBuildReportPayload:
    def test_round_trip_shape(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        for i in range(6):
            _msg(db, i % 2, f"今天天气不错{i}", base + i * 3600)
        db.commit()

        out = ReportService().build_report_payload(1, base - _DAY, base + 2 * _DAY)
        assert out["ok"] is True
        assert out["kind"] == "report"
        assert out["version"] == rmod.REPORT_VERSION
        assert out["contact"]["sensitive"] is True
        assert out["stats"]["total"] == 6
        assert out["report"]["chars"] == sum(len(f"今天天气不错{i}") for i in range(6))
        assert "milestones" in out["story"] and "chemistry" in out["story"]

    def test_empty_window_rejected(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "窗外的消息", base)
        db.commit()
        out = ReportService().build_report_payload(1, base + 10 * _DAY, base + 11 * _DAY)
        assert out["ok"] is False

    def test_window_excludes_outside(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "窗内", base)
        _msg(db, 1, "窗外", base + 30 * _DAY)
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["stats"]["total"] == 1
        assert out["report"]["chars"] == len("窗内")

    def test_temperature_latest_row(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "聊一句", base)
        db.execute(
            "INSERT INTO affinity_scores (conversation_id, overall_score,"
            " analysis_version, created_at) VALUES (1, 66.0, 1, 100), (1, 82.0, 1, 200)"
        )
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["report"]["temperature"] == {"score": 82, "label": "炽热"}

    def test_temperature_window_cutoff(self, db):
        # 窗口口径：历史纪念册印「截至窗口结束」的温度——窗后跑的新分析
        # 不得穿透进旧窗口（此前取全会话最新，纪念册会印今天的温度）
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "聊一句", base)
        db.execute(
            "INSERT INTO affinity_scores (conversation_id, overall_score,"
            " analysis_version, created_at) VALUES (1, 66.0, 1, ?), (1, 90.0, 1, ?)",
            (base - 100, base + 10 * 86400),
        )
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["report"]["temperature"] == {"score": 66, "label": "温热"}
        # 窗口内从未分析过（仅窗后有行）→ 降级 None，封面只讲天数
        db.execute("DELETE FROM affinity_scores WHERE created_at < ?", (base,))
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["report"]["temperature"] is None

    def test_temperature_none_without_analysis(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "聊一句", base)
        db.commit()
        out = ReportService().build_report_payload(1, base - _DAY, base + _DAY)
        assert out["report"]["temperature"] is None


class TestMemeMining:
    def test_recurring_phrase_ranked_with_exact_counts(self, db):
        base = _local_noon("2026-03-01 08:00:00")
        # 「干饭大王」连续实词组合高频复现（双方都说）——梗页要挖的形态
        for i in range(10):
            _msg(db, 1, f"干饭大王又赢了{i}", base + i * 120)
            _msg(db, 0, f"认输吧干饭大王{i}", base + i * 120 + 60)
        db.commit()
        service = ReportService()
        memes = service._mine_memes(1, base - _DAY, base + _DAY)
        assert memes, "高频复现短语应入榜"
        hit = next(m for m in memes if m["text"] == "干饭大王")
        # 精确计数 = 含该短语的消息条数（10+10 条都含），分侧各 10
        assert hit["count"] == 20
        assert hit["me"] == 10 and hit["ta"] == 10
        # 母串（认输干饭大王）与子串（认输干饭）不重复入榜
        texts = [m["text"] for m in memes]
        assert not ("认输干饭" in texts and "认输干饭大王" in texts)
        # 等距抽样 + LIKE 计数确定性：两次挖掘结果一致
        assert service._mine_memes(1, base - _DAY, base + _DAY) == memes

    def test_rare_phrase_not_listed(self, db):
        base = _local_noon("2026-03-01 08:00:00")
        # 每条内容独有（数字打断相邻性），无任何复现短语
        for i in range(30):
            _msg(db, i % 2, f"独白{i}碎语{chr(0x4E00 + i)}", base + i * 120)
        db.commit()
        memes = ReportService()._mine_memes(1, base - _DAY, base + _DAY)
        # 无任何短语达到样本/全窗门槛 → 空榜（页面跳分镜）
        assert memes == []

    def test_like_wildcard_escaped(self, db):
        # 短语含 LIKE 通配符时精确计数不得放大（% 会匹配一切）
        assert rmod._like_escape("100%确信") == "100\\%确信"
        base = _local_noon("2026-03-01 08:00:00")
        for i in range(9):
            _msg(db, 1, "进度100%完成", base + i * 120)
        db.commit()
        count, me = ReportService()._count_phrase(1, base - _DAY, base + _DAY, "100%完成")
        assert count == 9 and me == 9

    def test_min_total_gate(self, db):
        # 样本内高频但全窗仅 6 条 < 8 门槛 → 不入榜
        base = _local_noon("2026-03-01 08:00:00")
        for i in range(6):
            _msg(db, 1, f"晚安宝贝做个好梦{i}", base + i * 120)
        db.commit()
        memes = ReportService()._mine_memes(1, base - _DAY, base + _DAY)
        assert all(m["count"] >= rmod.REPORT_MEME_MIN_TOTAL for m in memes)

    def test_forwarded_share_cards_not_memes(self, db):
        # 【淘宝】/【闲鱼】转发卡片是外部样板文：样板短语复现再多也不是你们的梗
        base = _local_noon("2026-03-01 08:00:00")
        for i in range(10):
            _msg(db, i % 2, f"【淘宝】大促价保 https://e.tb.cn/x{i} 点击链接领券", base + i * 120)
        # 同窗有真梗在聊（确保过滤只去卡片、不误伤正常挖掘）
        for i in range(10):
            _msg(db, i % 2, f"干饭大王又赢了{i}", base + 3600 + i * 120)
        db.commit()
        memes = ReportService()._mine_memes(1, base - _DAY, base + _DAY)
        texts = [m["text"] for m in memes]
        assert not any("链接" in t or "淘宝" in t or "大促" in t for t in texts), texts
        assert any(t == "干饭大王" for t in texts), texts


class TestMemePublicSafety:
    def test_entity_bearing_phrase_marked_unsafe(self):
        # 含实体形短语（手机/地址/链接）标 public_safe=False——公开版投影
        # 据此滤除；正常绰号梗不受影响
        memes = [
            {"text": "干饭大王", "count": 20, "me": 10, "ta": 10},
            {"text": "打到13800001111去", "count": 9, "me": 5, "ta": 4},
            {"text": "望京路88号院", "count": 8, "me": 4, "ta": 4},
        ]
        out = ReportService._mark_meme_public_safety(memes)
        by_text = {m["text"]: m["public_safe"] for m in out}
        assert by_text["干饭大王"] is True
        assert by_text["打到13800001111去"] is False
        assert by_text["望京路88号院"] is False

    def test_detection_failure_fails_closed(self, monkeypatch):
        # 检测抛错按不安全处理（红线方向从严），不得把未检测条目放行
        def _boom(text):
            raise RuntimeError("redactor down")

        monkeypatch.setattr(
            "app.services.realtime.privacy_redactor.PrivacyRedactor.detect_entities", _boom
        )
        out = ReportService._mark_meme_public_safety([{"text": "干饭大王"}])
        assert out[0]["public_safe"] is False


class TestMemeDictionary:
    def test_dictionary_wider_than_report_and_full_span(self, db):
        # 13 个互不包含的复现短语：报告页取 10，词典（上限 24）应收 ≥11，
        # 且跨度 = 全会话（首条→末条消息时间戳）
        base = _local_noon("2026-03-01 08:00:00")
        phrases = [
            "干饭大王", "电影周末", "奶茶火锅", "地铁末班", "猫咪午睡", "代码上线",
            "考试结束", "演唱会门票", "外卖到了", "旅游计划", "游戏开黑", "加班深夜", "下雨回家",
        ]
        ts = base
        for k, phrase in enumerate(phrases):
            for _ in range(8):
                _msg(db, 1, phrase, ts)
            ts += 3600  # 首短语在窗头、末短语在 13 小时后（全会话跨度内）
        db.commit()
        service = ReportService()
        out = service.meme_dictionary(1)
        assert out["ok"] is True
        texts = [m["text"] for m in out["items"]]
        assert len(texts) >= 11 and len(texts) <= rmod.REPORT_MEME_DICT_TOP
        assert set(texts) <= set(phrases)
        # 全会话跨度：from/to 即首末文本消息时间戳（每短语 8 条同刻，末刻 = base+12h）
        assert out["from_ts"] == base
        assert out["to_ts"] == base + 12 * 3600

    def test_dictionary_empty_conversation(self, db):
        db.execute("INSERT INTO messages (conversation_id, is_sender, content, timestamp) VALUES (1, 1, '', 100)")
        db.commit()
        assert ReportService().meme_dictionary(1)["ok"] is False


class TestMirrorStats:
    def test_sides_and_directions(self, db):
        # 方向口径：reply 的 is_sender 决定侧别——TA 回我（=0）进 ta，我回 TA（=1）进 me
        base = _local_noon("2026-03-01 12:00:00")
        msgs = [
            (1, 1, "在吗", base),           # m1 我发
            (2, 0, "嗯", base + 60),        # m2 TA 回（60s → ta）
            (3, 1, "干嘛呢", base + 100),   # m3 我发
            (4, 0, "没事", base + 220),     # m4 TA 回（120s → ta）
            (5, 0, "睡了？", base + 300),   # m5 TA 发
            (6, 1, "马上", base + 330),     # m6 我回（30s → me）
        ]
        for mid, sender, content, ts in msgs:
            db.execute(
                "INSERT INTO messages (id, conversation_id, is_sender, message_type, content, timestamp)"
                " VALUES (?, 1, ?, 1, ?, ?)",
                (mid, sender, content, ts),
            )
        for sent, reply, secs, abnormal in [(1, 2, 60, 0), (3, 4, 120, 0), (5, 6, 30, 0), (4, 5, 999, 1)]:
            db.execute(
                "INSERT INTO response_times (conversation_id, sent_message_id, reply_message_id,"
                " response_time_seconds, is_abnormal, created_at) VALUES (1, ?, ?, ?, ?, 1)",
                (sent, reply, secs, abnormal),
            )
        for initiator in ("user", "user", "user", "other"):
            db.execute(
                "INSERT INTO sessions (conversation_id, start_time, end_time, message_count,"
                " initiator, created_at) VALUES (1, 1, 2, 3, ?, 1)",
                (initiator,),
            )
        db.commit()

        from app.webview.api.analysis_read import AnalysisReadApiMixin

        res = AnalysisReadApiMixin().get_mirror_stats(1)
        assert res["ok"] is True
        # ta 侧：[60, 120] 中位数取上中位（与 get_response_time_stats 同口径）
        assert res["reply"]["ta"] == {"count": 2, "avg": 90.0, "median": 120.0}
        assert res["reply"]["me"] == {"count": 1, "avg": 30.0, "median": 30.0}
        assert res["initiative"] == {"total": 4, "me": 3, "ta": 1}
        # 字数：我 = 在吗(2)+干嘛呢(3)+马上(2)；TA = 嗯(1)+没事(2)+睡了？(3)
        assert res["volume"] == {"me_chars": 7, "ta_chars": 6}

    def test_empty_conversation_ok(self, db):
        from app.webview.api.analysis_read import AnalysisReadApiMixin

        res = AnalysisReadApiMixin().get_mirror_stats(1)
        assert res["ok"] is True
        assert res["reply"]["me"]["count"] == 0 and res["reply"]["ta"]["count"] == 0
        assert res["initiative"] == {"total": 0, "me": 0, "ta": 0}
        assert res["volume"] == {"me_chars": 0, "ta_chars": 0}


class TestRhythmAndEmoji:
    def test_greeting_rhythm_day_boundaries(self, db):
        # 一天：首条 8 点（我）→ 早安天；末条 23 点（TA）→ 晚安天
        d1 = _local_noon("2026-03-01 08:00:00")
        _msg(db, 1, "早安", d1)
        _msg(db, 0, "晚安", _local_noon("2026-03-01 23:00:00"))
        # 一天：首条 12 点（非早安）末条 21 点（非晚安）
        _msg(db, 1, "午间", _local_noon("2026-03-02 12:00:00"))
        _msg(db, 0, "傍晚", _local_noon("2026-03-02 21:00:00"))
        db.commit()
        rhythm = ReportService()._rhythm(1, _local_noon("2026-03-01 00:00:00"),
                                         _local_noon("2026-03-03 00:00:00"))
        assert rhythm["morning_days"] == 1
        assert rhythm["morning_by_me"] == 1
        assert rhythm["night_days"] == 1
        assert rhythm["night_by_me"] == 0

    def test_emoji_window_top(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "开心😂😂", base)
        _msg(db, 1, "再发😂", base + 60)
        _msg(db, 0, "对方[呲牙]", base + 120)
        _msg(db, 0, "窗外不计😂", base + 30 * _DAY)
        db.commit()
        emoji = ReportService()._window_emoji(1, base - _DAY, base + _DAY)
        assert emoji is not None
        keys_me = {(i["key"], i["count"]) for i in emoji["top_me"]}
        assert ("😂", 3) in keys_me  # 窗外那条不计
        assert any(i["key"] == "呲牙" and i["kind"] == "builtin" for i in emoji["top_ta"])

    def test_emoji_none_when_silent(self, db):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "纯文字没有任何表情", base)
        db.commit()
        assert ReportService()._window_emoji(1, base - _DAY, base + _DAY) is None


class TestBridge:
    def test_bridge_date_parsing_and_pass_through(self, db, monkeypatch):
        base = _local_noon("2026-03-01 12:00:00")
        _msg(db, 1, "窗内消息", base)
        db.commit()
        captured = {}

        class _Fake:
            def build_report_payload(self, cid, from_ts, to_ts, wxid=""):
                captured["args"] = (cid, from_ts, to_ts, wxid)
                return {"ok": True}

        monkeypatch.setattr(
            "app.services.analysis.report_service.ReportService", _Fake
        )
        bridge = DeepAnalysisApiMixin()
        out = bridge.get_report_payload(1, "2026-03-01", "2026-03-02", "wxid_x")
        assert out["ok"] is True
        cid, from_ts, to_ts, wxid = captured["args"]
        assert cid == 1 and wxid == "wxid_x"
        assert datetime.fromtimestamp(from_ts).strftime("%Y-%m-%d") == "2026-03-01"
        # to_date 收口到当日 23:59:59
        assert datetime.fromtimestamp(to_ts).strftime("%H:%M:%S") == "23:59:59"

    def test_bridge_requires_dates(self):
        bridge = DeepAnalysisApiMixin()
        assert bridge.get_report_payload(1, "", "")["ok"] is False
