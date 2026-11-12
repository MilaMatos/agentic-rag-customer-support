import os
from typing import Any
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.auditor import construir_prompt_auditor
from src.agents.parsers import extrair_json_auditoria
from src.agents.schemas import VereditoAuditorSchema

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteAuditorQualidade:
    """Agente autônomo responsável por auditar a resposta N1 e definir se requer escalonamento."""

    def __init__(self, model_name: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.llm = LLM(
            model=model_name,
            custom_openai=True,
            base_url=BASE_URL,
            api_key=API_KEY,
            temperature=0.0,
            max_tokens=1024,
            additional_params={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
            timeout=30,
        )

    def executar(
        self,
        pergunta_cliente: str,
        resposta_redator: str,
        chunks: list[dict[str, Any]],
    ) -> VereditoAuditorSchema:
        prompts = construir_prompt_auditor(
            pergunta_cliente=pergunta_cliente,
            resposta_redator=resposta_redator,
            chunks_fatiados=chunks,
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
        crew.kickoff()

        dict_auditoria = extrair_json_auditoria(task.output.raw)
        return VereditoAuditorSchema(**dict_auditoria)