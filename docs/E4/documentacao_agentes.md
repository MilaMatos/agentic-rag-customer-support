# Entrega 4: Arquitetura de Agentes, Tools e Testes Isolados

Nesta entrega, consolidamos a arquitetura de agentes do **NexusTech Support Copilot** utilizando o framework CrewAI. Antecipando parte do escopo de orquestração, estruturamos **quatro agentes especialistas** encapsulados em classes autônomas (`src/agents/`), operando sob contratos Pydantic (`schemas.py`), *Output Parsers* determinísticos (`parsers.py`) e integração com ferramentas (`tools.py`).

---

## 1. Especificação dos Agentes e Ferramentas (Itens 4.1, 4.2 e 4.3)

### 1.1. Agente Redator N1 (`AgenteRedatorN1`) — Integração com Tool RAG
Agente responsável pela comunicação direta com o cliente, transformando diretrizes técnicas em respostas empáticas e acionáveis.

* **Papel (`role`):** Especialista de Atendimento (Redator).
* **Responsabilidade (`goal`):** Produzir resposta clara, natural e estritamente fiel à base de conhecimento para o cliente.
* **Ferramenta Vinculada (`tools`):**
  * `buscar_manual_rag_tool` (`src/agents/tools.py`): Encapsula o `NexusRetriever` como uma `@tool` oficial do CrewAI. Realiza busca vetorial no PostgreSQL (`pgvector`) usando o modelo `nvidia/nemotron-3.5-embed-1b`, filtro de categoria, `top-k = 1` e piso de similaridade de cosseno de `0.30`.
  * **Modo de Operação Híbrido:** Na execução isolada (`chunks=None`), o agente invoca autonomamente a `buscar_manual_rag_tool`. Na execução em pipeline (`chunks` pré-carregados pelo orquestrador), consome o contexto diretamente para evitar buscas duplicadas no banco.
* **Inputs:** `pergunta_cliente` (str), `chunks` (list ou None), `feedback_anterior` (str opcional) e `categoria` (str opcional).
* **Outputs:** Dicionário processado por `separar_mensagem_e_fonte()` contendo `mensagem_cliente` (texto limpo), `fonte_citada` (ID do manual ou `FORA_DE_ESCOPO`) e `texto_completo_auditoria`.
* **Critérios de Decisão:**
  * Guia o passo a passo de autoatendimento (N1) quando a dúvida possui cobertura e não fere gatilhos de escalonamento.
  * Informa transferência imediata para um especialista caso o cliente já tenha tentado os passos sem sucesso ou quando a busca retornar `FORA_DE_ESCOPO`.

---

### 1.2. Agente Auditor de Qualidade (`AgenteAuditorQualidade`)
Atua como camada de governança e roteamento técnico antes que qualquer mensagem chegue ao usuário final.

* **Papel (`role`):** Auditor de Qualidade e Roteamento de Tickets.
* **Responsabilidade (`goal`):** Auditar a fidelidade da resposta gerada pelo Redator frente ao manual RAG e definir se o chamado requer escalonamento humano (`requer_escalonamento: bool`).
* **Inputs:** `pergunta_cliente` (str), `resposta_redator` (str contendo a tag de fonte) e `chunks` (list com as fatias `resolucao_n1` e `escalonamento`).
* **Output Estruturado (`VereditoAuditorSchema`):**
  * `analise_raciocinio` (str)
  * `aprovado_para_envio` (bool)
  * `redator_alucinou` (bool)
  * `citou_fonte` (bool)
  * `requer_escalonamento` (bool)
  * `feedback_correcao` (str)
* **Critérios de Decisão:**
  * Reprova a resposta (`aprovado_para_envio = False`) e gera instruções em `feedback_correcao` se o Redator inventar valores/menus, omitir a tag `[[FONTE: ...]]`, insistir em passos N1 quando o caso exigia escalonamento ou ceder a *Prompt Injection*.
  * Aprova o bloqueio (`aprovado_para_envio = True` e `requer_escalonamento = True`) quando o Redator recusa solicitações fora da documentação e encaminha com `[[FONTE: FORA_DE_ESCOPO]]`.

