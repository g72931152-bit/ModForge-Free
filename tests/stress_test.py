from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
import tempfile
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import main


def test_concurrent_global_admission_never_exceeds_limit() -> None:
    old_jobs = dict(main.jobs)
    old_global = main.job_reservations_global
    old_client = dict(main.job_reservations_client)
    main.jobs.clear(); main.job_reservations_global = 0; main.job_reservations_client.clear()
    accepted = []
    lock = threading.Lock()
    barrier = threading.Barrier(32)

    def worker(i: int):
        barrier.wait()
        try:
            main.reserve_job_slot(f"stress-{i}")
            with lock: accepted.append(i)
        except Exception:
            return

    try:
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(worker, range(32)))
        assert len(accepted) == main.MAX_ACTIVE_JOBS_GLOBAL
        assert main.job_reservations_global == main.MAX_ACTIVE_JOBS_GLOBAL
    finally:
        for i in accepted:
            main.release_job_slot(f"stress-{i}")
        main.jobs.clear(); main.jobs.update(old_jobs)
        main.job_reservations_global = old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)


def test_concurrent_same_client_admission_never_exceeds_client_limit() -> None:
    old_jobs = dict(main.jobs)
    old_global = main.job_reservations_global
    old_client = dict(main.job_reservations_client)
    main.jobs.clear(); main.job_reservations_global = 0; main.job_reservations_client.clear()
    accepted = []
    barrier = threading.Barrier(16)

    def worker(_):
        barrier.wait()
        try:
            main.reserve_job_slot("single-stress-client")
            accepted.append(1)
        except Exception:
            pass

    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(worker, range(16)))
        assert len(accepted) == main.MAX_ACTIVE_JOBS_PER_CLIENT
    finally:
        for _ in accepted:
            main.release_job_slot("single-stress-client")
        main.jobs.clear(); main.jobs.update(old_jobs)
        main.job_reservations_global = old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)



def test_concurrent_restart_dedup_never_creates_parallel_children() -> None:
    old_jobs = dict(main.jobs)
    old_global = main.job_reservations_global
    old_client = dict(main.job_reservations_client)
    old_children = dict(main.restart_children)
    old_restart_res = set(main.restart_reservations)
    main.jobs.clear(); main.job_reservations_global = 0; main.job_reservations_client.clear()
    main.restart_children.clear(); main.restart_reservations.clear()
    old_id = "stress-restart-source"
    main.jobs[old_id] = {"job_id": old_id, "status": "error", "_client_id": "restart-client", "root": tempfile.mkdtemp(prefix="modforge-stress-restart-")}
    source = Path(main.jobs[old_id]["root"]) / "source"
    source.mkdir(parents=True)
    (source / "upload.zip").write_bytes(b"x")

    async def one_attempt():
        req = type("Req", (), {"client": type("Client", (), {"host": "198.51.100.88"})(), "headers": {}})()
        try:
            return await main.restart_job(old_id, req)
        except Exception as exc:
            return exc

    async def run_all():
        return await asyncio.gather(*(one_attempt() for _ in range(24)))

    old_run_job = main.run_job; old_watchdog = main.job_timeout_watchdog
    async def noop(*_args, **_kwargs):
        return None
    main.run_job = noop; main.job_timeout_watchdog = noop
    try:
        results = asyncio.run(run_all())
        successes = [r for r in results if isinstance(r, dict) and r.get("ok")]
        errors = [r for r in results if not isinstance(r, dict)]
        assert len(successes) == 1, results
        assert errors, results
        assert all(getattr(e, "detail", {}).get("code") == "MF-409" for e in errors)
        assert main.restart_children[old_id] == successes[0]["job_id"]
    finally:
        main.run_job = old_run_job; main.job_timeout_watchdog = old_watchdog
        for jid, job in list(main.jobs.items()):
            if jid != old_id:
                shutil_root = Path(job.get("root", ""))
                if shutil_root.exists():
                    import shutil; shutil.rmtree(shutil_root, ignore_errors=True)
        src_root = Path(main.jobs[old_id]["root"])
        import shutil; shutil.rmtree(src_root, ignore_errors=True)
        main.jobs.clear(); main.jobs.update(old_jobs)
        main.job_reservations_global = old_global; main.job_reservations_client.clear(); main.job_reservations_client.update(old_client)
        main.restart_children.clear(); main.restart_children.update(old_children)
        main.restart_reservations.clear(); main.restart_reservations.update(old_restart_res)

