from uuid import uuid4
import pytest

from src.agents.schemas import (
    AtendimentoRedatorSchema,
    CaixaRastreabilidadeSchema,
    ConfirmacaoHumanaSchema,
    ContextoRAGSchema,
    ResultadoConfirmacaoSchema,
    SugestaoCopilotoSchema,
    TicketClassification,
    VereditoAuditorSchema,
)
from src.db.connection import criar_tabelas
from src.db.session_repo import SessionRepository
from src.agents.retry import executar_crew_com_retry


@pytest.fixture(scope="module", autouse=True)
def garantir_tabelas():
    criar_tabelas()


def _montar_sugestao(session_id: str, tenant_id: str, categoria: str, chunk_id: str, pergunta: str, resp_ia: str):
    caixa = CaixaRastreabilidadeSchema(
        ticket_id=f"{session_id}-T1",
        timestamp="2026-11-24T12:00:00-03:00",
        pergunta_cliente=pergunta,
        triagem_inicial=TicketClassification(category=categoria, is_followup=False),
        rag_contexto=ContextoRAGSchema(
            chunk_id=chunk_id,
            subcategoria=categoria,
            score_similaridade=0.55,
            regra_escalonamento_aplicada="Escalar se persistir.",
        ),
        atendimento_n1=AtendimentoRedatorSchema(
            mensagem_enviada_ao_cliente=resp_ia,
            fonte_tecnica_citada=chunk_id,
            tentativas_redacao=1,
        ),
        auditoria=VereditoAuditorSchema(
            analise_raciocinio="OK",
            aprovado_para_envio=True,
            redator_alucinou=False,
            citou_fonte=True,
            requer_escalonamento=False,
        ),
        telemetria_tempos_s={"total_pipeline_s": 1.2},
    )
    return SugestaoCopilotoSchema(
        suggestion_id=f"SUG-{uuid4().hex[:8]}",
        session_id=session_id,
        tenant_id=tenant_id,
        pergunta_cliente=pergunta,
        mensagem_sugerida=resp_ia,
        alerta_escalonamento=False,
        caixa_rastreabilidade=caixa,
        chunks_usados=[{"chunk_id": chunk_id, "category": categoria}],
    )


def test_ciclo_memoria_topicos_e_encerramento():
    repo = SessionRepository(max_chars_topico=80)
    sid = f"TEST-DB-{uuid4().hex[:8]}"
    tenant = "tenant_teste"

    try:
        repo.obter_ou_criar_sessao(sid, tenant_id=tenant)

        # Turno 1: Technical
        sug1 = _montar_sugestao(
            sid, tenant, "Technical", "MAN-TECH-001-SEC-03",
            "Meu dashboard está travado na tela inicial.",
            "Limpe o cache do Chrome e desative a VPN.",
        )
        repo.salvar_sugestao_pendente(sug1)
        conf1 = ConfirmacaoHumanaSchema(
            suggestion_id=sug1.suggestion_id,
            acao_humana="EDITADA",
            mensagem_final_enviada="Por favor, limpe o cache no Chrome e desative a VPN.",
        )
        res1 = ResultadoConfirmacaoSchema(
            suggestion_id=sug1.suggestion_id,
            session_id=sid,
            tenant_id=tenant,
            acao_humana="EDITADA",
            atendente_id="n1_01",
            mensagem_sugerida=sug1.mensagem_sugerida,
            mensagem_final_enviada=conf1.mensagem_final_enviada,
            was_edited=True,
            edit_ratio=0.25,
            status_sessao="ABERTA",
        )
        trocou = repo.confirmar_turno(sug1, conf1, res1)
        assert trocou is None

        # Turno 2: troca para Billing
        sug2 = _montar_sugestao(
            sid, tenant, "Billing", "MAN-BILL-001-SEC-01",
            "Aproveitando, minha fatura veio duplicada.",
            "Vou verificar a cobrança duplicada.",
        )
        repo.salvar_sugestao_pendente(sug2)
        conf2 = ConfirmacaoHumanaSchema(
            suggestion_id=sug2.suggestion_id,
            acao_humana="ACEITA_SEM_EDICAO",
            mensagem_final_enviada=sug2.mensagem_sugerida,
        )
        res2 = ResultadoConfirmacaoSchema(
            suggestion_id=sug2.suggestion_id,
            session_id=sid,
            tenant_id=tenant,
            acao_humana="ACEITA_SEM_EDICAO",
            atendente_id="n1_01",
            mensagem_sugerida=sug2.mensagem_sugerida,
            mensagem_final_enviada=sug2.mensagem_sugerida,
            was_edited=False,
            edit_ratio=0.0,
            status_sessao="ABERTA",
        )
        trocou = repo.confirmar_turno(sug2, conf2, res2)
        assert trocou == "Technical"

        # Simula compactação em background do tópico Technical
        ctx_tech = repo.obter_contexto_topico(sid, "Technical", tenant_id=tenant)
        assert ctx_tech["precisa_compactar"] is True
        assert ctx_tech["cached_chunks"][0]["chunk_id"] == "MAN-TECH-001-SEC-03"

        repo.atualizar_resumo_topico(
            sid, "Technical", "Cliente relatou dashboard travado; orientado cache e VPN.", ate_turno=1, tenant_id=tenant
        )
        ctx_compactado = repo.obter_contexto_topico(sid, "Technical", tenant_id=tenant)
        assert "RESUMO ANTERIOR DO TÓPICO" in ctx_compactado["historico_formatado"]
        assert "fatura" not in ctx_compactado["historico_formatado"]

        # Isolamento por tenant: outro tenant não enxerga histórico
        assert repo.obter_historico_recente(sid, tenant_id="outro_tenant") == ""

        # Encerramento limpa estado quente mas mantém transcrição
        repo.encerrar_sessao(sid, tenant_id=tenant)
        sessao_final = repo.obter_ou_criar_sessao(sid, tenant_id=tenant)
        assert sessao_final.status == "ENCERRADA"
        assert sessao_final.chunks_em_cache is None
        assert sessao_final.topic_contexts is None
        assert sessao_final.pending_suggestion is None
        assert "dashboard" in repo.obter_transcricao_completa(sid, tenant_id=tenant)
    finally:
        repo.limpar_sessao_teste(sid)   

