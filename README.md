# ModForge v1 (0.41) — BeamNG.drive mod repair

ModForge is a strict, minimal web service for checking and safely repairing BeamNG.drive 0.41 mods.

## v1 (0.41) changes

### UI and session
- Stable release remains the `v1` line; this maintenance release is `v1 (0.41)`.
- A changelog is shown on the first visit after a release change.
- The selected file, repair mode, suffix, wishes and last job reference survive normal browser restarts.
- Download checks the finished artifact with `HEAD` before starting the download.

### Vehicle branding
- Vehicle mods are branded directly in the vehicle data instead of installing a manual BeamNG UI App.
- The visible vehicle name is suffixed with `ModForge`, for example `CTS ModForge` or `Cadillac ModForge` when that is the existing visible name.
- Likely vehicle preview/thumbnail images receive the supplied ModForge logo as a small watermark in the top-right corner.
- `modforge_applied.json` records which vehicle info files and preview files were branded.
- Re-processing an already branded artifact is idempotent: the watermark is not applied twice.


### Material/texture repair
- Standard mode now treats missing glass texture maps as a repairable material failure instead of only changing transparency flags.
- Glass materials are inspected inside `Stages` as well as legacy top-level fields.
- When a glass texture referenced by the mod is absent, ModForge removes only the broken texture maps and replaces them with a self-contained `baseColorFactor` + `opacityFactor` fallback that follows BeamNG's documented translucent glass material structure.
- The result is rechecked so the same missing glass resource is not still reported after repair.
- The service does not copy proprietary BeamNG base-game files into the generated mod.

### Feedback and email
- Feedback is persisted locally in `MODFORGE_FEEDBACK_PATH`.
- Owner notifications use SMTP when configured.
- When a visitor provides an email, the notification sent to the owner now sets that address as `Reply-To`, so replying to the email can answer the visitor directly.
- The author panel has `Проверить почту`, which triggers a test message and exposes the last SMTP error in the admin status endpoint.
- SMTP failures are logged by the backend instead of being silently discarded.
- Optional `MODFORGE_SMTP_SSL=1` support is included for SSL SMTP servers.

## SMTP setup

Set these environment variables on the deployment server. Never put the password in the repository.

```text
MODFORGE_SMTP_HOST=smtp.example.com
MODFORGE_SMTP_PORT=587
MODFORGE_SMTP_USER=your-mailbox@example.com
MODFORGE_SMTP_PASSWORD=your-smtp-password
MODFORGE_SMTP_FROM=your-mailbox@example.com
MODFORGE_SMTP_TLS=1
MODFORGE_SMTP_SSL=0
MODFORGE_SMTP_TIMEOUT=20
MODFORGE_ADMIN_KEY=a-long-random-secret
```

For Gmail/Google Workspace, use the SMTP credentials appropriate for the mailbox (normally an app password when the account requires it), not a normal account password.

Owner mailbox: `ptornsaso0h@gmail.com`.

## Storage and persistence

- Default job storage: `./data/jobs`.
- `MODFORGE_DATA_ROOT` can point at a persistent volume.
- `MODFORGE_WORK_ROOT` and `MODFORGE_FEEDBACK_PATH` can override the job/feedback locations.
- Finished job artifacts are retained for 7 days by default (`MODFORGE_JOB_RETENTION`).
- Interrupted queued/running jobs are restored from their persisted `source` copy after backend restart.

## Limits

- Maximum upload: 2 GiB.
- Maximum unpacked job size: 4 GiB.
- Maximum files: 12,000.

## Important limitation

ModForge does not launch BeamNG.drive itself, so the service cannot prove a live 3D physics result. It validates files and performs conservative/heuristic repairs. Unknown Lua logic, complex physics problems and game-runtime-only issues can still require testing in BeamNG.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --port 8000 --reload
```

## Docker

The supplied Dockerfile installs the required Python packages and exposes `${PORT}` (default `10000`). Mount `/app/data` to a persistent volume in production.

## Version

`v1 (0.41)`


## v1 (0.41) interface update

- Приоритетный запрос пользователя обрабатывается первым, затем выполняется общий скан распространённых проблем сторонних модов.
- Добавлен отдельный Mod Lab: мягкая/жёсткая подвеска, изменение тяги/оборотов и создание дополнительных PC-конфигураций.
- Добавлен независимый сетевой профиль: 2 / 5 / 20 MB/s. Профиль сохраняется отдельно от режима ремонта; в интерфейсе отображается текущий расход передачи. Интервал фонового опроса задачи также адаптируется к профилю.
- Полностью обновлена визуальная часть: анимированный фон, яркость баннера по степени видимости, пульсация логотипа во время задачи и цветовой индикатор прогресса в favicon.
- Выбор входа теперь использует векторные иконки ZIP, папки и файла без emoji.
- В окне ожидания добавлены две мини-игры с переключением без закрытия окна: Змейка и Реакция.

## Ограничение сетевого профиля

2/5/20 MB/s — это клиентский сетевой бюджет/темп фонового взаимодействия. Сам глубокий анализ распакованного мода выполняется локально на backend и не может «съесть» 20 MB/s без реальной сетевой операции. ModForge не скачивает закрытые игровые ассеты BeamNG.
