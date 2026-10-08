"""编码安全的强制刷新打印（stdout 版 ``_print`` 的唯一实现）。

为什么存在：Windows 打包/重定向场景下 stdout 可能是 cp936/GBK，
消息里的 emoji（⚠️📥 等）触发 UnicodeEncodeError 直接炸掉调用链
（c48b96e 修的实锤案例：backfill 落库路径因此崩溃过）。本函数在
编码失败时用 errors=replace 兜底重写，保证"打印永不炸调用方"。

使用：``from .safe_print import safe_print as _print``
各模块保留自己的模块级 ``_print`` 绑定，测试 monkeypatch 不受影响。
logger.debug 语义的 ``_print`` 不要用本模块——集中定义会丢失日志
归属（记录的 logger 名会变成 safe_print 而非调用方模块）。
"""
from __future__ import annotations

import sys


def safe_print(*args, **kwargs) -> None:
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        text = sep.join(str(arg) for arg in args) + end
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        sys.stdout.write(safe_text)
        if kwargs.get("flush", False):
            sys.stdout.flush()
