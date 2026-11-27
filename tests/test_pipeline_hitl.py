from types import SimpleNamespace

from src.agents.schemas import (
    ConfirmacaoHumanaSchema,
    TicketClassification,
    VereditoAuditorSchema,
)
from src.pipeline_agents import NexusSupportPipeline


def _chunk_exemplo(chunk_id: str = "MAN-TECH-001", categoria: str = "Technical", score: float = 0.85) -> dict:
    return {
        "rank": 1,
        "chunk_id": chunk_id,
        "category": categoria,
        "subcategory": "Dashboard",
        "similarity_score": score,
        "fatias": {
            "sintomas": "Tela travada",
            "resolucao_n1": "Limpe o cache e tente novamente.",
            "escalonamento": "Escalar se persistir após os passos.",
        },
        "conteudo_original": "Manual técnico de exemplo.",
    }


class _FakeRetriever:
    def __init__(self, chunks_por_chamada=None):
        self.chunks_por_chamada = list(chunks_por_chamada or [[_chunk_exemplo()]])
        self.chamadas_buscar = 0
        self.ultima_query = None
        self.ultima_categoria = None
        self.embeddings = SimpleNamespace(embed_query=lambda q: [0.1, 0.2, 0.3])

    def buscar_chunks(self, query: str, k: int = 1, category_filter=None, min_similarity: float = 0.30):
        self.chamadas_buscar += 1
        self.ultima_query = query
        self.ultima_categoria = category_filter
        if self.chunks_por_chamada:
            return self.chunks_por_chamada.pop(0)
        return []

    def buscar_chunks_por_vetor(self, embedding, k: int = 1, category_filter=None, min_similarity: float = 0.30):
        return self.buscar_chunks(
            query="vetor_turno_1",
            k=k,
            category_filter=category_filter,
            min_similarity=min_similarity,
        )


class _FakeClassificador:
    def __init__(self, classificacoes: list[TicketClassification]):
        self._classificacoes = list(classificacoes)
        self.chamadas = 0

    def executar(self, pergunta_cliente: str, historico_recente: str = "", categoria_anterior: str = ""):
        self.chamadas += 1
        idx = min(self.chamadas - 1, len(self._classificacoes) - 1)
        return self._classificacoes[idx].model_copy(deep=True)


class _FakeRedator:
    def executar(self, pergunta_cliente: str, chunks, feedback_anterior=None, categoria="", historico_conversa="", forcar_escalonamento_limite=False):
        cid = chunks[0]["chunk_id"] if chunks else "FORA_DE_ESCOPO"
        return {
            "mensagem_cliente": f"Sugestão para '{pergunta_cliente}' baseada em {cid}.",
            "fonte_citada": cid,
            "texto_completo_auditoria": f"Sugestão para '{pergunta_cliente}'\n\n[[FONTE: {cid}]]",
        }


class _FakeAuditor:
    def executar(self, pergunta_cliente: str, resposta_redator: str, chunks, historico_conversa="", forcar_escalonamento_limite=False):
        return VereditoAuditorSchema(
            analise_raciocinio="Resposta aderente ao manual.",
            aprovado_para_envio=True,
            redator_alucinou=False,
            citou_fonte=True,
            requer_escalonamento=False,
            feedback_correcao="",
        )


class _FakeResumidor:
    def executar(self, resposta_final_cliente: str) -> str:
        return "- Ação Tomada: Escalado.\n- Próximo Passo do Cliente: Aguardar."


class _FakeSessionRepo:
    def __init__(self, sessao_inicial=None):
        self.sessao = sessao_inicial or SimpleNamespace(
            session_id="sess-1",
            tenant_id="tenant-a",
            status="ABERTA",
            turno_global=0,
            turnos_no_topico_atual=0,
            categoria_atual=None,
            chunks_em_cache=[],
            pending_suggestion=None,
        )
        self.sugestoes_salvas = []
        self.mensagens_confirmadas = []

    def obter_ou_criar_sessao(self, session_id: str, tenant_id: str = "default"):
        return self.sessao

    def obter_historico_recente(self, session_id: str, tenant_id: str = "default", limite_mensagens: int = 4) -> str:
        if not self.mensagens_confirmadas:
            return ""
        return "\n".join(f"CLIENTE: {m['pergunta']}\nATENDENTE N1: {m['resposta']}" for m in self.mensagens_confirmadas[-2:])

    def obter_contexto_topico(self, session_id: str, categoria: str, tenant_id: str = "default") -> dict:
        return {
            "historico_formatado": self.obter_historico_recente(session_id, tenant_id=tenant_id),
            "cached_chunks": self.sessao.chunks_em_cache or [],
            "resumo_anterior": "",
            "texto_novo": "",
            "ultimo_turno_topico": self.sessao.turnos_no_topico_atual,
            "precisa_compactar": False,
        }

    def salvar_sugestao_pendente(self, sugestao) -> None:
        self.sugestoes_salvas.append(sugestao)
        self.sessao.pending_suggestion = sugestao.model_dump()
        self.sessao.status = "AGUARDANDO_N1"

    def obter_sugestao_pendente(self, session_id: str, suggestion_id: str, tenant_id: str = "default"):
        for s in reversed(self.sugestoes_salvas):
            if s.suggestion_id == suggestion_id:
                return s
        raise KeyError(suggestion_id)

    def obter_transcricao_completa(self, session_id: str, tenant_id: str = "default") -> str:
        return self.obter_historico_recente(session_id, tenant_id=tenant_id)

    def confirmar_turno(self, sugestao, confirmacao, resultado):
        self.mensagens_confirmadas.append({
            "pergunta": sugestao.pergunta_cliente,
            "resposta": resultado.mensagem_final_enviada,
        })
        cat = sugestao.caixa_rastreabilidade.triagem_inicial.category
        is_followup = sugestao.caixa_rastreabilidade.triagem_inicial.is_followup
        self.sessao.turno_global += 1
        self.sessao.turnos_no_topico_atual = (
            self.sessao.turnos_no_topico_atual + 1 if (is_followup and self.sessao.categoria_atual == cat) else 1
        )
        self.sessao.categoria_atual = cat
        self.sessao.chunks_em_cache = sugestao.chunks_usados
        self.sessao.pending_suggestion = None
        self.sessao.status = resultado.status_sessao
        return None


