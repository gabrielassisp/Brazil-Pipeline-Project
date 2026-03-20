"""
gold_builder.py — Constrói a camada Gold com métricas analíticas derivadas.

Produz:
  1. GoldMonthlySnapshot: snapshot mensal consolidado com todos os indicadores
     em uma única linha por mês — pronto para consumo por dashboards.
  2. Índice de Stress Econômico (ISE): indicador composto normalizado que
     combina inflação, desemprego e câmbio em um único número [0-100].
  3. Selic real: taxa de juros descontada a inflação.
  4. Correlação entre indicadores: detecta relações entre séries.
"""

import logging
from datetime import datetime

import pandas as pd
import numpy as np
from sqlalchemy import text

from database import SessionLocal, engine
from models import Base, GoldMonthlySnapshot

logger = logging.getLogger(__name__)


def load_silver(indicator: str) -> pd.DataFrame:
    """Carrega série da camada Silver."""
    sql = text("""
        SELECT reference_date, value, value_12m_avg, value_yoy_pct
        FROM silver_indicators
        WHERE indicator = :indicator AND is_valid = 1
        ORDER BY reference_date
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"indicator": indicator})
    df["reference_date"] = pd.to_datetime(df["reference_date"])
    return df.set_index("reference_date")


def compute_stress_index(
    ipca_12m: float | None,
    desemprego: float | None,
    cambio: float | None,
) -> float | None:
    """
    Índice de Stress Econômico (ISE) — composto normalizado [0-100].

    Fórmula: média ponderada dos três componentes normalizados.
    - Inflação (IPCA 12m): peso 40% — normalizado em [0, 15%]
    - Desemprego: peso 35% — normalizado em [5%, 20%]
    - Câmbio (R$/USD): peso 25% — normalizado em [3.5, 7.5]

    100 = máximo stress histórico estimado, 0 = condição ideal.
    """
    if any(v is None for v in [ipca_12m, desemprego, cambio]):
        return None

    ipca_norm = max(0, min(1, ipca_12m / 15.0))
    desemprego_norm = max(0, min(1, (desemprego - 5.0) / 15.0))
    cambio_norm = max(0, min(1, (cambio - 3.5) / 4.0))

    ise = (ipca_norm * 0.40 + desemprego_norm * 0.35 + cambio_norm * 0.25) * 100
    return round(ise, 2)


def compute_correlation_matrix(indicators: dict[str, pd.Series]) -> pd.DataFrame:
    """
    Calcula correlação de Pearson entre todos os indicadores.
    Útil para identificar: selic sobe → câmbio cai? desemprego cresce → IPCA cai?
    """
    df = pd.DataFrame(indicators)
    return df.corr(method="pearson").round(3)


def build_gold_snapshots() -> int:
    """
    Constrói os snapshots mensais da camada Gold.
    Faz um join temporal de todos os indicadores Silver
    e calcula as métricas derivadas.
    """
    # Carregar séries da Silver
    try:
        ipca = load_silver("ipca")
        selic = load_silver("selic")
        desemprego = load_silver("desemprego")
        cambio = load_silver("cambio_usd")
        pib = load_silver("pib_variacao")
    except Exception as e:
        logger.error(f"Erro ao carregar Silver: {e}")
        return 0

    # Alinhar temporalmente — usar período mensal como índice comum
    all_dates = sorted(set(
        list(ipca.index) + list(selic.index) +
        list(desemprego.index) + list(cambio.index)
    ))

    inserted = 0
    with SessionLocal() as session:
        for date in all_dates:
            def _get(df, col="value"):
                if date in df.index:
                    v = df.loc[date, col]
                    return float(v) if pd.notna(v) else None
                return None

            ipca_val = _get(ipca)
            ipca_12m = _get(ipca, "value_12m_avg")
            selic_val = _get(selic)
            desemp_val = _get(desemprego)
            cambio_val = _get(cambio)
            pib_val = _get(pib)

            # Selic real: descontada da inflação acumulada 12m
            selic_real = None
            if selic_val is not None and ipca_12m is not None:
                # Fórmula de Fisher: (1 + i) / (1 + π) - 1
                selic_real = round(
                    ((1 + selic_val / 100) / (1 + ipca_12m / 100) - 1) * 100, 2
                )

            ise = compute_stress_index(ipca_12m, desemp_val, cambio_val)

            existing = session.query(GoldMonthlySnapshot).filter_by(
                reference_date=date
            ).first()

            snap_data = dict(
                ipca=ipca_val,
                ipca_12m=ipca_12m,
                selic=selic_val,
                selic_real=selic_real,
                desemprego=desemp_val,
                cambio_usd=cambio_val,
                pib_crescimento=pib_val,
                econ_stress_idx=ise,
                computed_at=datetime.utcnow(),
            )

            if existing:
                for k, v in snap_data.items():
                    setattr(existing, k, v)
            else:
                session.add(GoldMonthlySnapshot(reference_date=date, **snap_data))
                inserted += 1

        session.commit()

    logger.info(f"Gold snapshots: {inserted} novos, {len(all_dates)} total processados.")
    return inserted


def compute_and_log_correlations() -> pd.DataFrame:
    """Calcula e loga a matriz de correlação entre indicadores."""
    try:
        series = {
            "ipca":      load_silver("ipca")["value"],
            "selic":     load_silver("selic")["value"],
            "desemprego": load_silver("desemprego")["value"],
            "cambio":    load_silver("cambio_usd")["value"],
        }
        corr = compute_correlation_matrix(series)
        logger.info(f"\nMatriz de correlação:\n{corr.to_string()}")
        return corr
    except Exception as e:
        logger.warning(f"Não foi possível calcular correlações: {e}")
        return pd.DataFrame()


def run_gold_build() -> dict:
    """Executa a construção completa da camada Gold."""
    Base.metadata.create_all(bind=engine)
    inserted = build_gold_snapshots()
    corr = compute_and_log_correlations()
    return {
        "snapshots_inserted": inserted,
        "correlation_computed": not corr.empty,
    }
