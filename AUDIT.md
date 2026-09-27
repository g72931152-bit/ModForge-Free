## Version semantics audit

`v1 (0.42)` is the current ModForge site release line. `0.42` is an update inside global engine `v1`. BeamNG.drive target metadata remains `0.39`.

# ModForge v1 (0.42) audit

This pass extends the supplied working project instead of replacing its FastAPI/backend, browser frontend, 15-stage pipeline, repair modes, recovery, feedback, branding, Docker setup or existing smoke test.

## Existing behavior preserved

- ZIP / folder / single-file intake.
- 15-stage scan/repair/recheck/package flow.
- Standard / medium / aggressive repair modes.
- Pause / cancel / restart and persisted job recovery.
- Vehicle branding and existing material/glass repair behavior.
- Feedback + SMTP/admin routes.
- Existing download/report behavior.

## V1 (0.42) additions

- Mod Health with Structure, Syntax, Resources, Materials, Vehicle, Configs and Performance derived from actual scan findings; no arbitrary numeric score is fabricated.
- Severity (`CRITICAL`, `ERROR`, `WARNING`, `INFO`) and confidence (`SAFE`, `PROBABLE`, `HEURISTIC`, `MANUAL_REVIEW`) on normalized issues.
- Repair Preview generated immediately before the repair stage, with safe vs heuristic changes and manual-review counts.
- Before/After diff collection for changed text resources plus hash/size comparison for binary or large resources.
- Central repair-rule registry with detection, fix, severity, confidence and verification metadata.
- Mod Doctor endpoint using the real report evidence for the current job before recommending a conservative action.
- Resource Inspector with a file tree, size/hash, references, referenced-by, missing references, unused candidates, shared dependencies and duplicate groups.
- SHA-256 duplicate detector without automatic deletion.
- Performance scanner for large textures, large geometry, duplicate resources and unused candidates; it does not promise an FPS number.
- Safe cleaner limited to OS/archive junk and obvious temporary/backup names.
- PREPARE FOR RELEASE: repair snapshot → safe cleanup → recheck → Release ZIP.
- History snapshots for original source plus repair/optimized/Mod Lab stages, with rollback endpoints. Original input is never overwritten.
- ZIP-to-ZIP compare with added/removed/changed/conflict data.
- ZIP security hardening: traversal, symlink, encrypted entry, duplicate-path, max-size, depth, file-count and compression-ratio guards.
- Per-client/global active-job limits, duplicate-run guard and a processing timeout watchdog.
- Simple / Advanced UI mode, reduced-motion support and new workbench controls.

## Reliability / compatibility fixes found during this pass

- Fixed `scan_lighting()` using undefined resource-index variables.
- Resource extraction now reuses one case-insensitive index per stage and rejects unsafe archive structures before writing files.
- Audio extensions are included in reference analysis so sound paths participate in dependency checks.
- Obsolete project version labels were removed from active UI/docs.

## Verification performed in this environment

- `python -m py_compile main.py tests/smoke_test.py`
- `node --check assets/app.js`
- Existing vehicle-branding and glass-repair smoke tests pass.
- New regression coverage passes for path traversal, oversized unpacked ZIP limits, archive-bomb guard, symlink ZIP entries, broken JSON, broken JBeam, missing references/textures, SHA duplicate detection, safe cleaner behavior, compare/conflicts and Mod Doctor.
- FastAPI integration checks pass for `/api/health`, `/api/repair-rules` and `/api/compare`; `/api/health` reports `v1 (0.42)`.
- End-to-end synthetic job completed successfully through analyze → repair → verify → package, followed by PREPARE FOR RELEASE and rollback on the synthetic test mod.

## Known limitation

BeamNG.drive itself is not executed by this backend. Runtime-only Lua behavior, complex physics, visual rendering and game-specific interactions still require testing in the game.

## Reliability hotfix (post 0.42)

- Fixed final polling timeouts caused by `/api/jobs/{id}` returning the entire potentially large report payload.
- Job polling now returns only compact progress/status metadata; the full report is fetched separately after `done`.
- Browser API timeout increased for normal control calls, with a longer timeout for the final report fetch.
- Transient backend/network timeouts during polling no longer mark the repair as failed; the client retries with bounded backoff while the backend job continues.
- Added regression coverage proving a large report does not expand the polling response.

## Verification performed after the hotfix

- `python -m py_compile main.py tests/smoke_test.py`
- `node --check assets/app.js`
- `pytest -q` → 7 passed.
- Local FastAPI E2E: analyze → repair → verify → report fetch → download HEAD → download GET all returned successfully.
- Final status response remained compact (1,118 bytes) while the fetched report was 20,945 bytes in the synthetic integration test.
