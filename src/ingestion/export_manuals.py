
import json
import re
from pathlib import Path


# Diretórios do projeto
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "data" / "chunks"
OUTPUT_DIR = BASE_DIR / "data" / "manuals"


def normalizar_nome(nome: str) -> str:
    """Converte o nome em um formato adequado para arquivos."""
    nome = nome.strip().lower()
    nome = re.sub(r"[^\w\s-]", "", nome)
    nome = re.sub(r"[\s-]+", "_", nome)
    return nome


def exportar_manuais():
    # Criar diretório de saída caso não exista
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Localizar todos os documentos de conhecimento
    arquivos_json = sorted(
        INPUT_DIR.glob("base_conhecimento_*.json")
    )

    if not arquivos_json:
        print(f"Nenhum arquivo encontrado em: {INPUT_DIR}")
        return

    sucessos = 0
    erros = 0

    for arquivo in arquivos_json:
        try:
            with open(arquivo, "r", encoding="utf-8") as f:
                dados = json.load(f)

            # Os JSONs possuem uma lista com os documentos
            if not isinstance(dados, list):
                dados = [dados]

            for documento in dados:
                content = documento.get("content")

                if not isinstance(content, str) or not content.strip():
                    print(f"[AVISO] Conteúdo vazio em {arquivo.name}")
                    erros += 1
                    continue

                # Utilizar a categoria como nome do arquivo,
                # com fallback para o nome do JSON original.
                metadata = documento.get("metadata", {})
                categoria = metadata.get("category")

                nome_base = (
                    normalizar_nome(categoria)
                    if categoria
                    else arquivo.stem.replace(
                        "base_conhecimento_", ""
                    )
                )

                caminho_md = OUTPUT_DIR / f"manual_{nome_base}.md"

                # Salvar somente o conteúdo original do documento
                with open(caminho_md, "w", encoding="utf-8") as f:
                    f.write(content.strip())
                    f.write("\n")

                print(f"[OK] {arquivo.name} -> {caminho_md.name}")
                sucessos += 1

        except (json.JSONDecodeError, OSError, AttributeError) as e:
            print(f"[ERRO] {arquivo.name}: {e}")
            erros += 1

    print("\n========== RESULTADO ==========")
    print(f"Manuais exportados: {sucessos}")
    print(f"Erros: {erros}")
    print(f"Diretório de saída: {OUTPUT_DIR}")


if __name__ == "__main__":
    exportar_manuais()
