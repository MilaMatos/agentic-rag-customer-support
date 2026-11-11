import os
import glob
import json
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import (
    OpenAI,
    APIStatusError,
    APITimeoutError,
    APIConnectionError,
)
from langchain_text_splitters import MarkdownHeaderTextSplitter
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document


# ============================================================
# CONFIGURACOES
# ============================================================

load_dotenv()

# langchain-postgres utiliza psycopg 3.
# Se DATABASE_URL estiver como postgresql+psycopg2://,
# a funcao abaixo converte para postgresql+psycopg://.
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/nexus_knowledge",
)

API_KEY = os.getenv("NVIDIA_API_KEY")
BASE_URL = os.getenv(
    "NVIDIA_BASE_URL",
    "https://integrate.api.nvidia.com/v1",
)

MODEL_NAME = "nvidia/nemotron-3.5-embed-1b"
COLLECTION_NAME = "nexus_knowledge_base"

# Pasta contendo os cinco JSONs:
# data/chunks/base_conhecimento_billing.json etc.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DIRETORIO_MANUAIS = (
    PROJECT_ROOT / "data" / "knowledge_base" / "json"
)

# A NVIDIA foi testada e respondeu individualmente, mas retornou
# HTTP 500 para arrays com 2 ou mais textos.
# Por isso, cada chunk gera seu embedding em uma requisicao separada.
EMBEDDING_REQUEST_TIMEOUT = 90.0
EMBEDDING_MAX_RETRIES = 3
EMBEDDING_RETRY_BASE_SECONDS = 2

# Quantidade de vetores ja calculados enviados ao PostgreSQL por chamada.
# Este lote NAO gera embeddings; apenas grava vetores existentes.
DB_INSERT_BATCH_SIZE = 10

# Dimensao retornada pelo modelo no teste realizado.
EXPECTED_EMBEDDING_DIMENSION = 2048

# Cuidado: True apaga a colecao existente ao inicializar o PGVector.
RECREATE_COLLECTION = True

# Pergunta usada no teste final de recuperacao.
TEST_QUERY = "The dashboard is not loading any data, just a spinning wheel."


# ============================================================
# VALIDACOES E UTILITARIOS
# ============================================================

def normalizar_db_url(url: str) -> str:
    """Adapta URLs antigas para o driver psycopg 3."""
    url = url.strip()

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql+psycopg2://"):
        url = url.replace(
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
            1,
        )

    return url


def validar_configuracoes() -> None:
    """Verifica se as variáveis de ambiente obrigatórias estão carregadas"""
    if not API_KEY:
        raise RuntimeError(
            "NVIDIA_API_KEY nao encontrada. Verifique o arquivo .env."
        )

    if not BASE_URL:
        raise RuntimeError("NVIDIA_BASE_URL nao foi configurada.")

    if not DB_URL:
        raise RuntimeError("DATABASE_URL nao foi configurada.")


def validar_dimensao(vetor: list[float], identificador: str) -> None:
    """Garante que o vetor retornado possui a dimensão esperada pelo banco (2048)"""
    if len(vetor) != EXPECTED_EMBEDDING_DIMENSION:
        raise RuntimeError(
            f"Dimensao inesperada no chunk {identificador}: "
            f"{len(vetor)}. Esperado: {EXPECTED_EMBEDDING_DIMENSION}."
        )


# ============================================================
# NVIDIA NIM - EMBEDDINGS INDIVIDUAIS
# ============================================================

