# NexusTech Support Copilot — Documentação de API & Front-end

Este documento detalha a arquitetura, os contratos REST/WebSocket, as regras de negócio de posse entre níveis de atendimento (N1 → N2/N3) e a interface multi-visão construída para o **NexusTech Support Copilot**.

---

## 1. Visão Geral da Arquitetura

A aplicação segue um design desacoplado em três camadas principais:

1. **Orquestração de IA (`src/pipeline_agents.py` & `src/agents/`):** encapsula a `NexusSupportPipeline` (Classificador, RAG `pgvector`, Redator N1, Auditor QA e Resumidor). As rotas HTTP não invocam agentes diretamente — a pipeline é injetada via `Depends(get_pipeline)`.
2. **Camada de API & Tempo Real (`src/api/`):** servidor **FastAPI** responsável por rotas REST multi-tenant, execução assíncrona em background, governança de posse de sessão, sanitização de privacidade e 3 canais **WebSocket** isolados.
3. **Interface Multi-Visão (`frontend-app/`):** aplicação **React + Vite + Tailwind CSS** baseada no Design System prototipado no **Google Stitch**, conectada simultaneamente à API REST e aos WebSockets para os perfis **Cliente**, **Atendente N1** e **Especialista N2/N3**.

---

## 2. Back-end: API FastAPI, WebSockets & Persistência

### 2.1 Estrutura de Arquivos
* `src/api/main.py`: inicialização da aplicação FastAPI, configuração de CORS e registro das rotas.
* `src/api/dependencies.py`: injeção de dependências (`get_pipeline`, `get_session_repo`, `get_tenant_id`).
* `src/api/routes.py`: endpoints REST, handlers WebSocket e orquestração em background.
* `src/api/schemas.py`: contratos Pydantic de entrada e saída da API.
* `src/api/ws_manager.py`: gerenciamento de conexões WebSocket segmentadas por `tenant_id` e perfil (`client`, `agent`, `specialist`).
* `src/db/models.py` & `src/db/session_repo.py`: modelos SQLAlchemy e operações transacionais no PostgreSQL.

### 2.2 Princípios de Design da API
* **Isolamento Multi-Tenant:** todas as requisições de negócio utilizam o header `X-Tenant-ID` (padrão `default`), garantindo segregação de sessões, filas, mensagens e eventos WebSocket.
* **Execução Não-Bloqueante (`202 Accepted`):** o envio de mensagens do cliente no fluxo N1 responde `202 Accepted` imediatamente e agenda o processamento da IA em `BackgroundTasks`. Chamadas síncronas da pipeline e do SQLAlchemy são executadas via `asyncio.to_thread(...)` para não bloquear o *event loop* do FastAPI.
* **Privacidade por Design (`view=client`):** a visão do cliente e o canal `/ws/client/{session_id}` filtram rigorosamente dados internos — o cliente nunca recebe sugestões pendentes da IA (`pending_suggestion`), chunks recuperados do manual ou `handoff_summary`.

---

### 2.3 Endpoints REST

| Método | Endpoint | Responsabilidade | Regras & Retornos Principais |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Verificação de disponibilidade da API | `200 OK` |
| `GET` | `/ready` | Verificação de prontidão (banco e pipeline) | `200 OK` / `503` |
| `POST` | `/api/v1/sessions` | Cria ou recupera uma sessão de atendimento | Gera `customer_external_id` sequencial por tenant (`cli-001`, `cli-002`...) |
| `GET` | `/api/v1/sessions` | Lista sessões do tenant (fila do N1) | Suporta filtro por status |
| `GET` | `/api/v1/sessions/{session_id}/messages` | Retorna detalhe da sessão e histórico de mensagens | Aceita `view=client \| agent \| specialist`. Sanitiza dados internos em `view=client` |
| `POST` | `/api/v1/sessions/{session_id}/messages` | Envia mensagem do cliente | Retorna `409` se `ENCERRADA`. Se `ESCALADA_N2`, grava direto sem acionar Copiloto N1; caso contrário, retorna `202 Accepted` e dispara pipeline em background |
| `POST` | `/api/v1/sessions/{session_id}/suggestions/{suggestion_id}/confirm` | Confirmação HITL do N1 (`ACEITA_SEM_EDICAO`, `EDITADA`, `ESCALADA_N2`) | Efetiva turno no banco e gera `handoff_summary` sob demanda se escalar. Retorna `403 Forbidden` se já estiver em `ESCALADA_N2` |
| `POST` | `/api/v1/sessions/{session_id}/close` | Encerramento da sessão pelo N1 | Retorna `403 Forbidden` se a sessão estiver sob posse do N2 (`ESCALADA_N2`). Dispara `session.closed` via WS |
| `POST` | `/api/v1/sessions/{session_id}/client-close` | Encerramento da sessão pelo próprio Cliente | Encerra a sessão, limpa estado quente e notifica todos os canais via `session.closed` |
| `GET` | `/api/v1/specialist/sessions` | Lista fila de sessões escaladas (`ESCALADA_N2`) | Ordenada por `escalated_at` |
| `POST` | `/api/v1/specialist/sessions/{session_id}/messages` | Envia mensagem direta do Especialista N2/N3 para o cliente | Grava via `registrar_mensagem_direta` (`sender_role="SPECIALIST_N2"`) e notifica cliente e agentes via WS |
| `POST` | `/api/v1/specialist/sessions/{session_id}/resolve` | Encerra/resolve chamado escalado pelo Especialista N2/N3 | Muda status para `ENCERRADA`, limpa estado quente e dispara `session.closed` |

