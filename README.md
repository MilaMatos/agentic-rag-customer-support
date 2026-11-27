# Suíte de Avaliação & Benchmark Multi-Agente (`feat/eval-benchmark`)

> **Por que esta branch é separada da `main`?**
> Esta branch isola toda a infraestrutura de benchmark, tabelas de resultados no PostgreSQL (`eval_results` e `eval_multiturn_results`), datasets sintéticos e runners de avaliação. O objetivo é permitir experimentos estatísticos pesados e reutilização da metodologia por outras equipes **sem poluir o código de produção nem o schema oficial da `main`**.

---

## 1. Estrutura da Suíte

```text
data/evaluation/
├── testes_benchmark.json     # 68 casos single-turn (30 EN, 30 PT, 8 bordas EDGE)
└── testes_benchmark.py       # Script gerador/estruturador do dataset

src/eval/
├── probe_models.py           # Pré-teste rápido de latência, JSON e thinking ON/OFF
├── probe_adaptacao.py        # Validação de adaptação dos modelos filtrados
├── presets.py                # Combinações de modelos por agente (isolamento 1 variável/degrau)
├── judge.py                  # AvaliadorDuplo (Juiz Técnico + Juiz Cliente em paralelo)
├── runner_single_turn.py     # Executor single-turn com checkpoint automático no PostgreSQL
├── runner_multi_turn.py      # Executor multi-turn com LLM simulando o cliente
└── relatorio.py              # Consolidador de métricas (resumo, detalhe e exportação CSV)
```

---

## 2. Por que usar um Juiz Duplo em Paralelo (`AvaliadorDuplo`)?

Usar uma única nota de LLM-as-a-Judge mascara falhas opostas e graves em sistemas de suporte com RAG:

* **Falso positivo de UX ("Alucinação Educada"):** o modelo improvisa regras ou finge ter consultado logs internos em um tom acolhedor — recebe **Cliente 10/10**, mas **Técnico 0/10**.
* **Falso positivo técnico ("Robô Rígido"):** o modelo acerta a regra do manual, mas escala cedo demais sem ouvir o usuário ou vaza jargões internos (`N1`, `backoffice`) — recebe **Técnico 10/10**, mas **Cliente 4–6/10**.

Para evitar esse ponto cego, o `src/eval/judge.py` dispara **dois juízes independentes em paralelo** com visões propositalmente diferentes:

| Juiz | Modelo | O que enxerga | Critérios (0 a 2 cada · Total 0–10) |
| :--- | :--- | :--- | :--- |
| **Juiz Técnico (QA / Auditoria)** | `nvidia/nemotron-3-ultra-550b-a55b` | Manual base recuperado, fonte citada, gabarito esperado, decisão de escalonamento e handoff. | **Single-Turn:** `citacao_fonte`, `aderencia_escopo`, `fidelidade_manual`, `ausencia_alucinacao`, `coerencia_escalonamento`<br>**Multi-Turn:** `nao_repeticao_n1`, `qualidade_handoff`, `memoria_isolamento`, `ausencia_alucinacao`, `timing_escalonamento` |
| **Juiz Cliente (UX / CSAT)** | `nvidia/nemotron-3.5-super-vl-120b-a12b` | **Apenas** a conversa final visível ao usuário (sem manual, sem metadados internos). | **Single-Turn:** `empatia_tom`, `clareza_passos`, `satisfacao_geral`, `utilidade_pratica`, `sem_jargao_interno`<br>**Multi-Turn:** `empatia_tom`, `clareza_conducao`, `satisfacao_geral`, `sem_jargao_interno`, `sensacao_de_ser_ouvido` |

---

## 3. Metodologia Experimental

A avaliação foi dividida em **três fases progressivas** para economizar tempo e isolar a contribuição real de cada modelo:

