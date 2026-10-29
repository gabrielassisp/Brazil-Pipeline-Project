with observations as (
    select *,
        lag(value) over (partition by source, indicator, country, frequency order by reference_date) as previous_value,
        lag(reference_date) over (partition by source, indicator, country, frequency order by reference_date) as previous_reference_date
    from {{ ref('stg_observations') }}
)
select *,
    case
        when frequency = 'monthly' and date_diff(reference_date, previous_reference_date, month) = 1 then value - previous_value
        when frequency = 'annual' and date_diff(reference_date, previous_reference_date, year) = 1 then value - previous_value
        else null
    end as change_in_source_units
from observations
