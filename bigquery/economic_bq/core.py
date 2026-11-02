import hashlib
import calendar
import json
import math
import re
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class QualityError(ValueError):
    pass


def fetch_json(url, attempts=3, opener=urlopen, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            request = Request(url, headers={'User-Agent':'BrazilEconomicPipeline/1.0 (public-data portfolio)'})
            with opener(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == attempts-1:
                raise
            sleep(2 ** attempt)
        except (URLError, TimeoutError):
            if attempt == attempts-1:
                raise
            sleep(2 ** attempt)
    raise RuntimeError('Tentativas esgotadas')


def number(value):
    if isinstance(value, bool) or value is None:
        raise QualityError('Valor numérico ausente ou inválido')
    try:
        result = float(str(value).replace(',', '.'))
    except (ValueError, TypeError):
        raise QualityError('Valor numérico inválido') from None
    if not math.isfinite(result):
        raise QualityError('NaN ou infinito não são aceitos')
    return result


def observation(source, indicator, period, value, frequency, unit, payload):
    parsed = date.fromisoformat(period)
    if parsed.day != 1 or (frequency == 'annual' and parsed.month != 1):
        raise QualityError('Período fora da granularidade declarada')
    key = '|'.join([source, indicator, 'BR', frequency, period])
    return dict(observation_key=hashlib.sha256(key.encode()).hexdigest(), source=source,
                indicator=indicator, country='BR', reference_date=period, value=number(value),
                frequency=frequency, unit=unit, payload=json.dumps(payload, ensure_ascii=False, allow_nan=False))


def parse_ibge(data):
    if not isinstance(data, list) or len(data) < 2:
        raise QualityError('Resposta IBGE vazia ou inesperada')
    result = []
    for row in data[1:]:
        if row.get('D1C') != '1' or row.get('D2C') != '63':
            raise QualityError('IBGE retornou localidade ou variável inesperada')
        period = row.get('D3C', '')
        if not re.fullmatch(r'\d{6}', period):
            raise QualityError('Período IBGE inválido')
        result.append(observation('ibge', 'ipca_monthly', period[:4]+'-'+period[4:]+'-01',
                                  row.get('V'), 'monthly', '%', row))
    return result


def parse_bcb(data):
    if not isinstance(data, list) or not data:
        raise QualityError('Resposta BCB vazia ou inesperada')
    monthly = {}
    for row in data:
        day = datetime.strptime(row['data'], '%d/%m/%Y').date()
        value = number(row['valor'])
        key = day.replace(day=1).isoformat()
        # Selic: última observação diária disponível do mês, não média mensal.
        if key not in monthly or day > monthly[key][0]:
            monthly[key] = (day, value, row)
    return [observation('bcb', 'selic_annualized', period, item[1], 'monthly', '% a.a.', item[2])
            for period, item in sorted(monthly.items())]


def parse_worldbank(data):
    if not isinstance(data, list) or len(data) != 2 or not isinstance(data[0], dict) or not isinstance(data[1], list):
        raise QualityError('Resposta World Bank inesperada')
    if int(data[0].get('pages', 0)) != 1:
        raise QualityError('World Bank retornou paginação não coberta por esta janela')
    result = []
    for row in data[1]:
        if row.get('countryiso3code') != 'BRA' or row.get('indicator', {}).get('id') != 'NY.GDP.MKTP.KD.ZG':
            raise QualityError('World Bank retornou país ou indicador inesperado')
        # Anos sem valor publicado são ausências reais, nunca dados simulados.
        if row.get('value') is None:
            continue
        year = row.get('date', '')
        if not re.fullmatch(r'\d{4}', year):
            raise QualityError('Ano World Bank inválido')
        result.append(observation('worldbank', 'gdp_growth_annual', year+'-01-01',
                                  row['value'], 'annual', '% a.a.', row))
    if not result:
        raise QualityError('World Bank sem observações publicadas na janela')
    return result


def validate_window(start, end):
    start, end = date.fromisoformat(start), date.fromisoformat(end)
    if start > end or start.day != 1 or end.day != calendar.monthrange(end.year,end.month)[1]:
        raise QualityError('A janela deve cobrir meses completos, com início anterior ao fim')
    if (end-start).days > 5*366:
        raise QualityError('Limite da demonstração: janela de até cinco anos')
    return start, end


def validate_rows(rows):
    if not rows or len(rows) > 20000:
        raise QualityError('Carga vazia ou acima do limite de 20.000 observações')
    keys = set()
    for row in rows:
        number(row['value'])
        if row['observation_key'] in keys:
            raise QualityError('Observação duplicada; a carga não será publicada')
        keys.add(row['observation_key'])
        if row['source'] not in {'ibge','bcb','worldbank'} or row['frequency'] not in {'monthly','annual'}:
            raise QualityError('Fonte ou frequência inválida')
    if {r['source'] for r in rows} != {'ibge','bcb','worldbank'}:
        raise QualityError('Todas as três fontes são obrigatórias')


def collect(start='2022-01-01', end='2024-12-31', mode='live', getter=fetch_json):
    first, last = validate_window(start, end)
    if mode not in {'live','fixture'}:
        raise QualityError('Modo inválido')
    if mode == 'fixture':
        rows = []
        for year in range(first.year, last.year+1):
            for month in range(1,13):
                day = date(year,month,1)
                if first <= day <= last:
                    rows += [observation('ibge','ipca_monthly',day.isoformat(),.2+month/100,'monthly','%',{'synthetic':True}),
                             observation('bcb','selic_annualized',day.isoformat(),10+month/10,'monthly','% a.a.',{'synthetic':True})]
            if first <= date(year,1,1) <= last:
                rows.append(observation('worldbank','gdp_growth_annual',f'{year}-01-01',2.0,'annual','% a.a.',{'synthetic':True}))
    else:
        ibge = f'https://apisidra.ibge.gov.br/values/t/1737/n1/1/v/63/p/{first:%Y%m}-{last:%Y%m}?formato=json'
        bcb = f'https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial={first:%d/%m/%Y}&dataFinal={last:%d/%m/%Y}'
        wb = f'https://api.worldbank.org/v2/country/BR/indicator/NY.GDP.MKTP.KD.ZG?format=json&date={first.year}:{last.year}&per_page=100'
        rows = parse_ibge(getter(ibge)) + parse_bcb(getter(bcb)) + parse_worldbank(getter(wb))
        rows = [r for r in rows if first <= date.fromisoformat(r['reference_date']) <= last]
    validate_rows(rows)
    expected = set()
    month = first
    while month <= last:
        expected.add(month.isoformat())
        month = date(month.year+1,1,1) if month.month==12 else date(month.year,month.month+1,1)
    for source in ('ibge','bcb'):
        observed = {r['reference_date'] for r in rows if r['source']==source}
        if observed != expected:
            raise QualityError(f'Cobertura mensal incompleta na fonte {source}')
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row.update(ingestion_date=timestamp[:10], ingested_at=timestamp, is_synthetic=mode=='fixture')
    return rows
