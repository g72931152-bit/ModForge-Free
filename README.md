# ModForge v1

ModForge is a BeamNG.drive mod structure checker and safe repair service.

- Current stable version: **v1**
- Target: **BeamNG.drive 0.39**
- Inputs: ZIP archives and folders containing a BeamNG mod structure.
- Output: ZIP archive preserving the mod's internal structure.
- Default output suffix: `_FIXED` (customizable in the UI).

## v1 features
- Multi-stage scan with detailed stage explanations.
- Safe-path and archive structure checks.
- JSON / PC / JBeam syntax checks.
- Resource and reference checks with case/path repair when a unique matching file exists inside the submitted mod.
- Material checks and conservative glass-material normalization.
- Deep post-repair verification and full final re-check.
- Pause, reset, and current-file listing during a job.
- First-visit changelog, privacy notice and usage instructions.
- Quick scan priorities and output-name customization.
- Responsive UI for phones, desktops and large displays.
- Optional banner and support slots via `site_config.json`.

## Explicit limitations
ModForge v1 does **not** launch BeamNG.drive for a full visual render, cannot guarantee repairs to unknown Lua/physics logic, and does not download or copy third-party or proprietary game assets from the internet.

PNG/JPG files are not supported as standalone products; they are only processed when they are part of a supported BeamNG mod structure.

## Deployment
The repository root contains `Dockerfile`. Deploy it as a Docker web service on Render or another Docker host. `assets/logo.png` and `assets/banner.png` can be replaced without changing application code.
