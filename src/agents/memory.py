from typing import Any, Optional
from pydantic import BaseModel, Field


class MensagemChat(BaseModel):
    role: str = Field(..., description="'cliente' ou 'suporte_n1'")
    content: str


class SessionMemory(BaseModel):
    """Gerencia o estado multi-turno, cache de RAG e limite de tentativas por tópico."""

    session_id: str
    max_turnos_por_topico: int = Field(default=3)
    janela_historico: int = Field(default=6)

    turno_global: int = Field(default=0)
    turnos_no_topico_atual: int = Field(default=0)
    categoria_atual: Optional[str] = Field(default=None)
    chunks_em_cache: list[dict[str, Any]] = Field(default_factory=list)
    historico_mensagens: list[MensagemChat] = Field(default_factory=list)
    historico_caixas: list[dict[str, Any]] = Field(default_factory=list)

    def obter_historico_formatado(self) -> str:
        """Retorna as últimas mensagens formatadas para injeção nos prompts."""
        if not self.historico_mensagens:
            return ""

        recorte = self.historico_mensagens[-self.janela_historico :]
        linhas = []
        for msg in recorte:
            autor = "CLIENTE" if msg.role == "cliente" else "ATENDENTE N1"
            linhas.append(f"{autor}: {msg.content}")
        return "\n".join(linhas)

    def atualizar_contexto_topico(self, nova_categoria: str, is_followup: bool) -> bool:
        """
        Atualiza contadores de tópico e retorna True se deve reutilizar o chunk em cache,
        ou False se precisa buscar um novo chunk no PGVector.
        """
        self.turno_global += 1

        mesmo_topico = (
            is_followup
            and self.categoria_atual == nova_categoria
            and len(self.chunks_em_cache) > 0
        )

        if mesmo_topico:
            self.turnos_no_topico_atual += 1
            return True

        # Novo tópico ou 1º turno da sessão: reseta contador do tópico
        self.categoria_atual = nova_categoria
        self.turnos_no_topico_atual = 1
        return False

    def atingiu_limite_topico(self) -> bool:
        """Verifica se o cliente ultrapassou o limite de interações no mesmo problema."""
        return self.turnos_no_topico_atual >= self.max_turnos_por_topico

    def registrar_turno(
        self,
        pergunta_cliente: str,
        resposta_agente: str,
        chunks_usados: list[dict[str, Any]],
        caixa_dict: dict[str, Any],
    ) -> None:
        """Salva as mensagens do turno e atualiza o cache de chunks."""
        self.historico_mensagens.append(MensagemChat(role="cliente", content=pergunta_cliente))
        self.historico_mensagens.append(MensagemChat(role="suporte_n1", content=resposta_agente))
        self.chunks_em_cache = chunks_usados
        self.historico_caixas.append(caixa_dict)