class NvidiaNimEmbeddings(Embeddings):
    """
    Wrapper da NVIDIA NIM.

    Documentos:
        input_type='passage'

    Consultas:
        input_type='query'

    Cada chamada envia exatamente um texto, pois os testes locais
    demonstraram HTTP 500 para lotes com 2, 3, 4 e 5 textos.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = MODEL_NAME,
        max_retries: int = EMBEDDING_MAX_RETRIES,
    ):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=EMBEDDING_REQUEST_TIMEOUT,
            # Retry controlado manualmente abaixo.
            max_retries=0,
        )
        self.model = model
        self.max_retries = max_retries

    def _embed_one(self, text: str, input_type: str) -> list[float]:
        if input_type not in ("passage", "query"):
            raise ValueError(
                "input_type deve ser 'passage' ou 'query'."
            )

        texto = text if text and text.strip() else " "

        for tentativa in range(1, self.max_retries + 1):
            try:
                response = self.client.embeddings.create(
                    input=[texto],
                    model=self.model,
                    encoding_format="float",
                    extra_body={
                        "input_type": input_type,
                        "truncate": "END",
                    },
                )

                if not response.data:
                    raise RuntimeError(
                        "A NVIDIA retornou uma resposta sem embeddings."
                    )

                # Ordena pela posicao retornada pela API.
                item = sorted(
                    response.data,
                    key=lambda resultado: resultado.index,
                )[0]

                vetor = item.embedding

                if not isinstance(vetor, list) or not vetor:
                    raise RuntimeError(
                        "A NVIDIA retornou um embedding vazio ou invalido."
                    )

                return vetor

            except (APIStatusError, APITimeoutError, APIConnectionError) as erro:
                status = getattr(erro, "status_code", None)

                temporario = (
                    isinstance(
                        erro,
                        (APITimeoutError, APIConnectionError),
                    )
                    or status == 429
                    or (status is not None and status >= 500)
                )

                if not temporario or tentativa >= self.max_retries:
                    raise

                espera = EMBEDDING_RETRY_BASE_SECONDS ** tentativa

                print(
                    f"      [RETRY] NVIDIA falhou na tentativa "
                    f"{tentativa}/{self.max_retries}. "
                    f"HTTP={status}. Nova tentativa em {espera}s."
                )
                time.sleep(espera)

        raise RuntimeError("Falha inesperada ao gerar embedding.")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Compatibilidade com a interface LangChain.

        Mesmo que receba varios textos, envia cada um separadamente
        para a NVIDIA.
        """
        embeddings = []

        for indice, texto in enumerate(texts, start=1):
            print(
                f"      -> Gerando embedding individual "
                f"{indice}/{len(texts)}..."
            )
            embeddings.append(
                self._embed_one(texto, input_type="passage")
            )

        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text, input_type="query")


def validar_modelo(embeddings: NvidiaNimEmbeddings) -> None:
    """Valida o modelo de embeddings na NVIDIA NIM."""
    print("1. Validando modelo de Embeddings na NVIDIA NIM...")

    texto_teste = (
        "Procedimento operacional de suporte N1 no ERP NexusTech "
        "para faturamento e login."
    )

    vetor = embeddings._embed_one(texto_teste, input_type="passage")
    validar_dimensao(vetor, "TESTE")

    print(
        f"   -> Modelo validado: {embeddings.model} "
        f"({len(vetor)} dimensoes; requisicao individual)."
    )


# ============================================================
# SECTION-LEVEL CHUNKING
# ============================================================

