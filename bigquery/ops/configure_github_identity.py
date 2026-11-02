"""Dedicated portfolio project only. No keys are created or printed."""
import json
import os
from pathlib import Path
import subprocess
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

PROJECT='gabriel-econ-bq-261029-8d72'
NUMBER='622896976570'
REPO_ID='1186847115'
OWNER_ID='210399529'
REPO='gabrielassisp/Brazil-Pipeline-Project'
POOL='portfolio-github'
PROVIDER='economic-pipeline'
SA=f'economic-pipeline@{PROJECT}.iam.gserviceaccount.com'
SDK=Path('C:/Program Files (x86)/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd')
ROOT=Path(__file__).resolve().parents[2]
os.environ['CLOUDSDK_CONFIG']=str(ROOT/'.gcloud-portfolio')


def cli(*args):
    result=subprocess.run([str(SDK),*args,'--quiet','--format=json'],capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def exists(*args):
    result=subprocess.run([str(SDK),*args,'--quiet','--format=json'],capture_output=True,text=True)
    if result.returncode==0:return True
    if 'NOT_FOUND' in result.stderr or 'not found' in result.stderr.lower():return False
    raise RuntimeError(result.stderr.strip())


billing=cli('billing','projects','describe',PROJECT)
if billing.get('billingEnabled'):
    raise RuntimeError('Expected the billing-disabled dedicated portfolio project')
cli('services','enable','iam.googleapis.com','iamcredentials.googleapis.com','sts.googleapis.com',f'--project={PROJECT}')
if not exists('iam','service-accounts','describe',SA,f'--project={PROJECT}'):
    cli('iam','service-accounts','create','economic-pipeline',f'--project={PROJECT}',
        '--display-name=Portfolio economic pipeline runtime')
if not exists('iam','workload-identity-pools','describe',POOL,'--location=global',f'--project={PROJECT}'):
    cli('iam','workload-identity-pools','create',POOL,'--location=global',f'--project={PROJECT}',
        '--display-name=Portfolio GitHub Actions')
condition=(f"assertion.repository_id == '{REPO_ID}' && assertion.repository_owner_id == '{OWNER_ID}' "
           f"&& assertion.ref == 'refs/heads/main' && assertion.workflow_ref == '{REPO}/.github/workflows/bigquery-cloud.yml@refs/heads/main'")
provider_args=['--location=global',f'--workload-identity-pool={POOL}',f'--project={PROJECT}']
if not exists('iam','workload-identity-pools','providers','describe',PROVIDER,*provider_args):
    cli('iam','workload-identity-pools','providers','create-oidc',PROVIDER,*provider_args,
        '--issuer-uri=https://token.actions.githubusercontent.com',
        '--attribute-mapping=google.subject=assertion.sub,attribute.repository_id=assertion.repository_id',
        '--attribute-condition='+condition)
else:
    current=cli('iam','workload-identity-pools','providers','describe',PROVIDER,*provider_args)
    if current.get('attributeCondition')!=condition:
        raise RuntimeError('Existing provider condition differs; inspect before changing trust')
member=f'principalSet://iam.googleapis.com/projects/{NUMBER}/locations/global/workloadIdentityPools/{POOL}/attribute.repository_id/{REPO_ID}'
cli('iam','service-accounts','add-iam-policy-binding',SA,f'--project={PROJECT}',
    '--role=roles/iam.workloadIdentityUser','--member='+member)
for role in ['roles/bigquery.jobUser','roles/serviceusage.serviceUsageConsumer']:
    cli('projects','add-iam-policy-binding',PROJECT,'--member=serviceAccount:'+SA,'--role='+role)
# Access token remains in process memory; never printed or persisted.
token=subprocess.check_output([str(SDK),'auth','print-access-token'],text=True).strip()
client=bigquery.Client(project=PROJECT,credentials=Credentials(token=token))
for layer in ['bronze','silver','gold']:
    dataset=client.get_dataset(f'{PROJECT}.portfolio_econ_live_{layer}')
    if (dataset.labels or {}).get('app')!='brazil-econ-portfolio':
        raise RuntimeError('Dataset is not owned by the demonstration')
    entry=bigquery.AccessEntry('WRITER','userByEmail',SA)
    entries=list(dataset.access_entries)
    if entry not in entries:
        dataset.access_entries=entries+[entry]
        client.update_dataset(dataset,['access_entries'])
print(json.dumps(dict(project=PROJECT,billing_enabled=False,service_account=SA,
    provider=f'projects/{NUMBER}/locations/global/workloadIdentityPools/{POOL}/providers/{PROVIDER}',
    trust='numeric repository + owner + main + exact workflow',dataset_access='WRITER on the three demo datasets only')))
