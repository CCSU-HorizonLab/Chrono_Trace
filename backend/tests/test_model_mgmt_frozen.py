"""打包版模型缺失的行为测试：frozen 态不提供无效下载与误导文案。

背景：推理是 ONNX 单后端（只认 onnx/ 产物），应用内下载拉的是 ModelScope
源模型权重——打包版内置模型缺失时下载是假修复，且「运行 python 脚本」
文案对打包用户无意义。
"""

import sys
import threading
from pathlib import Path

import pytest


backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))


from app.webview.api.model_mgmt import ModelMgmtApiMixin


class _FakeManager:
    def __init__(self, issue):
        self._issue = issue

    def diagnose_model_status(self):
        return {"repo_id": "fake/repo", "issue": self._issue}


class _FakeBridge(ModelMgmtApiMixin):
    def __init__(self):
        self.settings = {}
        self._settings_lock = threading.Lock()

    def _save_settings(self):
        pass

    def _get_sentiment_model_manager(self):
        return _FakeManager("模型目录不存在: /fake/sentiment_3class")

    def _diagnose_embedding_model_status(self):
        return {"repo_id": "fake/emb", "issue": "模型目录不存在: /fake/bge", "can_recover": True}


@pytest.fixture
def no_onnx(monkeypatch):
    """强制走 ModelManager 诊断分支（跳过本机 onnx 产物探测）。"""
    monkeypatch.setattr(
        "app.services.analysis.onnx_inference.has_onnx_models", lambda: False
    )


def _make_bridge(monkeypatch, frozen: bool) -> _FakeBridge:
    monkeypatch.setattr("app.config.IS_FROZEN", frozen)
    return _FakeBridge()


class TestMissingModelMessaging:
    def test_dev_issue_mentions_export_script(self, no_onnx, monkeypatch):
        result = _make_bridge(monkeypatch, frozen=False).check_analysis_model_status()
        assert result["ok"] is True
        assert result["missing_models"] == ["sentiment", "embedding"]
        for item in result["missing_details"]:
            assert "ensure_models_for_export.py" in item["issue"]

    def test_frozen_issue_redirects_to_reinstall(self, no_onnx, monkeypatch):
        result = _make_bridge(monkeypatch, frozen=True).check_analysis_model_status()
        assert result["missing_models"] == ["sentiment", "embedding"]
        for item in result["missing_details"]:
            assert item["issue"] == "安装包内置模型缺失：请重新下载完整安装包并覆盖安装"
            assert item["can_auto_download"] is False
            assert "python" not in item["issue"]


class TestDownloadRejection:
    def test_frozen_download_rejected(self, no_onnx, monkeypatch):
        bridge = _make_bridge(monkeypatch, frozen=True)
        result = bridge.download_analysis_models()
        assert result["ok"] is False
        assert result["error_code"] == "BUNDLED_MODEL_MISSING"
        assert "重新下载完整安装包" in result["error"]
        # 不得启动下载任务
        assert "task_id" not in result
