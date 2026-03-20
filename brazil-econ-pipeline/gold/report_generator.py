"""
report_generator.py — Gera relatório HTML da camada Gold.

Produz um relatório estático com:
  - KPIs dos indicadores mais recentes
  - Tabela de snapshots mensais
  - Resultado das validações de qualidade
  - Interpretação do Índice de Stress Econômico
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from database import engine
from models import GoldMonthlySnapshot, GoldQualityLog
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")


def _fmt(v, decimals=2, suffix=""):
    if v is None:
        return "—"
    return f"{v:.{decimals}f}{suffix}"


def _ise_color(ise: float | None) -> str:
    if ise is None:
        return "#6c7086"
    if ise >= 65:
        return "#f38ba8"
    if ise >= 40:
        return "#fab387"
    return "#a6e3a1"


def _ise_label(ise: float | None) -> str:
    if ise is None:
        return "—"
    if ise >= 65:
        return "Alto stress"
    if ise >= 40:
        return "Stress moderado"
    return "Condição favorável"


def generate_report() -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)

    # Carregar dados Gold
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT * FROM gold_monthly_snapshots ORDER BY reference_date DESC"),
            conn
        )
        quality_df = pd.read_sql(
            text("SELECT * FROM gold_quality_log ORDER BY run_date DESC LIMIT 100"),
            conn
        )

    if df.empty:
        logger.warning("Sem dados Gold para gerar relatório.")
        return REPORTS_DIR / "empty_report.html"

    latest = df.iloc[0]
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # ── Tabela de snapshots ──
    snapshot_rows = ""
    for _, row in df.head(24).iterrows():
        date_str = pd.to_datetime(row["reference_date"]).strftime("%b/%Y")
        ise = row.get("econ_stress_idx")
        ise_color = _ise_color(ise)
        snapshot_rows += f"""
        <tr>
            <td>{date_str}</td>
            <td>{_fmt(row.get('ipca'), suffix='%')}</td>
            <td>{_fmt(row.get('ipca_12m'), suffix='%')}</td>
            <td>{_fmt(row.get('selic'), suffix='%')}</td>
            <td>{_fmt(row.get('selic_real'), suffix='%')}</td>
            <td>{_fmt(row.get('desemprego'), suffix='%')}</td>
            <td>{_fmt(row.get('cambio_usd'), 4)}</td>
            <td style="color:{ise_color};font-weight:600">{_fmt(ise, 1)}</td>
        </tr>"""

    # ── Tabela de qualidade ──
    quality_rows = ""
    for _, row in quality_df.iterrows():
        status_color = "#a6e3a1" if row.get("passed") else "#f38ba8"
        status_text = "PASSOU" if row.get("passed") else "FALHOU"
        quality_rows += f"""
        <tr>
            <td>{row.get('layer', '')}</td>
            <td>{row.get('indicator', '')}</td>
            <td>{row.get('expectation', '')}</td>
            <td style="color:{status_color};font-weight:600">{status_text}</td>
            <td style="font-size:12px;color:#6c7086">{row.get('details', '')}</td>
        </tr>"""

    if not quality_rows:
        quality_rows = '<tr><td colspan="5" style="text-align:center;color:#6c7086">Nenhuma validação registrada ainda</td></tr>'

    ise_latest = latest.get("econ_stress_idx")
    ise_color = _ise_color(ise_latest)
    ise_label = _ise_label(ise_latest)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Brazil Economic Pipeline — {now_str}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0b0c10;color:#cdd6f4;font-family:'Segoe UI',sans-serif;padding:40px;font-size:15px}}
  h1{{font-size:28px;font-weight:700;margin-bottom:4px}}
  .sub{{color:#6c7086;font-size:13px;margin-bottom:40px}}
  .kpi-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:40px}}
  .kpi{{background:#1e1e2e;border:1px solid #2a2d36;border-radius:12px;padding:20px;text-align:center}}
  .kpi-val{{font-size:32px;font-weight:700;color:#fcc717;letter-spacing:-1px}}
  .kpi-label{{font-size:12px;color:#6c7086;margin-top:6px}}
  .ise-card{{background:#1e1e2e;border:1px solid #2a2d36;border-radius:12px;padding:28px;margin-bottom:40px;display:flex;align-items:center;gap:32px}}
  .ise-val{{font-size:56px;font-weight:700;letter-spacing:-2px}}
  .ise-meta h3{{font-size:18px;font-weight:500;margin-bottom:8px}}
  .ise-meta p{{font-size:14px;color:#6c7086;max-width:500px;line-height:1.6}}
  h2{{font-size:18px;font-weight:500;margin-bottom:16px}}
  .section{{margin-bottom:48px}}
  table{{width:100%;border-collapse:collapse;background:#1e1e2e;border-radius:12px;overflow:hidden;font-size:14px}}
  th{{background:#181825;padding:12px 14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#6c7086}}
  td{{padding:10px 14px;border-top:1px solid #2a2d36}}
  tr:hover td{{background:rgba(255,255,255,.02)}}
  .footer{{margin-top:60px;font-size:12px;color:#6c7086}}
</style>
</head>
<body>
  <h1>Brazil Economic Pipeline</h1>
  <p class="sub">Camada Gold · Relatório gerado em {now_str} · Fontes: IBGE, Banco Central, World Bank</p>

  <div class="kpi-row">
    <div class="kpi">
      <div class="kpi-val">{_fmt(latest.get('ipca'), suffix='%')}</div>
      <div class="kpi-label">IPCA mensal</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{_fmt(latest.get('ipca_12m'), suffix='%')}</div>
      <div class="kpi-label">IPCA acumulado 12m</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{_fmt(latest.get('selic'), suffix='%')}</div>
      <div class="kpi-label">Selic a.a.</div>
    </div>
    <div class="kpi">
      <div class="kpi-val" style="color:#{'a6e3a1' if (latest.get('selic_real') or 0) > 0 else 'f38ba8'}">{_fmt(latest.get('selic_real'), suffix='%')}</div>
      <div class="kpi-label">Selic real (Fisher)</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{_fmt(latest.get('desemprego'), suffix='%')}</div>
      <div class="kpi-label">Desemprego</div>
    </div>
    <div class="kpi">
      <div class="kpi-val">{_fmt(latest.get('cambio_usd'), 4)}</div>
      <div class="kpi-label">R$/USD</div>
    </div>
  </div>

  <div class="section">
    <h2>Índice de Stress Econômico (ISE)</h2>
    <div class="ise-card">
      <div class="ise-val" style="color:{ise_color}">{_fmt(ise_latest, 1)}</div>
      <div class="ise-meta">
        <h3 style="color:{ise_color}">{ise_label}</h3>
        <p>Composto ponderado: inflação 12m (40%) + desemprego (35%) + câmbio (25%).
        Escala 0-100, onde 100 representa condição de stress máximo histórico estimado.
        Permite comparar o ambiente econômico entre períodos distintos em um único número.</p>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>Série histórica — últimos 24 meses</h2>
    <table>
      <thead><tr>
        <th>Mês</th><th>IPCA mensal</th><th>IPCA 12m</th>
        <th>Selic</th><th>Selic real</th><th>Desemprego</th>
        <th>R$/USD</th><th>ISE</th>
      </tr></thead>
      <tbody>{snapshot_rows}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Log de qualidade de dados (Great Expectations)</h2>
    <table>
      <thead><tr>
        <th>Camada</th><th>Indicador</th><th>Expectativa</th><th>Status</th><th>Detalhe</th>
      </tr></thead>
      <tbody>{quality_rows}</tbody>
    </table>
  </div>

  <div class="footer">
    Brazil Economic Pipeline · Fontes públicas: api.bcb.gov.br · apisidra.ibge.gov.br · api.worldbank.org
  </div>
</body>
</html>"""

    path = REPORTS_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.html"
    path.write_text(html, encoding="utf-8")
    logger.info(f"Relatório salvo: {path}")
    return path
