import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, LLM
from src.rag.prompts.classification_schema import TicketClassification

load_dotenv()

llm_classifier = LLM(
    model="openai/nvidia/nemotron-3.5-lightning-30b-a3b",
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
    temperature=0.0,
    timeout=30,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}}
)

triage_agent = Agent(
    role='Especialista em Triagem de Suporte B2B',
    goal='Analisar o ticket do cliente e classificá-lo perfeitamente na taxonomia da empresa, retornando apenas os dados estruturados.',
    backstory='Você é a primeira linha do suporte NexusTech. Sua missão é ler o problema do cliente e definir a categoria, prioridade e nível de atendimento inicial. Você é analítico, direto e nunca inventa informações.',
    llm=llm_classifier,
    verbose=False
)

def run_classification(customer_query: str):
    task_description = f"""
    Classifique o seguinte ticket do cliente: '{customer_query}'

    Regras de Negócio da NexusTech (Siga estritamente):
    - Todo problema de cobrança (duplicada, fatura errada) deve ser classificado inicialmente como N1, pois o cliente tem acesso ao autoatendimento no painel.
    - Problemas técnicos que afetam todos os usuários devem ser N3.
    - Dúvidas gerais sobre a plataforma devem ser N1.

    Exemplos de Classificação:
    Ticket: "I was charged twice for the same month. Here is the receipt."
    Resultado esperado: category="Billing", priority="Media", initial_level="N1"

    Ticket: "O sistema inteiro caiu, ninguém consegue logar."
    Resultado esperado: category="Technical", priority="Critica", initial_level="N3"

    Agora, gere o JSON para o ticket solicitado.
    """

    classification_task = Task(
        description=task_description,
        expected_output="Um JSON estruturado com os dados da triagem.",
        agent=triage_agent,
        output_json=TicketClassification,
        output_file='classifier_log.json'
    )

    crew = Crew(
        agents=[triage_agent],
        tasks=[classification_task]
    )

    return crew.kickoff()

if __name__ == "__main__":
    test_queries = [
        "I was charged twice for the same month. Here is the receipt.", # 1. Billing (N1)
        "A API de produção está retornando Erro 500 para todos os nossos utilizadores desde as 8h da manhã.", # 2. Technical (N3 - Crítico)
        "Como faço para convidar um novo membro da minha equipa para o painel?", # 3. General Inquiry (N1 - Baixa)
        "URGENT: there are unknown transactions on my account, I think I was hacked!", # 4. Fraud (N2/N3 - Alta/Crítica)
        "Preciso de atualizar o CNPJ da minha empresa no vosso registo." # 5. Account (N1/N2 - Média)
    ]
    
    print("Iniciando testes do Classificador\n")
    
    for i, query in enumerate(test_queries, 1):
        print(f"[{i}/5] Analisando: '{query}'")
        result = run_classification(query)
        print(f"-> {result.raw}\n")
        
    print("Testes concluídos.")