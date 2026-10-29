"""嵌入变体迁移启动路径（W14）。

此前 rag/config 模块未定义 logger，迁移命中分支的 logger.info 触发
NameError、except 分支的 logger.warning 再次 NameError 一路抛到 Bridge
的 _load_settings 被吞成 debug 级「迁移跳过」——落盘与否无人知晓，
失败也静默。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.realtime.rag.config import persist_rag_variant_migration_if_needed


def test_variant_migration_hit_branch_returns_cleanly(monkeypatch):
    """命中迁移分支：正常落盘返回 True，不再因缺 logger 抛 NameError。"""
    saved = {}
    monkeypatch.setattr(
        "app.services.wechat.account_settings.load_settings_from_file",
        lambda: {"rag_embedding_model": "text2vec", "rag_embedding_dim": 768},
    )
    monkeypatch.setattr(
        "app.services.wechat.account_settings.save_settings_to_file",
        lambda payload: saved.update(payload),
    )
    monkeypatch.setattr(
        "app.services.realtime.rag.config.apply_rag_defaults",
        lambda raw: {"rag_embedding_model": "bge-small", "rag_embedding_dim": 512},
    )

    assert persist_rag_variant_migration_if_needed() is True
    assert saved["rag_embedding_model"] == "bge-small"
    assert saved["rag_embedding_dim"] == 512


def test_variant_migration_noop_when_model_matches(monkeypatch):
    """未命中（旧值与目标一致/缺旧值）：安静返回 False 不落盘。"""
    saved = {}
    monkeypatch.setattr(
        "app.services.wechat.account_settings.load_settings_from_file",
        lambda: {"rag_embedding_model": "bge-small", "rag_embedding_dim": 512},
    )
    monkeypatch.setattr(
        "app.services.wechat.account_settings.save_settings_to_file",
        lambda payload: saved.update(payload),
    )
    monkeypatch.setattr(
        "app.services.realtime.rag.config.apply_rag_defaults",
        lambda raw: {"rag_embedding_model": "bge-small", "rag_embedding_dim": 512},
    )

    assert persist_rag_variant_migration_if_needed() is False
    assert saved == {}
