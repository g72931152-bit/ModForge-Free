# ModMendryx v1 (0.62-A) — аудит, исправления и стресс-проверка

## Итог

Текущая версия: **v1 (0.62-A)**

Движки:

- **VA 2 · Verification Architecture 2 · 0IN-1.0**
- **VE 1 · Variant Engineering 1 · M0-D-l00**

Целевой профиль: **BeamNG.drive 0.39**.

Главный критерий аудита: успешная упаковка ZIP не считается ремонтом. Ремонтом считается подтверждённое file-level изменение + повторная проверка результата.

## Критические исправления

### 1. Большой ZIP мог завершаться после этапа крупного файла

Причины были связаны с сочетанием тяжёлой потоковой обработки, давления на временное хранилище и восстановления только по исходному архиву.

Исправления:

- streaming worker для файлов от 512 МиБ;
- последовательный чтение больших файлов вместо конкурирующего полного scan;
- контроль нагрузки и async cooldown;
- checkpoint по мере чтения крупного файла;
- раннее освобождение `source/upload.zip` после успешной распаковки;
- storage plan до тяжёлой обработки;
- продолжение из сохранённой `payload` при restart;
- recovery path больше не требует наличия удалённого source archive;
- восстановленный job запускается ровно один раз.

Результат: реальный HTTP E2E для ZIP с элементом **506 MiB** дошёл до `done`, artefact HEAD вернул `200`.

### 2. Восстановление после restart могло запускать одну задачу дважды

В старой логике восстановления был риск повторного `run_job()`.

Исправлено: восстановление создаёт ровно одну async task на job.

### 3. Preflight использовал некорректный параметр размера

Был обнаружен реальный `MF-503` из-за обращения к переменной, которая не существовала в preflight-контексте.

Исправлено: оценка пикового хранилища строится из сохранённых параметров job.

### 4. VE 1 мог неявно зависеть от pipeline VA 2

Исправлено:

- отдельные engine ids;
- отдельные entrypoints;
- отдельное состояние;
- отдельный workspace lifecycle;
- отдельная финализация;
- прямой запуск VE 1 не запускает VA 2.

### 5. Ресурс мог закончиться сообщением «не найден» без попытки восстановления

Исправлен алгоритм поиска:

`точное совпадение → path normalization → case normalization → локальный кандидат → совместимое расширение/ресурс → безопасная реконструкция → fallback`.

Relative path вычисляется от файла-владельца ссылки.

### 6. Повреждённый найденный ресурс считался пригодным

Добавлена проверка содержимого поддерживаемого ресурса и repair path до его окончательного использования, когда такой repair безопасен.

### 7. AI-трафик был в основном диагностикой

Добавлены реальные изменения:

- PC `model` normalization;
- `info_*.json` creation/normalization;
- `Population`;
- `Config Type`;
- vehicle groups;
- emergency/service groups;
- explainable AI traffic manifest.

### 8. Не было ограничения области AI repair

Добавлен scope:

- `all`;
- `target`.

### 9. Emergency vehicles не выделялись достаточно явно

Добавлено распознавание по названию/признакам и отдельная service/police logic.

### 10. AI repair мог переписывать уже исправный профиль

Генераторы vehicle groups и manifest теперь сравнивают существующие данные перед записью.

Повторный одинаковый repair должен быть без лишних file-level изменений.

## Ошибки результата

Кнопка download теперь делает HEAD-проверку артефакта перед скачиванием.

При недоступном artefact:

- кнопка отключается;
- текст заменяется на `✕`;
- ставится `aria-label`/`title`;
- кнопка не возвращается к обычному download-состоянию автоматически.

## Error severity

Критический avatar теперь используется только для:

- `MF-500`;
- `MF-528`.

`MF-509` и `MF-520` относятся к обычным ошибкам.

## UI audit

Проверены:

- пробелы после двоеточия в пользовательских русскоязычных строках;
- тексты кнопок;
- aria labels;
- заголовки;
- видимость второстепенного текста;
- контраст логотипа;
- состояния unavailable/error;
- PRE-FLIGHT;
- Interface Info;
- quick shortcuts;
- Halloween state.

