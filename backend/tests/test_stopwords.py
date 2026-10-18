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


def test_generic_filler_nouns_in_daily_topics_out():
    """泛聊天高频实词（语义空转）收；日程话题词是生活方式信号不收"""
    for word in ("东西", "时候", "出来", "真的", "问题", "不能", "处理"):
        assert word in CHAT_STOP_WORDS, word
    for word in ("吃饭", "上班", "睡觉"):
        assert word not in CHAT_STOP_WORDS, word


def test_content_pos_tags_boundaries():
    """词性白名单只含实词词性：代词/时间词/副词/数量/虚词整类出局"""
    from app.services.analysis.stopwords import CONTENT_POS_TAGS

    for tag in ("n", "nr", "ns", "vn", "v", "a", "eng"):
        assert tag in CONTENT_POS_TAGS, tag
    for tag in ("r", "t", "d", "m", "q", "c", "p", "u", "x"):
        assert tag not in CONTENT_POS_TAGS, tag


def test_pos_whitelist_kills_deixis_in_pipeline():
    """端到端：代词/时间指示/副词经词性白名单出局，泛用动词经停用词出局，
    内容词（火锅/电影/游戏）保留——挡的是整类噪声不是实词"""
    from app.services.analysis.wordcloud_generator import WordCloudGenerator

    texts = [
        "我们上午去吃了火锅，下午看了电影",
        "他们这儿不能处理事情，那儿也一样",
        "周末一起去游戏厅玩游戏",
    ]
    words = {item["word"] for item in WordCloudGenerator().generate(texts, top_n=30)}
    for noise in ("我们", "他们", "这儿", "那儿", "上午", "下午", "周末", "不能", "处理", "事情", "真的"):
        assert noise not in words, noise
    assert words & {"火锅", "电影", "游戏"}, words


def test_words_are_short_tokens_only():
    """聊天停用词都是短 token（中文 ≤4 字，ASCII 占位 ≤5），长词混入多半是误收"""
    for word in CHAT_STOP_WORDS:
        cap = 5 if word.isascii() else 4
        assert len(word) <= cap, word


def test_module_docstring_records_purpose():
    assert "单一来源" in stopwords_mod.__doc__
