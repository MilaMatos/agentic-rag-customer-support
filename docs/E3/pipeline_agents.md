# Documentação Técnica: Pipeline Multi-Agente RAG (NexusTech Support Copilot)

## 1. Visão Geral
Este documento descreve a arquitetura e o fluxo de execução do orquestrador multi-agente implementado em `pipeline_agents.py`. O sistema automatiza o atendimento de suporte B2B combinando triagem estruturada, recuperação semântica vetorial, um ciclo de melhoria contínua Ator-Crítico (*Actor-Critic*) entre o Redator e o Auditor, e resumos executivos para transbordo (*handoff*).

---

## 2. Contratos de Dados (Pydantic Schemas)
Para garantir estabilidade e tipagem estrita na comunicação entre os agentes e na persistência de logs, utilizamos contratos em Pydantic:

* **`TriagemClassificadorSchema`**: Define os metadados de entrada do chamado (`categoria`, `prioridade`, `nivel_inicial` e `justificativa_triagem`).
* **`ContextoRAGSchema`**: Armazena o rastreio do chunk recuperado no PGVector (`chunk_id`, `subcategoria`, `score_similaridade` e a regra de escalonamento aplicada).
* **`AtendimentoRedatorSchema`**: Consolida a mensagem final tratada, a fonte técnica citada e o número de tentativas de redação.
* **`VereditoAuditorSchema`**: Contém o resultado da avaliação do *LLM-as-a-Judge*, incluindo flags de aprovação, alucinação, citação de fonte e exigência de escalonamento.
* **`ResumoHandoffSchema`**: Gera um sumário estruturado para operadores humanos (N2/N3) contendo a ação tomada e o próximo passo recomendado.
* **`CaixaRastreabilidadeSchema`**: Envelope mestre que unifica todo o ciclo de vida do ticket e sua telemetria detalhada.

---

## 3. Fluxo de Execução da Pipeline (`NexusSupportPipeline`)

O fluxo de processamento de um ticket (`processar_ticket`) segue cinco etapas sequenciais:

1. **Triagem Inicial**: O agente classificador processa a dúvida do cliente ou aceita parâmetros externos validados.
2. **Busca Vetorial Fatiada**: O `NexusRetriever` executa uma busca de similaridade de cosseno no PGVector aplicando filtros estritos por categoria (`min_similarity=0.30`).
3. **Loop Ator-Crítico (Redator + Auditor)**:
   * O **Redator** (`_executar_redator`) gera a resposta conversacional N1 com base nos chunks fatiados. Os parâmetros `memory=False` e `cache=False` são forçados no CrewAI para evitar loops estáticos de memória.
   * O **Auditor** (`_executar_auditor`) atua com temperatura determinística ($T=0.0$) avaliando a fidelidade da resposta, exigindo correção caso haja desvios ou alucinações.
4. **Governança de Transbordo**: Se o auditor determinar que o caso requer escalonamento (`requer_escalonamento = True`), o fluxo de *handoff* é ativado.
5. **Geração de Logs e Telemetria**: Todos os tempos de execução (classificação, retriever, redator e auditor) são metrificados individualmente em segundos, e o envelope consolidado é salvo em formato JSON na pasta de rastreabilidade.