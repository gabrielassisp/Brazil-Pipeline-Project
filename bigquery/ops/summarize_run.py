"""Write bounded, non-secret execution evidence to the Actions summary."""
import json
import os
from pathlib import Path

reports=list(Path('output').glob('*/run.json'))
if not reports:
    summary='## Economic pipeline\n\nNenhum relatório foi gerado; consulte a etapa que falhou.\n'
else:
    report_path=max(reports,key=lambda p:p.stat().st_mtime)
    report=json.loads(report_path.read_text())
    result_path=report_path.parent/'dbt-target/run_results.json'
    results=json.loads(result_path.read_text()).get('results',[]) if result_path.exists() else []
    models=sum(x['unique_id'].startswith('model.') and x['status']=='success' for x in results)
    tests=sum(x['unique_id'].startswith('test.') and x['status']=='pass' for x in results)
    summary=(f"## Economic pipeline — {report['status']}\n\n"
             f"- Modo: `{report['mode']}`\n"
             f"- Janela histórica: {report['start']} a {report['end']}\n"
             f"- Registros: {report.get('row_count',0)}\n"
             f"- Modelos aprovados: {models}; testes dbt aprovados: {tests}\n"
             f"- Duração total: {report.get('elapsed_seconds',0)} s\n"
             f"- Load job: `{report.get('load',{}).get('job_id','não disponível')}`\n\n"
             "Relatórios e catálogo estão no artefato bigquery-run-evidence, retido por sete dias.\n")
if os.getenv('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as handle:handle.write(summary)
else:
    print(summary)
