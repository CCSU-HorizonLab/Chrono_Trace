"""情感分类上文窗口——v2 学生（ctx 口径）的唯一拼接口径。

与训练/打标同源（backend/scripts/distill_sentiment_v2.py 的 build_samples）：
上文 = 同会话前至多 CTX_N 条文本消息（任意发送者），单条换行压空格、
截 CTX_CHARS 字，" / " 连接；模型输入 = "上文 [SEP] 目标消息"，
无上文时退回纯消息。三口径（打标 prompt / 学生训练 / 生产推理）必须
同形——改这里要同步改训练脚本并重训。
"""

CTX_N = 3        # 上文条数
CTX_CHARS = 60   # 单条上文截断字数


def context_string(prev_texts: list) -> str:
    """有序上文文本列表 → 拼接串（取末尾 CTX_N 条，空列表得空串）。"""
    parts = [str(t).replace("\n", " ")[:CTX_CHARS] for t in prev_texts[-CTX_N:]]
    return " / ".join(parts)


def build_contexts(texts: list) -> list:
    """有序文本列表 → 每条各自的上文串（第 i 条的上文 = 前 i 条）。"""
    return [context_string(texts[:i]) for i in range(len(texts))]


def compose_input(context: str, text: str) -> str:
    """模型输入形态：ctx [SEP] msg；空上文退回纯消息（学生训练同款）。"""
    return f"{context} [SEP] {text}" if context else text
