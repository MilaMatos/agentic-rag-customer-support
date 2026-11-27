import argparse
import json
from pathlib import Path
import time
from typing import Optional

from sqlalchemy import select

from src.db.connection import SessionLocal, criar_tabelas
from src.db.models import EvalResultDB
from src.eval.judge import AvaliadorDuplo, DEFAULT_TECH_JUDGE
from src.eval.presets import PRESETS_MODELOS
from src.pipeline_agents import ARQUIVO_TESTES, MIN_SIMILARITY, NexusSupportPipeline

import logging
from src.agents.retry import aguardar_conexao

logging.disable(logging.ERROR)



def _ja_executado(experiment_id: str, case_id: str, run_index: int) -> bool:
    with SessionLocal() as db:
        stmt = select(EvalResultDB.id).where(
            EvalResultDB.experiment_id == experiment_id,
            EvalResultDB.case_id == case_id,
            EvalResultDB.run_index == run_index,
        )
        return db.execute(stmt).scalar_one_or_none() is not None


def _espera_escalonamento(caso: dict) -> bool:
    if "deve_escalar" in caso:
        return bool(caso["deve_escalar"])
    esperado = caso.get("esperado") or {}
    nivel = esperado.get("nivel_escalonamento") or caso.get("nivel_inicial", "N1")
    return str(nivel).upper() in ("N2", "N3")


def rodar_benchmark_single_turn(
    experiment_id: str,
    preset_name: str = "copilot_fast_thinking_off",
    repeticoes: int = 10,
    sleep_s: float = 2.5,
    judge_model: Optional[str] = None,
    limite_casos: Optional[int] = None,
    dataset_path: Optional[str] = None,
) -> None:
    criar_tabelas()
    models_cfg = PRESETS_MODELOS[preset_name]
    pipeline = NexusSupportPipeline(model_config=models_cfg)
    juiz = AvaliadorDuplo(
        tech_spec={
            "model": judge_model,
            "enable_thinking": True,
            "max_tokens": 2048,
            "timeout": 90,
        }
        if judge_model
        else DEFAULT_TECH_JUDGE
    )

    caminho_dataset = Path(dataset_path) if dataset_path else ARQUIVO_TESTES
    with open(caminho_dataset, "r", encoding="utf-8") as f:
        casos = json.load(f)

    if limite_casos:
        casos = casos[:limite_casos]

    total_previsto = len(casos) * repeticoes
    concluidos = 0

    try:
        for run_idx in range(1, repeticoes + 1):
            for caso in casos:
                case_id = caso["id_teste"]
                concluidos += 1

                if _ja_executado(experiment_id, case_id, run_idx):
                    print(f"[{concluidos}/{total_previsto}] SKIP {case_id} (run {run_idx}) — checkpoint", flush=True)
                    continue

                try:
                    aguardar_conexao()
                    print(f"[{concluidos}/{total_previsto}] RUN  {case_id} (run {run_idx}/{repeticoes})...", flush=True)
                    caixa = pipeline.processar_ticket(
                        pergunta_cliente=caso["pergunta"],
                        gerar_resumo=False,
                        ticket_id=f"{experiment_id}-{case_id}-R{run_idx}",
                    )

                    chunks = pipeline.retriever.buscar_chunks(
                        query=caso["pergunta"],
                        k=1,
                        category_filter=None,
                        min_similarity=MIN_SIMILARITY,
                    )
                    conteudo_chunk = chunks[0]["conteudo_original"] if chunks else ""

                    exp_cat = caso["categoria"]
                    pred_cat = caixa.triagem_inicial.category
                    exp_esc = _espera_escalonamento(caso)
                    pred_esc = caixa.auditoria.requer_escalonamento

                    avaliacao = juiz.avaliar_single(
                        pergunta=caso["pergunta"],
                        resposta_cliente=caixa.atendimento_n1.mensagem_enviada_ao_cliente,
                        fonte_citada=caixa.atendimento_n1.fonte_tecnica_citada,
                        conteudo_chunk=conteudo_chunk,
                        expected_escalation=exp_esc,
                        predicted_escalation=pred_esc,
                    )

                    registro = EvalResultDB(
                        experiment_id=experiment_id,
                        models_config=models_cfg,
                        case_id=case_id,
                        run_index=run_idx,
                        mode="single_turn",
                        pergunta=caso["pergunta"],
                        expected_category=exp_cat,
                        predicted_category=pred_cat,
                        category_match=(exp_cat == pred_cat),
                        expected_escalation=exp_esc,
                        predicted_escalation=pred_esc,
                        escalation_match=(exp_esc == pred_esc),
                        chunk_id=caixa.rag_contexto.chunk_id,
                        fonte_citada=caixa.atendimento_n1.fonte_tecnica_citada,
                        aprovado_auditor=caixa.auditoria.aprovado_para_envio,
                        redator_alucinou=caixa.auditoria.redator_alucinou,
                        tentativas_redacao=caixa.atendimento_n1.tentativas_redacao,
                        total_pipeline_s=caixa.telemetria_tempos_s["total_pipeline_s"],
                        telemetria_tempos=caixa.telemetria_tempos_s,
                        judge_model=juiz.tech_model_name,
                        judge_score_total=avaliacao["tech"]["score_total"],
                        judge_criteria=avaliacao["tech"]["criteria"],
                        judge_reasoning=avaliacao["tech"]["reasoning"],
                        client_judge_model=juiz.client_model_name,
                        client_score_total=avaliacao["client"]["score_total"],
                        client_criteria=avaliacao["client"]["criteria"],
                        client_reasoning=avaliacao["client"]["reasoning"],
                        caixa_completa=caixa.model_dump(),
                    )

                    with SessionLocal() as db:
                        db.add(registro)
                        db.commit()

                    print(
                        f"   -> Cat: {pred_cat} (OK={exp_cat == pred_cat}) | "
                        f"Esc: {pred_esc} (OK={exp_esc == pred_esc}) | "
                        f"Tec: {avaliacao['tech']['score_total']}/10 | "
                        f"Cli: {avaliacao['client']['score_total']}/10 | "
                        f"Tempo: {caixa.telemetria_tempos_s['total_pipeline_s']}s",
                        flush=True,
                    )
                    time.sleep(sleep_s)

                except KeyboardInterrupt:
                    raise
                except Exception as exc:
                    print(
                        f"   [FALHA] {case_id} (run {run_idx}): {type(exc).__name__} — {str(exc)[:120]}",
                        flush=True,
                    )
                    aguardar_conexao()
                    time.sleep(5.0)
                    continue
    finally:
        pipeline.shutdown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark single-turn com checkpoint em PostgreSQL.")
    parser.add_argument("--exp", required=True, help="ID único do experimento")
    parser.add_argument("--preset", default="copilot_fast_thinking_off", choices=list(PRESETS_MODELOS.keys()))
    parser.add_argument("--runs", type=int, default=10, help="Repetições por pergunta")
    parser.add_argument("--sleep", type=float, default=2.5, help="Pausa em segundos entre execuções")
    parser.add_argument("--judge", default=None, help="Override do modelo do Juiz")
    parser.add_argument("--limit", type=int, default=None, help="Limitar qtd de perguntas")
    parser.add_argument("--dataset", default=None, help="Caminho alternativo de JSON de testes")
    args = parser.parse_args()

    rodar_benchmark_single_turn(
        experiment_id=args.exp,
        preset_name=args.preset,
        repeticoes=args.runs,
        sleep_s=args.sleep,
        judge_model=args.judge,
        limite_casos=args.limit,
        dataset_path=args.dataset,
    )