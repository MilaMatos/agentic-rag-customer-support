from contextvars import copy_context
import pytest

from src.agents.memory import SessionMemory
from src.agents.schemas import ConfirmacaoHumanaSchema
from src.agents.tools import _ultimos_chunks_ctx, obter_ultimos_chunks_tool
from src.pipeline_agents import NexusSupportPipeline


class TestSessionMemoryEConcorrencia:
    """Testes unitários rápidos (sem LLM) para memória HITL e isolamento de contexto"""

    def test_cache_rag_e_troca_de_topico_sem_bloqueio(self):
        mem = SessionMemory(session_id="TEST-MEM-01", tenant_id="empresa_a")
        chunk_tech = [{"chunk_id": "MAN-TECH-001-SEC-03", "subcategory": "Dashboard"}]
        chunk_bill = [{"chunk_id": "MAN-BILL-002-SEC-01", "subcategory": "Fatura"}]

        # Turno 1: novo tópico
        usar_cache, turno_topico = mem.avaliar_contexto_topico("Technical", is_followup=False)
        assert usar_cache is False
        assert turno_topico == 1
        mem.registrar_turno("Pergunta 1", "Resposta 1", "Technical", False, chunk_tech, {})

        # Turnos 2, 3 e 4 no mesmo tópico: mantém cache e contador informativo sem bloquear
        for esperado in (2, 3, 4):
            usar_cache, turno_topico = mem.avaliar_contexto_topico("Technical", is_followup=True)
            assert usar_cache is True
            assert turno_topico == esperado
            mem.registrar_turno(f"P{esperado}", f"R{esperado}", "Technical", True, chunk_tech, {})

        # Turno 5: troca de assunto reseta contador para 1 e invalida cache
        usar_cache, turno_topico = mem.avaliar_contexto_topico("Billing", is_followup=False)
        assert usar_cache is False
        assert turno_topico == 1
        mem.registrar_turno("Fatura duplicada", "Verificando", "Billing", False, chunk_bill, {})
        assert mem.categoria_atual == "Billing"
        assert mem.chunks_em_cache == chunk_bill

    def test_isolamento_contextvar_tools(self):
        ctx_a = copy_context()
        ctx_b = copy_context()

        ctx_a.run(_ultimos_chunks_ctx.set, [{"chunk_id": "CHUNK-A"}])
        ctx_b.run(_ultimos_chunks_ctx.set, [{"chunk_id": "CHUNK-B"}])

        assert ctx_a.run(obter_ultimos_chunks_tool) == [{"chunk_id": "CHUNK-A"}]
        assert ctx_b.run(obter_ultimos_chunks_tool) == [{"chunk_id": "CHUNK-B"}]


