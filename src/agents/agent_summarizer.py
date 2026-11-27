from typing import Any, Optional
from crewai import Agent, Task, Crew, Process

from src.agents.llm_factory import LLMConfig, criar_llms_agente
from src.agents.parsers import limpar_texto_resumo
from src.agents.prompts.summarizer import construir_prompt_resumo
from src.agents.retry import executar_crew_com_retry


class AgenteResumo:
    """Gera dossiê de handoff para especialistas e compacta tópicos extensos em background"""

    def __init__(self, model_name: Optional[str | LLMConfig | dict[str, Any]] = None):
        self.llm, self.fallback_llm = criar_llms_agente("summarizer", model_name, temperature=0.0)

    def executar(self, resposta_final_cliente: str) -> str:
        prompts = construir_prompt_resumo(resposta_final_cliente)

        agente = Agent(
            role="Analista de Handoff e Qualidade",
            goal="Extrair os pontos críticos da resposta gerada para o histórico interno do ticket.",
            backstory=prompts["system_prompt"],
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=prompts["user_prompt"],
            expected_output="Resumo executivo de duas linhas (Ação Tomada e Próximo Passo).",
            agent=agente,
        )

        crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
        executar_crew_com_retry(crew, fallback_llm=self.fallback_llm)

        return limpar_texto_resumo(task.output.raw)

    def resumir_topico(
        self,
        categoria: str,
        transcricao_topico: str,
        resumo_anterior: str = "",
    ) -> str:
        bloco_previo = f"Resumo anterior:\n{resumo_anterior}\n\n" if resumo_anterior else ""
        prompt = (
            f"Compacte a conversa abaixo sobre o tópico '{categoria}' em 2 a 4 frases objetivas.\n"
            f"Preserve fatos técnicos, sintomas, testes já feitos pelo cliente (incluindo confirmações de sim/não) e pendências.\n"
            f"Ignore saudações e preenchimentos sem valor técnico.\n\n"
            f"{bloco_previo}Novas mensagens:\n{transcricao_topico}"
        )

        agente = Agent(
            role="Analista de Memória Conversacional",
            goal="Condensar histórico de um tópico preservando todos os fatos técnicos.",
            backstory="Você resume atendimentos de suporte técnico de forma concisa, fiel e sem inventar dados.",
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=prompt,
            expected_output="Resumo factual curto (2 a 4 frases) em português.",
            agent=agente,
        )

        crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
        executar_crew_com_retry(crew, fallback_llm=self.fallback_llm)
        return limpar_texto_resumo(task.output.raw)