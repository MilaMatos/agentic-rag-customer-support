from typing import Any

PRESETS_MODELOS: dict[str, dict[str, Any]] = {
    "copilot_fast": {
        "classifier": {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "enable_thinking": False},
        "redactor": {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "enable_thinking": False},
        "auditor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "summarizer": {"model": "nvidia/nemotron-3.5-bolt-e4b"},
    },
    "copilot_preciso": {
        "classifier": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
        "redactor": {"model": "nvidia/nemotron-3.5-lightning-30b-a3b", "enable_thinking": False},
        "auditor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "summarizer": {"model": "nvidia/nemotron-3.5-bolt-e4b"},
    },
    "autonomo_fast": {
        "classifier": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
        "redactor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "auditor": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
        "summarizer": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
    },
    "copilot_redator_super": {
        "classifier": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
        "redactor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "auditor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
        "summarizer": {"model": "nvidia/nemotron-3.5-bolt-e4b"},
    },
}