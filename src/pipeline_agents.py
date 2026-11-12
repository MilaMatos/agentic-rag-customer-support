import os

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.rag.retriever import NexusRetriever
from src.agents.agent_classifier import AgenteClassificador
from src.agents.agent_redactor import AgenteRedatorN1
from src.agents.agent_auditor import AgenteAuditorQualidade
from src.agents.agent_summarizer import AgenteResumo
from src.agents.schemas import (
    TicketClassification,
    ContextoRAGSchema,
    AtendimentoRedatorSchema,
    VereditoAuditorSchema,
    CaixaRastreabilidadeSchema,
)

MAX_TENTATIVAS_CORRECAO = 2
MIN_SIMILARITY = 0.30

ARQUIVO_TESTES = Path("data/evaluation/testes_e3.json")
PASTA_RASTREABILIDADE = Path("logs/rastreabilidade")
PASTA_RASTREABILIDADE.mkdir(parents=True, exist_ok=True)


class NexusSupportPipeline:
    """Orquestrador Multi-Agente RAG do NexusTech Support Copilot"""

    def __init__(self):
        self.retriever = NexusRetriever()
        self.classificador = AgenteClassificador()
        self.redator = AgenteRedatorN1()
        self.auditor = AgenteAuditorQualidade()
        self.resumidor = AgenteResumo()

    def _obter_classificacao(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
    ) -> TicketClassification:
        """Usa o dict externo (se fornecido para teste isolado) ou aciona o AgenteClassificador"""
        if classificacao_externa:
            return TicketClassification(
                category=classificacao_externa.get("category") or classificacao_externa.get("categoria", "General Inquiry"),
                priority=classificacao_externa.get("priority") or classificacao_externa.get("prioridade", "Media"),
                initial_level=classificacao_externa.get("initial_level") or classificacao_externa.get("nivel_inicial", "N1"),
                triage_justification=classificacao_externa.get("triage_justification") or classificacao_externa.get("justificativa_triagem", ""),
            )
        return self.classificador.executar(pergunta_cliente=pergunta_cliente)

    def processar_ticket(
        self,
        pergunta_cliente: str,
        classificacao_externa: Optional[dict[str, Any]] = None,
        gerar_resumo: bool = True,
        ticket_id: Optional[str] = None,
    ) -> CaixaRastreabilidadeSchema:
        """Executa o fluxo completo do ticket e retorna a Caixa de Rastreabilidade"""
        t_inicio_total = time.time()
        id_exec = ticket_id or f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 1. Agente 1: Triagem e Classificação
        t0 = time.time()
        triagem = self._obter_classificacao(pergunta_cliente, classificacao_externa)
        tempo_classificacao = round(time.time() - t0, 3)

        # 2. Busca Semântica Fatiada no PGVector
        t1 = time.time()
        chunks = self.retriever.buscar_chunks(
            query=pergunta_cliente,
            k=1,
            category_filter=triagem.category,
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

        # 3. Agentes 2 e 3: Redator <-> Auditor com Loop de Autocorreção
        t2 = time.time()
        feedback = None
        dados_redator: dict[str, str] = {}
        veredito: Optional[VereditoAuditorSchema] = None
        tentativas_realizadas = 0

        for tentativa in range(1, MAX_TENTATIVAS_CORRECAO + 2):
            tentativas_realizadas = tentativa
            dados_redator = self.redator.executar(
                pergunta_cliente=pergunta_cliente,
                chunks=chunks,
                feedback_anterior=feedback,
            )
            veredito = self.auditor.executar(
                pergunta_cliente=pergunta_cliente,
                resposta_redator=dados_redator["texto_completo_auditoria"],
                chunks=chunks,
            )
            if veredito.aprovado_para_envio:
                break
            feedback = veredito.feedback_correcao

        tempo_agentes_rag = round(time.time() - t2, 3)

        # 4. Agente 4: Resumo Executivo Interno
        t3 = time.time()
        resumo_texto = None
        if gerar_resumo:
            resumo_texto = self.resumidor.executar(
                resposta_final_cliente=dados_redator.get("mensagem_cliente", "")
            )
        tempo_resumo = round(time.time() - t3, 3)

        # 5. Montagem da Caixa de Rastreabilidade Oficial
        return CaixaRastreabilidadeSchema(
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
            resumo_interno_ticket=resumo_texto,
            telemetria_tempos_s={
                "classificacao_s": tempo_classificacao,
                "retriever_pgvector_s": tempo_rag,
                "redator_e_auditor_s": tempo_agentes_rag,
                "resumo_s": tempo_resumo,
                "total_pipeline_s": round(time.time() - t_inicio_total, 3),
            },
        )


def rodar_pipeline_com_json_testes(
    filtro_id: Optional[str] = None,
    usar_agente_classificador: bool = True,
    gerar_resumo: bool = True,
) -> Path:
    pipeline = NexusSupportPipeline()

    with open(ARQUIVO_TESTES, "r", encoding="utf-8") as f:
        casos = json.load(f)

    if filtro_id:
        casos = [c for c in casos if c.get("id_teste") == filtro_id]

    caixas_geradas = []

    for caso in casos:
        entrada_mock = None
        if not usar_agente_classificador:
            entrada_mock = {
                "category": caso["categoria"],
                "priority": caso.get("prioridade", "Alta"),
                "initial_level": caso.get("nivel_inicial", "N1"),
                "triage_justification": caso.get("descricao", "Triagem via dataset de testes."),
            }

        print(f"\nProcessando [{caso['id_teste']}]...")
        caixa = pipeline.processar_ticket(
            pergunta_cliente=caso["pergunta"],
            classificacao_externa=entrada_mock,
            gerar_resumo=gerar_resumo,
            ticket_id=caso["id_teste"],
        )
        caixas_geradas.append(caixa.model_dump())

        print(f" -> Categoria Triagem: {caixa.triagem_inicial.category} (Esperada: {caso['categoria']})")
        print(f" -> Requer Escalonamento (Auditor): {caixa.auditoria.requer_escalonamento}")
        print(f" -> Tempo Total: {caixa.telemetria_tempos_s['total_pipeline_s']}s")

    caminho_saida = PASTA_RASTREABILIDADE / f"rastreabilidade_tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(caixas_geradas, f, indent=4, ensure_ascii=False)

    print(f"\nCaixa de Rastreabilidade salva em: {caminho_saida.resolve()}")
    return caminho_saida


if __name__ == "__main__":
    # Para rodar os 4 agentes completos de ponta a ponta:
    rodar_pipeline_com_json_testes(usar_agente_classificador=True, gerar_resumo=True)