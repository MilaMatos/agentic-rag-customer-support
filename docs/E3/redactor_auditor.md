# Documentação Técnica — Entrega 3 (E3)
## Núcleo RAG Multi-Agente: Recuperação Seletiva, Redator N1 e Auditor de Governança

**Projeto:** NexusTech Support Copilot  
**Escopo do Documento:** Especificação técnica do subsistema de Recuperação Vetorial Fatiada (`retriever.py`), Engenharia de Prompts e Guardrails do Agente Redator N1 (`redactor.py`) e do Agente Auditor de Qualidade e Validação de Transbordo (`auditor.py`).

---

## 1. Visão Geral da Arquitetura

No fluxo de atendimento automatizado da NexusTech, a geração de respostas baseadas na Base de Conhecimento (*Retrieval-Augmented Generation* - RAG) opera sob o padrão arquitetural **Actor-Critic** (Ator-Crítico), desacoplando a responsabilidade de redação conversacional da validação de regras de negócio e validação da necessidade de transbordo de tickets:

1. **Camada de Recuperação e *Context Slicing* (`NexusRetriever`):** Consulta o banco vetorial PostgreSQL (`pgvector`) filtrando pelo domínio semântico do chamado e particiona deterministicamente o documento recuperado em seções operacionais independentes.
2. **Agente Ator — Especialista de Atendimento (`Redator`):** Consome o contexto operacional e sintetiza uma resposta humanizada diretamente para o cliente final, livre de jargões internos de infraestrutura, anexando um marcador técnico oculto de rastreabilidade.
3. **Agente Crítico — Auditor de Qualidade e Roteamento (`Auditor`):** Atua como *LLM-as-a-Judge* determinístico (`temperature = 0.0`). Inspeciona a saída do Redator contra os fragmentos originais do manual operacional, prevenindo alucinações, validando a citação de fonte e sinalizando a necessidade de transbordo (`requer_escalonamento`) caso o autoatendimento falhe ou o caso exija intervenção humana, respeitando o nível inicial definido pelo Classificador.

---

## 2. Recuperação Vetorial e *Context Slicing* (`src/rag/retriever.py`)

Para evitar o fenômeno de *Prompt Drift* e o vazamento de diretrizes internas de backoffice para o cliente final, o módulo `NexusRetriever` implementa a técnica de **Injeção de Contexto Seletivo (*Context Slicing*)** logo após a busca vetorial.

### 2.1. Parâmetros de Busca Vetorial
* **Modelo de Embeddings:** `nvidia/nemotron-3.5-embed-1b` configurado com `input_type="query"` (otimizado para buscas assimétricas em tempo real) e `encoding_format="float"`.
* **Cálculo de Similaridade e *Threshold*:** A distância de cosseno $d$ retornada pelo `PGVector` é convertida em score de similaridade normalizado $S = \max(0.0, 1.0 - d)$. Documentos com $S < 0.30$ (`min_similarity=0.30`) são descartados na origem, acionando o protocolo de contingência `[FORA_DE_ESCOPO]`.
* **Filtragem de Metadados:** A busca aplica pré-filtragem exata via JSONB no PostgreSQL (`filter={"category": category_filter}`), restringindo o espaço de busca vetorial à categoria identificada na triagem.

### 2.2. Particionamento Determinístico em Memória
Aproveitando a estrutura padronizada dos manuais gerados na Entrega 2, o método estático `_fatiar_conteudo()` aplica expressões regulares (`re.DOTALL | re.IGNORECASE`) para decompor o *chunk* atômico em três vetores textuais independentes sem custo adicional de chamadas de LLM:

| Variável Extraída | Padrão Regex Alvo | Finalidade na Engenharia de Contexto |
| :--- | :--- | :--- |
| `sintomas` | `\*\*Contexto e Sintomas.*?\*\*` | Registro contextual e diagnóstico do cenário. |
| `resolucao_n1` | `\*\*Resolução N1.*?\*\*` | Injetada como `<DIRETRIZES_DE_AUTOATENDIMENTO>` para guiar a resposta ao cliente. |
| `escalonamento` | `\*\*Critério de Escalonamento.*?\*\*` | Injetada como `<REGRAS_DE_ESCALONAMENTO_N2_N3>` para validação da necessidade de *handoff* pelo Auditor. |

---

## 3. Agente Redator N1 (`src/rag/prompts/redactor.py`)

O **Agente Redator** tem como objetivo traduzir procedimentos técnicos do ERP NexusTech em instruções claras, empáticas e naturais em Português do Brasil, mantendo fidelidade estrita à documentação recuperada.

### 3.1. Hiperparâmetros de Inferência
* **Modelo Base:** `nvidia/nemotron-3.5-lightning-30b-a3b`
* **Temperatura:** `0.1` (garante fluidez linguística com mínima variância criativa).
* **Controle de Latência (*Reasoning Override*):** `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`. A desativação de *tokens* de raciocínio prolongado (`<think>`) reduz o *Time-To-First-Token* (TTFT) e estabiliza a geração em ~2 a 3 segundos por chamada.
* **Desativação de Cache:** Para garantir o funcionamento do loop de autocorreção (*Actor-Critic*), o cache de execução e de memória das *Tasks* do Redator é desativado, forçando a reavaliação real do prompt a cada feedback negativo do Auditor.

### 3.2. Arquitetura de Prompt e *Guardrails*
O `REDATOR_SYSTEM_PROMPT` aplica restrições negativas (*Negative Constraints*) e roteamento condicional de discurso:

