# Entrega 2 (Parte 1): Engenharia de Dados, Diagnóstico de Datasets e Síntese de Base de Conhecimento (KB)

**Projeto:** NexusTech Support Copilot (B2B ERP SaaS)  
**Módulo:** `src/ingestion/` (`ingestion_pipeline.py`, `chunking_strategy.py`, `export_manuals.py`)

---

## 1. Anatomia e Diagnóstico Comparativo dos Datasets

Durante a fase exploratória, avaliamos dois datasets públicos de suporte ao cliente para compor a base de testes e orientar a criação da Base de Conhecimento (KB). A investigação revelou que ambos possuem **alta volumetria superficial**, mas são construídos a partir de um conjunto reduzido de intenções reais.

### 1.1. Comparativo Estrutural: Bitext vs. CRM Tickets

| Dimensão Analisada | Dataset 1: Bitext Customer Support | Dataset 2: CRM `customer_support_tickets.csv` (Escolhido) |
| :--- | :--- | :--- |
| **Volume Bruto** | 26.872 registros | 20.000 registros |
| **Categorias Macro** | 11 categorias (`ORDER`, `REFUND`, `SHIPPING`, etc.) | 5 categorias (`Account`, `Billing`, `Technical`, `Fraud`, `General Inquiry`) |
| **Intenções / Perguntas Únicas Reais** | **27 intenções base** (*intents*) | **30 perguntas base** (exatamente 6 por categoria) |
| **Mecanismo de Geração Sintética** | **Variação Linguística:** Reescreve as mesmas 27 intenções de milhares de formas usando *flags* estilísticas (formal, informal, erros de digitação, linguagem coloquial). | **Injeção de Ruído (Lorem Ipsum):** Sorteia uma das 30 frases reais de um ERP B2B, adiciona a saudação `"Hi Support,"` no início e concatena frases aleatórias sem sentido em inglês após o ponto final. |
| **Adequação ao Domínio NexusTech** | Focado em varejo/e-commerce B2C (rastreio de pacotes, troca de produtos físicos). | Focado em **SaaS / ERP B2B** (erros de API 500, sincronização, 2FA, planos Enterprise, faturas contratuais). |

### 1.2. Descoberta Crítica: O Problema de *Semantic Drift* no `Ticket_Subject`
Ao inspecionar profundamente o Dataset 2 (`customer_support_tickets.csv`), identificamos duas anomalias importantes de qualidade de dados:
1. **Incompatibilidade entre Categoria e Subcategoria:** Parte dos registros apresentava `Ticket_Subject` pertencente a uma categoria diferente de `Issue_Category` (tratado no script de limpeza via filtro de validação).
2. **Desacoplamento entre `Ticket_Subject` e `Ticket_Description`:** O gerador sintético original do CSV sorteava a coluna `Ticket_Subject` (ex: `Subscription upgrade`) de forma independente da frase real em `Ticket_Description` (ex: *"How do I update my profile picture?"*).
   * **Impacto:** Quando utilizamos o agrupamento direto por `Ticket_Subject` nas primeiras iterações, a LLM recebia um título de "Upgrade de Assinatura" junto com uma pergunta sobre "Foto de Perfil", gerando manuais com alucinação cruzada.
   * **Solução de Engenharia:** Mapeamos as **30 perguntas únicas reais** após a limpeza textual e estabelecemos um **Catálogo Canônico (`CATALOGO_CANONICO`)** com 30 subcategorias padronizadas em português, garantindo alinhamento 1:1 entre o problema do usuário e a seção do manual.

---

## 2. Pipeline de Higienização e Validação (`ingestion_pipeline.py`)

O script `src/ingestion/ingestion_pipeline.py` executa o pré-processamento determinístico do dataset bruto (`data/raw/customer_support_tickets.csv`) para gerar a base limpa (`data/cleaned/tickets.csv`):

* **Anonimização (LGPD / Privacidade):** Remoção imediata de colunas contendo PII (`Customer_Name` e `Customer_Email`).
* **Extração Cirúrgica da Query (`limpar_texto`):**
  * Remoção da saudação padrão `Hi Support,` via expressão regular (`(?i)^\s*hi support,\s*`).
  * Corte na primeira pontuação terminal (`^.*?[.!?](?=\s|$)`), descartando integralmente o ruído sintético (*Lorem Ipsum*) concatenado ao final dos chamados.

---

## 3. Fundamentação Científica para Geração da Base de Conhecimento (Pseudo-Documentos)

