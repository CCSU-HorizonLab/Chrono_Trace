import json
import socket
import ssl
import time
import random
import urllib.error
import urllib.request
from typing import Any, Callable, Optional


DEFAULT_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_RETRY_DELAY = 1.5


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
) -> dict[str, Any]:
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
        except Exception as err:
            if is_retryable_network_error(err) and attempt < max_retries:
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
