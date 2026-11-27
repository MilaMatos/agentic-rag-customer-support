import argparse
from pathlib import Path
from typing import Optional
import pandas as pd
from src.db.connection import engine


def relatorio_single(experiment_id: Optional[str] = None, exportar_csv: Optional[str] = None) -> None:
    query = "SELECT * FROM eval_results"
    params = {}
    if experiment_id:
        query += " WHERE experiment_id = %(exp)s"
        params["exp"] = experiment_id

    df = pd.read_sql(query, engine, params=params)
    if df.empty:
        print("Nenhum resultado em eval_results.")
        return

    print("\n=== SINGLE-TURN: RESUMO POR EXPERIMENTO ===")
    resumo = df.groupby("experiment_id").agg(
        execucoes=("id", "count"),
        acc_cat_pct=("category_match", lambda s: round(s.mean() * 100, 1)),
        acc_esc_pct=("escalation_match", lambda s: round(s.mean() * 100, 1)),
        aprov_auditor_pct=("aprovado_auditor", lambda s: round(s.mean() * 100, 1)),
        juiz_media=("judge_score_total", lambda s: round(s.mean(), 2)),
        juiz_std=("judge_score_total", lambda s: round(s.std(), 2)),
        lat_p50_s=("total_pipeline_s", lambda s: round(s.quantile(0.50), 2)),
        lat_p95_s=("total_pipeline_s", lambda s: round(s.quantile(0.95), 2)),
        cli_media=("client_score_total", lambda s: round(s.mean(), 2)),
    )
    print(resumo.to_string())

    if exportar_csv:
        saida = Path(exportar_csv)
        saida.parent.mkdir(parents=True, exist_ok=True)
        df.drop(columns=["caixa_completa"]).to_csv(saida, index=False)
        print(f"\nCSV salvo em: {saida.resolve()}")


def relatorio_multiturn(experiment_id: Optional[str] = None, exportar_csv: Optional[str] = None) -> None:
    query = "SELECT * FROM eval_multiturn_results"
    params = {}
    if experiment_id:
        query += " WHERE experiment_id = %(exp)s"
        params["exp"] = experiment_id

    df = pd.read_sql(query, engine, params=params)
    if df.empty:
        print("Nenhum resultado em eval_multiturn_results.")
        return

    print("\n=== MULTI-TURN: RESUMO POR EXPERIMENTO ===")
    resumo = df.groupby("experiment_id").agg(
        conversas=("id", "count"),
        turnos_medios=("total_turnos", lambda s: round(s.mean(), 2)),
        acc_esc_pct=("escalation_match", lambda s: round(s.mean() * 100, 1)),
        cache_hits_medio=("cache_hits", lambda s: round(s.mean(), 2)),
        juiz_media=("judge_score_total", lambda s: round(s.mean(), 2)),
        juiz_std=("judge_score_total", lambda s: round(s.std(), 2)),
        lat_turno_media_s=("latencia_media_turno_s", lambda s: round(s.mean(), 2)),
        lat_turno_p95_s=("latencia_media_turno_s", lambda s: round(s.quantile(0.95), 2)),
        cli_media=("client_score_total", lambda s: round(s.mean(), 2)),
    )
    print(resumo.to_string())

    print("\n=== MULTI-TURN: POR CENÁRIO ===")
    por_cen = df.groupby(["experiment_id", "scenario_id"]).agg(
        runs=("id", "count"),
        acc_esc_pct=("escalation_match", lambda s: round(s.mean() * 100, 1)),
        juiz_media=("judge_score_total", lambda s: round(s.mean(), 2)),
        lat_turno_s=("latencia_media_turno_s", lambda s: round(s.mean(), 2)),
        cli_media=("client_score_total", lambda s: round(s.mean(), 2)),
    )
    print(por_cen.to_string())

    if exportar_csv:
        saida = Path(exportar_csv)
        saida.parent.mkdir(parents=True, exist_ok=True)
        df.drop(columns=["turnos_detalhe"]).to_csv(saida, index=False)
        print(f"\nCSV salvo em: {saida.resolve()}")

def inspecionar_detalhes(modo: str, experiment_id: str, limite: int = 10) -> None:
    tabela = "eval_multiturn_results" if modo == "multi" else "eval_results"
    query = f"SELECT * FROM {tabela} WHERE experiment_id = %(exp)s ORDER BY id ASC LIMIT %(lim)s"
    df = pd.read_sql(query, engine, params={"exp": experiment_id, "lim": limite})
    if df.empty:
        print("Nenhum registro encontrado.")
        return

    for _, row in df.iterrows():
        print("\n" + "=" * 90)
        if modo == "single":
            caixa = row["caixa_completa"] or {}
            atend = caixa.get("atendimento_n1", {})
            aud = caixa.get("auditoria", {})
            print(f"[{row['case_id']} | Run {row['run_index']}] Cat: {row['predicted_category']} (Esp: {row['expected_category']}) | Esc: {row['predicted_escalation']} (Esp: {row['expected_escalation']})")
            print(f"Tempos: {row['telemetria_tempos']} | Tentativas: {row['tentativas_redacao']} | Chunk: {row['chunk_id']}")
            print(f"Pergunta: {row['pergunta']}")
            print(f"Resposta N1: {atend.get('mensagem_enviada_ao_cliente', '')}")
            print(f"Auditor: {aud.get('analise_raciocinio', '')}")
            print(f"Juiz Técnico ({row['judge_score_total']}/10 - {row['judge_criteria']}): {row['judge_reasoning']}")
            print(f"Juiz Cliente ({row['client_score_total']}/10 - {row['client_criteria']}): {row['client_reasoning']}")
        else:
            print(f"[{row['scenario_id']} | Run {row['run_index']}] Turnos: {row['total_turnos']} | Esc: {row['final_escalated']} (Esp: {row['expected_escalation']}) | Média/turno: {row['latencia_media_turno_s']}s")
            print(f"Transcrição:\n{row['transcricao']}")
            if row["handoff_summary"]:
                print(f"\nHandoff N2:\n{row['handoff_summary']}")
            print(f"\nJuiz Técnico ({row['judge_score_total']}/10 - {row['judge_criteria']}): {row['judge_reasoning']}")
            print(f"Juiz Cliente ({row['client_score_total']}/10 - {row['client_criteria']}): {row['client_reasoning']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Relatório estatístico dos benchmarks no PostgreSQL.")
    parser.add_argument("--modo", default="single", choices=["single", "multi"])
    parser.add_argument("--exp", default=None)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--detalhe", action="store_true", help="Imprime conversas, respostas e raciocínio do banco")
    parser.add_argument("--limit", type=int, default=10, help="Limite de registros no modo --detalhe")
    args = parser.parse_args()

    if args.detalhe:
        if not args.exp:
            raise ValueError("Informe --exp ao usar --detalhe.")
        inspecionar_detalhes(modo=args.modo, experiment_id=args.exp, limite=args.limit)
    elif args.modo == "multi":
        relatorio_multiturn(experiment_id=args.exp, exportar_csv=args.csv)
    else:
        relatorio_single(experiment_id=args.exp, exportar_csv=args.csv)
