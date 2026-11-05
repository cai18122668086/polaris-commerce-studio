"""Paired immutable-object backup and isolated restore for additive video tables.

Adapted from the repository's online replica backup procedure. Never restores
into or stops production. Runtime credentials remain server-local in 0600 files.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,secrets,subprocess,time
from pathlib import Path

def run(args, **kwargs): return subprocess.run(args,check=True,**kwargs)
def inspect(name): return json.loads(subprocess.check_output(["docker","inspect",name]))[0]
def private(path,body):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream:stream.write(body)
def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()

BACKUP_CODE = r"""
import os,boto3,tarfile,sys,json,hashlib,io
s=boto3.client('s3',endpoint_url=os.environ['POLARIS_S3_ENDPOINT_URL'],aws_access_key_id=os.environ['POLARIS_S3_ACCESS_KEY'],aws_secret_access_key=os.environ['POLARIS_S3_SECRET_KEY'],region_name=os.environ['POLARIS_S3_REGION'])
b=os.environ['POLARIS_S3_BUCKET'];records=[]
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
 for page in s.get_paginator('list_objects_v2').paginate(Bucket=b):
  for row in page.get('Contents',[]):
   value=s.get_object(Bucket=b,Key=row['Key']);data=value['Body'].read();name='objects/'+str(len(records))
   info=tarfile.TarInfo(name);info.size=len(data);archive.addfile(info,io.BytesIO(data))
   records.append(dict(name=name,key=row['Key'],sha256=hashlib.sha256(data).hexdigest(),size=len(data),content_type=value.get('ContentType','application/octet-stream'),metadata=value.get('Metadata',{})))
 data=json.dumps(records).encode();info=tarfile.TarInfo('manifest.json');info.size=len(data);archive.addfile(info,io.BytesIO(data))
"""

RESTORE_CODE = r"""
import os,tarfile,json,hashlib,boto3,subprocess,io,asyncio,time
from sqlalchemy import create_engine,text
from PIL import Image
assert 'polaris-video-restore-' in os.environ['POLARIS_DATABASE_URL']
assert 'polaris-video-restore-' in os.environ['POLARIS_S3_ENDPOINT_URL']
s=boto3.client('s3',endpoint_url=os.environ['POLARIS_S3_ENDPOINT_URL'],aws_access_key_id=os.environ['POLARIS_S3_ACCESS_KEY'],aws_secret_access_key=os.environ['POLARIS_S3_SECRET_KEY'],region_name=os.environ['POLARIS_S3_REGION'])
b=os.environ['POLARIS_S3_BUCKET']
for attempt in range(40):
 try:s.create_bucket(Bucket=b);break
 except Exception:time.sleep(1)
else:raise RuntimeError('Isolated object storage did not become ready')
with tarfile.open('/backup/objects.tar') as archive:
 records=json.load(archive.extractfile('manifest.json'))
 for row in records:
  data=archive.extractfile(row['name']).read();assert hashlib.sha256(data).hexdigest()==row['sha256']
  s.put_object(Bucket=b,Key=row['key'],Body=data,ContentType=row['content_type'],Metadata=row['metadata'])
engine=create_engine(os.environ['POLARIS_DATABASE_URL']);mapping={row['key']:row for row in records}
with engine.connect() as connection:
 before=connection.execute(text('SELECT version_num FROM alembic_version')).scalar()
 rows=list(connection.execute(text("SELECT object_key,sha256 FROM assets WHERE storage_provider='s3' AND deleted_at IS NULL AND lifecycle_status='ready'")))
 for key,sha in rows:
  assert key in mapping,'Database asset absent from paired objects'
  assert hashlib.sha256(s.get_object(Bucket=b,Key=key)['Body'].read()).hexdigest()==sha,'Restored checksum mismatch'
assert before=='20261030_0034'
subprocess.run(['python','-m','alembic','upgrade','head'],check=True)
with engine.connect() as connection:
 assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar()=='20261105_0039'
 assert connection.execute(text('SELECT count(*) FROM video_cloned_voices')).scalar()==0
