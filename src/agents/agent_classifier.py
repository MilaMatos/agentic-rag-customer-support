from typing import Any, Optional
from crewai import Agent, Task, Crew, Process

from src.agents.llm_factory import LLMConfig, criar_llms_agente
from src.agents.parsers import extrair_json_classificacao
from src.agents.prompts.classifier import construir_prompt_classificador
from src.agents.retry import executar_crew_com_retry
from src.agents.schemas import TicketClassification


class AgenteClassificador:
    """Responsável pela triagem, roteamento de tópico e categoria"""

    def __init__(self, model_name: Optional[str | LLMConfig | dict[str, Any]] = None):
        self.llm, self.fallback_llm = criar_llms_agente("classifier", model_name, temperature=0.0)

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

        crew = Crew(agents=[agente], tasks=[task], process=Process.sequential, verbose=False)
        executar_crew_com_retry(crew, fallback_llm=self.fallback_llm)

        dados_dict = extrair_json_classificacao(task.output.raw)
        return TicketClassification(**dados_dict)