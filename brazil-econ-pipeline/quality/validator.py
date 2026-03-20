"""
validator.py — Validação de qualidade de dados com Great Expectations.

Implementa "expectativas" (contratos) sobre os dados coletados.
Se uma expectativa falha, o pipeline registra o problema e
pode interromper a progressão para a camada Silver.

Expectations implementadas:
  - Completude: colunas obrigatórias não podem ser nulas
  - Range: valores devem estar dentro de faixas realistas
  - Freshness: dados não podem ter mais de N dias de atraso
  - Unicidade: não pode haver duplicatas por (indicator, date)
  - Tipo: valores devem ser numéricos
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from database import SessionLocal, engine
from models import BronzeIBGE, BronzeBCB, GoldQualityLog

logger = logging.getLogger(__name__)


@dataclass
class ExpectationResult:
    """Resultado de uma expectativa individual."""
    expectation: str
    indicator: str
    passed: bool
    details: str = ""
    severity: Literal["error", "warning"] = "error"


@dataclass
class ValidationSuite:
    """Conjunto de resultados de validação para uma camada."""
    layer: str
    indicator: str
    results: list[ExpectationResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results if r.severity == "error")

    @property
    def n_passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def n_failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)


# ── Expectativas individuais ──────────────────────────────────────────────────

def expect_no_nulls(df: pd.DataFrame, column: str, indicator: str) -> ExpectationResult:
    """Coluna não pode ter valores nulos."""
    null_count = df[column].isnull().sum()
    pct = null_count / len(df) * 100 if len(df) > 0 else 0
    return ExpectationResult(
        expectation="expect_no_nulls",
        indicator=indicator,
        passed=null_count == 0,
        details=f"{null_count} nulos ({pct:.1f}%) na coluna '{column}'",
        severity="error",
    )


def expect_value_between(
    df: pd.DataFrame,
    column: str,
    indicator: str,
    min_val: float,
    max_val: float,
) -> ExpectationResult:
    """Todos os valores devem estar dentro de [min_val, max_val]."""
    out_of_range = df[(df[column] < min_val) | (df[column] > max_val)]
    return ExpectationResult(
        expectation="expect_value_between",
        indicator=indicator,
        passed=len(out_of_range) == 0,
        details=f"{len(out_of_range)} valores fora de [{min_val}, {max_val}]: {out_of_range[column].tolist()[:3]}",
        severity="error",
    )


def expect_no_duplicates(
    df: pd.DataFrame,
    subset: list[str],
    indicator: str,
) -> ExpectationResult:
    """Não pode haver duplicatas pelo subconjunto de colunas."""
    dupes = df.duplicated(subset=subset).sum()
    return ExpectationResult(
        expectation="expect_no_duplicates",
        indicator=indicator,
        passed=dupes == 0,
        details=f"{dupes} duplicatas por {subset}",
        severity="error",
    )


def expect_min_row_count(
    df: pd.DataFrame,
    indicator: str,
    min_count: int,
) -> ExpectationResult:
    """DataFrame deve ter pelo menos N linhas."""
    return ExpectationResult(
        expectation="expect_min_row_count",
        indicator=indicator,
        passed=len(df) >= min_count,
        details=f"{len(df)} linhas (mínimo: {min_count})",
        severity="warning",
    )


def expect_recent_data(
    df: pd.DataFrame,
    date_column: str,
    indicator: str,
    max_days_stale: int = 45,
) -> ExpectationResult:
    """Os dados mais recentes não podem ser mais antigos que max_days_stale dias."""
    if df.empty:
        return ExpectationResult(
            expectation="expect_recent_data",
            indicator=indicator,
            passed=False,
            details="DataFrame vazio",
            severity="error",
        )

    try:
        latest = pd.to_datetime(df[date_column]).max()
        age_days = (datetime.utcnow() - latest.to_pydatetime()).days
        return ExpectationResult(
            expectation="expect_recent_data",
            indicator=indicator,
            passed=age_days <= max_days_stale,
            details=f"Dado mais recente: {latest.date()} ({age_days} dias atrás)",
            severity="warning",
        )
    except Exception as e:
        return ExpectationResult(
            expectation="expect_recent_data",
            indicator=indicator,
            passed=False,
            details=str(e),
            severity="warning",
        )


def expect_column_type_numeric(
    df: pd.DataFrame,
    column: str,
    indicator: str,
) -> ExpectationResult:
    """Coluna deve ser numérica."""
    is_numeric = pd.api.types.is_numeric_dtype(df[column])
    return ExpectationResult(
        expectation="expect_column_type_numeric",
        indicator=indicator,
        passed=is_numeric,
        details=f"Tipo encontrado: {df[column].dtype}",
        severity="error",
    )


# ── Suites de validação por fonte ─────────────────────────────────────────────

IBGE_RANGES = {
    "ipca":        (-2.0, 5.0),    # IPCA mensal raramente sai disso
    "desemprego":  (5.0, 20.0),    # desemprego histórico no Brasil
    "pib_variacao": (-5.0, 5.0),   # variação trimestral do PIB
}

BCB_RANGES = {
    "selic":                    (0.0, 20.0),
    "cambio_usd":               (3.0, 8.0),
    "reservas_internacionais":  (200, 500),
    "ipca_expectativa_12m":     (0.0, 15.0),
}


def validate_bronze_ibge(indicator: str) -> ValidationSuite:
    """Valida dados IBGE na camada Bronze."""
    suite = ValidationSuite(layer="bronze_ibge", indicator=indicator)

    with SessionLocal() as session:
        rows = session.query(BronzeIBGE).filter_by(indicator=indicator).all()

    if not rows:
        suite.results.append(ExpectationResult(
            expectation="expect_min_row_count",
            indicator=indicator,
            passed=False,
            details="Nenhum registro encontrado para este indicador.",
            severity="error",
        ))
        return suite

    df = pd.DataFrame([{
        "reference_date": r.reference_date,
        "value": r.value,
        "collected_at": r.collected_at,
    } for r in rows])

    suite.results.append(expect_min_row_count(df, indicator, min_count=12))
    suite.results.append(expect_no_nulls(df, "value", indicator))
    suite.results.append(expect_no_duplicates(df, ["reference_date"], indicator))
    suite.results.append(expect_column_type_numeric(df, "value", indicator))
    suite.results.append(expect_recent_data(df, "reference_date", indicator, max_days_stale=60))

    if indicator in IBGE_RANGES:
        lo, hi = IBGE_RANGES[indicator]
        suite.results.append(expect_value_between(df, "value", indicator, lo, hi))

    return suite


def validate_bronze_bcb(indicator: str) -> ValidationSuite:
    """Valida dados BCB na camada Bronze."""
    suite = ValidationSuite(layer="bronze_bcb", indicator=indicator)

    with SessionLocal() as session:
        rows = session.query(BronzeBCB).filter_by(indicator=indicator).all()

    if not rows:
        suite.results.append(ExpectationResult(
            expectation="expect_min_row_count",
            indicator=indicator,
            passed=False,
            details="Nenhum registro encontrado.",
            severity="error",
        ))
        return suite

    df = pd.DataFrame([{
        "reference_date": r.reference_date,
        "value": r.value,
    } for r in rows])

    suite.results.append(expect_min_row_count(df, indicator, min_count=6))
    suite.results.append(expect_no_nulls(df, "value", indicator))
    suite.results.append(expect_no_duplicates(df, ["reference_date"], indicator))
    suite.results.append(expect_column_type_numeric(df, "value", indicator))
    suite.results.append(expect_recent_data(df, "reference_date", indicator, max_days_stale=45))

    if indicator in BCB_RANGES:
        lo, hi = BCB_RANGES[indicator]
        suite.results.append(expect_value_between(df, "value", indicator, lo, hi))

    return suite


def run_all_validations() -> dict[str, ValidationSuite]:
    """Executa todas as suites de validação e persiste o log no Gold."""
    from ingestion.ibge_collector import IBGE_SERIES
    from ingestion.bcb_collector import BCB_SERIES

    suites = {}

    for indicator in IBGE_SERIES:
        suite = validate_bronze_ibge(indicator)
        suites[f"ibge_{indicator}"] = suite
        _log_results(suite)

    for indicator in BCB_SERIES:
        suite = validate_bronze_bcb(indicator)
        suites[f"bcb_{indicator}"] = suite
        _log_results(suite)

    _print_summary(suites)
    return suites


def _log_results(suite: ValidationSuite) -> None:
    """Persiste resultados no gold_quality_log."""
    with SessionLocal() as session:
        for r in suite.results:
            session.add(GoldQualityLog(
                layer=suite.layer,
                indicator=r.indicator,
                expectation=r.expectation,
                passed=r.passed,
                details=r.details,
            ))
        session.commit()


def _print_summary(suites: dict[str, ValidationSuite]) -> None:
    total = sum(s.n_passed + s.n_failed for s in suites.values())
    passed = sum(s.n_passed for s in suites.values())
    failed = sum(s.n_failed for s in suites.values())
    pct = passed / total * 100 if total > 0 else 0

    logger.info(f"\n{'='*50}")
    logger.info(f"Validação concluída: {passed}/{total} ({pct:.1f}%) expectations OK")
    for key, suite in suites.items():
        status = "OK" if suite.passed else "FAIL"
        logger.info(f"  [{status}] {key}: {suite.n_passed} ok, {suite.n_failed} falhou")
    logger.info(f"{'='*50}\n")
