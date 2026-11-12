import os
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Literal
import logging

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from crewai import Agent, Task, Crew, Process, LLM

from src.rag.retriever import NexusRetriever
from src.rag.prompts.redactor import construir_prompt_redator, separar_mensagem_e_fonte
from src.rag.prompts.auditor import construir_prompt_auditor, extrair_json_auditoria

load_dotenv()

# Desativa telemetria externa do CrewAI que adiciona latência a cada kickoff()
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

# Silencia os avisos de contagem aproximada de tokens do CrewAI/LiteLLM
logging.getLogger("crewai.llms.base_llm").setLevel(logging.ERROR)
logging.getLogger("LiteLLM").setLevel(logging.ERROR)

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

MAX_TENTATIVAS_CORRECAO = 2
MIN_SIMILARITY = 0.30

ARQUIVO_TESTES = Path("data/evaluation/testes_e3.json")
PASTA_RASTREABILIDADE = Path("logs/rastreabilidade")
PASTA_RASTREABILIDADE.mkdir(parents=True, exist_ok=True)

# =====================================================================
# SCHEMAS DE CONTRATO ENTRE AGENTES E CAIXA DE RASTREABILIDADE
# =====================================================================

class TriagemClassificadorSchema(BaseModel):
    """Contrato de saída do Agente 1 (Classificador)."""
    categoria: Literal["Technical", "Billing", "Account", "Fraud", "General Inquiry"] = Field(
        description="Categoria oficial da base de conhecimento."
    )
    prioridade: Literal["Baixa", "Media", "Alta", "Critica"] = Field(
        default="Media", description="Nível de prioridade do chamado."
    )
    nivel_inicial: Literal["N1", "N2", "N3"] = Field(
        default="N1", description="Hipótese de nível na triagem inicial."
    )
    justificativa_triagem: str = Field(
        default="", description="Motivo resumido da classificação inicial."
    )


class ContextoRAGSchema(BaseModel):
    """Dados do chunk recuperado no PGVector salvos para rastreabilidade."""
    chunk_id: str = Field(description="ID do chunk recuperado ou FORA_DE_ESCOPO.")
    subcategoria: str = Field(description="Subcategoria do manual operacional.")
    score_similaridade: float = Field(description="Score de similaridade de cosseno (0.0 a 1.0).")
    regra_escalonamento_aplicada: str = Field(description="Trecho da regra N2/N3 do manual.")


class AtendimentoRedatorSchema(BaseModel):
    """Dados consolidados gerados pelo Agente 2 (Redator N1)."""
    mensagem_enviada_ao_cliente: str = Field(description="Texto limpo enviado ao cliente no chat.")
    fonte_tecnica_citada: str = Field(description="Chunk_ID extraído da tag [[FONTE: ...]].")
    tentativas_redacao: int = Field(description="Número de tentativas até aprovação do Auditor.")


class VereditoAuditorSchema(BaseModel):
    """Contrato de saída do Agente 3 (Auditor de Qualidade e Roteamento)."""
    analise_raciocinio: str = Field(
        description="1 frase explicando se respeitou o manual e o porquê do nível N1, N2 ou N3."
    )
    aprovado_para_envio: bool = Field(
        description="True se aprovado, False se precisar de correção pelo Redator."
    )
    redator_alucinou: bool = Field(
        description="True se o Redator inventou regras, prazos ou valores."
    )
    citou_fonte: bool = Field(
        description="True se incluiu a tag [[FONTE: ...]] ao final."
    )
    nivel_escalonamento: Literal["N1", "N2", "N3"] = Field(
        description="Nível técnico definitivo do chamado (N1, N2 ou N3)."
    )
    feedback_correcao: str = Field(
        default="", description="Instrução de correção para o Redator caso reprovado."
    )


