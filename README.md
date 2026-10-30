# 🚀 NexusTech Support Copilot — Sistema Multi-Agente com RAG

Repositório oficial do projeto desenvolvido durante o **Programa de Capacitação em Sistemas Multi-Agentes com RAG**.  
Este projeto resolve o **Problema 1 (Copilot de Atendimento ao Cliente)** para a empresa fictícia **NexusTech Solutions** (SaaS B2B de ERP em nuvem).

---

## 🎯 Visão Geral do Projeto

O **NexusTech Support Copilot** é um sistema multi-agente orquestrado que auxilia atendentes de suporte N1 (e clientes via chat) na resolução rápida e padronizada de chamados. 

O sistema, desenhado para operar no padrão de chat contínuo com limite de tentativas, classifica automaticamente a intenção do usuário, realiza buscas semânticas em bases de conhecimento, redige respostas fundamentadas com citação de fontes, audita a qualidade da resposta (prevenindo alucinações) e elabora resumos executivos quando o chamado precisa ser escalado para especialistas técnicos.

---

## 🏗️ Stack Tecnológico Definido

| Camada | Tecnologia |
| :--- | :--- |
| **Orquestração Multi-Agente** | LangGraph |
| **Banco Vetorial & Relacional** | PostgreSQL + extensão `pgvector` |
| **Backend / API** | FastAPI + Pydantic |
| **Frontend** | Google Stitch (Prototipação) + React / Next.js |

---

## 📂 Estrutura Atual do Repositório

```text
nexustech-support-copilot/
├── docs/
│   ├── entendimento_problema.md       # Entregável 1.1: Contexto, dores, personas e KPIs
│   ├── arquitetura_stack.md         # Entregáveis 1.2 a 1.4: Arquitetura, Dados e Stack
│   └── diagrama.jpeg               # Entregável 1.2: Diagrama visual
└── README.md                             # Documentação principal e roadmap
```
*(Nota: Diretórios de código-fonte, dados e infraestrutura serão adicionados a partir da Entrega 2).*

---

## 📅 Cronograma e Status das Entregas (Backlog)

- [x] **Entrega 1 (24/10) — Planejamento e Design do Sistema**
  - [x] 1.1 Documento de entendimento do problema
  - [x] 1.2 Proposta de arquitetura e fluxo de orquestração
  - [x] 1.3 Mapeamento e avaliação dos datasets
  - [x] 1.4 Definição do stack técnico
  - [x] 1.5 Inicialização e estruturação do repositório GitHub
- [ ] **Entrega 2 (31/10) — Infraestrutura e Ingestão de Dados**
  - [ ] Setup do ambiente e banco PostgreSQL + `pgvector`
  - [ ] Pipeline de ingestão, limpeza e geração de embeddings
- [ ] **Entrega 3 (07/11) — Pipeline RAG Funcional**
  - [ ] Módulo de retrieval e conexão com a LLM
- [ ] **Entrega 4 (14/11) — Primeiro Agente Funcional**
  - [ ] Implementação isolada e testes com *tools*
- [ ] **Entrega 5 (21/11) — Sistema Multi-Agente Orquestrado**
  - [ ] Integração dos agentes e configuração de estado/loops no LangGraph
- [ ] **Entrega 6 (28/11) — API e Interface do Usuário**
  - [ ] Exposição de rotas FastAPI e integração com Frontend
- [ ] **Entrega 7 (05/12) — Testes, Avaliação e Documentação**
  - [ ] Aferição de métricas e testes end-to-end
- [ ] **Apresentação Final (12/12) — Showcase**
