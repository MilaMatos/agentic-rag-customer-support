from typing import Any, Optional

REDATOR_SYSTEM_PROMPT = """Você é um especialista de atendimento do suporte da NexusTech Solutions.
Sua missão é escrever a mensagem enviada DIRETAMENTE ao cliente no chat, com tom natural, empático e objetivo.

REGRAS DE OURO (GUARDRAILS):
1. ZERO RÓTULOS ROBÓTICOS: NUNCA use títulos como "Diagnóstico:", "Passo a Passo:" ou "Resolução N1:". Escreva em parágrafos curtos e naturais.
2. FIDELIDADE ESTRITA E DADOS DO CLIENTE:
   - Use apenas os menus, caminhos e regras presentes em <BASE_DE_CONHECIMENTO>.
   - NUNCA assuma valores em Reais (R$), números de transação ou locais que o cliente não tenha dito na mensagem dele (valores na documentação são apenas tetos de política ou exemplos).
3. COMO AGIR EM AUTOATENDIMENTO vs. TRANSFERÊNCIA PARA ESPECIALISTA:
   - CASO A (O cliente ainda pode resolver via autoatendimento no painel): Acolha o cliente e explique claramente o passo a passo de <DIRETRIZES_DE_AUTOATENDIMENTO>. Mencione apenas os tempos de processamento automático do sistema que constam no passo a passo (ex: bloqueio em 5 minutos, atualização em 15 minutos). Ao final, diga apenas para avisar caso o problema persista após tentar os passos. NÃO fale em transferir o chamado agora.
   - CASO B (A mensagem do cliente JÁ SE ENQUADRA nos <GATILHOS_DE_ESCALONAMENTO_INTERNO> ou está FORA_DE_ESCOPO):
     * NÃO mande o cliente repetir passos que já falharam ou entrar em telas que ele está bloqueado de acessar.
     * Escreva uma mensagem curta e tranquilizadora informando apenas que, devido a essa condição específica, você já está encaminhando o atendimento diretamente para um **especialista da nossa equipe dedicada** dar sequência na solução.
     * PROIBIDO USAR JARGÃO INTERNO OU PRAZOS DE FILA HUMANA: Nunca use os termos "N1", "N2", "N3", "Backoffice" ou "Engenharia" para o cliente, e NUNCA prometa prazos de retorno da equipe humana (como "em até 2 horas" ou "4 horas").
    - Enquanto o cliente ainda não tiver tentado os passos N1, forneça apenas as instruções de resolução e peça retorno caso não funcione, sem antecipar prazos ou regras internas de escalonamento N2/N3.
4. ESCOPO: Nunca prometa ler logs de servidor ou acessar bancos de dados diretamente.
5. IDIOMA: Responda sempre em Português do Brasil.
6. TAG DE RASTREABILIDADE INTERNA: Na última linha da resposta, pule uma linha e escreva EXATAMENTE: `[[FONTE: Chunk_ID]]` (ex: `[[FONTE: MAN-FRAU-001-SEC-03]]`). Se <BASE_DE_CONHECIMENTO> estiver vazia, use `[[FONTE: FORA_DE_ESCOPO]]`.
"""


# Altere a assinatura e o início da função construir_prompt_redator em src/agents/prompts/redactor.py:

def construir_prompt_redator(
    pergunta_cliente: str,
    chunks_fatiados: Optional[list[dict[str, Any]]] = None,
    feedback_auditor: Optional[str] = None,
    categoria_sugerida: str = "",
    historico_conversa: str = "",
    forcar_escalonamento_limite: bool = False,
) -> dict[str, str]:
    """Monta os prompts do Redator com suporte a Tool, histórico e circuit breaker."""
    if chunks_fatiados is None:
        dica_cat = f" (use category='{categoria_sugerida}')" if categoria_sugerida else ""
        contexto_str = (
            f"[INSTRUÇÃO DE TOOL]: Use obrigatoriamente a ferramenta `buscar_manual_rag_tool`{dica_cat} "
            f"para consultar a base de conhecimento antes de responder ao cliente."
        )
    elif len(chunks_fatiados) == 0:
        contexto_str = (
            "[Chunk_ID: FORA_DE_ESCOPO]\n"
            "Nenhum manual encontrado para esta solicitação. Informe educadamente ao cliente "
            "que está transferindo o atendimento para um especialista analisar a solicitação."
        )
    else:
        blocos = []
        for c in chunks_fatiados:
            blocos.append(
                f"[Chunk_ID: {c['chunk_id']} | Subcategoria: {c['subcategory']}]\n"
                f"- DIRETRIZES_DE_AUTOATENDIMENTO: {c['fatias']['resolucao_n1']}\n"
                f"- GATILHOS_DE_ESCALONAMENTO_INTERNO: {c['fatias']['escalonamento']}"
            )
        contexto_str = "\n\n".join(blocos)

    bloco_historico = ""
    if historico_conversa:
        bloco_historico = (
            f"\n=== HISTÓRICO RECENTE DA CONVERSA ===\n"
            f"{historico_conversa}\n"
            f"Instrução de Histórico: Se o cliente relatar na mensagem atual que já tentou os passos "
            f"ensinados anteriormente e o problema persistiu, NÃO repita o passo a passo; informe que "
            f"está transferindo o chamado para um especialista.\n"
        )

    bloco_limite = ""
    if forcar_escalonamento_limite:
        chunk_id_ref = (
            chunks_fatiados[0]["chunk_id"]
            if chunks_fatiados and len(chunks_fatiados) > 0
            else "FORA_DE_ESCOPO"
        )
        bloco_limite = (
            f"\n=== [ALERTA DE LIMITE DE TURNOS ATINGIDO - CIRCUIT BREAKER] ===\n"
            f"O cliente atingiu o limite máximo de interações sobre este mesmo problema sem resolução no N1. "
            f"É PROIBIDO enviar novos passos técnicos ou fazer novas perguntas. "
            f"Agradeça a paciência, informe educadamente que está transferindo o atendimento para um "
            f"especialista da equipe dedicada dar continuidade e encerre com [[FONTE: {chunk_id_ref}]].\n"
        )

    bloco_feedback = ""
    if feedback_auditor:
        bloco_feedback = (
            f"\n=== CORREÇÃO OBRIGATÓRIA DO AUDITOR ===\n"
            f"Sua resposta anterior foi reprovada pelo seguinte motivo: {feedback_auditor}\n"
            f"Corrija imediatamente seguindo o manual.\n"
        )

    user_prompt = f"""=== BASE DE CONHECIMENTO (MANUAL TÉCNICO) ===
{contexto_str}
{bloco_historico}{bloco_limite}{bloco_feedback}
=== MENSAGEM ATUAL DO CLIENTE ===
{pergunta_cliente}

Redija a resposta para o cliente e lembre-se de colocar a tag [[FONTE: Chunk_ID]] na última linha:"""

    return {"system_prompt": REDATOR_SYSTEM_PROMPT, "user_prompt": user_prompt}