class ResumoHandoffSchema(BaseModel):
    """Contrato de saída do Agente 4 (Resumo de Handoff para N2/N3)."""
    nivel_destino: Literal["N2", "N3"] = Field(description="Nível para o qual o ticket foi escalado.")
    fila_responsavel: str = Field(description="Equipe de destino (ex: Backoffice Financeiro, Engenharia).")
    resumo_executivo: str = Field(description="Síntese clara do problema do cliente.")
    acoes_ja_realizadas: str = Field(description="O que já foi validado ou tentado no N1.")
    motivo_tecnico_escalonamento: str = Field(description="Gatilho do manual que exigiu o escalonamento.")
    acao_recomendada_proximo_nivel: str = Field(description="Próximo passo técnico para o especialista.")


class CaixaRastreabilidadeSchema(BaseModel):
    """Envelope mestre do ticket contendo todo o histórico, decisões e telemetria da pipeline."""
    ticket_id: str
    timestamp: str
    pergunta_cliente: str
    triagem_inicial: TriagemClassificadorSchema
    rag_contexto: ContextoRAGSchema
    atendimento_n1: AtendimentoRedatorSchema
    auditoria: VereditoAuditorSchema
    requer_handoff_humano: bool
    resumo_handoff_n2_n3: Optional[ResumoHandoffSchema] = None
    telemetria_tempos_s: dict[str, float]

# =====================================================================
# PIPELINE OFICIAL CREWAI
# =====================================================================