---

### 2.4 Canais e Eventos WebSocket

Os três canais são isolados por `tenant_id` (e por `session_id` no caso do cliente):

* **`/ws/client/{session_id}`:** recebe respostas confirmadas do N1, respostas diretas do N2, aviso de transferência, digitação (`agent.typing`, `specialist.typing`) e `session.closed`. Envia eventos `typing`.
* **`/ws/agent`:** recebe atualizações de fila, novas mensagens do cliente (`client.message_received`), ciclo do Copiloto (`copilot.processing`, `copilot.suggestion_ready`, `copilot.error`), `client.typing`, `session.escalated` e `session.closed`. Envia eventos `typing`.
* **`/ws/specialist`:** recebe novas sessões escaladas (`session.escalated`), mensagens diretas do cliente em sessões escaladas (`client.message_received`), respostas (`specialist.message_sent`), `client.typing` e `session.closed`. Envia eventos `typing`.

---

### 2.5 Regras de Posse N1 → N2/N3 e Persistência

1. **Fluxo Normal (Posse N1):**
   * Mensagem do cliente dispara `pipeline.gerar_sugestao_db` em background.
   * A sugestão fica salva em `chat_sessions.pending_suggestion` e a rastreabilidade em `copilot_traceability`.
   * Apenas após confirmação humana em `/confirm` (`confirmar_turno`), as mensagens (`CLIENT` e `HUMAN_N1`) entram no histórico oficial `chat_messages`.
2. **Escalonamento (Transferência de Posse para N2/N3):**
   * Ao confirmar com `human_action = "ESCALADA_N2"`, o Resumidor gera o `handoff_summary` sob demanda e o status muda para `ESCALADA_N2`.
   * **Bloqueio do N1:** rotas `/confirm` e `/close` passam a retornar `403 Forbidden` para evitar conflito de atendimento.
   * **Atendimento Direto N2:** novas mensagens do cliente desviam do Copiloto N1 e são gravadas diretamente em `chat_messages` via `SessionRepository.registrar_mensagem_direta(...)`.
   * **Dossiê do Especialista:** `obter_detalhe_sessao` consulta `copilot_traceability` para preencher `auditor_escalation_reason`, com fallback para a última análise registrada em caso de escalada manual pelo N1.
3. **Encerramento (`ENCERRADA`):**
   * Pode ser acionado pelo N1 (enquanto não escalada), pelo Especialista N2 (`/resolve`) ou pelo Cliente (`/client-close`).
   * Limpa o estado temporário/quente em `chat_sessions` (`chunks_em_cache`, `topic_contexts`, `pending_suggestion`), preserva o histórico oficial e bloqueia novas mensagens com `409 Conflict`.

---

## 3. Front-end: React, Vite & Tailwind (Google Stitch)

### 3.1 Stack e Estrutura (`frontend-app/`)
* **Tecnologias:** React 18+, Vite, Tailwind CSS e Material Symbols Outlined.
* **Design System:** tokens de cores, tipografia e layout de 3 colunas exportados do **Google Stitch** e configurados em `tailwind.config.js` e `src/index.css`.
* **Arquivos principais:**
  * `src/App.jsx`: barra superior de navegação e roteamento por query string (`?role=client`, `?role=agent`, `?role=specialist`).
  * `src/services/api.js`: cliente HTTP centralizado (`X-Tenant-ID`), construtores de URLs WebSocket e utilitários de formatação.
  * `src/components/ClientView.jsx`: interface do Cliente.
  * `src/components/AgentView.jsx`: workspace de 3 colunas do Atendente N1.
  * `src/components/SpecialistView.jsx`: fila, chat direto e dossiê do Especialista N2/N3.