class TestCicloHITLUnitario:
    """Valida que a memória só grava após confirmação humana e só resume no escalonamento"""

    def test_edicao_humana_e_resumo_sob_demanda(self, monkeypatch):
        pipeline = NexusSupportPipeline()
        sessao = SessionMemory(session_id="TEST-HITL-01", tenant_id="tenant_x")
        chamadas_resumo = {"count": 0}

        def mock_resumo(resposta_final_cliente: str) -> str:
            chamadas_resumo["count"] += 1
            return "Ação Tomada: N1 validado.\nPróximo Passo: Investigar logs N2."

        monkeypatch.setattr(pipeline.resumidor, "executar", mock_resumo)

        # Simula sugestão pendente sem precisar chamar LLM
        from src.agents.schemas import (
            AtendimentoRedatorSchema,
            CaixaRastreabilidadeSchema,
            ContextoRAGSchema,
            SugestaoCopilotoSchema,
            TicketClassification,
            VereditoAuditorSchema,
        )

        caixa_fake = CaixaRastreabilidadeSchema(
            ticket_id="TEST-HITL-01-T1",
            timestamp="2026-11-23T15:00:00-03:00",
            pergunta_cliente="Dashboard travado",
            triagem_inicial=TicketClassification(category="Technical", is_followup=False),
            rag_contexto=ContextoRAGSchema(
                chunk_id="MAN-TECH-001-SEC-03",
                subcategoria="Dashboard",
                score_similaridade=0.5,
                regra_escalonamento_aplicada="Escalar se persistir.",
            ),
            atendimento_n1=AtendimentoRedatorSchema(
                mensagem_enviada_ao_cliente="Limpe o cache do navegador.",
                fonte_tecnica_citada="MAN-TECH-001-SEC-03",
                tentativas_redacao=1,
            ),
            auditoria=VereditoAuditorSchema(
                analise_raciocinio="OK",
                aprovado_para_envio=True,
                redator_alucinou=False,
                citou_fonte=True,
                requer_escalonamento=True,
            ),
            telemetria_tempos_s={"total_pipeline_s": 1.0},
        )
        sugestao = SugestaoCopilotoSchema(
            suggestion_id="SUG-TESTE-01",
            session_id=sessao.session_id,
            tenant_id=sessao.tenant_id,
            pergunta_cliente="Dashboard travado",
            mensagem_sugerida="Limpe o cache do navegador.",
            alerta_escalonamento=True,
            caixa_rastreabilidade=caixa_fake,
            chunks_usados=[{"chunk_id": "MAN-TECH-001-SEC-03"}],
        )
        sessao.salvar_sugestao_pendente(sugestao.suggestion_id, sugestao.model_dump())

        # Antes da confirmação, histórico permanece vazio
        assert len(sessao.historico_mensagens) == 0

        res = pipeline.confirmar_envio_turno(
            sessao=sessao,
            confirmacao=ConfirmacaoHumanaSchema(
                suggestion_id="SUG-TESTE-01",
                acao_humana="ESCALADA_N2",
                mensagem_final_enviada="Encaminhei seu caso ao especialista N2.",
                atendente_id="operador_01",
            ),
        )

        assert res.was_edited is True
        assert res.edit_ratio > 0.0
        assert res.status_sessao == "ESCALADA_N2"
        assert chamadas_resumo["count"] == 1
        assert sessao.historico_mensagens[-1].content == "Encaminhei seu caso ao especialista N2."
        assert sessao.handoff_summary is not None


class TestPipelineMultiTurnoIntegrado:
    """Teste integrado de 2 turnos validando cache e alerta de escalonamento N1 -> N2"""

    def test_conversa_2_turnos_followup_e_escalonamento(self, monkeypatch):
        pipeline = NexusSupportPipeline()
        sessao = SessionMemory(session_id="TEST-E2E-MULTI")

        chamadas_pgvector = {"count": 0}
        chunk_dashboard = [
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

        def mock_buscar_chunks(*args, **kwargs):
            chamadas_pgvector["count"] += 1
            return chunk_dashboard

        monkeypatch.setattr(pipeline.retriever, "buscar_chunks", mock_buscar_chunks)

        caixa_t1 = pipeline.processar_turno_sessao(
            pergunta_cliente="Meu painel principal não carrega os relatórios, fica só uma bolinha girando.",
            sessao=sessao,
            gerar_resumo=False,
        )
        assert caixa_t1.triagem_inicial.category == "Technical"
        assert caixa_t1.rag_contexto.chunk_id == "MAN-TECH-001-SEC-03"
        assert caixa_t1.rag_contexto.reutilizado_do_cache is False
        assert caixa_t1.auditoria.requer_escalonamento is False
        assert chamadas_pgvector["count"] == 1

        caixa_t2 = pipeline.processar_turno_sessao(
            pergunta_cliente="Já limpei o cache no Chrome, desativei a VPN e dei Ctrl+F5 há mais de meia hora, mas continua travado!",
            sessao=sessao,
            gerar_resumo=False,
        )
        assert caixa_t2.triagem_inicial.is_followup is True
        assert caixa_t2.rag_contexto.chunk_id == "MAN-TECH-001-SEC-03"
        assert caixa_t2.rag_contexto.reutilizado_do_cache is True
        assert caixa_t2.auditoria.requer_escalonamento is True
        assert chamadas_pgvector["count"] == 1