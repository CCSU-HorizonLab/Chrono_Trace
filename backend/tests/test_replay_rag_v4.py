"""Tests for the reproducible three-track replay runner."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.rag_store import RagStore
from scripts.replay_rag_v4 import replay


class FakeRetriever:
    def retrieve(self, **kwargs):
        return {
            "items": [{"document_id": 1, "score": 0.82}],
            "strategy": "facts",
            "status": {"status": "ready"},
            "elapsed_ms": 2,
        }


def test_replay_copies_source_and_writes_all_three_tracks(tmp_path):
    source_path = tmp_path / "source.sqlite3"
    output_path = tmp_path / "replay.sqlite3"
    conn = sqlite3.connect(source_path)
    conn.row_factory = sqlite3.Row
    store = RagStore(conn)
    store.upsert_status("account-a", 1, status="ready", document_count=0, vector_count=0)
    conn.commit()
    conn.close()

    manifest = replay(
        source_path,
        output_path,
        [{"id": "coffee", "query_text": "她喜欢什么咖啡？", "expected_scope": "all"}],
        account_wxid="account-a",
        conversation_id=1,
        retriever=FakeRetriever(),
    )
    assert manifest["rows_written"] == 3
    assert manifest["rows_by_track"] == {"no_rag": 1, "document_rag": 1, "fact_path": 1}
    assert manifest["errors"] == []

    source = sqlite3.connect(source_path)
    replayed = sqlite3.connect(output_path)
    assert source.execute("select count(*) from rag_retrieval_logs").fetchone()[0] == 0
    rows = replayed.execute(
        "select retrieval_source, rag_enabled, document_ids_json, fact_ids_json "
        "from rag_retrieval_logs order by id"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0][0] == "none" and rows[0][1] == 0
    assert rows[1][0] == "document" and json.loads(rows[1][2]) == [1]
    assert rows[2][0] == "fact" and json.loads(rows[2][3]) == [1]
