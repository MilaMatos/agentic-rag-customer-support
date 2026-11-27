import json
import os
from pathlib import Path
import time
from dotenv import load_dotenv
from openai import OpenAI

from src.eval.probe_models import PROMPT_JSON, _extrair_json_valido

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

TESTES = [
    ("nvidia/nemotron-3.5-lightning-30b-a3b", {"enable_thinking": True}, 60),
    ("nvidia/nemotron-3.5-lightning-30b-a3b", {"enable_thinking": False}, 60),
    ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", {"enable_thinking": False}, 60),
    ("nvidia/nemotron-3.5-super-vl-120b-a12b", {"enable_thinking": True}, 60),
    ("nvidia/nemotron-3.5-super-vl-120b-a12b", {"enable_thinking": False}, 60),
    ("nvidia/nemotron-3-ultra-550b-a55b", {"enable_thinking": False}, 75),
    ("moonshotai/kimi-k3.1-pro", {"enable_thinking": False}, 90),
    ("moonshotai/kimi-k3.1-pro", None, 90),
    ("z-ai/glm-5.3-flash", {"enable_thinking": False}, 90),
    ("mistralai/mistral-large-4-1t-a52b", None, 90),
]


def main() -> None:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resultados = []

    for model_id, chat_kwargs, timeout_s in TESTES:
        modo = f"thinking={chat_kwargs['enable_thinking']}" if chat_kwargs else "padrao"
        print(f"Testando {model_id} [{modo}] ...", end=" ", flush=True)
        t0 = time.perf_counter()
        try:
            params = {
                "model": model_id,
                "messages": [{"role": "user", "content": PROMPT_JSON}],
                "temperature": 0.0,
                "max_tokens": 2048,
                "timeout": timeout_s,
            }
            if chat_kwargs is not None:
                params["extra_body"] = {"chat_template_kwargs": chat_kwargs}

            resp = client.chat.completions.create(**params)
            lat = round(time.perf_counter() - t0, 2)
            msg = resp.choices[0].message
            content = (msg.content or "").strip()
            reasoning = (getattr(msg, "reasoning_content", None) or "").strip()
            json_ok = _extrair_json_valido(content)

            print(f"OK | {lat}s | JSON={json_ok} | reasoning_len={len(reasoning)}")
            resultados.append({
                "model_id": model_id,
                "modo": modo,
                "ok": True,
                "latencia_s": lat,
                "json_valido": json_ok,
                "reasoning_len": len(reasoning),
                "content_len": len(content),
            })
        except Exception as exc:
            lat = round(time.perf_counter() - t0, 2)
            err = f"{type(exc).__name__}: {str(exc)[:140]}"
            print(f"ERRO ({lat}s) -> {err}")
            resultados.append({
                "model_id": model_id,
                "modo": modo,
                "ok": False,
                "latencia_s": lat,
                "erro": err,
            })
        time.sleep(1.0)

    saida = Path("logs/probe_adaptacao_nim.json")
    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"\nSalvo em: {saida.resolve()}")


if __name__ == "__main__":
    main()