---

### 1.3. Agente Classificador (`AgenteClassificador`)
Responsável pela triagem inicial do chamado para restringir o espaço de busca semântica no banco vetorial.

* **Papel (`role`):** Especialista em Triagem de Suporte B2B.
* **Responsabilidade (`goal`):** Classificar o ticket na taxonomia oficial da NexusTech.
* **Inputs:** `pergunta_cliente` (str).
* **Output Estruturado (`TicketClassification`):** `category` (`Technical`, `Billing`, `Account`, `Fraud` ou `General Inquiry`), `priority` (`Baixa`, `Media`, `Alta`, `Critica`), `initial_level` (`N1`, `N2`, `N3`) e `triage_justification` (str).

---

### 1.4. Agente de Resumo Interno (`AgenteResumo`)
Sintetiza o atendimento para alimentar o histórico interno e agilizar o contexto em casos de transbordo (Handoff).

* **Papel (`role`):** Analista de Handoff e Qualidade.
* **Responsabilidade (`goal`):** Extrair os pontos críticos da resposta enviada ao cliente em formato padronizado.
* **Inputs:** `resposta_final_cliente` (str).
* **Outputs:** String estruturada em duas linhas (`- Ação Tomada:` e `- Próximo Passo do Cliente:`).

---

### 1.5. Funções Auxiliares e Output Parsers (`src/agents/parsers.py`)
Para manter baixa latência e evitar chamadas extras de LLM apenas para formatação, implementamos parsers determinísticos em Python:
* `separar_mensagem_e_fonte()`: Remove blocos `<think>`, extrai o código da tag `[[FONTE: ...]]` via Regex e isola a mensagem limpa para o cliente.
* `extrair_json_auditoria()` e `extrair_json_classificacao()`: Higienizam marcações Markdown de código JSON e garantem fallback seguro na conversão para objetos Pydantic.

---

## 2. Estratégia de Testes Automatizados (Item 4.4)

A suíte de validação foi estruturada com **`pytest`** na pasta `tests/`, dividida em três níveis de isolamento para permitir validação rápida de mudanças sem depender da execução da pipeline completa:

| Arquivo de Teste | Escopo | Cenários Validados |
| :--- | :--- | :--- |
| **`tests/test_unit_modulos.py`** | Testes Unitários Puros (Sem LLM / Sem Banco) | • Fatiamento Regex de chunks (`_fatiar_conteudo`) em sintomas, N1 e escalonamento.<br>• Extração da tag oculta `[[FONTE: ...]]` e fallback para `NÃO_CITADA`.<br>• Montagem de prompts para cenários `FORA_DE_ESCOPO` e parse de JSON sujo. |
| **`tests/test_retriever_rag.py`** | Testes de Integração do Motor RAG (`PGVector`) | • Comparativo prático entre `Top-3` e `Top-1` em queries dentro do escopo.<br>• Bloqueio automático pelo threshold (`< 0.30`) para dúvidas de suporte fora da documentação. |
| **`tests/test_agents.py`** | Testes Isolados de Agentes (`@pytest.mark.parametrize`) | • **Classificador:** Triagem de cobrança duplicada (`Billing` / `N1`) e queda crítica (`Technical` / `N3`).<br>• **Redator:** Fluxo com chunk pré-carregado, fluxo autônomo invocando `buscar_manual_rag_tool` (`chunks=None`) e defesa contra *Prompt Injection* (receita de bolo).<br>• **Auditor:** Aprovação de resposta N1 fiel, reprovação de alucinação (promessa de acesso a banco de dados e valores inventados) e aprovação de transbordo `FORA_DE_ESCOPO`.<br>• **Resumidor:** Formatação estrita em duas linhas executivas. |