Добавлено отдельное визуальное основание вокруг логотипа в Halloween Egg, чтобы прозрачный логотип не терялся на фоне.

## Halloween

Проверено:

- сезонная тема;
- сохранение unlock;
- 31-click threshold;
- запуск flying pumpkin только в рабочих фазах;
- случайные края экрана;
- click-to-catch;
- автоматическое удаление;
- отсутствие кнопки закрытия у самой тыквы;
- очистка pumpkin при выходе из processing/preparing;
- совместимость с обычным интерфейсом.

## Preflight

Preflight теперь показывает до запуска:

- структуру;
- количество файлов;
- размер рабочей копии;
- найденные проблемы;
- AI traffic readiness;
- storage strategy для крупных файлов;
- следующий рекомендуемый шаг.

Однозначный единичный вариант выбирается автоматически, поэтому задача не ждёт selection timeout без причины.

## SEO audit

Добавлены:

- title;
- meta description;
- robots meta;
- canonical;
- Open Graph;
- Twitter metadata;
- JSON-LD WebApplication;
- `robots.txt`;
- `sitemap.xml`.

## Hosting audit

### Cloudflare Pages

Frontend подготовлен для Pages через `wrangler.toml` с `pages_build_output_dir = "./site"`.

### Render

FastAPI backend остаётся на Render.

Это важно для крупных загрузок: Cloudflare Workers Free ограничивает входящий request body 100 MB, поэтому 506 MiB мод нельзя обслуживать как прямой Workers upload/repair request. citeturn222467search5

Render Free подходит для тестов/хобби, но имеет sleep после 15 минут без входящего трафика и эфемерную локальную файловую систему. Это подтверждает необходимость уже добавленных recovery/storage-механизмов и указывает на следующий шаг — внешнее object storage для долговременных данных. citeturn222467search0turn222467search6

### R2 / durable storage

Object storage можно добавить следующим этапом, чтобы worker не зависел от эфемерного локального диска backend.

## Репозиторий

Верхний уровень релизной сборки содержит ровно три папки:

```text
app/
site/
tests/
```

Временные каталоги тестов и Python caches в релиз не включаются.

## Тестирование

После последних изменений выполнены следующие категории проверки:

- Python syntax;
- JavaScript syntax;
- API health/bootstrap;
- VA 2 Standard;
- VA 2 Medium;
- VA 2 Aggressive / 15 blocks;
- percentage parser;
- repair rules;
- relative resource resolution;
- missing-resource recovery;
- damaged-resource repair path;
- AI traffic scope `all`;
- AI traffic scope `target`;
- emergency traffic metadata;
- AI repair idempotence;
- VE 1 isolation;
- VE 1 restart/recovery;
- malformed ZIP;
- path traversal;
- archive safety limits;
- load cooldown;
- restart/re-check;
- large-file streaming;
- result download/HEAD;
- unavailable artifact button state;
- Interface Info;
- keyboard shortcuts;
- Halloween contract;
- Chromium UI smoke.

### Последний полный regression

`pytest -q tests`

**95 passed**

### Полный stress-run

`PYTHONPATH=app python tests/full_stress_v059a.py`

**FULL STRESS RESULT: PASS**

### Реальный HTTP E2E: 506 MiB

`python tests/real_http_506mb.py`

Результат:

- upload HTTP: `200`;
- обработка дошла до `done`;
- без session-ended error;
- report: `200`;
- artifact HEAD: `200`.

### Syntax

`python -m py_compile app/main.py` — OK

`node --check site/assets/app.js` — OK

`node --check site/assets/halloween.js` — OK

### Docker

Dockerfile статически проверен.

Настоящий `docker build` не выполнялся, потому что Docker daemon отсутствует в рабочей среде.

## Ограничения, которые нельзя выдавать за исправленные без runtime

- полное выполнение пользовательского Lua;
- точное физическое поведение конкретной машины внутри BeamNG.drive;
- реальная остановка AI на каждой реализации сирены;
- navgraph/runtime-specific traffic behavior;
- GPU/рендер-зависимые артефакты;
- закрытые игровые ассеты.

В этих случаях отчёт должен показывать ограничение, а не маскировать его под успешный repair.
