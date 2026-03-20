"""
bcb_collector.py — Coleta indicadores do Banco Central via API SGS (OLINDA).

Indicadores coletados:
  - Selic (código 432): taxa básica de juros ao ano
  - Câmbio USD (código 1): R$/USD taxa de câmbio diária (agrega em mensal)
  - Reservas internacionais (código 3546): em USD bilhões

API pública, sem autenticação. Documentação: https://dadosabertos.bcb.gov.br/
"""

import logging
from datetime import datetime, date
from collections import defaultdict

import requests

from database import SessionLocal, engine
from models import Base, BronzeBCB

logger = logging.getLogger(__name__)

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"

BCB_SERIES = {
    "selic":               {"code": 432,  "unit": "% a.a.", "freq": "monthly"},
    "cambio_usd":          {"code": 1,    "unit": "R$/USD", "freq": "daily"},
    "reservas_internacionais": {"code": 3546, "unit": "USD bi", "freq": "monthly"},
    "ipca_expectativa_12m": {"code": 6981, "unit": "%",     "freq": "monthly"},
}


def _simulate_bcb(indicator: str, cfg: dict) -> list[dict]:
    """Dados sintéticos para uso sem conexão."""
    import random
    rng = random.Random(hash(indicator + "bcb"))

    defaults = {
        "selic": (2.0, 14.75),
        "cambio_usd": (4.80, 6.20),
        "reservas_internacionais": (280, 360),
        "ipca_expectativa_12m": (3.5, 6.5),
    }
    low, high = defaults.get(indicator, (0, 100))

    records = []
    for year in range(2022, 2025):
        for month in range(1, 13):
            if year == 2024 and month > 9:
                break
            date_str = f"{year}-{month:02d}-01"
            val = round(rng.uniform(low, high), 2)
            records.append({
                "indicator": indicator,
                "reference_date": date_str,
                "value": val,
                "series_code": cfg["code"],
            })
    return records


def fetch_bcb(indicator: str) -> list[dict]:
    """
    Busca série do BCB SGS.
    Para séries diárias (câmbio), agrega em média mensal.
    """
    cfg = BCB_SERIES[indicator]
    url = SGS_URL.format(code=cfg["code"])
    params = {"formato": "json", "dataInicial": "01/01/2022", "dataFinal": "31/12/2024"}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        raw = resp.json()

        # Para séries diárias: agregar em mensal (média)
        if cfg["freq"] == "daily":
            monthly: dict = defaultdict(list)
            for item in raw:
                try:
                    d = datetime.strptime(item["data"], "%d/%m/%Y")
                    key = f"{d.year}-{d.month:02d}-01"
                    monthly[key].append(float(item["valor"].replace(",", ".")))
                except (ValueError, KeyError):
                    continue
            records = [
                {
                    "indicator": indicator,
                    "reference_date": k,
                    "value": round(sum(v) / len(v), 4),
                    "series_code": cfg["code"],
                }
                for k, v in monthly.items()
                if v
            ]
        else:
            records = []
            for item in raw:
                try:
                    d = datetime.strptime(item["data"], "%d/%m/%Y")
                    date_str = f"{d.year}-{d.month:02d}-01"
                    val = float(item["valor"].replace(",", "."))
                    records.append({
                        "indicator": indicator,
                        "reference_date": date_str,
                        "value": val,
                        "series_code": cfg["code"],
                    })
                except (ValueError, KeyError):
                    continue

        logger.info(f"BCB '{indicator}': {len(records)} registros coletados.")
        return records

    except requests.RequestException as e:
        logger.warning(f"BCB API indisponível ({e}). Usando dados simulados.")
        return _simulate_bcb(indicator, cfg)


def persist_bcb(records: list[dict]) -> int:
    """Salva registros novos no bronze, ignora duplicatas."""
    inserted = 0
    with SessionLocal() as session:
        for r in records:
            exists = (
                session.query(BronzeBCB)
                .filter_by(indicator=r["indicator"], reference_date=r["reference_date"])
                .first()
            )
            if not exists:
                session.add(BronzeBCB(**r))
                inserted += 1
        session.commit()
    return inserted


def run_bcb_collection() -> dict:
    """Coleta todos os indicadores BCB configurados."""
    Base.metadata.create_all(bind=engine)
    results = {}
    for indicator in BCB_SERIES:
        records = fetch_bcb(indicator)
        inserted = persist_bcb(records)
        results[indicator] = {"fetched": len(records), "inserted": inserted}
        logger.info(f"  BCB {indicator}: {inserted} novos registros.")
    return results
