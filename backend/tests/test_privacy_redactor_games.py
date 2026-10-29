"""G4 脱敏证据可用性测试:游戏名正反例、核心对象完整性、fail-closed 回归。"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.realtime.privacy_redactor import (
    PrivacyRedactor,
    evidence_core_intact,
)


def _redact(text: str) -> str:
    return PrivacyRedactor().redact(
        text, account_wxid="wxid_a", conversation_id=1, source_table="test"
    ).redacted_text


def test_game_titles_with_road_chars_are_preserved():
    """地址规则不得误伤"某游戏名"等含路/街字符的游戏译名。"""
    assert _redact("我们玩某游戏名吧") == "我们玩某游戏名吧"
    assert _redact("塞尔达传说王国之泪要出了") == "塞尔达传说王国之泪要出了"
    assert _redact("马里奥赛车开一把?") == "马里奥赛车开一把?"


def test_game_position_names_not_flagged():
    assert _redact("现在中路推塔别浪") == "现在中路推塔别浪"
    assert _redact("走上路还是下路") == "走上路还是下路"


def test_real_addresses_still_redacted():
    """修复误伤不得放松真实地址的脱敏。"""
    assert "[ADDRESS_" in _redact("她家在上海市浦东新区张江路")
    assert "[ADDRESS_" in _redact("约在人民路123号")
    assert "[ADDRESS_" in _redact("他住在中山路88号3单元502室")
    assert "[ADDRESS_" in _redact("她住在武昌路附近")


def test_phone_still_redacted():
    assert _redact("电话13812345678") == "电话[PHONE_" + _redact("电话13812345678")[len("电话[PHONE_"):]


def test_mixed_sentence_only_redacts_address_part():
    text = "明天到人民路123号找我,记得带上某游戏名的卡带"
    redacted = _redact(text)
    assert "[ADDRESS_" in redacted
    assert "某游戏名" in redacted


def test_evidence_core_intact_short_fact():
    """短事实出现占位符即核心对象丢失。"""
    assert evidence_core_intact("我们玩某游戏名吧", "我们玩某游戏名吧") is True
    assert evidence_core_intact("我们玩某游戏名吧", "[ADDRESS_AB12CD]") is False
    assert evidence_core_intact("她喜欢玩游戏", "她喜欢玩[ADDRESS_AB12CD]") is False


def test_evidence_core_intact_long_fact_bigram_ratio():
    original = "对方喜欢在周末的时候玩主机游戏,尤其是合作类闯关,一起玩会很开心"
    partial = "对方喜欢在周末的时候玩主机游戏,尤其是[ADDRESS_AB12CD]闯关,一起玩会很开心"
    assert evidence_core_intact(original, original) is True
    # 少量实体被替换,主体事实保留 → 可用
    assert evidence_core_intact(original, partial) is True
    # 核心对象被整体吃掉 → 不可用
    assert evidence_core_intact(original, "对方喜欢在[ADDRESS_AB12CD]") is False


def test_evidence_core_intact_non_chinese_passthrough():
    assert evidence_core_intact("ID: 12345", "ID: [PHONE_AB12CD]") is True


def test_strong_mask_still_masks_everything():
    masked = PrivacyRedactor().strong_mask("她家在上海市浦东新区张江路,电话13812345678")
    assert "上海" not in masked
    assert "13812345678" not in masked


def test_strong_mask_same_guardrails_as_redact():
    """W13：兜底路径与 redact 同口径——译名哨兵 + 裸路名误报过滤。

    此前 strong_mask 裸套 PATTERNS：星穹铁道被地址模式吃成 [ADDRESS]、
    「中路推塔」整句消失，保护只存在于主路径。
    """
    # 译名不被地址模式吃掉
    masked = PrivacyRedactor().strong_mask("我们打星穹铁道模拟宇宙")
    assert "星穹铁道" in masked
    assert "[ADDRESS]" not in masked
    # 裸路名（无居住语境）不判地址
    assert PrivacyRedactor().strong_mask("现在中路推塔别浪") == "现在中路推塔别浪"
    # 真实地址仍被打码（守卫不得放松兜底）
    assert "张江路" not in PrivacyRedactor().strong_mask("她家在上海市浦东新区张江路")
