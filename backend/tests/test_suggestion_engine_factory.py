"""Tests for current LLM-only suggestion engine factory behavior."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.llm_engine import LLMSuggestionEngine
from app.services.realtime.suggestion_engine import SuggestionEngineFactory


def test_factory_rejects_removed_template_engine():
    SuggestionEngineFactory._engine_cache.clear()

    with pytest.raises(ValueError, match="未知引擎类型"):
        SuggestionEngineFactory.create("template")


def test_factory_local_llm_returns_llm_engine():
    SuggestionEngineFactory._engine_cache.clear()

    engine = SuggestionEngineFactory.create("local_llm")

    assert isinstance(engine, LLMSuggestionEngine)
