from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import litellm

from benchmark.config import BenchmarkConfig, LLMProvider

logger = logging.getLogger(__name__)

litellm.drop_params = True

_SOCKS_PROXY_CLEANED = False


def _clean_socks_proxy() -> None:
    global _SOCKS_PROXY_CLEANED
    if _SOCKS_PROXY_CLEANED:
        return
    _SOCKS_PROXY_CLEANED = True

    for var in ("ALL_PROXY", "all_proxy"):
        val = os.environ.get(var, "")
        if val.startswith("socks"):
            logger.info("Removing %s=%s (aiohttp incompatible)", var, val)
            os.environ.pop(var, None)


async def call_llm(
    config: BenchmarkConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> str:
    _clean_socks_proxy()

    provider = config.get_provider()
    fallbacks = config.get_fallback_providers()

    providers_to_try = [provider, *fallbacks]

    last_error: Exception | None = None
    for p in providers_to_try:
        try:
            return await _call_single(
                p,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                json_mode,
            )
        except Exception as e:
            logger.warning("LLM call failed with %s: %s", p.model, e)
            last_error = e
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")


async def _call_single(
    provider: LLMProvider,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> str:
    kwargs: dict = {
        "model": provider.litellm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": provider.api_key,
    }

    if provider.api_base:
        kwargs["api_base"] = provider.api_base

    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response: Any = await litellm.acompletion(**kwargs)
    content = response.choices[0].message.content or ""
    return content.strip()


def extract_json_from_response(text: str) -> dict:
    json_block = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if json_block:
        return json.loads(json_block.group(1))

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    return json.loads(text)
