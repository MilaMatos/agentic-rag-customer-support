from dataclasses import dataclass, field
import os
from typing import Any, Optional
from dotenv import load_dotenv
from crewai import LLM

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


@dataclass
class LLMConfig:
    model: str
    temperature: float = 0.0
    max_tokens: int = 1500
    timeout: int = 45
    context_window_size: int = 32768
    enable_thinking: Optional[bool] = None
    extra_body: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "enable_thinking": self.enable_thinking,
        }


# Perfis padrão adaptados às características de cada modelo na NIM
MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "nvidia/nemotron-3.5-bolt-e4b": {"max_tokens": 1024, "timeout": 30},
    "poolside/laguna-xs-2.1": {"max_tokens": 1024, "timeout": 30},
    "minimaxai/minimax-m3.1-flash": {"max_tokens": 1500, "timeout": 40},
    "nvidia/ising-calibration-1.5-31b": {"max_tokens": 1500, "timeout": 45},
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": {"max_tokens": 2048, "timeout": 45},
    "nvidia/nemotron-3.5-lightning-30b-a3b": {"max_tokens": 2048, "timeout": 45},
    "nvidia/nemotron-3.5-super-vl-120b-a12b": {"max_tokens": 2048, "timeout": 60},
    "nvidia/nemotron-3-ultra-550b-a55b": {"max_tokens": 2048, "timeout": 75},
    "moonshotai/kimi-k3.1-pro": {"max_tokens": 2048, "timeout": 90},
    "mistralai/mistral-large-4-1t-a52b": {"max_tokens": 2048, "timeout": 120},
    "z-ai/glm-5.3-flash": {"max_tokens": 2048, "timeout": 90},
}


def resolver_config(spec: str | LLMConfig | dict[str, Any], **overrides: Any) -> LLMConfig:
    if isinstance(spec, LLMConfig):
        base = {**spec.__dict__, **overrides}
        return LLMConfig(**base)

    if isinstance(spec, dict):
        model = spec["model"]
        defaults = MODEL_DEFAULTS.get(model, {})
        merged = {**defaults, **spec, **overrides}
        return LLMConfig(**merged)

    defaults = MODEL_DEFAULTS.get(spec, {})
    merged = {"model": spec, **defaults, **overrides}
    return LLMConfig(**merged)


def criar_llm(spec: str | LLMConfig | dict[str, Any], **overrides: Any) -> LLM:
    if not API_KEY:
        raise ValueError("NVIDIA_API_KEY não encontrada no .env")

    cfg = resolver_config(spec, **overrides)
    extra = dict(cfg.extra_body)
    if cfg.enable_thinking is not None:
        chat_kwargs = dict(extra.get("chat_template_kwargs", {}))
        chat_kwargs["enable_thinking"] = cfg.enable_thinking
        extra["chat_template_kwargs"] = chat_kwargs

    kwargs: dict[str, Any] = {
        "model": cfg.model,
        "custom_openai": True,
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout": cfg.timeout,
        "context_window_size": cfg.context_window_size,
    }
    if extra:
        kwargs["extra_body"] = extra

    return LLM(**kwargs)