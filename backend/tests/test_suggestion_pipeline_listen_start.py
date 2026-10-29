"""开场建议抑制时间戳的置位时机（第四轮抽查 W11）。

`_listen_start_suggestion_at` 此前在 engine.generate() 返回并落库之后
才设置——推理模型 20-40s 延迟窗口内 60s 抑制不生效，轮询的 silence
冷场提醒恰在此窗口触发，开场建议与体面降温两张重复卡片同时生成。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.realtime.suggestion_pipeline import SuggestionPipelineMixin


class _Host(SuggestionPipelineMixin):
    """最小宿主：只供 _generate_listen_start_suggestion 依赖的钩子。"""

    def __init__(self):
        self._monitor_session_token = 1
        self._suggestion_config = {
            "trigger_mode": "semi_auto",
            "intent": "maintain",
            "engine_type": "llm",
        }
        self._listen_start_suggestion_at = 0

    def _build_session_state(self, token):
        return {"token": token, "batch_id": "b1"}

    def _session_is_current(self, session_state):
        return True

    def _build_llm_suggestion_context(self, session_state, mode, recent_limit, trigger_context):
        return {
            "recent_messages": [{"content": f"消息{i}"} for i in range(recent_limit)],
            "trigger_context": trigger_context,
        }

    def _save_suggestion_to_db(self, trigger, result, session_state=None):
        return None


def test_suppression_timestamp_set_before_llm_call(monkeypatch):
    """进入 engine.generate 时抑制时间戳必须已置位（覆盖 LLM 延迟窗口）。"""
    host = _Host()
    observed = {}

    class _Engine:
        def generate(self, trigger_type, intent, ctx):
            observed["ts_at_generate_entry"] = host._listen_start_suggestion_at
            return {"reply": "好的"}

    class _Factory:
        @staticmethod
        def create(engine_type):
            return _Engine()

    monkeypatch.setattr(
        "app.services.realtime.suggestion_engine.SuggestionEngineFactory", _Factory
    )

    host._generate_listen_start_suggestion()

    assert observed["ts_at_generate_entry"] > 0, (
        "抑制时间戳必须在 LLM 调用前置位——否则延迟窗口内 silence 照发"
    )
    assert time.time() - host._listen_start_suggestion_at < 60
