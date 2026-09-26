# ModForge v1 audit

This release was rebuilt from the supplied `ModForge-v1-0_31-beta.zip` source.

## Critical issues found and corrected

### 1. Restart recovery was wired but not actually restoring in-progress jobs
`restore_persisted_jobs()` only loaded terminal jobs, while the startup handler contained logic for queued/running jobs. A backend restart could therefore leave an active job on disk but invisible to the new process.

**Fix:** queued/running/processing/paused/rebuilding states are restored and resumed from the persisted `source` copy.

### 2. The vehicle status implementation used a manual UI App path
The previous build injected a custom UI App and told the user to add it through BeamNG UI Apps. That did not match the requested "vehicle icon" workflow and introduced unnecessary dependency on a HUD layout.

**Fix:** vehicle mods are now branded in the vehicle data itself: the visible vehicle name/brand is marked with `ModForge`, and likely preview/thumbnail images receive the ModForge logo. No manual UI App step is required.

### 3. Feedback emails could silently disappear
Email errors were swallowed by `_safe_email()` and the owner notification contained the visitor email only as text.

**Fix:** SMTP failures are stored/logged, an author-only email test endpoint/button was added, and visitor email is now set as `Reply-To` on the owner notification.

### 4. Release UI showed stale/incorrect stage information
The backend has 12 stages, while the sidebar/changelog still said 11 in places.

**Fix:** all visible stage counts now use 12.

### 5. Privacy wording was inconsistent with 7-day retention
The old first-visit text described the working copy as purely temporary even though the backend intentionally retains job artifacts for up to 7 days.

**Fix:** the text now explains the 7-day default retention and separate feedback storage.

## Verification performed

- Python syntax check: `python -m py_compile main.py`
- JavaScript syntax check: `node --check assets/app.js`
- Vehicle branding smoke test with a synthetic BeamNG vehicle directory.
- Idempotence test: a second branding pass does not add a second watermark.
- Feedback SMTP smoke test: verifies `Reply-To` points to the visitor and admin email diagnostics respond.

## Limitation

The supplied project can be statically verified here, but BeamNG.drive itself is not available in this environment, so the final artifact still needs a real in-game 0.39 smoke test with a vehicle mod.
