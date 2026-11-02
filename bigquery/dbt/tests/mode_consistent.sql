select observation_key
from {{ ref('stg_observations') }}
where is_synthetic != {{ 'true' if env_var('BQ_MODE', 'live') == 'fixture' else 'false' }}
