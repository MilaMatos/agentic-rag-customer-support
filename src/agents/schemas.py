from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class TicketClassification(BaseModel):
    """Contrato de saída do Agente 1 (Classificador)"""
    category: Literal["Technical", "Billing", "Account", "Fraud", "General Inquiry"] = Field(
        description="Technical, Billing, Account, Fraud ou General Inquiry"
    )
    priority: Literal["Baixa", "Media", "Alta", "Critica"] = Field(
        default="Media",
        description="Baixa, Media, Alta ou Critica",
    )
    initial_level: Literal["N1", "N2", "N3"] = Field(
        default="N1",
        description="N1, N2 ou N3",
    )
    triage_justification: str = Field(
        default="",
        description="Motivo resumido da classificação em no máximo 2 frases",
    )
    is_followup: bool = Field(
        default=False,
        description="True se a mensagem atual for continuação/dúvida sobre o mesmo problema do turno anterior.",
    )
    search_query: str = Field(
        default="",
        description="Query limpa e completa otimizada para busca vetorial no PGVector.",
    )


class ContextoRAGSchema(BaseModel):
    """Dados do chunk recuperado no PGVector salvos para rastreabilidade"""
    chunk_id: str
    subcategoria: str
    score_similaridade: float
    regra_escalonamento_aplicada: str
    reutilizado_do_cache: bool = Field(default=False)
    turno_no_topico: int = Field(default=1)


class AtendimentoRedatorSchema(BaseModel):
    """Dados consolidados gerados pelo Agente 2 (Redator N1)"""
    mensagem_enviada_ao_cliente: str
    fonte_tecnica_citada: str
    tentativas_redacao: int


class VereditoAuditorSchema(BaseModel):
    """Contrato de saída do Agente 3 (Auditor de Qualidade e Roteamento)"""
    analise_raciocinio: str
    aprovado_para_envio: bool
    redator_alucinou: bool
    citou_fonte: bool
    requer_escalonamento: bool
    feedback_correcao: str = ""


class CaixaRastreabilidadeSchema(BaseModel):
    """Envelope mestre do ticket contendo todo o histórico, decisões e telemetria"""
    ticket_id: str
    timestamp: str
    pergunta_cliente: str
    triagem_inicial: TicketClassification
    rag_contexto: ContextoRAGSchema
    atendimento_n1: AtendimentoRedatorSchema
    auditoria: VereditoAuditorSchema
    resumo_interno_ticket: Optional[str] = None
    telemetria_tempos_s: dict[str, float]


AcaoHumana = Literal["ACEITA_SEM_EDICAO", "EDITADA", "REJEITADA_MANUAL", "ESCALADA_N2"]
StatusSessao = Literal["ABERTA", "AGUARDANDO_N1", "ESCALADA_N2", "ENCERRADA"]


class SugestaoCopilotoSchema(BaseModel):
    """Saída da Fase 1: sugestão pendente aguardando decisão do atendente N1"""
    suggestion_id: str
    session_id: str
    tenant_id: str = "default"
    pergunta_cliente: str
    mensagem_sugerida: str
    alerta_escalonamento: bool
    caixa_rastreabilidade: CaixaRastreabilidadeSchema
    chunks_usados: list[dict[str, Any]] = Field(default_factory=list)


class ConfirmacaoHumanaSchema(BaseModel):
    """Entrada da Fase 2: decisão e texto efetivamente enviado pelo N1"""
    suggestion_id: str
    acao_humana: AcaoHumana
    mensagem_final_enviada: str
    atendente_id: str = "n1_default"


class ResultadoConfirmacaoSchema(BaseModel):
    """Resultado auditado após envio humano e eventual handoff para N2/N3"""
    suggestion_id: str
    session_id: str
    tenant_id: str = "default"
    acao_humana: AcaoHumana
    atendente_id: str
    mensagem_sugerida: str
    mensagem_final_enviada: str
    was_edited: bool
    edit_ratio: float
    status_sessao: StatusSessao
    handoff_summary: Optional[str] = None