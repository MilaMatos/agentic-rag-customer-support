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
venv/bin/python -m src.ingestion.vector_pipeline
```

### 5. Executar a Bateria de Testes do RAG Multi-Agente
Execute o orquestrador CrewAI para processar o dataset de avaliação (`testes_e3.json`). O script fará a busca vetorial, executará o Agente Redator e acionará o Agente Auditor:
```bash
venv/bin/python -m src.pipeline_agents
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
│   ├── E2/                               # Entrega 2: Dados e Ingestão
│   └── E3/                               # Entrega 3: Motor RAG e Agentes
├── logs/                                 # Logs e rastreabilidade da Caixa de Estado
├── sandbox/                              # Simulador de terminal e testes interativos
├── src/
│   ├── agents/                           # Orquestração Multi-Agente (CrewAI)
│   │   ├── prompts/                      # Templates de sistema e guardrails
│   │   ├── agent_auditor.py              # Classe do Agente Auditor de Qualidade
│   │   ├── agent_classifier.py           # Classe do Agente Classificador (Triagem)
│   │   ├── agent_redactor.py             # Classe do Agente Redator N1
│   │   ├── agent_summarizer.py           # Classe do Agente de Resumo Interno
│   │   ├── parsers.py                    # Output parsers (Regex, JSON, Limpeza)
│   │   └── schemas.py                    # Contratos de dados e Caixa de Rastreabilidade
│   ├── ingestion/                        # Scripts de processamento e ingestão offline
│   ├── rag/                              # Módulo de Recuperação Vetorial (Runtime)
│   │   └── retriever.py                  # Busca semântica e Context Slicing no PGVector
│   └── pipeline_agents.py                # Orquestrador central de fluxo dos agentes
├── tests/                                # Suíte de testes automatizados (Pytest)
│   ├── test_agents.py                    # Testes de integração e casos de borda
│   ├── test_retriever_rag.py             # Testes de precisão vetorial (Top-K)
│   └── test_unit_modulos.py              # Testes unitários (Parsers e Regex)
├── .env                                  # Variáveis de ambiente (ignorado no git)
├── .gitignore
├── docker-compose.yml                    # Setup de infra (PostgreSQL + pgvector)
├── pytest.ini                            # Configurações do ambiente de testes
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
- [x] **Entrega 3 (07/11) — Pipeline RAG Funcional**
  - [x] Módulo de recuperação vetorial (Retriever) otimizado
  - [x] Estratégia de particionamento (Context Slicing)
- [x] **Entrega 4 e 5 (14/11 e 21/11) — Sistema Multi-Agente Orquestrado (Adiantado)**
  - [x] Construção isolada dos 4 agentes (Classificador, Redator, Auditor e Resumo)
  - [x] Contratos via Pydantic (Caixa de Rastreabilidade) e Orquestração
  - [x] Suíte de validação e casos de borda com Pytest
- [ ] **Entrega 6 (28/11) — API, Memória e Interface do Usuário**
  - [ ] Implementação do histórico deslizante multi-turno no pipeline
  - [ ] Exposição de rotas FastAPI e integração com Frontend
- [ ] **Entrega 7 (05/12) — Testes em Larga Escala e Documentação**
  - [ ] Aferição de métricas e testes end-to-end simulando produção
- [ ] **Apresentação Final (12/12) — Showcase**
