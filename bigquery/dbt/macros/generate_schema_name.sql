{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ env_var('BQ_DATASET_PREFIX', 'portfolio_econ') }}_{{ env_var('BQ_MODE', 'live') }}_{{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
