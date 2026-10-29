select expected_source
from unnest(['ibge','bcb','worldbank']) as expected_source
left join (select distinct source from {{ ref('stg_observations') }}) as actual
  on actual.source = expected_source
where actual.source is null
