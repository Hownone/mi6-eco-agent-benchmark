from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LLMProvider:
    model: str
    api_key: str
    api_base: str | None = None

    @property
    def litellm_model(self) -> str:
        if self.api_base:
            return f"openai/{self.model}"
        return self.model


def _resolve_api_key(env_vars: list[str]) -> str | None:
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            return val
    return None


@dataclass
class BenchmarkConfig:
    primary_model: str = "openrouter/anthropic/claude-sonnet-4.6"
    fallback_models: list[str] = field(
        default_factory=lambda: [
            "deepseek-reasoner",
            "glm-5",
        ]
    )

    openrouter_api_key: str | None = field(default=None)
    deepseek_api_key: str | None = field(default=None)
    zhipu_api_key: str | None = field(default=None)

    default_pdk_target: str = "generic"
    default_max_route_layer: str = "METAL6"
    default_min_route_layer: str = "METAL1"
    default_power_nets: list[str] = field(default_factory=lambda: ["VDD"])
    default_ground_nets: list[str] = field(default_factory=lambda: ["VSS"])

    def __post_init__(self) -> None:
        if not self.openrouter_api_key:
            self.openrouter_api_key = _resolve_api_key(
                [
                    "OPENROUTER_API_KEY",
                    "MI6_PROVIDERS__OPENROUTER__API_KEY",
                ]
            )
        if not self.deepseek_api_key:
            self.deepseek_api_key = _resolve_api_key(
                [
                    "MI6_PROVIDERS__DEEPSEEK__API_KEY",
                    "DEEPSEEK_API_KEY",
                ]
            )
        if not self.zhipu_api_key:
            self.zhipu_api_key = _resolve_api_key(
                [
                    "MI6_PROVIDERS__BIGMODEL__API_KEY",
                    "ZHIPU_API_KEY",
                ]
            )

    def get_provider(self) -> LLMProvider:
        if self.openrouter_api_key:
            return LLMProvider(
                model=self.primary_model,
                api_key=self.openrouter_api_key,
            )

        if self.deepseek_api_key:
            return LLMProvider(
                model="deepseek-reasoner",
                api_key=self.deepseek_api_key,
                api_base="https://api.deepseek.com",
            )

        if self.zhipu_api_key:
            return LLMProvider(
                model="glm-5",
                api_key=self.zhipu_api_key,
                api_base="https://open.bigmodel.cn/api/paas/v4",
            )

        raise RuntimeError(
            "No LLM API key found. Set MI6_PROVIDERS__OPENROUTER__API_KEY, "
            "MI6_PROVIDERS__DEEPSEEK__API_KEY, or MI6_PROVIDERS__BIGMODEL__API_KEY."
        )

    def get_fallback_providers(self) -> list[LLMProvider]:
        providers: list[LLMProvider] = []

        if self.deepseek_api_key:
            providers.append(
                LLMProvider(
                    model="deepseek-reasoner",
                    api_key=self.deepseek_api_key,
                    api_base="https://api.deepseek.com",
                )
            )

        if self.zhipu_api_key:
            providers.append(
                LLMProvider(
                    model="glm-5",
                    api_key=self.zhipu_api_key,
                    api_base="https://open.bigmodel.cn/api/paas/v4",
                )
            )

        return providers


DEFAULT_CASES_DIR = Path("/home/project/haonan/eco-agent-cases/cases")
