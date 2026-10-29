select count(*) as actual
from {{ ref('latest_indicators') }}
having count(*) != 3
