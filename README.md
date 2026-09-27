# ModForge v1 (0.63) — Global Update

## Version semantics

`v1 (0.63)` is the current ModForge site release in the `v1` line. The supported BeamNG.drive target remains `0.39`.

# ModForge v1 (0.63) — BeamNG.drive mod repair

ModForge is a strict, minimal web service for checking and safely repairing BeamNG.drive 0.39 mods.

## v1 (0.63) Global Update changes
- Added local per-profile "usual settings" memory: after several deliberate runs ModForge can offer one-click reuse of recurring resource/problem/priority/repair/task/processing selections.
- A one-time browser-local data reset runs on upgrade to 0.53 so existing profile/settings state starts clean; server-side jobs are not deleted.

## v1 (0.53) historical usual-settings update

The current site has local browser profiles rather than a server-side account system. Usual settings are scoped to the local profile on that device. Guest and named profiles therefore have separate preference histories. Free-form task descriptions are not reused automatically.


### UI and session
- Stable release remains the `v1` line; this maintenance release is `v1 (0.63)`.
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
- Lighting repair is conservative for BeamNG 0.39: clearly legacy PointLight/SpotLight brightness is migrated to physical intensity, 8-bit light colors are converted to linear RGBA, and malformed spotlight angle ordering is corrected; position/rotation, cookies, flares and animations are never rewritten automatically.
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

`v1 (0.63)`


## v1 (0.63) lighting hardening
- BeamNG 0.39 light repair is conservative: legacy PointLight/SpotLight brightness is migrated to physical intensity only when the light class is explicit; clearly 8-bit colors are converted from sRGB to linear RGBA; malformed spotlight angle ordering is corrected. Position/rotation, glowMap transitions, cookies, flares and animations are never rewritten automatically.

## v1 (0.63) site interface update

- Приоритетный запрос пользователя обрабатывается первым, затем выполняется общий скан распространённых проблем сторонних модов.
- Добавлен отдельный Mod Lab: мягкая/жёсткая подвеска, изменение тяги/оборотов и создание дополнительных PC-конфигураций.
- Добавлен независимый профиль скорости обработки и обмена: Стандарт / Быстрее / Агрессивно быстрее. Профиль сохраняется отдельно от режима ремонта; в интерфейсе отображается текущий расход передачи. Интервал фонового опроса задачи также адаптируется к профилю.
- Полностью обновлена визуальная часть: анимированный фон, яркость баннера по степени видимости, пульсация логотипа во время задачи и цветовой индикатор прогресса в favicon.
- Выбор входа теперь использует векторные иконки ZIP, папки и файла без emoji.
- В окне ожидания добавлены две мини-игры с переключением без закрытия окна: Змейка и Реакция.

## Ограничение сетевого профиля

Профиль скорости не является обещанием фиксированных MB/s: backend получает приоритет обработки и использует его в пределах лимитов бесплатного хостинга. При наличии крупных файлов половина выделенного рабочего бюджета резервируется под их отдельные потоковые блоки; оставшаяся часть идёт на обычную обработку. Более быстрый профиль также может увеличить объём сетевых запросов со стороны браузера.


## v1 (0.63) advanced workbench interface
- Локальный профиль: имя, акцент (оранжевый/синий/мятный), плотность и режим уменьшенных анимаций.
- Профиль показывает локальную статистику запусков, исправлений, последнего источника и выбранного режима.
- Настройки не требуют регистрации и не отправляют персональные настройки на backend.
- Добавлены Material-style ripple/transition-анимации и поддержка `Ctrl/Cmd + Enter` для быстрого запуска.
- Визуальные эффекты намеренно приглушены, чтобы интерфейс оставался строгим и функциональным.

## Визуальная диагностика и история сессий · 0.52 UI

В интерфейсе добавлен единый каталог понятных ошибок. Критические состояния (например, `MF-528` и `MF-509`) получают красно-чёрную карточку с треснувшим логотипом, остальные ошибки используют чёрно-оранжевую тему. Код, причина и следующий шаг отображаются отдельно; важные слова подчёркиваются.

`MF-528` срабатывает, когда публичный `state_epoch` сервера изменился относительно сохранённого значения браузера. Значение можно менять через `MODFORGE_STATE_EPOCH` при осознанном глобальном сбросе/восстановлении состояния.

После первого успешно начатого скачивания результата появляется кнопка с четырьмя квадратами. Она открывает локальную историю сессий с порядковым номером, коротким ID задачи, исходным именем и временем. История не требует отдельной базы аккаунтов и не очищается при обычной потере соединения.

Для уже открывавшегося сайта добавлен service-worker fallback: при потере сети навигация получает отдельную страницу `MF-503`, а локальный shell, логотипы, стили и JavaScript остаются доступными из cache. Дополнительно доступны `Ctrl/Cmd+Shift+U`, `Ctrl/Cmd+Shift+R`, `Ctrl/Cmd+Shift+P`, `Ctrl/Cmd+Shift+S`, `?` и `Esc`.


## v1 (0.63) visual reliability update

- Version line is now `0.63`; the footer no longer repeats the release number.
- Processing stages show a small animated state marker while the stage is active and a checkmark after completion.
- The Files control shows the files belonging to the currently active stage from the same status snapshot as the progress UI.
- Pause/Resume keeps the actual server state in the control instead of resetting the button label.
- Status polling has no frontend hard timeout: a delayed backend response shows a yellow connection warning and the job remains running.
- The warning is also shown inside the active stage's expanded details.
- Added calm pointer/touch-reactive background illumination with reduced-motion support.
- Error screens use the supplied normal/critical ModForge avatars with transparent backgrounds and severity-aware themes.


## v1 (0.63) global lighting/material hardening

- BeamNG.drive 0.39 PBL light props are migrated conservatively: SPOTLIGHT uses `lightIntensityCd`, POINTLIGHT uses `lightIntensityLm`.
- Light orientation/placement fields are preserved; no automatic guessing of `baseRotation`, `baseRotationGlobal`, translation, flare, cookie, or animation.
- Nested JBeam light objects are supported when repairing inner/outer cone ordering.
- Vehicle PBR materials receive deterministic normalization only where the source data is unambiguous. Reflection behavior is restored without inventing environment maps for arbitrary materials.
- Glass fallbacks remain neutral and texture-independent when source maps are missing.
- Release label: `v1 (0.63) Global Update`; BeamNG.drive target: `0.39`.