1. **Supressão de Rótulos Robóticos:** Proibição explícita de cabeçalhos de formulário (`Diagnóstico:`, `Passo a Passo:`, `Resolução N1:`), prevenindo a rejeição imediata do usuário por percepção de bot engessado.
2. **Prevenção de Alucinação Numérica e de Interface:** O agente é proibido de inferir valores monetários (`R$`), IDs de transação ou menus não declarados literalmente no bloco `<BASE_DE_CONHECIMENTO>`.
3. **Bifurcação Comportamental (Autoatendimento vs. Transbordo):**
   * **Caso A (Autoatendimento Viável):** O agente instrui o caminho de menu passo a passo e informa apenas os tempos de processamento sistêmico (ex: bloqueio automático em 5 minutos, validação de duplicidade em 15 minutos).
   * **Caso B (Falha Prévia Declarada ou Impedimento Técnico):** Quando o relato do cliente comprova que a ação N1 já falhou (ex: botão inexistente mesmo com e-mail validado) ou há bloqueio total de acesso (ex: perda de dispositivo 2FA sem códigos de backup), o Redator **não** repete instruções inócuas de painel; ele acolhe o usuário e informa o encaminhamento imediato a um especialista dedicado.
4. **Isolamento de Jargão Interno:** Mesmo ao comunicar uma transferência (Caso B), o Redator é impedido de expor nomenclaturas operacionais internas (`N1`, `N2`, `N3`, `Backoffice`, `Engenharia`) ou prometer SLAs de filas humanas ao cliente.

### 3.3. Pós-Processamento e Extração de Metadados (`separar_mensagem_e_fonte`)
Para conciliar a experiência conversacional limpa com a exigência de rastreabilidade técnica, o Redator é instruído a finalizar toda geração com a tag `[[FONTE: Chunk_ID]]`. A função `separar_mensagem_e_fonte()` executa a higienização em três saídas:

* `mensagem_cliente`: Texto final expurgado de tags `<think>` e do marcador `[[FONTE: ...]]`, pronto para renderização no chat do cliente.
* `fonte_citada`: Identificador exato do *chunk* extraído via Regex (`r"\[\[FONTE:\s*([^\]]+)\]\]"`), utilizado para validação de *grounding*.
* `texto_completo_auditoria`: Payload integral preservado para inspeção do Agente Auditor.

---

## 4. Agente Auditor de Qualidade e Validação de Transbordo (`src/rag/prompts/auditor.py`)

O **Agente Auditor** opera como camada de governança, conformidade (*compliance*) e validação da necessidade de transbordo pós-RAG. O Classificador é o único responsável pelo roteamento.

### 4.1. Hiperparâmetros de Inferência
* **Modelo Base:** `nvidia/nemotron-3.5-lightning-30b-a3b`
* **Temperatura:** `0.0` (máximo determinismo na avaliação lógica e geração de JSON).
* **Isolamento de Contexto:** Recebe simultaneamente `<MENSAGEM_DO_CLIENTE>`, `<DIRETRIZES_N1>`, `<REGRAS_DE_ESCALONAMENTO_N2_N3>` e `<RESPOSTA_DO_REDATOR>`.

### 4.2. Regras de Julgamento e Validação de Transbordo
Diferente do Redator (que foca na comunicação com o cliente), o Auditor aplica uma matriz de decisão para validar a necessidade de transbordo do chamado:

1. **Validação de Fidelidade (`redator_alucinou`):** Compara o rascunho com `<DIRETRIZES_N1>`. Qualquer invenção de menus, promessa de leitura de logs/bancos de dados no N1 ou suposição de valores não informados pelo cliente resulta em reprovação imediata (`aprovado_para_envio: false`).
2. **Validação de Rastreabilidade (`citou_fonte`):** Verifica a presença obrigatória da tag `[[FONTE: Chunk_ID]]` (ou `[[FONTE: FORA_DE_ESCOPO]]` quando a busca vetorial não retorna documentos acima do *threshold*).
3. **Validação de Escalonamento (`requer_escalonamento`):** Define como `false` quando o problema é resolvido no N1. Define como `true` quando a mensagem do cliente atinge gatilhos de escalonamento ou necessita de encaminhamento para a equipe especializada.
4. **Prevenção de Falso-Negativo em Casos de Escalonamento:** O prompt instrui explicitamente o Auditor a **aprovar** (`aprovado_para_envio: true`) respostas em que o Redator encaminhou corretamente o cliente para a equipe especializada devido a um gatilho legítimo de N2/N3, evitando loops infinitos de correção.

### 4.3. Contrato de Saída e *Fallback* Resiliente
O Auditor responde exclusivamente em formato JSON estruturado, validado contra o schema Pydantic `VereditoAuditorSchema`:

```json
{
  "analise_raciocinio": "1 frase explicando se a resposta respeitou o manual e justificando a necessidade ou não de transbordo.",
  "aprovado_para_envio": true,
  "redator_alucinou": false,
  "citou_fonte": true,
  "requer_escalonamento": false,
  "feedback_correcao": ""
}
```

A função `extrair_json_auditoria()` implementa sanitização de blocos Markdown (` ```json `) e extração via expressão regular (`r"\{.*\}"`), garantindo que, mesmo em caso de falha de formatação da LLM, o sistema retorne um dicionário padrão de *fallback* seguro (`aprovado_para_envio: False` e `requer_escalonamento: false`) com instruções claras para a rodada de autocorreção do Redator.