class NexusSupportPipeline:
    """Orquestrador Multi-Agente RAG do NexusTech Support Copilot."""

    def __init__(self):
        if not API_KEY:
            raise ValueError("NVIDIA_API_KEY não encontrada no .env")

        self.retriever = NexusRetriever()

        self.llm_redator = LLM(
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            custom_openai=True,
            base_url=BASE_URL,
            api_key=API_KEY,
            temperature=0.1,
            max_tokens=1024,
            context_window_size=8192,
            additional_params={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
            timeout=30,
        )

        self.llm_auditor = LLM(
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            custom_openai=True,
            base_url=BASE_URL,
            api_key=API_KEY,
            temperature=0.0,
            max_tokens=1024,
            context_window_size=8192,
            additional_params={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
            timeout=30,
        )

    # -----------------------------------------------------------------
    # PONTO DE EXTENSÃO 1: AGENTE CLASSIFICADOR
    # -----------------------------------------------------------------
    def _obter_classificacao(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
    ) -> TriagemClassificadorSchema:
        """
        Recebe a classificação vinda do JSON de testes (ou do Agente Classificador)
        """
        if classificacao_externa:
            return TriagemClassificadorSchema(**classificacao_externa)

        # TODO : Plugar chamada do Agente Classificador aqui quando não vier do JSON
        raise NotImplementedError("Classificador automático ainda não integrado. Passe classificacao_externa.")

    # -----------------------------------------------------------------
    # NÚCLEO RAG: REDATOR + AUDITOR
    # -----------------------------------------------------------------

    def _executar_redator(
        self,
        pergunta_cliente: str,
        chunks: list[dict[str, Any]],
        feedback_anterior: Optional[str] = None,
    ) -> dict[str, str]:
        """Instancia o Agente Redator e gera a resposta ao cliente."""
        prompts_red = construir_prompt_redator(
            pergunta_cliente=pergunta_cliente,
            chunks_fatiados=chunks,
            feedback_auditor=feedback_anterior,
        )

        agente_redator = Agent(
            role="Especialista de Atendimento (Redator)",
            goal="Produzir resposta clara e fiel à base de conhecimento para o cliente.",
            backstory=prompts_red["system_prompt"],
            llm=self.llm_redator,
            verbose=False,
            allow_delegation=False,
        )

        task_redacao = Task(
            description=prompts_red["user_prompt"],
            expected_output="Resposta ao cliente contendo a tag [[FONTE: Chunk_ID]] na última linha.",
            agent=agente_redator,
        )

        crew_redator = Crew(
            agents=[agente_redator],
            tasks=[task_redacao],
            process=Process.sequential,
            verbose=False,
        )
        crew_redator.kickoff()
        
        return separar_mensagem_e_fonte(task_redacao.output.raw)

    def _executar_auditor(
        self,
        pergunta_cliente: str,
        resposta_redator: str,
        chunks: list[dict[str, Any]],
    ) -> VereditoAuditorSchema:
        """Instancia o Agente Auditor e avalia a resposta gerada."""
        prompts_aud = construir_prompt_auditor(
            pergunta_cliente=pergunta_cliente,
            resposta_redator=resposta_redator,
            chunks_fatiados=chunks,
        )

        agente_auditor = Agent(
            role="Auditor de Qualidade e Roteamento de Tickets",
            goal="Auditar fidelidade da resposta e definir o nível atual do chamado (N1, N2 ou N3).",
            backstory=prompts_aud["system_prompt"],
            llm=self.llm_auditor,
            verbose=False,
            allow_delegation=False,
        )

        task_auditoria = Task(
            description=prompts_aud["user_prompt"],
            expected_output="JSON válido contendo analise_raciocinio, aprovado_para_envio, redator_alucinou, citou_fonte, nivel_escalonamento e feedback_correcao.",
            agent=agente_auditor,
        )

        crew_auditor = Crew(
            agents=[agente_auditor],
            tasks=[task_auditoria],
            process=Process.sequential,
            verbose=False,
        )
        crew_auditor.kickoff()

        dict_auditoria = extrair_json_auditoria(task_auditoria.output.raw)
        return VereditoAuditorSchema(**dict_auditoria)

    # -----------------------------------------------------------------
    # PONTO DE EXTENSÃO 2: AGENTE DE RESUMO / HANDOFF
    # -----------------------------------------------------------------
    def _executar_resumo_handoff(
        self,
        caixa_rastreabilidade: CaixaRastreabilidadeSchema,
    ) -> Optional[dict[str, Any]]:
        """
        Recebe a Caixa de Rastreabilidade pronta caso o ticket seja N2 ou N3.
        Por enquanto permanece vazio (None) até a integração dos próximos agentes.
        """
        # TODO: Ler os campos de `caixa_rastreabilidade` e gerar o resumo para N2/N3
        return None

    # -----------------------------------------------------------------
    # EXECUÇÃO DE UM TICKET
    # -----------------------------------------------------------------
    def processar_ticket(
        self,
        pergunta_cliente: str,
        classificacao_externa: dict[str, Any],
        ticket_id: Optional[str] = None,
    ) -> CaixaRastreabilidadeSchema:
        """
        Executa o fluxo completo do ticket e retorna a Caixa de Rastreabilidade
        """

        t_inicio_total = time.time()
        id_exec = ticket_id or f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 1. Triagem Inicial (vinda do JSON ou do Classificador)
        t0 = time.time()
        triagem = self._obter_classificacao(pergunta_cliente, classificacao_externa)
        tempo_classificacao = round(time.time() - t0, 3)

        # 2. Busca Semântica Fatiada no PGVector
        t1 = time.time()
        chunks = self.retriever.buscar_chunks(
            query=pergunta_cliente,
            k=1,
            category_filter=triagem.categoria,
            min_similarity=MIN_SIMILARITY,
        )
        tempo_rag = round(time.time() - t1, 3)

        chunk_top1 = chunks[0] if chunks else {}
        rag_trace = ContextoRAGSchema(
            chunk_id=chunk_top1.get("chunk_id", "FORA_DE_ESCOPO"),
            subcategoria=chunk_top1.get("subcategory", "N/A"),
            score_similaridade=chunk_top1.get("similarity_score", 0.0),
            regra_escalonamento_aplicada=chunk_top1.get("fatias", {}).get(
                "escalonamento", "Escalonar para N2 por ausência de cobertura."
            ),
        )

        # 3. Redator + Auditor com Loop de Autocorreção
        t2 = time.time()
        feedback = None
        dados_redator: dict[str, str] = {}
        veredito: Optional[VereditoAuditorSchema] = None
        tentativas_realizadas = 0

        for tentativa in range(1, MAX_TENTATIVAS_CORRECAO + 2):
            tentativas_realizadas = tentativa

            dados_redator = self._executar_redator(
                pergunta_cliente=pergunta_cliente,
                chunks=chunks,
                feedback_anterior=feedback,
            )
            
            veredito = self._executar_auditor(
                pergunta_cliente=pergunta_cliente,
                resposta_redator=dados_redator["texto_completo_auditoria"],
                chunks=chunks,
            )
            
            if veredito.aprovado_para_envio:
                break
            feedback = veredito.feedback_correcao

        tempo_agentes_rag = round(time.time() - t2, 3)
        requer_handoff = veredito.nivel_escalonamento in ("N2", "N3")

        # 4. Montagem da Caixa de Rastreabilidade Oficial
        caixa = CaixaRastreabilidadeSchema(
            ticket_id=id_exec,
            timestamp=datetime.now().astimezone().isoformat(),
            pergunta_cliente=pergunta_cliente,
            triagem_inicial=triagem,
            rag_contexto=rag_trace,
            atendimento_n1=AtendimentoRedatorSchema(
                mensagem_enviada_ao_cliente=dados_redator.get("mensagem_cliente", ""),
                fonte_tecnica_citada=dados_redator.get("fonte_citada", "NÃO_CITADA"),
                tentativas_redacao=tentativas_realizadas,
            ),
            auditoria=veredito,
            requer_handoff_humano=requer_handoff,
            resumo_handoff_n2_n3=None,
            telemetria_tempos_s={
                "classificacao_s": tempo_classificacao,
                "retriever_pgvector_s": tempo_rag,
                "redator_e_auditor_s": tempo_agentes_rag,
                "total_pipeline_s": round(time.time() - t_inicio_total, 3),
            },
        )

        # 5. Aciona o Resumo de Handoff (vazio por enquanto) se for N2 ou N3
        if caixa.requer_handoff_humano:
            caixa.resumo_handoff_n2_n3 = self._executar_resumo_handoff(caixa)

        return caixa


# =====================================================================
# EXECUÇÃO A PARTIR DO JSON DE TESTES
# =====================================================================

def rodar_pipeline_com_json_testes(filtro_id: Optional[str] = None) -> Path:
    pipeline = NexusSupportPipeline()

    with open(ARQUIVO_TESTES, "r", encoding="utf-8") as f:
        casos = json.load(f)

    if filtro_id:
        casos = [c for c in casos if c.get("id_teste") == filtro_id]

    caixas_geradas = []

    for caso in casos:
        # Monta o contrato exatamente como o Classificador enviará
        entrada_classificador = caso.get("classificacao_entrada") or {
            "categoria": caso["categoria"],
            "prioridade": caso.get("prioridade", "Alta"),
            "nivel_inicial": caso.get("nivel_inicial", "N1"),
            "justificativa_triagem": caso.get("descricao", "Triagem inicial via dataset de testes."),
        }

        print(f"\nProcessando [{caso['id_teste']}] -> Categoria: {entrada_classificador['categoria']}...")
        caixa = pipeline.processar_ticket(
            pergunta_cliente=caso["pergunta"],
            classificacao_externa=entrada_classificador,
            ticket_id=caso["id_teste"],
        )
        caixas_geradas.append(caixa.model_dump())

        print(f" -> Nível Final Auditor: {caixa.auditoria.nivel_escalonamento} | Handoff: {caixa.requer_handoff_humano}")
        print(f" -> Tempo Total: {caixa.telemetria_tempos_s['total_pipeline_s']}s")

    caminho_saida = PASTA_RASTREABILIDADE / f"rastreabilidade_tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(caixas_geradas, f, indent=4, ensure_ascii=False)

    print(f"\nCaixa de Rastreabilidade salva em: {caminho_saida.resolve()}")
    return caminho_saida


if __name__ == "__main__":
    rodar_pipeline_com_json_testes()