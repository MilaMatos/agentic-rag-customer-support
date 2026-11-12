SUMMARIZER_SYSTEM_PROMPT = (
    "Você é responsável por ler respostas dadas aos clientes e resumi-las para que "
    "analistas humanos entendam rapidamente o que foi resolvido ou qual ação o cliente deve tomar."
)


def construir_prompt_resumo(resposta_final_cliente: str) -> dict[str, str]:
    user_prompt = f"""Leia a mensagem final que será enviada ao cliente:

"{resposta_final_cliente}"

Escreva um resumo executivo interno seguindo estritamente este formato (não adicione saudações ou texto extra, apenas as duas linhas abaixo):
- Ação Tomada: [Resumo de 1 frase do que foi informado ou resolvido]
- Próximo Passo do Cliente: [O que o cliente precisa fazer agora, se houver]"""

    return {
        "system_prompt": SUMMARIZER_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
    }