import json
import re
from typing import Any


def separar_mensagem_e_fonte(resposta_bruta: str) -> dict[str, str]:
    """Separa o texto limpo que vai para o cliente da tag técnica [[FONTE: ...]]"""
    texto = re.sub(r"<think>.*?</think>", "", resposta_bruta, flags=re.DOTALL).strip()
    match_fonte = re.search(r"\[\[FONTE:\s*([^\]]+)\]\]", texto, flags=re.IGNORECASE)
    fonte = match_fonte.group(1).strip() if match_fonte else "NÃO_CITADA"

    mensagem_limpa = re.sub(r"\[\[FONTE:\s*[^\]]+\]\]", "", texto, flags=re.IGNORECASE).strip()

    return {
        "mensagem_cliente": mensagem_limpa,
        "fonte_citada": fonte,
        "texto_completo_auditoria": texto,
    }


def extrair_json_auditoria(resposta_llm: str) -> dict[str, Any]:
    """Limpa marcações Markdown/think e converte a resposta bruta do Auditor em dict"""
    texto = re.sub(r"<think>.*?</think>", "", resposta_llm, flags=re.DOTALL).strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", texto, flags=re.DOTALL)

    dados = {}
    if match:
        try:
            dados = json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    if "requer_escalonamento" not in dados:
        nivel_antigo = dados.get("nivel_escalonamento", "N1")
        dados["requer_escalonamento"] = nivel_antigo in ("N2", "N3")

    return {
        "analise_raciocinio": dados.get("analise_raciocinio", "Análise não informada pelo auditor."),
        "aprovado_para_envio": bool(dados.get("aprovado_para_envio", True)),
        "redator_alucinou": bool(dados.get("redator_alucinou", False)),
        "citou_fonte": bool(dados.get("citou_fonte", True)),
        "requer_escalonamento": bool(dados.get("requer_escalonamento", False)),
        "feedback_correcao": dados.get("feedback_correcao", ""),
    }


def extrair_json_classificacao(resposta_llm: str) -> dict[str, Any]:
    """Limpa marcações Markdown/think e converte a resposta do Classificador em dict"""
    texto = re.sub(r"<think>.*?</think>", "", resposta_llm, flags=re.DOTALL).strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", texto, flags=re.DOTALL)

    dados = {}
    if match:
        try:
            dados = json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    categorias_validas = {"Technical", "Billing", "Account", "Fraud", "General Inquiry"}
    cat = dados.get("category") or dados.get("categoria") or "General Inquiry"
    if cat not in categorias_validas:
        cat = "General Inquiry"

    prioridades_validas = {"Baixa", "Media", "Alta", "Critica"}
    prio = dados.get("priority") or dados.get("prioridade") or "Media"
    if prio not in prioridades_validas:
        prio = "Media"

    niveis_validos = {"N1", "N2", "N3"}
    nivel = dados.get("initial_level") or dados.get("nivel_inicial") or "N1"
    if nivel not in niveis_validos:
        nivel = "N1"

    justificativa = (
        dados.get("triage_justification")
        or dados.get("justificativa_triagem")
        or "Triagem realizada automaticamente."
    )

    return {
        "category": cat,
        "priority": prio,
        "initial_level": nivel,
        "triage_justification": str(justificativa),
    }


def limpar_texto_resumo(resposta_llm: str) -> str:
    """Remove blocos de pensamento oculto do resumo executivo"""
    return re.sub(r"<think>.*?</think>", "", resposta_llm, flags=re.DOTALL).strip()