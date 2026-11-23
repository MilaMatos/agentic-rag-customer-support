from typing import Any, Optional
from crewai.tools import tool
from src.rag.retriever import NexusRetriever

_retriever_instance: Optional[NexusRetriever] = None
_ultimos_chunks_recuperados: list[dict[str, Any]] = []


def obter_retriever() -> NexusRetriever:
    """Singleton para reutilizar a conexão do PGVector."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = NexusRetriever()
    return _retriever_instance


def obter_ultimos_chunks_tool() -> list[dict[str, Any]]:
    """Retorna os chunks da última chamada da tool para auditoria e testes."""
    return _ultimos_chunks_recuperados


@tool("buscar_manual_rag_tool")
def buscar_manual_rag_tool(query: str, category: str = "") -> str:
    """
    Busca procedimentos operacionais na Base de Conhecimento (PGVector) da NexusTech.
    Parâmetros:
    - query: Pergunta ou sintoma relatado pelo cliente.
    - category: Categoria opcional (Technical, Billing, Account, Fraud, General Inquiry).
    """
    global _ultimos_chunks_recuperados
    retriever = obter_retriever()

    cat_valida = category.strip() if category and category.strip() else None
    chunks = retriever.buscar_chunks(
        query=query,
        k=1,
        category_filter=cat_valida,
        min_similarity=0.30,
    )
    _ultimos_chunks_recuperados = chunks

    if not chunks:
        return (
            "[Chunk_ID: FORA_DE_ESCOPO]\n"
            "Nenhum manual encontrado com similaridade suficiente (< 0.30). "
            "Informe educadamente que está transferindo para um especialista e cite [[FONTE: FORA_DE_ESCOPO]]."
        )

    blocos = []
    for c in chunks:
        blocos.append(
            f"[Chunk_ID: {c['chunk_id']} | Subcategoria: {c['subcategory']}]\n"
            f"- DIRETRIZES_DE_AUTOATENDIMENTO: {c['fatias']['resolucao_n1']}\n"
            f"- GATILHOS_DE_ESCALONAMENTO_INTERNO: {c['fatias']['escalonamento']}"
        )
    return "\n\n".join(blocos)