def carregar_e_fatiar_manuais(
    diretorio_manuais: str,
) -> list[Document]:
    """Lê os manuais JSON e divide o conteúdo por seção"""
    print("\n2. Fatiando Manuais (Section-Level Chunking)...")

    pasta = Path(diretorio_manuais)

    if not pasta.exists():
        raise FileNotFoundError(
            f"Diretorio de manuais nao encontrado: {pasta.resolve()}"
        )

    arquivos_json = sorted(
        glob.glob(str(pasta / "base_conhecimento_*.json"))
    )

    if not arquivos_json:
        raise FileNotFoundError(
            "Nenhum arquivo encontrado com o padrao "
            f"{pasta}/base_conhecimento_*.json"
        )

    print(f"   -> {len(arquivos_json)} arquivo(s) JSON encontrado(s).")

    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "categoria_titulo"),
            ("###", "subcategoria"),
        ],
        strip_headers=False,
    )

    todos_os_chunks: list[Document] = []
    ids_gerados: set[str] = set()

    for caminho in arquivos_json:
        nome_arquivo = Path(caminho).name
        print(f"   -> Lendo: {nome_arquivo}")

        with open(caminho, "r", encoding="utf-8") as arquivo:
            documentos = json.load(arquivo)

        if isinstance(documentos, dict):
            # Aceita tanto um objeto unico quanto uma lista de objetos.
            documentos = [documentos]

        if not isinstance(documentos, list):
            raise ValueError(
                f"O JSON {nome_arquivo} deve conter uma lista "
                "ou um objeto de documento."
            )

        for doc_indice, doc in enumerate(documentos, start=1):
            if not isinstance(doc, dict):
                raise ValueError(
                    f"Documento {doc_indice} de {nome_arquivo} "
                    "nao e um objeto JSON."
                )

            doc_id = doc.get("doc_id")
            conteudo = doc.get("content")
            metadata_original = doc.get("metadata") or {}

            if not doc_id:
                raise ValueError(
                    f"Documento {doc_indice} de {nome_arquivo} "
                    "nao possui doc_id."
                )

            if not isinstance(conteudo, str) or not conteudo.strip():
                raise ValueError(
                    f"Documento {doc_id} nao possui content valido."
                )

            if not isinstance(metadata_original, dict):
                raise ValueError(
                    f"Metadata invalida no documento {doc_id}."
                )

            category = metadata_original.get("category", "Uncategorized")
            source = metadata_original.get("source", nome_arquivo)

            # Mantem a limpeza original do pipeline.
            texto_limpo = re.sub(r"\n-{3,}\n", "\n\n", conteudo)

            secoes = splitter.split_text(texto_limpo)

            for indice_secao, secao in enumerate(secoes, start=1):
                texto_secao = secao.page_content.strip()

                if not texto_secao:
                    continue

                chunk_id = f"{doc_id}-SEC-{indice_secao:02d}"

                if chunk_id in ids_gerados:
                    raise ValueError(
                        f"chunk_id duplicado: {chunk_id}. "
                        "Verifique se doc_id e unico entre os JSONs."
                    )

                ids_gerados.add(chunk_id)

                doc_langchain = Document(
                    page_content=texto_secao,
                    metadata={
                        "chunk_id": chunk_id,
                        "doc_id": str(doc_id),
                        "category": str(category),
                        "subcategory": secao.metadata.get(
                            "subcategoria",
                            "Diretrizes Gerais",
                        ),
                        "source": str(source),
                        "source_file": nome_arquivo,
                    },
                )

                todos_os_chunks.append(doc_langchain)

        print(
            f"      {nome_arquivo}: processamento concluido."
        )

    if not todos_os_chunks:
        raise RuntimeError(
            "Nenhum chunk foi gerado. Verifique o conteudo dos JSONs."
        )

    print(
        f"   -> {len(todos_os_chunks)} chunks gerados "
        f"a partir de {len(arquivos_json)} arquivo(s)."
    )

    return todos_os_chunks


# ============================================================
# GERACAO DOS VETORES
# ============================================================

def gerar_embeddings_individuais(
    documentos: list[Document],
    embeddings: NvidiaNimEmbeddings,
) -> list[list[float]]:
    """Gera os vetores de cada chunk individualmente"""
    print("\n3. Gerando embeddings individuais...")

    vetores: list[list[float]] = []
    total = len(documentos)

    for indice, documento in enumerate(documentos, start=1):
        chunk_id = documento.metadata["chunk_id"]

        print(
            f"   -> Chunk {indice}/{total}: {chunk_id}"
        )

        try:
            vetor = embeddings._embed_one(
                documento.page_content,
                input_type="passage",
            )

            validar_dimensao(vetor, chunk_id)
            vetores.append(vetor)

        except Exception as erro:
            raise RuntimeError(
                f"Falha ao gerar embedding do chunk {chunk_id}. "
                f"Tipo: {type(erro).__name__}. Detalhes: {erro}"
            ) from erro

    if len(vetores) != len(documentos):
        raise RuntimeError(
            f"Quantidade divergente: {len(documentos)} documentos "
            f"e {len(vetores)} embeddings."
        )

    print(
        f"   -> {len(vetores)} embeddings gerados com sucesso."
    )

    return vetores


# ============================================================
# ARMAZENAMENTO NO PGVECTOR
# ============================================================

