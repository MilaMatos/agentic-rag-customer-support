# Entrega 1.1 — Documento de Entendimento do Problema
**Projeto:** NexusTech Support Copilot (Sistema Multi-Agente com RAG)  
**Empresa Fictícia:** NexusTech Solutions (SaaS B2B — ERP em Nuvem)  
**Área de Negócio:** Customer Support (Atendimento ao Cliente N1, N2 e N3)

---

## 1. Contexto de Negócio
A **NexusTech Solutions** é uma empresa de SaaS B2B que fornece uma plataforma de gestão empresarial (ERP em nuvem) para **15.000 clientes ativos**. Para manter a operação, a empresa conta com uma estrutura de suporte técnico e operacional composta por **80 atendentes**, divididos em três níveis de complexidade:
* **Nível 1 (N1):** Triagem inicial, dúvidas de uso, procedimentos padrão e problemas recorrentes documentados.
* **Nível 2 (N2):** Configurações avançadas, análise de integrações e incidentes funcionais não triviais.
* **Nível 3 (N3):** Engenharia de suporte, bugs críticos de código, problemas de banco de dados e infraestrutura.

---

## 2. Personas e Usuários do Sistema

### 2.1 Usuário Primário: Atendente de Suporte N1 (Modo Copilot)
* **Perfil:** Profissional responsável pela linha de frente do atendimento (chat, e-mail e tickets). Alta pressão por velocidade de resposta e baixo tempo de treinamento devido ao *turnover* natural da área.
* **Rotina Atual:** Precisa alternar manualmente entre CRM, Wiki interna, manuais de produto em PDF e histórico de tickets antigos para encontrar respostas.
* **O que espera do sistema:** Receber automaticamente a classificação do chamado, uma sugestão de resposta pronta e fundamentada nos manuais oficiais, e a indicação clara das fontes (rastreabilidade) para validar e responder em poucos segundos.

### 2.2 Usuário Secundário: Cliente Final B2B (Modo Auto-Atendimento / Chat)
* **Perfil:** Operador financeiro, analista contábil ou gestor que utiliza o ERP da NexusTech no dia a dia.
* **Rotina Atual:** Abre chamados para dúvidas operacionais simples e aguarda longos períodos por uma resposta padronizada, ou recebe orientações contraditórias dependendo de qual atendente assume o ticket.
* **O que espera do sistema:** Resolução rápida em poucos turnos de conversa para dúvidas conhecidas, ou encaminhamento ágil para um especialista humano (N2/N3) sem precisar repetir todo o problema do zero.

### 2.3 Usuário Beneficiário: Especialista N2 / N3 (Receptor do Escalonamento)
* **Perfil:** Analista técnico sênior.
* **Dor Atual:** Perde até 40% do tempo atendendo chamados que deveriam ter sido resolvidos no N1 ou lendo históricos longos e confusos para entender o que já foi tentado.
* **O que espera do sistema:** Receber apenas chamados realmente complexos, acompanhados de um **Resumo Executivo de Handoff** (o que o cliente pediu, quais artigos já foram tentados pelo Copilot e por que o caso foi escalado).

---

## 3. Diagnóstico das Dores Críticas

1. **Alto volume de tickets repetitivos:** Grande parte da demanda refere-se a dúvidas já documentadas em FAQs e manuais, mas subutilizadas por dificuldade de busca.
2. **Tempo Médio de Atendimento (TMA) elevado (12 min):** O tempo é consumido majoritariamente na pesquisa manual em múltiplos sistemas fragmentados.
3. **Inconsistência nas respostas:** Falta de padronização gera respostas diferentes para o mesmo problema, causando retrabalho e queda de confiança.
4. **Escalonamento desnecessário (38%):** Pela dificuldade de encontrar o procedimento correto rapidamente, o N1 transfere tickets simples para N2/N3, inflando o custo operacional.
5. **Ausência de rastreabilidade e memória de sessão:** Não há registro estruturado de qual documento fundamentou cada resposta dada, dificultando auditorias de qualidade e melhoria contínua da base de conhecimento.

---

## 4. Resultado Esperado e Escopo da Solução

Construir um **Copilot de Atendimento ao Cliente baseado em Arquitetura Multi-Agente e RAG (Retrieval-Augmented Generation)** operando no padrão **Bounded Multi-Turn (Chat Contínuo com Limite de Turnos)**.

### Capacidades Essenciais:
* **Compreensão e Triagem Contextual:** Identificar a intenção do usuário (seja na abertura do ticket ou em mensagens subsequentes de continuação/mudança de assunto) e classificar categoria, prioridade e nível sugerido.
* **Recuperação Semântica (RAG):** Consultar o banco vetorial (PG Vector) para extrair os artigos de base de conhecimento e padrões de resolução mais aderentes.
* **Geração Fundamentada:** Redigir respostas claras e estritamente ancoradas nos documentos recuperados, citando o ID da fonte utilizada.
* **Auditoria Automática (Guardrail) e Limite de Turnos:** Avaliar a qualidade e a confiança da resposta antes da exibição. Permitir a continuação da conversa em múltiplos turnos, mas acionar o escalonamento automático caso a confiança seja baixa ou o limite de tentativas para o mesmo problema seja atingido.
* **Handoff Inteligente para N2/N3:** Gerar automaticamente um resumo consolidado da sessão e anexar o log de rastreabilidade quando houver escalonamento humano.

---

## 5. Métricas de Sucesso (KPIs de Negócio e Técnicos)

| Indicador (KPI) | Baseline Atual | Meta com o Copilot | Impacto Esperado |
| :--- | :---: | :---: | :--- |
| **Tempo Médio de Resposta (TMA)** | 12 min | **< 4 min** | Redução de 66% no tempo operacional por ticket |
| **Taxa de Resolução em N1 (FCR)** | 45% | **> 75%** | Maior autonomia da linha de frente |
| **NPS do Suporte** | 32 | **> 55** | Aumento da satisfação e redução do risco de *churn* |
| **Escalonamento Indevido (N1 $\rightarrow$ N2/N3)** | 38% | **< 15%** | Liberação da agenda dos especialistas N2/N3 |