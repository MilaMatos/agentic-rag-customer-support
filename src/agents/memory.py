from typing import Any, Optional
from pydantic import BaseModel, Field


class MensagemChat(BaseModel):
    role: str = Field(..., description="'cliente' ou 'suporte_n1'")
    content: str


class SessionMemory(BaseModel):
    """Gerencia estado conversacional, cache de RAG e sugestões pendentes HITL."""

    session_id: str
    tenant_id: str = Field(default="default")
    janela_historico: int = Field(default=6)

    status: str = Field(default="ABERTA")
    turno_global: int = Field(default=0)
    turnos_no_topico_atual: int = Field(default=0)
    categoria_atual: Optional[str] = Field(default=None)
    handoff_summary: Optional[str] = Field(default=None)
    chunks_em_cache: list[dict[str, Any]] = Field(default_factory=list)
    historico_mensagens: list[MensagemChat] = Field(default_factory=list)
    historico_caixas: list[dict[str, Any]] = Field(default_factory=list)
    sugestoes_pendentes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def obter_historico_formatado(self, completo: bool = False) -> str:
        """Retorna mensagens formatadas (janela recente ou transcrição completa)."""
        if not self.historico_mensagens:
            return ""

        recorte = (
            self.historico_mensagens
            if completo
            else self.historico_mensagens[-self.janela_historico :]
        )
        linhas = []
        for msg in recorte:
            autor = "CLIENTE" if msg.role == "cliente" else "ATENDENTE N1"
            linhas.append(f"{autor}: {msg.content}")
        return "\n".join(linhas)

    def avaliar_contexto_topico(self, nova_categoria: str, is_followup: bool) -> tuple[bool, int]:
        """Retorna (reutilizar_cache, proximo_turno_no_topico) sem mutar estado."""
        mesmo_topico = (
            is_followup
            and self.categoria_atual == nova_categoria
            and len(self.chunks_em_cache) > 0
        )
        if mesmo_topico:
            return True, self.turnos_no_topico_atual + 1
        return False, 1

    def salvar_sugestao_pendente(self, suggestion_id: str, payload: dict[str, Any]) -> None:
        self.sugestoes_pendentes[suggestion_id] = payload
        self.status = "AGUARDANDO_N1"

    def consumir_sugestao_pendente(self, suggestion_id: str) -> dict[str, Any]:
        if suggestion_id not in self.sugestoes_pendentes:
            raise KeyError(f"Sugestão '{suggestion_id}' não encontrada na sessão '{self.session_id}'.")
        return self.sugestoes_pendentes.pop(suggestion_id)

    def registrar_turno(
        self,
        pergunta_cliente: str,
        resposta_enviada: str,
        categoria: str,
        is_followup: bool,
        chunks_usados: list[dict[str, Any]],
        caixa_dict: dict[str, Any],
    ) -> None:
        """Efetiva o turno após confirmação humana e atualiza cache/contadores."""
        reutilizou, proximo_turno_topico = self.avaliar_contexto_topico(categoria, is_followup)
        self.turno_global += 1
        self.categoria_atual = categoria
        self.turnos_no_topico_atual = proximo_turno_topico

        self.historico_mensagens.append(MensagemChat(role="cliente", content=pergunta_cliente))
        self.historico_mensagens.append(MensagemChat(role="suporte_n1", content=resposta_enviada))
        self.chunks_em_cache = chunks_usados if not reutilizou else self.chunks_em_cache
        self.historico_caixas.append(caixa_dict)