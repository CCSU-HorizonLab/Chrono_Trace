import json
import socket
import ssl
import threading
import time
import random
import urllib.error
import urllib.request
from typing import Any, Callable, Optional


DEFAULT_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_RETRY_DELAY = 1.5


class LLMRequestAborted(RuntimeError):
    """调用方请求中止（外部取消信号，不视为网络失败）。"""


# ---------------------------------------------------------------------------
# 交互式 LLM 调用取消注册表：bridge 层置位（scope, key），HTTP 跑守护工作
# 线程，主线程轮询命中即抛 LLMRequestAborted 立即返回——在途 socket 无法
# 强断，由 should_abort 在尝试边界退出（history_qa / group_summary 共用）。
# ---------------------------------------------------------------------------
_CANCEL_LOCK = threading.Lock()
_CANCELLED: set = set()


def request_llm_cancel(scope: str, key: int) -> None:
    """标记取消某个进行中的交互式调用（下一次轮询点生效）。"""
    with _CANCEL_LOCK:
        _CANCELLED.add((str(scope), int(key)))


def take_llm_cancel(scope: str, key: int) -> bool:
    """消费取消标记（存在即清除并返回 True）。"""
    with _CANCEL_LOCK:
        token = (str(scope), int(key))
        if token in _CANCELLED:
            _CANCELLED.discard(token)
            return True
        return False


