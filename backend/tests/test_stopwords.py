"""停用词单一来源不变量测试（词云与群统计共用 CHAT_STOP_WORDS）。"""

import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.analysis import stopwords as stopwords_mod
from app.services.analysis.group_summary_service import STOP_WORDS
from app.services.analysis.stopwords import CHAT_STOP_WORDS


def test_both_consumers_share_single_source():
    """群统计与词云必须引用同一张表，防两套口径再次漂移"""
    assert STOP_WORDS is CHAT_STOP_WORDS
    from app.services.analysis.wordcloud_generator import WordCloudGenerator

    assert WordCloudGenerator().stopwords == CHAT_STOP_WORDS


def test_curated_boundaries():
    """虚词全收；情感实词刻意不收（词云里是信号不是噪声）"""
    for word in ("的", "然后", "这样", "回复", "消息", "哈哈"):
        assert word in CHAT_STOP_WORDS, word
    for word in ("好", "行", "喜欢", "爱", "开心"):
        assert word not in CHAT_STOP_WORDS, word


def test_words_are_short_tokens_only():
    """聊天停用词都是短 token（中文 ≤4 字，ASCII 占位 ≤5），长词混入多半是误收"""
    for word in CHAT_STOP_WORDS:
        cap = 5 if word.isascii() else 4
        assert len(word) <= cap, word


def test_module_docstring_records_purpose():
    assert "单一来源" in stopwords_mod.__doc__
