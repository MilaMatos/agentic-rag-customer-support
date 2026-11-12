import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.summarizer import construir_prompt_resumo
from src.agents.parsers import limpar_texto_resumo

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteResumo:
    """Agente autônomo responsável por gerar o resumo executivo interno do atendimento"""

    def __init__(self, model_name: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.llm = LLM(
            model=model_name,
            custom_openai=True,
            base_url=BASE_URL,
            api_key=API_KEY,
            temperature=0.0,
            max_tokens=512,
            additional_params={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
            timeout=30,
        )

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

        crew = Crew(
            agents=[agente],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
        crew.kickoff()

        return limpar_texto_resumo(task.output.raw)