def run_cancelable(
    fn: Callable[[], Any],
    *,
    cancelled: Callable[[], bool],
    on_cancel: Optional[Callable[[], None]] = None,
    poll_interval: float = 0.2,
    cancel_message: str = "本次请求已取消",
) -> Any:
    """fn 跑守护工作线程（阻塞 HTTP），主线程轮询 cancelled()，命中即
    on_cancel() 后抛 LLMRequestAborted；fn 的异常原样重抛。"""
    holder: dict[str, Any] = {}

    def _worker() -> None:
        try:
            holder["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 —— 结果经 holder 传递
            holder["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    while worker.is_alive():
        if cancelled():
            if on_cancel:
                on_cancel()
            raise LLMRequestAborted(cancel_message)
        worker.join(timeout=poll_interval)
    if "error" in holder:
        raise holder["error"]
    return holder.get("value")


def _iter_exception_chain(err: BaseException):
    seen: set[int] = set()
    current: BaseException | None = err

    while current is not None and id(current) not in seen:
        yield current
        seen.add(id(current))

        next_err: BaseException | None = None
        if isinstance(current, urllib.error.URLError):
            reason = getattr(current, "reason", None)
            if isinstance(reason, BaseException):
                next_err = reason

        if next_err is None:
            cause = getattr(current, "__cause__", None)
            context = getattr(current, "__context__", None)
            if isinstance(cause, BaseException):
                next_err = cause
            elif isinstance(context, BaseException):
                next_err = context

        current = next_err


def is_timeout_error(err: Exception) -> bool:
    if isinstance(err, (TimeoutError, socket.timeout)):
        return True
    if isinstance(err, urllib.error.URLError):
        reason = getattr(err, "reason", None)
        return isinstance(reason, (TimeoutError, socket.timeout))
    return False


def _has_non_retryable_ssl_failure(err: Exception) -> bool:
    for item in _iter_exception_chain(err):
        if isinstance(item, ssl.SSLCertVerificationError):
            return True
        if isinstance(item, ssl.CertificateError):
            return True

        text = str(item).lower()
        if "certificate verify failed" in text:
            return True

    return False


def describe_network_error(err: Exception) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    for item in _iter_exception_chain(err):
        text = str(item).strip() or item.__class__.__name__
        if text not in seen:
            parts.append(text)
            seen.add(text)

    if not parts:
        return err.__class__.__name__

    return " | ".join(parts)


def is_retryable_network_error(err: Exception) -> bool:
    if is_timeout_error(err):
        return True

    if _has_non_retryable_ssl_failure(err):
        return False

    retryable_types = (
        ConnectionResetError,
        ConnectionAbortedError,
        ConnectionRefusedError,
        BrokenPipeError,
        EOFError,
        ssl.SSLError,
    )

    for item in _iter_exception_chain(err):
        if isinstance(item, retryable_types):
            return True

    text = describe_network_error(err).lower()
    markers = (
        "unexpected eof while reading",
        "eof occurred in violation of protocol",
        "remote end closed connection",
        "connection reset",
        "connection aborted",
        "timed out",
        "temporarily unavailable",
    )
    return any(marker in text for marker in markers)


def compute_retry_delay(
    attempt: int,
    retry_after: Optional[str] = None,
    *,
    base_retry_delay: float = DEFAULT_BASE_RETRY_DELAY,
) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return base_retry_delay * (2 ** attempt) + random.uniform(0.0, 0.5)


def build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    tls12 = getattr(getattr(ssl, "TLSVersion", None), "TLSv1_2", None)
    if tls12 is not None:
        context.minimum_version = tls12
    return context


def _read_http_error_body(err: urllib.error.HTTPError) -> str:
    try:
        raw = err.read()
    except Exception:
        return ""

    if not raw:
        return ""

    try:
        text = raw.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""

    return text[:500]


def post_json_with_retries(
    *,
    url: str,
    payload: dict[str, Any],
    timeout: int,
    log: Callable[[str], None],
    log_prefix: str,
    headers: Optional[dict[str, str]] = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retryable_http_status: Optional[set[int]] = None,
    base_retry_delay: float = DEFAULT_BASE_RETRY_DELAY,
    should_abort: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """POST JSON，可重试网络/限流错误。

    should_abort 在每次尝试前与重试等待前轮询，返回 True 即抛
    LLMRequestAborted（交互式调用方用于外部取消）。
    """
    def _aborted() -> bool:
        return should_abort is not None and should_abort()

    merged_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Connection": "close",
        "User-Agent": "ChronoTrace/1.0",
    }
    if headers:
        merged_headers.update(headers)

    retryable_http_status = retryable_http_status or set(DEFAULT_RETRYABLE_HTTP_STATUS)
    ssl_context = build_ssl_context()

    log(f"{log_prefix} POST {url}")

    for attempt in range(max_retries + 1):
        if _aborted():
            raise LLMRequestAborted(f"{log_prefix} 请求已被调用方取消")
        started_at = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=merged_headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                status = resp.status
            elapsed = time.time() - started_at
            log(f"{log_prefix} HTTP {status} ({elapsed:.2f}s)")
            return body
        except urllib.error.HTTPError as err:
            status = getattr(err, "code", None)
            if status in retryable_http_status and attempt < max_retries:
                if _aborted():
                    raise LLMRequestAborted(f"{log_prefix} 请求已被调用方取消") from err
                delay = compute_retry_delay(
                    attempt,
                    err.headers.get("Retry-After"),
                    base_retry_delay=base_retry_delay,
                )
                log(f"{log_prefix} Retry on HTTP {status} after {delay:.1f}s (attempt {attempt + 1})")
                time.sleep(delay)
                continue

            detail = _read_http_error_body(err)
            if detail:
                raise RuntimeError(f"LLM HTTP {status} error: {detail}") from err
            raise RuntimeError(f"LLM HTTP {status} error: {err}") from err
        except LLMRequestAborted:
            raise
        except Exception as err:
            if is_retryable_network_error(err) and attempt < max_retries:
                if _aborted():
                    raise LLMRequestAborted(f"{log_prefix} 请求已被调用方取消") from err
                delay = compute_retry_delay(attempt, base_retry_delay=base_retry_delay)
                log(
                    f"{log_prefix} Retry on network error after {delay:.1f}s "
                    f"(attempt {attempt + 1}): {describe_network_error(err)}"
                )
                time.sleep(delay)
                continue

            raise ConnectionError(
                f"LLM network request failed: {describe_network_error(err)}"
            ) from err

    raise RuntimeError("LLM API did not return a response body")
