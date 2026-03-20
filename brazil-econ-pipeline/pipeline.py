"""
pipeline.py — Orquestrador principal do pipeline Bronze → Silver → Gold.

Executa as quatro etapas em sequência:
  1. Ingestão (coleta das três APIs)
  2. Validação de qualidade (Great Expectations customizado)
  3. Transformação Bronze → Silver
  4. Construção da camada Gold + relatório HTML

Uso:
    python pipeline.py              # execução única
    python pipeline.py --schedule   # modo agendado (diário às 06:00)
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline")


def run_pipeline() -> dict:
    """Executa o pipeline completo end-to-end."""
    start = datetime.utcnow()
    logger.info("=" * 60)
    logger.info("PIPELINE INICIADO")
    logger.info("=" * 60)

    summary = {}

    # ── Etapa 1: Ingestão ────────────────────────────────────────
    logger.info("\n[1/4] INGESTÃO — coletando dados das APIs...")
    os.makedirs("data", exist_ok=True)

    from ingestion.ibge_collector import run_ibge_collection
    from ingestion.bcb_collector import run_bcb_collection
    from ingestion.worldbank_collector import run_worldbank_collection

    ibge_results = run_ibge_collection()
    bcb_results = run_bcb_collection()
    wb_results = run_worldbank_collection()

    summary["ingestion"] = {
        "ibge": ibge_results,
        "bcb": bcb_results,
        "worldbank": wb_results,
    }
    logger.info("Ingestão concluída.")

    # ── Etapa 2: Validação de qualidade ──────────────────────────
    logger.info("\n[2/4] QUALIDADE — validando dados na camada Bronze...")
    from quality.validator import run_all_validations
    suites = run_all_validations()

    failed_critical = [
        k for k, s in suites.items()
        if not s.passed
    ]
    summary["quality"] = {
        "total_suites": len(suites),
        "failed": len(failed_critical),
        "failed_names": failed_critical,
    }

    if failed_critical:
        logger.warning(
            f"Validação: {len(failed_critical)} suite(s) com erros críticos: {failed_critical}"
        )
        logger.warning("Pipeline continua, mas dados inválidos serão marcados.")
    else:
        logger.info("Todos os dados passaram na validação de qualidade.")

    # ── Etapa 3: Transformação Bronze → Silver ───────────────────
    logger.info("\n[3/4] TRANSFORMAÇÃO — Bronze → Silver...")
    from transforms.silver_transformer import run_silver_transforms
    silver_results = run_silver_transforms()
    summary["silver"] = silver_results
    total_silver = sum(silver_results.values())
    logger.info(f"Silver: {total_silver} registros transformados.")

    # ── Etapa 4: Camada Gold + relatório ─────────────────────────
    logger.info("\n[4/4] GOLD — construindo camada analítica e relatório...")
    from gold.gold_builder import run_gold_build
    from gold.report_generator import generate_report

    gold_results = run_gold_build()
    report_path = generate_report()

    summary["gold"] = gold_results
    summary["report"] = str(report_path)

    elapsed = (datetime.utcnow() - start).total_seconds()
    summary["elapsed_seconds"] = round(elapsed, 1)

    logger.info("\n" + "=" * 60)
    logger.info(f"PIPELINE CONCLUÍDO em {elapsed:.1f}s")
    logger.info(f"Relatório: {report_path}")
    logger.info("=" * 60)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Brazil Economic Data Pipeline")
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Modo agendado: executa diariamente às 06:00",
    )
    args = parser.parse_args()

    if args.schedule:
        logger.info("Modo agendado ativado. Próxima execução: 06:00 diário.")
        run_pipeline()  # executar imediatamente ao iniciar
        schedule.every().day.at("06:00").do(run_pipeline)
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        run_pipeline()


if __name__ == "__main__":
    main()
