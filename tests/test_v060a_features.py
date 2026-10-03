from __future__ import annotations
import asyncio, json, threading, zipfile
from pathlib import Path
from fastapi.testclient import TestClient
import httpx
import pytest
import main


def _job(root, **extra):
    d={"job_id":"feature-test","root":str(root),"status":"running","repair_mode":"standard","task_mode":"repair",
       "repair_actions":list(main.DEFAULT_REPAIR_ACTIONS),"repair_exclusions":[],"excluded_files":[],
       "_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event()}
    d.update(extra); return d


def test_ai_traffic_adaptation_creates_groups_and_emergency_metadata(tmp_path):
    root=tmp_path/'mod'; v=root/'vehicles'/'ambulance_2019'; v.mkdir(parents=True)
    (v/'ambulance_2019.jbeam').write_text('{"body":{"information":{"name":"Ambulance"},"siren":"yes"}}','utf-8')
    (v/'rescue.pc').write_text('{"name":"Rescue","description":"Emergency ambulance","model":""}','utf-8')
    job=_job(root, asset_type='vehicle', asset_subtype='sedan')
    issues=main.repair_ai_traffic(root,job)
    rules={x.get('rule_id') for x in issues}
    assert 'AI-PC-MODEL' in rules
    assert 'AI-INFO-CREATE' in rules
    assert 'AI-TRAFFIC-GROUP' in rules
    assert 'AI-EMERGENCY-GROUP' in rules
    info=json.loads((v/'info_rescue.json').read_text('utf-8'))
    assert info['Config Type']=='Service'
    assert info['Population']==main.AI_TRAFFIC_EMERGENCY_POPULATION
    group=json.loads((root/'vehicleGroups'/'modmendryx_emergency_traffic.vehGroup.json').read_text('utf-8'))
    assert group['data'][0]['model']=='ambulance_2019'


@pytest.mark.asyncio
async def test_preparation_endpoint_returns_before_engine_starts(tmp_path):
    old_root=main.WORK_ROOT
    old_jobs=dict(main.jobs); old_global=main.job_reservations_global; old_client=dict(main.job_reservations_client)
    main.jobs.clear(); main.job_reservations_global=0; main.job_reservations_client.clear()
    main.WORK_ROOT=tmp_path/'jobs'; main.WORK_ROOT.mkdir()
    transport = httpx.ASGITransport(app=main.app)
    client=httpx.AsyncClient(transport=transport,base_url='http://test')
    z=tmp_path/'car.zip'
    with zipfile.ZipFile(z,'w') as out:
        out.writestr('vehicles/car/car.jbeam','{"car":{"information":{"name":"Car"}}}')
        out.writestr('vehicles/car/body.materials.json','{"body":{"class":"Material","Stages":[{"baseColorMap":"missing.png"}]}}')
    try:
        r=await client.post('/api/analyze', files={'files':('car.zip',z.open('rb'),'application/zip')}, data={
            'source_kind':'zip','source_name':'car.zip','asset_type':'vehicle','asset_subtype':'sedan',
            'task_mode':'repair','repair_mode':'standard','prepare_only':'1','repair_actions_json':json.dumps(main.DEFAULT_REPAIR_ACTIONS)})
        assert r.status_code==200, r.text
        jid=r.json()['job_id']
        for _ in range(200):
            j=(await client.get(f'/api/jobs/{jid}')).json()
            if j['status']=='prepared': break
            await asyncio.sleep(.03)
        assert j['status']=='prepared'
        assert j['start_available'] is True
        assert isinstance(j['preparation'],dict)
        assert main.jobs[jid].get('_run_started') is None
        # Start explicitly and wait for completion.
        sr=await client.post(f'/api/jobs/{jid}/start')
        assert sr.status_code==200, sr.text
        for _ in range(120):
            j=(await client.get(f'/api/jobs/{jid}')).json()
            if j['status'] in {'done','error','cancelled'}: break
            await asyncio.sleep(.05)
        assert j['status']=='done', j.get('error') or j.get('stage_detail')
        report=(await client.get(f'/api/jobs/{jid}/report')).json()
        assert 'repair_effectiveness' in report
        assert report.get('changed_files')
    finally:
        await client.aclose()
        main.WORK_ROOT=old_root
        main.jobs.clear(); main.jobs.update(old_jobs); main.job_reservations_global=old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)


def test_prepared_cancel_is_terminal(tmp_path):
    jid='prepared-cancel'
    root=tmp_path/jid; (root/'source').mkdir(parents=True)
    job=_job(root,status='prepared',job_id=jid,prepare_only=True,start_available=True)
    main.jobs[jid]=job
    client=TestClient(main.app)
    try:
        r=client.post(f'/api/jobs/{jid}/cancel')
        assert r.status_code==200
        assert r.json()['status']=='cancelled'
    finally:
        main.jobs.pop(jid,None)
