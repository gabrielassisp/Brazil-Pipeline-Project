select source, indicator, frequency, is_synthetic,
       count(*) as observation_count,
       count(distinct observation_key) as distinct_observation_count,
       min(reference_date) as first_reference_date,
       max(reference_date) as last_reference_date,
       max(ingested_at) as last_ingested_at
from {{ ref('stg_observations') }}
group by source, indicator, frequency, is_synthetic
