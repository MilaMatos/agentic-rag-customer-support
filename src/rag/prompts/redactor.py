import re
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
   - CASO B (A mensagem do cliente JÁ SE ENQUADRA nos <GATILHOS_DE_ESCALONAMENTO_INTERNO> — ex: o cliente já tentou os passos e falhou, o botão não aparece, ou perdeu o celular 2FA e não tem códigos de recuperação):
     * NÃO mande o cliente repetir passos que já falharam ou entrar em telas que ele está bloqueado de acessar.
     * Escreva uma mensagem curta e tranquilizadora informando apenas que, devido a essa condição específica, você já está encaminhando o atendimento diretamente para um **especialista da nossa equipe dedicada** dar sequência na solução.
     * PROIBIDO USAR JARGÃO INTERNO OU PRAZOS DE FILA HUMANA: Nunca use os termos "N1", "N2", "N3", "Backoffice" ou "Engenharia" para o cliente, e NUNCA prometa prazos de retorno da equipe humana (como "em até 2 horas" ou "4 horas"). O sistema fará o roteamento automático do ticket.
4. ESCOPO: Nunca prometa ler logs de servidor ou acessar bancos de dados diretamente.
5. IDIOMA: Responda sempre em Português do Brasil.
6. TAG DE RASTREABILIDADE INTERNA: Na última linha da resposta, pule uma linha e escreva EXATAMENTE: `[[FONTE: Chunk_ID]]` (ex: `[[FONTE: MAN-FRAU-001-SEC-03]]`). Se <BASE_DE_CONHECIMENTO> estiver vazia, use `[[FONTE: FORA_DE_ESCOPO]]`.
"""


def construir_prompt_redator(
    pergunta_cliente: str,
    chunks_fatiados: list[dict[str, Any]],
    feedback_auditor: Optional[str] = None,
) -> dict[str, str]:
    if not chunks_fatiados:
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
                f"- GATILHOS_DE_ESCALONAMENTO_INTERNO (Apenas para decidir se transfere para especialista): {c['fatias']['escalonamento']}"
            )
        contexto_str = "\n\n".join(blocos)

    bloco_correcao = ""
    if feedback_auditor:
        bloco_correcao = (
            f"<AJUSTE_SOLICITADO_PELO_AUDITOR>\n"
            f"{feedback_auditor}\n"
            f"Reescreva a mensagem corrigindo este ponto e mantenha a tag [[FONTE: Chunk_ID]] na última linha.\n"
            f"</AJUSTE_SOLICITADO_PELO_AUDITOR>\n\n"
        )

    user_prompt = (
        f"<BASE_DE_CONHECIMENTO>\n{contexto_str}\n</BASE_DE_CONHECIMENTO>\n\n"
        f"{bloco_correcao}"
        f"<MENSAGEM_DO_CLIENTE>\n{pergunta_cliente}\n</MENSAGEM_DO_CLIENTE>\n\n"
        f"Escreva a resposta direta para o cliente (com a tag [[FONTE: ...]] na última linha)."
    )

    return {
        "system_prompt": REDATOR_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }


def separar_mensagem_e_fonte(resposta_bruta: str) -> dict[str, str]:
    """Separa o texto limpo que vai para o cliente da tag técnica de fonte."""
    texto = re.sub(r"<think>.*?</think>", "", resposta_bruta, flags=re.DOTALL).strip()
    match_fonte = re.search(r"\[\[FONTE:\s*([^\]]+)\]\]", texto, flags=re.IGNORECASE)
    fonte = match_fonte.group(1).strip() if match_fonte else "NÃO_CITADA"

    mensagem_limpa = re.sub(r"\[\[FONTE:\s*[^\]]+\]\]", "", texto, flags=re.IGNORECASE).strip()

    return {
        "mensagem_cliente": mensagem_limpa,
        "fonte_citada": fonte,
        "texto_completo_auditoria": texto,
    }