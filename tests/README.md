# Suíte de Testes (`tests/`)

Esta pasta reúne os testes automatizados de regressão da pipeline multi-agente, memória no PostgreSQL e resiliência de modelos.

> **Nota sobre benchmarks de modelos:** avaliações estatísticas extensivas (Single-Turn 68×5, Multi-Turno com cliente simulado e Juiz Duplo) ficam isoladas na branch **`feat/eval-benchmark`**. Os testes aqui garantem que o código de produção em `main` funciona corretamente a cada alteração.

---

## 1. Estrutura da Suíte (34 testes)

| Arquivo | Qtd | Marcador | Dependências | O que valida |
| :--- | :---: | :---: | :--- | :--- |
| `test_unit_modulos.py` | 8 | — | Nenhuma (offline) | Fatiamento de chunks, parsers determinísticos (`[[FONTE]]`, JSON sujo), prompts fora de escopo e defaults do `llm_factory.py` (`thinking=False`). |
| `test_db_repo.py` | 5 | — | PostgreSQL (Docker) | Ciclo de memória por tópico (`chat_sessions`/`chat_messages`/`copilot_traceability`), isolamento por `tenant_id`, encerramento/limpeza, fila N2, retry transitório e acionamento/bloqueio de `fallback_llm`. |
| `test_pipeline_db.py` | 2 | — | PostgreSQL (Docker) | Execução paralela no Turno 1 (`Classificador` + embedding), RAG sem `category_filter`, isolamento de histórico entre tópicos, compactação em background e handoff. |
| `test_agents.py` | 9 | `llm` | NVIDIA NIM (`.env`) | Testes parametrizados individuais dos 4 agentes (Classificador, Redator N1, Auditor QA e Resumidor — handoff e compactação) incluindo prompt injection e alucinação. |
| `test_multiturn.py` | 1 | `llm` | PostgreSQL + NVIDIA NIM | Fluxo E2E de 2 turnos com LLMs reais validando follow-up, reutilização de cache RAG (`0 ms`) e escalonamento N2 com geração de `handoff_summary`. |
| `test_api_endpoints.py` | 4 | — | PostgreSQL (Docker) | Rotas REST (`/health`, `/ready`, `/sessions`, `/close`), isolamento multi-tenant, privacidade `view=client`, WebSockets e fila do especialista. |
| `test_hitl_rules.py` | 3 | — | Nenhuma (offline) | Cálculo de edição (`was_edited`/`edit_ratio`) e regra de chamada sob demanda do Resumidor apenas no escalonamento N2. |
| `test_pipeline_hitl.py` | 2 | — | PostgreSQL (Docker) | Fluxo multi-turno HITL validando sugestão pendente sem confirmação, continuação e troca de tópico. |
---

## 2. Pré-requisitos

1. Ambiente virtual ativo com as dependências instaladas (`requirements.txt`).
2. **Para testes com banco (`test_db_repo.py`, `test_pipeline_db.py`, `test_multiturn.py`):** PostgreSQL + `pgvector` em execução:
   ```bash
   docker compose up -d
   ```
3. **Para testes com marcador `llm` (`test_agents.py`, `test_multiturn.py`):** arquivo `.env` configurado com `NVIDIA_API_KEY` válida.

---

## 3. Como Executar

### Testes rápidos sem chamada de LLM (15 testes · ~1–2s)
Ideal para rodar antes de qualquer commit ou em CI:
```bash
python -m pytest tests/ -v -m "not llm" -p no:warnings
```

### Apenas testes unitários puros (sem Docker nem API · 8 testes)
```bash
python -m pytest tests/test_unit_modulos.py -v -p no:warnings
```

### Apenas testes com LLMs reais na NVIDIA NIM (10 testes · ~35s)
Valida aderência real dos prompts, modelos padrão e fallback:
```bash
python -m pytest tests/ -v -m llm -p no:warnings
```

### Suíte completa (todos os 34 testes)
```bash
python -m pytest tests/ -v -p no:warnings
```

### Rodar um arquivo ou teste específico
```bash
python -m pytest tests/test_db_repo.py -v
python -m pytest tests/test_db_repo.py -k "fallback" -v
```

---

## 4. Boas Práticas ao Adicionar Novos Testes

* **Sempre marque testes que chamam a API da NVIDIA com `@pytest.mark.llm`** (registrado em `pytest.ini`), mantendo a execução `-m "not llm"` rápida e determinística.
* **Limpe dados criados no PostgreSQL:** use IDs únicos (`uuid4()`) e chame `repo.limpar_sessao_teste(sid)` e `pipeline.shutdown()` dentro de blocos `finally:`.
* **Testes de API / FastAPI:** quando novos arquivos (ex.: `test_api*.py`) forem adicionados após o merge do back-end, basta incluí-los na tabela da Seção 1.