from uuid import uuid4
import pytest

from src.agents.schemas import ConfirmacaoHumanaSchema
from src.db.connection import criar_tabelas
from src.db.session_repo import SessionRepository
from src.pipeline_agents import NexusSupportPipeline

CHUNK_DASHBOARD = [
    {
        "chunk_id": "MAN-TECH-001-SEC-03",
        "category": "Technical",
        "subcategory": "Travamento do Dashboard",
        "similarity_score": 0.4749,
        "fatias": {
            "sintomas": "Dashboard principal não carrega indicadores.",
            "resolucao_n1": "1) Usar Chrome/Edge; 2) Limpar cache; 3) Desativar VPN e Ctrl+F5.",
            "escalonamento": "Transferir para N2 se já executou os 3 passos N1 e persistir > 20 min.",
        },
    }
]


@pytest.fixture(scope="module", autouse=True)
def garantir_tabelas():
    criar_tabelas()


@pytest.mark.llm
class TestPipelineMultiTurnoE2E:
    """Teste E2E de 2 turnos com LLMs reais e persistência no PostgreSQL."""

    def test_conversa_2_turnos_followup_cache_e_escalonamento(self, monkeypatch):
        repo = SessionRepository()
        pipeline = NexusSupportPipeline(session_repo=repo)
        sid = f"TEST-E2E-MT-{uuid4().hex[:8]}"
        tenant = "tenant_e2e"

        chamadas_rag = {"count": 0}

        def mock_por_vetor(**kwargs):
            assert kwargs.get("category_filter") is None
            chamadas_rag["count"] += 1
            return CHUNK_DASHBOARD

        def mock_buscar_chunks(**kwargs):
            assert kwargs.get("category_filter") is None
            chamadas_rag["count"] += 1
            return CHUNK_DASHBOARD

        monkeypatch.setattr(pipeline.retriever.embeddings, "embed_query", lambda txt: [0.1] * 8)
        monkeypatch.setattr(pipeline.retriever, "buscar_chunks_por_vetor", mock_por_vetor)
        monkeypatch.setattr(pipeline.retriever, "buscar_chunks", mock_buscar_chunks)

        try:
            # Turno 1: orientação N1 sem escalar
            sug1 = pipeline.gerar_sugestao_db(
                sid,
                "Meu painel principal não carrega os relatórios, fica só uma bolinha girando.",
                tenant_id=tenant,
            )
            caixa_t1 = sug1.caixa_rastreabilidade
            assert caixa_t1.triagem_inicial.category == "Technical"
            assert caixa_t1.rag_contexto.chunk_id == "MAN-TECH-001-SEC-03"
            assert caixa_t1.rag_contexto.reutilizado_do_cache is False
            assert caixa_t1.auditoria.requer_escalonamento is False
            assert chamadas_rag["count"] == 1

            pipeline.confirmar_envio_db(
                sid,
                ConfirmacaoHumanaSchema(
                    suggestion_id=sug1.suggestion_id,
                    acao_humana="ACEITA_SEM_EDICAO",
                    mensagem_final_enviada=sug1.mensagem_sugerida,
                ),
                tenant_id=tenant,
            )

            # Turno 2: follow-up confirma falha após 30 min -> cache hit + alerta N2
            sug2 = pipeline.gerar_sugestao_db(
                sid,
                "Já limpei o cache no Chrome, desativei a VPN e dei Ctrl+F5 há mais de meia hora, mas continua travado!",
                tenant_id=tenant,
            )
            caixa_t2 = sug2.caixa_rastreabilidade
            assert caixa_t2.triagem_inicial.is_followup is True
            assert caixa_t2.rag_contexto.chunk_id == "MAN-TECH-001-SEC-03"
            assert caixa_t2.rag_contexto.reutilizado_do_cache is True
            assert caixa_t2.auditoria.requer_escalonamento is True
            assert chamadas_rag["count"] == 1

            res2 = pipeline.confirmar_envio_db(
                sid,
                ConfirmacaoHumanaSchema(
                    suggestion_id=sug2.suggestion_id,
                    acao_humana="ESCALADA_N2",
                    mensagem_final_enviada="Estou encaminhando seu caso para um especialista.",
                ),
                tenant_id=tenant,
            )
            assert res2.status_sessao == "ESCALADA_N2"
            assert res2.handoff_summary is not None
        finally:
            pipeline.shutdown()
            repo.limpar_sessao_teste(sid)