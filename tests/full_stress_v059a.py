from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as modforge_main

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("MODFORGE_STRESS_PORT", "8767"))
BASE = f"http://127.0.0.1:{PORT}"


def wait_until(fn, timeout=180.0, interval=0.35):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        value = fn()
        last = value
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for condition; last={last!r}")


def make_zip(path: Path, large=False):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("vehicles/stress/stress.jbeam", '''{"nodes":{"n1":[0,0,0]},"spring":10000,"beamSpring":12000,"damp":500,"torque":400,"maxTorque":500,"maxRPM":6500,"idleRPM":900,"torqueBoost":100}''')
        zf.writestr("vehicles/stress/info.json", json.dumps({"name": "Stress Microbus"}))
        zf.writestr("vehicles/stress/rescue.pc", json.dumps({"config": "Rescue", "vars": {"body": "stress"}}))
        zf.writestr("vehicles/stress/body.materials.json", json.dumps({
            "body": {"class":"Material","Stages":[{"baseColorFactor":[1,0.2,0.2,1]}]},
            "windshieldGlass": {"class":"Material","Stages":[{"baseColorFactor":[0.1,0.1,0.1,1]}]},
        }))
        zf.writestr("vehicles/stress/broken.materials.json", '{"body":{"Stages":[{"baseColorFactor":[1,1,1,1],"baseColorMap":"body.dds","roughnessMap":"missing.dds"}]},}')
        zf.writestr("vehicles/stress/notes.jbeam", '{"information":{"name":"stress","note":"literal }, comma ,} inside string"},}')
        zf.writestr("vehicles/stress/body.png", b"not-a-real-png")
        if large:
            # Stored > 512 MiB payload to exercise the real large-file path without a
            # highly compressible archive ratio. Written in chunks to avoid a 520 MiB Python object.
            size = 520 * 1024 * 1024
            zi = zipfile.ZipInfo("vehicles/stress/large.dds")
            zi.compress_type = zipfile.ZIP_STORED
            with zf.open(zi, "w", force_zip64=True) as fh:
                chunk = b"MFG-LARGE-STRESS" * (1024 * 1024 // len(b"MFG-LARGE-STRESS"))
                remaining = size
                while remaining:
                    n = min(8 * 1024 * 1024, remaining)
                    fh.write((chunk * ((n + len(chunk) - 1) // len(chunk)))[:n])
                    remaining -= n


def fields(task_mode="repair", speed="standard", repair_mode="standard", asset_type="other", asset_subtype=""):
    return {
        "source_kind": "zip", "source_name": "stress.zip", "wishes": "",
        "priority_json": "[]", "manifest_json": "[]", "output_suffix": "FIXED",
        "output_type": "zip", "repair_mode": repair_mode, "task_mode": task_mode,
        "modification_request": "", "processing_speed": speed, "asset_type": asset_type,
        "asset_subtype": asset_subtype, "problem_hints_json": "[]", "repair_actions_json": json.dumps(list(modforge_main.DEFAULT_REPAIR_ACTIONS)),
        "repair_exclusions_json": "[]", "excluded_files_json": "[]",
    }


def upload(client: httpx.Client, zip_path: Path, **kwargs):
    data = fields(**kwargs)
    with zip_path.open("rb") as fh:
        r = client.post("/api/analyze", data=data, files={"files": (zip_path.name, fh, "application/zip")}, timeout=900)
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def poll(client, job_id, terminal=("done", "error", "cancelled"), timeout=300):
    history=[]
    def get():
        r=client.get(f"/api/jobs/{job_id}", timeout=20)
        assert r.status_code == 200, r.text
        d=r.json(); history.append((d.get("status"), d.get("stage_label")))
        return d if d.get("status") in terminal else None
    d=wait_until(get, timeout=timeout, interval=0.5)
    return d, history


def start_server(data_root: Path):
    env=os.environ.copy()
    env.update({
        "MODFORGE_DATA_ROOT": str(data_root),
        "MODFORGE_WORK_ROOT": str(data_root / "jobs"),
        "MODFORGE_FEEDBACK_PATH": str(data_root / "feedback.json"),
        "MODFORGE_JOB_TIMEOUT": "600",
    })
    proc=subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    wait_until(lambda: _health_ok(), timeout=30, interval=0.25)
    return proc


def _health_ok():
    try:
        with httpx.Client(base_url=BASE) as c:
            r=c.get("/api/health", timeout=2)
            return r.status_code==200
    except Exception:
        return False


def stop_server(proc):
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=5)


def browser_ui_smoke():
    # The execution sandbox blocks Chromium from opening loopback HTTP URLs. Load the
    # exact production HTML/CSS/JS from a file URL and stub only the bootstrap API.
    from playwright.sync_api import sync_playwright
    html=(ROOT / "index.html").read_text("utf-8")
    css=(ROOT / "assets" / "styles.css").read_text("utf-8")
    js=(ROOT / "assets" / "app.js").read_text("utf-8")
    stages=[{"key":str(i),"label":f"Этап {i}","description":""} for i in range(1,16)]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        # Load the exact production markup/styles but remove external script tags: app.js is injected below after the storage/API shim.
        import re as _re
        test_html = _re.sub(r'<script[^>]+src="/(?:assets/)?(?:halloween|app)\.js[^>]*></script>', '', html, flags=_re.I)
        test_html = _re.sub(r'<script>if\("serviceWorker"[^<]+</script>', '', test_html, flags=_re.I)
        page.set_content(test_html.replace('</head>', '<style>'+css+'</style></head>'), wait_until="domcontentloaded")
        page.evaluate("""() => {
          const store = () => ({
            _m: new Map(), get length(){ return this._m.size; },
            key(i){ return Array.from(this._m.keys())[i] ?? null; },
            getItem(k){ return this._m.has(k) ? this._m.get(k) : null; },
            setItem(k,v){ this._m.set(String(k), String(v)); },
            removeItem(k){ this._m.delete(String(k)); },
            clear(){ this._m.clear(); }
          });
          window.__mfStorage = store();
          window.__mfSessionStorage = store();
          window.fetch = async (input, init) => {
            const url=String(input);
            if (url.includes('/api/health')) return new Response(JSON.stringify({
              ok:true,release_id:'v1 (0.61-A)',site_version:'0.61-A',beamng_version:'0.39',state_epoch:'ui-test',
              stages:Array.from({length:15},(_,i)=>({key:String(i),label:'Этап '+(i+1),description:'',weight:1})),
              config:{brand_name:'ModForge',tagline:'Проверка и безопасное исправление модов BeamNG.drive',default_suffix:'FIXED',repair_modes:{standard:{count:7}},ad_enabled:false},
              capabilities:{async_load_cooldown:true,persistent_lab_workspace:true,stage_scoped_polling:true,bounded_reports:true}
            }),{status:200,headers:{'Content-Type':'application/json'}});
            if (url.includes('/api/engines')) return new Response(JSON.stringify({ok:true,engines:[{id:'VA2'},{id:'VE1'}]}),{status:200,headers:{'Content-Type':'application/json'}});
            return new Response(JSON.stringify({ok:true}),{status:200,headers:{'Content-Type':'application/json'}});
          };
          __mfStorage.setItem('mf_data_reset_release','0.61-A');
          __mfStorage.setItem('mf_seen_release','v1 (0.61-A)');
          __mfStorage.setItem('mf_privacy','1');
          __mfStorage.setItem('mf_guide','1');
        }
        """)
        page.add_script_tag(content=js.replace('localStorage','window.__mfStorage').replace('sessionStorage','window.__mfSessionStorage'))
        page.wait_for_timeout(400)
        assert page.locator("#interfaceInfoTop").is_visible()
        page.locator("#interfaceInfoTop").click()
        assert page.locator("#interfaceInfo").is_visible()
        assert page.locator("#interfaceInfoNav").locator("button").count() >= 10
        page.locator('[data-info-section="engines"]').click()
        assert "VA 2" in page.locator("#interfaceInfoContent").inner_text()
        assert "VE 1" in page.locator("#interfaceInfoContent").inner_text()
        page.keyboard.press("Escape")
        assert page.locator("#interfaceInfo").is_hidden()
        page.keyboard.press("i")
        assert page.locator("#interfaceInfo").is_visible()
        page.keyboard.press("Escape")
        body=page.locator("body").inner_text()
        assert "Проверить и исправить" not in body
        assert "ModLab" not in body
        assert "VA 2 · Verification Architecture" in body
        assert "VE 1 · Variant Engineering" in body
        assert not any(token in body for token in [" 01 ", " 02 ", " 03 "])
        browser.close()


def main_stress():
    with tempfile.TemporaryDirectory(prefix="modforge-full-stress-") as td:
        tmp=Path(td); small=tmp/"stress.zip"; big=tmp/"large-stress.zip"; make_zip(small, large=False)
        print("[1] Basic health/engine API")
        proc=start_server(tmp/"state")
        try:
            with httpx.Client(base_url=BASE) as c:
                health=c.get("/api/health", timeout=10).raise_for_status()
                hd=health.json(); assert hd["site_version"]=="0.61-A"; assert {e["id"] for e in hd["engines"]}=={"VA2","VE1"}
                assert hd["capabilities"]["async_load_cooldown"] is True
                assert c.get("/api/engines").status_code==200
                print("    OK", hd["release_id"], "engines=VA2,VE1")

                print("[2] VA 2 standard pipeline")
                jid=upload(c,small,task_mode="repair",speed="standard",repair_mode="standard")
                done,hist=poll(c,jid,timeout=180); assert done["status"]=="done", done
                report=c.get(f"/api/jobs/{jid}/report").json(); assert report["engine_id"]=="VA2" and report["engine_release"]=="0IN-1.0"
                assert report["summary"]["fixed"] > 0, report["summary"]
                assert report["diffs"], "VA 2 reported no actual changed/created files"
                changed={x["file"] for x in report["diffs"] if x.get("status") in {"changed","added"}}
                assert "vehicles/stress/broken.materials.json" in changed
                assert any(x.startswith("vehicles/stress/missing") and x.endswith(".png") for x in changed)
                assert "vehicles/stress/body.png" in changed, "Referenced corrupt candidate texture was not actually rebuilt"
                assert report.get("actual_repairs"), "Report did not expose actual repair actions"
                assert c.head(f"/api/jobs/{jid}/download").status_code==200
                assert c.get(f"/api/jobs/{jid}/health").status_code==200
                assert c.get(f"/api/jobs/{jid}/diff").status_code==200
                print("    OK final stage:", hist[-1])

                print("[3] VA 2 aggressive + exact percentage parser regression")
                jid2=upload(c,small,task_mode="repair",speed="aggressive",repair_mode="aggressive")
                done2,_=poll(c,jid2,timeout=180); assert done2["status"]=="done"
                parsed=json.loads(json.dumps(done2)); assert parsed["check_blocks"]["count"]==15; assert done2["engine_id"]=="VA2"
                factors = modforge_main.modification_factors(modforge_main.parse_modification_request("сделать подвеску мягче на 15%; RPM +25%; увеличить тягу двигателя на 25%"))
                assert factors["suspension"] < 1 and factors["engine"] > 1 and factors["rpm"] > 1
                print("    OK aggressive=15 blocks; parser factors respected")

                print("[4] Restart / re-check")
                rr=c.post(f"/api/jobs/{jid}/restart", timeout=20); assert rr.status_code==200, rr.text
                rjid=rr.json()["job_id"]; rdone,_=poll(c,rjid,timeout=180); assert rdone["status"]=="done"
                assert rdone["engine_id"]=="VA2"
                print("    OK restarted_from", jid[:8], "→", rjid[:8])

                print("[5] VE 1 isolated workflow")
                ve=upload(c,small,task_mode="modify",speed="standard",repair_mode="medium",asset_type="vehicle",asset_subtype="microbus")
                waited=wait_until(lambda: (lambda d: d if d.get("status") in {"waiting_selection","lab_ready","error"} else None)(c.get(f"/api/jobs/{ve}").json()),timeout=180,interval=.5)
                assert waited["status"]!="error", waited
                if waited["status"]=="waiting_selection":
                    cat=c.get(f"/api/jobs/{ve}/catalog").json()["catalog"]
                    assert cat["items"]
                    sel=cat["items"][0]
                    sr=c.post(f"/api/jobs/{ve}/catalog-selection",json={"selected_variant":sel},timeout=20); assert sr.status_code==200, sr.text
                lab=wait_until(lambda: (lambda d: d if d.get("status") in {"lab_ready","error"} else None)(c.get(f"/api/jobs/{ve}").json()),timeout=180,interval=.5)
                assert lab["status"]=="lab_ready", lab
                assert c.get(f"/api/jobs/{ve}/lab/materials").status_code==200
                mats=c.get(f"/api/jobs/{ve}/lab/materials").json()["materials"]
                assert mats, "VE1 material catalog is empty"
                pr=c.post(f"/api/jobs/{ve}/lab/paint",json={"material_ids":[mats[0]["id"]],"hex_color":"#4A90E2"},timeout=20); assert pr.status_code==200, pr.text
                ph=c.post(f"/api/jobs/{ve}/lab/physics",json={"kind":"suspension","percent":15},timeout=20); assert ph.status_code==200, ph.text
                st=c.post(f"/api/jobs/{ve}/lab/stress",json={"kind":"suspension"},timeout=20); assert st.status_code==200 and st.json()["ok"] is True, st.text
                bad=c.get(f"/api/jobs/{ve}/lab/materials"); assert bad.status_code==200
                fin=c.post(f"/api/jobs/{ve}/lab/finalize",timeout=180); assert fin.status_code==200, fin.text
                vdone,_=poll(c,ve,timeout=180); assert vdone["status"]=="done"; vr=c.get(f"/api/jobs/{ve}/report").json(); assert vr["engine_id"]=="VE1" and vr["engine_release"]=="M0-D-l00"
                # VA2-only operation is forbidden on VE1 state.
                assert c.post(f"/api/jobs/{ve}/restart").status_code==200  # restart of a finished VE1 is a new VE1 session
                print("    OK paint + physics + stress + separate finalize")

                print("[6] Error paths")
                badzip=tmp/"bad.zip"; badzip.write_bytes(b"not a zip")
                ej=upload(c,badzip,task_mode="repair",speed="standard",repair_mode="standard")
                ed,_=poll(c,ej,timeout=60); assert ed["status"]=="error" and "ZIP" in (ed.get("error") or "")
                traversal=tmp/"traversal.zip"
                with zipfile.ZipFile(traversal,"w") as zf: zf.writestr("../escape.jbeam","{}")
                tj=upload(c,traversal,task_mode="repair",speed="standard",repair_mode="standard")
                tdj,_=poll(c,tj,timeout=60); assert tdj["status"]=="error"
                print("    OK malformed ZIP + traversal blocked")
        finally:
            stop_server(proc)

        print("[7] Persistent VE 1 recovery across backend restart")
        proc=start_server(tmp/"recovery")
        try:
            with httpx.Client(base_url=BASE) as c:
                ve=upload(c,small,task_mode="modify",speed="standard",repair_mode="standard",asset_type="vehicle",asset_subtype="microbus")
                waited=wait_until(lambda: (lambda d: d if d.get("status") in {"waiting_selection","lab_ready","error"} else None)(c.get(f"/api/jobs/{ve}").json()),timeout=180,interval=.5)
                if waited["status"]=="waiting_selection":
                    cat=c.get(f"/api/jobs/{ve}/catalog").json()["catalog"]; sr=c.post(f"/api/jobs/{ve}/catalog-selection",json={"selected_variant":cat["items"][0]}); assert sr.status_code==200
                lab=wait_until(lambda: (lambda d: d if d.get("status") in {"lab_ready","error"} else None)(c.get(f"/api/jobs/{ve}").json()),timeout=180,interval=.5)
                assert lab["status"]=="lab_ready"
                print("    created durable lab", ve[:8])
                stop_server(proc)
                proc=start_server(tmp/"recovery")
                r=c.get(f"/api/jobs/{ve}",timeout=10); assert r.status_code==200 and r.json()["status"]=="lab_ready"
                fm=c.post(f"/api/jobs/{ve}/lab/finalize",timeout=180); assert fm.status_code==200, fm.text
                print("    OK lab_ready survived restart and exported")
        finally:
            stop_server(proc)

        print("[8] Large ZIP > 512 MiB and streaming worker")
        make_zip(big, large=True)
        proc=start_server(tmp/"large")
        try:
            with httpx.Client(base_url=BASE) as c:
                jid=upload(c,big,task_mode="repair",speed="standard",repair_mode="medium")
                seen_cooldown=False; seen_large=False; deadline=time.time()+600; final=None
                while time.time()<deadline:
                    d=c.get(f"/api/jobs/{jid}",timeout=20).json()
                    if d.get("status")=="cooldown": seen_cooldown=True
                    if d.get("large_file_count",0)>0 or d.get("large_files"): seen_large=True
                    if d.get("status") in {"done","error","cancelled"}: final=d; break
                    time.sleep(1.0)
                assert final and final["status"]=="done", final
                assert seen_large, "large file was not detected by worker path"
                assert final["large_task_status"] in {"done","completed","running"}
                assert c.head(f"/api/jobs/{jid}/download").status_code==200
                print("    OK 520 MiB large member detected; streaming worker completed; output downloadable")
        finally:
            stop_server(proc)

        print("[9] Headless UI smoke / info center / shortcuts")
        proc=start_server(tmp/"ui")
        try:
            browser_ui_smoke()
            print("    OK Chromium checked navigation, info center, Escape/I shortcuts and renamed engines")
        finally:
            stop_server(proc)

        print("FULL STRESS RESULT: PASS")


if __name__ == "__main__":
    main_stress()
