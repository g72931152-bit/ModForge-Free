import asyncio, json, zipfile
from pathlib import Path

import httpx
import pytest

import main

@pytest.mark.asyncio
async def test_preparation_can_recover_after_early_source_release(tmp_path):
    old_root, old_jobs = main.WORK_ROOT, dict(main.jobs)
    main.jobs.clear(); main.WORK_ROOT=tmp_path/'jobs'; main.WORK_ROOT.mkdir()
    try:
        jid='recover-prep'
        root=main.WORK_ROOT/jid; (root/'payload').mkdir(parents=True); (root/'source').mkdir(parents=True)
        (root/'payload'/'vehicles'/'car').mkdir(parents=True)
        (root/'payload'/'vehicles'/'car'/'car.jbeam').write_text('{"car":{"information":{"name":"Car"}}}',encoding='utf-8')
        main.jobs[jid]={"job_id":jid,"root":str(root),"status":"preparing","source_kind":"zip","original_name":"car.zip","source_name":"car.zip","prepare_only":True,"task_mode":"repair","asset_type":"vehicle","asset_subtype":"sedan","repair_actions":list(main.DEFAULT_REPAIR_ACTIONS),"repair_exclusions":[],"excluded_files":[],"selected_variant":None,"processing_speed":"standard","_cancel_event":__import__('threading').Event(),"_pause_event":__import__('threading').Event(),"_timeout_event":__import__('threading').Event(),"uploaded_bytes":0}
        await main.prepare_job(jid, root, 'car.zip', 'zip')
        assert main.jobs[jid]['status']=='prepared'
        assert main.jobs[jid]['recovery_basis']=='working_copy'
    finally:
        main.WORK_ROOT=old_root; main.jobs.clear(); main.jobs.update(old_jobs)

@pytest.mark.asyncio
async def test_runtime_and_seo_routes_are_served(tmp_path):
    transport=httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport,base_url='http://test') as c:
        r=await c.get('/runtime-config.js'); assert r.status_code==200; assert '__MF_API_ORIGIN__' in r.text
        r=await c.get('/robots.txt'); assert r.status_code==200 and 'Sitemap:' in r.text
        r=await c.get('/sitemap.xml'); assert r.status_code==200 and '<urlset' in r.text
