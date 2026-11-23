CLASSIFIER_SYSTEM_PROMPT = (
    "Você é a primeira linha do suporte NexusTech. Sua missão é ler o problema do cliente "
    "e definir a categoria, prioridade e nível de atendimento inicial. "
    "Você é analítico, direto e nunca inventa informações."
)


# Em src/agents/prompts/classifier.py, adicione a função construir_prompt_classificador:

def construir_prompt_classificador(
    pergunta_cliente: str,
    historico_recente: str = "",
    categoria_anterior: str = "",
) -> dict[str, str]:
    contexto_memoria = ""
    if historico_recente:
        contexto_memoria = (
            f"\n[HISTÓRICO RECENTE DA SESSÃO (Categoria Anterior: {categoria_anterior})]\n"
            f"{historico_recente}\n"
        )

    user_prompt = f"""Analise a mensagem do cliente e retorne APENAS um objeto JSON válido seguindo o schema:
{contexto_memoria}
[MENSAGEM ATUAL DO CLIENTE]:
{pergunta_cliente}

REGRAS DE MULTI-TURNO PARA O JSON:
1. "category": Escolha entre "Technical", "Billing", "Account", "Fraud" ou "General Inquiry". Se a mensagem atual for uma resposta curta ou continuação do HISTÓRICO RECENTE, mantenha a Categoria Anterior ({categoria_anterior or 'N/A'}).
2. "priority": "Baixa", "Media", "Alta" ou "Critica".
3. "initial_level": "N1", "N2" ou "N3".
4. "triage_justification": Explicação curta da classificação.
5. "is_followup": booleano (true/false). Marque `true` SOMENTE se houver [HISTÓRICO RECENTE] e a mensagem atual tratar do mesmo problema/assunto. Se for o 1º turno ou se o cliente mudou de assunto, marque `false`.
6. "search_query": string com a pergunta reescrita de forma clara e completa para busca em banco vetorial (ex: se o cliente disse apenas "qual o valor?", reescreva combinando com o assunto do histórico).
"""
    return {"system_prompt": CLASSIFIER_SYSTEM_PROMPT, "user_prompt": user_prompt}