def test_retry_transitorio_crew():
    estado = {"tentativas": 0}

    class CrewInstavel:
        def kickoff(self):
            estado["tentativas"] += 1
            if estado["tentativas"] == 1:
                raise TimeoutError("timeout simulado NIM")
            return "ok"

    assert executar_crew_com_retry(CrewInstavel(), max_tentativas=2, espera_s=0.01) == "ok"
    assert estado["tentativas"] == 2


def test_consultas_leitura_api_e_fila_especialista():
    repo = SessionRepository()
    sid = f"TEST-READ-{uuid4().hex[:8]}"
    tenant = f"t_{uuid4().hex[:6]}"

    try:
        sug = _montar_sugestao(
            sid, tenant, "Technical", "MAN-TECH-001-SEC-03",
            "Sistema fora do ar.", "Verificando incidente.",
        )
        repo.salvar_sugestao_pendente(sug)

        sessoes = repo.listar_sessoes(tenant_id=tenant)
        assert len(sessoes) == 1
        assert sessoes[0]["tem_sugestao_pendente"] is True

        conf = ConfirmacaoHumanaSchema(
            suggestion_id=sug.suggestion_id,
            acao_humana="ESCALADA_N2",
            mensagem_final_enviada="Encaminhado ao especialista N2.",
        )
        res = ResultadoConfirmacaoSchema(
            suggestion_id=sug.suggestion_id,
            session_id=sid,
            tenant_id=tenant,
            acao_humana="ESCALADA_N2",
            atendente_id="n1_01",
            mensagem_sugerida=sug.mensagem_sugerida,
            mensagem_final_enviada=conf.mensagem_final_enviada,
            was_edited=True,
            edit_ratio=0.5,
            status_sessao="ESCALADA_N2",
            handoff_summary="Ação Tomada: N1 checado.\nPróximo Passo: Analisar N2.",
        )
        repo.confirmar_turno(sug, conf, res)

        fila_n2 = repo.listar_fila_especialista(tenant_id=tenant)
        assert len(fila_n2) == 1
        assert fila_n2[0]["handoff_summary"] is not None

        detalhe = repo.obter_detalhe_sessao(sid, tenant_id=tenant)
        assert detalhe is not None
        assert len(detalhe["mensagens"]) == 2
    finally:
        repo.limpar_sessao_teste(sid)