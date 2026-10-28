"""LLM 模型配置桥接测试：密钥明文不回传、编辑不重输密钥不被清空。

历史缺陷（审查确认）：
1. get_llm_models 列表把明文 api_key 原样回传前端（bridge 返回值直进
   JS 上下文，devtools/内存快照可见），api_key_masked 只是附加展示字段；
2. save_llm_model 更新分支无条件写 api_key=''——编辑表单从不回显密钥，
   保存即把已配置密钥静默清空，下次 LLM 调用 401 才被发现。
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

import pytest

import app.db.connection as db_connection
from app.webview.api.llm_models import LlmModelsApiMixin


@pytest.fixture
def api(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db_connection, "get_db", lambda: conn)
    # 激活分支会构造 RealtimeMonitorService 同步建议引擎——mock 掉避免真服务副作用
    monkeypatch.setattr(
        "app.services.realtime.monitor_service.RealtimeMonitorService", MagicMock()
    )
    instance = LlmModelsApiMixin()
    instance._conn = conn
    # get_llm_models 内建表；save 依赖表已存在
    instance.get_llm_models()
    yield instance
    conn.close()


def _stored_key(api) -> str:
    row = api._conn.execute("SELECT api_key FROM llm_models").fetchone()
    return row["api_key"] or ""


def _save(api, **overrides):
    model = {
        "name": "测试模型",
        "provider": "deepseek",
        "model_id": "deepseek-chat",
        "api_base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-abcdefghijklmnop",
        "is_active": False,
        "temperature": 0.7,
        "extra_body": "",
    }
    model.update(overrides)
    result = api.save_llm_model(model)
    assert result["ok"] is True, result.get("error")


def test_list_never_returns_plaintext_key(api):
    """列表回传不得携带明文 api_key——只有 masked 摘要。"""
    _save(api)
    models = api.get_llm_models()["models"]
    assert len(models) == 1
    assert "api_key" not in models[0]
    assert "sk-abcdefghijklmnop" not in str(models)
    assert models[0]["api_key_masked"].startswith("sk-a")
    assert models[0]["api_key_masked"].endswith("mnop")


def test_update_without_key_preserves_stored_key(api):
    """编辑保存不带密钥（前端不回显、空串提交）：原密钥保留不被清空。"""
    _save(api, api_key="sk-abcdefghijklmnop")
    row = api._conn.execute("SELECT id FROM llm_models").fetchone()
    _save(api, id=row["id"], api_key="")
    assert _stored_key(api) == "sk-abcdefghijklmnop"


def test_update_with_new_key_overwrites(api):
    """重输新密钥则覆盖旧值。"""
    _save(api, api_key="sk-old-key-000000000")
    row = api._conn.execute("SELECT id FROM llm_models").fetchone()
    _save(api, id=row["id"], api_key="sk-new-key-111111111")
    assert _stored_key(api) == "sk-new-key-111111111"


def test_new_model_without_key_stores_empty(api):
    """新建本地模型（无密钥）：存空串，列表 masked 为空。"""
    _save(api, api_key="")
    assert _stored_key(api) == ""
    assert api.get_llm_models()["models"][0]["api_key_masked"] == ""
