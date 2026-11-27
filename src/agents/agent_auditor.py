import os
from typing import Any
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.auditor import construir_prompt_auditor
from src.agents.parsers import extrair_json_auditoria
from src.agents.schemas import VereditoAuditorSchema
from src.agents.retry import executar_crew_com_retry

from src.agents.llm_factory import criar_llm

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteAuditorQualidade:
    """Agente autônomo responsável por auditar a resposta N1 e definir se requer escalonamento."""

    def __init__(self, model_name: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.llm = criar_llm(model_name, temperature=0.0)

    def executar(
        self,
        pergunta_cliente: str,
        resposta_redator: str,
        chunks: list[dict[str, Any]],
        historico_conversa: str = "",
        forcar_escalonamento_limite: bool = False,
    ) -> VereditoAuditorSchema:
        prompts = construir_prompt_auditor(
            pergunta_cliente=pergunta_cliente,
            resposta_redator=resposta_redator,
            chunks_fatiados=chunks,
            historico_conversa=historico_conversa,
            forcar_escalonamento_limite=forcar_escalonamento_limite,
        )

        agente = Agent(
            role="Auditor de Qualidade e Roteamento de Tickets",
            goal="Auditar fidelidade da resposta e definir se requer escalonamento (true ou false).",
            backstory=prompts["system_prompt"],
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=prompts["user_prompt"],
            expected_output="JSON válido contendo analise_raciocinio, aprovado_para_envio, redator_alucinou, citou_fonte, requer_escalonamento e feedback_correcao.",
            agent=agente,
        )

        crew = Crew(
            agents=[agente],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
        executar_crew_com_retry(crew)

        dict_auditoria = extrair_json_auditoria(task.output.raw)
        return VereditoAuditorSchema(**dict_auditoria)