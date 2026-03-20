"""
test_pipeline.py — Testes unitários para todas as camadas do pipeline.

Cobertura:
  - Transformações Silver (média móvel, YoY, alinhamento de datas)
  - Validador de qualidade (todas as expectations)
  - Índice de Stress Econômico (cálculo, casos-limite)
  - Coletores (parsing de respostas, fallback simulado)

Execute com: pytest tests/ -v
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from transforms.silver_transformer import enrich_series
from quality.validator import (
    expect_no_nulls,
    expect_value_between,
    expect_no_duplicates,
    expect_min_row_count,
    expect_recent_data,
    expect_column_type_numeric,
)
from gold.gold_builder import compute_stress_index, compute_correlation_matrix


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def serie_mensal():
    """Série temporal mensal estável de 24 meses."""
    dates = pd.date_range("2022-01-01", periods=24, freq="MS")
    return pd.DataFrame({"date": dates, "value": np.linspace(3.0, 6.0, 24)})


@pytest.fixture
def serie_com_pico():
    """Série com um valor discrepante."""
    dates = pd.date_range("2022-01-01", periods=12, freq="MS")
    values = [4.5] * 11 + [99.9]
    return pd.DataFrame({"date": dates, "value": values})


@pytest.fixture
def df_limpo():
    """DataFrame sem problemas — deve passar em todas as expectations."""
    dates = pd.date_range("2022-01-01", periods=15, freq="MS").strftime("%Y-%m")
    return pd.DataFrame({
        "reference_date": dates,
        "value": np.random.default_rng(42).uniform(1, 10, 15),
    })


# ── Testes de transformação Silver ────────────────────────────────────────────

class TestEnrichSeries:
    def test_retorna_dataframe(self, serie_mensal):
        result = enrich_series(serie_mensal)
        assert isinstance(result, pd.DataFrame)

    def test_colunas_adicionadas(self, serie_mensal):
        result = enrich_series(serie_mensal)
        assert "value_12m_avg" in result.columns
        assert "value_yoy_pct" in result.columns

    def test_media_movel_suaviza(self, serie_mensal):
        result = enrich_series(serie_mensal)
        # A média móvel deve ser mais suave que os valores originais
        ma_std = result["value_12m_avg"].dropna().std()
        raw_std = result["value"].std()
        assert ma_std <= raw_std

    def test_primeiros_valores_ma_nao_nulos(self, serie_mensal):
        result = enrich_series(serie_mensal)
        # com min_periods=3, a MA deve existir a partir do 3º ponto
        assert result["value_12m_avg"].iloc[2:].notna().all()

    def test_yoy_nan_nos_primeiros_12(self, serie_mensal):
        result = enrich_series(serie_mensal)
        # YoY requer 12 pontos anteriores
        assert result["value_yoy_pct"].iloc[:12].isna().all()

    def test_yoy_existe_apos_12_meses(self, serie_mensal):
        result = enrich_series(serie_mensal)
        assert result["value_yoy_pct"].iloc[12:].notna().any()

    def test_serie_vazia_retorna_df_vazio(self):
        df = pd.DataFrame({"date": [], "value": []})
        result = enrich_series(df)
        assert len(result) == 0

    def test_coluna_custom(self, serie_mensal):
        df = serie_mensal.rename(columns={"value": "preco"})
        result = enrich_series(df, value_col="preco")
        assert "value_12m_avg" in result.columns


# ── Testes de validação de qualidade ─────────────────────────────────────────

class TestExpectNoNulls:
    def test_passa_sem_nulos(self, df_limpo):
        r = expect_no_nulls(df_limpo, "value", "test")
        assert r.passed

    def test_falha_com_nulos(self, df_limpo):
        df = df_limpo.copy()
        df.loc[0, "value"] = None
        r = expect_no_nulls(df, "value", "test")
        assert not r.passed

    def test_detalhe_informa_quantidade(self, df_limpo):
        df = df_limpo.copy()
        df.loc[[0, 1], "value"] = None
        r = expect_no_nulls(df, "value", "test")
        assert "2" in r.details


class TestExpectValueBetween:
    def test_passa_dentro_do_range(self):
        df = pd.DataFrame({"value": [1.0, 2.5, 4.9]})
        r = expect_value_between(df, "value", "test", 0, 5)
        assert r.passed

    def test_falha_acima_do_limite(self):
        df = pd.DataFrame({"value": [1.0, 99.0]})
        r = expect_value_between(df, "value", "test", 0, 5)
        assert not r.passed

    def test_falha_abaixo_do_limite(self):
        df = pd.DataFrame({"value": [-5.0, 2.0]})
        r = expect_value_between(df, "value", "test", 0, 10)
        assert not r.passed

    def test_limite_exato_passa(self):
        df = pd.DataFrame({"value": [0.0, 10.0]})
        r = expect_value_between(df, "value", "test", 0, 10)
        assert r.passed


class TestExpectNoDuplicates:
    def test_passa_sem_duplicatas(self, df_limpo):
        r = expect_no_duplicates(df_limpo, ["reference_date"], "test")
        assert r.passed

    def test_falha_com_duplicatas(self, df_limpo):
        df = pd.concat([df_limpo, df_limpo.iloc[:1]], ignore_index=True)
        r = expect_no_duplicates(df, ["reference_date"], "test")
        assert not r.passed


class TestExpectMinRowCount:
    def test_passa_com_suficiente(self, df_limpo):
        r = expect_min_row_count(df_limpo, "test", min_count=5)
        assert r.passed

    def test_falha_com_poucos(self):
        df = pd.DataFrame({"value": [1, 2]})
        r = expect_min_row_count(df, "test", min_count=10)
        assert not r.passed

    def test_severidade_e_warning(self, df_limpo):
        r = expect_min_row_count(df_limpo, "test", min_count=5)
        assert r.severity == "warning"


class TestExpectRecentData:
    def test_passa_com_dados_recentes(self):
        df = pd.DataFrame({
            "reference_date": [(datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m")]
        })
        r = expect_recent_data(df, "reference_date", "test", max_days_stale=30)
        assert r.passed

    def test_falha_com_dados_antigos(self):
        df = pd.DataFrame({"reference_date": ["2020-01"]})
        r = expect_recent_data(df, "reference_date", "test", max_days_stale=30)
        assert not r.passed

    def test_falha_com_df_vazio(self):
        df = pd.DataFrame({"reference_date": []})
        r = expect_recent_data(df, "reference_date", "test")
        assert not r.passed


class TestExpectColumnTypeNumeric:
    def test_passa_com_float(self):
        df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})
        r = expect_column_type_numeric(df, "value", "test")
        assert r.passed

    def test_falha_com_string(self):
        df = pd.DataFrame({"value": ["um", "dois", "três"]})
        r = expect_column_type_numeric(df, "value", "test")
        assert not r.passed


# ── Testes do Índice de Stress Econômico ─────────────────────────────────────

class TestStressIndex:
    def test_retorna_float(self):
        ise = compute_stress_index(5.0, 12.0, 5.5)
        assert isinstance(ise, float)

    def test_range_valido(self):
        ise = compute_stress_index(5.0, 12.0, 5.5)
        assert 0 <= ise <= 100

    def test_condicao_ideal_da_ise_baixo(self):
        ise = compute_stress_index(0.5, 5.0, 3.5)
        assert ise < 20

    def test_stress_maximo_da_ise_alto(self):
        ise = compute_stress_index(15.0, 20.0, 7.5)
        assert ise > 80

    def test_retorna_none_com_valor_faltando(self):
        assert compute_stress_index(None, 12.0, 5.5) is None
        assert compute_stress_index(5.0, None, 5.5) is None
        assert compute_stress_index(5.0, 12.0, None) is None

    def test_monotono_inflacao(self):
        ise_baixo = compute_stress_index(2.0, 10.0, 5.0)
        ise_alto = compute_stress_index(10.0, 10.0, 5.0)
        assert ise_alto > ise_baixo

    def test_monotono_desemprego(self):
        ise_baixo = compute_stress_index(5.0, 6.0, 5.0)
        ise_alto = compute_stress_index(5.0, 18.0, 5.0)
        assert ise_alto > ise_baixo


# ── Testes de correlação ──────────────────────────────────────────────────────

class TestCorrelationMatrix:
    def test_retorna_dataframe(self):
        s = {
            "a": pd.Series([1, 2, 3, 4, 5]),
            "b": pd.Series([2, 4, 6, 8, 10]),
        }
        corr = compute_correlation_matrix(s)
        assert isinstance(corr, pd.DataFrame)

    def test_diagonal_e_um(self):
        s = {
            "a": pd.Series([1.0, 2.0, 3.0]),
            "b": pd.Series([3.0, 1.0, 2.0]),
        }
        corr = compute_correlation_matrix(s)
        assert corr.loc["a", "a"] == 1.0
        assert corr.loc["b", "b"] == 1.0

    def test_correlacao_perfeita(self):
        s = {
            "x": pd.Series([1.0, 2.0, 3.0, 4.0]),
            "y": pd.Series([2.0, 4.0, 6.0, 8.0]),
        }
        corr = compute_correlation_matrix(s)
        assert abs(corr.loc["x", "y"] - 1.0) < 1e-6


# ── Testes dos coletores (modo simulado) ──────────────────────────────────────

class TestSimulators:
    def test_ibge_simulado_retorna_lista(self):
        from ingestion.ibge_collector import _simulate_ibge, IBGE_SERIES
        cfg = IBGE_SERIES["ipca"]
        records = _simulate_ibge("ipca", cfg)
        assert isinstance(records, list)
        assert len(records) > 0

    def test_ibge_campos_obrigatorios(self):
        from ingestion.ibge_collector import _simulate_ibge, IBGE_SERIES
        cfg = IBGE_SERIES["ipca"]
        records = _simulate_ibge("ipca", cfg)
        required = {"indicator", "reference_date", "value", "unit", "source_code"}
        for r in records:
            assert required.issubset(r.keys())

    def test_bcb_simulado_retorna_lista(self):
        from ingestion.bcb_collector import _simulate_bcb, BCB_SERIES
        cfg = BCB_SERIES["selic"]
        records = _simulate_bcb("selic", cfg)
        assert len(records) > 0

    def test_bcb_valor_no_range(self):
        from ingestion.bcb_collector import _simulate_bcb, BCB_SERIES
        cfg = BCB_SERIES["selic"]
        records = _simulate_bcb("selic", cfg)
        for r in records:
            assert 0.0 <= r["value"] <= 20.0

    def test_wb_simulado_retorna_lista(self):
        from ingestion.worldbank_collector import _simulate_wb
        records = _simulate_wb("BR", "NY.GDP.MKTP.KD.ZG")
        assert len(records) > 0

    def test_wb_anos_corretos(self):
        from ingestion.worldbank_collector import _simulate_wb
        records = _simulate_wb("BR", "NY.GDP.MKTP.KD.ZG")
        anos = [r["year"] for r in records]
        assert all(2019 <= a <= 2024 for a in anos)