1. **Pré-teste / Probe (`probe_models.py`):** mede latência pura, adesão a JSON estruturado e impacto de `enable_thinking=True` vs `False`. Elimina cedo modelos instáveis ou lentos demais antes de rodar centenas de casos.
2. **Bateria Multi-Turno (`runner_multi_turn.py`):** 6 cenários × 3 repetições (18 conversas/preset) com um LLM simulando o cliente. Valida dinâmica conversacional real: retenção de memória, cache hit, troca de tópico (`NOVO_TOPICO`), não repetição de passos e momento correto de escalar.
3. **Bateria Single-Turn Bilíngue (`runner_single_turn.py`):** 68 casos × 5 repetições (340 execuções/preset) sem ruído entre turnos, usando **presets em escada** que trocam **apenas 1 agente por degrau**:
   * `copilot_fast` $\rightarrow$ `copilot_preciso`: isola o **Classificador** (`lightning-30b` vs `ultra-550b`).
   * `copilot_preciso` $\rightarrow$ `copilot_redator_super`: isola o **Redator** (`lightning-30b` vs `super-vl-120b`).
   * `copilot_redator_super` $\rightarrow$ `autonomo_fast`: isola o **Auditor** (`super-vl-120b` vs `ultra-550b`).

### Resiliência e Checkpoint no PostgreSQL
Cada execução concluída é gravada imediatamente nas tabelas `eval_results` (single-turn) ou `eval_multiturn_results` (multi-turn) em `src/db/models.py`. Se houver queda de rede ou timeout, o wrapper `src/agents/retry.py` tenta reconectar automaticamente; caso o processo seja interrompido, basta rodar o mesmo comando com o mesmo `--exp` que o runner retoma exatamente de onde parou sem repetir execuções já salvas.

---

## 4. Como Criar ou Adaptar para Outra Equipe / Domínio

Para reaproveitar este framework em outro projeto multi-agente:

1. **Monte o dataset (`data/evaluation/testes_benchmark.json`):** inclua casos canônicos (que devem ser resolvidos sem escalar), casos bilíngues se aplicável e casos de borda (`EDGE`) divididos entre *escalonamento obrigatório* e *fora de escopo real*.
   ```json
   {
     "id": "CAN-PT-01",
     "pergunta": "O 2FA não está funcionando, não recebo o código.",
     "expected_category": "Account",
     "expected_escalation": false
   }
   ```
2. **Cadastre seus presets em `src/eval/presets.py`:** mude apenas um agente por preset para conseguir atribuir ganhos de qualidade ou latência ao componente certo.
   ```python
   "meu_preset": {
       "classifier": {"model": "nvidia/nemotron-3-ultra-550b-a55b", "enable_thinking": False},
       "redactor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
       "auditor": {"model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "enable_thinking": False},
       "summarizer": {"model": "nvidia/nemotron-3.5-bolt-e4b"},
   }
   ```
3. **Ajuste as rubricas dos juízes em `src/eval/judge.py`:** adapte os 5 subcritérios (0 a 2 pontos cada) do Juiz Técnico às regras do seu domínio e mantenha o Juiz Cliente cego aos bastidores internos.
4. **Defina cenários multi-turno em `src/eval/runner_multi_turn.py`:** escreva a `mensagem_inicial`, a `instrucao_cliente` (persona e comportamento do simulador) e `expected_escalation`.
5. **Desacople a RAG do erro de classificação durante o benchmark:** passe `category_filter=None` tanto na pipeline quanto na consulta de referência do Juiz Técnico em `runner_single_turn.py` para medir separadamente a acurácia do Classificador e a qualidade de Redator/Auditor.

---

## 5. Como Executar

### Pré-requisitos
```bash
# Subir PostgreSQL + pgvector
docker compose up -d

# Ativar ambiente virtual e conferir .env (NVIDIA_API_KEY e DATABASE_URL)
source venv/bin/activate
```

### 1. Pré-teste rápido de modelos (Probe)
```bash
venv/bin/python -m src.eval.probe_models
```

### 2. Sanity Check (2 casos rápidos antes de rodar um lote grande)
```bash
venv/bin/python -m src.eval.runner_single_turn \
  --exp check_rapido \
  --preset copilot_redator_super \
  --dataset data/evaluation/testes_benchmark.json \
  --runs 1 --limit 2 --sleep 1.0

venv/bin/python -m src.eval.relatorio --modo single --exp check_rapido --detalhe
```