from app.config import Settings
from app.main import create_app
from app.processing_consent import record_consent,POLICY_VERSION
from app.outbox import publish_pending_events
from fastapi.testclient import TestClient
from uuid import uuid4
app=create_app(Settings())
with TestClient(app) as client:
 assert client.get('/health/ready').status_code==200
 with app.state.session_factory() as session:
  record_consent(session,'usr_video_restore',{'policyVersion':POLICY_VERSION,'hongKongProcessing':True,'aiTraining':True},source='isolated_restore_drill');session.commit()
 def upload(name,kind):
  data=io.BytesIO();Image.new('RGB',(96,96),(235,197,64)).save(data,format='PNG')
  response=client.post('/api/v1/workspaces/ws_video_restore/assets',headers={'Idempotency-Key':str(uuid4())},data={'origin_kind':'upload','media_kind':kind},files={'file':(name,data.getvalue(),'image/png')})
  assert response.status_code==201,response.text
  return response.json()['id']
 source=upload('source.png','image');mask=upload('mask.png','mask')
 response=client.post('/api/v1/workspaces/ws_video_restore/jobs',headers={'Idempotency-Key':str(uuid4())},json={'type':'local_edit','intent':'submit','display_name':'restore drill','input':{'source_asset_id':source,'selection_mask_asset_id':mask},'configuration':{'instruction':'Change color','quality':'balanced','output_format':'png'}})
 assert response.status_code==201,response.text
 job=response.json()['id'];asyncio.run(app.state.task_runner.run(job))
 result=client.get('/api/v1/workspaces/ws_video_restore/jobs/'+job).json();assert result['status']=='completed',result['status']
