# NexusTech Support Copilot

Copiloto de suporte B2B multi-agente com RAG (`pgvector`), fluxo Human-in-the-Loop (N1 → N2/N3), API FastAPI com WebSockets em tempo real e interface multi-visão em React + Vite + Tailwind.

## Pré-requisitos

- Docker e Docker Compose
- Chave de API válida da NVIDIA NIM (`NVIDIA_API_KEY`)

## 1. Configuração Inicial

Crie o arquivo `.env` na raiz a partir do modelo:

```bash
cp .env.example .env
```

Preencha `NVIDIA_API_KEY` no `.env`.

## 2. Subir a Stack Completa (Banco + API + Front-end)

```bash
docker compose up -d --build
```

*(Se estiver usando Compose v1, utilize `docker-compose` no lugar de `docker compose`.)*

## 3. Inicializar Tabelas e Ingerir os Manuais (primeira execução)

```bash
docker compose exec api python -c "from src.db.connection import criar_tabelas; criar_tabelas()"
docker compose exec api python -m src.ingestion.vector_pipeline
```

## 4. Acessar a Aplicação

Abra as três visões lado a lado para testar o fluxo completo em tempo real:

- **Cliente:** http://localhost:5173/?role=client
- **Atendente N1:** http://localhost:5173/?role=agent
- **Especialista N2/N3:** http://localhost:5173/?role=specialist
- **API (Swagger):** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

## 5. Testes Automatizados

Rodar a suíte rápida (24 testes sem chamadas à NVIDIA NIM):

```bash
docker compose exec api pytest -m "not llm" -v -o cache_dir=/tmp/pytest_cache
```

Para detalhes de todos os 34 testes (incluindo testes reais com LLMs `-m llm`), consulte [`tests/README.md`](tests/README.md).

## Documentação Adicional

- **API, WebSockets e Front-end:** [`docs/E5/documentacao_tecnica_api_frontend.md`](docs/E5/documentacao_tecnica_api_frontend.md)
- **Suíte de Testes:** [`tests/README.md`](tests/README.md)
- **Benchmarks e Juiz Duplo:** branch `feat/eval-benchmark`