"""关系体检报告导出测试：渲染完整性/转义/落盘位置。"""

import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.services.analysis.affinity_report_export as remod
from app.services.analysis.affinity_report_export import (
    AffinityReportExportError,
    export_affinity_report,
    render_affinity_report,
)


def _dim(name, score, weight, subs=None):
    return SimpleNamespace(
        name=name, score=score, weight=weight,
        weighted_score=score * weight, interpretation=f"{name}表现稳定",
        sub_scores=subs or {"daily_message": 60.0},
    )


def _result(**overrides):
    result = SimpleNamespace(
        overall_score=72.5,
        overall_interpretation="互动频繁，情感基础扎实。",
        analysis_caliber=5,
        interaction_investment=_dim("互动投入", 78.0, 0.40, {"daily_message": 80.0, "reply_symmetry": 70.0}),
        emotional_resonance=_dim("情感共鸣", 70.0, 0.35, {"bidirectional_positive": 66.0}),
        closeness_signals=_dim("亲近信号", 65.0, 0.15),
        preference_compatibility=None,
        llm_relationship=_dim("AI 关系评估", 74.0, 0.08, {"communication_quality": 70.0}),
        llm_relationship_absent_reason=None,
        risk_assessment={
            "highest_level": "留意",
            "llm_evidence_available": True,
            "signals": {
                "hot_cold": {
                    "label": "忽冷忽热", "level": "留意",
                    "stat_basis": "日消息量波动偏高", "evidence": ["前几天还天天聊"],
                    "note": "仅对话证据，统计指标未达阈值",
                },
                "one_sided": {"label": "单向投入", "level": "未见异常", "stat_basis": "未见失衡", "evidence": [], "note": ""},
            },
        },
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


# ===== 渲染 =====


def test_render_contains_all_sections():
    history = [
        {"overall_score": 71.0, "analysis_version": 5, "created_at": 1760000000},
        {"overall_score": 69.0, "analysis_version": 4, "created_at": 1750000000},
    ]
    profile = {"personality_tags": ["幽默", "话痨"], "chat_style": "语气轻松", "relationship_note": ""}

    html = render_affinity_report(
        {"display_name": "阿明"}, _result(), history, profile,
        {"message_count": 520, "active_days": 88, "first_ts": 1750000000, "last_ts": 1760000000},
    )

    assert "阿明 · 关系体检报告" in html
    assert "72" in html and "互动频繁" in html
    # 雷达 SVG：在场四维 → 四边形数据多边形
    assert "<svg" in html and "<polygon" in html
    assert "互动投入" in html and "AI 关系评估" in html
    # 权重 0 的喜好兼容缺席（None）不出现
    assert "喜好兼容度" not in html
    # 风险预警：留意 + 证据引用 + 级别配色
    assert "忽冷忽热" in html and "前几天还天天聊" in html
    assert 'class="risk-item watch"' in html and 'class="risk-item normal"' in html
    # 历史（跨口径行都展示，不做对比）
    assert "v5" in html and "v4" in html
    # 画像标签
    assert "幽默" in html
    # 页脚知情提示：报告含聊天原文摘录
    assert "原文摘录" in html
    # 单文件：内联样式、无脚本依赖
    assert "<style>" in html and "<script" not in html


def test_render_escapes_user_text():
    html = render_affinity_report(
        {"display_name": "<script>alert(1)</script>"}, _result(), [], None,
        {"message_count": 0, "active_days": 0, "first_ts": None, "last_ts": None},
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_without_risk_assessment_notes_absence():
    html = render_affinity_report(
        {"display_name": "阿明"}, _result(risk_assessment=None), [], None,
        {"message_count": 0, "active_days": 0, "first_ts": None, "last_ts": None},
    )
    assert "未包含风险预警" in html


def test_render_radar_skipped_for_few_dims():
    result = _result(
        interaction_investment=_dim("互动投入", 78.0, 0.4),
        emotional_resonance=None, closeness_signals=None, llm_relationship=None,
    )
    html = render_affinity_report(
        {"display_name": "阿明"}, result, [], None,
        {"message_count": 0, "active_days": 0, "first_ts": None, "last_ts": None},
    )
    assert "<svg" not in html  # 少于 3 维不成雷达


# ===== 落盘 =====


@pytest.fixture
def export_env(monkeypatch, tmp_path):
    """内存库 + 桩服务 + 临时导出目录。"""
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY, display_name TEXT, account_wxid TEXT)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INT, timestamp INT)")
    conn.execute("INSERT INTO conversations VALUES (1, '阿明', 'wxid_me')")
    conn.execute("INSERT INTO messages VALUES (1, 1, 1760000000)")
    conn.execute("INSERT INTO messages VALUES (2, 1, 1760000100)")

    import app.services.analysis.affinity_analysis_service as aasmod
    import app.services.analysis.affinity_history as histmod

    monkeypatch.setattr(remod, "get_db", lambda: conn)
    monkeypatch.setattr(
        aasmod, "AffinityAnalysisService",
        type("Stub", (), {"get_scores": lambda self, cid: _result()}),
    )
    monkeypatch.setattr(
        histmod, "get_recent_scores",
        lambda cid, limit=2: [{"overall_score": 71.0, "analysis_version": 5, "created_at": 1760000000}],
    )
    # 画像读取：桩返回 None（无画像分支）
    import app.services.realtime.contact_profiler as profiler_mod

    monkeypatch.setattr(
        profiler_mod, "ContactProfiler",
        type("StubProfiler", (), {"get_profile": lambda self, name, wxid="": None}),
    )
    # 导出目录指向 pytest 临时目录，不污染系统临时区
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    yield tmp_path
    conn.close()


def test_export_writes_html_into_export_dir(export_env):
    result = export_affinity_report(1)

    assert result["ok"] is True
    path = result["file_path"]
    assert "chrono_trace_export" in path and path.endswith(".html")
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert "阿明 · 关系体检报告" in content
    assert "v5" in content  # 历史来自桩


def test_export_requires_analysis_result(export_env, monkeypatch):
    import app.services.analysis.affinity_analysis_service as aasmod

    monkeypatch.setattr(
        aasmod, "AffinityAnalysisService",
        type("Empty", (), {"get_scores": lambda self, cid: None}),
    )
    with pytest.raises(AffinityReportExportError) as exc:
        export_affinity_report(1)
    assert "好感度分析" in str(exc.value)


def test_export_rejects_missing_conversation(export_env):
    with pytest.raises(AffinityReportExportError):
        export_affinity_report(99)
