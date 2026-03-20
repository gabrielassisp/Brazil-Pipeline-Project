"""
worldbank_collector.py — Coleta indicadores do World Bank API para comparativo global.

Coleta GDP growth, inflação e desemprego de Brasil, EUA, Argentina e média mundial
para contextualizar os indicadores brasileiros globalmente.

API pública, sem autenticação. Documentação: https://datahelpdesk.worldbank.org/
"""

import logging
from datetime import datetime

import requests

from database import SessionLocal, engine
from models import Base, BronzeWorldBank

logger = logging.getLogger(__name__)

WB_URL = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"

COUNTRIES = ["BR", "US", "AR", "WLD"]  # Brasil, EUA, Argentina, Mundo

WB_INDICATORS = {
    "NY.GDP.MKTP.KD.ZG": "PIB crescimento anual (%)",
    "FP.CPI.TOTL.ZG":    "Inflação CPI anual (%)",
    "SL.UEM.TOTL.ZS":    "Desemprego (% força de trabalho)",
}


def _simulate_wb(country: str, indicator_code: str) -> list[dict]:
    """Dados sintéticos para uso sem conexão."""
    import random
    rng = random.Random(hash(country + indicator_code))

    ranges = {
        "NY.GDP.MKTP.KD.ZG": (-5, 6),
        "FP.CPI.TOTL.ZG": (0, 15),
        "SL.UEM.TOTL.ZS": (3, 15),
    }
    low, high = ranges.get(indicator_code, (0, 10))
    return [
        {
            "country_code": country,
            "indicator_code": indicator_code,
            "year": y,
            "value": round(rng.uniform(low, high), 2),
        }
        for y in range(2019, 2024)
    ]


def fetch_worldbank(country: str, indicator_code: str) -> list[dict]:
    """Busca indicador do World Bank para um país."""
    url = WB_URL.format(country=country, indicator=indicator_code)
    params = {"format": "json", "date": "2019:2023", "per_page": 10}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data or len(data) < 2:
            return _simulate_wb(country, indicator_code)

        records = []
        for item in data[1]:
            if item.get("value") is None:
                continue
            records.append({
                "country_code": country,
                "indicator_code": indicator_code,
                "year": int(item["date"]),
                "value": float(item["value"]),
            })

        return records

    except requests.RequestException as e:
        logger.warning(f"World Bank indisponível ({e}). Usando dados simulados.")
        return _simulate_wb(country, indicator_code)


def persist_worldbank(records: list[dict]) -> int:
    """Salva no bronze, ignora duplicatas por (country, indicator, year)."""
    inserted = 0
    with SessionLocal() as session:
        for r in records:
            exists = (
                session.query(BronzeWorldBank)
                .filter_by(
                    country_code=r["country_code"],
                    indicator_code=r["indicator_code"],
                    year=r["year"],
                )
                .first()
            )
            if not exists:
                session.add(BronzeWorldBank(**r))
                inserted += 1
        session.commit()
    return inserted


def run_worldbank_collection() -> dict:
    """Coleta todos os indicadores do World Bank para todos os países."""
    Base.metadata.create_all(bind=engine)
    results = {}
    for indicator_code in WB_INDICATORS:
        total_fetched = 0
        total_inserted = 0
        for country in COUNTRIES:
            records = fetch_worldbank(country, indicator_code)
            inserted = persist_worldbank(records)
            total_fetched += len(records)
            total_inserted += inserted
        results[indicator_code] = {"fetched": total_fetched, "inserted": total_inserted}
        logger.info(f"  WorldBank {indicator_code}: {total_inserted} novos registros.")
    return results
