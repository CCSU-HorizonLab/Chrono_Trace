"""消息内容解码与占位符统一口径。

微信 V4 解密库的 message_content / compress_content 混有 zstd 压缩
BLOB（转发/小程序/图片/表情等），且 local_type 高 32 位带 flag。导入、
启动迁移、RAG/问答读侧三端共用一套解码：

- bytes：zstd magic 或 UTF-8 不可解码/不可打印 → 按掩码类型给占位符
- str：前 64 字符非打印占比超三成，或含 >=2 个 U+FFFD 换坏字符
  （历史 ingest errors='replace' 产物的特征）→ 占位符

占位符词表按「类型名」导出单一来源（TYPE_NAME_PLACEHOLDER），实时
监听 db_watch 的 NON_TEXT_PLACEHOLDER 从这里导入，两侧不再手工同步
（此前已漂移：db_watch 有 file→[文件]、默认 [消息]，本表缺失）。

无 zstd 解压依赖（包体积考虑），压缩内容不做真解压——type=1 的压缩
文本消息给「[压缩消息]」占位，后续需要可引入 zstandard 补真解压。
"""

from __future__ import annotations

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# 类型名 → 占位符（db_watch.NON_TEXT_PLACEHOLDER 的单一来源；
# local_type 整数键控见 LOCAL_TYPE_PLACEHOLDER）
TYPE_NAME_PLACEHOLDER = {
    "image": "[图片]",
    "voice": "[语音]",
    "video": "[视频]",
    "emoji": "[表情]",
    "location": "[位置]",
    "appmsg": "[链接/小程序]",
    "voip": "[通话]",
    "card": "[名片]",
    "video_channel": "[视频号]",
    "file": "[文件]",
    "system": "[系统消息]",
}

# local_type（已掩码）→ 非文本占位符
LOCAL_TYPE_PLACEHOLDER = {
    3: "[图片]",
    34: "[语音]",
    42: "[名片]",
    43: "[视频]",
    47: "[表情]",
    48: "[位置]",
    49: "[链接/小程序]",
    50: "[通话]",
    62: "[视频号]",
    10000: "[系统消息]",
    10002: "[系统消息]",
}
# type=1 的压缩 BLOB：真实文本但当前无解压通道，用独立措辞避免误标媒体
COMPRESSED_TEXT_PLACEHOLDER = "[压缩消息]"
DEFAULT_PLACEHOLDER = "[媒体消息]"
# U+FFFD 换坏字符密度阈值（样本内出现次数）：errors='replace' 解码 zstd
# 二进制的产物动辄十几个；正常文本至多零星一个
_FFFD_THRESHOLD = 2


def looks_binary_text(text: str) -> bool:
    """文本疑似二进制/乱码：非打印占比超三成，或 U+FFFD 换坏字符密集。

    私有区（U+E000..U+F8FF，旧版内联表情/图标）按可打印处理，避免
    表情密集的正常消息被误判成乱码。
    """
    if len(text) <= 8:
        return False
    sample = text[:64]
    if sample.count("\ufffd") >= _FFFD_THRESHOLD:
        return True
    non_printable = sum(
        1
        for ch in sample
        if not (
            ch.isprintable()
            or ch in "\n\r\t"
            or "" <= ch <= ""
        )
    )
    return non_printable / len(sample) > 0.3


def _placeholder(message_type: int | None) -> str:
    masked = int(message_type or 1) & 0xFFFFFFFF
    if masked == 1:
        return COMPRESSED_TEXT_PLACEHOLDER
    return LOCAL_TYPE_PLACEHOLDER.get(masked, DEFAULT_PLACEHOLDER)


def decode_message_content(content, message_type: int | None = None) -> str:
    """把库中任意形态的消息内容归一为可读文本（压缩二进制给占位符）。

    对已是 str 的正常文本幂等（原样返回），可作为「是否需要归一」的
    判定器使用：返回值与输入不同即为脏文本。
    """
    if content is None:
        return ""
    if isinstance(content, (bytes, bytearray)):
        raw = bytes(content)
        if raw[:4] == ZSTD_MAGIC:
            return _placeholder(message_type)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _placeholder(message_type)
        if looks_binary_text(text):
            return _placeholder(message_type)
        return text
    text = str(content)
    if looks_binary_text(text):
        return _placeholder(message_type)
    return text
