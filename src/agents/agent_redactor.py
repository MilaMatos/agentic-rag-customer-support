import logging
import os
from typing import Any, Optional
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.redactor import construir_prompt_redator
from src.agents.parsers import separar_mensagem_e_fonte
from src.agents.tools import buscar_manual_rag_tool
from src.agents.retry import executar_crew_com_retry

from src.agents.llm_factory import criar_llm

load_dotenv()
logging.getLogger("crewai.llms.base_llm").setLevel(logging.ERROR)

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteRedatorN1:
    """Agente autônomo responsável pela redação humanizada N1."""

    def __init__(self, model_name: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.llm = criar_llm(model_name, temperature=0.1)
        self.tools = [buscar_manual_rag_tool]

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

        ferramentas_ativas = self.tools if chunks is None else []

        agente = Agent(
            role="Especialista de Atendimento (Redator)",
            goal="Produzir resposta clara e fiel à base de conhecimento para o cliente.",
            backstory=prompts["system_prompt"],
            llm=self.llm,
            tools=ferramentas_ativas,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=prompts["user_prompt"],
            expected_output="Resposta ao cliente contendo a tag [[FONTE: Chunk_ID]] na última linha.",
            agent=agente,
        )

        crew = Crew(
            agents=[agente],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
        executar_crew_com_retry(crew)

        return separar_mensagem_e_fonte(task.output.raw)