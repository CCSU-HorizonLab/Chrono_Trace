"""画像 LLM 调用的输出预算加倍重试（contact/self profiler 共用）。

此前两个 profiler 各自维护一份逐行相同的 ~60 行循环（预算加倍、
finish_reason 判定、reasoning_content 回退、usage 日志），修 bug 极易
漂移——抽为单点。混合推理模型的思考长度随输入波动且计入 completion
额度，无法预算，输出被 max_tokens 截断时逐级加倍重试。
"""
from __future__ import annotations

from typing import Callable, Optional

MAX_OUTPUT_TOKEN_BUDGET = 32768


def call_profile_llm_with_budget_retry(
    *,
    url: str,
    payload: dict,
    headers: dict,
    timeout: float,
    initial_budget: int,
    parse_json: Callable[[str], Optional[dict]],
    extract_json_candidate: Callable[[str], str],
    post_json: Callable,
    log: Callable[..., None],
    log_prefix: str,
) -> Optional[dict]:
    """跑一次画像生成调用（含截断加倍重试），返回解析后的 dict 或 None。

    parse_json / extract_json_candidate 由调用方注入（两个 profiler 的
    解析实现略有差异，保持各自行为不变）。
    """
    attempt_budget = initial_budget
    while True:
        payload["max_tokens"] = attempt_budget
        body = post_json(
            url=url,
            payload=payload,
            headers=headers,
            timeout=timeout,
            log=log,
            log_prefix=log_prefix,
        )

        choice = (body.get("choices") or [{}])[0]
        message_obj = choice.get("message", {})
        content = message_obj.get("content", "") or ""
        reasoning = message_obj.get("reasoning_content", "")

        # content 为空时只有 reasoning 中确实含完整 JSON 才回退（推理模型
        # 可能只输出思考；response_format + 更大预算优先保证 content）
        if not content and reasoning:
            reasoning_candidate = extract_json_candidate(reasoning)
            if reasoning_candidate.lstrip().startswith("{") and reasoning_candidate.rstrip().endswith("}"):
                content = reasoning_candidate
                log(f"{log_prefix} ⚠️ content 为空，使用 reasoning_content 中的 JSON 回退")
            else:
                log(f"{log_prefix} ⚠️ content 为空且 reasoning_content 没有完整 JSON")

        usage = body.get("usage", {})
        log(
            f"{log_prefix} 📥 tokens: prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')}, "
            f"total={usage.get('total_tokens', '?')}"
        )

        parsed = parse_json(content)
        if parsed:
            return parsed

        completion_tokens = usage.get("completion_tokens") or 0
        truncated = (
            choice.get("finish_reason") == "length"
            or completion_tokens >= attempt_budget
        )
        if not truncated or attempt_budget >= MAX_OUTPUT_TOKEN_BUDGET:
            return None
        attempt_budget = min(attempt_budget * 2, MAX_OUTPUT_TOKEN_BUDGET)
        log(
            f"{log_prefix} ⚠️ 输出在 {attempt_budget // 2} token 处被截断"
            f"（推理模型的思考计入了输出额度），加大到 {attempt_budget} 重试"
        )