def armazenar_no_pgvector(
    documentos: list[Document],
    vetores: list[list[float]],
    embeddings: NvidiaNimEmbeddings,
) -> PGVector:
    """
    Insere os documentos e vetores calculados no PostgreSQL/PGVector em lotes
    """
    print("\n4. Conectando ao PostgreSQL (pgvector)...")

    if len(documentos) != len(vetores):
        raise ValueError(
            "A quantidade de documentos e vetores precisa ser igual."
        )

    db_url = normalizar_db_url(DB_URL)

    print(
        "   -> Driver PostgreSQL: psycopg 3."
    )
    print(
        f"   -> Colecao: {COLLECTION_NAME}"
    )
    print(
        f"   -> Insercao em lotes de {DB_INSERT_BATCH_SIZE} "
        "vetores previamente calculados."
    )

    # A colecao so e inicializada/deletada DEPOIS que todos os embeddings
    # foram gerados. Assim, uma falha da NVIDIA nao apaga a colecao anterior.
    vetor_db = PGVector(
        embeddings=embeddings,
        collection_name=COLLECTION_NAME,
        connection=db_url,
        use_jsonb=True,
        pre_delete_collection=RECREATE_COLLECTION,
    )

    textos = [doc.page_content for doc in documentos]
    metadados = [doc.metadata for doc in documentos]
    ids = [doc.metadata["chunk_id"] for doc in documentos]

    total = len(textos)

    for inicio in range(0, total, DB_INSERT_BATCH_SIZE):
        fim = min(inicio + DB_INSERT_BATCH_SIZE, total)

        print(
            f"   -> Gravando vetores {inicio + 1}-{fim} de {total}..."
        )

        vetor_db.add_embeddings(
            texts=textos[inicio:fim],
            embeddings=vetores[inicio:fim],
            metadatas=metadados[inicio:fim],
            ids=ids[inicio:fim],
        )

    print(
        f"   -> {total} vetores gravados na colecao "
        f"'{COLLECTION_NAME}'."
    )

    return vetor_db


# ============================================================
# TESTE DE RECUPERACAO
# ============================================================

def testar_recuperacao(
    vetor_db: PGVector,
    pergunta: str = TEST_QUERY,
    quantidade: int = 3,
) -> None:
    """Executa uma query de validação no PGVector após a ingestão"""
    print("\n5. Testando busca semantica no PGVector...")

    print(f"   Query: {pergunta}")

    resultados = vetor_db.similarity_search_with_score(
        pergunta,
        k=quantidade,
    )

    if not resultados:
        print("   -> Nenhum resultado encontrado.")
        return

    for indice, (documento, distancia) in enumerate(
        resultados,
        start=1,
    ):
        print("\n" + "-" * 65)
        print(f"Top {indice} | Distancia: {distancia:.6f}")
        print(
            f"Categoria: {documento.metadata.get('category')}"
        )
        print(
            f"Subcategoria: {documento.metadata.get('subcategory')}"
        )
        print(
            f"Documento: {documento.metadata.get('doc_id')}"
        )
        print(
            f"Chunk: {documento.metadata.get('chunk_id')}"
        )
        print(f"Trecho: {documento.page_content}")

    print("\n   -> Teste de recuperacao concluido.")


# ============================================================
# EXECUCAO PRINCIPAL
# ============================================================

def processar_e_injetar_vetores() -> None:
    """
    Orquestra o pipeline completo de criação e população do banco vetorial
    """
    validar_configuracoes()

    print("=" * 65)
    print("PIPELINE DE INGESTAO VETORIAL - NEXUSTECH")
    print("=" * 65)

    embeddings = NvidiaNimEmbeddings(
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL_NAME,
    )

    # 1. Validar NVIDIA com uma requisicao individual.
    validar_modelo(embeddings)

    # 2. Ler os JSONs e gerar chunks por secao.
    todos_os_chunks = carregar_e_fatiar_manuais(
        DIRETORIO_MANUAIS
    )

    # 3. Gerar todos os embeddings antes de tocar na colecao.
    todos_os_vetores = gerar_embeddings_individuais(
        todos_os_chunks,
        embeddings,
    )

    # 4. Armazenar os vetores ja calculados, sem chamar a NVIDIA.
    vetor_db = armazenar_no_pgvector(
        documentos=todos_os_chunks,
        vetores=todos_os_vetores,
        embeddings=embeddings,
    )

    # 5. Testar recuperacao. A pergunta usa input_type='query'.
    testar_recuperacao(vetor_db)

    print("\n" + "=" * 65)
    print("INGESTAO VETORIAL CONCLUIDA COM SUCESSO!")
    print("=" * 65)


if __name__ == "__main__":
    try:
        processar_e_injetar_vetores()
    except KeyboardInterrupt:
        print("\nExecucao interrompida pelo usuario.")
        raise
    except Exception as erro:
        print("\n" + "=" * 65)
        print("ERRO NA INGESTAO VETORIAL")
        print("=" * 65)
        print(f"Tipo: {type(erro).__name__}")
        print(f"Detalhes: {erro}")
        raise