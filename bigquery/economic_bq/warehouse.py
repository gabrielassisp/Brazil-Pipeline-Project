from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

APP = 'brazil-econ-portfolio'


@dataclass(frozen=True)
class Config:
    project: str
    prefix: str = 'portfolio_econ'
    location: str = 'US'
    mode: str = 'live'
    maximum_bytes_billed: int = 100_000_000

    def __post_init__(self):
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,28}[a-z0-9]', self.project):
            raise ValueError('Informe explicitamente o ID do seu projeto pessoal; o projeto padrão do SDK não é usado')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,35}', self.prefix):
            raise ValueError('Prefixo inválido')
        if self.mode not in ('live','fixture'):
            raise ValueError('Modo inválido')
        if not 1 <= self.maximum_bytes_billed <= 1_000_000_000:
            raise ValueError('Limite por consulta deve estar entre 1 e 1.000.000.000 bytes')
        if not re.fullmatch(r'[A-Za-z0-9-]+', self.location):
            raise ValueError('Localidade inválida')

    def dataset(self, layer):
        if layer not in ('bronze','silver','gold'):
            raise ValueError('Camada inválida')
        return f'{self.project}.{self.prefix}_{self.mode}_{layer}'


class Warehouse:
    def __init__(self, config, client=None):
        from google.cloud import bigquery
        self.api = bigquery
        self.config = config
        self.client = client or bigquery.Client(project=config.project, location=config.location)

    def bootstrap(self):
        from google.api_core.exceptions import NotFound
        for layer in ('bronze','silver','gold'):
            ident = self.config.dataset(layer)
            try:
                existing = self.client.get_dataset(ident)
                if (existing.labels or {}).get('app') != APP or existing.location.lower() != self.config.location.lower():
                    raise ValueError(f'Dataset existente não pertence a este projeto de demonstração: {ident}')
            except NotFound:
                dataset = self.api.Dataset(ident)
                dataset.location = self.config.location
                dataset.labels = {'app':APP,'mode':self.config.mode}
                dataset.default_table_expiration_ms = 7*24*60*60*1000
                self.client.create_dataset(dataset)

    def load(self, rows, run_id):
        from google.api_core.exceptions import NotFound
        from .core import validate_rows
        validate_rows(rows)
        if any(row['is_synthetic'] != (self.config.mode == 'fixture') for row in rows):
            raise ValueError('Não é permitido misturar dados sintéticos e reais')
        for layer in ('bronze','silver','gold'):
            dataset = self.client.get_dataset(self.config.dataset(layer))
            if (dataset.labels or {}).get('app') != APP or dataset.location.lower() != self.config.location.lower():
                raise ValueError('Execute o bootstrap; os três datasets devem pertencer à demonstração')
        ident = self.config.dataset('bronze') + '.observations'
        schema = [self.api.SchemaField(name, kind, mode='REQUIRED') for name, kind in (
            ('observation_key','STRING'),('source','STRING'),('indicator','STRING'),('country','STRING'),
            ('reference_date','DATE'),('value','FLOAT'),('frequency','STRING'),('unit','STRING'),
            ('payload','STRING'),('ingestion_date','DATE'),('ingested_at','TIMESTAMP'),('is_synthetic','BOOLEAN'),('run_id','STRING'))]
        try:
            existing = self.client.get_table(ident)
            if (existing.labels or {}).get('app') != APP or existing.table_type != 'TABLE':
                raise ValueError('O destino existente não pertence à demonstração')
            if [(f.name,f.field_type,f.mode) for f in existing.schema] != [(f.name,f.field_type,f.mode) for f in schema]:
                raise ValueError('Schema de destino divergente; nenhuma substituição foi executada')
        except NotFound:
            table = self.api.Table(ident, schema=schema)
            table.labels = {'app':APP,'mode':self.config.mode}
            table.time_partitioning = self.api.TimePartitioning(type_=self.api.TimePartitioningType.DAY, field='ingestion_date')
            table.clustering_fields = ['source','indicator','reference_date']
            table.require_partition_filter = True
            self.client.create_table(table)
        config = self.api.LoadJobConfig(schema=schema, write_disposition='WRITE_TRUNCATE',
                                        source_format='NEWLINE_DELIMITED_JSON', max_bad_records=0,
                                        time_partitioning=self.api.TimePartitioning(type_='DAY',field='ingestion_date'),
                                        clustering_fields=['source','indicator','reference_date'],
                                        ignore_unknown_values=False, labels={'app':APP,'mode':self.config.mode})
        payload = [dict(row,run_id=run_id) for row in rows]
        job = self.client.load_table_from_json(payload, ident, job_id='econ_'+run_id,
                                              location=self.config.location, job_config=config)
        job.result(timeout=180)
        if job.output_rows != len(rows):
            raise RuntimeError('O total informado pelo load job difere da carga local')
        table = self.client.get_table(ident)
        table.expires = datetime.now(timezone.utc)+timedelta(days=7)
        table.require_partition_filter = True
        self.client.update_table(table,['expires','require_partition_filter'])
        return dict(job_id=job.job_id, output_rows=job.output_rows, input_bytes=job.input_file_bytes,
                    destination=ident, partition_field='ingestion_date')

    def query_latest(self):
        sql = f'SELECT source, indicator, frequency, unit, reference_date, value, is_synthetic FROM `{self.config.dataset("gold")}.latest_indicators` ORDER BY source, indicator'
        config = self.api.QueryJobConfig(maximum_bytes_billed=self.config.maximum_bytes_billed,
                                         use_query_cache=True, labels={'app':APP,'mode':self.config.mode})
        job = self.client.query(sql, job_config=config, location=self.config.location)
        rows = [dict(row) for row in job.result(timeout=120)]
        return dict(rows=rows, job_id=job.job_id, total_bytes_processed=job.total_bytes_processed,
                    total_bytes_billed=job.total_bytes_billed)
