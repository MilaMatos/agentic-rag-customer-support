import pandas as pd
import json
import os
from crewai import Agent, Task, Crew, Process, LLM

chave_nvidia = os.getenv("OPENAI_API_KEY")

llm_oficial = LLM(
    model="openai/nvidia/nemotron-3.5-lightning-30b-a3b",
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=chave_nvidia,
    temperature=0.1,
    timeout=300,
    max_retries=5,
    extra_body={
        "chat_template_kwargs": {"enable_thinking": True},
        "reasoning_budget": 8192
    }
)

sintetizador = Agent(
    role='Arquiteto de Operações e Documentação da NexusTech Solutions',
    goal='Escrever o Manual Operacional Consolidado de uma categoria de suporte para alimentar o banco vetorial (RAG).',
    backstory='Você é a Fonte Oficial da Verdade. Defina dados concretos de um ERP B2B (menus, SLAs, horários). N1 é estritamente autoatendimento para o cliente final. O N1 nunca acessa logs ou sistemas de backend (isso é papel do N2/N3).',
    verbose=False,
    allow_delegation=False,
    llm=llm_oficial
)

mesclador = Agent(
    role='Editor Chefe de Documentação',
    goal='Consolidar os manuais de subcategorias em um documento final Markdown estruturado.',
    backstory='Você organiza o documento final mantendo exatamente a estrutura exigida sem perder as resoluções concretas geradas pelo Arquiteto.',
    verbose=False,
    allow_delegation=False,
    llm=llm_oficial
)

def gerar_chunks_crewai(input_path: str, output_dir: str):
    print("A carregar os dados limpos")
    df = pd.read_csv(input_path)
    os.makedirs(output_dir, exist_ok=True)
    
    categorias = df['category'].unique()
    
    for categoria in categorias:
        print(f"A processar a categoria: {categoria}")
        df_cat = df[df['category'] == categoria]
        subcategorias = df_cat['subcategory'].unique()
        tarefas_sintese = []
        
        for subcat in subcategorias:
            df_sub = df_cat[df_cat['subcategory'] == subcat]
            pergunta_unica = df_sub['query'].iloc[0]
            
            tarefa = Task(
                description=f'''
                Você é a Fonte da Verdade.
                Categoria: {categoria}
                Subcategoria (Inglês): {subcat}
                
                Problema relatado pelo cliente:
                "{pergunta_unica}"
                
                Gere o manual para esta subcategoria.
                
                OBRIGATÓRIO INICIAR O TEXTO EXATAMENTE COM:
                ### {subcat}
                
                E seguir com os 3 tópicos (máximo de 120 palavras por tópico):
                - **Contexto e Sintomas:**
                - **Resolução N1 (Autoatendimento e Políticas):** Instruções reais de ERP. Sem acesso a logs.
                - **Critério de Escalonamento (N2 / N3):** Quando transferir.
                ''',
                expected_output=f'Diretrizes estruturadas iniciando com ### {subcat}.',
                agent=sintetizador
            )
            tarefas_sintese.append(tarefa)
            
        tarefa_mesclagem = Task(
            description=f'''
            Sua única tarefa é concatenar (juntar) as diretrizes recebidas.
            
            1. Crie o título principal: `# Manual Operacional NexusTech: {categoria}`
            2. Pule uma linha e adicione o título: `### Diretrizes Gerais da Categoria` e escreva um parágrafo resumindo a categoria (máximo 50 palavras).
            3. Abaixo disso, COPIE E COLE exatamente o texto gerado por cada uma das tarefas anteriores. NÃO altere o texto original, não reescreva, não traduza os títulos. Apenas monte o documento final.
            ''',
            expected_output=f'Manual concatenado em Markdown puro.',
            agent=mesclador,
            context=tarefas_sintese
        )
        
        equipe = Crew(
            agents=[sintetizador, mesclador],
            tasks=[*tarefas_sintese, tarefa_mesclagem],
            process=Process.sequential, 
            verbose=False
        )
        
        resultado = equipe.kickoff()
        
        doc_id = f"MAN-{categoria.upper()[:4].replace(' ', '')}-001"
        chunk_estruturado = [{
            "doc_id": doc_id,
            "metadata": {
                "category": categoria,
                "subcategories_included": list(subcategorias),
                "section": "Consolidated Operational Manual",
                "source": "synthetic_knowledge_document"
            },
            "content": resultado.raw
        }]
        
        nome_arquivo = f"base_conhecimento_{categoria.replace(' ', '_').lower()}.json"
        caminho_saida = os.path.join(output_dir, nome_arquivo)
        
        with open(caminho_saida, 'w', encoding='utf-8') as f:
            json.dump(chunk_estruturado, f, ensure_ascii=False, indent=2)
            
        print(f"Documento {nome_arquivo} guardado com sucesso!")

if __name__ == "__main__":
    gerar_chunks_crewai("data/cleaned/tickets.csv", "data/chunks")