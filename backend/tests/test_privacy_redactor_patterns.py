"""脱敏器 PII 模式覆盖测试（邮箱/URL/座机三类后补模式 + 原有类别不回归）。

背景：PATTERNS 原先只有 api_key/身份证/银行卡/手机号/地址五类，邮箱、
分享链接、企业座机原样放行直发远程 LLM——补齐后此处锁行为。
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.realtime.privacy_redactor import PrivacyRedactor  # noqa: E402


def _redact(text: str) -> str:
    return PrivacyRedactor().redact(text).redacted_text


class TestEmailUrlLandlinePatterns:
    """新增三类 PII 模式"""

    def test_email_redacted(self):
        out = _redact("文件发我邮箱 zhang.san1990@qq.com 谢谢")
        assert "zhang.san1990" not in out
        assert "qq.com" not in out
        assert "[EMAIL_" in out

    def test_share_link_redacted_without_swallowing_punctuation(self):
        # 网盘链接带提取码整体吃掉，后面的中文逗号与正文不得被吞
        out = _redact("看这个 https://pan.baidu.com/s/1abcDEF123?pwd=x9y8，你觉得呢")
        assert "pan.baidu.com" not in out
        assert "pwd=x9y8" not in out
        assert out.endswith("，你觉得呢")

    def test_www_url_redacted(self):
        out = _redact("官网 www.example.com 也有")
        assert "example.com" not in out
        assert "[URL_" in out

    def test_landline_with_area_code_redacted(self):
        out = _redact("座机 010-62781234 打这个")
        assert "62781234" not in out
        assert "[LANDLINE_" in out

    def test_hotline_400_redacted(self):
        out = _redact("客服 400-618-1234 转人工")
        assert "618-1234" not in out
        assert "[LANDLINE_" in out

    def test_plain_chinese_sentence_untouched(self):
        assert _redact("正常一句话没有敏感内容") == "正常一句话没有敏感内容"

    def test_version_like_string_not_treated_as_email(self):
        # "pkg@1.0" 类版本号末段非字母 TLD，不按邮箱误伤
        assert _redact("升级到 node@20.10.0 版本") == "升级到 node@20.10.0 版本"

    def test_plain_domain_without_scheme_not_touched(self):
        # 裸域名（无协议头/www 前缀）不按 URL 误伤——聊天里说域名多指代非链接
        out = _redact("去 baidu.com 搜一下")
        assert out == "去 baidu.com 搜一下"

    def test_strong_mask_covers_new_patterns(self):
        masked = PrivacyRedactor().strong_mask("邮箱 a.b@qq.com 链接 https://x.com/y 座机 010-62781234")
        assert "a.b@qq.com" not in masked
        assert "x.com" not in masked
        assert "62781234" not in masked

    def test_existing_phone_pattern_still_works(self):
        out = _redact("手机 13800138000 别打")
        assert "13800138000" not in out
        assert "[PHONE_" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestChineseAdjacentBoundaries:
    """PII 紧贴中文（中文聊天最常见形态）：\\b 对中文失效的回归锁。

    re 的 \\w 含中文，「我身份证110…你记一下」中证|1 之间无词边界，
    \\b 锚定的 id_card/bank_card/email/url/api_key 整体放行——改用
    显式字符类环视（只排字母数字）后中文前后均允许命中。
    """

    def test_id_card_adjacent_chinese_redacted(self):
        out = _redact("我身份证11010119900307425X你记一下")
        assert "11010119900307425X" not in out
        assert "[ID_CARD_" in out

    def test_bank_card_adjacent_chinese_redacted(self):
        out = _redact("卡号6222020200112233445转给你")
        assert "6222020200112233445" not in out
        assert "[BANK_CARD_" in out

    def test_email_adjacent_chinese_redacted(self):
        out = _redact("我邮箱zhangsan1990@163.com发我")
        assert "zhangsan1990" not in out
        assert "[EMAIL_" in out

    def test_url_adjacent_chinese_redacted(self):
        out = _redact("链接https://pan.baidu.com/s/abc你觉得呢")
        assert "pan.baidu.com" not in out
        assert "[URL_" in out

    def test_api_key_adjacent_chinese_redacted(self):
        out = _redact("密钥sk-abcdefgh12345678给我")
        assert "sk-abcdefgh12345678" not in out
        assert "[API_KEY_" in out

    def test_strong_mask_covers_chinese_adjacent_forms(self):
        masked = PrivacyRedactor().strong_mask("身份证11010119900307425X邮箱a@b.com")
        assert "11010119900307425X" not in masked
        assert "a@b.com" not in masked

    def test_long_digit_order_number_not_id_card(self):
        # 12 位流水号：不足身份证/银行卡长度，不误伤（19 位数字串按
        # bank_card 存量语义仍脱敏——宁可多脱，此处只锁短号不误伤）
        out = _redact("流水号123456789012请查收")
        assert "123456789012" in out

    def test_order_number_suffix_not_address(self):
        # 「流水号/订单号」的「号」不是门牌号——此前 address 后缀「号楼?」
        # 的可选「号」分支把「流水号123…」整句当地址吞掉
        out = _redact("流水号1234567890123456789请查收")
        assert "流水号" in out and "请查收" in out
