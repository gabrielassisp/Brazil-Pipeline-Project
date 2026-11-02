select observation_key
from {{ ref('stg_observations') }}
where value is null or is_nan(value) or is_inf(value)