### 3. Bateria Single-Turn em background (`nohup` — ideal para madrugada)
```bash
mkdir -p logs
PYTHONUNBUFFERED=1 nohup bash -c '
venv/bin/python -u -m src.eval.runner_single_turn --exp st_v2_fast --preset copilot_fast --dataset data/evaluation/testes_benchmark.json --runs 5 --sleep 2.0 &&
venv/bin/python -u -m src.eval.runner_single_turn --exp st_v2_preciso --preset copilot_preciso --dataset data/evaluation/testes_benchmark.json --runs 5 --sleep 2.0 &&
venv/bin/python -u -m src.eval.runner_single_turn --exp st_v2_redator_super --preset copilot_redator_super --dataset data/evaluation/testes_benchmark.json --runs 5 --sleep 2.0 &&
venv/bin/python -u -m src.eval.runner_single_turn --exp st_v2_autonomo --preset autonomo_fast --dataset data/evaluation/testes_benchmark.json --runs 5 --sleep 2.5
' > logs/eval_single_overnight.log 2>&1 &

# Acompanhar progresso em tempo real
tail -f logs/eval_single_overnight.log
```

### 4. Bateria Multi-Turno
```bash
venv/bin/python -u -m src.eval.runner_multi_turn --exp mt_eval --preset copilot_redator_super --runs 3
```

### 5. Consolidar Relatórios e Exportar CSV
```bash
# Resumo geral Single-Turn + exportação CSV
venv/bin/python -m src.eval.relatorio --modo single --csv logs/relatorio_single.csv

# Detalhe caso a caso de um experimento específico
venv/bin/python -m src.eval.relatorio --modo single --exp st_v2_redator_super --detalhe

# Resumo geral Multi-Turno
venv/bin/python -m src.eval.relatorio --modo multi
```

---

## 6. Resultados de Referência (NexusTech — 1.360 Execuções Single-Turn)

| Preset (`thinking=False`) | Classificador | Redator | Auditor | Cat (BI) | Esc (Acur.) | Técnico (std) | Cliente | P50 |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `copilot_fast` | `lightning-30b` | `lightning-30b` | `super-vl-120b` | 82,6% | 92,9% | 9,08 (±1,74) | 9,35 | 15,97s |
| `copilot_preciso` | `ultra-550b` | `lightning-30b` | `super-vl-120b` | 89,4% | 93,5% | 9,19 (±1,52) | 9,32 | 12,20s |
| **`copilot_redator_super` (Vencedor)** | **`ultra-550b`** | **`super-vl-120b`** | **`super-vl-120b`** | **89,4%** | **92,4%** | **9,73 (±0,66)** | **9,16** | **14,26s** |
| `autonomo_fast` | `ultra-550b` | `super-vl-120b` | `ultra-550b` | 89,1% | 91,5% | 9,71 (±0,74) | 9,15 | 16,53s |

*Nota: `Esc (Acur.)` representa a assertividade da decisão de escalar vs. resolver no N1 (não a taxa de tickets escalados).*

### Principais Aprendizados
* **`thinking=False` venceu com folga:** desligar o raciocínio reduziu a latência em até 10× no probe e eliminou estouros de token (`EmptyLLMResponseError`) no multi-turno.
* **Maior ganho veio no Redator:** trocar `lightning-30b` por `super-vl-120b` elevou a nota técnica de `9,19` para `9,73`, cortou o desvio padrão pela metade (`1,52 → 0,66`) e zerou alucinações detectadas (`0,0%`).
* **Auditor mais pesado não compensou:** subir o Auditor para `ultra-550b` manteve a mesma nota (`9,71`) e quase dobrou o tempo da etapa Redator+Auditor (`10,98s → 20,15s`).
* **Busca RAG sem `category_filter`:** resultou em `0,0%` de falso fora de escopo em português e exatos `50,0%` nos 8 casos `EDGE` (barrando os 4 fora de escopo reais pelo limiar de similaridade).