import pytest
from src.agents.memory import SessionMemory
from src.pipeline_agents import NexusSupportPipeline


class TestSessionMemoryUnitario:
    """Testes unitários rápidos (0s, sem LLM) para a máquina de estado da memória."""

    def test_cache_rag_e_circuit_breaker_3_turnos(self):
        mem = SessionMemory(session_id="TEST-MEM-01", max_turnos_por_topico=3)
        chunk_fake = [{"chunk_id": "MAN-TECH-001-SEC-03", "subcategory": "Dashboard"}]

        # Turno 1: Novo tópico -> não usa cache, turno_no_topico = 1
        usar_cache_t1 = mem.atualizar_contexto_topico("Technical", is_followup=False)
        assert usar_cache_t1 is False
        assert mem.turnos_no_topico_atual == 1
        assert mem.atingiu_limite_topico() is False
        mem.registrar_turno("Pergunta 1", "Resposta 1", chunk_fake, {})

        # Turno 2: Follow-up mesmo tópico -> usa cache, turno_no_topico = 2
        usar_cache_t2 = mem.atualizar_contexto_topico("Technical", is_followup=True)
        assert usar_cache_t2 is True
        assert mem.turnos_no_topico_atual == 2
        assert mem.atingiu_limite_topico() is False
        mem.registrar_turno("Pergunta 2", "Resposta 2", chunk_fake, {})

        # Turno 3: Follow-up mesmo tópico -> usa cache, turno_no_topico = 3 e ATINGE LIMITE!
        usar_cache_t3 = mem.atualizar_contexto_topico("Technical", is_followup=True)
        assert usar_cache_t3 is True
        assert mem.turnos_no_topico_atual == 3
        assert mem.atingiu_limite_topico() is True
        mem.registrar_turno("Pergunta 3", "Resposta 3", chunk_fake, {})

        # Turno 4: Cliente muda de assunto (Billing, is_followup=False) -> reseta contador para 1!
        usar_cache_t4 = mem.atualizar_contexto_topico("Billing", is_followup=False)
        assert usar_cache_t4 is False
        assert mem.turnos_no_topico_atual == 1
        assert mem.atingiu_limite_topico() is False


class TestPipelineMultiTurnoIntegrado:
    """Teste integrado de 2 turnos validando retenção de contexto, cache e transição N1 -> N2."""

    def test_conversa_2_turnos_followup_e_escalonamento(self, monkeypatch):
        pipeline = NexusSupportPipeline()
        sessao = SessionMemory(session_id="TEST-E2E-MULTI", max_turnos_por_topico=3)

        # Contador para provar que o banco vetorial só é consultado no Turno 1
        chamadas_pgvector = {"count": 0}
        chunk_dashboard = [
            {
                "chunk_id": "MAN-TECH-001-SEC-03",
                "category": "Technical",
                "subcategory": "Travamento do Dashboard",
                "similarity_score": 0.4749,
                "fatias": {
                    "sintomas": "Dashboard principal não carrega indicadores, exibindo apenas ícone de carregamento infinito.",
                    "resolucao_n1": "1) Confirmar uso do Google Chrome ou Microsoft Edge atualizados; 2) Limpar cache e cookies do navegador; 3) Desativar VPN corporativa ou AdBlock temporariamente e recarregar a página (Ctrl + F5).",
                    "escalonamento": "Transferir para N2 se o cliente já tiver executado os 3 passos N1 e o travamento persistir por mais de 20 minutos.",
                },
            }
        ]

        def mock_buscar_chunks(*args, **kwargs):
            chamadas_pgvector["count"] += 1
            return chunk_dashboard

        # Substitui apenas a chamada de rede do embedding para evitar APITimeoutError do NIM
        monkeypatch.setattr(pipeline.retriever, "buscar_chunks", mock_buscar_chunks)

        # Turno 1: Problema inicial do Dashboard (Deve buscar no RAG e reter no N1)
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

        # Turno 2: Follow-up dizendo que os passos N1 falharam (Deve usar CACHE e escalar para N2!)
        caixa_t2 = pipeline.processar_turno_sessao(
            pergunta_cliente="Já limpei o cache no Chrome, desativei a VPN e dei Ctrl+F5 há mais de meia hora, mas continua travado!",
            sessao=sessao,
            gerar_resumo=False,
        )
        assert caixa_t2.triagem_inicial.is_followup is True
        assert caixa_t2.rag_contexto.chunk_id == "MAN-TECH-001-SEC-03"
        assert caixa_t2.rag_contexto.reutilizado_do_cache is True
        assert caixa_t2.auditoria.requer_escalonamento is True
        # Prova que o PGVector NÃO foi chamado novamente no Turno 2!
        assert chamadas_pgvector["count"] == 1