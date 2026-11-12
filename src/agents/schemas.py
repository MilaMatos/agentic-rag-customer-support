from typing import Literal, Optional
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


class ContextoRAGSchema(BaseModel):
    """Dados do chunk recuperado no PGVector salvos para rastreabilidade"""
    chunk_id: str
    subcategoria: str
    score_similaridade: float
    regra_escalonamento_aplicada: str


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