# 🚀 NexusTech Support Copilot — Sistema Multi-Agente com RAG

Repositório oficial do projeto desenvolvido durante o **Programa de Capacitação em Sistemas Multi-Agentes com RAG**.  
Este projeto resolve o **Problema 1 (Copilot de Atendimento ao Cliente)** para a empresa fictícia **NexusTech Solutions** (SaaS B2B de ERP em nuvem).

---

## 🎯 Visão Geral do Projeto

O **NexusTech Support Copilot** é um sistema multi-agente orquestrado que auxilia atendentes de suporte N1 (e clientes via chat) na resolução rápida e padronizada de chamados. 

O sistema, desenhado para operar no padrão de chat contínuo com limite de tentativas (Bounded Multi-Turn), classifica automaticamente a intenção do usuário, realiza buscas semânticas em bases de conhecimento, redige respostas fundamentadas com citação de fontes, audita a qualidade da resposta (prevenindo alucinações) e elabora resumos executivos quando o chamado precisa ser escalado para especialistas técnicos.

---

## 🏗️ Stack Tecnológico Definido

| Camada | Tecnologia |
| :--- | :--- |
| **Orquestração Multi-Agente** | CrewAI |
| **Banco Vetorial & Relacional** | PostgreSQL + extensão `pgvector` |
| **Infraestrutura e Dados** | Docker, Python |

---

## 🚀 Como Executar o Projeto

Para testar o pipeline RAG Multi-Agente localmente, siga os passos abaixo. Certifique-se de ter o **Docker** (para o banco vetorial) e o **Python 3.10+** instalados na sua máquina.

### 1. Configuração do Ambiente
Clone o repositório e crie um ambiente virtual para isolar as dependências:
```bash
# Crie o ambiente virtual
python -m venv venv

# Ative o ambiente (Linux/Mac)
source venv/bin/activate
# ou no Windows: venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt
```

### 2. Variáveis de Ambiente
Crie um arquivo `.env` na raiz do projeto contendo suas chaves de API e a string de conexão do banco de dados:
```env
NVIDIA_API_KEY="sua_chave_aqui"
NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"
DATABASE_URL="postgresql+psycopg://admin:adminpassword@localhost:5432/nexus_knowledge"
```

### 3. Subir o Banco de Dados (PGVector)
Inicie o container do PostgreSQL com a extensão vetorial em segundo plano:
```bash
docker-compose up -d
```

### 4. Ingestão de Dados (Knowledge Base)
Antes de rodar os agentes, popule o banco de dados vetorial com os manuais operacionais da NexusTech:
```bash
python -m src.ingestion.vector_pipeline
```

### 5. Executar a Bateria de Testes do RAG Multi-Agente
Execute o orquestrador CrewAI para processar o dataset de avaliação (`testes_e3.json`). O script fará a busca vetorial, executará o Agente Redator e acionará o Agente Auditor:
```bash
python -m src.pipeline_agents
```
*(Os resultados da execução, contendo as métricas de acerto e o JSON de rastreabilidade, serão salvos automaticamente na pasta `logs/`).*

---

## 📂 Estrutura Atual do Repositório

```text
nexustech-support-copilot/
├── data/                                 # Datasets e Base de Conhecimento
│   ├── cleaned/                          # Dados tabulares processados (ex: tickets.csv)
│   ├── evaluation/                       # Datasets de teste e avaliação (Gabaritos)
│   │   └── testes_e3.json                # Bateria de perguntas E3
│   └── knowledge_base/                   # Chunks (json) e Manuais sintéticos (manuals)
├── docs/                                 # Documentação do projeto por entrega
│   ├── E1/                               # Entrega 1: Planejamento
│   │   ├── apresentacao_E1.html
│   │   ├── arquitetura_stack.md
│   │   ├── diagrama.jpeg
│   │   └── entendimento_do_problema.md
│   └── E2/                               # Entrega 2: Dados e Ingestão
│       ├── apresentacao_E2.html
│       ├── estrategia_chunking.md
│       └── pesquisa_dados_kb.md
├── logs/                                 # Logs de execução e rastreabilidade (Gerados automaticamente)
├── sandbox/                              # Scripts de rascunho e testes isolados (Ignorado no git)
├── src/
│   ├── ingestion/                        # Scripts de processamento e ingestão
│   │   ├── chunking_strategy.py          # Lógica de particionamento (Chunking)
│   │   ├── export_manuals.py             # Geração de manuais
│   │   ├── ingestion_pipeline.py         # Pipeline de preparação dos dados
│   │   └── vector_pipeline.py            # Ingestão vetorial no PostgreSQL/pgvector
│   ├── rag/                              # Pipeline RAG Multi-Agente
│   │   ├── prompts/                      # Templates de sistema e guardrails
│   │   │   ├── auditor.py
│   │   │   └── redactor.py
│   │   └── retriever.py                  # Busca semântica e fatiamento no PGVector
│   └── pipeline_agents.py                # Orquestrador CrewAI (Redator + Auditor)
├── .env                                  # Variáveis de ambiente (ignorado no git)
├── .gitignore
├── docker-compose.yml                    # Setup de infra (PostgreSQL + pgvector)
├── requirements.txt                      # Dependências Python
└── README.md                             # Documentação principal e roadmap
```
---

## 📅 Cronograma e Status das Entregas (Backlog)

- [x] **Entrega 1 (24/10) — Planejamento e Design do Sistema**
  - [x] 1.1 Documento de entendimento do problema
  - [x] 1.2 Proposta de arquitetura e fluxo de orquestração
  - [x] 1.3 Mapeamento e avaliação dos datasets
  - [x] 1.4 Definição do stack técnico
  - [x] 1.5 Inicialização e estruturação do repositório GitHub
- [x] **Entrega 2 (31/10) — Infraestrutura e Ingestão de Dados**
  - [x] Setup do ambiente e banco PostgreSQL + `pgvector` via Docker
  - [x] Pipeline de pesquisa, limpeza, chunking semântico e geração de embeddings
- [ ] **Entrega 3 (07/11) — Pipeline RAG Funcional**
  - [ ] Módulo de retrieval e conexão com a LLM
- [ ] **Entrega 4 (14/11) — Primeiro Agente Funcional**
  - [ ] Implementação isolada e testes com *tools*
- [ ] **Entrega 5 (21/11) — Sistema Multi-Agente Orquestrado**
  - [ ] Integração dos agentes e configuração de estado/loops no LangGraph
- [ ] **Entrega 6 (28/11) — API e Interface do Usuário**
  - [ ] Exposição de rotas FastAPI e integração com Frontend
- [ ] **Entrega 7 (05/12) — Testes, Avaliação e Documentação**
  - [ ] Aferição de métricas e testes end-to-end
- [ ] **Apresentação Final (12/12) — Showcase**