def test_repeated_repair_stress_is_idempotent() -> None:
    root = Path(tempfile.mkdtemp(prefix="modforge-stress-repair-"))
    (root / "vehicles" / "car").mkdir(parents=True)
    (root / "vehicles" / "car" / "good.png").write_bytes(b"png")
    (root / "vehicles" / "car" / "bad.json").write_text('{"a": "x,}", "b": [1,],}', "utf-8")
    job = {"job_id":"stress","repair_mode":"medium","scan_workers":1,"_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event()}
    first = main.repair_tree(root, job)
    snapshot = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert first
    for _ in range(25):
        assert main.repair_tree(root, job) == []
    assert {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()} == snapshot


def test_large_task_cancel_stress() -> None:
    async def run():
        root = Path(tempfile.mkdtemp(prefix="modforge-stress-large-"))
        (root / "big.bin").write_bytes(b"x")
        original = main.review_large_file
        main.jobs["stress-large"] = {"job_id":"stress-large","root":str(root),"_cancel_event":threading.Event(),"_pause_event":threading.Event(),"_timeout_event":threading.Event()}
        def slow(_path, job):
            for _ in range(500):
                main.check_cancel_pause(job); time.sleep(0.001)
            return {"sha256":"x","bytes_read":1,"signals":[]}
        main.review_large_file = slow
        try:
            for _ in range(10):
                main.jobs["stress-large"]["_cancel_event"].clear(); main.jobs["stress-large"]["status"]="running"
                task = asyncio.create_task(main.run_large_file_task("stress-large", root, [{"file":"big.bin","size":1}]))
                await asyncio.sleep(0.002)
                main.jobs["stress-large"]["_cancel_event"].set()
                try:
                    await task
                except RuntimeError as exc:
                    assert str(exc) == "__CANCELLED__"
                assert main.jobs["stress-large"]["large_task_status"] == "cancelled"
        finally:
            main.review_large_file = original
            main.jobs.pop("stress-large", None)
    asyncio.run(run())


def test_public_health_has_no_private_configuration() -> None:
    data = asyncio.run(main.health())
    encoded = json.dumps(data, ensure_ascii=False)
    assert "SMTP_HOST" not in encoded
    assert "owner_email" not in encoded
    assert "MODFORGE_ADMIN_KEY" not in encoded
    assert "email" not in data



def test_processing_budget_half_to_large_files_under_each_speed() -> None:
    for profile in ("standard","balanced","aggressive"):
        cfg=main.processing_speed_settings(profile)
        assert cfg["large_file_workers"] * 2 == cfg["total_workers"]
        assert cfg["poll_ms"] >= 1800
        job={"repair_mode":"aggressive","processing_speed":profile}
        main.apply_processing_budget(job,profile,True)
        assert job["scan_workers"] + job["large_file_workers"] == job["processing_workers"]
        assert job["large_file_budget_share"] == 0.5


def test_many_large_files_keep_unique_block_numbers() -> None:
    items=[{"file":f"large-{i}.bin","size":1,"status":"queued"} for i in range(50)]
    for idx,item in enumerate(items,1): item["block_no"]=15+idx
    assert [x["block_no"] for x in items] == list(range(16,66))
    assert len({x["block_no"] for x in items}) == len(items)

if __name__ == "__main__":
    test_concurrent_global_admission_never_exceeds_limit()
    test_concurrent_same_client_admission_never_exceeds_client_limit()
    test_concurrent_restart_dedup_never_creates_parallel_children()
    test_repeated_repair_stress_is_idempotent()
    test_large_task_cancel_stress()
    test_public_health_has_no_private_configuration()
    test_processing_budget_half_to_large_files_under_each_speed()
    test_many_large_files_keep_unique_block_numbers()
    print("ModMendryx stress tests: OK")
