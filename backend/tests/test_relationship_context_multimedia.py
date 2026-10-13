"""关系上下文服务多媒体阈值测试（亲密/同事等关系的语音视频期望频次）。

多媒体加分本体随态度倾向解体迁入亲近信号（closeness_signals_service），
阈值随关系类型的口径不变。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analysis.relationship_context_service import (
    RelationshipContext,
    RelationshipContextService,
)


class TestRelationshipContextServiceMediaThresholds:
    def test_returns_friend_defaults_without_context(self, monkeypatch):
        service = RelationshipContextService()
        monkeypatch.setattr(service, "get_context", lambda conversation_id: None)

        result = service.get_multimedia_thresholds(1)

        assert result == {
            "relationship_type": "friend",
            "video": 3.0,
            "voice": 20.0,
        }

    def test_thresholds_cover_all_relationship_types(self, monkeypatch):
        service = RelationshipContextService()

        expected = {
            "lover": (4.0, 20.0),
            "crush": (4.0, 20.0),
            "friend": (3.0, 20.0),
            "family": (3.0, 20.0),
            "colleague": (1.0, 10.0),
            "other": (1.0, 10.0),
        }
        for relationship_type, (video, voice) in expected.items():
            ctx = RelationshipContext(relationship_type=relationship_type)
            monkeypatch.setattr(service, "get_context", lambda cid, ctx=ctx: ctx)

            result = service.get_multimedia_thresholds(1)

            assert result["relationship_type"] == relationship_type
            assert result["video"] == video
            assert result["voice"] == voice