### 3.2 Funcionalidades por Perfil

* **Visão Cliente (`?role=client`):**
  * Abertura de atendimento solicitando apenas o nome do cliente.
  * Exibição de badges de status em tempo real (*Em Atendimento*, *Com Especialista N2*, *Encerrado*).
  * Indicadores de digitação diferenciados para Atendente N1 e Especialista N2.
  * Botão **Encerrar Chat** (`/client-close`) e bloqueio automático do campo de entrada ao receber `session.closed`.

* **Visão Atendente N1 (`?role=agent`):**
  * **Coluna Esquerda (Inbox):** fila de sessões com filtros (`Open`, `Escalated`, `Closed`), busca textual, contador de turnos e categoria.
  * **Coluna Central (Thread & Composer):** histórico de mensagens, exibição destacada da pergunta pendente, indicador de processamento do Copiloto, área de rascunho editável e ações **Send Reply** (detecta automaticamente `ACEITA_SEM_EDICAO` vs `EDITADA` comparando com o rascunho original), **Escalate to N2** e **Close**.
  * **Coluna Direita (AI Copilot / Details):** justificativa do Auditor (*Why This Response?*), categoria, `RAG Chunk ID`, badge de *Cache Hit / Vector Search* e alerta visual de escalonamento.
  * **Modo Somente Leitura:** ao escalar para N2 (ou encerrar), o composer e o botão *Close* são travados com banner informativo.

* **Visão Especialista N2/N3 (`?role=specialist`):**
  * **Escalated Queue:** fila ao vivo alimentada por `/ws/specialist`.
  * **Thread & Chat Direto:** visualização do histórico completo (Cliente + N1 + N2) e composer ativo para responder diretamente ao cliente em tempo real.
  * **Escalation Dossier:** resumo executivo (`handoff_summary`), motivo do auditor (`auditor_escalation_reason`), metadados do cliente e botão **Resolve Ticket**.

---

## 4. Testes Automatizados

A validação da camada de API e regras HITL está organizada em:
* `tests/test_api_endpoints.py`: testa ciclo completo das rotas REST, isolamento multi-tenant, WebSockets, privacidade (`view=client`) e dossiê do especialista.
* `tests/test_hitl_rules.py` & `tests/test_pipeline_hitl.py`: validam regras de confirmação humana, cálculo de edição (`was_edited`, `edit_ratio`) e transições de estado da pipeline.

---

## 5. Como Rodar Localmente

### Pré-requisitos
* Python 3.12+
* Node.js (LTS) e npm
* Docker (PostgreSQL + `pgvector`)

### Passo a Passo
1. **Banco de Dados:**
   ```bash
   docker compose up -d
   ```
2. **Back-end (FastAPI):**
   ```bash
   python -m venv venv
   .\venv\Scripts\Activate.ps1   # Linux/macOS: source venv/bin/activate
   pip install -r requirements.txt
   uvicorn src.api.main:app --reload
   ```
   * API: `http://localhost:8000` | Swagger: `http://localhost:8000/docs`
3. **Front-end (React + Vite):**
   ```bash
   cd frontend-app
   npm install
   npm run dev
   ```
   * Cliente: `http://localhost:5173/?role=client`
   * Atendente N1: `http://localhost:5173/?role=agent`
   * Especialista N2/N3: `http://localhost:5173/?role=specialist`
4. **Testes:**
   ```bash
   pytest
   ```

---

## 6. Próximos Passos & Melhorias Mapeadas

* **Contexto para mensagens simples / sem correspondência:** evitar que saudações isoladas (ex.: *"oi"*, *"olá"*) ou mensagens curtas fora de padrão disparem escalonamento indevido para N2.
* **Remover saudações repetitivas da IA:** ajustar o prompt do Redator para não sugerir cumprimentos (*"Bom dia! Tudo bem?"*) em toda nova mensagem de uma conversa já em andamento.
* **Mensagem de contexto junto com o escalonamento:** permitir enviar uma mensagem personalizada do atendente N1 junto com o aviso de transferência ao escalar para N2.
* **UX do Front-end & Testes:** renderização de Markdown nas bolhas de chat, reconexão automática de WebSocket e expansão do `pytest` cobrindo as rotas de posse N2 (`/client-close`, `/specialist/sessions/{id}/messages` e bloqueio `403`).