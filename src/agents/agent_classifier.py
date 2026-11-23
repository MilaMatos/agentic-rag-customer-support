import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.classifier import construir_prompt_classificador
from src.agents.parsers import extrair_json_classificacao
from src.agents.schemas import TicketClassification

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteClassificador:
    """Agente autônomo responsável pela triagem e classificação inicial do ticket."""

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

    def executar(
        self,
        pergunta_cliente: str,
        historico_recente: str = "",
        categoria_anterior: str = "",
    ) -> TicketClassification:
        prompts = construir_prompt_classificador(
            pergunta_cliente=pergunta_cliente,
            historico_recente=historico_recente,
            categoria_anterior=categoria_anterior,
        )

        agente = Agent(
            role="Especialista em Triagem de Suporte B2B",
            goal="Analisar o ticket do cliente e classificá-lo na taxonomia da empresa.",
            backstory=prompts["system_prompt"],
            llm=self.llm,
            verbose=False,
            allow_delegation=False,
        )

        task = Task(
            description=prompts["user_prompt"],
            expected_output=(
                'JSON válido contendo exatamente as chaves: '
                '"category", "priority", "initial_level", "triage_justification", '
                '"is_followup" (boolean) e "search_query" (string).'
            ),
            agent=agente,
        )

        crew = Crew(
            agents=[agente],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
        crew.kickoff()

        dados_dict = extrair_json_classificacao(task.output.raw)
        return TicketClassification(**dados_dict)