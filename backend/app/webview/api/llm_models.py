"""LLM 模型管理（CRUD/厂商模型发现）——从 bridge.py 拆出（步骤 3 mixin）。

Bridge 继承此 Mixin，方法名不变、前端 API 面与测试零破坏。
"""
from __future__ import annotations

import logging
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class LlmModelsApiMixin:
    """LLM 模型管理（CRUD/厂商模型发现）"""

    def get_llm_models(self) -> dict[str, Any]:
        """获取所有已配置的 LLM 模型列表"""
        try:
            from ...db.connection import get_db

            conn = get_db()

            # 确保表存在
            conn.execute('''
                CREATE TABLE IF NOT EXISTS llm_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    api_base_url TEXT NOT NULL,
                    api_key TEXT,
                    is_active INTEGER DEFAULT 0,
                    max_tokens INTEGER DEFAULT 512,
                    temperature REAL DEFAULT 0.7,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            ''')

            cursor = conn.execute(
                'SELECT id, name, provider, model_id, api_base_url, '
                'api_key, is_active, max_tokens, temperature, '
                'created_at, updated_at FROM llm_models ORDER BY is_active DESC, updated_at DESC'
            )

            models = []
            for row in cursor.fetchall():
                m = dict(row)
                # API Key 脱敏展示：只显示前4和后4个字符
                key = m.get('api_key') or ''
                if len(key) > 10:
                    m['api_key_masked'] = f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"
                elif key:
                    m['api_key_masked'] = '****'
                else:
                    m['api_key_masked'] = ''
                models.append(m)

            return {"ok": True, "models": models}
        except Exception as e:
            logger.error(f"[Bridge] 获取模型列表失败: {e}")
            return {"ok": False, "error": str(e), "models": []}

    def save_llm_model(self, model: dict[str, Any]) -> dict[str, Any]:
        """
        新增或更新 LLM 模型配置

        Args:
            model: {
                "id": int (可选，有则更新),
                "name": str,
                "provider": str,
                "model_id": str,
                "api_base_url": str,
                "api_key": str (可选),
                "is_active": bool,
                "max_tokens": int (legacy/internal, optional),
                "temperature": float
            }
        """
        try:
            import time as _time
            from ...db.connection import get_db

            conn = get_db()
            now = int(_time.time())

            model_id = model.get('id')
            legacy_max_tokens = model.get('max_tokens')
            if legacy_max_tokens is None and model_id is not None:
                existing = conn.execute(
                    'SELECT max_tokens FROM llm_models WHERE id = ?',
                    (model_id,),
                ).fetchone()
                legacy_max_tokens = existing['max_tokens'] if existing else 512
            if legacy_max_tokens is None:
                legacy_max_tokens = 512

            # 如果设为激活，先把其他所有模型设为非激活
            if model.get('is_active'):
                conn.execute('UPDATE llm_models SET is_active = 0')

            if model.get('id') is not None:
                # 只更新状态，其他字段保持不变
                if len(model) == 2 and 'is_active' in model:
                    conn.execute(
                        'UPDATE llm_models SET is_active = ?, updated_at = ? WHERE id = ?',
                        (1 if model['is_active'] else 0, _time.time(), model['id'])
                    )
                else:
                    conn.execute(
                        '''UPDATE llm_models SET name = ?, provider = ?, model_id = ?, 
                           api_base_url = ?, api_key = ?, is_active = ?, max_tokens = ?, 
                           temperature = ?, updated_at = ? WHERE id = ?''',
                        (model.get('name', ''), model.get('provider', ''), model.get('model_id', ''),
                         model.get('api_base_url', ''), model.get('api_key', ''), 1 if model.get('is_active') else 0,
                         legacy_max_tokens, model.get('temperature', 0.7), _time.time(), model['id'])
                    )
            else:
                conn.execute(
                    '''INSERT INTO llm_models (name, provider, model_id, api_base_url, 
                       api_key, is_active, max_tokens, temperature, created_at, updated_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (model.get('name', ''), model.get('provider', ''), model.get('model_id', ''),
                     model.get('api_base_url', ''), model.get('api_key', ''), 1 if model.get('is_active') else 0,
                     legacy_max_tokens, model.get('temperature', 0.7), _time.time(), _time.time())
                )

            conn.commit()

            # 如果激活了 LLM 模型，同步更新建议引擎类型
            if model.get('is_active'):
                try:
                    from ...services.realtime.monitor_service import RealtimeMonitorService
                    monitor = RealtimeMonitorService()
                    monitor.set_suggestion_config({'engine_type': 'llm'})
                except Exception:
                    pass

            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 保存模型配置失败: {e}")
            import traceback
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def delete_llm_model(self, model_id: int) -> dict[str, Any]:
        """删除 LLM 模型配置"""
        try:
            from ...db.connection import get_db

            conn = get_db()
            conn.execute('DELETE FROM llm_models WHERE id = ?', (model_id,))
            conn.commit()

            return {"ok": True}
        except Exception as e:
            logger.error(f"[Bridge] 删除模型失败: {e}")
            return {"ok": False, "error": str(e)}

    def fetch_provider_models(self, base_url: str, api_key: str = "") -> dict[str, Any]:
        """查询厂商 API 可用的模型列表（通过 GET /models 端点）
        
        Args:
            base_url: API 基址址 (e.g. https://api.deepseek.com/v1)
            api_key: API 密钥
            
        Returns:
            {"ok": True, "models": ["deepseek-chat", "deepseek-reasoner", ...]}
        """
        try:
            from ...services.realtime.llm_engine import LLMSuggestionEngine
            engine = LLMSuggestionEngine()
            model_ids = engine._fetch_available_models(base_url, api_key)
            if model_ids is not None:
                return {"ok": True, "models": model_ids}
            else:
                return {"ok": False, "error": "无法查询可用模型，请检查 API 地址和密钥", "models": []}
        except Exception as e:
            logger.error(f"[Bridge] 查询厂商模型失败: {e}")
            return {"ok": False, "error": str(e), "models": []}

