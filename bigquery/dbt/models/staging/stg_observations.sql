select observation_key, source, indicator, country, reference_date, value,
       frequency, unit, ingested_at, is_synthetic, run_id
from {{ source('bronze', 'observations') }}
where ingestion_date = date('{{ env_var("BQ_SNAPSHOT_DATE", run_started_at.strftime("%Y-%m-%d")) }}')
  and reference_date between date('{{ env_var("BQ_START_DATE", "2022-01-01") }}')
                         and date('{{ env_var("BQ_END_DATE", "2024-12-31") }}')
