from types import SimpleNamespace

from src.agents.schemas import ConfirmacaoHumanaSchema
from src.pipeline_agents import NexusSupportPipeline


class _FakeRepo:
    def __init__(self, sugestao):
        self.sugestao = sugestao
        self.confirmado = None

    def obter_sugestao_pendente(self, session_id: str, suggestion_id: str, tenant_id: str = "default"):
        return self.sugestao

    def obter_transcricao_completa(self, session_id: str, tenant_id: str = "default") -> str:
        return "CLIENTE: Erro persistente no painel."

    def confirmar_turno(self, sugestao, confirmacao, resultado):
        self.confirmado = (sugestao, confirmacao, resultado)
        return None


class _FakeResumidor:
    def __init__(self):
        self.chamadas = 0
        self.ultimo_texto = ""

    def executar(self, resposta_final_cliente: str) -> str:
        self.chamadas += 1
        self.ultimo_texto = resposta_final_cliente
        return "- Ação Tomada: Escalado para N2.\n- Próximo Passo do Cliente: Aguardar especialista."


def test_calculo_diff_edicao():
    sem_edicao, ratio_zero = NexusSupportPipeline._calcular_diff("Olá, tudo bem?", "Olá, tudo bem?")
    editado, ratio_parcial = NexusSupportPipeline._calcular_diff(
        "Olá! Tente limpar o cache do navegador.",
        "Olá! Tente limpar o cache e desativar a VPN.",
    )
    print(f"\n[diff sem edição] was_edited={sem_edicao}, edit_ratio={ratio_zero}")
    print(f"[diff com edição] was_edited={editado}, edit_ratio={ratio_parcial}")

    assert sem_edicao is False
    assert ratio_zero == 0.0
    assert editado is True
    assert 0.0 < ratio_parcial < 1.0


def test_confirmar_envio_n1_nao_chama_resumidor():
    pipeline = NexusSupportPipeline.__new__(NexusSupportPipeline)
    sugestao = SimpleNamespace(
        mensagem_sugerida="Resposta padrão N1.",
        pergunta_cliente="Como reseto a senha?",
        caixa_rastreabilidade=SimpleNamespace(
            triagem_inicial=SimpleNamespace(category="Account")
        ),
    )
    pipeline.session_repo = _FakeRepo(sugestao)
    resumidor = _FakeResumidor()
    pipeline.resumidor = resumidor
    pipeline._agendar_compactacao_se_necessario = lambda *args, **kwargs: None

    confirmacao = ConfirmacaoHumanaSchema(
        suggestion_id="SUG-1",
        acao_humana="ACEITA_SEM_EDICAO",
        mensagem_final_enviada="Resposta padrão N1.",
        atendente_id="n1-01",
    )

    res = pipeline.confirmar_envio_db("sess-1", confirmacao, tenant_id="t1")
    print(
        f"\n[N1 normal] status={res.status_sessao}, was_edited={res.was_edited}, "
        f"edit_ratio={res.edit_ratio}, resumidor_chamadas={resumidor.chamadas}, "
        f"handoff_summary={res.handoff_summary}"
    )

    assert res.was_edited is False
    assert res.edit_ratio == 0.0
    assert res.handoff_summary is None
    assert resumidor.chamadas == 0


def test_confirmar_envio_escalada_n2_chama_resumidor_sob_demanda():
    pipeline = NexusSupportPipeline.__new__(NexusSupportPipeline)
    sugestao = SimpleNamespace(
        mensagem_sugerida="Vou transferir para um especialista.",
        pergunta_cliente="Continua falhando após tentar tudo.",
    )
    pipeline.session_repo = _FakeRepo(sugestao)
    resumidor = _FakeResumidor()
    pipeline.resumidor = resumidor

    confirmacao = ConfirmacaoHumanaSchema(
        suggestion_id="SUG-2",
        acao_humana="ESCALADA_N2",
        mensagem_final_enviada="Vou transferir para um especialista.",
        atendente_id="n1-01",
    )

    res = pipeline.confirmar_envio_db("sess-1", confirmacao, tenant_id="t1")
    print(
        f"\n[Escalada N2] status={res.status_sessao}, resumidor_chamadas={resumidor.chamadas}\n"
        f"Transcrição enviada ao resumidor:\n{resumidor.ultimo_texto}\n"
        f"Resumo gerado:\n{res.handoff_summary}"
    )

    assert res.status_sessao == "ESCALADA_N2"
    assert res.handoff_summary is not None
    assert resumidor.chamadas == 1
    assert "Continua falhando" in resumidor.ultimo_texto
