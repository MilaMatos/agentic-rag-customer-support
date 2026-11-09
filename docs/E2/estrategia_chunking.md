# Entrega 2 (Parte 2): Estratégia de Chunking, Embeddings Assíncronos e Persistência no PGVector

**Projeto:** NexusTech Support Copilot (B2B ERP SaaS)  
**Módulo:** `src/ingestion/vector_pipeline.py` e `docker-compose.yml`

---

## 1. Pesquisa e Seleção da Estratégia de Segmentação (Chunking)

A escolha da estratégia de *chunking* define a qualidade do contexto entregue aos agentes do sistema RAG. Realizamos uma revisão técnica das principais abordagens do mercado — incluindo o benchmark oficial da **NVIDIA Developer Blog** (*"Finding the Best Chunking Strategy for Accurate AI Responses"*) — para selecionar o método mais aderente aos manuais operacionais da NexusTech.

### 1.1. Análise Comparativa das Estratégias Avaliadas

| Estratégia de Chunking | Funcionamento Técnico | Vantagens | Limitações no Contexto NexusTech |
| :--- | :--- | :--- | :--- |
| **Fixed-Size / Sliding Window** | Corta o texto rigidamente a cada $N$ tokens/caracteres com sobreposição (*overlap*) fixa. | Simples e previsível em consumo de memória. | **Alto risco de quebra de regra:** Pode separar o sintoma do cliente da regra de escalonamento N2/N3, induzindo o Agente Auditor ao erro. |
| **Recursive Character** | Quebra hierarquicamente por parágrafos (`\n\n`), linhas (`\n`) e espaços até atingir um limite de tokens. | Respeita fronteiras naturais de frases e parágrafos. | Não compreende a hierarquia lógica de um manual; pode juntar o final de uma subcategoria com o início da próxima. |
| **Semantic Chunking** | Calcula embeddings frase a frase e corta o texto quando a distância de cosseno entre sentenças adjacentes supera um limiar. | Excelente para textos corridos sem formatação ou transcrições longas. | **Inadequado para manuais normativos:** Como o vocabulário muda abruptamente entre "Sintomas do Usuário" e "Regras de Escalonamento Backoffice", o corte semântico fragmentaria a mesma subcategoria em vários pedaços incompletos. |
| **Section-Level Chunking (Escolhida)** | Divide o documento guiado por marcadores estruturais explícitos da árvore Markdown (`#` e `###`). | **Preserva unidades lógicas completas:** Garante que Causa (Sintoma), Ação (N1) e Transbordo (N2/N3) permaneçam blindados no mesmo chunk. | Exige que os documentos de origem possuam formatação consistente (requisito 100% atendido pela nossa geração estruturada). |

### 1.2. Justificativa do Section-Level Chunking (com base no Benchmark NVIDIA)
O estudo da NVIDIA destaca que estratégias orientadas à estrutura física/lógica do documento (*Page-level* e *Section-level*) superam recortes arbitrários quando os documentos possuem escopo bem delimitado, pois fornecem contexto suficiente para a LLM raciocinar sem diluir a densidade do vetor.

Como nossos manuais sintéticos já nascem formatados sob rígida hierarquia Markdown (`# Manual` $\rightarrow$ `### Subcategoria`), implementamos o `MarkdownHeaderTextSplitter` (com `strip_headers=False`) no script `vector_pipeline.py`:
* **Preservação do Cabeçalho no Corpo do Vetor:** Manter `### <Subcategoria>` na primeira linha do `page_content` reforça o peso semântico do tópico durante o cálculo do embedding.
* **Granularidade Exata:** Os 5 manuais JSON são segmentados em **35 chunks atômicos** (7 seções por manual: 1 seção introdutória + 6 subcategorias operacionais), identificados de forma única no padrão `MAN-<CAT>-001-SEC-01` a `SEC-07`.

---

## 2. Engenharia de Vetorização com NVIDIA NIM (`vector_pipeline.py`)

A geração dos vetores e a persistência no banco de dados foram consolidadas no script `src/ingestion/vector_pipeline.py`, projetado com foco em **tolerância a falhas e integridade transacional**.

### 2.1. Modelo de Embedding e Descobertas de Integração na API NVIDIA NIM
* **Depreciação de Modelos Legados (HTTP 410):** Durante os testes, identificamos que o modelo `nvidia/nv-embedqa-e5-v5` atingiu *End-of-Life* (HTTP 410 Gone). Migramos para o modelo oficial de última geração **`nvidia/nemotron-3.5-embed-1b`**, que gera vetores densos de **2.048 dimensões**.
* **Assimetria Semântica (`input_type`):** Modelos de RAG da arquitetura NVIDIA exigem diferenciação explícita entre o que está sendo indexado e o que está sendo buscado:
  * Documentos indexados utilizam `input_type="passage"`.
  * Consultas de usuários em tempo de execução utilizam `input_type="query"`.
