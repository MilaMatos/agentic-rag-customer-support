from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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
from src.api.dependencies import get_pipeline, get_session_repo
from src.api.main import app
from src.api.routes import check_db_ready


class _FakeAPIRepo:
    def __init__(self):
        self.sessoes: dict[tuple[str, str], dict] = {}
        self.mensagens: dict[tuple[str, str], list[dict]] = {}

    def obter_ou_criar_sessao(
        self,
        session_id: str,
        tenant_id: str = "default",
        customer_name: str | None = None,
        customer_external_id: str | None = None,
    ):
        chave = (tenant_id, session_id)
        if chave not in self.sessoes:
            agora = datetime.now(timezone.utc)
            self.sessoes[chave] = {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "customer_name": customer_name,
                "customer_external_id": customer_external_id,
                "status": "ABERTA",
                "turno_global": 0,
                "turnos_no_topico_atual": 0,
                "categoria_atual": None,
                "handoff_summary": None,
                "auditor_escalation_reason": None,
                "pending_suggestion": None,
                "created_at": agora,
                "updated_at": agora,
                "escalated_at": None,
            }
            self.mensagens[chave] = []
        return SimpleNamespace(**self.sessoes[chave])

    def listar_sessoes(self, tenant_id: str = "default", status=None, limite: int = 50):
        res = []
        for (tid, _), s in self.sessoes.items():
            if tid != tenant_id:
                continue
            if status and s["status"] != status:
                continue
            res.append(self._serializar(s))
        return res

    def listar_fila_especialista(self, tenant_id: str = "default", limite: int = 50):
        return [
            self._serializar(s)
            for (tid, _), s in self.sessoes.items()
            if tid == tenant_id and s["status"] == "ESCALADA_N2"
        ]

    def obter_detalhe_sessao(self, session_id: str, tenant_id: str = "default"):
        chave = (tenant_id, session_id)
        if chave not in self.sessoes:
            return None
        dados = self._serializar(self.sessoes[chave])
        dados["pending_suggestion"] = self.sessoes[chave]["pending_suggestion"]
        dados["auditor_escalation_reason"] = self.sessoes[chave]["auditor_escalation_reason"]
        dados["mensagens"] = list(self.mensagens[chave])
        return dados

    def encerrar_sessao(self, session_id: str, tenant_id: str = "default"):
        chave = (tenant_id, session_id)
        if chave in self.sessoes:
            self.sessoes[chave]["status"] = "ENCERRADA"
            self.sessoes[chave]["pending_suggestion"] = None

    @staticmethod
    def _serializar(s: dict) -> dict:
        return {
            "session_id": s["session_id"],
            "tenant_id": s["tenant_id"],
            "customer_name": s["customer_name"],
            "customer_external_id": s["customer_external_id"],
            "status": s["status"],
            "turno_global": s["turno_global"],
            "turnos_no_topico_atual": s["turnos_no_topico_atual"],
            "categoria_atual": s["categoria_atual"],
            "handoff_summary": s["handoff_summary"],
            "tem_sugestao_pendente": bool(s["pending_suggestion"]),
            "created_at": s["created_at"].isoformat(),
            "updated_at": s["updated_at"].isoformat(),
            "escalated_at": s["escalated_at"].isoformat() if s["escalated_at"] else None,
        }

