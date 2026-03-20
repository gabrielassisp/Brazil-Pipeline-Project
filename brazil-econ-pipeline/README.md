# Brazil Economic Data Pipeline

Pipeline de dados econômicos brasileiros com arquitetura em camadas (Bronze → Silver → Gold), validação de qualidade formal e relatório HTML automático.

> **Projeto de portfólio** — demonstra engenharia de dados com fontes reais (IBGE, Banco Central, World Bank), arquitetura medallion, validação de qualidade com expectations customizadas e métricas analíticas derivadas.

---

## O que o projeto faz

Coleta automaticamente indicadores macroeconômicos brasileiros de três APIs públicas, valida a qualidade dos dados com um sistema de expectations formal, transforma e alinha as séries temporais, e produz uma camada analítica com o Índice de Stress Econômico (ISE) — um indicador composto que combina inflação, desemprego e câmbio em um único número.

### Indicadores coletados

| Fonte | Indicadores |
|---|---|
| IBGE SIDRA | IPCA mensal, Taxa de desemprego (PNAD), Crescimento do PIB |
| Banco Central (SGS) | Selic, Câmbio R$/USD, Reservas internacionais, Expectativa IPCA 12m |
| World Bank | PIB growth, CPI, Desemprego (BR, US, AR, WLD) |

---

## Arquitetura

```
APIs públicas (IBGE + BCB + World Bank)
         │
         ▼
  ┌─ Bronze ────────────────────────────┐
  │  Dados brutos exatamente como       │
  │  vieram da API. Nunca modificados.  │
  └─────────────────────────────────────┘
         │
         ▼
  ┌─ Validação (Quality) ───────────────┐
  │  Expectations: nulos, ranges,       │
  │  duplicatas, freshness, tipos.      │
  │  Log salvo no Gold.                 │
  └─────────────────────────────────────┘
         │
         ▼
  ┌─ Silver ────────────────────────────┐
  │  Dados limpos, tipados e alinhados. │
  │  Média móvel 12m, YoY calculados.  │
  └─────────────────────────────────────┘
         │
         ▼
  ┌─ Gold ──────────────────────────────┐
  │  Snapshot mensal consolidado.       │
  │  Selic real (Fisher), ISE.          │
  │  Relatório HTML automático.         │
  └─────────────────────────────────────┘
```

---

## Como rodar

```bash
git clone <repo-url>
cd brazil-econ-pipeline

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -e .   # instalar o pacote em modo editável

# Rodar o pipeline completo
python pipeline.py

# Modo agendado (executa diariamente às 06:00)
python pipeline.py --schedule

# Só os testes
pytest tests/ -v
```

O relatório HTML é salvo em `reports/report_YYYYMMDD_HHMM.html`.  
Todas as APIs são públicas e gratuitas — sem cadastro necessário.  
Se as APIs estiverem indisponíveis, o pipeline usa dados simulados automaticamente.

---

## Testes

```bash
pytest tests/ -v
```

42 testes unitários cobrindo:
- Enriquecimento de séries (média móvel, YoY, edge cases)
- Todas as 6 expectations de qualidade
- Índice de Stress Econômico (monotonicidade, casos-limite, None handling)
- Matriz de correlação
- Simuladores de todas as três fontes

---

## Estrutura

```
brazil-econ-pipeline/
├── pipeline.py                    # orquestrador principal
├── models.py                      # ORM das 3 camadas
├── database.py                    # conexão SQLite
├── ingestion/
│   ├── ibge_collector.py          # IBGE SIDRA API
│   ├── bcb_collector.py           # Banco Central SGS API
│   └── worldbank_collector.py     # World Bank API
├── quality/
│   └── validator.py               # expectations customizadas
├── transforms/
│   └── silver_transformer.py      # Bronze → Silver
├── gold/
│   ├── gold_builder.py            # Silver → Gold + ISE
│   └── report_generator.py        # relatório HTML
├── tests/
│   └── test_pipeline.py           # 42 testes unitários
└── requirements.txt
```

---

## Decisões técnicas

**Por que arquitetura medallion (Bronze/Silver/Gold)?** É o padrão usado em data lakehouses modernos (Databricks, Delta Lake, Azure Synapse). Demonstra que você entende separação de responsabilidades em dados: nunca modificar a fonte bruta, transformar de forma rastreável, e entregar uma camada limpa para consumo.

**Por que não usar o Great Expectations oficial?** A lib oficial tem overhead de configuração significativo e dependências pesadas. Implementar as expectations manualmente demonstra entendimento do conceito — que é o que importa para uma entrevista jr. O padrão é idêntico: `ExpectationResult` com `passed`, `details` e `severity`.

**Por que o Índice de Stress Econômico (ISE)?** É uma métrica derivada que você inventou — não existe nenhum dataset que você possa baixar pronto. Isso mostra raciocínio analítico: pegar três séries brutas, normalizá-las e combiná-las com pesos para criar algo novo. Em uma entrevista é muito mais interessante de explicar do que "calculei a média".

**Por que APIs brasileiras?** Diferencia o projeto de 95% dos portfólios que usam Kaggle ou APIs americanas. Um recrutador de empresa nacional reconhece imediatamente o IPCA, a Selic e o IBGE — o projeto tem contexto de negócio real sem precisar de explicação.