* **Contorno de Limitações do SDK Padrão (`NvidiaNimEmbeddings`):**
  * A classe padrão `OpenAIEmbeddings` do LangChain envia automaticamente `encoding_format="base64"` quando a validação de contexto local é desativada, além de agrupar múltiplos documentos na mesma chamada — comportamento que causava `HTTP 500 (service inference failed)` no servidor da NVIDIA para o modelo `nemotron-3.5-embed-1b`.
  * **Solução Implementada:** Criamos a classe customizada `NvidiaNimEmbeddings` herdando diretamente de `langchain_core.embeddings.Embeddings`, forçando `encoding_format="float"`, requisições unitárias (`_embed_one`), verificação estrita de dimensionalidade (`EXPECTED_EMBEDDING_DIMENSION = 2048`) e *retry* com *exponential backoff* para códigos `429` e `5xx`.

---

## 3. Persistência no PostgreSQL (`pgvector`) e Segurança Operacional

A camada de armazenamento vetorial roda em container Docker (`nexus_pgvector` na porta `5432`, banco `nexus_knowledge`) integrado via driver moderno **`psycopg 3`** (`postgresql+psycopg://`).

### 3.1. Arquitetura de Ingestão em 5 Estágios (`processar_e_injetar_vetores`)
1. **Estágio 1 — *Health Check* do Modelo (`validar_modelo`):** Antes de processar os arquivos, dispara uma requisição de teste na NVIDIA NIM e valida se o vetor retornado possui exatamente 2.048 dimensões.
2. **Estágio 2 — Carregamento e Section-Level Chunking (`carregar_e_fatiar_manuais`):** Lê os 5 JSONs em `data/knowledge_base/json/`, higieniza divisores visuais e gera os objetos `Document` enriquecidos com metadados JSONB (`chunk_id`, `doc_id`, `category`, `subcategory`, `source`, `source_file`).
3. **Estágio 3 — Pré-Cálculo Completo em Memória (`gerar_embeddings_individuais`):** Calcula todos os 35 vetores antes de abrir transação destrutiva no banco de dados. Se a API externa falhar de forma irrecuperável no chunk 20, o banco de dados existente permanece intacto.
4. **Estágio 4 — Escrita em Lotes no PGVector (`armazenar_no_pgvector`):** Com todos os vetores validados em memória, inicializa a coleção `nexus_knowledge_base` (com `pre_delete_collection=True` para evitar duplicatas) e insere os vetores pré-calculados via `add_embeddings` em lotes de 10 registros (`DB_INSERT_BATCH_SIZE = 10`).
5. **Estágio 5 — Teste Automatizado de Recuperação (`testar_recuperacao`):** Executa uma busca semântica de validação (`similarity_search_with_score`) com a query em inglês `"The dashboard is not loading any data, just a spinning wheel."`, comprovando a capacidade *cross-lingual* do modelo `nemotron-3.5-embed-1b` ao recuperar os chunks técnicos em português no Top-K.

---

## 4. Estrutura Final do Repositório (Entrega 2)

```text
AGENT/
├── data/
│   ├── cleaned/
│   │   └── tickets.csv                        # Chamados higienizados, sem PII e sem Lorem Ipsum
│   └── knowledge_base/
│       ├── json/                              # Fonte estruturada para o pipeline vetorial
│       │   ├── base_conhecimento_account.json
│       │   ├── base_conhecimento_billing.json
│       │   ├── base_conhecimento_fraud.json
│       │   ├── base_conhecimento_general_inquiry.json
│       │   └── base_conhecimento_technical.json
│       └── manuals/                           # Manuais exportados em Markdown para leitura/auditoria
│           ├── manual_account.md
│           ├── manual_billing.md
│           ├── manual_fraud.md
│           ├── manual_general_inquiry.md
│           └── manual_technical.md
├── docs/
│   ├── E1/                                    # Entregáveis da Semana 1
│   └── E2/                                    # Entregáveis da Semana 2
│       ├── pesquisa_dados_e_kb.md
│       ├── estrategia_chunking_e_vetorizacao.md
│       └── apresentacao_E2.html
├── src/
│   └── ingestion/
│       ├── ingestion_pipeline.py              # Limpeza de texto, LGPD e validação de categorias
│       ├── chunking_strategy.py               # Síntese da KB via CrewAI + Catálogo Canônico
│       ├── export_manuals.py                  # Conversor JSON -> Markdown
│       └── vector_pipeline.py                 # Section-Level Chunking + NVIDIA NIM + PGVector
├── docker-compose.yml                         # Container PostgreSQL + pgvector
└── requirements.txt