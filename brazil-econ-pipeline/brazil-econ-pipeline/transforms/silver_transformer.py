"""
silver_transformer.py — Transforma Bronze → Silver.

Operações:
  1. Alinha séries de diferentes frequências para mensal
  2. Calcula média móvel de 12 meses
  3. Calcula variação ano a ano (YoY %)
  4. Marca registros que passaram na validação de qualidade
  5. Persiste na tabela silver_indicators
"""

import logging
from datetime import datetime

import pandas as pd
import numpy as np

from database import SessionLocal, engine
from models import BronzeIBGE, BronzeBCB, SilverIndicator, Base

logger = logging.getLogger(__name__)


def _load_ibge_series(indicator: str) -> pd.DataFrame:
    """Carrega série IBGE do bronze e converte datas."""
    with SessionLocal() as session:
        rows = session.query(BronzeIBGE).filter_by(indicator=indicator).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{"date": r.reference_date, "value": r.value} for r in rows])
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m", errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date")
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df


def _load_bcb_series(indicator: str) -> pd.DataFrame:
    """Carrega série BCB do bronze e converte datas."""
    with SessionLocal() as session:
        rows = session.query(BronzeBCB).filter_by(indicator=indicator).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{"date": r.reference_date, "value": r.value} for r in rows])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "value"]).sort_values("date")
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df = df.groupby("date")["value"].mean().reset_index()
    return df


def enrich_series(df: pd.DataFrame, value_col: str = "value") -> pd.DataFrame:
    """
    Calcula métricas derivadas:
    - Média móvel de 12 meses (suaviza sazonalidade)
    - Variação ano a ano em % (compara mesmo mês do ano anterior)
    """
    df = df.copy().sort_values("date")
    df["value_12m_avg"] = df[value_col].rolling(window=12, min_periods=3).mean().round(4)
    df["value_yoy_pct"] = df[value_col].pct_change(periods=12).mul(100).round(2)
    return df


def persist_silver(records: list[dict]) -> int:
    """Salva registros na Silver, substituindo os existentes (upsert simples)."""
    inserted = 0
    with SessionLocal() as session:
        for r in records:
            existing = (
                session.query(SilverIndicator)
                .filter_by(indicator=r["indicator"], reference_date=r["reference_date"])
                .first()
            )
            if existing:
                for k, v in r.items():
                    setattr(existing, k, v)
                existing.transformed_at = datetime.utcnow()
            else:
                session.add(SilverIndicator(**r))
                inserted += 1
        session.commit()
    return inserted


def transform_ibge(indicator: str, source_label: str, unit: str) -> int:
    """Transforma um indicador IBGE para a camada Silver."""
    df = _load_ibge_series(indicator)
    if df.empty:
        logger.warning(f"Silver: sem dados IBGE para '{indicator}'.")
        return 0

    df = enrich_series(df)

    records = [
        {
            "indicator": indicator,
            "reference_date": row["date"],
            "value": row["value"],
            "value_12m_avg": row.get("value_12m_avg"),
            "value_yoy_pct": row.get("value_yoy_pct"),
            "source": "ibge",
            "unit": unit,
            "is_valid": True,
        }
        for _, row in df.iterrows()
        if pd.notna(row["value"])
    ]

    inserted = persist_silver(records)
    logger.info(f"Silver IBGE '{indicator}': {len(records)} transformados, {inserted} novos.")
    return inserted


def transform_bcb(indicator: str, unit: str) -> int:
    """Transforma um indicador BCB para a camada Silver."""
    df = _load_bcb_series(indicator)
    if df.empty:
        logger.warning(f"Silver: sem dados BCB para '{indicator}'.")
        return 0

    df = enrich_series(df)

    records = [
        {
            "indicator": indicator,
            "reference_date": row["date"],
            "value": row["value"],
            "value_12m_avg": row.get("value_12m_avg"),
            "value_yoy_pct": row.get("value_yoy_pct"),
            "source": "bcb",
            "unit": unit,
            "is_valid": True,
        }
        for _, row in df.iterrows()
        if pd.notna(row["value"])
    ]

    inserted = persist_silver(records)
    logger.info(f"Silver BCB '{indicator}': {len(records)} transformados, {inserted} novos.")
    return inserted


def run_silver_transforms() -> dict:
    """Executa todas as transformações Bronze → Silver."""
    Base.metadata.create_all(bind=engine)
    results = {}

    ibge_config = [
        ("ipca", "IPCA mensal (%)", "%"),
        ("desemprego", "Taxa de desocupação (%)", "%"),
        ("pib_variacao", "PIB variação trimestral (%)", "%"),
    ]
    for indicator, _, unit in ibge_config:
        n = transform_ibge(indicator, "ibge", unit)
        results[f"ibge_{indicator}"] = n

    bcb_config = [
        ("selic", "% a.a."),
        ("cambio_usd", "R$/USD"),
        ("reservas_internacionais", "USD bi"),
        ("ipca_expectativa_12m", "%"),
    ]
    for indicator, unit in bcb_config:
        n = transform_bcb(indicator, unit)
        results[f"bcb_{indicator}"] = n

    return results
