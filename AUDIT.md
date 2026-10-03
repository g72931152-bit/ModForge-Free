# ModForge v1 (0.61-A) — аудит, переработка и стресс-проверка

## Область аудита

Проверены backend `main.py`, frontend `index.html`, `assets/app.js`, `assets/styles.css`, `assets/halloween.js`, PWA shell, конфигурация и тестовый набор. Отдельно проверены VA 2 Repair Core, VE 1, preflight, AI traffic, restart/re-check, большие файлы, error paths и интерфейс.

## Найденные проблемы и исправления

### 1. Ремонт фактически мог сводиться к пересборке

**Проблема:** успешная упаковка результата не означала, что мод действительно был изменён.

**Исправление:** ремонт теперь измеряется через фактические file-level изменения. Добавлены `health_before_repair`, `repair_effectiveness`, `actual_repairs`, `changed_files` и `modforge_repair_manifest.json`. При отсутствии изменений и сохранённых проблемах результат это явно показывает.

### 2. Недостаточно надёжное восстановление ресурсов

**Проблема:** отсутствие ссылки могло закончиться только предупреждением.

**Исправление:** добавлен каскад восстановления локального ресурса: точное соответствие, нормализация пути/регистра, однозначный кандидат, совместимый fallback и безопасная пересборка поддерживаемых случаев. Повреждённый найденный ресурс сначала проходит repair path.

### 3. Относительные ссылки проверялись не всегда в контексте владельца

**Исправление:** ресурсный анализ привязан к файлу, из которого идёт ссылка, а не только к корню payload.

### 4. AI traffic был только диагностикой

**Проблема:** автомобиль мог быть принят за «проблемный AI», но файл не получал реальной traffic metadata.

**Исправление:** добавлены PC `model` normalization, `info_*` Population/Config Type, vehicle groups, emergency group и explainable manifest.

### 5. Не было управления охватом AI-трафика

**Исправление:** добавлен выбор `all` / `target`: весь мод или выбранная конфигурация.

### 6. Emergency-транспорт не выделялся отдельно

**Исправление:** добавлен приоритетный role detection по названию/признакам и отдельная Police/Service traffic group. Population для emergency выше стандартной.

### 7. Siren behavior нельзя было честно «починить» универсальным Lua-файлом

**Исправление:** движок не генерирует неизвестный контроллер наугад. Он исправляет доступную metadata-часть и явно сообщает о зависимости от BeamNG runtime traffic/navgraph.

### 8. VE 1 и VA 2 могли пересекаться

**Исправление:** разделены engine ids, состояния, entrypoints, workspace lifecycle и отдельная финализация VE 1.

### 9. Preflight отсутствовал как самостоятельный этап

**Исправление:** upload → preparation → prepared → explicit start. Пользователь видит найденные проблемы до запуска движка.

### 10. Большой файл мог перегружать обработку

**Исправление:** отдельный streaming path для файлов от 512 МиБ, resource budget, worker limits и автоматический cooldown без потери задачи.

### 11. Повторный AI repair был неидемпотентным

**Проблема:** vehicle groups и manifest переписывались даже при одинаковом содержимом.

**Исправление:** генераторы теперь сравнивают существующее содержимое перед записью. Повторный repair исправного AI-профиля возвращает пустой набор изменений.

### 12. Preflight-задание не всегда было удобно запускать после подготовки

**Исправление:** добавлен отдельный `/api/jobs/{job_id}/start`, состояние `prepared`, сохранение состояния и запуск без повторной распаковки.

### 13. Ctrl+Enter запускал только upload-path

**Исправление:** Ctrl/Cmd+Enter теперь запускает подготовленную задачу через `beginTaskFromUI()`, а при выбранном файле начинает загрузку.

### 14. Halloween 31 clicks изменял только локальное состояние/окно

**Исправление:** Egg теперь изменяет полноценную CSS-тему интерфейса, сохраняет unlock и не использует блокирующий overlay.

### 15. Видимый релиз мог оставаться старым после обновления

**Исправление:** текущий релиз поднят до **v1 (0.61-A)**, `STATE_EPOCH` и PWA cache epoch подняты до `061a`, старые видимые `0.60-A` маркеры удалены.

## Проверка AI traffic

Добавлены реальные проверки:

- `model` в PC;
- `info_*.json` creation/normalization;
- `Config Type=Service` для ambulance/service;
- emergency Population;
- общая traffic group;
- emergency traffic group;
- target-only traffic scope;
- повторная идемпотентная обработка.

## Стресс-проверка

### Unit/regression

`pytest -q --disable-warnings`

**93 passed**

### Полный stress-run

`python tests/full_stress_v059a.py`

**FULL STRESS RESULT: PASS**

Проверено:

1. Health/engine API.
2. VA 2 standard pipeline.
3. VA 2 aggressive и 15 verification blocks.
4. Процентный parser regression.
5. Restart / re-check.
6. Изолированный VE 1 workflow.
7. Malformed ZIP и path traversal.
8. Persistent VE 1 recovery после backend restart.
9. Реальный ZIP с большим членом **520 MiB**.
10. Streaming worker и скачивание результата.
11. Chromium headless UI smoke.
12. Interface Info Center.
13. Escape/I navigation.
14. Renamed engines.

### Дополнительная проверка

Отдельно подтверждено:

- AI scope `all` — PASS;
- AI scope `target` — PASS;
- AI repair idempotence — PASS;
- Halloween assets / 31-click contract — PASS;
- preflight panel/contract — PASS;
- Python syntax — PASS;
- JavaScript syntax (`app.js`, `halloween.js`) — PASS;
- ZIP archive integrity — PASS;
- старые visible release markers `0.60-A` / `060a` — не найдены.

## Ограничения подтверждения

Локальная среда не содержит установленного Docker daemon, поэтому `docker build` здесь не выполнялся. Dockerfile и зависимости прошли статическую проверку.

BeamNG.drive runtime не запускается внутри этого серверного stress-run, поэтому живое 3D-поведение, navgraph и конкретная реакция AI на сирену требуют отдельной проверки уже в игре.

## Итог

Версия 0.61-A не рассматривает успешную упаковку ZIP как доказательство ремонта. Цепочка теперь построена как:

**upload → preflight → выбор области → реальный repair → повторная диагностика → file-level diff → health after repair → финальная упаковка**

Для VE 1 цепочка отдельная:

**upload → preflight → выбор варианта → VE 1 workspace → изменения → stress → finalize**
