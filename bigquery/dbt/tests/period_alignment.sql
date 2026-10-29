select observation_key
from {{ ref('stg_observations') }}
where extract(day from reference_date) != 1
   or (frequency = 'annual' and extract(month from reference_date) != 1)
