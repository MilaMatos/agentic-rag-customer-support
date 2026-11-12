# Documentação Técnica — Entrega 3 (E3)
## Núcleo de Classificação e Handoff: Triagem Determinística e Resumo Executivo

**Projeto:** NexusTech Support Copilot  
**Escopo do Documento:** Especificação técnica do Agente Classificador de Triagem Inicial (`classifier.py`, `classification_schema.py`) e do Agente Analista de Handoff/Resumo (`summarizer.py`).

---

## 1. Visão Geral da Arquitetura

Para garantir uma orquestração perfeita antes e depois do núcleo RAG de atendimento, a arquitetura implementa dois agentes periféricos cruciais, focados em categorização de entrada e síntese de saída:

1. **Agente Classificador (`Especialista em Triagem`):** Opera como o ponto de entrada da pipeline. Lê a dúvida bruta do cliente e determina, de forma autônoma e estruturada (via Pydantic), a taxonomia do ticket (Categoria, Prioridade e Nível de Atendimento Inicial). É o **único responsável pelo roteamento**, definindo a porta lógica pela qual o ticket será tratado.
2. **Agente Analista de Handoff (`Analista de Handoff e Qualidade`):** Opera como o ponto de saída para tickets que exigem transbordo humano (escalonamento). Lê a resposta completa gerada pelo Redator N1 e sintetiza um resumo executivo hiper-focado, otimizando o *Time-to-Resolution* (TTR) do especialista humano (N2/N3) que assumirá o caso.

Ambos operam sob o padrão de *Zero-Shot Classification/Summarization*, extraindo informações sem estado prévio.

---

## 2. Agente Classificador de Triagem Inicial (`src/rag/prompts/classifier.py`)

O **Agente Classificador** tem a missão crítica de categorizar o problema do cliente antes de qualquer consulta ao banco de dados vetorial, garantindo que o `NexusRetriever` aplique os filtros semânticos corretos e que o fluxo obedeça à taxonomia de escalonamento.

### 2.1. Hiperparâmetros de Inferência
* **Modelo Base:** `nvidia/nemotron-3.5-lightning-30b-a3b`
* **Temperatura:** `0.0` (máximo determinismo lógico para garantir precisão nas categorias fechadas).
* **Controle de Latência (*Reasoning Override*):** `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` desativa o *chain-of-thought* longo para garantir triagens em frações de segundo.

### 2.2. Arquitetura do Prompt e Regras de Negócio
O Classificador atua com diretivas rígidas injetadas diretamente na `Task`:

1. **Taxonomia Fechada:** O modelo é obrigado a mapear o problema do cliente contra uma taxonomia predefinida e inflexível.
2. **Injeção de Regras de Roteamento:** O prompt contém condicionais de negócio explícitas, como:
   * **Problemas de Cobrança:** Inicializados sempre como `N1`, forçando a verificação de manuais de autoatendimento.
   * **Falhas Massivas/Erro 500:** Classificados diretamente como `N3` (crítico) para ignorar o autoatendimento.
   * **Dúvidas Gerais:** Roteadas para `N1`.
3. **Few-Shot Prompting Incorporado:** Para calibrar o LLM, o prompt da `Task` fornece exemplos diretos de entrada e saída (ex: "I was charged twice..." -> "Billing", "Media", "N1").

### 2.3. Contrato de Dados Estrito (Pydantic Schema)
Para impedir falhas de *parsing* JSON, a saída do Agente Classificador é rigidamente controlada pelo `TicketClassification` (`classification_schema.py`), forçando o CrewAI a garantir conformidade:

| Campo Pydantic | Regra de Validação / Enumeração Aceite |
| :--- | :--- |
| `category` | Estritamente: `Technical`, `Billing`, `Account`, `Fraud` ou `General Inquiry`. |
| `priority` | Estritamente: `Baixa`, `Media`, `Alta` ou `Critica`. |
| `initial_level` | Estritamente: `N1`, `N2` ou `N3` (O nível definitivo de roteamento). |
| `triage_justification` | Máximo de 2 frases justificando a escolha da categoria e nível. |

---

## 3. Agente Analista de Handoff e Resumo (`src/rag/prompts/summarizer.py`)

Quando o Agente Auditor aprova uma resposta, mas determina que o caso não foi resolvido (acionando a flag `requer_escalonamento = true`), o **Agente Analista de Handoff** entra em ação. A sua função é extrair valor administrativo do texto longo gerado pelo Redator N1.

### 3.1. Hiperparâmetros de Inferência
* **Modelo Base:** `nvidia/nemotron-3.5-lightning-30b-a3b`
* **Temperatura:** `0.0` (garante extração factual e evita a adição de interpretações alucinadas ao resumo).
* **Controle de Latência (*Reasoning Override*):** Desativação do *thinking* via `extra_body` para otimização de velocidade na finalização da *pipeline*.

### 3.2. Engenharia de Extração (Formatting Constraints)
Para evitar que o LLM crie resumos discursivos, parágrafos introdutórios ("Aqui está o resumo...") ou perca a objetividade, o prompt do `Summarizer` utiliza **restrições de formatação estritas** (*Formatting Constraints*):

1. **Supressão de Ruído Conversacional:** O prompt exige explicitamente: *"não adicione saudações ou texto extra, apenas as duas linhas abaixo"*.
2. **Estrutura de Saída Fixa:** O agente é forçado a preencher dois *bullets* práticos:
   * **`- Ação Tomada:`** Síntese em uma frase do que o sistema N1 informou ou bloqueou (ex: "Chamado encaminhado para a equipa dedicada").
   * **`- Próximo Passo do Cliente:`** O que o utilizador deve fazer ou esperar a seguir (ex: "Aguardar contacto do especialista").

### 3.3. Integração com a Rastreabilidade (Handoff Schema)
A saída limpa de duas linhas gerada por este Agente (`result.raw`) é injetada diretamente no campo `resumo_executivo` do `ResumoHandoffSchema` no orquestrador principal (`pipeline_agents.py`). Isto assegura que, quando o ticket chega à fila humana do N2/N3, o especialista lê apenas a síntese destilada e factual do que a IA e o cliente já discutiram, acelerando o tempo de diagnóstico manual.