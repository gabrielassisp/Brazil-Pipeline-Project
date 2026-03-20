"""
models.py — Modelos ORM para as três camadas do pipeline.

Bronze: dados brutos exatamente como vieram da API
Silver: dados limpos, tipados e alinhados temporalmente
Gold:   métricas calculadas prontas para consumo analítico
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ── BRONZE — dados brutos ─────────────────────────────────────────────────────

class BronzeIBGE(Base):
    """Série temporal bruta do IBGE (SIDRA API)."""
    __tablename__ = "bronze_ibge"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    indicator    = Column(String(50), nullable=False)   # ex: "ipca", "pib", "desemprego"
    reference_date = Column(String(10), nullable=False) # ex: "2024-01"
    value        = Column(Float)
    unit         = Column(String(50))
    source_code  = Column(String(20))                  # código da tabela SIDRA
    raw_response = Column(Text)                        # JSON original para auditoria
    collected_at = Column(DateTime, default=datetime.utcnow)


class BronzeBCB(Base):
    """Série temporal bruta do Banco Central (SGS API)."""
    __tablename__ = "bronze_bcb"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    indicator    = Column(String(50), nullable=False)   # ex: "selic", "cambio_usd"
    reference_date = Column(String(10), nullable=False)
    value        = Column(Float)
    series_code  = Column(Integer)                     # código da série no SGS
    collected_at = Column(DateTime, default=datetime.utcnow)


class BronzeWorldBank(Base):
    """Indicadores do World Bank para comparativo global."""
    __tablename__ = "bronze_worldbank"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    country_code = Column(String(5), nullable=False)
    indicator_code = Column(String(50), nullable=False)  # ex: "NY.GDP.MKTP.CD"
    year         = Column(Integer, nullable=False)
    value        = Column(Float)
    collected_at = Column(DateTime, default=datetime.utcnow)


# ── SILVER — dados limpos ─────────────────────────────────────────────────────

class SilverIndicator(Base):
    """
    Série temporal limpa e normalizada.
    Todas as fontes convergem aqui com frequência mensal
    e unidades padronizadas.
    """
    __tablename__ = "silver_indicators"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    indicator     = Column(String(50), nullable=False)
    reference_date = Column(DateTime, nullable=False)   # sempre primeiro dia do mês
    value         = Column(Float, nullable=False)
    value_12m_avg = Column(Float)                       # média móvel 12 meses
    value_yoy_pct = Column(Float)                       # variação ano a ano (%)
    source        = Column(String(20), nullable=False)  # "ibge", "bcb", "worldbank"
    unit          = Column(String(30))
    is_valid      = Column(Boolean, default=True)       # passou na validação GE
    transformed_at = Column(DateTime, default=datetime.utcnow)


# ── GOLD — camada analítica ───────────────────────────────────────────────────

class GoldMonthlySnapshot(Base):
    """
    Snapshot mensal consolidado com todos os indicadores
    e métricas derivadas em uma única linha por mês.
    Pronto para consumo por dashboards e relatórios.
    """
    __tablename__ = "gold_monthly_snapshots"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    reference_date  = Column(DateTime, nullable=False, unique=True)
    ipca            = Column(Float)   # inflação mensal (%)
    ipca_12m        = Column(Float)   # inflação acumulada 12 meses (%)
    selic           = Column(Float)   # taxa Selic ao ano (%)
    selic_real      = Column(Float)   # Selic real = Selic - IPCA_12m
    desemprego      = Column(Float)   # taxa de desocupação (%)
    cambio_usd      = Column(Float)   # R$/USD (média mensal)
    pib_crescimento = Column(Float)   # crescimento do PIB vs trimestre anterior (%)
    econ_stress_idx = Column(Float)   # índice composto: desemprego + inflação + câmbio
    computed_at     = Column(DateTime, default=datetime.utcnow)


class GoldQualityLog(Base):
    """Histórico de resultados das validações de qualidade (Great Expectations)."""
    __tablename__ = "gold_quality_log"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    run_date     = Column(DateTime, default=datetime.utcnow)
    layer        = Column(String(20))   # "bronze" ou "silver"
    indicator    = Column(String(50))
    expectation  = Column(String(100))
    passed       = Column(Boolean)
    details      = Column(Text)
