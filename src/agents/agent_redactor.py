import os
from typing import Any, Optional
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.redactor import construir_prompt_redator
from src.agents.parsers import separar_mensagem_e_fonte

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteRedatorN1:
    """Agente autônomo responsável pela redação humanizada N1."""

    def __init__(self, model_name: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.llm = LLM(
            model=model_name,
            custom_openai=True,
            base_url=BASE_URL,
            api_key=API_KEY,
            temperature=0.1,
            max_tokens=1024,
            additional_params={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
            timeout=30,
        )

    def executar(
        self,
        pergunta_cliente: str,
        chunks: list[dict[str, Any]],
        feedback_anterior: Optional[str] = None,
    ) -> dict[str, str]:
        prompts = construir_prompt_redator(
            pergunta_cliente=pergunta_cliente,
            chunks_fatiados=chunks,
            feedback_auditor=feedback_anterior,
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

        crew = Crew(
            agents=[agente],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
        crew.kickoff()

        return separar_mensagem_e_fonte(task.output.raw)