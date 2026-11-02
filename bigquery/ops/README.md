# Operação agendada do pipeline

A federação OIDC foi configurada no projeto dedicado, sem chaves JSON e com faturamento desativado. A confiança é restrita ao repositório/dono por ID numérico, main e workflow exato. As permissões do runtime são documentadas no README principal.

A publicação do workflow dispara uma execução de validação. Confira o resultado no Actions antes de afirmar que a execução federada passou. O cron diário é 11:00 UTC (08:00 em São Paulo), janela histórica 2022–2024.

`configure_github_identity.py` é um script administrativo idempotente e específico para este projeto. Requer login administrativo; não roda no cron. Ele recusa provider com condição diferente e datasets sem o rótulo da demonstração. Nunca cria chave JSON nem imprime tokens.

`ops/summarize_run.py` produz o resumo da carga no Actions usando apenas os artefatos da execução.
