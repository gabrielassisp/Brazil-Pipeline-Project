import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from .core import collect, validate_window
from .warehouse import Config, Warehouse

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, content):
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False, default=str), encoding='utf-8')


def dbt_env(config, start, end, snapshot_date):
    return {**os.environ, 'BQ_PROJECT':config.project, 'BQ_LOCATION':config.location,
            'BQ_DATASET_PREFIX':config.prefix,'BQ_MODE':config.mode,
            'BQ_START_DATE':start,'BQ_END_DATE':end,'BQ_SNAPSHOT_DATE':snapshot_date,
            'BQ_MAX_BYTES_BILLED':str(config.maximum_bytes_billed),
            'DBT_SEND_ANONYMOUS_USAGE_STATS':'false'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Brazil Economic Pipeline · BigQuery + dbt')
    parser.add_argument('command',choices=['extract','bootstrap','run','query'])
    parser.add_argument('--mode',choices=['live','fixture'],default=os.getenv('BQ_MODE','live'))
    parser.add_argument('--project',default=os.getenv('BQ_PROJECT',''))
    parser.add_argument('--prefix',default=os.getenv('BQ_DATASET_PREFIX','portfolio_econ'))
    parser.add_argument('--location',default=os.getenv('BQ_LOCATION','US'))
    parser.add_argument('--maximum-bytes-billed',type=int,default=int(os.getenv('BQ_MAX_BYTES_BILLED','100000000')))
    parser.add_argument('--start',default='2022-01-01')
    parser.add_argument('--end',default='2024-12-31')
    parser.add_argument('--output',type=Path,default=ROOT/'output')
    args = parser.parse_args(argv)
    validate_window(args.start,args.end)
    config = None
    if args.command != 'extract':
        config = Config(args.project,args.prefix,args.location,args.mode,args.maximum_bytes_billed)
    if args.command == 'bootstrap':
        Warehouse(config).bootstrap()
        print(json.dumps({'status':'datasets_ready','datasets':[config.dataset(x) for x in ('bronze','silver','gold')]}))
        return
    if args.command == 'query':
        print(json.dumps(Warehouse(config).query_latest(),indent=2,default=str))
        return
    run_id = uuid.uuid4().hex
    directory = args.output / run_id
    directory.mkdir(parents=True,exist_ok=False)
    clock = time.perf_counter()
    report = dict(run_id=run_id, status='running', mode=args.mode,
                  start=args.start,end=args.end, started_at=datetime.now(timezone.utc).isoformat())
    try:
        rows = collect(args.start,args.end,args.mode)
        ndjson = ''.join(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n' for row in rows)
        (directory/'observations.ndjson').write_text(ndjson,encoding='utf-8')
        report.update(row_count=len(rows),sources={source:sum(row['source']==source for row in rows) for source in ('ibge','bcb','worldbank')},
                      sha256=hashlib.sha256(ndjson.encode()).hexdigest(), status='extracted')
        if args.command == 'run':
            warehouse = Warehouse(config)
            report['load'] = warehouse.load(rows,run_id)
            # Cloud step requires the datasets created by the explicit bootstrap command.
            executable = str(Path(sys.executable).parent / ('dbt.exe' if os.name=='nt' else 'dbt'))
            flags = ['--project-dir',str(ROOT/'dbt'),
                   '--profiles-dir',str(ROOT/'dbt'),'--target-path',str(directory/'dbt-target'),
                   '--log-path',str(directory/'dbt-logs')]
            for command in ('build','docs generate'):
                subprocess.run([executable,'--no-use-colors']+command.split()+flags+['--threads','1'],
                               env=dbt_env(config,args.start,args.end,rows[0]['ingestion_date']),check=True,
                               timeout=420 if command=='build' else 180)
            report['query'] = warehouse.query_latest()
            report['status'] = 'success'
        else:
            report['status'] = 'extracted_only'
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__)
        raise
    finally:
        report.update(finished_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=round(time.perf_counter()-clock,3))
        write_json(directory/'run.json',report)
        print(json.dumps({'status':report['status'],'report':str(directory/'run.json'),'rows':report.get('row_count')},indent=2))


if __name__ == '__main__':
    main()
