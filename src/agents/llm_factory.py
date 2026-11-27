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
    timeout: int = 40
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


MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    "nvidia/nemotron-3.5-bolt-e4b": {"max_tokens": 1024, "timeout": 25},
    "nvidia/nemotron-3.5-lightning-30b-a3b": {"max_tokens": 2048, "timeout": 30},
    "nvidia/nemotron-3.5-super-vl-120b-a12b": {"max_tokens": 2048, "timeout": 40},
    "nvidia/nemotron-3-ultra-550b-a55b": {"max_tokens": 2048, "timeout": 45},
}

DEFAULT_AGENT_MODELS: dict[str, dict[str, dict[str, Any]]] = {
    "classifier": {
        "primary": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
        "fallback": {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "enable_thinking": False},
    },
    "redactor": {
        "primary": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "fallback": {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "enable_thinking": False},
    },
    "auditor": {
        "primary": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "fallback": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
    },
    "summarizer": {
        "primary": {"model": "nvidia/nemotron-3.5-bolt-e4b", "enable_thinking": False},
        "fallback": {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "enable_thinking": False},
    },
}


def resolver_config(spec: str | LLMConfig | dict[str, Any], **overrides: Any) -> LLMConfig:
    if isinstance(spec, LLMConfig):
        return LLMConfig(**{**spec.__dict__, **overrides})

    if isinstance(spec, dict):
        defaults = MODEL_DEFAULTS.get(spec["model"], {})
        return LLMConfig(**{**defaults, **spec, **overrides})

    defaults = MODEL_DEFAULTS.get(spec, {})
    return LLMConfig(**{"model": spec, **defaults, **overrides})


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


def criar_llms_agente(
    role: str,
    override_spec: Optional[str | LLMConfig | dict[str, Any]] = None,
    **overrides: Any,
) -> tuple[LLM, Optional[LLM]]:
    cfg = DEFAULT_AGENT_MODELS[role]
    primary_spec = override_spec if override_spec is not None else cfg["primary"]
    fallback_spec = cfg["fallback"]

    llm_primary = criar_llm(primary_spec, **overrides)
    if resolver_config(primary_spec).model == resolver_config(fallback_spec).model:
        return llm_primary, None

    llm_fallback = criar_llm(fallback_spec, **overrides)
    return llm_primary, llm_fallback