"""敷衍判定与情感词典不变量测试。

is_perfunctory 的长度兜底曾把「哈哈/谢谢/爱你」一并误伤（抬高情感
共鸣维的敷衍回复率与单向投入风险），此处锁定白名单与显式词表的行为。
"""

import sys
from pathlib import Path

backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))

from app.services.realtime.sentiment_rules import (
    EMOJI_SENTIMENT,
    ENGAGED_SHORT_REPLIES,
    INTERNET_SLANG,
    PERFUNCTORY_WORDS,
    get_emoji_sentiment,
    get_slang_info,
    is_perfunctory,
)


class TestIsPerfunctory:
    def test_engaged_short_replies_not_perfunctory(self):
        """笑声/感谢/情感表达/状态告知等高投入短回复不算敷衍"""
        for text in ("哈哈", "嘿嘿", "谢谢", "爱你", "抱抱", "来了", "在呢",
                     "好嘞", "666", "牛", "棒"):
            assert not is_perfunctory(text), text

    def test_dismissive_replies_are_perfunctory(self):
        """嗯/哦/好吧类冷应答与放任句式仍判敷衍"""
        for text in ("嗯", "哦", "好吧", "随便", "嗯嗯", "行行"):
            assert is_perfunctory(text), text

    def test_three_char_reduplication_now_caught(self):
        """3 字叠字应付躲过旧长度兜底，须靠显式词表命中"""
        for text in ("嗯嗯嗯", "哦哦哦", "好好好", "行行行", "无所谓", "不知道"):
            assert is_perfunctory(text), text

    def test_empty_text_not_perfunctory(self):
        """空串/纯空白不是回复，不计入敷衍分母"""
        assert not is_perfunctory("")
        assert not is_perfunctory("   ")

    def test_whitelist_takes_priority_over_word_list(self):
        """白名单优先于显式词表（同一词不会同时出现在两表）"""
        assert not (ENGAGED_SHORT_REPLIES & set(PERFUNCTORY_WORDS))

    def test_longer_substantive_reply_not_perfunctory(self):
        assert not is_perfunctory("我明天下午三点到，你直接来地铁站找我")


class TestEmojiLexicon:
    def test_coverage_expanded(self):
        """常用中文聊天表情需覆盖到百级（曾只有 45 个）"""
        assert len(EMOJI_SENTIMENT) >= 110

    def test_intensity_sign_matches_sentiment(self):
        """极性与强度符号必须自洽：负面强度为负、正面为正"""
        for info in EMOJI_SENTIMENT.values():
            if info["sentiment"] == "positive":
                assert info["intensity"] > 0
            elif info["sentiment"] == "negative":
                assert info["intensity"] < 0
            else:
                assert -0.3 <= info["intensity"] <= 0.0

    def test_new_entries_lookup(self):
        assert get_emoji_sentiment("🫶")["sentiment"] == "positive"
        assert get_emoji_sentiment("🤡")["sentiment"] == "negative"
        # 歧义大表（笑死/绝望并存）挂中性，不赌方向
        assert get_emoji_sentiment("💀")["sentiment"] == "neutral"


class TestSlangLexicon:
    def test_relationship_domain_words_present(self):
        """关系语域词直接服务本应用的分析目标"""
        assert get_slang_info("双向奔赴")["sentiment"] == "positive"
        assert get_slang_info("下头")["sentiment"] == "negative"

    def test_lookup_is_case_insensitive(self):
        assert get_slang_info("PUA")["sentiment"] == "negative"

    def test_stale_words_removed(self):
        """过气词不再入表（曾混入「奥利给」）"""
        assert get_slang_info("奥利给") is None

    def test_intensity_sign_matches_sentiment(self):
        for info in INTERNET_SLANG.values():
            if info["sentiment"] == "positive":
                assert info["intensity"] > 0
            elif info["sentiment"] == "negative":
                assert info["intensity"] < 0
