# 🚀 NexusTech Support Copilot — Sistema Multi-Agente com RAG

Repositório oficial do projeto desenvolvido durante o **Programa de Capacitação em Sistemas Multi-Agentes com RAG**.  
Este projeto resolve o **Problema 1 (Copilot de Atendimento ao Cliente)** para a empresa fictícia **NexusTech Solutions** (SaaS B2B de ERP em nuvem).

---

## 🎯 Visão Geral do Projeto

O **NexusTech Support Copilot** é um sistema multi-agente orquestrado que atua como **Copiloto para atendentes humanos de suporte N1** no modelo *Human-in-the-Loop* (HITL).

Em vez de responder ou transferir clientes de forma autônoma, a arquitetura opera em **duas fases** dentro de conversas multi-turno com memória de sessão e cache inteligente de RAG:

1. **Fase 1 — Geração de Sugestão (`gerar_sugestao_turno`):**
   - **Agente Classificador:** Analisa a mensagem atual junto ao histórico recente, classifica categoria/prioridade, detecta continuidade de tópico (`is_followup`) e otimiza a consulta vetorial (`search_query`).
   - **Motor RAG + Cache de Sessão:** Reutiliza o manual em cache para perguntas de acompanhamento no mesmo assunto (reduzindo latência) ou consulta o `PGVector` com *Context Slicing* e corte de similaridade mínima de `0.30`.
   - **Agente Redator N1:** Redige uma proposta de resposta humanizada e fundamentada no manual oficial com citação obrigatória de fonte (`[[FONTE: Chunk_ID]]`), operando tanto com chunks pré-carregados quanto via `@tool("buscar_manual_rag_tool")` com isolamento concorrente (`ContextVar`).
   - **Agente Auditor de Qualidade:** Valida fidelidade ao manual (com loop de autocorreção contra alucinações) e atua como emissor exclusivo do alerta de escalonamento (`requer_escalonamento`).
2. **Fase 2 — Confirmação Humana e Handoff (`confirmar_envio_turno`):**
   - O atendente humano N1 decide se envia, edita ou escala o atendimento.
   - O sistema calcula automaticamente métricas de edição (`was_edited` e `edit_ratio`) e grava na memória da sessão **apenas o texto efetivamente enviado ao cliente**.
   - **Agente Resumo (Sob Demanda):** Acionado somente quando o atendente confirma o escalonamento (`ESCALADA_N2`), consolidando o histórico completo da conversa em um dossiê executivo para o especialista N2/N3.

---

## 🏗️ Stack Tecnológico

| Camada | Tecnologia |
| :--- | :--- |
| **Orquestração Multi-Agente** | CrewAI (`1.15.35`), Pydantic (`2.12.5`) |
| **Modelos (LLM & Embeddings)** | NVIDIA NIM (`nemotron-3.5-lightning-30b-a3b` e `nemotron-3.5-embed-1b`) |
| **Motor RAG & Banco Vetorial** | PostgreSQL 16 + `pgvector`, `langchain-postgres` |
| **Infraestrutura & Testes** | Docker, Python 3.11+, Pytest (`9.2.0`) |

---

## 🚀 Como Executar o Projeto

Certifique-se de ter **Docker** e **Python 3.10+** instalados na máquina.

### 1. Configuração do Ambiente Virtual
Clone o repositório, crie o ambiente virtual e instale as dependências travadas:

```bash
# Crie o ambiente virtual
python -m venv venv

# Ative o ambiente (Linux/Mac)
source venv/bin/activate
# ou no Windows: venv\Scripts\activate

# Instale as dependências do projeto
pip install -r requirements.txt
```

### 2. Variáveis de Ambiente
Crie um arquivo `.env` na raiz do projeto com as credenciais da API e do banco de dados:

```env
NVIDIA_API_KEY="sua_chave_aqui"
NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"
DATABASE_URL="postgresql+psycopg://admin:adminpassword@localhost:5432/nexus_knowledge"

# Opcional (sobrescreve os padrões do docker-compose.yml)
POSTGRES_USER="admin"
POSTGRES_PASSWORD="adminpassword"
POSTGRES_DB="nexus_knowledge"
POSTGRES_PORT="5432"
```

### 3. Subir o Banco de Dados (PostgreSQL + PGVector)
Inicie o container em segundo plano (com `healthcheck` configurado via `pg_isready`):

```bash
docker-compose up -d
```

Para confirmar que o banco está saudável (`healthy`):

```bash
docker ps
```

### 4. Ingestão da Base de Conhecimento
Popule o banco vetorial com os manuais operacionais da NexusTech (necessário na primeira execução ou ao recriar o volume do banco):

```bash
venv/bin/python -m src.ingestion.vector_pipeline
```

### 5. Executar a Pipeline

#### A) Avaliação em Lote (*Single-Turn* — Dataset `testes_e3.json`)
Processa todos os casos de avaliação de ponta a ponta e salva a Caixa de Rastreabilidade em `logs/rastreabilidade/`:

```bash
venv/bin/python -m src.pipeline_agents
```

