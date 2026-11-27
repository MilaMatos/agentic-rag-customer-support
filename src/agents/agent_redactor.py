import logging
from typing import Any, Optional
from crewai import Agent, Task, Crew, Process

from src.agents.llm_factory import LLMConfig, criar_llms_agente
from src.agents.parsers import separar_mensagem_e_fonte
from src.agents.prompts.redactor import construir_prompt_redator
from src.agents.retry import executar_crew_com_retry

logging.getLogger("crewai.llms.base_llm").setLevel(logging.ERROR)


class AgenteRedatorN1:
    """Responsável pela redação humanizada ancorada nos manuais"""

    def __init__(self, model_name: Optional[str | LLMConfig | dict[str, Any]] = None):
        self.llm, self.fallback_llm = criar_llms_agente("redactor", model_name, temperature=0.1)

    def executar(
        self,
        pergunta_cliente: str,
        chunks: Optional[list[dict[str, Any]]] = None,
        feedback_anterior: Optional[str] = None,
        categoria: str = "",
        historico_conversa: str = "",
        forcar_escalonamento_limite: bool = False,
    ) -> dict[str, str]:
        prompts = construir_prompt_redator(
            pergunta_cliente=pergunta_cliente,
            chunks_fatiados=chunks,
            feedback_auditor=feedback_anterior,
            categoria_sugerida=categoria,
            historico_conversa=historico_conversa,
            forcar_escalonamento_limite=forcar_escalonamento_limite,
        )

        agente = Agent(
            role="Especialista de Atendimento (Redator)",
            goal="Produzir resposta clara e fiel à base de conhecimento para o cliente.",
            backstory=prompts["system_prompt"],
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=prompts["user_prompt"],
            expected_output="Resposta ao cliente contendo a tag [[FONTE: Chunk_ID]] na última linha.",
            agent=agente,
        )

        crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
        executar_crew_com_retry(crew, fallback_llm=self.fallback_llm)

        return separar_mensagem_e_fonte(task.output.raw)