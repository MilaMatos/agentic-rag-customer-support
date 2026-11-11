import pandas as pd
import re
from pathlib import Path

# Relação entre subcategorias e categorias
MAPA_CATEGORIAS = {
    "2FA issues": "Account",
    "Change email": "Account",
    "Delete account": "Account",
    "Password reset": "Account",
    "Profile update": "Account",
    "Subscription upgrade": "Account",
    "Charged twice": "Billing",
    "Invoice discrepancy": "Billing",
    "Payment failed": "Billing",
    "Refund status": "Billing",
    "Suspicious charge": "Billing",
    "Update credit card": "Billing",
    "Account hacked": "Fraud",
    "Alert notification": "Fraud",
    "Phishing attempt": "Fraud",
    "Stolen card": "Fraud",
    "Suspicious activity": "Fraud",
    "Unrecognized login": "Fraud",
    "Demo request": "General Inquiry",
    "Feature request": "General Inquiry",
    "Hours of operation": "General Inquiry",
    "Office location": "General Inquiry",
    "Pricing tiers": "General Inquiry",
    "Product question": "General Inquiry",
    "API Error 500": "Technical",
    "App crashing": "Technical",
    "Data not syncing": "Technical",
    "Installation issue": "Technical",
    "Login failed": "Technical",
    "Screen freezes": "Technical"
}

def limpar_texto(texto):
    """Remove saudações e textos aleatórios após a primeira frase."""
    if pd.isna(texto):
        return ""

    texto = str(texto).strip()

    # Remove saudação inicial
    texto = re.sub(r"(?i)^\s*hi support,\s*", "", texto)

    # Normaliza espaços
    texto = re.sub(r"\s+", " ", texto).strip()

    # Mantém somente a primeira frase
    resultado = re.search(r"^.*?[.!?](?=\s|$)", texto)
    if resultado:
        texto = resultado.group(0)

    return texto.strip()

def limpar_dados_tickets(input_path: str, output_path: str):
    """
    Higieniza o CSV bruto, remove PII, valida categorias e exporta tickets limpos
    """
    print("Carregando dataset bruto")
    df = pd.read_csv(input_path)
    total_original = len(df)
    print(f"Registros carregados: {total_original}")

    print("Removendo informações pessoais")
    colunas_para_remover = ["Customer_Name", "Customer_Email"]
    df = df.drop(columns=[col for col in colunas_para_remover if col in df.columns])

    print("Padronizando nomes das colunas")
    df = df.rename(columns={
        "Ticket_Description": "query",
        "Issue_Category": "category"
    })

    print("Limpando descrições dos chamados")
    if "query" not in df.columns:
        raise ValueError("Coluna Ticket_Description não encontrada.")
    df["query"] = df["query"].apply(limpar_texto)

    print("Extraindo subcategorias")
    if "Ticket_Subject" not in df.columns:
        raise ValueError("Coluna Ticket_Subject não encontrada.")
    df["subcategory"] = (
        df["Ticket_Subject"]
        .fillna("")
        .astype(str)
        .str.split(" - ")
        .str[0]
        .str.strip()
    )

    df = df.drop(columns=["Ticket_Subject"])

    print("Verificando registros incompletos")
    campos_obrigatorios = ["category", "subcategory", "query"]
    df[campos_obrigatorios] = df[campos_obrigatorios].replace(r"^\s*$", pd.NA, regex=True)
    df = df.dropna(subset=campos_obrigatorios)

    print("Validando classificação dos chamados")
    df["categoria_esperada"] = df["subcategory"].map(MAPA_CATEGORIAS)
    df["status_validacao"] = "OK"

    df.loc[df["categoria_esperada"].isna(), "status_validacao"] = "SUBCATEGORIA_NAO_RECONHECIDA"

    df.loc[
        df["categoria_esperada"].notna() & (df["category"] != df["categoria_esperada"]),
        "status_validacao"
    ] = "CATEGORIA_INCOMPATIVEL"

    registros_revisao = df[df["status_validacao"] != "OK"].copy()
    df = df[df["status_validacao"] == "OK"].copy()

    df = df.drop(columns=["categoria_esperada", "status_validacao"])

    caminho_saida = Path(output_path)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)
    
    caminho_revisao = caminho_saida.parent / "tickets_para_revisao.csv"

    df.to_csv(caminho_saida, index=False, encoding="utf-8-sig")
    registros_revisao.to_csv(caminho_revisao, index=False, encoding="utf-8-sig")

    print(f"Registros originais: {total_original}")
    print(f"Registros limpos: {len(df)}")
    print(f"\nDataset salvo em: {caminho_saida}")
    print(f"Relatório salvo em: {caminho_revisao}")
    print("\nPipeline de ingestão concluído!")

if __name__ == "__main__":
    limpar_dados_tickets(
        "data/raw/customer_support_tickets.csv",
        "data/cleaned/tickets.csv"
    )