#### B) Simulador Interativo Multi-Turno (Terminal)
Permite conversar em múltiplos turnos pelo terminal acompanhando categoria, detecção de *follow-up*, uso de cache RAG, veredito do Auditor e salvamento automático da sessão em `logs/sessoes_chat/`:

```bash
venv/bin/python -m sandbox.chat_terminal
```

---

## 🧪 Como Rodar os Testes Automatizados

Utilizamos `pytest` para validar parsers, busca vetorial, comportamento isolado dos agentes (parametrizado), memória multi-turno, isolamento de concorrência (`ContextVar`) e ciclo HITL.

> **Nota sobre warnings:** A flag `-p no:warnings` oculta os `DeprecationWarning` internos emitidos pela própria biblioteca do CrewAI, mantendo a saída do terminal limpa.

### Rodar toda a suíte de testes
```bash
venv/bin/python -m pytest tests/ -v -p no:warnings
```

### Rodar apenas testes unitários rápidos
Valida parsers, regex, máquina de estado `SessionMemory`, isolamento `ContextVar`, cálculo de *diff* de edição humana e resumo sob demanda em menos de 1 segundo:
```bash
venv/bin/python -m pytest tests/test_unit_modulos.py tests/test_multiturn.py -k "TestSessionMemoryEConcorrencia or TestCicloHITLUnitario" -v -p no:warnings
```

### Rodar a suíte completa de Multi-Turno & HITL
```bash
venv/bin/python -m pytest tests/test_multiturn.py -v -p no:warnings
```

### Rodar os testes parametrizados dos agentes isolados (incluindo Tool RAG e Prompt Injection)
```bash
venv/bin/python -m pytest tests/test_agents.py -v -p no:warnings
```

### Rodar os testes de precisão vetorial do Retriever (PGVector)
```bash
venv/bin/python -m pytest tests/test_retriever_rag.py -v -p no:warnings
```

---

## 📂 Estrutura Atual do Repositório

```text
nexustech-support-copilot/
├── data/                                 # Datasets e Base de Conhecimento
│   ├── cleaned/                          # Dados tabulares processados
│   ├── evaluation/                       # Datasets de avaliação e gabaritos
│   │   └── testes_e3.json                # Bateria de avaliação single-turn
│   └── knowledge_base/                   # Chunks (JSON) e Manuais operacionais
├── docs/                                 # Documentação técnica e apresentações por entrega
│   ├── E1/                               # Entrega 1: Planejamento e Arquitetura
│   ├── E2/                               # Entrega 2: Dados e Ingestão Vetorial
│   ├── E3/                               # Entrega 3: Motor RAG e Apresentação
│   ├── E4/                               # Entrega 4: Agentes, Tools e Testes
│   │   └── documentacao_agentes.md       # Documentação técnica dos 4 agentes
│   └── E5/                               # Entrega 5: Contrato Full-Stack e Produção
│       └── contrato_integracao_hitl.md   # Especificação formal HITL (API, SQL e AWS)
├── logs/                                 # Rastreabilidade e logs de sessões locais
├── sandbox/                              # Simuladores interativos de terminal
│   └── chat_terminal.py                  # Chat multi-turno com SessionMemory
├── src/
│   ├── agents/                           # Camada Multi-Agente (CrewAI)
│   │   ├── prompts/                      # Prompts de sistema, guardrails e multi-turno
│   │   ├── __init__.py                   # Configuração de telemetria e logging
│   │   ├── agent_auditor.py              # Agente Auditor de Qualidade e Escalonamento
│   │   ├── agent_classifier.py           # Agente Classificador Contextual (Follow-up)
│   │   ├── agent_redactor.py             # Agente Redator N1 (Modo Híbrido + Tool RAG)
│   │   ├── agent_summarizer.py           # Agente Resumo Executivo (Sob Demanda)
│   │   ├── memory.py                     # SessionMemory (Histórico, Cache RAG e HITL)
│   │   ├── parsers.py                    # Output parsers (Regex, JSON, Limpeza)
│   │   ├── schemas.py                    # Contratos Pydantic (Rastreabilidade e HITL)
│   │   └── tools.py                      # @tool RAG isolada por requisição (ContextVar)
│   ├── ingestion/                        # Pipeline offline de limpeza e embeddings
│   ├── rag/                              # Recuperação Vetorial em Runtime
│   │   └── retriever.py                  # Busca PGVector, Context Slicing e Retries
│   └── pipeline_agents.py                # Orquestrador (Single-Turn e Ciclo HITL 2 Fases)
├── tests/                                # Suíte de testes automatizados (Pytest)
│   ├── test_agents.py                    # Testes parametrizados dos agentes e Tool RAG
│   ├── test_multiturn.py                 # Testes de memória, ContextVar, HITL e E2E
│   ├── test_retriever_rag.py             # Testes de precisão vetorial (Top-K)
│   └── test_unit_modulos.py              # Testes unitários de parsers e utilitários
├── .env                                  # Variáveis de ambiente (ignorado no git)
├── .gitignore
├── docker-compose.yml                    # PostgreSQL 16 + pgvector com healthcheck
├── requirements.txt                      # Dependências Python com versões travadas
└── README.md                             # Documentação principal
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