class _FakeAPIPipeline:
    def __init__(self, repo: _FakeAPIRepo):
        self.repo = repo
        self.sugestoes: dict[str, SugestaoCopilotoSchema] = {}

    def gerar_sugestao_db(self, session_id: str, pergunta_cliente: str, tenant_id: str = "default"):
        caixa = CaixaRastreabilidadeSchema(
            ticket_id=f"{session_id}-T1",
            timestamp=datetime.now(timezone.utc).isoformat(),
            pergunta_cliente=pergunta_cliente,
            triagem_inicial=TicketClassification(
                category="Technical",
                priority="Alta",
                is_followup=False,
                search_query=pergunta_cliente,
            ),
            rag_contexto=ContextoRAGSchema(
                chunk_id="MAN-TECH-001-SEC-03",
                subcategoria="Dashboard",
                score_similaridade=0.87,
                regra_escalonamento_aplicada="Escalar se persistir.",
                reutilizado_do_cache=False,
                turno_no_topico=1,
            ),
            atendimento_n1=AtendimentoRedatorSchema(
                mensagem_enviada_ao_cliente="Tente limpar o cache e pressionar Ctrl+F5.",
                fonte_tecnica_citada="MAN-TECH-001-SEC-03",
                tentativas_redacao=1,
            ),
            auditoria=VereditoAuditorSchema(
                analise_raciocinio="Aderente ao manual.",
                aprovado_para_envio=True,
                redator_alucinou=False,
                citou_fonte=True,
                requer_escalonamento=False,
                feedback_correcao="",
            ),
            telemetria_tempos_s={"total_pipeline_s": 0.42},
        )
        sug = SugestaoCopilotoSchema(
            suggestion_id="SUG-API-001",
            session_id=session_id,
            tenant_id=tenant_id,
            pergunta_cliente=pergunta_cliente,
            mensagem_sugerida="Tente limpar o cache e pressionar Ctrl+F5.",
            alerta_escalonamento=False,
            caixa_rastreabilidade=caixa,
            chunks_usados=[],
        )
        self.sugestoes[sug.suggestion_id] = sug
        sess = self.repo.sessoes[(tenant_id, session_id)]
        sess["pending_suggestion"] = sug.model_dump()
        sess["status"] = "AGUARDANDO_N1"
        sess["categoria_atual"] = "Technical"
        sess["turnos_no_topico_atual"] = 1
        sess["auditor_escalation_reason"] = caixa.auditoria.analise_raciocinio
        return sug

    def confirmar_envio_db(
        self,
        session_id: str,
        confirmacao: ConfirmacaoHumanaSchema,
        tenant_id: str = "default",
    ) -> ResultadoConfirmacaoSchema:
        if confirmacao.suggestion_id not in self.sugestoes:
            raise KeyError("Sugestão não encontrada.")
        sug = self.sugestoes.pop(confirmacao.suggestion_id)
        sess = self.repo.sessoes[(tenant_id, session_id)]
        sess["pending_suggestion"] = None
        sess["turno_global"] += 1

        is_esc = confirmacao.acao_humana == "ESCALADA_N2"
        handoff = "- Problema: Travamento persistente.\n- Ação: Encaminhado para N2." if is_esc else None
        sess["status"] = "ESCALADA_N2" if is_esc else "ABERTA"
        if is_esc:
            sess["handoff_summary"] = handoff
            sess["escalated_at"] = datetime.now(timezone.utc)

        self.repo.mensagens[(tenant_id, session_id)].extend([
            {
                "message_id": "MSG-C1",
                "turn_number": sess["turno_global"],
                "sender_role": "CLIENT",
                "chunk_id": "MAN-TECH-001-SEC-03",
                "content": sug.pergunta_cliente,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "message_id": "MSG-N1",
                "turn_number": sess["turno_global"],
                "sender_role": "HUMAN_N1",
                "chunk_id": "MAN-TECH-001-SEC-03",
                "content": confirmacao.mensagem_final_enviada,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ])

        was_edited = sug.mensagem_sugerida != confirmacao.mensagem_final_enviada
        return ResultadoConfirmacaoSchema(
            suggestion_id=confirmacao.suggestion_id,
            session_id=session_id,
            tenant_id=tenant_id,
            acao_humana=confirmacao.acao_humana,
            atendente_id=confirmacao.atendente_id,
            mensagem_sugerida=sug.mensagem_sugerida,
            mensagem_final_enviada=confirmacao.mensagem_final_enviada,
            was_edited=was_edited,
            edit_ratio=0.25 if was_edited else 0.0,
            status_sessao=sess["status"],
            handoff_summary=handoff,
        )
    def encerrar_sessao_db(self, session_id: str, tenant_id: str = "default") -> None:
        self.repo.encerrar_sessao(session_id=session_id, tenant_id=tenant_id)


@pytest.fixture
def api_client():
    repo = _FakeAPIRepo()
    pipeline = _FakeAPIPipeline(repo)

    app.dependency_overrides[get_session_repo] = lambda: repo
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    app.dependency_overrides[check_db_ready] = lambda: True

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_health_e_ready(api_client: TestClient):
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/ready").json() == {"status": "ready", "database": "connected"}

    app.dependency_overrides[check_db_ready] = lambda: False
    resp_503 = api_client.get("/ready")
    assert resp_503.status_code == 503
    assert resp_503.json()["error_code"] == "DATABASE_UNAVAILABLE"


def test_isolamento_tenant_e_privacidade_view_client(api_client: TestClient):
    headers_a = {"X-Tenant-ID": "tenant-alpha"}
    headers_b = {"X-Tenant-ID": "tenant-beta"}

    # Cria sessão no tenant Alpha
    r_create = api_client.post("/api/v1/sessions", json={"customer_name": "João"}, headers=headers_a)
    assert r_create.status_code == 201
    sid = r_create.json()["session_id"]

    # Tenant Beta não enxerga sessão do Alpha
    r_beta = api_client.get(f"/api/v1/sessions/{sid}/messages?view=agent", headers=headers_b)
    assert r_beta.status_code == 404
    assert r_beta.json()["error_code"] == "SESSION_NOT_FOUND"

    # Envia mensagem -> gera sugestão pendente
    r_msg = api_client.post(
        f"/api/v1/sessions/{sid}/messages",
        json={"content": "Meu painel travou."},
        headers=headers_a,
    )
    assert r_msg.status_code == 202

    # view=client NUNCA recebe pending_suggestion nem metadados internos
    r_client = api_client.get(f"/api/v1/sessions/{sid}/messages?view=client", headers=headers_a).json()
    assert r_client["pending_suggestion"] is None
    assert r_client["categoria_atual"] is None

    # view=agent recebe pending_suggestion
    r_agent = api_client.get(f"/api/v1/sessions/{sid}/messages?view=agent", headers=headers_a).json()
    assert r_agent["pending_suggestion"] is not None
    assert r_agent["pending_suggestion"]["suggestion_id"] == "SUG-API-001"


def test_fluxo_websockets_e_escalonamento_especialista(api_client: TestClient):
    headers = {"X-Tenant-ID": "tenant-ws"}
    sid = api_client.post("/api/v1/sessions", json={"customer_name": "Maria"}, headers=headers).json()["session_id"]

    with (
        api_client.websocket_connect(f"/ws/client/{sid}?tenant_id=tenant-ws") as ws_cli,
        api_client.websocket_connect("/ws/agent?tenant_id=tenant-ws") as ws_ag,
        api_client.websocket_connect("/ws/specialist?tenant_id=tenant-ws") as ws_spec,
    ):
        # 1. Cliente envia mensagem
        resp_msg = api_client.post(
            f"/api/v1/sessions/{sid}/messages",
            json={"content": "Já tentei tudo e continua travado."},
            headers=headers,
        )
        assert resp_msg.status_code == 202

        # Atendente recebe os 3 eventos do copiloto
        ev1 = ws_ag.receive_json()
        ev2 = ws_ag.receive_json()
        ev3 = ws_ag.receive_json()
        assert [ev1["type"], ev2["type"], ev3["type"]] == [
            "client.message_received",
            "copilot.processing",
            "copilot.suggestion_ready",
        ]
        sug_id = ev3["data"]["suggestion_id"]

        # 2. Atendente escala para N2
        resp_conf = api_client.post(
            f"/api/v1/sessions/{sid}/suggestions/{sug_id}/confirm",
            json={
                "attendant_id": "n1-01",
                "human_action": "ESCALADA_N2",
                "human_final_text": "Vou transferir seu atendimento para um especialista.",
            },
            headers=headers,
        )
        assert resp_conf.status_code == 200
        assert resp_conf.json()["session_status"] == "ESCALADA_N2"
        assert resp_conf.json()["handoff_summary"] is not None

        # Cliente recebe apenas aviso sanitizado (sem handoff_summary)
        ev_cli = ws_cli.receive_json()
        assert ev_cli["type"] == "session.escalated"
        assert "handoff_summary" not in ev_cli["data"]

        # Atendente e Especialista recebem o handoff_summary
        ev_ag_esc = ws_ag.receive_json()
        ev_spec_esc = ws_spec.receive_json()
        assert ev_ag_esc["type"] == "session.escalated"
        assert ev_spec_esc["type"] == "session.escalated"
        assert ev_spec_esc["data"]["handoff_summary"] is not None

    # Confere fila e dossiê do especialista via REST + resolução
    fila = api_client.get("/api/v1/specialist/queue", headers=headers).json()
    assert len(fila["items"]) == 1
    assert fila["items"][0]["session_id"] == sid

    dossie = api_client.get(f"/api/v1/specialist/sessions/{sid}", headers=headers).json()
    assert dossie["handoff_summary"] is not None
    assert dossie["last_chunk_id"] == "MAN-TECH-001-SEC-03"
    assert dossie["customer_name"] == "Maria"
    assert dossie["auditor_escalation_reason"] == "Aderente ao manual."

    r_res = api_client.post(f"/api/v1/specialist/sessions/{sid}/resolve", headers=headers)
    assert r_res.status_code == 200
    assert r_res.json()["status"] == "ENCERRADA"

def test_encerrar_sessao_pelo_n1(api_client: TestClient):
    headers = {"X-Tenant-ID": "tenant-n1"}
    sid = api_client.post("/api/v1/sessions", json={"customer_name": "Carlos"}, headers=headers).json()["session_id"]

    resp = api_client.post(f"/api/v1/sessions/{sid}/close", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"session_id": sid, "status": "ENCERRADA"}