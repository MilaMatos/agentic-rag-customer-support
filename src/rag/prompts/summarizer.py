import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, LLM

load_dotenv()

llm_summarizer = LLM(
    model="openai/nvidia/nemotron-3.5-lightning-30b-a3b",
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
    temperature=0.0,
    timeout=30,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}}
)

summarizer_agent = Agent(
    role='Analista de Handoff e Qualidade',
    goal='Extrair os pontos críticos da resposta gerada para o cliente, criando um resumo objetivo para o histórico interno do ticket.',
    backstory='Você é responsável por ler respostas longas dadas aos clientes e resumi-las para que analistas humanos entendam rapidamente o que foi resolvido ou qual ação o cliente deve tomar.',
    llm=llm_summarizer,
    verbose=False
)

def run_summarization(final_response: str):
    task_description = f"""
    Leia a mensagem final que será enviada ao cliente:
    
    "{final_response}"
    
    Escreva um resumo executivo interno seguindo estritamente este formato (não adicione saudações ou texto extra, apenas as duas linhas abaixo):
    - Ação Tomada: [Resumo de 1 frase do que foi informado ou resolvido]
    - Próximo Passo do Cliente: [O que o cliente precisa fazer agora, se houver]
    """

    summarization_task = Task(
        description=task_description,
        expected_output="Resumo executivo de duas linhas (Ação Tomada e Próximo Passo).",
        agent=summarizer_agent,
        output_file='summarizer_log.txt'
    )

    crew = Crew(
        agents=[summarizer_agent],
        tasks=[summarization_task]
    )

    return crew.kickoff()

if __name__ == "__main__":
    test_response = """
    Olá! Tudo bem?
    
    Lamento muito que isso tenha acontecido. Vi que você foi cobrado duas vezes pelo mesmo mês no valor de R$ 297,00. Isso é chato, mas fique tranquilo(a): esse tipo de situação tem solução e, segundo nossa política, você tem direito a 100% de restituição sem multa ou juros, desde que seja na mesma fatura/ciclo mensal.
    
    No painel da sua conta, por favor, acesse Módulo Faturamento > Histórico de Cobranças. Lá você deverá identificar a entrada duplicada (com a mesma data de vencimento e valor R$ 297,00) e clicar em "Solicitar Revisão". O sistema vai processar a devolução e o crédito costuma cair em até 5 dias úteis.
    
    Caso não encontre o botão ou a opção não apareça, por favor me avise imediatamente, pois precisaremos abrir um chamado para a equipe de Backoffice verificar com mais detalhes.
    
    Fico no aguardo do seu retorno!
    """
    
    print("Iniciando a criação do resumo interno\n")
    result = run_summarization(test_response)
    
    print("\n Resumo gerado")
    print(result.raw)