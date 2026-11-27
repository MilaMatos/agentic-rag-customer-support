import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

from src.agents.prompts.summarizer import construir_prompt_resumo
from src.agents.parsers import limpar_texto_resumo
from src.agents.retry import executar_crew_com_retry

from src.agents.llm_factory import criar_llm

load_dotenv()

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")


class AgenteResumo:
    """Agente autônomo responsável por gerar o resumo executivo interno do atendimento"""

    def __init__(self, model_name: str = "nvidia/nemotron-3.5-lightning-30b-a3b"):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.llm = criar_llm(model_name, temperature=0.0)

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
        executar_crew_com_retry(crew)

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
        executar_crew_com_retry(crew)
        return limpar_texto_resumo(task.output.raw)