**Comandos de execução:**

    # Executar toda a suíte
    venv/bin/python -m pytest tests/ -v

    # Executar apenas os testes parametrizados de um agente específico
    venv/bin/python -m pytest tests/test_agents.py -k "test_agente_redator" -v

    #Executar um teste específico pelo ID
    venv/bin/python -m pytest tests/test_agents.py -k "autonomo_usando_rag_tool" -v

---

## 3. Dificuldades Encontradas e Soluções Aplicadas

1. **Falso Negativo do Auditor em Casos de *Prompt Injection* / Fora de Escopo:**
   * *Problema:* Ao testar um ataque onde o usuário pedia para esquecer as regras e fornecer uma receita de bolo, o Redator agia corretamente recusando o pedido e encaminhando com `[[FONTE: FORA_DE_ESCOPO]]`. Contudo, o Auditor reprovava a resposta alegando que o Redator "não atendeu ao pedido de confeitaria do cliente".
   * *Solução:* Refinamos o prompt de sistema do Auditor (`src/agents/prompts/auditor.py`) adicionando uma diretriz explícita para casos `[FORA_DE_ESCOPO]`, instruindo-o a aprovar a contenção quando o Redator se recusar a sair do personagem e marcar `requer_escalonamento = True`.
2. **Simplificação do Contrato de Escalonamento (Níveis vs. Booleano):**
   * *Problema:* Pedir ao Auditor para decidir entre `"N1"`, `"N2"` ou `"N3"` gerava ambiguidade em casos fora da base (ora classificando como N2, ora como N3).
   * *Solução:* Simplificamos o contrato em `VereditoAuditorSchema` para o booleano `requer_escalonamento: bool` (`True` para transbordo à fila especializada e `False` para retenção no N1), mantendo um fallback retrocompatível no parser.
3. **Convergência de Códigos Paralelos e Acoplamento:**
   * *Problema:* Os scripts iniciais dos agentes foram desenvolvidos em paralelo com estruturas diferentes (alguns acoplados à pipeline e outros em scripts procedurais com `output_file` fixo).
   * *Solução:* Refatoramos toda a estrutura em `src/agents/`, separando templates (`prompts/`), funções auxiliares (`parsers.py`), contratos (`schemas.py`) e padronizando os 4 agentes em classes independentes com o método `.executar()`.
4. **Latência Elevada e Poluição de Logs/Warnings no Terminal:**
   * *Problema:* Os modelos `nemotron` levavam mais de 30 segundos quando geravam raciocínio oculto (`<think>`) e o CrewAI emitia dezenas de `DeprecationWarning` e avisos de contagem aproximada de tokens a cada chamada.
   * *Solução:* Desativamos o pensamento oculto via `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (reduzindo o tempo total da pipeline para ~8 a 12s) e configuramos filtros de logging/warnings em `src/agents/__init__.py` e `pytest.ini`.

---

## 4. Próximos Passos

1. **Expansão do Catálogo de *Edge Cases* em `tests/test_agents.py`:** Adicionar novos cenários nas listas parametrizadas (`CASOS_REDATOR`, `CASOS_AUDITOR` e `CASOS_CLASSIFICADOR`), cobrindo engenharia social, perguntas ambíguas com múltiplos problemas no mesmo ticket e entradas vazias/ruído.
2. **Amadurecimento da Memória Conversacional Multi-Turno:** Evoluir o gerenciamento de contexto iniciado em `sandbox/chat_terminal.py` para que o `AgenteClassificador` identifique se a nova mensagem do cliente no Turno 2+ é continuação do mesmo problema ou mudança de assunto, preservando o chunk original quando o cliente apenas responde a uma pergunta de acompanhamento.
3. **Exposição via API e Interface (Sprints Futuras):** Após consolidar a bateria de testes de borda e a estabilidade da memória por sessão, expor a `NexusSupportPipeline` através de endpoints REST (FastAPI) integrados ao frontend de atendimento.