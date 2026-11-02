select source, indicator, country, reference_date, value, frequency, unit,
       previous_reference_date, previous_value, change_in_source_units,
       ingested_at, is_synthetic, run_id
from {{ ref('economic_trends') }}
qualify row_number() over (
    partition by source, indicator, country, frequency order by reference_date desc
) = 1
