import time
from uuid import uuid4
import pytest

from src.agents.schemas import (
    ConfirmacaoHumanaSchema,
    TicketClassification,
    VereditoAuditorSchema,
)
from src.db.connection import criar_tabelas
from src.db.session_repo import SessionRepository
from src.pipeline_agents import NexusSupportPipeline


@pytest.fixture(scope="module", autouse=True)
def garantir_tabelas():
    criar_tabelas()


CHUNK_TECH = [{
    "chunk_id": "MAN-TECH-001-SEC-03",
    "category": "Technical",
    "subcategory": "Travamento do Dashboard",
    "similarity_score": 0.62,
    "fatias": {
        "sintomas": "Dashboard travado.",
        "resolucao_n1": "Limpar cache e desativar VPN.",
        "escalonamento": "Escalar se persistir > 20 min.",
    },
}]

CHUNK_BILL = [{
    "chunk_id": "MAN-BILL-001-SEC-01",
    "category": "Billing",
    "subcategory": "Cobrança Duplicada",
    "similarity_score": 0.71,
    "fatias": {
        "sintomas": "Fatura cobrada duas vezes.",
        "resolucao_n1": "Solicitar comprovante e abrir estorno.",
        "escalonamento": "Escalar para financeiro se > 5 dias.",
    },
}]


def _veredito_ok(requer_escalonamento: bool = False) -> VereditoAuditorSchema:
    return VereditoAuditorSchema(
        analise_raciocinio="OK",
        aprovado_para_envio=True,
        redator_alucinou=False,
        citou_fonte=True,
        requer_escalonamento=requer_escalonamento,
    )


def test_turno1_embedding_especulativo_em_paralelo(monkeypatch):
    repo = SessionRepository()
    pipeline = NexusSupportPipeline(session_repo=repo)
    sid = f"TEST-PAR-{uuid4().hex[:8]}"

    chamadas = {"por_vetor": 0, "padrao": 0}

    def mock_classificador(**kwargs):
        time.sleep(0.15)
        return TicketClassification(category="Technical", is_followup=False)

    def mock_embed(texto):
        time.sleep(0.15)
        return [0.1] * 8

    def mock_por_vetor(**kwargs):
        chamadas["por_vetor"] += 1
        return CHUNK_TECH

    def mock_padrao(**kwargs):
        chamadas["padrao"] += 1
        return CHUNK_TECH

    monkeypatch.setattr(pipeline.classificador, "executar", mock_classificador)
    monkeypatch.setattr(pipeline.retriever.embeddings, "embed_query", mock_embed)
    monkeypatch.setattr(pipeline.retriever, "buscar_chunks_por_vetor", mock_por_vetor)
    monkeypatch.setattr(pipeline.retriever, "buscar_chunks", mock_padrao)
    monkeypatch.setattr(
        pipeline.redator,
        "executar",
        lambda **kw: {
            "mensagem_cliente": "Limpe o cache.",
            "fonte_citada": "MAN-TECH-001-SEC-03",
            "texto_completo_auditoria": "Limpe o cache. [[FONTE: MAN-TECH-001-SEC-03]]",
        },
    )
    monkeypatch.setattr(pipeline.auditor, "executar", lambda **kw: _veredito_ok())

    try:
        t0 = time.perf_counter()
        sug = pipeline.gerar_sugestao_db(sid, "Meu dashboard travou", tenant_id="t_par")
        duracao = time.perf_counter() - t0

        assert duracao < 0.28
        assert chamadas["por_vetor"] == 1
        assert chamadas["padrao"] == 0
        assert sug.caixa_rastreabilidade.rag_contexto.chunk_id == "MAN-TECH-001-SEC-03"
    finally:
        repo.limpar_sessao_teste(sid)