print(json.dumps(dict(restored=True,objects=len(records),verified_db_assets=len(rows),schema_before=before,schema_after='20261105_0039',api_ready=True,mock_job_completed=True)))
"""

def main(revision,image):
    assert re.fullmatch(r"[0-9a-f]{40}",revision) and re.fullmatch(r"sha256:[0-9a-f]{64}",image)
    root=Path('/opt/polaris/backups/video-studio-'+revision[:12]);root.mkdir(mode=0o700)
    baseline={role:inspect('polaris-production-'+role+'-1') for role in ['api','postgres','minio','detail-api','detail-worker']}
    private(root/'baseline.private.json',json.dumps(baseline))
    with (root/'postgres.dump').open('xb') as stream:run(['docker','exec','polaris-production-postgres-1','pg_dump','-U','polaris','-d','polaris','-Fc'],stdout=stream)
    os.chmod(root/'postgres.dump',0o600);print('Database snapshot saved.',flush=True)
    with (root/'objects.tar').open('xb') as stream:run(['docker','exec','-i','polaris-production-api-1','python','-'],input=BACKUP_CODE.encode(),stdout=stream)
    os.chown(root/'objects.tar',10001,10001);os.chmod(root/'objects.tar',0o600);print('Immutable object snapshot saved.',flush=True)
    network='polaris-video-restore-'+revision[:12];pg=network+'-postgres';mini=network+'-minio'
    assert not pg.startswith('polaris-production-') and not mini.startswith('polaris-production-')
    run(['docker','network','create','--internal',network],stdout=subprocess.DEVNULL)
    password=secrets.token_urlsafe(32)
    private(root/'postgres.env','POSTGRES_USER=polaris\nPOSTGRES_DB=polaris\nPOSTGRES_PASSWORD='+password+'\n')
    private(root/'minio.env','MINIO_ROOT_USER=video_restore\nMINIO_ROOT_PASSWORD='+password+'\n')
    for name in [pg,mini]:run(['docker','volume','create',name],stdout=subprocess.DEVNULL)
    run(['docker','run','-d','--pull=never','--name',pg,'--network',network,'--memory','384m','--cpus','0.5','--env-file',str(root/'postgres.env'),'-v',pg+':/var/lib/postgresql',baseline['postgres']['Image']],stdout=subprocess.DEVNULL)
    run(['docker','run','-d','--pull=never','--name',mini,'--network',network,'--memory','384m','--cpus','0.5','--env-file',str(root/'minio.env'),'-v',mini+':/data',baseline['minio']['Image'],'server','/data'],stdout=subprocess.DEVNULL)
    for _ in range(40):
        if subprocess.run(['docker','exec',pg,'pg_isready','-U','polaris'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
        time.sleep(1)
    else:raise RuntimeError('Isolated PostgreSQL did not become ready')
    with (root/'postgres.dump').open('rb') as stream:run(['docker','exec','-i',pg,'pg_restore','-U','polaris','-d','polaris','--no-owner','--no-acl'],stdin=stream)
    env=dict(item.split('=',1) for item in baseline['api']['Config']['Env'])
    env.update(POLARIS_ENVIRONMENT='test',POLARIS_AUTH_MODE='development',POLARIS_DATABASE_URL='postgresql+psycopg://polaris:'+password+'@'+pg+':5432/polaris',POLARIS_STORAGE_BACKEND='s3',POLARIS_S3_ENDPOINT_URL='http://'+mini+':9000',POLARIS_S3_ACCESS_KEY='video_restore',POLARIS_S3_SECRET_KEY=password,POLARIS_S3_AUTO_CREATE_BUCKET='false',POLARIS_AUTO_CREATE_SCHEMA='false',POLARIS_TASK_RUNNER='mock',POLARIS_TASK_DISPATCHER='inline',POLARIS_AUTO_PROCESS_JOBS='false',POLARIS_ECOMMERCE_STARTUP_RECOVERY_ENABLED='false',POLARIS_ECOMMERCE_LOGIN_ENABLED='false',POLARIS_RETENTION_ENABLED='false',POLARIS_PROVIDER_QUOTA_ENABLED='false',POLARIS_WORKSPACE_CREDIT_ENFORCEMENT_ENABLED='false',POLARIS_AURORA_WORK_ROOT='/tmp/aurora-work',POLARIS_DEVELOPMENT_USER_ID='usr_video_restore',POLARIS_DEVELOPMENT_WORKSPACE_ID='ws_video_restore',POLARIS_MOCK_JOB_DELAY_SECONDS='0')
    for key in list(env):
        if key.endswith(('API_KEY','API_TOKEN','PROVIDER_ENABLED')):env[key]='false' if key.endswith('PROVIDER_ENABLED') else ''
    private(root/'restore.env','\n'.join(key+'='+value for key,value in env.items())+'\n')
    with (root/'restore-result.log').open('x') as stream:run(['docker','run','--rm','--pull=never','-i','--network',network,'--memory','768m','--cpus','1','--read-only','--tmpfs','/tmp:uid=10001,gid=10001,mode=0700','--env-file',str(root/'restore.env'),'-v',str(root/'objects.tar')+':/backup/objects.tar:ro',image,'python','-'],input=RESTORE_CODE.encode(),stdout=stream,stderr=subprocess.STDOUT)
    for role in ['api','detail-api','detail-worker']:
        assert inspect('polaris-production-'+role+'-1')['Id']==baseline[role]['Id']
    manifest={'revision':revision,'method':'database snapshot then immutable object copy; isolated DB/object restore with live-asset checksum verification','schema_before':'20261030_0034','schema_after_rehearsal':'20261105_0039','restore_passed':True,'production_unchanged':True,'artifacts':{p.name:{'bytes':p.stat().st_size,'sha256':digest(p)} for p in [root/'postgres.dump',root/'objects.tar']}}
    private(root/'manifest.json',json.dumps(manifest,indent=2))
    for name in [pg,mini]:
        assert inspect(name)['Id'] not in {v['Id'] for v in baseline.values()}
        run(['docker','stop','--time','30',name],stdout=subprocess.DEVNULL)
    print((root/'restore-result.log').read_text()[-1200:],flush=True)
    print(json.dumps({'backup_root':str(root),'restore_passed':True,'production_unchanged':True}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--revision',required=True);parser.add_argument('--image',required=True);args=parser.parse_args();main(args.revision,args.image)
