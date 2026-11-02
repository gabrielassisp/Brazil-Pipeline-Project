# Brazil Economic Pipeline

O projeto possui duas implementações independentes:

- [Versão original Python/SQLite](brazil-econ-pipeline/README.md).
- [Versão Google BigQuery + dbt](bigquery/README.md): carga em lote, fontes públicas, qualidade, particionamento e execução reproduzível.

A extensão BigQuery não modifica os arquivos nem o banco SQLite da versão original. A extensão foi executada no BigQuery em 29/10/2026 com 75 observações reais, quatro modelos e 16 testes dbt aprovados. Consulte a evidência e os passos para reproduzir no README da extensão.