def test_memoria_por_topico_compactacao_bg_e_handoff(monkeypatch):
    repo = SessionRepository(max_chars_topico=60)
    pipeline = NexusSupportPipeline(session_repo=repo)
    sid = f"TEST-TOP-{uuid4().hex[:8]}"
    tenant = "t_mem"

    historicos_recebidos: list[str] = []
    chamadas_compactacao = {"count": 0}
    transcricao_handoff = {"texto": ""}

    respostas_triagem = iter([
        TicketClassification(category="Technical", is_followup=False),
        TicketClassification(category="Billing", is_followup=False),
        TicketClassification(category="Technical", is_followup=False),
    ])

    monkeypatch.setattr(pipeline.classificador, "executar", lambda **kw: next(respostas_triagem))
    monkeypatch.setattr(pipeline.retriever.embeddings, "embed_query", lambda txt: [0.1] * 8)
    monkeypatch.setattr(pipeline.retriever, "buscar_chunks_por_vetor", lambda **kw: CHUNK_TECH)
    monkeypatch.setattr(
        pipeline.retriever,
        "buscar_chunks",
        lambda **kw: CHUNK_BILL if kw.get("category_filter") == "Billing" else CHUNK_TECH,
    )

    def mock_redator(**kw):
        historicos_recebidos.append(kw.get("historico_conversa", ""))
        cat = kw.get("categoria")
        fonte = "MAN-BILL-001-SEC-01" if cat == "Billing" else "MAN-TECH-001-SEC-03"
        msg = "Envie o comprovante da fatura." if cat == "Billing" else "Limpe o cache no Chrome e desative a VPN."
        return {
            "mensagem_cliente": msg,
            "fonte_citada": fonte,
            "texto_completo_auditoria": f"{msg} [[FONTE: {fonte}]]",
        }

    def mock_resumir_topico(categoria, transcricao_topico, resumo_anterior=""):
        chamadas_compactacao["count"] += 1
        return "Cliente relatou dashboard travado; orientado cache no Chrome e VPN."

    def mock_handoff(resposta_final_cliente):
        transcricao_handoff["texto"] = resposta_final_cliente
        return "Ação Tomada: N1 aplicado.\nPróximo Passo: Analisar logs N2."

    monkeypatch.setattr(pipeline.redator, "executar", mock_redator)
    monkeypatch.setattr(pipeline.auditor, "executar", lambda **kw: _veredito_ok(requer_escalonamento=True))
    monkeypatch.setattr(pipeline.resumidor, "resumir_topico", mock_resumir_topico)
    monkeypatch.setattr(pipeline.resumidor, "executar", mock_handoff)

    try:
        # Turno 1: Technical (passa de 60 chars -> dispara compactação em background)
        s1 = pipeline.gerar_sugestao_db(sid, "Meu dashboard principal está travado na tela.", tenant)
        pipeline.confirmar_envio_db(
            sid,
            ConfirmacaoHumanaSchema(
                suggestion_id=s1.suggestion_id,
                acao_humana="ACEITA_SEM_EDICAO",
                mensagem_final_enviada=s1.mensagem_sugerida,
            ),
            tenant,
        )
        pipeline.aguardar_background()
        assert chamadas_compactacao["count"] == 1

        # Turno 2: Billing (assunto novo -> histórico injetado deve vir vazio)
        s2 = pipeline.gerar_sugestao_db(sid, "Minha fatura veio cobrada em duplicidade.", tenant)
        assert historicos_recebidos[1] == ""
        pipeline.confirmar_envio_db(
            sid,
            ConfirmacaoHumanaSchema(
                suggestion_id=s2.suggestion_id,
                acao_humana="ACEITA_SEM_EDICAO",
                mensagem_final_enviada=s2.mensagem_sugerida,
            ),
            tenant,
        )

        # Turno 3: Volta para Technical -> recebe resumo do tópico sem vazar Billing
        s3 = pipeline.gerar_sugestao_db(sid, "Voltando ao dashboard, já fiz tudo e continua travado.", tenant)
        assert "RESUMO ANTERIOR DO TÓPICO (Technical)" in historicos_recebidos[2]
        assert "fatura" not in historicos_recebidos[2]

        res3 = pipeline.confirmar_envio_db(
            sid,
            ConfirmacaoHumanaSchema(
                suggestion_id=s3.suggestion_id,
                acao_humana="ESCALADA_N2",
                mensagem_final_enviada="Encaminhando seu caso para o especialista N2.",
            ),
            tenant,
        )
        assert res3.status_sessao == "ESCALADA_N2"
        assert res3.handoff_summary is not None
        assert "Voltando ao dashboard" in transcricao_handoff["texto"]

        pipeline.encerrar_sessao_db(sid, tenant)
        sessao_final = repo.obter_ou_criar_sessao(sid, tenant)
        assert sessao_final.status == "ENCERRADA"
        assert sessao_final.topic_contexts is None
    finally:
        repo.limpar_sessao_teste(sid)