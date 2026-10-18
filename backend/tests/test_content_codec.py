"""消息内容解码的单元测试。

背景：V4 库 content 混有 zstd 压缩 BLOB，旧链路 str(bytes) 产出
b'(\\xb5...' 式 repr 乱码混入 RAG 分段与问答引用；本套件覆盖
content_codec 的各解码分支（入库归一由 ingest 链路在写入时完成）。
"""

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.wechat.content_codec import (
    ZSTD_MAGIC,
    decode_message_content,
    looks_binary_text,
)


ZSTD_BLOB = ZSTD_MAGIC + b"\x00\x01\x02junkpayload"


class TestDecodeMessageContent:
    def test_none_returns_empty(self):
        assert decode_message_content(None) == ""

    def test_zstd_blob_type1_gives_compressed_text_placeholder(self):
        assert decode_message_content(ZSTD_BLOB, 1) == "[压缩消息]"

    def test_zstd_blob_unmasked_type_masks_first(self):
        # local_type 高 32 位带 flag：6*2^32+49 掩码后应为 49（链接/小程序）
        assert decode_message_content(ZSTD_BLOB, 6 * 4294967296 + 49) == "[链接/小程序]"

    def test_zstd_blob_media_type_gives_typed_placeholder(self):
        assert decode_message_content(ZSTD_BLOB, 3) == "[图片]"
        assert decode_message_content(ZSTD_BLOB, 43) == "[视频]"
        assert decode_message_content(ZSTD_BLOB, 10002) == "[系统消息]"

    def test_zstd_blob_unknown_type_gives_default_placeholder(self):
        assert decode_message_content(ZSTD_BLOB, 88) == "[媒体消息]"

    def test_zstd_blob_without_type_treated_as_text(self):
        assert decode_message_content(ZSTD_BLOB) == "[压缩消息]"

    def test_plain_utf8_bytes_decoded_as_text(self):
        assert decode_message_content("今晚吃火锅吗".encode("utf-8"), 1) == "今晚吃火锅吗"

    def test_non_utf8_bytes_gives_placeholder(self):
        assert decode_message_content(b"\xff\xfe\xfa", 43) == "[视频]"

    def test_utf8_but_binary_looking_bytes_gives_placeholder(self):
        # 旧链路 errors='ignore' 风格的可解码乱码：控制字符占比超三成
        garbage = ("\x00" * 30 + "ab").encode("utf-8")
        assert decode_message_content(garbage, 1) == "[压缩消息]"

    def test_str_passthrough(self):
        assert decode_message_content("普通消息", 1) == "普通消息"

    def test_binary_looking_str_gives_placeholder(self):
        assert decode_message_content("\x00\x01\x02" * 10 + "tail", 1) == "[压缩消息]"

    def test_short_string_never_flagged(self):
        # 短内容（表情、单字）不做乱码判定，避免误伤
        assert looks_binary_text("\x01\x02") is False
        assert decode_message_content("好", 1) == "好"


