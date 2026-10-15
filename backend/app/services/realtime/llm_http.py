import json
import re
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


# ---------------------------------------------------------------------------
# 思考量定档：交互链路（实时建议/问问微信/群日报/画像）快速模式默认
# reasoning_effort:"low"（OpenAI 兼容面通用，vLLM 亦支持）；深度链路
# （RAG 事实抽取/关系评估）固定 "medium"。模型级 extra_body（用户显式
# JSON，如 strata 网关私有 reasoning_budget_tokens）先合入且优先。
# ---------------------------------------------------------------------------
REASONING_MODEL_TAGS = (
    "reasoner", "deepseek-r1", "-r1", "qwen3", "qwq", "o1", "o3", "thinking",
)


def is_reasoning_model(model_id: str) -> bool:
    """按模型标识粗判思考模型（下发 reasoning_effort / 兜底 token 预算用）。"""
    normalized = (model_id or "").lower()
    return any(tag in normalized for tag in REASONING_MODEL_TAGS)


def is_legacy_qwen3(model_id: str) -> bool:
    """旧 Qwen3（3.0 系，不含 3.5/3.6）：prompt 前置 /no_think 软开关有效。"""
    m = re.search(r"qwen3(\.\d)?", (model_id or "").lower())
    return bool(m) and m.group(1) is None


def interactive_fast_mode_enabled() -> bool:
    """交互调用快速模式开关（设置键沿用 llm_fast_suggestion_mode，默认开）。"""
    try:
        from ..wechat.account_settings import load_settings_from_file
        return bool(load_settings_from_file().get("llm_fast_suggestion_mode", True))
    except Exception:
        return True


def _parse_extra_body(raw: Any) -> dict:
    """解析模型级 extra_body JSON；空/非法/非对象一律视为无附加参数。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def apply_interactive_fast_mode(payload: dict, model_config: dict) -> dict:
    """交互链路（实时建议/问问微信/群日报/画像）快速模式：开关开启且
    思考模型未显式指定时附 reasoning_effort:"low"；模型级 extra_body
    显式配置优先。"""
    return _apply_reasoning_effort(
        payload, model_config, "low", interactive_fast_mode_enabled()
    )


def apply_deep_call_effort(payload: dict, model_config: dict) -> dict:
    """深度链路（RAG 事实抽取/关系评估）思考量定档：思考模型附
    reasoning_effort:"medium"——不随快速模式开关（深度调用保留思考，
    但也不吃网关默认档——实测默认档思考量随 prompt 放大，长 prompt 易
    在思维链里耗尽输出预算）；模型级 extra_body 显式配置优先。"""
    return _apply_reasoning_effort(payload, model_config, "medium", True)


def _apply_reasoning_effort(
    payload: dict, model_config: dict, effort: str, enabled: bool
) -> dict:
    """就地合并思考量参数：extra_body 显式配置先合入（setdefault 保用户
    值），再按需补默认 reasoning_effort（调用方已显式指定则不动）。"""
    config = model_config or {}
    for key, value in _parse_extra_body(config.get("extra_body")).items():
        payload.setdefault(key, value)
    if (
        enabled
        and "reasoning_effort" not in payload
        and is_reasoning_model(str(config.get("model_id") or ""))
    ):
        payload["reasoning_effort"] = effort
    return payload


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
