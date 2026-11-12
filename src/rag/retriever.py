import os
import re
import time
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, APITimeoutError, APIConnectionError
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector

load_dotenv()

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/nexus_knowledge",
)
API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL_NAME = "nvidia/nemotron-3.5-embed-1b"
COLLECTION_NAME = "nexus_knowledge_base"


class NvidiaNimQueryEmbeddings(Embeddings):
    """Cliente de embeddings otimizado para consultas em tempo real (input_type='query')."""

    def __init__(self):
        if not API_KEY:
            raise RuntimeError("Chave da API NVIDIA não encontrada no .env.")
        self.client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=15.0, max_retries=0)
        self.model = MODEL_NAME

    def _embed_query(self, text: str) -> list[float]:
        texto = text.strip() if text and text.strip() else " "
        for tentativa in range(1, 4):
            try:
                resp = self.client.embeddings.create(
                    input=[texto],
                    model=self.model,
                    encoding_format="float",
                    extra_body={"input_type": "query", "truncate": "END"},
                )
                return resp.data[0].embedding
            except (APIStatusError, APITimeoutError, APIConnectionError):
                if tentativa >= 3:
                    raise
                time.sleep(1.5 ** tentativa)
        raise RuntimeError("Falha ao gerar embedding da query.")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Este cliente é exclusivo para buscas (queries).")

    def embed_query(self, text: str) -> list[float]:
        return self._embed_query(text)


class NexusRetriever:
    """Interface de busca e fatiamento semântico no PGVector."""

    def __init__(self):
        self.embeddings = NvidiaNimQueryEmbeddings()
        url_limpa = DB_URL.replace("postgresql+psycopg2://", "postgresql+psycopg://")

        self.vector_store = PGVector(
            embeddings=self.embeddings,
            collection_name=COLLECTION_NAME,
            connection=url_limpa,
            use_jsonb=True,
            pre_delete_collection=False,
        )

    @staticmethod
    def _fatiar_conteudo(conteudo: str) -> dict[str, str]:
        """Divide o chunk atômico em seções operacionais sem usar LLM."""
        sint = re.search(
            r"\*\*Contexto e Sintomas.*?\*\*[:\s]*(.*?)(?=\*\*Resolução N1|$)",
            conteudo,
            flags=re.DOTALL | re.IGNORECASE,
        )
        n1 = re.search(
            r"\*\*Resolução N1.*?\*\*[:\s]*(.*?)(?=\*\*Critério de Escalonamento|$)",
            conteudo,
            flags=re.DOTALL | re.IGNORECASE,
        )
        esc = re.search(
            r"\*\*Critério de Escalonamento.*?\*\*[:\s]*(.*)",
            conteudo,
            flags=re.DOTALL | re.IGNORECASE,
        )

        return {
            "sintomas": sint.group(1).strip() if sint else "Não especificado.",
            "resolucao_n1": n1.group(1).strip() if n1 else conteudo,
            "escalonamento": esc.group(1).strip() if esc else "Regra não encontrada.",
        }

    def buscar_chunks(
        self,
        query: str,
        k: int = 1,
        category_filter: Optional[str] = None,
        min_similarity: float = 0.30,
    ) -> list[dict[str, Any]]:
        """
        Realiza busca vetorial filtrada por categoria e aplica nota de corte de similaridade
        """
        filtro = {"category": category_filter} if category_filter else None
        resultados = self.vector_store.similarity_search_with_score(
            query=query, k=k, filter=filtro
        )

        chunks_processados = []
        for rank, (doc, distancia) in enumerate(resultados, start=1):
            score = round(max(0.0, 1.0 - float(distancia)), 4)
            if score < min_similarity:
                continue

            meta = doc.metadata or {}
            fatias = self._fatiar_conteudo(doc.page_content)

            chunks_processados.append({
                "rank": rank,
                "chunk_id": meta.get("chunk_id", "N/A"),
                "category": meta.get("category", "N/A"),
                "subcategory": meta.get("subcategory", "N/A"),
                "similarity_score": score,
                "fatias": fatias,
                "conteudo_original": doc.page_content,
            })

        return chunks_processados