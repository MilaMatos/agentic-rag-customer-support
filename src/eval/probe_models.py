import json
import os
from pathlib import Path
import re
import time
from dotenv import load_dotenv
from openai import OpenAI
from crewai import Agent, Crew, LLM, Process, Task

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

MODELOS_CANDIDATOS = [
    "bigcode/starcoder2-15b",
    "fastino/gliner2-pii",
    "google/gemma-3-12b-it",
    "google/gemma-3-4b-it",
    "minimaxai/minimax-m3.1-flash",
    "mistralai/mistral-large-4-1t-a52b",
    "moonshotai/kimi-k3.1-pro",
    "nvidia/ai-synthetic-video-detector",
    "nvidia/cosmos-reason2-8b",
    "nvidia/ising-calibration-1.5-31b",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3.5-bolt-e4b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/nvclip",
    "nvidia/riva-translate-4b-instruct-v2",
    "poolside/laguna-xs-2.1",
    "stepfun-ai/step-5-preview",
    "z-ai/glm-5.3-flash",
]

PROMPT_JSON = (
    'Classifique a mensagem "Meu painel não carrega, fica girando" em JSON estrito '
    'com as chaves "category" (Technical, Billing, Account, Fraud ou General Inquiry) '
    'e "resumo_pt" (máximo 8 palavras em português). Responda APENAS o JSON.'
)


def _extrair_json_valido(texto: str) -> bool:
    limpo = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.DOTALL).strip()
    limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpo, flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", limpo, flags=re.DOTALL)
    if not match:
        return False
    try:
        dados = json.loads(match.group(0))
        return isinstance(dados, dict) and "category" in dados
    except json.JSONDecodeError:
        return False


def testar_modelo_openai(client: OpenAI, model_id: str, timeout_s: float = 35.0) -> dict:
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": PROMPT_JSON}],
            temperature=0.0,
            max_tokens=1500,
            timeout=timeout_s,
        )
        latencia = round(time.perf_counter() - t0, 2)
        msg = resp.choices[0].message if resp.choices else None
        content = (msg.content or "").strip() if msg else ""
        reasoning = (getattr(msg, "reasoning_content", None) or "").strip() if msg else ""

        if not content and reasoning:
            return {
                "ok_openai": False,
                "latencia_openai_s": latencia,
                "json_valido": False,
                "usa_reasoning": True,
                "motivo": "content vazio (retornou apenas reasoning_content — incompatível com CrewAI sem ajuste)",
                "amostra": reasoning[:100].replace("\n", " "),
            }

        if not content:
            return {
                "ok_openai": False,
                "latencia_openai_s": latencia,
                "json_valido": False,
                "usa_reasoning": False,
                "motivo": "Resposta vazia (content e reasoning_content nulos)",
                "amostra": "",
            }

        json_ok = _extrair_json_valido(content)
        return {
            "ok_openai": True,
            "latencia_openai_s": latencia,
            "json_valido": json_ok,
            "usa_reasoning": bool(reasoning) or ("<think>" in content),
            "motivo": "" if json_ok else "Respondeu texto, mas não seguiu JSON estrito",
            "amostra": content[:120].replace("\n", " "),
        }
    except Exception as exc:
        latencia = round(time.perf_counter() - t0, 2)
        return {
            "ok_openai": False,
            "latencia_openai_s": latencia,
            "json_valido": False,
            "usa_reasoning": False,
            "motivo": f"{type(exc).__name__}: {str(exc)[:180]}",
            "amostra": "",
        }


def testar_modelo_crewai(model_id: str) -> tuple[bool, float, str]:
    t0 = time.perf_counter()
    try:
        llm = LLM(
            model=model_id,
            custom_openai=True,
            base_url=BASE_URL,
            api_key=API_KEY,
            temperature=0.0,
            max_tokens=1500,
            timeout=35,
        )
        agente = Agent(
            role="Classificador",
            goal="Retornar JSON válido.",
            backstory="Agente de teste rápido.",
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )
        task = Task(
            description=PROMPT_JSON,
            expected_output="JSON com category e resumo_pt.",
            agent=agente,
        )
        crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
        crew.kickoff()
        latencia = round(time.perf_counter() - t0, 2)
        raw = (task.output.raw or "").strip()
        if not raw:
            return False, latencia, "CrewAI retornou output vazio"
        return True, latencia, ""
    except Exception as exc:
        latencia = round(time.perf_counter() - t0, 2)
        return False, latencia, f"{type(exc).__name__}: {str(exc)[:180]}"


def main() -> None:
    if not API_KEY:
        raise ValueError("NVIDIA_API_KEY não encontrada no .env")

    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resultados = []

    print(f"Testando {len(MODELOS_CANDIDATOS)} modelos na NVIDIA NIM...\n")

    for i, model_id in enumerate(MODELOS_CANDIDATOS, start=1):
        print(f"[{i:02d}/{len(MODELOS_CANDIDATOS)}] {model_id} ...", end=" ", flush=True)
        res = testar_modelo_openai(client, model_id)
        res["model_id"] = model_id
        res["ok_crewai"] = False
        res["latencia_crewai_s"] = None

        if res["ok_openai"]:
            ok_crew, lat_crew, err_crew = testar_modelo_crewai(model_id)
            res["ok_crewai"] = ok_crew
            res["latencia_crewai_s"] = lat_crew
            if not ok_crew:
                res["motivo"] = f"OpenAI OK, mas falhou no CrewAI: {err_crew}"

        aprovado = res["ok_openai"] and res["ok_crewai"]
        res["aprovado"] = aprovado

        status = "APROVADO" if aprovado else "FALHOU"
        extra = f"({res['latencia_crewai_s']}s | JSON={res['json_valido']} | reasoning={res['usa_reasoning']})" if aprovado else f"-> {res['motivo']}"
        print(f"{status} {extra}")
        resultados.append(res)
        time.sleep(0.8)

    aprovados = [r for r in resultados if r["aprovado"]]
    reprovados = [r for r in resultados if not r["aprovado"]]

    print("\n" + "=" * 90)
    print(f"APROVADOS PARA BENCHMARK ({len(aprovados)}/{len(resultados)}):")
    print("=" * 90)
    for r in sorted(aprovados, key=lambda x: x["latencia_crewai_s"] or 999):
        print(
            f"  - {r['model_id']:<45} | CrewAI: {r['latencia_crewai_s']:>5}s | "
            f"JSON: {str(r['json_valido']):<5} | Reasoning: {str(r['usa_reasoning']):<5}"
        )

    print("\n" + "=" * 90)
    print(f"REPROVADOS / IGNORAR ({len(reprovados)}/{len(resultados)}):")
    print("=" * 90)
    for r in reprovados:
        print(f"  - {r['model_id']:<45} | Motivo: {r['motivo']}")

    saida = Path("logs/probe_models_nim.json")
    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"\nRelatório completo salvo em: {saida.resolve()}")


if __name__ == "__main__":
    main()