def _montar_pipeline(repo, retriever, classificador):
    p = NexusSupportPipeline.__new__(NexusSupportPipeline)
    p.session_repo = repo
    p.retriever = retriever
    p.classificador = classificador
    p.redator = _FakeRedator()
    p.auditor = _FakeAuditor()
    p.resumidor = _FakeResumidor()
    return p


def test_turno_1_gera_sugestao_pendente_sem_confirmar():
    repo = _FakeSessionRepo()
    retriever = _FakeRetriever([[_chunk_exemplo("MAN-TECH-001", "Technical", 0.88)]])
    classificador = _FakeClassificador([
        TicketClassification(
            category="Technical",
            priority="Alta",
            initial_level="N1",
            is_followup=True,  # No turno 1 deve ser forçado para False
            search_query="painel nao carrega relatorios",
        )
    ])
    pipeline = _montar_pipeline(repo, retriever, classificador)

    sug = pipeline.gerar_sugestao_db("sess-1", "Meu painel não carrega.", tenant_id="tenant-a")
    print(
        f"\n[Turno 1] suggestion_id={sug.suggestion_id}, cache={sug.caixa_rastreabilidade.rag_contexto.reutilizado_do_cache}, "
        f"turno_topico={sug.caixa_rastreabilidade.rag_contexto.turno_no_topico}, msgs_confirmadas={len(repo.mensagens_confirmadas)}"
    )

    assert sug.caixa_rastreabilidade.triagem_inicial.is_followup is False
    assert sug.caixa_rastreabilidade.rag_contexto.reutilizado_do_cache is False
    assert sug.caixa_rastreabilidade.rag_contexto.turno_no_topico == 1
    assert retriever.chamadas_buscar == 1
    assert len(repo.sugestoes_salvas) == 1
    assert len(repo.mensagens_confirmadas) == 0


def test_fluxo_multiturno_continua_topico_e_troca_topico():
    chunk_tech = _chunk_exemplo("MAN-TECH-001", "Technical", 0.88)
    chunk_billing = _chunk_exemplo("MAN-BILL-002", "Billing", 0.91)

    repo = _FakeSessionRepo()
    retriever = _FakeRetriever([[chunk_tech], [chunk_billing]])
    classificador = _FakeClassificador([
        TicketClassification(category="Technical", priority="Alta", is_followup=False, search_query="erro painel"),
        TicketClassification(category="Technical", priority="Alta", is_followup=True, search_query="ainda travando painel"),
        TicketClassification(category="Billing", priority="Media", is_followup=False, search_query="segunda via fatura"),
    ])
    pipeline = _montar_pipeline(repo, retriever, classificador)

    # Turno 1: gera -> confirma
    sug1 = pipeline.gerar_sugestao_db("sess-1", "Painel travou", tenant_id="tenant-a")
    pipeline.confirmar_envio_db(
        "sess-1",
        ConfirmacaoHumanaSchema(
            suggestion_id=sug1.suggestion_id,
            acao_humana="ACEITA_SEM_EDICAO",
            mensagem_final_enviada=sug1.mensagem_sugerida,
        ),
        tenant_id="tenant-a",
    )

    # Turno 2: mesmo tópico (reutiliza cache, não chama retriever)
    sug2 = pipeline.gerar_sugestao_db("sess-1", "Limpei o cache e continua igual", tenant_id="tenant-a")
    print(
        f"\n[Turno 2 - mesmo tópico] cache={sug2.caixa_rastreabilidade.rag_contexto.reutilizado_do_cache}, "
        f"turno_topico={sug2.caixa_rastreabilidade.rag_contexto.turno_no_topico}, buscas_totais={retriever.chamadas_buscar}"
    )
    assert sug2.caixa_rastreabilidade.rag_contexto.reutilizado_do_cache is True
    assert sug2.caixa_rastreabilidade.rag_contexto.turno_no_topico == 2
    assert retriever.chamadas_buscar == 1

    pipeline.confirmar_envio_db(
        "sess-1",
        ConfirmacaoHumanaSchema(
            suggestion_id=sug2.suggestion_id,
            acao_humana="ACEITA_SEM_EDICAO",
            mensagem_final_enviada=sug2.mensagem_sugerida,
        ),
        tenant_id="tenant-a",
    )

    # Turno 3: troca de tópico para Billing (busca novo chunk e zera contagem no tópico para 1)
    sug3 = pipeline.gerar_sugestao_db("sess-1", "Quero ver minha última fatura", tenant_id="tenant-a")
    print(
        f"[Turno 3 - novo tópico] cat={sug3.caixa_rastreabilidade.triagem_inicial.category}, "
        f"cache={sug3.caixa_rastreabilidade.rag_contexto.reutilizado_do_cache}, "
        f"turno_topico={sug3.caixa_rastreabilidade.rag_contexto.turno_no_topico}, buscas_totais={retriever.chamadas_buscar}"
    )
    assert sug3.caixa_rastreabilidade.triagem_inicial.category == "Billing"
    assert sug3.caixa_rastreabilidade.rag_contexto.reutilizado_do_cache is False
    assert sug3.caixa_rastreabilidade.rag_contexto.turno_no_topico == 1
    assert retriever.chamadas_buscar == 2