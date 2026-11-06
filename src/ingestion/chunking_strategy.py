import json
import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM
from pathlib import Path

load_dotenv()

chave_nvidia = os.getenv("OPENAI_API_KEY") or os.getenv("NVIDIA_API_KEY")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JSON_DIR = PROJECT_ROOT / "data" / "knowledge_base" / "json"

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

CATALOGO_CANONICO = {
    "Account": [
        ("Falha no 2FA", "2FA is not working, I don't get the code."),
        ("Perda de Dispositivo 2FA", "I need to change my email address, but the 2FA is linked to my old phone."),
        ("Redefinicao de Senha", "I forgot my password and the reset link is expired."),
        ("Upgrade Enterprise", "How can I upgrade my subscription to the Enterprise plan?"),
        ("Foto de Perfil", "How do I update my profile picture?"),
        ("Exclusao de Conta", "Please delete my account and all associated data immediately."),
    ],
    "Billing": [
        ("Status de Reembolso", "I requested a refund 5 days ago, where is it?"),
        ("Atualizacao de Pagamento", "Payment method update failed. I cannot add my new Visa card."),
        ("Divergencia na Fatura", "The invoice amount is higher than the agreed contract."),
        ("Segunda Via de Fatura", "Can you send me the invoice for transaction #99283?"),
        ("Cancelamento e Renovacao", "My subscription renewed automatically, but I wanted to cancel."),
        ("Cobranca Duplicada", "I was charged twice for the same month. Here is the receipt."),
    ],
    "Technical": [
        ("Falha de Sincronizacao", "Syncing data between mobile and desktop is failing."),
        ("Erro 500 no Login", "I am getting Error 500 when trying to log in, even after resetting my password."),
        ("Travamento do Dashboard", "The dashboard is not loading any data, just a spinning wheel."),
        ("Integracao de API", "API returns 500 Internal Server Error when fetching user list."),
        ("Instalacao de Patch", "I cannot install the latest patch on Windows 11."),
        ("Fechamento nas Configuracoes", "The app crashes every time I open the settings tab."),
    ],
    "Fraud": [
        ("Tentativa de Phishing", "I received a phishing email pretending to be your support team."),
        ("Cartao Roubado", "My credit card was used on your site without my permission, it was stolen."),
        ("Conta Invadida", "My account was hacked! Someone made transactions I didn't authorize. Block it now!"),
        ("Dispositivo Desconhecido", "There is an unrecognized device logged into my account."),
        ("Alerta de Seguranca", "I got a security alert notification about a login from Russia, it wasn't me."),
        ("Transacao Suspeita", "Suspicious activity detected on my billing history."),
    ],
    "General Inquiry": [
        ("Horario de Atendimento", "What are your hours of operation for phone support?"),
        ("Endereco da Sede", "Where is your main office located?"),
        ("Desconto para ONGs", "Do you offer discounts for non-profit organizations?"),
        ("Roadmap de Produto", "Is there a roadmap for new features coming this year?"),
        ("Solicitacao de Demo", "I would like to request a live demo for my team."),
        ("Planos e Precos", "How do the pricing tiers work for teams?"),
    ]
}

sintetizador = Agent(
    role='Arquiteto de Operações e Documentação da NexusTech Solutions',
    goal='Escrever o Manual Operacional Consolidado de uma categoria de suporte para alimentar o banco vetorial (RAG).',
    backstory=(
        'Você é a Fonte Oficial da Verdade. Defina dados concretos de um ERP B2B (menus, SLAs, horários). '
        'N1 é estritamente autoatendimento para o cliente final. '
        'O N1 nunca acessa logs ou sistemas de backend (isso é papel do N2/N3). '
        'Você é brasileiro e escreve toda a documentação exclusivamente em Português.'
    ),
    verbose=False,
    allow_delegation=False,
    llm=llm_oficial
)

def gerar_manuais(output_dir: str = None):
    if output_dir is None:
        output_dir = str(JSON_DIR)
    os.makedirs(output_dir, exist_ok=True)

    for categoria, itens in CATALOGO_CANONICO.items():
        print(f"A processar a categoria: {categoria}")
        subcategorias_nomes = [sub for sub, _ in itens]

        manual_completo = f"# Manual Operacional NexusTech: {categoria}\n\n"
        manual_completo += "### Diretrizes Gerais da Categoria\n"
        manual_completo += (
            f"Este documento consolida os procedimentos operacionais, SLAs e políticas "
            f"de suporte de autoatendimento (N1) e escalonamento (N2/N3) para a categoria {categoria}.\n\n"
        )

        for subcat, pergunta_unica in itens:
            print(f"   -> Gerando subcategoria: {subcat}...")
            tarefa = Task(
                description=f'''
                Categoria: {categoria}
                Subcategoria oficial: {subcat}
                Problema relatado pelo cliente: "{pergunta_unica}"

                Sua Tarefa:
                1. Inicie o texto EXATAMENTE com o cabeçalho: `### {subcat}`
                2. Escreva os 3 tópicos abaixo (máximo de 120 palavras por tópico) 100% EM PORTUGUÊS DO BRASIL:

                - **Contexto e Sintomas:** Explique o problema exato enfrentado pelo cliente com base na pergunta relatada.
                - **Resolução N1 (Autoatendimento e Políticas):** Dê instruções concretas de onde o cliente deve clicar no painel do ERP NexusTech e informe políticas/SLAs/valores concretos. ATENÇÃO: N1 nunca lê logs nem acessa banco de dados.
                - **Critério de Escalonamento (N2 / N3):** Regra exata de quando transferir o caso para o Backoffice (N2) ou Engenharia/Segurança (N3).

                NÃO escreva parágrafos em inglês. Aborde exclusivamente o assunto "{subcat}".
                ''',
                expected_output=f'Diretrizes em português iniciando exatamente com ### {subcat}.',
                agent=sintetizador
            )

            equipe = Crew(
                agents=[sintetizador],
                tasks=[tarefa],
                process=Process.sequential,
                verbose=False
            )
            resultado_subcat = equipe.kickoff()
            manual_completo += resultado_subcat.raw.strip() + "\n\n"

        doc_id = f"MAN-{categoria.upper()[:4].replace(' ', '')}-001"
        chunk_estruturado = [{
            "doc_id": doc_id,
            "metadata": {
                "category": categoria,
                "subcategories_included": subcategorias_nomes,
                "section": "Consolidated Operational Manual",
                "source": "synthetic_knowledge_document"
            },
            "content": manual_completo.strip()
        }]

        nome_arquivo = f"base_conhecimento_{categoria.replace(' ', '_').lower()}.json"
        caminho_saida = os.path.join(output_dir, nome_arquivo)

        with open(caminho_saida, 'w', encoding='utf-8') as f:
            json.dump(chunk_estruturado, f, ensure_ascii=False, indent=2)

        print(f"Documento {nome_arquivo} guardado com sucesso!\n")

if __name__ == "__main__":
    gerar_manuais()