Como datasets públicos de tickets fornecem apenas a **pergunta do cliente** (sem os manuais internos da empresa), embasamos a construção da nossa Base de Conhecimento Sintética em dois artigos de referência na literatura de Recuperação de Informação (IR) e RAG:

1. **[Query2doc: Query Expansion with Large Language Models](https://arxiv.org/pdf/2303.07678) (Microsoft Research — Wang et al., EMNLP 2023):**
   - **Conceito:** Demonstra que expandir queries curtas em "pseudo-documentos" densos gerados por LLMs aumenta drasticamente a precisão de recuperadores densos e esparsos, preenchendo o *lexical gap* entre a linguagem do usuário (sintoma) e a linguagem técnica (solução).

2. **[From Unstructured Communication to Intelligent RAG: Multi-Agent Automation for Supply Chain Knowledge Bases](https://www.researchgate.net/publication/392942571_From_Unstructured_Communication_to_Intelligent_RAG_Multi-Agent_Automation_for_Supply_Chain_Knowledge_Bases) (Amazon — KDD 2025):**
   - **Conceito:** Propõe um pipeline multi-etapa para transformar históricos de chamados em artigos estruturados de base de conhecimento corporativa, separando a descoberta de subcategorias (*Category Discovery*) da síntese estruturada de procedimentos operacionais (*Knowledge Synthesis*).

---

## 4. Arquitetura de Síntese de Manuais (`chunking_strategy.py` e `export_manuals.py`)

Aplicando os princípios do *Query2doc* e da arquitetura da Amazon, estruturamos a geração dos manuais operacionais no script `src/ingestion/chunking_strategy.py` utilizando **CrewAI** + **NVIDIA NIM (`nvidia/nemotron-3.5-lightning-30b-a3b`)**.

### 4.1. Decisões de Engenharia na Geração
* **Estrutura Tripartida Obrigatória por Subcategoria (`### <Subcategoria>`):**
  * `**Contexto e Sintomas:**` Ancora o vocabulário do problema relatado pelo cliente para maximizar o *match* semântico no RAG.
  * `**Resolução N1 (Autoatendimento e Políticas):**` Define caminhos exatos de tela no ERP NexusTech, SLAs e políticas financeiras/operacionais. Impõe a regra estrita de negócio: **o N1 é 100% autoatendimento e nunca acessa logs ou bancos de dados**.
  * `**Critério de Escalonamento (N2 / N3):**` Fornece regras determinísticas de transbordo para N2 (Backoffice/Análise Cadastral) e N3 (Engenharia/Segurança/Infraestrutura), essenciais para os futuros Agentes Auditor e de Resumo.

### 4.2. Catálogo Canônico Mapeado (30 Subcategorias)

| Categoria (`doc_id`) | Subcategorias Padronizadas Geradas (`###`) |
| :--- | :--- |
| **Account** (`MAN-ACCO-001`) | `Falha no 2FA`, `Perda de Dispositivo 2FA`, `Redefinicao de Senha`, `Upgrade Enterprise`, `Foto de Perfil`, `Exclusao de Conta` |
| **Billing** (`MAN-BILL-001`) | `Status de Reembolso`, `Atualizacao de Pagamento`, `Divergencia na Fatura`, `Segunda Via de Fatura`, `Cancelamento e Renovacao`, `Cobranca Duplicada` |
| **Technical** (`MAN-TECH-001`) | `Falha de Sincronizacao`, `Erro 500 no Login`, `Travamento do Dashboard`, `Integracao de API`, `Instalacao de Patch`, `Fechamento nas Configuracoes` |
| **Fraud** (`MAN-FRAU-001`) | `Tentativa de Phishing`, `Cartao Roubado`, `Conta Invadida`, `Dispositivo Desconhecido`, `Alerta de Seguranca`, `Transacao Suspeita` |
| **General Inquiry** (`MAN-GENE-001`) | `Horario de Atendimento`, `Endereco da Sede`, `Desconto para ONGs`, `Roadmap de Produto`, `Solicitacao de Demo`, `Planos e Precos` |

### 4.3. Exportação Dual: JSON Estruturado e Markdown Legível (`export_manuals.py`)
* Os 5 arquivos JSON consolidados são armazenados em `data/knowledge_base/json/base_conhecimento_<categoria>.json` para consumo direto pelo pipeline vetorial.
* O utilitário `src/ingestion/export_manuals.py` lê os JSONs e exporta versões em Markdown puro (`data/knowledge_base/manuals/manual_<categoria>.md`), permitindo inspeção humana imediata e auditoria de qualidade da documentação.