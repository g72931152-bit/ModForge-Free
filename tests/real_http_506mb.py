import asyncio, httpx, json, os, subprocess, sys, tempfile, time, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app'
SERVER=ROOT/'tests'/'_server_506'
SERVER.mkdir(exist_ok=True)
PORT=18991
ZIP=SERVER/'mod_506mb.zip'
BIG=SERVER/'big.bin'
SIZE=506*1024*1024

# Sparse input keeps fixture creation fast; ZIP_STORED preserves the actual 506 MiB payload size.
with BIG.open('wb') as f:
    f.truncate(SIZE)
with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_STORED) as z:
    z.writestr('vehicles/trafficcar/trafficcar.jbeam','{"trafficcar":{"information":{"name":"Traffic Test"}}}')
    z.writestr('vehicles/trafficcar/body.materials.json','{"body":{"class":"Material","Stages":[{"baseColorMap":"missing_body.dds"}]}}')
    z.write(BIG,'vehicles/trafficcar/mesh_506mb.bin')

proc=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port',str(PORT)],cwd=APP,env={**os.environ,'MODFORGE_DATA_ROOT':str(SERVER/'data'),'MODFORGE_WORK_ROOT':str(SERVER/'data'/'jobs'),'MODFORGE_JOB_RETENTION':'3600'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)

async def main():
    base=f'http://127.0.0.1:{PORT}'
    async with httpx.AsyncClient(timeout=None) as c:
        for _ in range(100):
            try:
                r=await c.get(base+'/api/health',timeout=2)
                if r.status_code==200: break
            except Exception: await asyncio.sleep(0.1)
        else: raise RuntimeError('server not ready')
        t=time.time()
        with ZIP.open('rb') as fh:
            r=await c.post(base+'/api/analyze', files={'files':('mod_506mb.zip',fh,'application/zip')}, data={
                'source_kind':'zip','source_name':'mod_506mb.zip','asset_type':'vehicle','asset_subtype':'sedan',
                'task_mode':'repair','repair_mode':'standard','processing_speed':'standard','prepare_only':'0',
                'priority_json':'["resources","vehicle","ai_traffic"]',
                'repair_actions_json':json.dumps(['resources','syntax','glass','mirrors','pbr','lighting','vehicle','compat_039','ai_traffic','safe_cleanup']),
                'repair_exclusions_json':'[]','excluded_files_json':'[]','ai_traffic_scope':'all'
            })
        print('upload',r.status_code,r.text[:300], 'sec', round(time.time()-t,2))
        if r.status_code!=200: raise RuntimeError(r.text)
        jid=r.json()['job_id']
        last=''
        start=time.time()
        seen_large=False
        while time.time()-start<900:
            j=(await c.get(base+f'/api/jobs/{jid}',timeout=10)).json()
            status=j.get('status'); label=j.get('stage_label',''); detail=j.get('stage_detail','')
            sig=(status,label,detail[:120],j.get('progress'))
            if sig!=last:
                print(status,label,j.get('progress'),detail[:180])
                last=sig
            if j.get('large_task_status')=='done': seen_large=True
            if status in {'done','error','cancelled'}:
                print('terminal',status,'error=',j.get('error'),'large=',j.get('large_task_status'),'seen_large=',seen_large)
                if status!='done': raise RuntimeError(str(j.get('error')))
                report=await c.get(base+f'/api/jobs/{jid}/report')
                print('report',report.status_code, (report.text[:600]))
                head=await c.head(base+f'/api/jobs/{jid}/download')
                print('download HEAD',head.status_code,head.headers.get('x-modforge-artifact-size'))
                if head.status_code!=200: raise RuntimeError(head.text)
                return
            await asyncio.sleep(0.5)
        raise RuntimeError('timeout waiting for terminal job')

try:
    asyncio.run(main())
    print('REAL 506MB HTTP E2E: PASS')
finally:
    proc.terminate()
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired: proc.kill()
