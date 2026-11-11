import json
import re
from typing import Any

AUDITOR_SYSTEM_PROMPT = """Você é o Agente Auditor de Qualidade e Roteamento de Tickets do NexusTech Support.
Sua missão é auditar a <RESPOSTA_DO_REDATOR> frente à <MENSAGEM_DO_CLIENTE> e definir o roteamento técnico do ticket ("N1", "N2" ou "N3").

REGRAS DE ROTEAMENTO E JULGAMENTO:
1. CASO DE AUTOATENDIMENTO ("nivel_escalonamento": "N1"):
   - Ocorre quando a <MENSAGEM_DO_CLIENTE> relata um problema inicial que pode ser resolvido pelos passos de <DIRETRIZES_N1> (e o cliente ainda não declarou que tentou e falhou).
   - O Redator deve explicar o passo a passo do painel sem prometer transferir o chamado imediatamente.
2. CASO DE ESCALONAMENTO ("nivel_escalonamento": "N2" ou "N3"):
   - Ocorre quando a <MENSAGEM_DO_CLIENTE> já atinge um gatilho de <REGRAS_DE_ESCALONAMENTO_N2_N3> (ex: o botão não aparece mesmo com e-mail validado; perdeu o celular 2FA e não tem códigos de recuperação; já tentou os passos e falhou).
   - Atenção: Para o cliente, o Redator deve apenas informar educadamente que está transferindo para um "especialista" ou "equipe dedicada" (sem usar jargões como N2/N3/Backoffice e sem prometer prazos de horas da fila humana), e NÃO deve mandar o cliente repetir passos que já falharam ou que ele está impedido de acessar.
   - Já você (Auditor), no JSON de saída, DEVE classificar "nivel_escalonamento" como "N2" ou "N3" conforme a regra técnica de <REGRAS_DE_ESCALONAMENTO_N2_N3> para que o sistema escale o ticket!
3. QUANDO REPROVAR ("aprovado_para_envio": false):
   - Se o Redator inventar menus, regras, prazos ou valores em R$ que o cliente não informou ("redator_alucinou": true).
   - Se o caso já exigia escalonamento (ex: cliente sem código de recuperação 2FA ou passo N1 já falhou) e o Redator insistiu em mandar o cliente fazer passos N1 no painel em vez de encaminhar ao especialista.
   - Se o caso era N1 simples e o Redator disse que já está transferindo o chamado agora.
   - Se esquecer a tag `[[FONTE: ...]]` ao final.

SAÍDA OBRIGATÓRIA (APENAS JSON VÁLIDO):
{
  "analise_raciocinio": "1 frase explicando se a resposta respeitou o manual e o porquê do nível técnico ser N1, N2 ou N3.",
  "aprovado_para_envio": true,
  "redator_alucinou": false,
  "citou_fonte": true,
  "nivel_escalonamento": "N1",
  "feedback_correcao": ""
}
"""


def construir_prompt_auditor(
    pergunta_cliente: str,
    resposta_redator: str,
    chunks_fatiados: list[dict[str, Any]],
) -> dict[str, str]:
    """
    Monta o system e user prompt do Auditor com diretrizes N1 e regras de escalonamento
    """
    if not chunks_fatiados:
        regras_n1 = "[FORA_DE_ESCOPO] Sem diretrizes N1."
        regras_escalonamento = "[FORA_DE_ESCOPO] Qualquer caso sem cobertura na base deve ser escalonado para N2."
    else:
        regras_n1 = ""
        regras_escalonamento = ""
        for c in chunks_fatiados:
            regras_n1 += f"[{c['chunk_id']}] {c['fatias']['resolucao_n1']}\n"
            regras_escalonamento += f"[{c['chunk_id']}] {c['fatias']['escalonamento']}\n"

    user_prompt = (
        f"<MENSAGEM_DO_CLIENTE>\n{pergunta_cliente}\n</MENSAGEM_DO_CLIENTE>\n\n"
        f"<DIRETRIZES_N1>\n{regras_n1}</DIRETRIZES_N1>\n\n"
        f"<REGRAS_DE_ESCALONAMENTO_N2_N3>\n{regras_escalonamento}</REGRAS_DE_ESCALONAMENTO_N2_N3>\n\n"
        f"<RESPOSTA_DO_REDATOR>\n{resposta_redator}\n</RESPOSTA_DO_REDATOR>\n\n"
        f"Retorne exclusivamente o JSON de auditoria."
    )

    return {
        "system_prompt": AUDITOR_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }


def extrair_json_auditoria(resposta_llm: str) -> dict[str, Any]:
    """
    Limpa marcações Markdown/think e converte a resposta bruta do Auditor em dict
    """
    texto = re.sub(r"<think>.*?</think>", "", resposta_llm, flags=re.DOTALL).strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE).strip()
    match = re.search(r"\{.*\}", texto, flags=re.DOTALL)

    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {
        "analise_raciocinio": "Falha ao converter JSON do auditor.",
        "aprovado_para_envio": False,
        "redator_alucinou": False,
        "citou_fonte": False,
        "nivel_escalonamento": "N1",
        "feedback_correcao": "Mantenha a resposta fiel ao manual e inclua [[FONTE: Chunk_ID]] ao final.",
    }