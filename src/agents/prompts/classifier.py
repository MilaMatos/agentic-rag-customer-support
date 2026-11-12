CLASSIFIER_SYSTEM_PROMPT = (
    "Você é a primeira linha do suporte NexusTech. Sua missão é ler o problema do cliente "
    "e definir a categoria, prioridade e nível de atendimento inicial. "
    "Você é analítico, direto e nunca inventa informações."
)


def construir_prompt_classificador(pergunta_cliente: str) -> dict[str, str]:
    user_prompt = f"""Classifique o seguinte ticket do cliente: '{pergunta_cliente}'

Regras de Negócio da NexusTech (Siga estritamente):
- Todo problema de cobrança (duplicada, fatura errada) deve ser classificado inicialmente como N1, pois o cliente tem acesso ao autoatendimento no painel.
- Problemas técnicos que afetam todos os usuários devem ser N3.
- Dúvidas gerais sobre a plataforma devem ser N1.

Exemplos de Classificação:
Ticket: "I was charged twice for the same month. Here is the receipt."
Resultado esperado: {{"category": "Billing", "priority": "Media", "initial_level": "N1", "triage_justification": "Cobrança duplicada passível de revisão via autoatendimento no painel."}}

Ticket: "O sistema inteiro caiu, ninguém consegue logar."
Resultado esperado: {{"category": "Technical", "priority": "Critica", "initial_level": "N3", "triage_justification": "Indisponibilidade geral afetando múltiplos usuários."}}

Retorne exclusivamente um objeto JSON válido contendo as chaves: "category", "priority", "initial_level" e "triage_justification"."""

    return {
        "system_prompt": CLASSIFIER_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }