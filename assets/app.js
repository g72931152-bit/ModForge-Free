(() => {
'use strict';

/* ══════════════════════════════════════════════════
   CONSTANTS & KEYS
══════════════════════════════════════════════════ */
const SK = {
  SUFFIX: 'mf_suffix',
  SESSION: 'mf_session',
  RELEASE: 'mf_seen_release',
  PRIVACY: 'mf_privacy',
  GUIDE: 'mf_guide',
  SNAKE_HI: 'mf_snake_hi',
  DRAFT: 'mf_draft',
  LAST_JOB: 'mf_last_job',
  ADMIN_KEY: 'mf_admin_key',
  PROFILE: 'mf_profile',
  METRICS: 'mf_metrics',
  HISTORY: 'mf_session_history',
  STATE_EPOCH: 'mf_state_epoch',
  USUAL_PREFERENCES: 'mf_usual_preferences_v1',
  DATA_RESET_RELEASE: 'mf_data_reset_release',
};
const LOCAL_DATA_RESET_RELEASE = '0.61-A';
const SESSION_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days
const API_TIMEOUT_MS = 60000;
const RESULT_TIMEOUT_MS = 120000;
const USUAL_MIN_RUNS = 3;
const USUAL_SAMPLE_LIMIT = 24;

// One-time clean slate for local account/profile/settings data on the 0.61-A release.
// Server-side jobs are untouched; only ModForge's local browser state is reset.
(function resetLocalStateFor053() {
  try {
    if (localStorage.getItem(SK.DATA_RESET_RELEASE) === LOCAL_DATA_RESET_RELEASE) return;
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('mf_') && key !== SK.DATA_RESET_RELEASE) keys.push(key);
    }
    keys.forEach(key => localStorage.removeItem(key));
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const key = sessionStorage.key(i);
      if (key && key.startsWith('mf_')) sessionStorage.removeItem(key);
    }
    localStorage.setItem(SK.DATA_RESET_RELEASE, LOCAL_DATA_RESET_RELEASE);
  } catch {}
})();

/* ══════════════════════════════════════════════════
   DOM HELPERS
══════════════════════════════════════════════════ */
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes = n => { n = Number(n) || 0; const u = ['B','KB','MB','GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${u[i]}`; };
const etaStr = s => { s = Number(s); if (!Number.isFinite(s) || s <= 0) return 'Осталось: —'; if (s < 60) return `Осталось: ~${Math.max(1, Math.round(s))} сек.`; return `Осталось: ~${Math.ceil(s / 60)} мин.`; };
const timeAgo = ts => { const d = Math.round((Date.now() - ts) / 60000); if (d < 1) return 'только что'; if (d < 60) return `${d} мин. назад`; return `${Math.floor(d / 60)} ч. назад`; };


/* ══════════════════════════════════════════════════
   VISUAL ERROR CATALOG
   Every public failure gets a useful explanation,
   a severity and a concrete next action.
══════════════════════════════════════════════════ */
const ERROR_CATALOG = {
  'MF-528': { level:'critical', title:'Восстановление данных', headline:'Данные и прошлые сессии были сброшены', reason:'Произошёл неудачный релиз или восстановление состояния сервера. Система обнаружила, что сохранённая версия данных больше не совпадает с текущей.', actions:['Не начинайте повторную загрузку сразу — сначала дайте сервису закончить восстановление.','История локальных сессий сохранена на устройстве и остаётся доступной.','Если резервная копия найдена сервером, восстановление будет привязано к исходной сессии.'], icon:'/assets/error-avatar-critical.png', retry:false },
  'MF-503': { level:'offline', title:'Сайт не отвечает', headline:'Не удалось связаться с ModForge', reason:'Сайт открылся, но backend сейчас недоступен. Это может быть временный перезапуск сервера, сон Render или проблема с сетью.', actions:['Проверьте интернет-соединение.','Нажмите «Повторить», когда сервис вернётся.','Ваша локальная история и черновик не удаляются.'], icon:'/assets/error-avatar.png', retry:true },
  'MF-TIMEOUT': { level:'offline', title:'Ответ слишком долго не приходит', headline:'Соединение с backend прервалось по времени', reason:'Сервер не успел ответить в допустимый срок. Текущая задача не считается автоматически сломанной только из-за таймаута.', actions:['Подождите несколько секунд и повторите подключение.','Не закрывайте вкладку, если задача всё ещё выполняется.','Для больших файлов можно повторить скачивание позже.'], icon:'/assets/error-avatar.png', retry:true },
  'MF-409': { level:'error', title:'Конфликт операции', headline:'Действие сейчас заблокировано', reason:'Две операции пытаются изменить одну и ту же сессию одновременно или состояние задачи ещё не готово для этого действия.', actions:['Дождитесь окончания текущей операции.','Не нажимайте повторно много раз.','После завершения можно повторить действие один раз.'], icon:'/assets/error-avatar.png', retry:false },
  'MF-509': { level:'critical', title:'Сессия потеряна', headline:'Текущая задача была сброшена во время обработки', reason:'Во время задания backend потерял рабочее состояние. Причиной может быть аварийный перезапуск, крупный файл, нехватка диска или конфликт восстановления.', actions:['Не создавайте копии задачи параллельно.','Проверьте историю сессий — её запись остаётся локально.','Повторите задачу после восстановления сервиса; исходник повторно не считается повреждённым без проверки.'], icon:'/assets/error-avatar-critical.png', retry:true },
  'MF-413': { level:'error', title:'Слишком большой файл', headline:'Файл не прошёл лимит размера', reason:'Текущий вход превышает разрешённый объём. Большой файл не должен приводить к зависшему worker или потере уже сохранённой сессии.', actions:['Проверьте размер архива.','Разделите набор ресурсов на несколько задач.','Если проблема повторяется на допустимом размере, отправьте ID задачи в обратную связь.'], icon:'/assets/error-avatar.png', retry:false },
  'MF-415': { level:'error', title:'Неподдерживаемый формат', headline:'Этот вход нельзя обработать', reason:'Файл или набор файлов не соответствует поддерживаемым BeamNG-ресурсам.', actions:['Выберите ZIP, папку мода или отдельный поддерживаемый ресурс.','Проверьте расширение файла.'], icon:'/assets/error-avatar.png', retry:false },
  'MF-422': { level:'error', title:'Неверные данные', headline:'Запрос заполнен некорректно', reason:'Один из параметров задачи или путь файла не соответствует ожидаемому формату.', actions:['Проверьте выбранные файлы и введённый текст.','Повторите запрос после исправления.'], icon:'/assets/error-avatar.png', retry:false },
  'MF-429': { level:'error', title:'Лимит задач', headline:'Нужно немного подождать', reason:'Достигнут лимит параллельных задач или сработала защита от слишком частых запросов.', actions:['Дождитесь завершения активных задач.','Не отправляйте один и тот же запрос многократно.','Для администратора действует отдельное ограничение запросов.'], icon:'/assets/error-avatar.png', retry:true },
  'MF-403': { level:'error', title:'Доступ запрещён', headline:'У вас нет прав для этого действия', reason:'Endpoint требует авторизацию или ключ режима автора.', actions:['Войдите снова, если сессия авторизации истекла.','Для обычного пользователя вернитесь к публичной функции.'], icon:'/assets/error-avatar.png', retry:false },
  'MF-CANCELLED': { level:'error', title:'Задача остановлена', headline:'Обработка была отменена', reason:'Задача завершена состоянием cancellation и не считается успешной.', actions:['Запустите задачу заново.','Исходная загрузка сохраняется до окончания срока хранения.'], icon:'/assets/error-avatar.png', retry:true },
  'MF-404': { level:'error', title:'Ресурс не найден', headline:'Запрошенная сессия или файл больше недоступны', reason:'Сервер не нашёл конкретный URL, задачу или готовый артефакт.', actions:['Проверьте историю сессий.','Если задача исчезла сразу после обновления сервиса, откроется режим восстановления 528.'], icon:'/assets/error-avatar.png', retry:false },
  'MF-500': { level:'critical', title:'Внутренняя ошибка', headline:'Сервер столкнулся с непредвиденной ошибкой', reason:'Операция остановлена с явной ошибкой и не считается успешно завершённой.', actions:['Повторите операцию один раз.','Если ошибка повторяется — отправьте код и ID задачи в поддержку.'], icon:'/assets/error-avatar-critical.png', retry:true },
};

function normalizeErrorCode(raw) {
  const m = String(raw || '').match(/MF-[A-Z0-9-]+/i);
  if (m) return m[0].toUpperCase();
  if (/Failed to fetch|NetworkError|Load failed/i.test(String(raw))) return 'MF-503';
  return 'MF-500';
}

function errorSpec(raw) { return ERROR_CATALOG[normalizeErrorCode(raw)] || ERROR_CATALOG['MF-500']; }
function errorCardHtml(code, rawMessage) {
  const spec = ERROR_CATALOG[code] || ERROR_CATALOG['MF-500'];
  const reason = String(rawMessage || '').replace(`${code}:`, '').trim();
  const actions = spec.actions.map(x => `<li>${esc(x)}</li>`).join('');
  const critical = spec.level === 'critical' ? ' critical' : '';
  const img = spec.icon || '/assets/logo.png';
  const markImportant = value => esc(value).replace(/(данные|сессия|файл|backend|соединение|лимит|ошибка|доступ|сервер|задача)/gi, '<span class="error-emphasis">$1</span>');
  return `<section class="diagnostic-error ${spec.level}${critical}">\n    <div class="diagnostic-mark"><img src="${img}" alt=""><span>${esc(code)}</span></div>\n    <div class="diagnostic-copy"><span class="eyebrow">${markImportant(spec.title)}</span><h3>${markImportant(spec.headline)}</h3><p>${markImportant(reason || spec.reason)}</p><div class="diagnostic-reason"><b>Почему:</b><span>${markImportant(spec.reason)}</span></div><div class="diagnostic-actions"><b>Что делать:</b><ul>${actions}</ul></div></div>\n  </section>`;
}

/* ══════════════════════════════════════════════════
   ELEMENT REFS
══════════════════════════════════════════════════ */
const els = {};
[
  'brandName','brandSub','versionBadge','interfaceInfoTop','paletteTop','adSlot','brand','feedbackTop','feedbackFooter','resultFeedbackBtn','profileTop','profileAvatar','profileName','profileState','heroProfileBtn','greetingLine','profileSummary','profileCard','profileStateDot','profileAvatarLarge','profileCardName','profileCardMeta','profileEditBtn','metricRuns','metricFixed','metricMode','profileLast',
  'zipBtn','folderBtn','fileBtn','zipInput','folderInput','fileInput',
  'dropzone','dropTitle','dropSub','selection',
  'priorityChips','wishes','outputType','repairMode','modeInfo','vehicleDetect','vehicleDetectTitle','vehicleDetectMeta','resultMode','applyStatus',
  'taskMode','repairConfig','wishesBox','modLab','modRequest','modShortcuts','requestPreview',
  'settingsBtn','settingsTop','suffixPreview','uiModeBtn','advancedTools','doctorQuery','doctorBtn','compareA','compareB','compareBtn','inspectorBtn','releaseBtn','healthBtn','previewBtn','diffBtn','clearBtn','issueFilters','filterCountAll','filterCountFixed','filterCountWarn','filterCountInfo','fixedSummary','fixedSummaryList',
  'startBtn','startLabel','startSpinner','readyState',
  'process','processTitle','processDetail',
  'overallPct','stageCount','progressBar','progressState','eta','connectionWarning','preparationPanel','preparationTitle','preparationMeta','preparationState','preparationSummary','preparationSummarySub','preparationAi','preparationAiSub','preparationNext','preparationFindings','preparationDetailsBtn','preparationCancelBtn','preparationStartBtn',
  'pauseBtn','filesBtn','resetJobBtn','stageGrid',
  'result','resultTitle','resultLead','resultMark',
  'statFiles','statFixed','statWarnings','statChecks',
  'issueList','downloadBtn','reportBtn','copyJobBtn','restartJobBtn','newJobBtn','resultFileNote',
  'modal','modalContent','modalActions','modalClose',
  'gameOverlay','snakeCanvas','snakeScore','snakeHi','gameStatus',
  'gameMinimize','gameClose',
  'sessionBanner','sessionDesc','sessionResume','sessionDismiss','historyTop','historyDrawer','historyList','historyClearBtn','quickHelp','quickHelpClose',
  'toastContainer','snakePromoBtn','interfaceInfo','interfaceInfoClose','interfaceInfoNav','interfaceInfoContent','processDetailsBtn','networkPresets','networkLimitLabel','networkUsageLabel','heroBannerMedia','brandTaskDot','reactionTarget','reactionTimer','gameTitle','gameControlsHint'
].forEach(id => els[id] = $(id));

const ASSET_TYPES = [
  ['vehicle','Машина'], ['map','Карта / уровень'], ['prop','Предмет / проп'],
  ['texture','Текстуры / материалы'], ['sound','Звуки'], ['other','Другое']
];
const ASSET_SUBTYPES = {
  vehicle:[['microbus','Микроавтобус'],['bus','Автобус'],['sedan','Седан'],['hatchback','Хэтчбек'],['wagon','Универсал'],['coupe','Купе'],['suv','SUV / кроссовер'],['pickup','Пикап'],['truck','Грузовик'],['trailer','Прицеп'],['motorcycle','Мотоцикл'],['aircraft','Самолёт'],['helicopter','Вертолёт'],['boat','Лодка / катер'],['other','Другое']],
  map:[['city','Город / улицы'],['track','Трасса / автодром'],['offroad','Бездорожье'],['environment','Окружение'],['scenario','Сценарий / уровень'],['terrain','Террейн'],['other','Другое']],
  prop:[['furniture','Мебель / интерьер'],['traffic','Транспортный объект'],['building','Здание / конструкция'],['decoration','Декорация'],['physics','Физический объект'],['other','Другое']],
  texture:[['vehicle','Автомобиль'],['environment','Окружение'],['ui','UI'],['material','Material / PBR'],['decal','Декали'],['other','Другое']],
  sound:[['engine','Двигатель'],['environment','Окружение'],['ui','UI'],['effects','Эффекты'],['other','Другое']],
  other:[['unknown','Определить автоматически'],['other','Другое']],
};
const REPAIR_ACTIONS = [
  ['resources','Ссылки на ресурсы'],['syntax','Синтаксис JSON / конфигураций'],['glass','Стекло и повреждения стекла'],['mirrors','Зеркала заднего вида'],['pbr','PBR и материалы'],['lighting','Свет, фонари и glow'],['vehicle','JBeam, колёса и физика'],['compat_039','Совместимость с BeamNG 0.39'],['ai_traffic','Адаптация под AI-трафик'],['safe_cleanup','Безопасная очистка служебного мусора']
];
const REPAIR_EXCLUSIONS = [
  ['glass','Не трогать стекло'],['mirrors','Не трогать зеркала'],['lighting','Не трогать свет'],['pbr','Не трогать PBR / материалы'],['textures','Не менять текстурные ссылки'],['wheels','Не менять колёса'],['physics','Не менять физику / JBeam'],['resources','Не менять ссылки на ресурсы'],['syntax','Не исправлять синтаксис'],['compat_039','Не выполнять перенос под BeamNG 0.39'],['ai_traffic','Не адаптировать AI-трафик']
];
const UI_PERFORMANCE = {
  optimization:{label:'Оптимизация',desc:'Максимально экономный интерфейс. Обработка файлов не изменяется.'},
  default:{label:'По умолчанию',desc:'Исходный баланс ModForge.'},
  standard:{label:'Стандарт',desc:'Чуть более плавные переходы при умеренной нагрузке.'},
  high:{label:'Высокая',desc:'Расширенная плавность и больше живых микро-анимаций.'},
  ultra:{label:'Ультра',desc:'Максимально плавный интерфейс и декоративные эффекты.'}
};
const PROBLEM_HINTS = [
  ['mirror_reflection','В зеркалах не отражается машина'],
  ['glass_transparency','Проблема со стеклом / прозрачностью'],
  ['no_texture','На стекле/детали появляется NO TEXTURE'],
  ['missing_texture','Не хватает текстуры'],
  ['not_visible','Деталь или машина не видна'],
  ['wheels','Проблема с колёсами'], ['lights','Проблема со светом / фонарями'],
  ['sound','Проблема со звуком'], ['physics','Проблема с физикой / JBeam'],
  ['spawn','Мод/машина не появляется в игре'], ['ai_traffic','Машина не появляется в AI-трафике / не спавнится среди traffic'], ['siren_traffic','AI-трафик не уступает дорогу машине со спецсигналом'], ['crash','Игра/сцена вылетает после загрузки мода'],
  ['freeze','После мода игра зависает или сильно тормозит'], ['fps','Резко упал FPS / появились просадки'],
  ['black_texture','Чёрные текстуры / чёрные материалы'], ['white_texture','Белые текстуры / белая деталь'],
  ['reflection','Пропали отражения / зеркало выглядит неправильно'], ['shadow','Неправильные или пропавшие тени'],
  ['lod','Проблема с LOD / деталь исчезает на расстоянии'], ['mesh','Меш/геометрия отображается неправильно'],
  ['suspension','Подвеска работает неправильно'], ['steering','Руль/управление работает неправильно'],
  ['brakes','Проблема с тормозами'], ['damage','Повреждения/деформация работают неправильно'],
  ['config_missing','Конфигурация не появляется в меню выбора'], ['camera','Проблема с камерой / обзором'],
  ['exhaust','Проблема с выхлопом / паром'], ['ui','Проблема с UI/отображением игры'],
  ['lighting_direction','Свет бьёт не туда / источник развёрнут'], ['launch_wheelspin','Машина слишком резко стартует / буксует на старте'], ['other','Другое — хочу описать сам']
];

/* ══════════════════════════════════════════════════
   APP STATE
══════════════════════════════════════════════════ */
const state = {
  files: [], kind: '', sourceName: '',
  jobId: null, pollTimer: null, pollInFlight: false, lastStatusJob: null,
  priority: new Set(),
  suffix: localStorage.getItem(SK.SUFFIX) || 'FIXED',
  repairMode: localStorage.getItem('mf_repair_mode') || 'standard',
  taskMode: localStorage.getItem('mf_task_mode') || 'repair',
  processingSpeed: localStorage.getItem('mf_processing_speed') || localStorage.getItem('mf_network_profile') || 'standard',
  processingWorkers: 2,
  largeFileWorkers: 1,
  profile: { id: '', name: 'Гость', accent: 'orange', customColor: '#f47b20', density: 'comfortable', reducedMotion: false, uiPerformance: 'default' },
  usualSettings: null,
  metrics: { runs: 0, fixed: 0, lastMode: 'standard', lastTaskMode: 'repair', lastSource: '' },
  pollFailures: 0,
  release: 'v1 (0.61-A)',
  stages: [],
  checkBlocks: { count: 7 },
  largeFiles: [],
  processingIntensity: 'обычная',
  busy: false,
  uploadXhr: null,
  lastRun: null,
  downloadUrl: null,
  downloadName: null,
  previewShownJob: null,
  catalog: null,
  catalogShownJob: null,
  ve1WorkspaceShownJob: null,
  selectedVariant: null,
  lastEtaSeconds: null,
  assetType: '',
  assetSubtype: '',
  repairActions: new Set(REPAIR_ACTIONS.map(x => x[0])),
  repairExclusions: new Set(),
  aiTrafficScope: 'all',
  excludedFiles: [],
  problemHints: new Set(),
  problemOther: '',
  largeStageVisible: false,
  errorCode: '',
  serverEpoch: '',
  connectionStall: false,
  connectionStageIndex: 0,
  paused: false,
  connectionStallTimer: null,
  pausePending: false,
  filesPending: false,
  history: [],
  resetDetected: false,
};

/* ══════════════════════════════════════════════════
   LOCAL PROFILE & PERSONALIZATION
══════════════════════════════════════════════════ */
function makeProfileId() {
  try { return crypto.randomUUID(); } catch {}
  return `profile-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
function loadProfile() {
  try {
    const p = JSON.parse(localStorage.getItem(SK.PROFILE) || 'null');
    if (p && typeof p === 'object') {
      state.profile = {
        id: typeof p.id === 'string' && p.id.trim() ? p.id.trim().slice(0, 80) : makeProfileId(),
        name: typeof p.name === 'string' && p.name.trim() ? p.name.trim().slice(0, 32) : 'Гость',
        accent: ['orange','blue','mint','lime','custom'].includes(p.accent) ? p.accent : 'orange',
        customColor: /^#[0-9a-fA-F]{6}$/.test(String(p.customColor || '')) ? String(p.customColor) : '#f47b20',
        density: ['comfortable','compact'].includes(p.density) ? p.density : 'comfortable',
        reducedMotion: !!p.reducedMotion,
        uiPerformance: Object.keys(UI_PERFORMANCE).includes(p.uiPerformance) ? p.uiPerformance : 'default',
      };
    } else {
      state.profile.id = makeProfileId();
      saveProfile();
    }
  } catch {
    if (!state.profile.id) state.profile.id = makeProfileId();
  }
  try {
    const m = JSON.parse(localStorage.getItem(SK.METRICS) || 'null');
    if (m && typeof m === 'object') state.metrics = { ...state.metrics, ...m };
  } catch {}
}
function saveProfile() { try { localStorage.setItem(SK.PROFILE, JSON.stringify(state.profile)); } catch {} }
function saveMetrics() { try { localStorage.setItem(SK.METRICS, JSON.stringify(state.metrics)); } catch {} }

function readUsualStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(SK.USUAL_PREFERENCES) || '{}');
    return raw && typeof raw === 'object' ? raw : {};
  } catch { return {}; }
}
function writeUsualStore(store) {
  try { localStorage.setItem(SK.USUAL_PREFERENCES, JSON.stringify(store)); } catch {}
}
function usualSettingsSnapshot() {
  return {
    assetType: state.assetType || '',
    assetSubtype: state.assetSubtype || '',
    repairActions: [...state.repairActions].sort(),
    repairExclusions: [...state.repairExclusions].sort(),
    excludedFiles: [...state.excludedFiles].sort(),
    problemHints: [...state.problemHints].sort(),
    priority: [...state.priority].sort(),
    repairMode: state.repairMode || 'standard',
    taskMode: state.taskMode || 'repair',
    processingSpeed: state.processingSpeed || 'standard',
    suffix: state.suffix || 'FIXED',
    outputType: els.outputType?.value || 'zip',
  };
}
function canonicalValue(value) {
  return JSON.stringify(value ?? null);
}
function modeFromSamples(samples, key) {
  const counts = new Map();
  samples.forEach(sample => {
    const value = sample?.[key];
    if (value == null) return;
    const signature = canonicalValue(value);
    counts.set(signature, (counts.get(signature) || 0) + 1);
  });
  let winner = null;
  let best = 0;
  counts.forEach((count, signature) => { if (count > best) { best = count; winner = signature; } });
  return winner ? { value: JSON.parse(winner), count: best, confidence: samples.length ? best / samples.length : 0 } : null;
}
function loadUsualSettings() {
  const store = readUsualStore();
  const entry = store[state.profile.id];
  const samples = Array.isArray(entry?.samples) ? entry.samples.slice(-USUAL_SAMPLE_LIMIT) : [];
  if (samples.length < USUAL_MIN_RUNS) { state.usualSettings = null; return null; }
  const fields = ['assetType','assetSubtype','repairActions','repairExclusions','excludedFiles','problemHints','priority','repairMode','taskMode','processingSpeed','suffix','outputType'];
  const values = {};
  let aggregate = 0;
  fields.forEach(key => {
    const mode = modeFromSamples(samples, key);
    if (mode) { values[key] = mode.value; aggregate += mode.confidence; }
  });
  state.usualSettings = {
    runs: Number(entry?.runs || samples.length),
    samples: samples.length,
    settings: values,
    averageConfidence: fields.length ? aggregate / fields.length : 0,
  };
  return state.usualSettings;
}
function recordUsualSettings() {
  if (!state.profile.id) return;
  const store = readUsualStore();
  const previous = store[state.profile.id] && typeof store[state.profile.id] === 'object' ? store[state.profile.id] : {};
  const samples = Array.isArray(previous.samples) ? previous.samples.slice(-USUAL_SAMPLE_LIMIT + 1) : [];
  samples.push(usualSettingsSnapshot());
  store[state.profile.id] = { runs: Number(previous.runs || 0) + 1, samples };
  writeUsualStore(store);
  loadUsualSettings();
}
function sameUsualSettings(a, b) {
  if (!a || !b) return true;
  return ['assetType','assetSubtype','repairActions','repairExclusions','excludedFiles','problemHints','priority','repairMode','taskMode','processingSpeed','suffix','outputType'].every(key => canonicalValue(a[key]) === canonicalValue(b[key]));
}
function settingsLabel(settings) {
  const asset = ASSET_TYPES.find(x => x[0] === settings.assetType)?.[1];
  const mode = { standard:'Обычная', medium:'Средняя', aggressive:'Максимальная' }[settings.repairMode] || settings.repairMode;
  const speed = { standard:'Обычная', balanced:'Быстрая', aggressive:'Максимальная' }[settings.processingSpeed] || settings.processingSpeed;
  const task = settings.taskMode === 'modify' ? 'VE 1' : 'VA 2';
  const subtype = (ASSET_SUBTYPES[settings.assetType] || []).find(x => x[0] === settings.assetSubtype)?.[1];
  const issues = Array.isArray(settings.problemHints) ? settings.problemHints.map(key => PROBLEM_HINTS.find(x => x[0] === key)?.[1]).filter(Boolean) : [];
  const priority = Array.isArray(settings.priority) ? settings.priority : [];
  const fragments = [asset, subtype, task, mode, speed];
  if (issues.length) fragments.push(`${issues.slice(0,2).join(' · ')}${issues.length > 2 ? ` +${issues.length - 2}` : ''}`);
  if (priority.length && !priority.includes('all')) fragments.push(`приоритет: ${priority.slice(0,2).join(', ')}${priority.length > 2 ? '…' : ''}`);
  return fragments.filter(Boolean).join(' · ');
}
function updateUsualSettingsPrompt() {
  const box = $('usualSettingsPrompt');
  if (!box) return;
  const usual = loadUsualSettings();
  if (!usual || !state.files.length || sameUsualSettings(usual.settings, usualSettingsSnapshot())) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const text = box.querySelector('[data-usual-summary]');
  if (text) text.textContent = `Обычно вы выбираете: ${settingsLabel(usual.settings)}.`;
  const count = box.querySelector('[data-usual-count]');
  if (count) count.textContent = `${Math.max(usual.runs, usual.samples)} запусков`;
}
function applyUsualSettings() {
  const usual = loadUsualSettings();
  if (!usual?.settings) return;
  const s = usual.settings;
  state.priority = new Set(Array.isArray(s.priority) ? s.priority.filter(Boolean) : []);
  state.repairMode = ['standard','medium','aggressive'].includes(s.repairMode) ? s.repairMode : 'standard';
  state.taskMode = s.taskMode === 'modify' ? 'modify' : 'repair';
  state.processingSpeed = ['standard','balanced','aggressive'].includes(s.processingSpeed) ? s.processingSpeed : 'standard';
  state.suffix = typeof s.suffix === 'string' && s.suffix.trim() ? s.suffix.slice(0,48) : 'FIXED';
  state.assetType = typeof s.assetType === 'string' ? s.assetType : '';
  state.problemHints = new Set(Array.isArray(s.problemHints) ? s.problemHints.filter(Boolean) : []);
  state.problemOther = '';
  if (els.outputType && ['zip','same'].includes(s.outputType)) els.outputType.value = s.outputType;
  localStorage.setItem('mf_repair_mode', state.repairMode);
  localStorage.setItem('mf_task_mode', state.taskMode);
  localStorage.setItem('mf_processing_speed', state.processingSpeed);
  localStorage.setItem(SK.SUFFIX, state.suffix);
  els.priorityChips?.querySelectorAll('.chip').forEach(chip => chip.classList.toggle('active', state.priority.has(chip.dataset.priority)));
  applyRepairModeUI();
  applyTaskModeUI();
  updateNetworkUI();
  if (els.suffixPreview) els.suffixPreview.textContent = state.suffix;
  saveDraft();
  updateSelection();
  toast('Обычные настройки применены.', 'success', 2800);
}
function initials(name) {
  const n = String(name || 'Гость').trim();
  if (!n || n === 'Гость') return 'G';
  return n.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase().slice(0,2) || 'M';
}
function hexToRgb(hex) {
  const value = String(hex || '').replace('#','').trim();
  if (!/^[0-9a-fA-F]{6}$/.test(value)) return [244,123,32];
  return [parseInt(value.slice(0,2),16), parseInt(value.slice(2,4),16), parseInt(value.slice(4,6),16)];
}
function mixHex(a, b, amount = .28) {
  const [ar,ag,ab] = hexToRgb(a), [br,bg,bb] = hexToRgb(b), t=Math.max(0,Math.min(1,Number(amount)||0));
  return '#' + [ar + (br-ar)*t, ag + (bg-ag)*t, ab + (bb-ab)*t].map(x=>Math.round(x).toString(16).padStart(2,'0')).join('');
}
function effectiveAccentColor() {
  if (state.profile.accent === 'blue') return '#6eaadf';
  if (state.profile.accent === 'mint') return '#67c7a0';
  if (state.profile.accent === 'lime') return '#a8d85b';
  if (state.profile.accent === 'custom' && /^#[0-9a-fA-F]{6}$/.test(state.profile.customColor || '')) return state.profile.customColor;
  return '#f47b20';
}
function applyProfile() {
  const root = document.documentElement;
  const accentColor = effectiveAccentColor();
  const strong = mixHex(accentColor, '#ffffff', .28);
  const [r,g,b] = hexToRgb(accentColor);
  root.dataset.accent = state.profile.accent;
  root.dataset.density = state.profile.density;
  root.classList.toggle('reduced-motion', !!state.profile.reducedMotion);
  root.dataset.uiPerformance = state.profile.uiPerformance || 'default';
  root.classList.toggle('no-animations', !!state.profile.reducedMotion);
  root.style.setProperty('--accent', accentColor);
  root.style.setProperty('--accent-strong', strong);
  root.style.setProperty('--accent-rgb', `${r} ${g} ${b}`);
  root.style.setProperty('--accent-soft', `rgb(${r} ${g} ${b} / .11)`);
  root.style.setProperty('--accent-line', `rgb(${r} ${g} ${b} / .45)`);
  root.style.setProperty('--orange', accentColor);
  root.style.setProperty('--orange2', strong);
  root.style.setProperty('--orange-dim', `rgb(${r} ${g} ${b} / .12)`);
  root.style.setProperty('--blue', accentColor);
  root.style.setProperty('--text-accent', mixHex(accentColor, '#ffffff', .55));
  root.style.setProperty('--muted-accent', mixHex(accentColor, '#ffffff', .36));
  root.style.setProperty('--dim-accent', mixHex(accentColor, '#ffffff', .20));
  root.style.setProperty('--text', mixHex(accentColor, '#f4f6f7', .10));
  root.style.setProperty('--muted', mixHex(accentColor, '#f4f6f7', .32));
  root.style.setProperty('--dim', mixHex(accentColor, '#f4f6f7', .19));
  root.style.setProperty('--green', accentColor);
  root.style.setProperty('--yellow', accentColor);
  window.__refreshModForgeBackground?.();
  const name = state.profile.name || 'Гость';
  const ini = initials(name);
  ['profileAvatar','profileAvatarLarge'].forEach(id => { if (els[id]) els[id].textContent = ini; });
  if (els.profileName) els.profileName.textContent = name;
  if (els.profileState) els.profileState.textContent = name === 'Гость' ? 'Локальный профиль' : 'Персональный профиль';
  if (els.profileCardName) els.profileCardName.textContent = name;
  if (els.profileCardMeta) els.profileCardMeta.textContent = name === 'Гость' ? 'Локальный профиль · без аккаунта' : 'Локальный профиль · настройки сохранены';
  if (els.greetingLine) els.greetingLine.textContent = name === 'Гость' ? 'Рабочее пространство готово' : `Добро пожаловать, ${name}`;
  const accentLabel = state.profile.accent === 'orange' ? 'оранжевый' : state.profile.accent === 'blue' ? 'голубой' : state.profile.accent === 'mint' ? 'мятный' : state.profile.accent === 'lime' ? 'салатовый' : accentColor.toUpperCase();
  if (els.profileSummary) els.profileSummary.textContent = `${state.metrics.runs || 0} задач · ${state.metrics.fixed || 0} исправлений · ${accentLabel} акцент`;
  if (els.metricRuns) els.metricRuns.textContent = state.metrics.runs || 0;
  if (els.metricFixed) els.metricFixed.textContent = state.metrics.fixed || 0;
  if (els.metricMode) els.metricMode.textContent = state.metrics.lastTaskMode === 'modify' ? 'LAB' : String(state.metrics.lastMode || 'standard').slice(0,4).toUpperCase();
  if (els.profileLast) els.profileLast.textContent = state.metrics.lastSource ? `Последняя задача: ${state.metrics.lastSource}` : 'Последняя задача: пока нет запусков';
  if (els.profileStateDot) els.profileStateDot.classList.toggle('custom', name !== 'Гость');
  setThemeFavicon();
}
function recordRunMetrics(report) {
  const job = state.jobId || '';
  if (!job || state.metricsRecordedJob === job) return;
  state.metricsRecordedJob = job;
  state.metrics.runs = Number(state.metrics.runs || 0) + 1;
  state.metrics.fixed = Number(state.metrics.fixed || 0) + Number(report?.summary?.fixed || 0);
  state.metrics.lastMode = state.repairMode || 'standard';
  state.metrics.lastTaskMode = state.taskMode || 'repair';
  state.metrics.lastSource = state.sourceName || '';
  saveMetrics();
  applyProfile();
}

/* ══════════════════════════════════════════════════
   PHASE MANAGEMENT
   Buttons visibility via html[data-phase] in CSS
══════════════════════════════════════════════════ */
function setPhase(phase) {
  document.documentElement.setAttribute('data-phase', phase);
}

function setReady(label, detail = '') {
  if (els.readyState) els.readyState.textContent = String(label || 'Готово');
  if (els.startBtn) els.startBtn.setAttribute('aria-label', String(label || 'Начать проверку'));
  if (detail) document.documentElement.dataset.readyDetail = String(detail).slice(0, 200);
  else delete document.documentElement.dataset.readyDetail;
}

setPhase('idle');

/* ══════════════════════════════════════════════════
   ANIMATED BACKGROUND (particle grid)
══════════════════════════════════════════════════ */
(function initBg() {
  const canvas = $('bgCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d', { alpha: true });
  let W = 0, H = 0, particles = [], raf = null, lastFrame = 0;
  const root = document.documentElement;

  function resize() {
    W = canvas.width = Math.max(1, window.innerWidth);
    H = canvas.height = Math.max(1, window.innerHeight);
  }

  function makeParticles() {
    particles = [];
    const mode=root.dataset.uiPerformance || 'default';
    const count = mode==='optimization' ? 0 : mode==='ultra' ? Math.min(34, Math.max(12, Math.floor((W*H)/65000))) : Math.min(24, Math.max(8, Math.floor((W*H)/80000)));
    for (let i = 0; i < count; i++) particles.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.18,vy:(Math.random()-.5)*.18,r:Math.random()*.9+.25,a:Math.random()*.28+.08});
  }

  function disabled(){ return root.classList.contains('no-animations') || root.dataset.uiPerformance==='optimization' || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches; }
  function stop(){ if(raf){cancelAnimationFrame(raf);raf=null;} ctx.clearRect(0,0,W,H); }
  function draw(now=performance.now()) {
    if(disabled()){ stop(); return; }
    const mode=root.dataset.uiPerformance || 'default';
    const interval=mode==='ultra' ? 16 : mode==='high' ? 20 : mode==='standard' ? 28 : 34;
    if(now-lastFrame<interval){ raf=requestAnimationFrame(draw); return; }
    lastFrame=now; ctx.clearRect(0,0,W,H);
    const spacing=56; ctx.fillStyle='rgba(244,123,32,0.055)'; const t=now/1000; const ox=(t*2)%spacing, oy=(t*1.5)%spacing;
    for(let x=-spacing+ox;x<W+spacing;x+=spacing) for(let y=-spacing+oy;y<H+spacing;y+=spacing) ctx.fillRect(x,y,1,1);
    particles.forEach(p=>{p.x+=p.vx;p.y+=p.vy;if(p.x<0)p.x=W;if(p.x>W)p.x=0;if(p.y<0)p.y=H;if(p.y>H)p.y=0;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fillStyle=`rgba(244,123,32,${Math.min(.18,p.a)})`;ctx.fill();});
    raf=requestAnimationFrame(draw);
  }
  function refresh(){ stop(); makeParticles(); if(!disabled()) draw(); }
  window.__refreshModForgeBackground = refresh;
  resize(); makeParticles(); draw();
  window.addEventListener('resize',()=>{resize();makeParticles();if(!disabled()&&!raf)draw();},{passive:true});
})();;

/* ══════════════════════════════════════════════════
   BANNER VISIBILITY / TASK FAVICON
══════════════════════════════════════════════════ */
(function initHeroBanner() {
  const banner = els.heroBannerMedia;
  if (!banner || !('IntersectionObserver' in window)) return;
  const update = ratio => {
    const clamped = Math.max(.12, Math.min(1, ratio));
    banner.style.setProperty('--banner-visibility', clamped.toFixed(2));
    banner.classList.toggle('fully-visible', clamped > .92);
  };
  const observer = new IntersectionObserver(entries => update(entries[0]?.intersectionRatio ?? 1), {threshold:[0,.25,.5,.75,1]});
  observer.observe(banner);
})();

function setThemeFavicon(active = document.body.classList.contains('task-active'), progress = Number(getComputedStyle(document.documentElement).getPropertyValue('--task-progress') || 0) * 100) {
  const favicon = document.querySelector('link[rel="icon"]');
  const meta = document.getElementById('themeColorMeta');
  if (!favicon) return;
  const accent = (state.profile && state.profile.accent) || 'orange';
  const color = effectiveAccentColor();
  const safeProgress = Math.max(0, Math.min(100, Number(progress) || 0));
  const key = `${accent}:${active ? Math.round(safeProgress / 5) : 0}`;
  if (favicon.dataset.mfKey === key) return;
  favicon.dataset.mfKey = key;
  const dot = active ? `<circle cx="26.5" cy="5.5" r="2.5" fill="${color}"/>` : '';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0b0d0e"/><rect x="3" y="3" width="26" height="26" rx="6" fill="none" stroke="${color}" stroke-opacity=".22"/><path d="M8 22V10h3l4 6 4-6h3v12h-3v-6.6l-4 5.7-4-5.7V22H8z" fill="${color}"/>${dot}</svg>`;
  favicon.href = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  favicon.type = 'image/svg+xml';
  if (meta) { const [r,g,b] = hexToRgb(color); const lum = (0.2126*r + 0.7152*g + 0.0722*b); meta.content = lum > 150 ? '#0a0d0e' : '#f7f9fa'; }
}

function setTaskActivity(active, progress=0) {
  const ratio = Math.max(0, Math.min(1, Number(progress) / 100));
  document.documentElement.style.setProperty('--task-progress', ratio.toFixed(3));
  document.body.classList.toggle('task-active', !!active);
  if (els.brandTaskDot) els.brandTaskDot.classList.toggle('active', !!active);
  setThemeFavicon(!!active, ratio * 100);
}


/* ══════════════════════════════════════════════════
   CALM POINTER-REACTIVE BACKGROUND
══════════════════════════════════════════════════ */
(function initPointerAura() {
  let hideTimer = null;
  const setPoint = (x, y, active = true) => {
    document.documentElement.style.setProperty('--pointer-x', `${Math.round(x)}px`);
    document.documentElement.style.setProperty('--pointer-y', `${Math.round(y)}px`);
    document.documentElement.style.setProperty('--pointer-aura', active ? '1' : '0');
  };
  let lastMove = 0;
  window.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const now = performance.now();
    if (now - lastMove < 40) return;
    lastMove = now;
    setPoint(e.clientX, e.clientY, true);
  }, { passive: true });
  window.addEventListener('pointerdown', e => {
    setPoint(e.clientX, e.clientY, true);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => setPoint(e.clientX, e.clientY, false), 1100);
  }, { passive: true });
  window.addEventListener('touchstart', e => {
    const t = e.touches?.[0];
    if (!t) return;
    setPoint(t.clientX, t.clientY, true);
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => setPoint(t.clientX, t.clientY, false), 1100);
  }, { passive: true });
  setPoint(window.innerWidth * .52, window.innerHeight * .34, false);
})();

/* ══════════════════════════════════════════════════
   TOAST SYSTEM
══════════════════════════════════════════════════ */
function toast(msg, type = 'info', duration = 3500) {
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  const closeBtn = document.createElement('button');
  closeBtn.textContent = '×';
  const msgSpan = document.createElement('span');
  msgSpan.textContent = msg;
  t.appendChild(msgSpan);
  t.appendChild(closeBtn);
  els.toastContainer.appendChild(t);
  requestAnimationFrame(() => t.classList.add('show'));
  const remove = () => { t.classList.remove('show'); setTimeout(() => t.remove(), 350); };
  closeBtn.addEventListener('click', remove);
  if (duration > 0) setTimeout(remove, duration);
  return remove;
}

/* ══════════════════════════════════════════════════
   MATERIAL MOTION HELPERS
══════════════════════════════════════════════════ */
function addRipple(el, event) {
  if (!el || document.documentElement.classList.contains('reduced-motion')) return;
  if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
  const r = document.createElement('span');
  r.className = 'ripple';
  const rect = el.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 1.35;
  r.style.width = `${size}px`; r.style.height = `${size}px`;
  r.style.left = `${(event.clientX || rect.left + rect.width/2) - rect.left - size/2}px`;
  r.style.top = `${(event.clientY || rect.top + rect.height/2) - rect.top - size/2}px`;
  el.appendChild(r);
  setTimeout(() => r.remove(), 650);
}
document.addEventListener('pointerdown', e => {
  const el = e.target.closest?.('.btn,.workflow-tab,.mode-card,.network-card,.chip,.custom-line,.profile-chip,.game-tab,.stage-more,.segment,.accent-option');
  if (el) addRipple(el, e);
}, { passive: true });

if ('IntersectionObserver' in window) {
  const revealObserver = new IntersectionObserver(entries => {
    entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('motion-visible'); revealObserver.unobserve(entry.target); } });
  }, { threshold: .08 });
  document.querySelectorAll('.panel,.config-box,.vehicle-detect,.hero-personal').forEach((el, i) => {
    el.classList.add('motion-reveal');
    el.style.setProperty('--reveal-delay', `${Math.min(i * 18, 180)}ms`);
    revealObserver.observe(el);
  });
}

document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.key !== 'Enter' || e.shiftKey || e.altKey) return;
  if (state.preparedJob?.status === 'prepared') {
    e.preventDefault();
    beginTaskFromUI();
    return;
  }
  if (!state.busy && els.startBtn && !els.startBtn.disabled) {
    e.preventDefault();
    startUpload();
  }
});

/* ══════════════════════════════════════════════════
   DRAFT PERSISTENCE
══════════════════════════════════════════════════ */
function saveDraft() {
  try {
    localStorage.setItem(SK.DRAFT, JSON.stringify({
      wishes: els.wishes?.value || '',
      outputType: els.outputType?.value || 'zip',
      priority: Array.from(state.priority || []),
      suffix: state.suffix || 'FIXED',
      repairMode: state.repairMode || 'standard',
      taskMode: state.taskMode || 'repair',
      processingSpeed: state.processingSpeed || 'standard',
      processingWorkers: state.processingWorkers || 2,
      largeFileWorkers: state.largeFileWorkers || 1,
      modRequest: els.modRequest?.value || '',
      assetType: state.assetType || '',
      assetSubtype: state.assetSubtype || '',
      repairActions: Array.from(state.repairActions || []),
      repairExclusions: Array.from(state.repairExclusions || []),
      aiTrafficScope: state.aiTrafficScope || 'all',
      excludedFiles: Array.from(state.excludedFiles || []),
      problemHints: Array.from(state.problemHints || []),
      problemOther: state.problemOther || '',
    }));
  } catch {}
}
function loadDraft() {
  try {
    const d = JSON.parse(localStorage.getItem(SK.DRAFT) || 'null');
    if (!d) return;
    if (els.wishes && typeof d.wishes === 'string') els.wishes.value = d.wishes;
    if (els.outputType && (d.outputType === 'zip' || d.outputType === 'same')) els.outputType.value = d.outputType;
    if (Array.isArray(d.priority)) {
      state.priority = new Set(d.priority.filter(Boolean));
      els.priorityChips?.querySelectorAll('.chip').forEach(chip => chip.classList.toggle('active', state.priority.has(chip.dataset.priority)));
    }
    if (d.repairMode && ['standard','medium','aggressive'].includes(d.repairMode)) state.repairMode=d.repairMode;
    if (d.taskMode === 'modify' || d.taskMode === 'repair') state.taskMode=d.taskMode;
    if (['standard','balanced','aggressive'].includes(d.processingSpeed || d.networkProfile)) state.processingSpeed=d.processingSpeed || d.networkProfile;
    if (Number(d.processingWorkers)) state.processingWorkers=Number(d.processingWorkers);
    if (Number(d.largeFileWorkers)) state.largeFileWorkers=Number(d.largeFileWorkers);
    if (els.modRequest && typeof d.modRequest === 'string') els.modRequest.value=d.modRequest;
    if (typeof d.assetType === 'string') state.assetType=d.assetType;
    if (typeof d.assetSubtype === 'string') state.assetSubtype=d.assetSubtype;
    if (Array.isArray(d.repairActions)) state.repairActions=new Set(d.repairActions.filter(x=>REPAIR_ACTIONS.some(a=>a[0]===x)));
    if (Array.isArray(d.repairExclusions)) state.repairExclusions=new Set(d.repairExclusions.filter(x=>REPAIR_EXCLUSIONS.some(a=>a[0]===x)));
    if (d.aiTrafficScope === 'target' || d.aiTrafficScope === 'all') state.aiTrafficScope=d.aiTrafficScope;
    if (Array.isArray(d.excludedFiles)) state.excludedFiles=d.excludedFiles.map(x=>String(x).trim()).filter(Boolean).slice(0,100);
    if (Array.isArray(d.problemHints)) state.problemHints=new Set(d.problemHints.filter(Boolean));
    if (typeof d.problemOther === 'string') state.problemOther = d.problemOther.slice(0, 2000);
    if (d.suffix) {
      state.suffix = String(d.suffix).slice(0,48);
      if (els.suffixPreview) els.suffixPreview.textContent = state.suffix;
    }
  } catch {}
}

/* ══════════════════════════════════════════════════
   SESSION PERSISTENCE
══════════════════════════════════════════════════ */
function makeFingerprint(files) {
  return Array.from(files).map(f => `${f.name}:${f.size}:${f.lastModified || 0}`).join('|');
}

function saveSession(data) {
  try { localStorage.setItem(SK.SESSION, JSON.stringify({ ...data, ts: Date.now() })); } catch {}
}

function updateSession(update) {
  try {
    const raw = localStorage.getItem(SK.SESSION);
    if (!raw) return;
    const s = JSON.parse(raw);
    localStorage.setItem(SK.SESSION, JSON.stringify({ ...s, ...update }));
  } catch {}
}

function loadSession() {
  try {
    const raw = localStorage.getItem(SK.SESSION);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (!s || !s.ts || Date.now() - s.ts > SESSION_TTL) {
      localStorage.removeItem(SK.SESSION);
      return null;
    }
    return s;
  } catch { return null; }
}

function clearSession() { localStorage.removeItem(SK.SESSION); }
function saveLastJob(data) {
  try { localStorage.setItem(SK.LAST_JOB, JSON.stringify({ ...data, ts: Date.now() })); } catch {}
}
function loadLastJob() {
  try {
    const raw = localStorage.getItem(SK.LAST_JOB);
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (!d || !d.jobId || !d.ts || Date.now() - d.ts > SESSION_TTL) { localStorage.removeItem(SK.LAST_JOB); return null; }
    return d;
  } catch { return null; }
}
function clearLastJob() { localStorage.removeItem(SK.LAST_JOB); }


function checkFileAgainstSession(files) {
  const session = loadSession();
  if (!session || !session.jobId) return;
  const fp = makeFingerprint(files);
  if (fp === session.fingerprint) {
    showSessionBanner(session);
  }
}

function showSessionBanner(session) {
  els.sessionBanner.hidden = false;
  els.sessionDesc.textContent =
    `«${session.sourceName || 'файл'}» · этап ${session.stageIndex || '?'} · ${timeAgo(session.ts)}`;
  els.sessionResume.onclick = () => resumeSession(session);
  els.sessionDismiss.onclick = () => {
    clearSession();
    els.sessionBanner.hidden = true;
  };
}

async function resumeSession(session) {
  els.sessionBanner.hidden = true;
  state.jobId = session.jobId;
  state.sourceName = session.sourceName || '';
  beginVisual();
  setPhase('processing');
  els.progressState.textContent = 'Восстановление сессии…';
  try {
    await poll();
    toast('Сессия восстановлена с этапа ' + (session.stageIndex || 1), 'success');
  } catch (e) {
    showError('MF-503: Не удалось восстановить сессию. ' + e.message);
    clearSession();
  }
}

// On page load: try to restore active session automatically (F5 protection)
async function tryRestoreOnLoad() {
  if (state.resetDetected) return;
  const session = loadSession();
  const last = loadLastJob();
  const candidate = session || last;
  if (!candidate || !candidate.jobId) return;
  try {
    const job = await api(`/api/jobs/${candidate.jobId}`);
    state.jobId = candidate.jobId;
    state.sourceName = candidate.sourceName || job.source_name || '';
    state.kind = candidate.kind || job.source_kind || 'zip';
    state.lastRun = { ...candidate };
    if (Array.isArray(candidate.priority)) state.priority = new Set(candidate.priority);
    if (typeof candidate.wishes === 'string' && els.wishes) els.wishes.value = candidate.wishes;
    if (candidate.outputType && els.outputType) els.outputType.value = candidate.outputType;
    if (candidate.suffix) { state.suffix = candidate.suffix; if (els.suffixPreview) els.suffixPreview.textContent = candidate.suffix; }
    if (candidate.repairMode) { state.repairMode=candidate.repairMode; applyRepairModeUI(); }
    if (candidate.taskMode) { state.taskMode=candidate.taskMode; applyTaskModeUI(); }
    if (typeof candidate.assetType === 'string') state.assetType=candidate.assetType;
    if (typeof candidate.assetSubtype === 'string') state.assetSubtype=candidate.assetSubtype;
    if (Array.isArray(candidate.repairActions)) state.repairActions=new Set(candidate.repairActions);
    if (Array.isArray(candidate.repairExclusions)) state.repairExclusions=new Set(candidate.repairExclusions);
    if (Array.isArray(candidate.excludedFiles)) state.excludedFiles=candidate.excludedFiles;
    if (Array.isArray(candidate.problemHints)) state.problemHints=new Set(candidate.problemHints);
    if (typeof job.asset_type === 'string' && !state.assetType) state.assetType=job.asset_type;
    if (typeof job.asset_subtype === 'string' && !state.assetSubtype) state.assetSubtype=job.asset_subtype;
    if (Array.isArray(job.repair_actions) && !state.repairActions.size) state.repairActions=new Set(job.repair_actions);
    if (Array.isArray(job.repair_exclusions) && !state.repairExclusions.size) state.repairExclusions=new Set(job.repair_exclusions);
    if (job.ai_traffic_scope === 'target' || job.ai_traffic_scope === 'all') state.aiTrafficScope=job.ai_traffic_scope;
    if (Array.isArray(job.excluded_files) && !state.excludedFiles.length) state.excludedFiles=job.excluded_files;
    if (Array.isArray(job.problem_hints) && !state.problemHints.size) state.problemHints=new Set(job.problem_hints);

    if (job.status === 'running' || job.status === 'processing' || job.status === 'paused' || job.status === 'queued' || job.status === 'rebuilding') {
      saveSession({ ...candidate, jobId: candidate.jobId, stageIndex: job.stage_index || 0 });
      beginVisual();
      setPhase('processing');
      poll();
      toast('Сохранённая задача восстановлена автоматически', 'success', 4000);
    } else if (job.status === 'done') {
      const report = await api(`/api/jobs/${candidate.jobId}/report`, { __timeoutMs: RESULT_TIMEOUT_MS });
      renderResult(report);
      saveLastJob({ ...candidate, jobId: candidate.jobId, ts: Date.now() });
      clearSession();
      toast('Последний результат восстановлен — файл снова доступен для скачивания.', 'success', 5000);
    } else {
      clearSession();
    }
  } catch (e) {
    // Keep the last-job reference for a short period so a transient backend restart
    // does not erase the user's ability to retry when the service comes back.
    if (session && /MF-404|не найден/i.test(String(e?.message || ''))) showError('MF-528: Сохранённая сессия больше не найдена после сброса данных. Локальная запись сохранена.');
    else if (session) toast('Сервис временно недоступен. Последняя задача сохранена.', 'warning', 4500);
  }
}

/* ══════════════════════════════════════════════════
   SNAKE GAME
══════════════════════════════════════════════════ */
class Snake {
  constructor(canvas) {
    this.cv = canvas;
    this.cx = canvas.getContext('2d');
    this.CELL = 20;
    this.COLS = Math.floor(canvas.width / this.CELL);
    this.ROWS = Math.floor(canvas.height / this.CELL);
    this.state = 'idle'; // idle | running | paused | dead
    this.hi = parseInt(localStorage.getItem(SK.SNAKE_HI) || '0');
    this.touchStart = null;
    this.score = 0;
    this.reset();
    this._onKey = this.onKey.bind(this);
    this._onTouchStart = this.onTouchStart.bind(this);
    this._onTouchEnd = this.onTouchEnd.bind(this);
    document.addEventListener('keydown', this._onKey);
    canvas.addEventListener('touchstart', this._onTouchStart, { passive: true });
    canvas.addEventListener('touchend', this._onTouchEnd, { passive: true });
    this.render();
    if (els.snakeHi) els.snakeHi.textContent = this.hi;
  }

  reset() {
    const cx = Math.floor(this.COLS / 2);
    const cy = Math.floor(this.ROWS / 2);
    this.snake = [{ x: cx, y: cy }, { x: cx - 1, y: cy }];
    this.dir = { x: 1, y: 0 };
    this.next = { x: 1, y: 0 };
    this.food = this.placeFood();
    this.score = 0;
    this.speed = 8;
    this.interval = 1000 / this.speed;
    this.lastT = 0;
    if (els.snakeScore) els.snakeScore.textContent = 0;
  }

  placeFood() {
    let p;
    do { p = { x: Math.floor(Math.random() * this.COLS), y: Math.floor(Math.random() * this.ROWS) }; }
    while (this.snake.some(s => s.x === p.x && s.y === p.y));
    return p;
  }

  onKey(e) {
    if (els.gameOverlay.hidden) return;
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      if (this.state === 'idle' || this.state === 'dead') this.start();
      else if (this.state === 'running') this.pause();
      else if (this.state === 'paused') this.resume();
      return;
    }
    const map = {
      ArrowUp: {x:0,y:-1}, w: {x:0,y:-1}, W: {x:0,y:-1},
      ArrowDown: {x:0,y:1}, s: {x:0,y:1}, S: {x:0,y:1},
      ArrowLeft: {x:-1,y:0}, a: {x:-1,y:0}, A: {x:-1,y:0},
      ArrowRight: {x:1,y:0}, d: {x:1,y:0}, D: {x:1,y:0},
    };
    const d = map[e.key];
    if (!d) return;
    if (d.x !== 0 && d.x === -this.dir.x) return;
    if (d.y !== 0 && d.y === -this.dir.y) return;
    this.next = d;
    if (e.key.startsWith('Arrow')) e.preventDefault();
  }

  onTouchStart(e) {
    this.touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    if (this.state === 'idle' || this.state === 'dead') this.start();
  }

  onTouchEnd(e) {
    if (!this.touchStart) return;
    const dx = e.changedTouches[0].clientX - this.touchStart.x;
    const dy = e.changedTouches[0].clientY - this.touchStart.y;
    if (Math.abs(dx) < 12 && Math.abs(dy) < 12) { this.touchStart = null; return; }
    let d;
    if (Math.abs(dx) > Math.abs(dy)) d = dx > 0 ? {x:1,y:0} : {x:-1,y:0};
    else d = dy > 0 ? {x:0,y:1} : {x:0,y:-1};
    if (!(d.x !== 0 && d.x === -this.dir.x) && !(d.y !== 0 && d.y === -this.dir.y)) this.next = d;
    this.touchStart = null;
  }

  start() { this.reset(); this.state = 'running'; this.lastT = performance.now(); this.loop(this.lastT); if (els.gameStatus) els.gameStatus.textContent = 'Пробел — пауза'; }
  pause() { this.state = 'paused'; if (els.gameStatus) els.gameStatus.textContent = 'Пауза · пробел — продолжить'; this.render(); }
  resume() { this.state = 'running'; this.lastT = performance.now(); this.loop(this.lastT); if (els.gameStatus) els.gameStatus.textContent = 'Пробел — пауза'; }

  loop(now) {
    if (this.state !== 'running') return;
    requestAnimationFrame(t => this.loop(t));
    if (now - this.lastT < this.interval) return;
    this.lastT = now;
    this.update();
    this.render();
  }

  update() {
    this.dir = { ...this.next };
    const head = { x: this.snake[0].x + this.dir.x, y: this.snake[0].y + this.dir.y };
    if (head.x < 0 || head.x >= this.COLS || head.y < 0 || head.y >= this.ROWS || this.snake.some(s => s.x === head.x && s.y === head.y)) {
      this.die(); return;
    }
    this.snake.unshift(head);
    if (head.x === this.food.x && head.y === this.food.y) {
      this.score++;
      if (this.score > this.hi) { this.hi = this.score; localStorage.setItem(SK.SNAKE_HI, this.hi); if (els.snakeHi) els.snakeHi.textContent = this.hi; }
      if (els.snakeScore) els.snakeScore.textContent = this.score;
      this.food = this.placeFood();
      if (this.score % 5 === 0 && this.speed < 20) { this.speed++; this.interval = 1000 / this.speed; }
    } else { this.snake.pop(); }
  }

  die() {
    this.state = 'dead';
    if (els.gameStatus) els.gameStatus.textContent = `Конец игры! Счёт: ${this.score} · пробел для рестарта`;
    this.render();
  }

  render() {
    const { cx: c, cv, CELL: S, COLS, ROWS } = this;
    const W = cv.width, H = cv.height;
    c.fillStyle = '#07090a';
    c.fillRect(0, 0, W, H);

    // Grid
    c.strokeStyle = 'rgba(255,255,255,.025)';
    c.lineWidth = .5;
    for (let x = 0; x <= COLS; x++) { c.beginPath(); c.moveTo(x*S, 0); c.lineTo(x*S, H); c.stroke(); }
    for (let y = 0; y <= ROWS; y++) { c.beginPath(); c.moveTo(0, y*S); c.lineTo(W, y*S); c.stroke(); }

    if (this.state === 'idle') {
      c.fillStyle = 'rgba(244,123,32,.8)';
      c.font = '600 12px Inter, sans-serif';
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('Нажмите пробел или тапните', W/2, H/2 - 10);
      c.fillStyle = 'rgba(142,151,155,.6)';
      c.font = '11px Inter, sans-serif';
      c.fillText('← ↑ → ↓  WASD  свайп', W/2, H/2 + 12);
      return;
    }

    // Food: glowing circle
    const fx = this.food.x * S, fy = this.food.y * S;
    c.fillStyle = '#e85555';
    c.shadowColor = '#e85555';
    c.shadowBlur = 10;
    c.beginPath();
    c.arc(fx + S/2, fy + S/2, S/2 - 3, 0, Math.PI*2);
    c.fill();
    c.shadowBlur = 0;

    // Snake
    this.snake.forEach((seg, i) => {
      const ratio = 1 - i / this.snake.length;
      if (i === 0) {
        c.fillStyle = '#f47b20';
        c.shadowColor = '#f47b20';
        c.shadowBlur = 8;
      } else {
        c.fillStyle = `rgba(244,123,32,${.25 + ratio * .65})`;
        c.shadowBlur = 0;
      }
      const r = i === 0 ? 5 : 3;
      const x = seg.x * S + 1, y = seg.y * S + 1, w = S - 2, h = S - 2;
      c.beginPath();
      c.roundRect ? c.roundRect(x, y, w, h, r) : c.rect(x, y, w, h);
      c.fill();
    });
    c.shadowBlur = 0;

    // Overlays
    if (this.state === 'paused') {
      c.fillStyle = 'rgba(0,0,0,.65)';
      c.fillRect(0, 0, W, H);
      c.fillStyle = 'rgba(244,123,32,.95)';
      c.font = '700 15px Inter, sans-serif';
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('ПАУЗА', W/2, H/2);
    }
    if (this.state === 'dead') {
      c.fillStyle = 'rgba(0,0,0,.72)';
      c.fillRect(0, 0, W, H);
      c.fillStyle = '#e86666';
      c.font = '700 17px Inter, sans-serif';
      c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('КОНЕЦ ИГРЫ', W/2, H/2 - 14);
      c.fillStyle = '#f47b20';
      c.font = '600 12px Inter, sans-serif';
      c.fillText(`Счёт: ${this.score}  ·  Рекорд: ${this.hi}`, W/2, H/2 + 8);
      c.fillStyle = 'rgba(142,151,155,.7)';
      c.font = '11px Inter, sans-serif';
      c.fillText('Пробел для рестарта', W/2, H/2 + 26);
    }
  }

  destroy() { this.state = 'paused'; document.removeEventListener('keydown', this._onKey); this.cv.removeEventListener('touchstart', this._onTouchStart); this.cv.removeEventListener('touchend', this._onTouchEnd); }
}

let snake = null;
let gameMinimized = false;
let activeGame = 'snake';
let reactionGame = null;

class ReactionGame {
  constructor() { this.state='idle'; this.timer=null; this.startedAt=0; this.best=Number(localStorage.getItem('mf_reaction_best')||0); this.readyTimer=null; this.render(); }
  render(){ if(!els.reactionTimer) return; els.reactionTimer.textContent=this.best?`${this.best} ms`:'—'; }
  start(){
    this.cleanup(); this.state='waiting'; if(els.gameStatus) els.gameStatus.textContent='Жди сигнал…'; if(els.reactionTarget){els.reactionTarget.className='reaction-target waiting';els.reactionTarget.textContent='ЖДИ';}
    const delay=900+Math.random()*2800; this.readyTimer=setTimeout(()=>{this.state='ready';this.startedAt=performance.now();if(els.reactionTarget){els.reactionTarget.className='reaction-target ready';els.reactionTarget.textContent='ЖМИ';}if(els.gameStatus)els.gameStatus.textContent='Нажми как можно быстрее';},delay);
  }
  click(){
    if(this.state==='idle' || this.state==='done'){ this.start(); return; }
    if(this.state==='waiting'){ this.state='false'; if(els.gameStatus)els.gameStatus.textContent='Слишком рано. Попробуй ещё раз.'; if(els.reactionTarget){els.reactionTarget.className='reaction-target false';els.reactionTarget.textContent='РАНО';} setTimeout(()=>this.start(),700); return; }
    if(this.state==='ready'){ const ms=Math.round(performance.now()-this.startedAt); this.state='done'; if(!this.best||ms<this.best){this.best=ms;localStorage.setItem('mf_reaction_best',String(ms));} if(els.reactionTimer)els.reactionTimer.textContent=`${ms} ms`;if(els.gameStatus)els.gameStatus.textContent='Нажми снова для нового раунда';if(els.reactionTarget){els.reactionTarget.className='reaction-target done';els.reactionTarget.textContent=`${ms} MS`;} }
  }
  cleanup(){ if(this.readyTimer)clearTimeout(this.readyTimer);this.readyTimer=null; }
  destroy(){this.cleanup();}
}

function selectGame(name){
  activeGame = name==='reaction' ? 'reaction' : 'snake';
  els.gameOverlay?.querySelectorAll('.game-tab').forEach(tab=>tab.classList.toggle('active',tab.dataset.game===activeGame));
  els.gameOverlay?.querySelectorAll('[data-game-panel]').forEach(panel=>panel.hidden=panel.dataset.gamePanel!==activeGame);
  if(els.gameTitle)els.gameTitle.textContent=activeGame==='reaction'?'Реакция':'Змейка';
  if(els.gameControlsHint)els.gameControlsHint.textContent=activeGame==='reaction'?'Нажми кнопку только после сигнала':'← ↑ → ↓ · WASD · свайп';
  if(activeGame==='reaction' && !reactionGame) reactionGame=new ReactionGame();
  if(activeGame==='reaction'){ if(els.reactionTimer)els.reactionTimer.textContent=reactionGame?.best?`${reactionGame.best} ms`:'—'; }
  else if(snake && snake.state==='idle') snake.render();
}

function showGame() {
  if (!els.gameOverlay) return;
  els.gameOverlay.hidden = false;
  if (!snake) snake = new Snake(els.snakeCanvas);
  if (!reactionGame) reactionGame = new ReactionGame();
  if (els.snakeHi) els.snakeHi.textContent = parseInt(localStorage.getItem(SK.SNAKE_HI) || '0');
  selectGame(activeGame);
}
function hideGame() {
  if (!els.gameOverlay) return;
  els.gameOverlay.hidden = true;
  reactionGame?.cleanup();
}

els.gameOverlay?.querySelectorAll('.game-tab').forEach(tab=>tab.addEventListener('click',()=>selectGame(tab.dataset.game)));
els.reactionTarget?.addEventListener('click',()=>reactionGame?.click());
if (els.gameMinimize) els.gameMinimize.addEventListener('click', () => {
  const panel = els.gameOverlay.querySelector('.game-panel'); gameMinimized = !gameMinimized;
  if (panel) panel.classList.toggle('minimized', gameMinimized);
  const stages=els.gameOverlay.querySelectorAll('.game-stage,.game-tabs,.game-footer'); stages.forEach(x=>x.classList.toggle('game-collapsed',gameMinimized));
  els.gameMinimize.textContent = gameMinimized ? '□' : '─';
});
if (els.gameClose) els.gameClose.addEventListener('click', hideGame);
if (els.snakePromoBtn) els.snakePromoBtn.addEventListener('click', showGame);

/* ══════════════════════════════════════════════════
   API
══════════════════════════════════════════════════ */
async function api(url, opts = {}) {
  const ctrl = new AbortController();
  const hasTimeout = Object.prototype.hasOwnProperty.call(opts, '__timeoutMs');
  const rawTimeout = hasTimeout ? opts.__timeoutMs : API_TIMEOUT_MS;
  const timeoutMs = rawTimeout === null ? null : Number(rawTimeout);
  const requestOpts = { ...opts };
  delete requestOpts.__timeoutMs;
  let t = null;
  if (timeoutMs !== null && Number.isFinite(timeoutMs) && timeoutMs > 0) t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...requestOpts, signal: ctrl.signal, headers: { ...(requestOpts.headers || {}), 'Cache-Control': 'no-cache' } });
    let d = {};
    try { d = await r.json(); } catch {}
    if (!r.ok) { const code = d.code || `MF-${r.status}`; throw new Error(`${code}: ${d.message || `HTTP ${r.status}`}`); }
    return d;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('MF-TIMEOUT: backend не ответил вовремя.');
    if (/Failed to fetch|NetworkError|Load failed/i.test(String(e.message))) throw new Error('MF-503: не удалось достучаться до backend.');
    throw e;
  } finally { if (t) clearTimeout(t); }
}

/* ══════════════════════════════════════════════════
   MODAL
══════════════════════════════════════════════════ */
function openModal(content, actions = '') {
  els.modalContent.innerHTML = content;
  els.modalActions.innerHTML = actions;
  els.modal.hidden = false;
  document.body.classList.add('modal-open');
}
function closeModal() { els.modal.hidden = true; document.body.classList.remove('modal-open'); }
els.modalClose.addEventListener('click', closeModal);
els.modal.addEventListener('click', e => { if (e.target === els.modal) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !els.modal.hidden) closeModal(); });

/* ══════════════════════════════════════════════════
   STAGES
══════════════════════════════════════════════════ */
const REPAIR_BLOCK_RANGES = {
  standard: [[1],[2],[3,4],[5,6],[7,8,9],[10,11],[12,13,14,15]],
  medium: [[1],[2],[3],[4,5],[6],[7,8],[9],[10],[11],[12,13,14],[15]],
  aggressive: Array.from({length:15},(_,i)=>[i+1]),
};

function currentRepairBlocks(){
  return REPAIR_BLOCK_RANGES[state.repairMode] || REPAIR_BLOCK_RANGES.standard;
}
function blockLabel(block){
  const first=state.stages[(block[0]||1)-1];
  if(!first) return `Блок ${block[0]||1}`;
  if(block.length===1) return first.label;
  const labels=block.map(i=>state.stages[i-1]?.label).filter(Boolean);
  return labels.join(' · ');
}
function renderStages() {
  const blocks=currentRepairBlocks();
  const regular = blocks.map((block,i) => `<article class="stage" data-stage-block="${i+1}" data-stage-internal="${block.join(',')}">
      <div class="stage-top">
        <div class="stage-number">${String(i+1).padStart(2,'0')}</div>
        <div class="stage-main"><div class="stage-title-row"><b>${esc(blockLabel(block))}</b><span class="stage-state-icon" data-stage-icon="${i+1}" aria-label="Ожидает">•</span></div><span>${block.length>1 ? `Группа из ${block.length} внутренних проверок.` : esc(state.stages[(block[0]||1)-1]?.description || 'Проверка.')}</span></div>
        <strong data-stage-p="${i+1}">0%</strong>
      </div>
      <button class="stage-more" data-toggle="${i+1}" type="button">⋯ Подробнее</button>
      <div class="stage-detail" data-detail="${i+1}">Ожидает запуска.</div><div class="stage-connection-note" data-stage-connection="${i+1}" hidden><span>!</span><b>Соединение с backend задерживается.</b><small>Ответ ещё ожидается; текущая проверка не отменена. Откройте «Подробнее», чтобы увидеть состояние.</small></div>
    </article>`).join('');
  const large = (state.largeFiles||[]).map(item => {
    const n=Number(item.block_no||16); const status=item.status||'queued';
    return `<article class="stage large-stage ${status==='done'?'done':''} ${status==='checking'?'active':''} ${status==='error'?'error':''}" data-large-block="${n}">
      <div class="stage-top"><div class="stage-number">${String(n).padStart(2,'0')}</div><div class="stage-main"><div class="stage-title-row"><b>Крупный файл · ${esc(item.file||'')}</b><span class="stage-state-icon" data-large-icon="${n}" aria-label="Ожидает">${status==='done'?'✓':status==='error'?'!':status==='checking'?'':'•'}</span></div><span>Отдельный потоковый блок; 50% рабочего бюджета крупных файлов.</span></div><strong>${status==='done'?'100%':status==='checking'?`${Number(item.progress||0)}%`:'0%'}</strong></div>
      <button class="stage-more" data-toggle-large="${n}" type="button">⋯ Подробнее</button><div class="stage-detail" data-large-detail="${n}">Размер: ${esc(bytes(item.size||0))}</div><div class="stage-connection-note" data-large-connection="${n}" hidden><span>!</span><b>Соединение с backend задерживается.</b><small>Ответ ещё ожидается; файл продолжает проверяться.</small></div>
    </article>`;
  }).join('');
  els.stageGrid.innerHTML = regular + large;
  els.stageGrid.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', () => b.closest('.stage').classList.toggle('open')));
  els.stageGrid.querySelectorAll('[data-toggle-large]').forEach(b => b.addEventListener('click', () => b.closest('.stage').classList.toggle('open')));
}

function setLargeStageUI(job) {
  if (Number(job.large_file_count||0)>0) {
    const next=JSON.parse(JSON.stringify(job.large_files||[]));
    next.forEach((item,idx)=>{ if(!item.block_no) item.block_no=16+idx; });
    state.largeFiles=next;
    renderStages();
  }
  const status = job.large_task_status || 'idle';
  (state.largeFiles||[]).forEach((item,idx)=>{
    const n=Number(item.block_no||16+idx); const card=els.stageGrid.querySelector(`[data-large-block="${n}"]`); if(!card)return;
    const st=(job.large_files||[]).find(x=>x.file===item.file)||item;
    card.classList.toggle('done', st.status==='done'); card.classList.toggle('active',st.status==='checking'); card.classList.toggle('error',st.status==='error');
    const icon=card.querySelector(`[data-large-icon="${n}"]`); if(icon){ const cls=st.status==='done'?'done':st.status==='error'?'error':st.status==='checking'?'checking':''; icon.textContent=cls==='done'?'✓':cls==='error'?'!':cls==='checking'?'':'•'; icon.className=`stage-state-icon ${cls}`; icon.setAttribute('aria-label', cls==='done'?'Завершено':cls==='error'?'Ошибка':cls==='checking'?'Выполняется':'Ожидает'); }
    const pct=st.status==='done'?100:(st.progress||0); const strong=card.querySelector('.stage-top>strong'); if(strong) strong.textContent=`${Number(pct)||0}%`;
    const detail=card.querySelector(`[data-large-detail="${n}"]`); if(detail) detail.textContent=job.large_task_detail || `Размер: ${bytes(st.size||0)}`;
  });
}

function setStageUI(job) {
  state.lastStatusJob = job;
  const idx = Number(job.stage_index || 0);
  state.paused = job.status === 'paused';
  state.connectionStageIndex = idx;
  const isVE1 = job.engine_id === 'VE1';
  document.documentElement.dataset.engine = isVE1 ? 'VE1' : 'VA2';
  const blocks=currentRepairBlocks();
  const blockIndex=Math.max(0, blocks.findIndex(r=>r.includes(idx))) + 1;
  if (job.processing_speed && ['standard','balanced','aggressive'].includes(job.processing_speed)) state.processingSpeed=job.processing_speed;
  if (job.processing_network_intensity) state.processingIntensity=job.processing_network_intensity;
  els.processTitle.textContent = job.stage_label || 'Проверка';
  els.processDetail.textContent = job.stage_detail || '—';
  els.overallPct.textContent = `${Math.round(job.progress || 0)}%`;
  els.stageCount.textContent = isVE1 ? `${Math.min(Math.max(idx,1),3)} / 3` : `${Math.min(blockIndex, blocks.length)} / ${blocks.length}`;
  els.progressBar.style.width = `${Math.min(100, Math.max(0, Number(job.progress) || 0))}%`;
  els.progressState.textContent = job.status === 'paused' ? 'Пауза' : job.status === 'cooldown' ? 'Короткая разгрузка' : job.status === 'lab_ready' ? 'Лаборатория готова' : job.status === 'done' ? 'Завершено' : ['error','rebuilding'].includes(job.status) ? (job.status === 'rebuilding' ? 'Восстановление файла' : 'Ошибка') : job.stage_label || 'Обработка';
  const etaNow=Number(job.eta_seconds);
  if(job.status==='waiting_selection'){ els.eta.textContent='Ожидает выбора модели'; } else { els.eta.textContent=etaStr(job.eta_seconds); }
  if(Number.isFinite(etaNow)){ if(state.lastEtaSeconds!==null && Math.abs(etaNow-state.lastEtaSeconds)>=5){ els.eta.classList.remove('eta-updated'); void els.eta.offsetWidth; els.eta.classList.add('eta-updated'); } state.lastEtaSeconds=etaNow; }
  blocks.forEach((block,i)=>{
    const card=els.stageGrid.querySelector(`[data-stage-block="${i+1}"]`); if(!card)return;
    const done=idx>0 && block.every(x=>x<idx) || job.status==='done';
    const active=block.includes(idx) && !['done','error','lab_ready'].includes(job.status);
    const error=block.includes(idx) && job.status==='error';
    card.classList.toggle('done',done); card.classList.toggle('active',active); card.classList.toggle('error',error);
    const icon=card.querySelector(`[data-stage-icon="${i+1}"]`); if(icon){ const cls=error?'error':done?'done':active?'checking':''; icon.textContent=cls==='done'?'✓':cls==='error'?'!':cls==='checking'?'':'•'; icon.className=`stage-state-icon ${cls}`; icon.setAttribute('aria-label', cls==='done'?'Завершено':cls==='error'?'Ошибка':cls==='checking'?'Выполняется':'Ожидает'); }
    const p=card.querySelector(`[data-stage-p="${i+1}"]`);
    if(p) p.textContent=done?'100%':active?`${Number(job.stage_progress)||0}%`:'0%';
    const d=card.querySelector(`[data-detail="${i+1}"]`); if(d && active) d.textContent=job.stage_detail || d.textContent;
  });
  setLargeStageUI(job);
  if(job.catalog_ready && ['waiting_selection','running'].includes(job.status) && ['vehicle','map'].includes(job.asset_type)) maybeOpenCatalog(job);
  if(job.selected_variant) state.selectedVariant=job.selected_variant;
  if(job.engine_id==='VE1' && job.status==='lab_ready' && state.ve1WorkspaceShownJob!==state.jobId){ state.ve1WorkspaceShownJob=state.jobId; openVE1Workspace(state.jobId, job.selected_variant || null); }
  document.documentElement.dataset.quietProcessing = ['queued','running','processing','cooldown','waiting_selection','preparing'].includes(job.status) ? '1' : '0';
  if(els.processDetailsBtn) { els.processDetailsBtn.hidden = isVE1 || !['running','processing','cooldown','paused','waiting_selection'].includes(job.status); if(isVE1) els.processDetailsBtn.textContent='Этапы VA 2 не используются'; }
  els.pauseBtn.textContent = job.status === 'paused' ? 'Продолжить' : 'Пауза';
  if (!isVE1 && job.repair_preview && idx >= 10 && state.previewShownJob !== state.jobId) {
    state.previewShownJob = state.jobId;
    showDataModal('REPAIR PREVIEW · до исправления', job.repair_preview);
  }
  if (idx >= 1 && document.documentElement.getAttribute('data-phase') === 'preparing') setPhase('processing');
  if (state.jobId) updateSession({ stageIndex: idx, ts: Date.now() });
}

/* ══════════════════════════════════════════════════
   VEHICLE / MAP CATALOG + VE 1
══════════════════════════════════════════════════ */
function catalogPreviewUrl(jobId, rel) { return rel ? `/api/jobs/${encodeURIComponent(jobId)}/catalog-preview?path=${encodeURIComponent(rel)}` : ''; }
function renderVariantCard(jobId, item, selectedId) {
  const selected=item.id===selectedId ? 'selected' : '';
  const img=item.preview ? `<img src="${catalogPreviewUrl(jobId,item.preview)}" alt="" loading="lazy">` : `<div class="catalog-placeholder-inline"><span>PREVIEW</span><b>нет изображения</b></div>`;
  const configs=(item.configs||[]).slice(0,8).map(c=>`<button type="button" class="catalog-config-chip" data-config-path="${esc(c.path)}" data-config-name="${esc(c.name)}">${esc(c.name)}</button>`).join('');
  return `<article class="catalog-card ${selected}" data-variant-id="${esc(item.id)}"><div class="catalog-thumb">${img}<span class="catalog-brand-badge">ModForge</span></div><div class="catalog-card-main"><b>${esc(item.name)}</b><small>${item.jbeam_count?`${item.jbeam_count} JBeam`:item.map_file_count?`${item.map_file_count} файлов уровня`:'логический ресурс'}${item.has_real_preview===false?' · preview создан ModForge':''}</small>${configs?`<div class="catalog-configs"><span>Конфигурации</span>${configs}</div>`:''}</div><button type="button" class="btn small catalog-select-btn">Выбрать</button></article>`;
}
async function openCatalogPicker(jobId, initialJob=null) {
  if(state.catalogShownJob===jobId && els.modal && !els.modal.hidden) return;
  let data=initialJob?.catalog ? {catalog:initialJob.catalog,selected_variant:initialJob.selected_variant} : null;
  try { data=data||await api(`/api/jobs/${encodeURIComponent(jobId)}/catalog`,{__timeoutMs:15000}); } catch(e){ toast(String(e.message||e),'error',3500); return; }
  const catalog=data.catalog||{}; state.catalog=catalog; state.catalogShownJob=jobId; state.selectedVariant=data.selected_variant||initialJob?.selected_variant||null;
  const items=Array.isArray(catalog.items)?catalog.items:[];
  if(!items.length){ toast('В моде не найдено отдельных моделей для выбора. Продолжаем общую обработку.','info',3200); return; }
  const selectedId=state.selectedVariant?.id||'';
  openModal(`<span class="eyebrow">ПОДГОТОВКА · ${esc(String(catalog.asset_type||'ресурс').toUpperCase())}</span><h2>Выберите конкретную модель</h2><p class="modal-lead">ModForge уже разобрал архив. Здесь можно выбрать именно ту машину или карту, которую нужно менять. Превью максимально близко к логике меню выбора BeamNG; если оригинального preview нет, используется отдельная заглушка.</p><div class="catalog-toolbar"><span>${items.length} элементов</span><span class="micro">Логотип ModForge закреплён в правом верхнем углу превью.</span></div><div class="catalog-grid">${items.map(item=>renderVariantCard(jobId,item,selectedId)).join('')}</div><section class="lab-panel" id="catalogLabPanel" hidden></section>`, `<button class="btn" id="catalogContinueBtn" type="button">Продолжить без выбора</button><button class="btn primary" id="catalogConfirmBtn" type="button" disabled>Выбрать модель</button>`);
  const setActive=(item,config={})=>{state.selectedVariant={...item,...config};els.modalContent.querySelectorAll('.catalog-card').forEach(c=>c.classList.toggle('selected',c.dataset.variantId===item.id));$('catalogConfirmBtn').disabled=false;};
  els.modalContent.querySelectorAll('.catalog-card').forEach(card=>{
    const item=items.find(x=>x.id===card.dataset.variantId); if(!item)return;
    card.querySelector('.catalog-select-btn')?.addEventListener('click',()=>setActive(item,{}));
    card.addEventListener('dblclick',()=>setActive(item,{}));
    card.querySelectorAll('.catalog-config-chip').forEach(ch=>ch.addEventListener('click',()=>setActive(item,{config_path:ch.dataset.configPath,config_name:ch.dataset.configName})));
  });
  $('catalogContinueBtn').addEventListener('click',()=>{closeModal(); if(initialJob?.status==='waiting_selection') toast('Общая проверка продолжится без привязки к конкретной модели.','info',2600);});
  $('catalogConfirmBtn').addEventListener('click',async()=>{
    if(!state.selectedVariant)return;
    try{const d=await api(`/api/jobs/${encodeURIComponent(jobId)}/catalog-selection`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_variant:state.selectedVariant}),__timeoutMs:15000});state.selectedVariant=d.selected_variant;closeModal();toast(`Выбрано: ${d.selected_variant.name||d.selected_variant.id}`,'success',2600); if(initialJob?.status==='prepared'){ await startPreparedJob(); } else { await openVE1Workspace(jobId,d.selected_variant); }}
    catch(e){toast(String(e.message||e),'error',3800);}
  });
}
async function openVE1Workspace(jobId, selected) {
  if(state.taskMode!=='modify') return;
  let mats=[]; try{mats=(await api(`/api/jobs/${encodeURIComponent(jobId)}/lab/materials`,{__timeoutMs:15000})).materials||[];}catch{}
  const materialRows=mats.map(m=>`<label class="lab-material"><input type="checkbox" value="${esc(m.id)}" checked><span><b>${esc(m.label||m.name||m.id)}</b><small>${esc(m.file||'')}</small></span></label>`).join('');
  openModal(`<span class="eyebrow">VE 1 · ${esc(selected?.name||'модель')}</span><h2>Рабочее пространство Variant Engineering</h2><p class="modal-lead">Превью модели и безопасные операции находятся рядом. Стекло, фары и другие исключённые реалистичные поверхности не входят в Paint автоматически.</p><div class="lab-layout"><div><div class="lab-preview">${selected?.preview?`<img src="${catalogPreviewUrl(jobId,selected.preview)}" alt="">`: '<span>Нет preview</span>'}<span class="catalog-brand-badge">ModForge</span></div><div class="lab-selected"><b>${esc(selected?.name||'Модель')}</b><span>${esc(selected?.config_name||'Базовая конфигурация')}</span></div></div><div class="lab-controls"><section><label class="field-label">Paint · доступные детали</label><div class="lab-material-grid">${materialRows||'<div class="files-empty">Нет безопасных материалов с baseColorFactor.</div>'}</div><div class="lab-color-row"><input id="labColor" type="color" value="#f47b20"><code id="labColorHex">#F47B20</code><button class="btn small primary" id="labPaintBtn" type="button">Покрасить выбранные</button></div></section><section><label class="field-label">Физика</label><div class="lab-range"><span>Подвеска</span><input id="labSuspension" type="range" min="-70" max="70" value="0" step="1"><output id="labSuspensionOut">0%</output><button class="btn small" id="labSuspensionBtn" type="button">Применить</button></div><div class="lab-range"><span>Двигатель</span><input id="labEngine" type="range" min="-50" max="100" value="0" step="1"><output id="labEngineOut">0%</output><button class="btn small" id="labEngineBtn" type="button">Применить</button></div><div class="lab-range"><span>RPM</span><input id="labRpm" type="range" min="-40" max="60" value="0" step="1"><output id="labRpmOut">0%</output><button class="btn small" id="labRpmBtn" type="button">Применить</button></div><div class="lab-range"><span>Плавный старт</span><input id="labLaunch" type="range" min="1" max="90" value="35" step="1"><output id="labLaunchOut">35%</output><button class="btn small" id="labLaunchBtn" type="button">Применить</button></div></section><section><label class="field-label">Мини-стресс-тесты</label><div class="lab-stress-actions"><button class="btn small" id="labStressSuspension" type="button">Проверить подвеску</button><button class="btn small" id="labStressEngine" type="button">Проверить двигатель</button></div><pre class="lab-output" id="labOutput">Ожидает действия.</pre></section></div></div>`, `<button class="btn" id="labBack" type="button">Назад к моделям</button><button class="btn primary" id="labClose" type="button">Сохранить изменения</button>`);
  $('labColor')?.addEventListener('input',e=>$('labColorHex').textContent=e.target.value.toUpperCase());
  for(const id of ['labSuspension','labEngine','labRpm','labLaunch']) $(id)?.addEventListener('input',e=>$(id+'Out').textContent=`${e.target.value}%`);
  const postPhysics=async(kind,percent)=>{try{const d=await api(`/api/jobs/${encodeURIComponent(jobId)}/lab/physics`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,percent}),__timeoutMs:20000});$('labOutput').textContent=(d.issues||[]).map(x=>`${x.title}: ${x.details}`).join('\n')||'Изменение применено.';}catch(e){$('labOutput').textContent=String(e.message||e);}};
  $('labPaintBtn')?.addEventListener('click',async()=>{const ids=[...els.modalContent.querySelectorAll('.lab-material input:checked')].map(x=>x.value);try{const d=await api(`/api/jobs/${encodeURIComponent(jobId)}/lab/paint`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({material_ids:ids,hex_color:$('labColor').value}),__timeoutMs:20000});$('labOutput').textContent=`Перекрашено материалов: ${(d.changes||[]).length}`;}catch(e){$('labOutput').textContent=String(e.message||e);}});
  $('labSuspensionBtn')?.addEventListener('click',()=>postPhysics('suspension',Number($('labSuspension').value)));
  $('labEngineBtn')?.addEventListener('click',()=>postPhysics('engine',Number($('labEngine').value)));
  $('labRpmBtn')?.addEventListener('click',()=>postPhysics('rpm',Number($('labRpm').value)));
  $('labLaunchBtn')?.addEventListener('click',()=>postPhysics('launch',Number($('labLaunch').value)));
  for(const [id,kind] of [['labStressSuspension','suspension'],['labStressEngine','engine']]) $(id)?.addEventListener('click',async()=>{try{const d=await api(`/api/jobs/${encodeURIComponent(jobId)}/lab/stress`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind}),__timeoutMs:20000});$('labOutput').textContent=`Stress ${kind}: ${d.ok?'OK':'REVIEW'} · параметры: ${d.stress?.checked_parameters||0} · min: ${d.stress?.min??'—'} · max: ${d.stress?.max??'—'}\n${d.stress?.note||''}`;}catch(e){$('labOutput').textContent=String(e.message||e);}});
  $('labBack').addEventListener('click',()=>openCatalogPicker(jobId,{catalog:state.catalog,selected_variant:state.selectedVariant}));
  $('labClose').addEventListener('click',async()=>{try{const d=await api(`/api/jobs/${encodeURIComponent(jobId)}/lab/finalize`,{method:'POST',__timeoutMs:120000});closeModal();toast(`VE 1 экспортирован · ${d.name||'файл'}`,'success',3800);state.busy=false;await poll();}catch(e){$('labOutput').textContent=String(e.message||e);toast('VE 1: '+String(e.message||e),'error',4200);}});
}
function maybeOpenCatalog(job){
  if(!job?.catalog_ready) return;
  if(state.catalogShownJob===state.jobId) return;
  openCatalogPicker(state.jobId,job);
}

/* ══════════════════════════════════════════════════
   INTERFACE INFO CENTER
   Dedicated navigation: users can choose a section instead of hunting for tooltips.
══════════════════════════════════════════════════ */
const INTERFACE_INFO = {
  overview:{title:'Обзор интерфейса',body:'<p>Главный экран разделён на четыре понятные зоны: верхняя панель, выбор движка, рабочая конфигурация и состояние задачи. Важные действия остаются на виду; подробности собраны в этом центре.</p><div class="info-grid-mini"><div><b>ⓘ Интерфейс</b><span>Полная справка по каждому экрану и элементу.</span></div><div><b>VA 2</b><span>Диагностика, исправление и повторная проверка.</span></div><div><b>VE 1</b><span>Изолированное редактирование вариантов без запуска VA 2.</span></div><div><b>⋮ / Подробнее</b><span>Компактные второстепенные пояснения там, где они не нужны постоянно.</span></div></div>'},
  topbar:{title:'Верхняя панель',body:'<h3>Версия</h3><p>Показывает текущий релиз сайта. Это версия интерфейса и серверного контракта, а не версия BeamNG.drive.</p><h3>«Интерфейс»</h3><p>Открывает этот центр информации. Здесь можно выбрать нужный раздел без наведения на подсказки.</p><h3>Палитра, профиль и настройки</h3><p>Палитра меняет внешний акцент. Профиль хранит локальные предпочтения. Настройки содержат визуальные и рабочие параметры; они не изменяют правила безопасности backend.</p><h3>Быстрые действия</h3><p>Клавиатурные сокращения находятся в разделе «Быстрые действия» и не дублируются отдельными крупными кнопками.</p>'},
  engines:{title:'Переключатель движка',body:'<h3>VA 2 · Verification Architecture · 0IN-1.0</h3><p>Основной диагностический контур: вход → анализ → безопасные изменения → повторная верификация → результат.</p><h3>VE 1 · Variant Engineering · M0-D-l00</h3><p>Изолированная лаборатория: подготовка рабочего пространства → выбор варианта → точечные изменения → стресс-проверки → отдельный экспорт.</p><p><b>Важно:</b> переключение на VE 1 не вызывает проверку/исправление VA 2. У движков разные состояния, API и финализация.</p>'},
  input:{title:'Вход и загрузка',body:'<h3>Выбор файла</h3><p>Загрузка принимает ZIP, папку и поддерживаемый отдельный BeamNG-ресурс. Исходник копируется в рабочую область до обработки.</p><h3>Безопасность</h3><p>Перед распаковкой проверяются пути, символические ссылки, дубликаты, шифрование, размер, количество файлов, глубина и коэффициент сжатия.</p><h3>Большие ZIP</h3><p>Файлы свыше порога большого ресурса проходят потоковый путь без попытки держать весь файл в памяти одной операцией.</p>'},
  focus:{title:'Фокус обработки',body:'<p>Этот блок ограничивает работу реальными данными из мода: тип ресурса, конкретная модель/карта и выбранная PC-конфигурация, когда они доступны.</p><p>VA 2 использует фокус для приоритетного анализа, но не пропускает обязательные структурные проверки. VE 1 использует выбранный вариант как рабочую область.</p>'},
  request:{title:'Запрос и пожелания',body:'<p>Свободное описание помогает уточнить цель обработки, но не считается разрешением на опасное изменение. Детерминированные правила VA 2 имеют собственные ограничения и не выполняют неизвестные команды.</p><p>Для числовых изменений используйте VE 1: там проценты и области изменения задаются отдельными контролами.</p>'},
  modes:{title:'Режимы проверки VA 2',body:'<div class="info-table"><div><b>Стандартный</b><span>7 блоков · базовая диагностика и подтверждённые исправления.</span></div><div><b>Средний</b><span>11 блоков · расширенная проверка связей и типовых ошибок.</span></div><div><b>Агрессивный</b><span>15 блоков · глубокие эвристики; неоднозначные случаи остаются обозначенными для ручной проверки.</span></div></div><p>Агрессивный режим не отключает проверку безопасности архива и не превращает неизвестные данные в разрешение на произвольную запись.</p>'},
  output:{title:'Результат и имя файла',body:'<p>Префикс/суффикс результата применяется к имени выходного архива. Исходник не перезаписывается.</p><p>После завершения доступны скачивание, компактный статус, полный отчёт, Health, Diff, Repair Preview и повторный запуск.</p><p>Для VE 1 результат помечается собственным engine_id и журналом лабораторных изменений.</p>'},
  speed:{title:'Скорость и нагрузка',body:'<p>Профиль скорости означает интенсивность работы, а не гарантированный MB/s. Крупные ресурсы обрабатываются отдельным ограниченным worker-путём.</p><p>При высокой нагрузке CPU/память/диск задача переводится в <b>cooldown</b>: прогресс и рабочая копия сохраняются, показывается причина паузы, затем обработка автоматически продолжается после снижения нагрузки. Потеря задачи или файла при самом cooldown не является штатным сценарием.</p>'},
  processing:{title:'Экран обработки',body:'<h3>Что видно постоянно</h3><p>Процент, текущая операция, состояние соединения и доступное действие. Это основной минимум, поэтому тяжёлые списки этапов скрыты по умолчанию.</p><h3>«Показать этапы»</h3><p>Только по запросу раскрывается подробная шкала блоков. Это снижает постоянную DOM-нагрузку.</p><h3>Связь</h3><p>Polling использует повтор с увеличивающейся паузой при временной недоступности API и не запускает вторую копию той же задачи.</p>'},
  preparation:{title:'Предварительный осмотр после загрузки',body:'<p>Сразу после загрузки ModForge разбирает рабочую копию, строит каталог и делает read-only скан. Сам ремонт ещё не начат. Здесь можно увидеть найденные ссылки, конфигурации, потенциальные проблемы и готовность AI-трафика.</p><p>Для VA 2 это означает: сначала осмотр → затем явный запуск Repair Core. Для VE 1: осмотр → выбор варианта, если их несколько → вход в отдельную лабораторию.</p><h3>Почему это важно</h3><p>Пользователь больше не ждёт неизвестно чего: до запуска видно, что именно найдено внутри файла.</p>'},
  aiTraffic:{title:'Адаптация под AI-трафик',body:'<p>Этот пункт восстанавливает traffic metadata, нормализует <b>model</b> в PC-конфигурациях, при необходимости создаёт info-файл с Population и Config Type и генерирует vehicle groups.</p><p><b>Все найденные конфигурации</b> добавляются в отдельную traffic group. Либо можно выбрать режим <b>только выбранная машина</b>. Для экстренных машин названия вроде Police, Ambulance, EMS, Fire, Скорая и Полиция используются для определения роли <b>Police</b> или <b>Service</b> и повышенной Population.</p><p>Сирена и реакция других участников трафика зависят также от игровой traffic/navgraph-системы. ModForge не выдумывает неизвестный Lua-контроллер: он исправляет документируемую роль и metadata, а ограничение показывает отдельно в отчёте.</p>'},
  lab:{title:'Рабочее пространство VE 1',body:'<h3>Модель и материалы</h3><p>Выбор конкретной модели/варианта происходит до входа в лабораторию. Безопасные материалы доступны для цветовых изменений; стекло и другие исключённые поверхности не предлагаются как обычный Paint.</p><h3>Физические параметры</h3><p>Подвеска, двигатель, RPM и плавный старт изменяются отдельными контролами с процентами. Это VE 1-операции и они не меняют настройки VA 2.</p><h3>Мини-стресс</h3><p>Проверяет диапазоны изменённых чисел без запуска самой игры.</p><h3>Сохранить изменения</h3><p>Запускает отдельную финализацию VE 1 и scoped verification для изменённой области, после чего создаётся отдельный архив.</p>'},
  resultPanel:{title:'Карточка результата',body:'<p>После <b>Готово</b> карточка содержит короткий итог. Ссылки на подробные данные открываются по запросу, чтобы не загружать в страницу весь отчёт.</p><p><b>Health</b> показывает категории фактических находок. <b>Diff</b> сравнивает изменения. <b>Repair Preview</b> описывает запланированные изменения. <b>История</b> позволяет вернуться к сохранённой сессии или сравнению.</p>'},
  recovery:{title:'Восстановление и ошибки',body:'<h3>Рестарт backend</h3><p>Сохранённая рабочая копия позволяет восстановить незавершённое задание. Для VE 1 состояние <b>lab_ready</b> сохраняется как редактируемое рабочее пространство.</p><h3>Pause / Resume</h3><p>Пауза меняет серверное состояние той же задачи; повторное нажатие продолжает её. Это не создаёт новую задачу.</p><h3>MF-528</h3><p>Код означает смену серверного epoch после глобального сброса состояния. Браузерная локальная история не удаляется автоматически.</p><h3>MF-5xx</h3><p>Смотрите код, причину и следующий шаг отдельно. Не запускайте повторно задачу только из-за краткого сетевого предупреждения.</p>'},
  history:{title:'История и быстрые повторения',body:'<p>После скачивания результата доступна локальная история сессий. Она не является серверной учётной записью и не заменяет резервную копию модифика.</p><p>Из истории можно быстро открыть сведения о предыдущем задании, сравнение и повторную обработку, когда исходная рабочая копия ещё доступна в срок хранения.</p>'},
  shortcuts:{title:'Быстрые действия',body:'<div class="info-table"><div><kbd>Ctrl/Cmd + Shift + U</kbd><span>Открыть выбор файла.</span></div><div><kbd>Ctrl/Cmd + Shift + R</kbd><span>Запустить или повторить задачу.</span></div><div><kbd>Ctrl/Cmd + Shift + P</kbd><span>Открыть Repair Preview.</span></div><div><kbd>Ctrl/Cmd + Shift + S</kbd><span>Открыть историю сессий.</span></div><div><kbd>I</kbd><span>Открыть центр информации об интерфейсе.</span></div><div><kbd>?</kbd><span>Открыть компактную подсказку клавиш.</span></div><div><kbd>Ctrl/Cmd + Enter</kbd><span>Запустить подготовленный файл или продолжить после предварительного осмотра.</span></div><div><kbd>Esc</kbd><span>Закрыть активное окно/меню.</span></div></div>'},
  limits:{title:'Ограничения и план развития',body:'<h3>Сейчас</h3><p>Сервис не запускает BeamNG.drive для настоящего 3D-рендера и физической симуляции. Он также не может безопасно вывести неизвестную Lua-логику из файла в гарантированно корректное поведение.</p><h3>Планируется</h3><p>Более глубокая семантическая диагностика Lua, расширенный анализ сложных конфигураций и дополнительные игровые профили без ослабления безопасного режима.</p><h3>Что уже сделано</h3><p>Health, Repair Preview, Diff, Resource Inspector, Mod Doctor, Performance Scan, Safe Cleaner, Release Check, Compare, история, rollback, сохранение рабочих копий и нагрузочный guard.</p>'},
};
function openInterfaceInfo(section='overview'){
  if(!els.interfaceInfo) return;
  els.interfaceInfo.hidden=false;
  const key=INTERFACE_INFO[section]?section:'overview';
  els.interfaceInfoNav.innerHTML=Object.entries(INTERFACE_INFO).map(([id,item])=>`<button class="interface-info-nav-btn ${id===key?'active':''}" type="button" data-info-section="${id}">${esc(item.title)}</button>`).join('');
  const render=selected=>{const item=INTERFACE_INFO[selected]||INTERFACE_INFO.overview; els.interfaceInfoContent.innerHTML=`<span class="eyebrow">РАЗДЕЛ</span><h3>${esc(item.title)}</h3>${item.body}`; els.interfaceInfoNav.querySelectorAll('[data-info-section]').forEach(btn=>btn.classList.toggle('active',btn.dataset.infoSection===selected));};
  els.interfaceInfoNav.querySelectorAll('[data-info-section]').forEach(btn=>btn.addEventListener('click',()=>render(btn.dataset.infoSection)));
  render(key);
}
function closeInterfaceInfo(){ if(els.interfaceInfo) els.interfaceInfo.hidden=true; }
els.interfaceInfoTop?.addEventListener('click',()=>openInterfaceInfo());
els.interfaceInfoClose?.addEventListener('click',closeInterfaceInfo);
els.interfaceInfo?.querySelectorAll('[data-interface-close]').forEach(el=>el.addEventListener('click',closeInterfaceInfo));

/* ══════════════════════════════════════════════════
   RELEASE FLOW
══════════════════════════════════════════════════ */
function showReleaseFlow() {
  const seen = localStorage.getItem(SK.RELEASE);
  const privacy = localStorage.getItem(SK.PRIVACY) === '1';
  const guide = localStorage.getItem(SK.GUIDE) === '1';
  if (seen !== state.release) showChangelog(!privacy, !guide);
  else if (!privacy) showPrivacy(!guide);
  else if (!guide) showGuide();
}

function showChangelog(np, ng) {
  openModal(
    `<span class="eyebrow">ОБНОВЛЕНИЕ</span><h2>ModForge ${esc(state.release)}</h2>
    <p class="modal-lead">Стабильный релиз. Основные изменения текущего релиза V1 (0.61-A):</p>
    <div class="change-grid">
      <section><b>ИСПРАВЛЕНО</b><ul>
        <li>Обрыв обработки после перезапуска backend теперь восстанавливается из сохранённой исходной копии.</li>
        <li>Почтовые ошибки больше не теряются без следа: последняя ошибка SMTP видна автору.</li>
        <li>Обратная связь теперь содержит Reply-To посетителя, когда он указал email.</li>
        <li>Счётчик этапов синхронизирован с фактическими 15 этапами.</li>
      </ul></section>
      <section><b>ДОБАВЛЕНО</b><ul>
        <li>Vehicle-моды получают статическую метку ModForge без ручного добавления UI Apps.</li>
        <li>Название автомобиля помечается «ModForge», а доступные preview/thumbnail-файлы получают логотип.</li>
        <li>Кнопка «Проверить почту» для автора.</li>
      </ul></section>
      <section><b>ОСТАЛОСЬ</b><ul>
        <li>BeamNG.drive 0.39 — целевой профиль; 0.61-A — текущая версия сайта ModForge внутри V1.</li>
        <li>Консервативные и эвристические автоисправления имеют ограничения.</li>
        <li>Мод всё равно нужно проверить в самой игре.</li>
      </ul></section>
    </div>`,
    `<button class="btn primary" id="relCont" type="button">Понятно</button>`
  );
  $('relCont').addEventListener('click', () => { localStorage.setItem(SK.RELEASE, state.release); closeModal(); if (np) showPrivacy(ng); else if (ng) showGuide(); });
}

function showPrivacy(ng) {
  openModal(
    `<span class="eyebrow">ПЕРВЫЙ ВХОД</span><h2>Политика конфиденциальности</h2>
    <p>Для обработки создаётся рабочая копия задания. Завершённые задания и исходные данные хранятся до 7 дней по умолчанию, после чего автоматически удаляются. Отдельный путь хранения можно изменить настройками сервера.</p>
    <p class="micro">Обратная связь хранится отдельно; email посетителя не публикуется в открытом списке.</p>
    <p class="micro">Не загружайте личные данные или файлы, не предназначенные для обработки сервисом.</p>`,
    `<button class="btn primary" id="privAcc" type="button">Принять и продолжить</button>`
  );
  $('privAcc').addEventListener('click', () => { localStorage.setItem(SK.PRIVACY, '1'); closeModal(); if (ng) showGuide(); });
}

function showGuide() {
  openModal(
    `<span class="eyebrow">КАК ПОЛЬЗОВАТЬСЯ</span><h2>Три шага</h2>
    <ol class="guide">
      <li>Выберите VA 2 для диагностики/исправления или VE 1 для изолированного редактирования.</li>
      <li>Загрузите ZIP, папку или поддерживаемый BeamNG-файл и задайте только нужные параметры.</li>
      <li>Во время работы смотрите текущий статус; полный список этапов открывается отдельно. Центр «Интерфейс» объясняет каждый элемент.</li>
    </ol>
    <p>VA 2 не делает рискованное изменение без достаточных доказательств. VE 1 не запускает VA 2 автоматически: это самостоятельная рабочая сессия.</p>
    <p class="micro">Горячие клавиши: I — центр интерфейса, ? — быстрые действия, Esc — закрыть окно.</p>`,
    `<button class="btn primary" id="guideDone" type="button">Начать работу</button>`
  );
  $('guideDone').addEventListener('click', () => { localStorage.setItem(SK.GUIDE, '1'); closeModal(); });
}

/* ══════════════════════════════════════════════════
   REPAIR MODE
══════════════════════════════════════════════════ */
els.repairMode?.querySelectorAll('.mode-card').forEach(card=>card.addEventListener('click',()=>{state.repairMode=card.dataset.mode||'standard';localStorage.setItem('mf_repair_mode',state.repairMode);applyRepairModeUI();renderStages();saveDraft();}));
els.modeInfo?.addEventListener('click', () => {
  openModal(
    `<span class="eyebrow">РЕЖИМЫ ИСПРАВЛЕНИЯ</span><h2>Глубина ремонта</h2>
    <div class="mode-explain">
      <section><b>Стандартный · 7 блоков</b><p>Безопасные подтверждённые исправления; спорные случаи остаются в отчёте. Рекомендуется для большинства модов.</p></section>
      <section><b>Средний · 11 блоков</b><p>Добавляется более глубокий подбор ресурсов, исправление типовых ошибок конфигурации и дополнительные JBeam-проверки.</p></section>
      <section><b>Агрессивный · 15 блоков</b><p>Добавляется эвристический ремонт неоднозначных ресурсов и очевидно нулевых параметров физики с повторной проверкой.</p></section>
    </div>`,
    `<button class="btn primary" id="modeInfoClose" type="button">Понятно</button>`
  );
  $('modeInfoClose')?.addEventListener('click', closeModal);
});

/* ══════════════════════════════════════════════════
   BRAND / HOME
══════════════════════════════════════════════════ */
if (els.brand) els.brand.addEventListener('click', () => {
  saveDraft();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

/* ══════════════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════════════ */
function showSettings() {
  const profiles = {standard:'Обычная', balanced:'Быстрая', aggressive:'Максимальная'};
  openModal(
    `<span class="eyebrow">ПРОФИЛЬ</span><h2>Персонализация рабочего пространства</h2>
    <p class="modal-lead">Все параметры ниже сохраняются локально в браузере. Регистрация не требуется.</p>
    <label class="field-label">Имя</label>
    <input class="field" id="profileNameInput" maxlength="32" value="${esc(state.profile.name === 'Гость' ? '' : state.profile.name)}" placeholder="Например, Alex">
    <span class="micro">Имя показывается только в интерфейсе на этом устройстве.</span>
    <label class="field-label" style="margin-top:16px">Акцент</label>
    <div class="accent-picker" id="accentPicker">
      <button class="accent-option ${state.profile.accent==='orange'?'active':''}" data-accent-option="orange" type="button"><i></i><b>Оранжевый</b><small>ModForge</small></button>
      <button class="accent-option ${state.profile.accent==='mint'?'active':''}" data-accent-option="mint" type="button"><i></i><b>Мятный</b><small>Нейтральный</small></button>
      <button class="accent-option ${state.profile.accent==='lime'?'active':''}" data-accent-option="lime" type="button"><i></i><b>Салатовый</b><small>Свежий</small></button>
      <button class="accent-option palette-brush ${state.profile.accent==='custom'?'active':''}" data-accent-option="custom" type="button"><i class="brush-mark"></i><b>Своя палитра</b><small id="customColorLabel">${esc(state.profile.customColor || '#f47b20')}</small></button>
    </div>
    <div class="custom-color-row"><label for="customAccentColorInput">Свой цвет</label><input id="customAccentColorInput" type="color" value="${esc(state.profile.customColor || '#f47b20')}" title="Открыть палитру"><code id="customAccentHex">${esc((state.profile.customColor || '#f47b20').toUpperCase())}</code><span>Кисть открывает системную палитру и цвет применяется ко всему интерфейсу.</span></div>
    <label class="field-label" style="margin-top:16px">Плотность интерфейса</label>
    <div class="segmented" id="densityPicker">
      <button class="segment ${state.profile.density==='comfortable'?'active':''}" data-density-option="comfortable" type="button">Комфортная</button>
      <button class="segment ${state.profile.density==='compact'?'active':''}" data-density-option="compact" type="button">Компактная</button>
    </div>
    <label class="field-label" style="margin-top:16px">Профиль интерфейса</label>
    <div class="ui-performance-grid">${Object.entries(UI_PERFORMANCE).map(([key,val])=>`<button class="ui-performance-card ${state.profile.uiPerformance===key?'active':''}" data-ui-performance="${key}" type="button"><strong>${val.label}</strong><small>${val.desc}</small></button>`).join('')}</div>
    <label class="toggle-row"><input id="reducedMotionInput" type="checkbox" ${state.profile.reducedMotion?'checked':''}><span><b>Полностью отключить анимации</b><small>Останавливает визуальные переходы интерфейса. Обработка файлов не меняется.</small></span></label>
    <hr class="settings-divider">
    <span class="eyebrow">РЕЗУЛЬТАТ</span>
    <label class="field-label">Суффикс результата</label>
    <input class="field" id="suffixInput" maxlength="48" value="${esc(state.suffix)}">
    <span class="micro">FIXED → CLEAN → REPAIRED или любое своё.</span>
    <label class="field-label" style="margin-top:16px">Скорость обработки и обмена</label>
    <div class="network-modal-grid">
      <button class="network-card ${state.processingSpeed==='standard'?'active':''}" data-modal-speed="standard" type="button"><strong>Стандарт</strong><span>Обычная</span><small>меньше фоновых запросов</small></button>
      <button class="network-card ${state.processingSpeed==='balanced'?'active':''}" data-modal-speed="balanced" type="button"><strong>Быстрее</strong><span>Приоритет скорости</span><small>больше обработки и обмена</small></button>
      <button class="network-card ${state.processingSpeed==='aggressive'?'active':''}" data-modal-speed="aggressive" type="button"><strong>Агрессивно быстрее</strong><span>Максимум</span><small>выше нагрузка в пределах хостинга</small></button>
    </div>`,
    `<button class="btn" id="sCancel" type="button">Отмена</button><button class="btn primary" id="sSave" type="button">Сохранить</button>`
  );
  let chosen = state.processingSpeed;
  let accent = state.profile.accent;
  let customColor = state.profile.customColor || '#f47b20';
  let density = state.profile.density;
  let uiPerformance = state.profile.uiPerformance || 'default';
  els.modalContent.querySelectorAll('[data-modal-speed]').forEach(btn=>btn.addEventListener('click',()=>{chosen=btn.dataset.modalSpeed;els.modalContent.querySelectorAll('[data-modal-speed]').forEach(x=>x.classList.toggle('active',x===btn));}));
  const customInput = $('customAccentColorInput');
  customInput?.addEventListener('input', e => { customColor = e.target.value; accent='custom'; $('customAccentHex').textContent=customColor.toUpperCase(); $('customColorLabel').textContent=customColor.toUpperCase(); els.modalContent.querySelectorAll('[data-accent-option]').forEach(x=>x.classList.toggle('active', x.dataset.accentOption==='custom')); });
  els.modalContent.querySelectorAll('[data-accent-option]').forEach(btn=>btn.addEventListener('click',()=>{accent=btn.dataset.accentOption;els.modalContent.querySelectorAll('[data-accent-option]').forEach(x=>x.classList.toggle('active',x===btn)); if(accent==='custom') customInput?.click();}));
  els.modalContent.querySelectorAll('[data-density-option]').forEach(btn=>btn.addEventListener('click',()=>{density=btn.dataset.densityOption;els.modalContent.querySelectorAll('[data-density-option]').forEach(x=>x.classList.toggle('active',x===btn));}));
  els.modalContent.querySelectorAll('[data-ui-performance]').forEach(btn=>btn.addEventListener('click',()=>{uiPerformance=btn.dataset.uiPerformance;els.modalContent.querySelectorAll('[data-ui-performance]').forEach(x=>x.classList.toggle('active',x===btn));}));
  $('sCancel').addEventListener('click', closeModal);
  $('sSave').addEventListener('click', () => {
    const typedName = $('profileNameInput').value.trim().replace(/\s+/g,' ');
    state.profile.name = typedName.slice(0,32) || 'Гость';
    state.profile.accent = accent;
    state.profile.customColor = /^#[0-9a-fA-F]{6}$/.test(customColor) ? customColor : '#f47b20';
    state.profile.density = density;
    state.profile.reducedMotion = !!$('reducedMotionInput').checked;
    state.profile.uiPerformance = Object.keys(UI_PERFORMANCE).includes(uiPerformance) ? uiPerformance : 'default';
    state.suffix = $('suffixInput').value.trim() || 'FIXED';
    state.processingSpeed = chosen;
    localStorage.setItem(SK.SUFFIX, state.suffix);
    localStorage.setItem('mf_repair_mode', state.repairMode);
    localStorage.setItem('mf_processing_speed', state.processingSpeed);
    saveProfile();
    els.suffixPreview.textContent = state.suffix;
    updateNetworkUI();
    applyProfile();
    saveDraft();
    closeModal();
    toast(`Профиль сохранён · ${state.profile.name === 'Гость' ? 'гость' : state.profile.name}`, 'success', 2500);
  });
}

function showPalette(){
  let accent=state.profile.accent;
  let customColor=state.profile.customColor || '#f47b20';
  const quick=[['orange','Оранжевый','ModForge','#f47b20'],['mint','Мятный','Нейтральный','#67c7a0'],['lime','Салатовый','Свежий','#a8d85b']];
  openModal(`<span class="eyebrow">ПАЛИТРА</span><h2>Цвет интерфейса</h2><p class="modal-lead">Акцент меняется глобально: кнопки, фокусы, прогресс, карточки, фоновые эффекты и состояния.</p><div class="accent-picker palette-large">${quick.map(x=>`<button class="accent-option ${accent===x[0]?'active':''}" data-palette-accent="${x[0]}" type="button"><i></i><b>${x[1]}</b><small>${x[2]}</small></button>`).join('')}<button class="accent-option palette-brush ${accent==='custom'?'active':''}" data-palette-accent="custom" type="button"><i class="brush-mark"></i><b>Своя палитра</b><small>${esc(customColor.toUpperCase())}</small></button></div><div class="custom-color-row palette-custom-row"><label for="paletteColorInput">Свой цвет</label><input id="paletteColorInput" type="color" value="${esc(customColor)}"><code id="paletteColorHex">${esc(customColor.toUpperCase())}</code><span>Можно выбрать любой цвет.</span></div>`, `<button class="btn" id="paletteCancel" type="button">Закрыть</button><button class="btn primary" id="paletteSave" type="button">Применить</button>`);
  const input=$('paletteColorInput');
  input?.addEventListener('input',e=>{customColor=e.target.value;accent='custom';$('paletteColorHex').textContent=customColor.toUpperCase();els.modalContent.querySelectorAll('[data-palette-accent]').forEach(x=>x.classList.toggle('active',x.dataset.paletteAccent==='custom'));});
  els.modalContent.querySelectorAll('[data-palette-accent]').forEach(btn=>btn.addEventListener('click',()=>{accent=btn.dataset.paletteAccent;els.modalContent.querySelectorAll('[data-palette-accent]').forEach(x=>x.classList.toggle('active',x===btn));if(accent==='custom')input?.click();}));
  $('paletteCancel').addEventListener('click',closeModal);
  $('paletteSave').addEventListener('click',()=>{state.profile.accent=accent;state.profile.customColor=/^#[0-9a-fA-F]{6}$/.test(customColor)?customColor:'#f47b20';saveProfile();applyProfile();saveDraft();closeModal();toast('Палитра применена глобально.','success',2200);});
}

els.settingsBtn.addEventListener('click', showSettings);
els.settingsTop.addEventListener('click', showSettings);
els.paletteTop?.addEventListener('click', showPalette);
els.profileTop?.addEventListener('click', showSettings);
els.heroProfileBtn?.addEventListener('click', showSettings);
els.profileEditBtn?.addEventListener('click', showSettings);

/* ══════════════════════════════════════════════════
   FILE PICKER STATE
══════════════════════════════════════════════════ */
function updateNetworkUI(){
  const map={standard:'Обычная',balanced:'Быстрая',aggressive:'Максимальная'};
  if(!map[state.processingSpeed]) state.processingSpeed='standard';
  els.networkPresets?.querySelectorAll('[data-network]').forEach(btn=>btn.classList.toggle('active',btn.dataset.network===state.processingSpeed));
  const active=els.networkPresets?.querySelector(`[data-network="${state.processingSpeed}"]`);
  const label=active?.querySelector('span')?.textContent || map[state.processingSpeed];
  if(els.networkLimitLabel) els.networkLimitLabel.textContent = label;
  if(els.networkUsageLabel) els.networkUsageLabel.textContent = state.processingIntensity || 'обычная';
}

els.networkPresets?.querySelectorAll('[data-network]').forEach(btn=>btn.addEventListener('click', () => {
  state.processingSpeed = btn.dataset.network || 'standard';
  localStorage.setItem('mf_processing_speed', state.processingSpeed);
  updateNetworkUI(); saveDraft();
}));


function applyRepairModeUI(){ els.repairMode?.querySelectorAll('.mode-card').forEach(c=>c.classList.toggle('active',c.dataset.mode===state.repairMode)); }
function detectVehicle(files){ const names=files.map(f=>(f.webkitRelativePath||f.name||'').replace(/\\/g,'/')); const hit=names.find(n=>/(^|\/)vehicles\/[^\/]+\//i.test(n)); if(!hit||!els.vehicleDetect) return; const m=hit.match(/(?:^|\/)vehicles\/([^\/]+)\//i); els.vehicleDetect.hidden=false; els.vehicleDetectTitle.textContent=`Автомобильный мод: ${m?m[1]:'обнаружен'}`; }

function setPickerVisual(kind = '') {
  const map = { zip: 'zipBtn', folder: 'folderBtn', single: 'fileBtn' };
  ['zipBtn','folderBtn','fileBtn'].forEach(id => {
    const btn = els[id];
    if (btn) btn.classList.toggle('selected', map[kind] === id && state.files.length > 0);
  });
}

function getAssetDescription(key){return ({vehicle:'Автомобильный мод с JBeam, кузовом, стёклами, светом и колёсами.',map:'Карта, уровень или трасса с окружением, terrain и сценами.',prop:'Отдельный объект, декорация, трафик или физический проп.',texture:'Набор текстур, материалов, PBR-карт или декалей.',sound:'Аудиоресурсы: двигатель, окружение, UI и эффекты.',other:'Другой BeamNG-ресурс; движок определит структуру автоматически.'}[key]||'');}
function updateSelection() {
  updateNetworkUI();
  const total = state.files.reduce((s, f) => s + f.size, 0);
  detectVehicle(state.files);
  els.selection.hidden = false;
  const type = state.kind === 'zip' ? 'ZIP' : state.kind === 'folder' ? 'Папка' : 'Файл';
  setPickerVisual(state.kind);
  saveDraft();
  const typeLabel = ASSET_TYPES.find(x => x[0] === state.assetType)?.[1] || 'Тип не указан';
  const subtypeLabel = (ASSET_SUBTYPES[state.assetType]||[]).find(x=>x[0]===state.assetSubtype)?.[1] || '';
  const scopeCount=state.repairExclusions.size + state.excludedFiles.length;
  const activeRepairCount=state.repairActions.size;
  const usual = loadUsualSettings();
  const showUsual = !!usual && !sameUsualSettings(usual.settings, usualSettingsSnapshot());
  els.selection.innerHTML = `<div class="selection-row"><div class="selection-main"><strong>${esc(state.sourceName)}</strong><span>${type} · ${state.files.length} объектов · ${bytes(total)}</span><small>${esc(typeLabel)}${subtypeLabel?` · ${esc(subtypeLabel)}`:''} · ${activeRepairCount} областей ремонта${scopeCount?` · исключений: ${scopeCount}`:''}</small></div><div class="selection-actions"><button class="selection-more" id="selectionMore" type="button" aria-label="Выбор типа" title="Тип ресурса">▼</button><button class="selection-scope" id="selectionScope" type="button" title="Что можно и нельзя менять">Области</button></div></div>${state.assetType?`<div class="selection-description"><b>${esc(typeLabel)}${subtypeLabel?` · ${esc(subtypeLabel)}`:''}</b><span>${esc(getAssetDescription(state.assetType))}</span></div>`:''}<div class="usual-settings" id="usualSettingsPrompt" ${showUsual ? '' : 'hidden'}><div><b>Ваши обычные настройки</b><span data-usual-summary>${showUsual ? esc(`Обычно вы выбираете: ${settingsLabel(usual.settings)}.`) : ''}</span><small data-usual-count>${showUsual ? `${Math.max(usual.runs, usual.samples)} запусков` : ''}</small></div><button class="btn small" id="applyUsualSettings" type="button">Применить мои</button></div>`;
  $('selectionMore')?.addEventListener('click', openSelectionMenu);
  $('selectionScope')?.addEventListener('click', openRepairScopeMenu);
  $('applyUsualSettings')?.addEventListener('click', applyUsualSettings);
  const valid = state.files.length > 0 && total <= 2 * 1024 * 1024 * 1024;
  els.startBtn.disabled = !valid || state.busy;
  setReady(valid ? 'Готово к проверке' : 'Нужен поддерживаемый файл', 'Перед запуском ModForge проверит связь с backend.');
  if (valid) checkFileAgainstSession(state.files);
}

function openSelectionMenu() {
  const typeButtons = ASSET_TYPES.map(([key,label]) => `<button class="choice-card ${state.assetType===key?'active':''}" data-asset-type="${key}" type="button"><b>${esc(label)}</b><small>${esc(getAssetDescription(key))}</small></button>`).join('');
  const problems = PROBLEM_HINTS.map(([key,label]) => `<button class="hint-chip ${state.problemHints.has(key)?'active':''}" data-problem-hint="${key}" type="button">${esc(label)}</button>`).join('');
  openModal(`<span class="eyebrow">КОНТЕКСТ</span><h2>Что именно загружено?</h2><p class="modal-lead">Выберите тип и более точное назначение. Это помогает движку выбрать релевантные проверки, но не отключает остальные проверки.</p><label class="field-label">1 · Основной тип</label><div class="choice-grid">${typeButtons}</div><div class="asset-subtype-box"><label class="field-label">2 · Подробный тип</label><select class="field" id="assetSubtypeSelect"><option value="">Выберите точнее…</option>${(ASSET_SUBTYPES[state.assetType]||[]).map(([k,v])=>`<option value="${k}" ${state.assetSubtype===k?'selected':''}>${esc(v)}</option>`).join('')}</select><small id="assetSubtypeHelp" class="micro">Например: машина → микроавтобус, автобус, самолёт или вертолёт.</small></div><label class="field-label" style="margin-top:18px">3 · Что уже известно о проблеме</label><div class="hint-grid">${problems}</div><div id="problemOtherWrap" ${state.problemHints.has('other')?'':'hidden'} style="margin-top:12px"><label class="field-label">Описание</label><textarea id="problemOther" class="field" maxlength="2000" placeholder="Например: старые зеркала смотрят вперёд, а не назад.">${esc(state.problemOther||'')}</textarea></div>`, `<button class="btn" id="selectionMetaClear" type="button">Очистить</button><button class="btn primary" id="selectionMetaSave" type="button">Готово</button>`);
  const refreshSubtype=()=>{const select=$('assetSubtypeSelect');if(!select)return;select.innerHTML=`<option value="">Выберите точнее…</option>${(ASSET_SUBTYPES[state.assetType]||[]).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('')}`;};
  els.modalContent.querySelectorAll('[data-asset-type]').forEach(btn=>btn.addEventListener('click',()=>{ state.assetType=btn.dataset.assetType||''; state.assetSubtype=''; els.modalContent.querySelectorAll('[data-asset-type]').forEach(x=>x.classList.toggle('active',x===btn)); refreshSubtype(); }));
  $('assetSubtypeSelect').addEventListener('change',e=>state.assetSubtype=e.target.value||'');
  els.modalContent.querySelectorAll('[data-problem-hint]').forEach(btn=>btn.addEventListener('click',()=>{ const key=btn.dataset.problemHint; if(state.problemHints.has(key)){state.problemHints.delete(key);btn.classList.remove('active')}else{state.problemHints.add(key);btn.classList.add('active')} $('problemOtherWrap').hidden=!state.problemHints.has('other'); }));
  $('selectionMetaClear').addEventListener('click',()=>{ state.assetType='';state.assetSubtype='';state.problemHints.clear();state.problemOther='';saveDraft();closeModal();updateSelection(); });
  $('selectionMetaSave').addEventListener('click',()=>{ state.problemOther=String($('problemOther')?.value||'').trim().slice(0,2000);if(state.problemOther)state.problemHints.add('other');saveDraft();closeModal();updateSelection(); });
}

function openRepairScopeMenu(){
  const actions=REPAIR_ACTIONS.map(([k,v])=>`<label class="scope-check"><input type="checkbox" data-repair-action="${k}" ${state.repairActions.has(k)?'checked':''}><span><b>${esc(v)}</b><small>Разрешить этой области вносить изменения.</small></span></label>`).join('');
  const exclusions=REPAIR_EXCLUSIONS.map(([k,v])=>`<label class="scope-check exclusion"><input type="checkbox" data-repair-exclusion="${k}" ${state.repairExclusions.has(k)?'checked':''}><span><b>${esc(v)}</b><small>Приоритетный запрет: детектор может сообщить о проблеме, но файл не меняется.</small></span></label>`).join('');
  openModal(`<span class="eyebrow">ОБЛАСТИ ИЗМЕНЕНИЙ</span><h2>Что трогать, а что оставить</h2><p class="modal-lead">Проверка продолжается по всему модулю, но изменения применяются только в разрешённых областях. Исключения имеют более высокий приоритет.</p><div class="scope-ai-box"><label class="field-label">Охват AI-трафика</label><label class="scope-radio"><input type="radio" name="aiTrafficScope" value="all" ${state.aiTrafficScope==='all'?'checked':''}><span><b>Все найденные конфигурации</b><small>Подготовить весь мод для traffic pool.</small></span></label><label class="scope-radio"><input type="radio" name="aiTrafficScope" value="target" ${state.aiTrafficScope==='target'?'checked':''}><span><b>Только выбранная машина</b><small>Для VE 1 — выбранный вариант; для VA 2 используется первый однозначный кандидат.</small></span></label></div><label class="field-label">Разрешить исправления</label><div class="scope-grid">${actions}</div><label class="field-label" style="margin-top:18px">Не трогать</label><div class="scope-grid">${exclusions}</div><label class="field-label" style="margin-top:18px">Файлы полностью исключить</label><textarea class="field scope-files" id="excludedFilesInput" maxlength="8000" placeholder="По одному пути или шаблону на строку. Например:
vehicles/mycar/mirrors.jbeam
vehicles/mycar/*.materials.json">${esc(state.excludedFiles.join('\n'))}</textarea><small class="micro">Это не скрывает файл из проверки: файл останется доступен для диагностики, но ModForge не будет его менять.</small>`, `<button class="btn" id="scopeAllOff" type="button">Только диагностика</button><button class="btn primary" id="scopeSave" type="button">Сохранить области</button>`);
  $('scopeAllOff').addEventListener('click',()=>{REPAIR_ACTIONS.forEach(([k])=>state.repairActions.delete(k));els.modalContent.querySelectorAll('[data-repair-action]').forEach(x=>x.checked=false);});
  $('scopeSave').addEventListener('click',()=>{state.repairActions=new Set([...els.modalContent.querySelectorAll('[data-repair-action]:checked')].map(x=>x.dataset.repairAction));state.repairExclusions=new Set([...els.modalContent.querySelectorAll('[data-repair-exclusion]:checked')].map(x=>x.dataset.repairExclusion));state.aiTrafficScope=els.modalContent.querySelector('[name=aiTrafficScope]:checked')?.value==='target'?'target':'all';state.excludedFiles=String($('excludedFilesInput')?.value||'').split(/\r?\n/).map(x=>x.trim()).filter(Boolean).slice(0,100);if(!state.repairActions.size)toast('Все изменения отключены: будет выполнена только диагностика.','info',2600);saveDraft();closeModal();updateSelection();});
}

function choose(files, kind, name) {
  state.files = Array.from(files || []);
  state.kind = kind;
  state.sourceName = name || state.files[0]?.name || 'beamng_resource';
  updateSelection();
}

els.zipBtn.addEventListener('click', () => els.zipInput.click());
els.folderBtn.addEventListener('click', () => els.folderInput.click());
els.fileBtn.addEventListener('click', () => els.fileInput.click());
els.zipInput.addEventListener('change', e => choose(e.target.files, 'zip', e.target.files[0]?.name));
els.folderInput.addEventListener('change', e => choose(e.target.files, 'folder', (e.target.files[0]?.webkitRelativePath || '').split('/')[0] || 'beamng_mod'));
els.fileInput.addEventListener('change', e => choose(e.target.files, 'single', e.target.files[0]?.name));

['dragenter','dragover'].forEach(t => els.dropzone.addEventListener(t, e => { e.preventDefault(); els.dropzone.classList.add('drag'); }));
['dragleave','drop'].forEach(t => els.dropzone.addEventListener(t, e => { e.preventDefault(); els.dropzone.classList.remove('drag'); }));
els.dropzone.addEventListener('drop', e => {
  const fs = Array.from(e.dataTransfer.files);
  if (fs.length === 1 && fs[0].name.toLowerCase().endsWith('.zip')) choose(fs, 'zip', fs[0].name);
  else if (fs.length === 1) choose(fs, 'single', fs[0].name);
  else { els.selection.hidden = false; els.selection.innerHTML = '<b>Набор файлов</b><span>Для нескольких файлов используйте выбор папки.</span>'; }
});

/* ══════════════════════════════════════════════════
   PRIORITY CHIPS
══════════════════════════════════════════════════ */
els.priorityChips.querySelectorAll('.chip').forEach(b => b.addEventListener('click', () => {
  const p = b.dataset.priority;
  if (p === 'all') { state.priority = new Set(['all']); els.priorityChips.querySelectorAll('.chip').forEach(x => x.classList.toggle('active', x === b)); return; }
  state.priority.delete('all');
  els.priorityChips.querySelector('[data-priority="all"]').classList.remove('active');
  if (state.priority.has(p)) { state.priority.delete(p); b.classList.remove('active'); } else { state.priority.add(p); b.classList.add('active'); }
  saveDraft();
  updateRequestPreview();
}));

els.outputType?.addEventListener('change', saveDraft);
els.wishes?.addEventListener('input', saveDraft);

function applyTaskModeUI() {
  state.taskMode = state.taskMode === 'modify' ? 'modify' : 'repair';
  localStorage.setItem('mf_task_mode', state.taskMode);
  els.taskMode?.querySelectorAll('.workflow-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.task === state.taskMode));
  if (els.modLab) els.modLab.hidden = state.taskMode !== 'modify';
  if (els.repairConfig) els.repairConfig.hidden = state.taskMode === 'modify';
  if (els.wishesBox) els.wishesBox.hidden = state.taskMode === 'modify';
  if (els.startLabel) els.startLabel.textContent = state.taskMode === 'modify' ? 'Запустить VE 1' : 'Запустить VA 2';
  updateRequestPreview();
}

function updateRequestPreview() {
  if (!els.requestPreview) return;
  if (state.taskMode === 'modify') {
    els.requestPreview.innerHTML = '';
    return;
  }
  const labels = {textures:'Текстуры',glass:'Стекло',jbeam:'JBeam',lighting:'Освещение',configs:'Конфигурации',wheels:'Колёса',sounds:'Звуки',materials:'Материалы',all:'Полная проверка'};
  const selected = [...state.priority].map(x => labels[x]).filter(Boolean);
  const text = els.wishes?.value?.trim();
  els.requestPreview.innerHTML = selected.length || text ? `<span>${esc(selected.length ? 'Сначала: ' + selected.join(' · ') : 'Сначала: автоматически по тексту')}</span>${text ? `<span class="preview-text">${esc(text.slice(0,180))}</span>` : ''}` : '<span>Пока ничего не выбрано — после загрузки будет полная проверка типовых проблем.</span>';
}

els.taskMode?.querySelectorAll('.workflow-tab').forEach(tab => tab.addEventListener('click', () => {
  state.taskMode = tab.dataset.task === 'modify' ? 'modify' : 'repair';
  applyTaskModeUI();
  saveDraft();
  if (state.taskMode === 'modify' && state.jobId && state.lastStatusJob?.engine_id === 'VE1' && state.lastStatusJob?.status === 'lab_ready') {
    state.ve1WorkspaceShownJob = state.jobId;
    openVE1Workspace(state.jobId, state.lastStatusJob.selected_variant || state.selectedVariant || null);
  } else if (state.taskMode === 'repair' && state.lastStatusJob?.engine_id === 'VE1' && !els.interfaceInfo?.hidden) {
    closeInterfaceInfo();
  }
}));
els.modShortcuts?.querySelectorAll('[data-mod-template]').forEach(btn => btn.addEventListener('click', () => {
  if (!els.modRequest) return;
  const t = btn.dataset.modTemplate || '';
  els.modRequest.value = els.modRequest.value.trim() ? `${els.modRequest.value.trim()} ${t}` : t;
  saveDraft();
}));
els.wishes?.addEventListener('input', () => { saveDraft(); updateRequestPreview(); });
els.modRequest?.addEventListener('input', saveDraft);


/* ══════════════════════════════════════════════════
   LOCAL SESSION HISTORY
   A session is added only after the result download
   has been successfully opened.
══════════════════════════════════════════════════ */
function loadHistory() {
  try {
    const data = JSON.parse(localStorage.getItem(SK.HISTORY) || '[]');
    state.history = Array.isArray(data) ? data.filter(x => x && x.jobId).slice(0, 40) : [];
  } catch { state.history = []; }
  renderHistory();
}
function saveHistory() {
  try { localStorage.setItem(SK.HISTORY, JSON.stringify(state.history.slice(0, 40))); } catch {}
  updateHistoryButton();
}
function updateHistoryButton() {
  if (els.historyTop) els.historyTop.hidden = !state.history.length;
}
function renderHistory() {
  if (!els.historyList) return;
  updateHistoryButton();
  if (!state.history.length) {
    els.historyList.innerHTML = '<div class="history-empty"><span class="history-empty-icon">▦</span><b>Пока нет скачанных сессий</b><small>После первой успешно начатой загрузки результата здесь появится номер сессии.</small></div>';
    return;
  }
  els.historyList.innerHTML = state.history.map((x, idx) => {
    const n = Number(x.sessionNo || (state.history.length - idx));
    const status = x.status === 'reset' ? 'Восстановление' : 'Скачано';
    const cls = x.status === 'reset' ? 'reset' : 'success';
    return `<button class="history-item" data-session-index="${idx}" type="button"><span class="history-number">#${n}</span><span class="history-main"><b>${esc(x.sourceName || 'Без имени')}</b><small>${esc(x.jobId.slice(0,12))} · ${esc(new Date(x.ts || Date.now()).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}))}</small></span><span class="history-status ${cls}">${status}</span></button>`;
  }).join('');
  els.historyList.querySelectorAll('[data-session-index]').forEach(btn => btn.addEventListener('click', () => openHistorySession(Number(btn.dataset.sessionIndex))));
}
function openHistoryDrawer() {
  if (!els.historyDrawer) return;
  loadHistory();
  els.historyDrawer.hidden = false;
  document.body.classList.add('history-open');
  setTimeout(() => els.historyDrawer.querySelector('[data-history-close]')?.focus(), 0);
}
function closeHistoryDrawer() {
  if (!els.historyDrawer) return;
  els.historyDrawer.hidden = true;
  document.body.classList.remove('history-open');
}
function recordSessionHistory() {
  if (!state.jobId) return;
  const already = state.history.find(x => x.jobId === state.jobId);
  if (already) { already.status = 'downloaded'; already.downloadName = state.downloadName || already.downloadName; already.ts = Date.now(); saveHistory(); return; }
  const nextNo = state.history.reduce((m, x) => Math.max(m, Number(x.sessionNo) || 0), 0) + 1;
  state.history.unshift({
    sessionNo: nextNo,
    jobId: state.jobId,
    sourceName: state.sourceName || loadLastJob()?.sourceName || 'beamng_resource',
    kind: state.kind,
    ts: Date.now(),
    status: 'downloaded',
    downloadName: state.downloadName || '',
    serverEpoch: state.serverEpoch || localStorage.getItem(SK.STATE_EPOCH) || '',
  });
  saveHistory();
  toast(`Сессия #${nextNo} сохранена в истории.`, 'success', 2200);
}
async function openHistorySession(index) {
  const item = state.history[index];
  if (!item) return;
  closeHistoryDrawer();
  state.jobId = item.jobId;
  state.sourceName = item.sourceName || '';
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(item.jobId)}`);
    if (job.status === 'done') {
      const report = await api(`/api/jobs/${encodeURIComponent(item.jobId)}/report`, { __timeoutMs: RESULT_TIMEOUT_MS });
      renderResult(report);
      toast(`Сессия #${item.sessionNo} открыта.`, 'success', 2200);
      return;
    }
    throw new Error(job.error || `MF-409: сессия сейчас имеет состояние «${job.status}».`);
  } catch (e) {
    const code = normalizeErrorCode(e.message);
    if (code === 'MF-404') {
      item.status = 'reset'; saveHistory(); renderHistory();
      showError(`MF-528: Сессия #${item.sessionNo} больше не найдена после сброса серверных данных. Локальная запись сохранена для восстановления.`);
    } else {
      showError(e.message);
    }
  }
}

function showQuickHelp() {
  if (!els.quickHelp) return;
  els.quickHelp.hidden = false;
  document.body.classList.add('quick-help-open');
}
function closeQuickHelp() {
  if (!els.quickHelp) return;
  els.quickHelp.hidden = true;
  document.body.classList.remove('quick-help-open');
}

/* ══════════════════════════════════════════════════
   RESET UI
══════════════════════════════════════════════════ */
function resetUI() {
  document.body.classList.remove('critical-error-active','offline-error-active');
  closeHistoryDrawer();
  closeQuickHelp();
  if (state.pollTimer) clearTimeout(state.pollTimer);
  if (state.uploadXhr) { state.uploadXhr.abort(); state.uploadXhr = null; }
  state.pollTimer = null; state.pollInFlight = false; state.lastStatusJob = null; state.preparedJob = null; state.preparation = null; state.jobId = null; state.ve1WorkspaceShownJob = null; state.paused = false; clearConnectionWarningTimer(); state.pausePending = false; state.filesPending = false;
  state.files = []; state.kind = ''; state.sourceName = ''; state.assetType = ''; state.problemHints = new Set(); state.problemOther = ''; state.largeStageVisible = false; state.busy = false; state.metricsRecordedJob = null; state.errorCode = ''; state.connectionStall = false; state.resetDetected = false;
  els.zipInput.value = ''; els.folderInput.value = ''; els.fileInput.value = '';
  els.selection.hidden = true;
  setPickerVisual('');
  els.startBtn.disabled = true;
  els.startBtn.classList.remove('loading','success','error');
  els.startLabel.textContent = state.taskMode === 'modify' ? 'Запустить VE 1' : 'Запустить VA 2';
  els.startSpinner.style.display = 'none';
  els.process.hidden = true;
  els.result.hidden = true;
  els.resultMark.className = 'result-symbol';
  els.restartJobBtn.hidden = true;
  els.resultFileNote.textContent = '';
  state.downloadUrl = null;
  state.downloadName = null;
  state.previewShownJob = null;
  els.dropTitle.textContent = 'Выберите то, что хотите проверить';
  els.dropSub.textContent = 'ZIP-архив, папка мода или отдельный BeamNG-файл.';
  setReady('Ожидается файл', 'Перед запуском ModForge проверит связь с backend.');
  applyTaskModeUI();
  setPhase('idle');
  renderStages();
  hideGame();
  setTaskActivity(false, 0);
  clearSession();
}

els.clearBtn.addEventListener('click', resetUI);
if (els.newJobBtn) els.newJobBtn.addEventListener('click', resetUI);

/* ══════════════════════════════════════════════════
   BEGIN VISUAL (loading state)
══════════════════════════════════════════════════ */
function beginVisual() {
  state.busy = true;
  els.startBtn.disabled = true;
  els.startBtn.classList.add('loading');
  els.startLabel.textContent = 'Подготавливаем…';
  els.startSpinner.style.display = 'inline-block';
  els.process.hidden = false;
  els.result.hidden = true;
  els.restartJobBtn.hidden = true;
  els.resultFileNote.textContent = '';
  els.progressBar.style.width = '0%';
  els.overallPct.textContent = '0%';
  els.stageCount.textContent = `0 / ${state.stages.length || 0}`;
  els.progressState.textContent = 'Проверяем связь с backend…';
  els.eta.textContent = 'Подключение…';
}

/* ══════════════════════════════════════════════════
   START UPLOAD
══════════════════════════════════════════════════ */
function renderPreparation(job) {
  if (!els.preparationPanel) return;
  const prep = job.preparation || {}; state.preparation = prep; state.preparedJob = job;
  els.preparationPanel.hidden = false;
  els.preparationState.textContent = job.task_mode === 'modify' ? 'VE 1 · ГОТОВО' : 'VA 2 · ГОТОВО';
  els.preparationTitle.textContent = job.task_mode === 'modify' ? 'Файл разобран — VE 1 ещё не запущен' : 'Файл разобран — VA 2 ещё не запущен';
  els.preparationMeta.textContent = `${bytes(job.uploaded_bytes||0)} загружено · ${Number(prep.files||job.source_file_count||0)} файлов · ${bytes(prep.unpacked_bytes||job.unpacked_bytes||0)} в рабочей копии`;
  const warn = Number(prep.warning_count||0);
  els.preparationSummary.textContent = `${Number(prep.finding_count||0)} находок · ${warn} требуют внимания`;
  els.preparationSummarySub.textContent = prep.catalog_count ? `${prep.catalog_count} вариантов в каталоге` : 'Каталог не выделяет отдельные варианты';
  const ai = prep.ai_traffic || {};
  els.preparationAi.textContent = ai.enabled ? (warn ? 'AI-трафик подготовлен к ремонту' : 'AI-трафик выглядит готовым') : 'Адаптация отключена';
  els.preparationAiSub.textContent = ai.hint || (ai.enabled ? 'Будут нормализованы роли, Population и vehicle groups.' : 'Можно включить её в «Области изменений».');
  els.preparationNext.textContent = job.task_mode === 'modify' && job.selection_required ? 'Выбрать модель' : 'Запускать движок';
  const findings = Array.isArray(prep.findings) ? prep.findings : [];
  els.preparationFindings.innerHTML = findings.slice(0,6).map(x => `<div class="preparation-finding ${esc(x.level||'info')}"><span>${x.level==='warning'?'!':x.level==='ok'?'✓':'•'}</span><div><b>${esc(x.title||'Найдено')}</b><small>${esc(x.details||'')}</small></div></div>`).join('') || '<div class="preparation-empty">Специфических находок не обнаружено. Полный движок всё равно выполнит итоговую проверку.</div>';
  els.preparationStartBtn.textContent = job.task_mode === 'modify' && job.selection_required ? 'Выбрать модель' : `Запустить ${job.task_mode === 'modify' ? 'VE 1' : 'VA 2'}`;
}

async function startUpload() {
  if (!state.files.length || state.busy) return;
  beginVisual();
  state.lastRun = { kind: state.kind, sourceName: state.sourceName, wishes: els.wishes?.value || '', modRequest: els.modRequest?.value || '', priority: Array.from(state.priority), outputType: els.outputType.value, suffix: state.suffix, taskMode: state.taskMode, assetType: state.assetType, assetSubtype: state.assetSubtype, repairActions: Array.from(state.repairActions), repairExclusions: Array.from(state.repairExclusions), excludedFiles: Array.from(state.excludedFiles) };
  saveDraft();
  setPhase('preparing');
  try { await api('/api/health'); } catch (e) { showError(e.message); return; }

  const total = state.files.reduce((s, f) => s + f.size, 0);
  if (total > 2 * 1024 * 1024 * 1024) { showError('MF-413: общий размер превышает 2 ГБ.'); return; }

  // Build the local 'usual settings' profile from deliberate starts, not from passive draft edits.
  recordUsualSettings();

  const fd = new FormData();
  fd.append('source_kind', state.kind);
  fd.append('source_name', state.sourceName);
  const combinedWishes = [els.wishes?.value?.trim() || '', state.problemOther ? `Дополнительно: ${state.problemOther}` : ''].filter(Boolean).join('\n');
  fd.append('wishes', combinedWishes);
  fd.append('priority_json', JSON.stringify([...state.priority]));
  let out = els.outputType.value;
  if (state.kind !== 'single' && out === 'same') out = 'zip';
  fd.append('output_type', out);
  fd.append('repair_mode', state.repairMode || 'standard');
  fd.append('task_mode', state.taskMode || 'repair');
  fd.append('modification_request', els.modRequest?.value || '');
  fd.append('processing_speed', state.processingSpeed || 'standard');
  fd.append('output_suffix', state.suffix || 'FIXED');
  fd.append('manifest_json', JSON.stringify(state.files.map(f => f.webkitRelativePath || f.name)));
  fd.append('asset_type', state.assetType || '');
  fd.append('asset_subtype', state.assetSubtype || '');
  fd.append('problem_hints_json', JSON.stringify([...state.problemHints]));
  fd.append('repair_actions_json', JSON.stringify([...state.repairActions]));
  fd.append('repair_exclusions_json', JSON.stringify([...state.repairExclusions]));
  fd.append('ai_traffic_scope', state.aiTrafficScope || 'all');
  fd.append('excluded_files_json', JSON.stringify(state.excludedFiles));
  fd.append('prepare_only', '1');
  state.files.forEach(f => fd.append('files', f, f.name));

  els.startLabel.textContent = 'Загрузка…';
  els.progressState.textContent = 'Передаём файлы на сервер…';

  // Preparation is intentionally lightweight: no game/decoration while the archive is being unpacked.
  hideGame();
  toast('Файл принят · сначала ModForge покажет, что найдено, затем предложит запуск.', 'info', 4200);

  const xhr = new XMLHttpRequest();
  state.uploadXhr = xhr;
  xhr.open('POST', '/api/analyze', true);
  xhr.timeout = 20 * 60 * 1000;

  let uploadStart = Date.now();
  let uploadedForMeter = 0;
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round(e.loaded / e.total * 100);
    const elapsed = (Date.now() - uploadStart) / 1000;
    const speed = e.loaded / elapsed;
    uploadedForMeter = e.loaded;
    const rem = (e.total - e.loaded) / speed;
    els.progressBar.style.width = `${p}%`;
    els.overallPct.textContent = `${p}%`;
    els.progressState.textContent = `Загрузка · ${p}% · ${bytes(speed)}/с`;
    els.eta.textContent = `До обработки: ~${Math.max(1, Math.ceil(rem))} сек.`;
    if (els.networkUsageLabel) els.networkUsageLabel.textContent = `${bytes(speed)}/с · ${bytes(uploadedForMeter)}`;
  };

  xhr.onload = () => {
    state.uploadXhr = null;
    let d = {};
    try { d = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status !== 200) { showError(`${d.code || `MF-${xhr.status}`}: ${d.message || 'Сервер отклонил загрузку.'}`); hideGame(); return; }
    state.jobId = d.job_id;
    els.startLabel.textContent = 'Анализируем содержимое…';
    // Save active session + a durable last-job reference. The latter survives a closed browser.
    const fp = makeFingerprint(state.files);
    const lastJob = { jobId: d.job_id, fingerprint: fp, sourceName: state.sourceName, kind: state.kind, priority: [...state.priority], wishes: els.wishes.value || '', outputType: out, suffix: state.suffix, repairMode: state.repairMode, processingSpeed: state.processingSpeed, assetType: state.assetType, assetSubtype: state.assetSubtype, problemHints: [...state.problemHints] }; 
    saveSession({ ...lastJob, stageIndex: 0 });
    saveLastJob(lastJob);
    toast('Загрузка завершена · начинается предварительный осмотр.', 'success', 3200);
    poll();
  };
  xhr.onerror = () => { state.uploadXhr = null; showError('MF-503: не удалось достучаться до backend.'); hideGame(); };
  xhr.ontimeout = () => { state.uploadXhr = null; showError('MF-TIMEOUT: загрузка заняла слишком долго.'); hideGame(); };
  xhr.onabort = () => { state.uploadXhr = null; };
  xhr.send(fd);
}

async function startPreparedJob() {
  if (!state.jobId || state.busy) return;
  try {
    if (state.preparedJob?.selection_required && !state.selectedVariant) {
      await openCatalogPicker(state.jobId, state.preparedJob);
      return;
    }
    state.busy = true; state.preparedJob = null; state.preparation = null;
    els.preparationPanel.hidden = true;
    els.startBtn.disabled = true; els.startBtn.classList.add('loading'); els.startLabel.textContent = 'Запускаем…'; els.startSpinner.style.display = 'inline-block';
    setPhase('processing'); els.process.hidden = false; showGame();
    await api(`/api/jobs/${encodeURIComponent(state.jobId)}/start`, { method:'POST', __timeoutMs:20000 });
    toast('Движок запущен · теперь началась фактическая обработка.', 'success', 2800);
    poll();
  } catch(e) {
    if (/MF-409/.test(String(e.message||e)) && state.preparedJob) { openCatalogPicker(state.jobId, state.preparedJob); return; }
    state.busy = false; showError(String(e.message||e));
  }
}
function beginTaskFromUI() {
  if (state.preparedJob?.status === 'prepared') return startPreparedJob();
  return startUpload();
}
els.startBtn.addEventListener('click', beginTaskFromUI);
els.preparationStartBtn?.addEventListener('click', startPreparedJob);
els.preparationCancelBtn?.addEventListener('click', async()=>{ if(!state.jobId) return resetUI(); try{ await api(`/api/jobs/${encodeURIComponent(state.jobId)}/cancel`,{method:'POST'}); }catch{} resetUI(); });
els.preparationDetailsBtn?.addEventListener('click',()=>{ if(state.preparation) showDataModal('ПРЕДВАРИТЕЛЬНЫЙ ОСМОТР', state.preparation); });

/* ══════════════════════════════════════════════════
   POLLING
══════════════════════════════════════════════════ */
function setConnectionWarning(active, detail = '') {
  state.connectionStall = !!active;
  if (els.connectionWarning) {
    els.connectionWarning.hidden = !active;
    if (detail) { const small = els.connectionWarning.querySelector('small'); if (small) small.textContent = detail; }
  }
  const activeStage = els.stageGrid?.querySelector('.stage.active');
  els.stageGrid?.querySelectorAll('.stage-connection-note').forEach(note => {
    const isCurrent = !!active && !!activeStage && activeStage.contains(note);
    note.hidden = !isCurrent;
    if (isCurrent && detail) { const small = note.querySelector('small'); if (small) small.textContent = detail; }
  });
}
function scheduleConnectionWarning() {
  clearTimeout(state.connectionStallTimer);
  state.connectionStallTimer = setTimeout(() => {
    setConnectionWarning(true, 'Ответ backend задерживается. Это предупреждение о связи, а не ошибка задачи.');
  }, 9000);
}
function clearConnectionWarningTimer() {
  clearTimeout(state.connectionStallTimer);
  state.connectionStallTimer = null;
  setConnectionWarning(false);
}
async function poll() {
  if (!state.jobId) return;
  if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
  if (state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    scheduleConnectionWarning();
    const job = await api(`/api/jobs/${state.jobId}`, { __timeoutMs: null });
    clearConnectionWarningTimer();
    state.pollFailures = 0;
    state.lastStatusJob = job;
    setStageUI(job);

    if (job.status === 'prepared') {
      state.preparedJob = job; state.preparation = job.preparation || null; state.selectedVariant = job.selected_variant || state.selectedVariant; state.busy = false;
      renderPreparation(job);
      els.process.hidden = true; els.result.hidden = true; els.startBtn.disabled = false; els.startBtn.classList.remove('loading','error','success'); els.startLabel.textContent = job.task_mode === 'modify' ? 'Запустить VE 1' : 'Запустить VA 2'; els.startSpinner.style.display = 'none';
      setPhase('prepared'); hideGame(); setTaskActivity(false, 0);
      return;
    }
    if (job.status === 'done') {
      const report = await api(`/api/jobs/${state.jobId}/report`, { __timeoutMs: RESULT_TIMEOUT_MS });
      renderResult(report);
      hideGame();
      clearSession();
      saveLastJob({ ...(loadLastJob() || {}), jobId: state.jobId, sourceName: state.sourceName || (loadLastJob()?.sourceName || ''), repairMode: job.repair_mode || state.repairMode, kind: state.kind, assetType: job.asset_type || state.assetType, assetSubtype: job.asset_subtype || state.assetSubtype, repairActions: job.repair_actions || [...state.repairActions], repairExclusions: job.repair_exclusions || [...state.repairExclusions], excludedFiles: job.excluded_files || state.excludedFiles, problemHints: job.problem_hints || [...state.problemHints], selectedVariant: job.selected_variant || state.selectedVariant });
      return;
    }
    if (job.status === 'error') { showError(job.error || job.stage_detail || 'MF-503: ошибка обработки.'); hideGame(); clearSession(); return; }
    if (job.status === 'cancelled') { showError('MF-CANCELLED: обработка остановлена пользователем.'); hideGame(); clearSession(); return; }

    const configuredPollMs = Number(job.processing_poll_ms || 1800);
    // UI-only network optimization: fewer status requests. This never changes backend repair workers.
    const uiPollFloor = state.profile.uiPerformance === 'optimization' ? 4200 : 1800;
    const minPollMs = Math.max(uiPollFloor, configuredPollMs);
    const backgroundMultiplier = document.hidden ? 4 : 1;
    const pollMs = Math.min(15000, minPollMs * backgroundMultiplier);
    state.pollTimer = setTimeout(poll, pollMs);
  } catch (e) {
    const raw = String(e?.message || e || '');
    const transient = /MF-TIMEOUT|MF-503|MF-502|Failed to fetch|NetworkError|Load failed/i.test(raw);
    if (!transient) {
      if (/MF-404/.test(raw) && state.jobId) showError(`MF-509: Текущая сессия ${state.jobId.slice(0,12)} исчезла во время обработки. Возможен сбой backend или восстановление состояния.`);
      else showError(raw);
      return;
    }
    state.pollFailures = (state.pollFailures || 0) + 1;
    clearTimeout(state.connectionStallTimer);
    setConnectionWarning(true, 'Связь с backend нестабильна. Ждём ответ без жёсткого тайм-аута; текущая задача продолжает выполняться.');
    els.processDetail.textContent = 'Соединение с backend замедлилось. Текущая проверка продолжает выполняться; не запускайте задачу повторно.';
    els.progressState.textContent = 'Ожидаем восстановление связи';
    const retryBase = document.hidden ? 5000 : 3000;
    const retryMs = Math.min(15000, retryBase * Math.pow(1.6, Math.min(state.pollFailures - 1, 4)));
    state.pollTimer = setTimeout(poll, retryMs);
  } finally {
    state.pollInFlight = false;
  }
}

/* ══════════════════════════════════════════════════
   PAUSE / STOP / FILES
══════════════════════════════════════════════════ */
async function togglePause() {
  if (!state.jobId || state.pausePending) return;
  state.pausePending = true;
  els.pauseBtn.disabled = true;
  els.pauseBtn.textContent = 'Обновляем…';
  try { const d = await api(`/api/jobs/${state.jobId}/pause`, { method: 'POST', __timeoutMs: 15000 }); state.paused = !!d.paused; els.pauseBtn.textContent = state.paused ? 'Продолжить' : 'Пауза'; setReady(state.paused ? 'Пауза' : 'Продолжается', 'Можно продолжить в любой момент.'); toast(state.paused ? 'Задача поставлена на паузу.' : 'Задача продолжена.', 'success', 1800); setTimeout(() => poll(), 60); }
  catch (e) { toast(e.message, 'error', 3200); }
  finally { state.pausePending = false; els.pauseBtn.disabled = false; if (state.jobId) els.pauseBtn.textContent = state.paused ? 'Продолжить' : 'Пауза'; }
}
els.pauseBtn.addEventListener('click', togglePause);

els.resetJobBtn.addEventListener('click', async () => {
  // During preparing phase — abort upload
  if (document.documentElement.getAttribute('data-phase') === 'preparing') {
    if (state.uploadXhr) state.uploadXhr.abort();
    resetUI();
    return;
  }
  if (state.jobId) {
    try { await api(`/api/jobs/${state.jobId}/cancel`, { method: 'POST' }); } catch {}
  }
  resetUI();
});

els.filesBtn.addEventListener('click', async () => {
  if (!state.jobId || state.filesPending) return;
  state.filesPending = true;
  els.filesBtn.disabled = true;
  try {
    let d = state.lastStatusJob ? {
      files: state.lastStatusJob.current_files || [],
      truncated: !!state.lastStatusJob.current_files_truncated,
      scope: 'current_stage',
      stage: state.lastStatusJob.stage_label || 'Проверка'
    } : null;
    if (!d) d = await api(`/api/jobs/${state.jobId}/files`, { __timeoutMs: 12000 });
    const scope = d.scope === 'current_stage' ? `Текущий этап · ${d.stage || 'Проверка'}` : 'Рабочая копия';
    const lines = d.files || [];
    const list = lines.length ? lines.map((x,i)=>`<div class="current-file-row"><span>${i+1}</span><code>${esc(x)}</code></div>`).join('') : '<div class="files-empty">Сейчас список активных файлов формируется…</div>';
    openModal(
      `<span class="eyebrow">ФАЙЛЫ · ${esc(scope)}</span><h2>Что сейчас проверяется</h2><p class="modal-lead">Показываем файлы именно текущего блока. Список взят из последнего состояния проверки.</p><div class="files-box current-files-box">${list}${d.truncated ? '<div class="files-more">… показан первый фрагмент списка</div>' : ''}</div>`,
      `<button class="btn" id="filesRefresh" type="button">Обновить список</button><button class="btn" id="filesCopy" type="button">Скопировать список</button><button class="btn primary" id="filesClose" type="button">Закрыть</button>`
    );
    $('filesClose').addEventListener('click', closeModal);
    $('filesCopy').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(lines.join('\n')); toast('Список файлов скопирован.', 'success', 1800); } catch { toast('Не удалось скопировать список.', 'warning', 2200); }
    });
    $('filesRefresh').addEventListener('click', () => { closeModal(); state.filesPending=false; els.filesBtn.disabled=false; els.filesBtn.click(); });
  } catch (e) { toast(e.message, 'error', 3200); }
  finally { state.filesPending = false; els.filesBtn.disabled = false; }
});

function showDataModal(title, data) {
  openModal(`<span class="eyebrow">WORKBENCH</span><h2>${esc(title)}</h2><div class="data-table"><pre>${esc(JSON.stringify(data, null, 2))}</pre></div>`, `<button class="btn primary" id="dataModalClose" type="button">Закрыть</button>`);
  $('dataModalClose')?.addEventListener('click', closeModal);
}

function healthHtml(health) {
  const cats = health?.categories || {};
  return `<div class="health-grid">${Object.entries(cats).map(([name,v]) => `<div class="health-cell health-${String(v.status||'').toLowerCase()}"><b>${esc(name)}</b><span>${esc(v.status || '—')} · ${Number(v.errors||0)} E · ${Number(v.warnings||0)} W</span></div>`).join('')}</div>`;
}

async function openJobData(kind) {
  if (!state.jobId) return toast('Сначала запустите задачу.', 'info');
  const urls = {health:`/api/jobs/${state.jobId}/health`,preview:`/api/jobs/${state.jobId}/repair-preview`,diff:`/api/jobs/${state.jobId}/diff`,inspector:`/api/jobs/${state.jobId}/inspector`};
  try { const d=await api(urls[kind]); showDataModal(kind.toUpperCase(), d); } catch(e){ toast(e.message,'error'); }
}

async function runDoctor() {
  if (!state.jobId) return toast('Сначала завершите анализ мода.', 'info');
  const query=els.doctorQuery?.value?.trim(); if(!query) return toast('Опишите симптом.','info');
  try { const d=await api(`/api/jobs/${state.jobId}/doctor`,{method:'POST',body:JSON.stringify({query})}); showDataModal('MOD DOCTOR', d.doctor); } catch(e){ toast(e.message,'error'); }
}

async function compareMods() {
  const a=els.compareA?.files?.[0], b=els.compareB?.files?.[0]; if(!a||!b) return toast('Выберите два ZIP.','info');
  const fd=new FormData(); fd.append('files',a,a.name); fd.append('files',b,b.name);
  try { const r=await fetch('/api/compare',{method:'POST',body:fd,cache:'no-store'}); const d=await r.json(); if(!r.ok) throw new Error(`${d.code||'MF-422'}: ${d.message||'Сравнение не выполнено.'}`); showDataModal('MOD COMPARE', d.compare); } catch(e){toast(e.message,'error');}
}

async function prepareRelease() {
  if (!state.jobId) return toast('Сначала завершите основную проверку.', 'info');
  if (!confirm('Запустить PREPARE FOR RELEASE? Original останется сохранённым.')) return;
  try { const d=await api(`/api/jobs/${state.jobId}/prepare-release`,{method:'POST'}); toast('Release ZIP подготовлен.','success',5000); showDataModal('PREPARE FOR RELEASE', d.release); } catch(e){toast(e.message,'error');}
}

function toggleUiMode() {
  const advanced = !els.advancedTools?.hidden;
  if (els.advancedTools) els.advancedTools.hidden = advanced;
  if (els.uiModeBtn) els.uiModeBtn.textContent = advanced ? 'Simple → Advanced' : 'Advanced → Simple';
  localStorage.setItem('mf_ui_mode', advanced ? 'simple' : 'advanced');
}

/* ══════════════════════════════════════════════════
   RESULT
══════════════════════════════════════════════════ */
function renderResult(report) {
  clearConnectionWarningTimer();
  recordRunMetrics(report);
  document.body.classList.remove('critical-error-active','offline-error-active');
  els.result.classList.remove('diagnostic-critical','diagnostic-offline');
  state.errorCode = '';
  state.busy = false;
  els.startBtn.classList.remove('loading');
  els.startBtn.classList.add('success');
  els.startLabel.textContent = 'Проверка завершена';
  els.startSpinner.style.display = 'none';
  els.process.hidden = false;
  els.result.hidden = false;
  els.overallPct.textContent = '100%';
  els.progressBar.style.width = '100%';
  els.progressState.textContent = 'Финальная проверка завершена';
  els.eta.textContent = 'Осталось: 0 сек.';
  setPhase('done');
  setTaskActivity(false, 100);

  const s = report.summary || {};
  els.resultTitle.textContent = s.ok ? 'Результат готов' : 'Результат готов с предупреждениями';
  els.resultLead.innerHTML = `Исправлено: ${s.fixed || 0}. Ошибок: ${s.errors || 0}. Предупреждений: ${s.warnings || 0}.` + healthHtml(report.health || {});
  if(els.resultMode) els.resultMode.innerHTML=`<span class="mode-result">${report.task_mode==='modify'?'VE 1':'VA 2'} · ${esc(report.repair_mode_label||report.repair_mode||state.repairMode)} · target ${esc(report.beamng_version||'0.39')}</span>`;
  const vs=report.vehicle_status||{};
  if(els.applyStatus){ const branded=vs.status==='repaired-artifact' || !!(vs.branding && (vs.branding.thumbnail_watermark || (vs.branding.info_files||[]).length)); if(branded){ els.applyStatus.hidden=false; els.applyStatus.innerHTML='<b>ModForge</b><span>Название автомобиля и доступные preview/thumbnail-файлы помечены ModForge. Отдельно добавлять UI Apps больше не нужно.</span>'; } else { els.applyStatus.hidden=true; els.applyStatus.innerHTML=''; } }
  els.resultMark.className = 'result-symbol' + (s.ok ? '' : ' warn');
  els.resultMark.textContent = s.ok ? '✓' : '!';
  els.statFiles.textContent = s.files_checked || 0;
  els.statFixed.textContent = s.fixed || 0;
  els.statWarnings.textContent = s.warnings || 0;
  els.statChecks.textContent = s.ok_checks || 0;

  const fixedRows = (report.issues || []).filter(x => x.level === 'fixed');
  if (els.fixedSummary && els.fixedSummaryList) {
    els.fixedSummary.hidden = fixedRows.length === 0;
    els.fixedSummaryList.innerHTML = fixedRows.slice(0, 8).map(x => {
      const target = x.target_file ? ` → ${esc(x.target_file)}` : '';
      const file = esc(x.file || x.source_file || 'рабочая область');
      return `<div class="fixed-row"><span class="fixed-dot">✓</span><div><b>${file}${target}</b><small>${esc(x.details || x.title || '')}</small></div></div>`;
    }).join('') + (fixedRows.length > 8 ? `<div class="fixed-more">Ещё ${fixedRows.length - 8} исправлений доступны через фильтр «Исправлено».</div>` : '');
  }

  els.issueList.innerHTML = (report.issues || []).map(x => {
    const cls = x.level === 'fixed' ? 'fixed' : x.severity === 'CRITICAL' || x.severity === 'ERROR' ? 'warning' : x.level === 'warning' ? 'warning' : x.level === 'ok' ? 'ok' : 'info';
    const lab = x.level === 'fixed' ? 'ИСПРАВЛЕНО' : (x.severity || (x.level === 'warning' ? 'WARNING' : x.level === 'ok' ? 'OK' : 'INFO'));
    return `<article class="issue"><div><span class="tag ${cls}">${esc(lab)}</span><b>${esc(x.title || 'Результат')}</b><span class="micro">${esc(x.category||'')} · ${esc(x.confidence||'')}</span></div><small>${esc(x.details || '')}</small></article>`;
  }).join('') || '<article class="issue"><b>Критических замечаний не найдено.</b></article>';

  state.downloadUrl = report.download_url || `/api/jobs/${state.jobId}/download`;
  state.downloadName = report.output_name || 'ModForge_result';
  saveLastJob({ ...(loadLastJob() || {}), jobId: state.jobId, sourceName: state.sourceName || (loadLastJob()?.sourceName || ''), repairMode: state.repairMode, kind: state.kind, ts: Date.now() });
  els.reportBtn.href = report.report_url || `/api/jobs/${state.jobId}/report`;
  els.restartJobBtn.hidden = true;
  els.resultFileNote.textContent = `Готовый файл: ${state.downloadName}. Его доступность проверяется перед скачиванием.`;
  els.result.scrollIntoView({ behavior: 'smooth', block: 'start' });
  toast(`✓ Проверка завершена · ${s.fixed || 0} исправлений · ${s.warnings || 0} предупреждений`, 'success', 6000);
}

/* ══════════════════════════════════════════════════
   ERROR
══════════════════════════════════════════════════ */
function showError(msg) {
  clearConnectionWarningTimer();
  const code = normalizeErrorCode(msg);
  const spec = ERROR_CATALOG[code] || ERROR_CATALOG['MF-500'];
  state.errorCode = code;
  state.busy = false;
  els.startBtn.classList.remove('loading','success','error');
  els.startBtn.classList.add('error');
  els.startLabel.textContent = spec.retry ? 'Повторить проверку' : 'Понятно';
  els.startSpinner.style.display = 'none';
  els.startBtn.disabled = !spec.retry;
  els.process.hidden = false;
  els.processTitle.textContent = spec.title;
  els.processDetail.textContent = String(msg).replace(`${code}:`, '').trim() || spec.reason;
  els.progressState.textContent = spec.retry ? 'Нужен повтор или восстановление' : 'Операция остановлена';
  els.eta.textContent = '';
  els.result.hidden = false;
  els.result.classList.toggle('diagnostic-critical', spec.level === 'critical');
  els.result.classList.toggle('diagnostic-offline', spec.level === 'offline');
  els.resultTitle.textContent = spec.headline;
  els.resultLead.innerHTML = errorCardHtml(code, msg);
  els.resultMark.textContent = spec.level === 'critical' ? '×' : spec.level === 'offline' ? '⌁' : '!';
  els.resultMark.className = `result-symbol warn ${spec.level}`;
  els.issueList.innerHTML = '';
  els.restartJobBtn.hidden = !spec.retry;
  els.restartJobBtn.textContent = code === 'MF-413' ? 'Выбрать другой файл' : spec.retry ? 'Повторить' : 'Закрыть';
  els.resultFileNote.textContent = code === 'MF-528'
    ? 'Ваши локальные сессии не удаляются этим экраном. После восстановления сервера попробуйте открыть историю ещё раз.'
    : spec.retry ? 'Повторная попытка не удалит локальный черновик.' : 'Операция не помечена как успешная.';
  setReady(spec.retry ? 'Требуется повтор' : 'Операция остановлена', spec.reason);
  setPhase('error');
  document.body.classList.toggle('critical-error-active', spec.level === 'critical');
  document.body.classList.toggle('offline-error-active', spec.level === 'offline');
  toast(`${code} · ${spec.headline}`, spec.level === 'critical' ? 'error' : spec.level === 'offline' ? 'warning' : 'error', 7000);
}

function showArtifactError(code, msg) {
  showError(`${code}: ${msg}`);
  els.processTitle.textContent = 'Ошибка получения файла';
  els.resultTitle.textContent = 'Готовый файл не удалось получить';
  els.issueList.innerHTML = `<article class="issue artifact-error"><div><span class="error-code">${esc(code)}</span><b>Файл сейчас недоступен</b></div><small>${esc(msg)}. Нажмите «Перезапустить всё», чтобы заново выполнить загрузку и обработку.</small></article>`;
  els.restartJobBtn.textContent = 'Перезапустить всё';
  els.resultFileNote.textContent = 'Ошибка появляется только при проблеме с готовым результатом или его выдачей.';
}

function openDownloadWindow(){ try { return window.open('about:blank','_blank','noopener,noreferrer'); } catch { return null; } }
function startDownloadInWindow(url,popup){ const target=`${url}${url.includes('?')?'&':'?'}mf_download=${Date.now()}`; if(popup && !popup.closed){ try { popup.location.replace(target); return true; } catch {} } const iframe=document.createElement('iframe'); iframe.style.position='fixed'; iframe.style.width='1px'; iframe.style.height='1px'; iframe.style.opacity='0'; iframe.style.pointerEvents='none'; iframe.src=target; document.body.appendChild(iframe); setTimeout(()=>iframe.remove(),120000); return true; }
async function downloadResult(){const job=loadLastJob();if(!state.jobId&&job?.jobId)state.jobId=job.jobId;if(!state.jobId)return showArtifactError('MF-404','Задание больше не найдено.');const url=state.downloadUrl||`/api/jobs/${state.jobId}/download`;const popup=openDownloadWindow();const original=els.downloadBtn.textContent;els.downloadBtn.disabled=true;els.downloadBtn.textContent='Проверяем файл…';try{const r=await fetch(url,{method:'HEAD',cache:'no-store'});if(!r.ok){let d={};try{d=await r.json()}catch{}throw new Error(`${d.code||`MF-${r.status}`}: ${d.message||'Готовый файл сейчас недоступен.'}`);}startDownloadInWindow(url,popup);els.downloadBtn.textContent='Скачивание запущено';recordSessionHistory(); toast('Скачивание запущено в отдельной вкладке. Текущая страница не сбрасывается.','success',3500)}catch(e){try{if(popup&&!popup.closed)popup.close()}catch{}const raw=String(e.message||e);const code=raw.match(/MF-[A-Z0-9-]+/)?.[0]||'MF-404';showArtifactError(code,raw.replace(`${code}: `,''))}finally{setTimeout(()=>{els.downloadBtn.disabled=false;els.downloadBtn.textContent=original},2200)}}
async function copyJobId() {
  if (!state.jobId) return toast('ID задачи ещё нет.', 'info');
  try { await navigator.clipboard.writeText(state.jobId); toast('ID задачи скопирован.', 'success', 2000); }
  catch { toast(`ID задачи: ${state.jobId}`, 'info', 4500); }
}

async function restartLastJob() {
  const last = loadLastJob();
  if (!last?.jobId) {
    if (!state.files.length) {
      toast('Для перезапуска сохранённого задания больше нет данных. Выберите файл заново.', 'warning', 5000);
      return resetUI();
    }
  }
  clearSession();
  els.restartJobBtn.hidden = true;
  try {
    if (last?.jobId) {
      els.restartJobBtn.disabled = true;
      els.restartJobBtn.textContent = 'Перезапускаем…';
      const d = await api(`/api/jobs/${encodeURIComponent(last.jobId)}/restart`, { method: 'POST' });
      state.jobId = d.job_id;
      state.sourceName = last.sourceName || '';
      state.kind = last.kind || 'zip';
      state.repairMode=last.repairMode||'standard'; applyRepairModeUI();
      state.processingSpeed=last.processingSpeed||state.processingSpeed; updateNetworkUI();
      state.priority = new Set(last.priority || []);
      els.wishes.value = last.wishes || '';
      els.outputType.value = last.outputType || 'zip';
      state.suffix = last.suffix || state.suffix;
      state.assetType = last.assetType || '';
      state.problemHints = new Set(last.problemHints || []);
      els.suffixPreview.textContent = state.suffix;
      saveSession({ ...last, jobId: d.job_id, stageIndex: 0 });
      saveLastJob({ ...last, jobId: d.job_id, ts: Date.now() });
      beginVisual();
      setPhase('processing');
      els.progressState.textContent = 'Перезапускаем сохранённую задачу…';
      toast('Сохранённая задача перезапущена без повторной загрузки.', 'success', 3500);
      await poll();
      return;
    }
  } catch (e) {
    els.restartJobBtn.disabled = false;
    els.restartJobBtn.textContent = 'Перезапустить всё';
    toast(e.message, 'warning', 5000);
  }
  // Fallback for a still-selected local file.
  if (state.files.length) {
    state.kind = state.lastRun?.kind || state.kind;
    state.sourceName = state.lastRun?.sourceName || state.sourceName;
    saveDraft();
    els.startBtn.disabled = false;
    startUpload();
  }
}
els.downloadBtn.addEventListener('click', downloadResult);
els.reportBtn?.addEventListener('click', async e => {
  e.preventDefault();
  const job = loadLastJob();
  if (!state.jobId && job?.jobId) state.jobId = job.jobId;
  if (!state.jobId) return showArtifactError('MF-404', 'Задание больше не найдено.');
  const popup=openDownloadWindow();
  try {
    const r = await fetch(`/api/jobs/${encodeURIComponent(state.jobId)}/report`, { cache: 'no-store' });
    if (!r.ok) { const d = await r.json().catch(()=>({})); throw new Error(`${d.code || `MF-${r.status}`}: ${d.message || 'Отчёт сейчас недоступен.'}`); }
    startDownloadInWindow(`/api/jobs/${state.jobId}/report`,popup);
  } catch (e) { try{if(popup&&!popup.closed)popup.close()}catch{} const raw=String(e.message||e); const code=raw.match(/MF-[A-Z0-9-]+/)?.[0] || 'MF-404'; showArtifactError(code, raw.replace(`${code}: `,'')); }
});
els.copyJobBtn.addEventListener('click', copyJobId);
els.restartJobBtn.addEventListener('click', restartLastJob);

/* ══════════════════════════════════════════════════
   FEEDBACK / REPORTS / REPLIES
══════════════════════════════════════════════════ */
function formatDate(ts) {
  try { return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(ts)); }
  catch { return ''; }
}

async function feedbackApi(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const adminKey = sessionStorage.getItem(SK.ADMIN_KEY) || '';
  if (adminKey) headers['X-ModForge-Admin-Key'] = adminKey;
  const r = await fetch(url, { ...opts, headers, cache: 'no-store' });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${d.code || `MF-${r.status}`}: ${d.message || 'Не удалось выполнить запрос.'}`);
  return d;
}

function feedbackHtml(items) {
  if (!items.length) return '<div class="feedback-empty">Пока здесь нет сообщений. Будьте первым.</div>';
  return items.map(item => `
    <article class="feedback-item" data-feedback-id="${esc(item.id)}">
      <div class="feedback-head"><div><b>${esc(item.name || 'Гость')}</b><span>${esc(formatDate(item.created_at))}</span></div><span class="feedback-status">${esc(item.status || 'открыто')}</span></div>
      <p>${esc(item.message || '')}</p>
      <div class="feedback-actions"><button class="text-action feedback-reply" type="button">Ответить</button><button class="text-action feedback-report" type="button">Пожаловаться</button></div>
      ${(item.replies || []).length ? `<div class="feedback-replies">${item.replies.map(r => `<div class="feedback-reply-item"><b>${esc(r.name || 'Гость')}${r.author ? ' · Автор' : ''}</b><span>${esc(formatDate(r.created_at))}</span><p>${esc(r.message || '')}</p></div>`).join('')}</div>` : ''}
      <div class="reply-box" hidden><input class="field reply-name" maxlength="40" placeholder="Имя"><textarea class="field reply-message" maxlength="1200" rows="3" placeholder="Ваш ответ"></textarea><button class="btn small primary send-reply" type="button">Отправить ответ</button></div>
    </article>`).join('');
}

async function openFeedback() {
  const author = sessionStorage.getItem(SK.ADMIN_KEY) ? ' · режим автора включён' : '';
  openModal(`<span class="eyebrow">ОБРАТНАЯ СВЯЗЬ</span><h2>Сообщения и ответы</h2>
    <p class="modal-lead">Сообщайте об ошибках, предлагайте улучшения, отвечайте и жалуйтесь на сообщения.${esc(author)}</p>
    <div class="feedback-form"><input class="field" id="feedbackName" maxlength="40" placeholder="Ваше имя (необязательно)"><input class="field" id="feedbackEmail" maxlength="160" type="email" placeholder="Email для ответа (необязательно)"><textarea class="field" id="feedbackMessage" maxlength="1200" rows="4" placeholder="Опишите проблему или предложение"></textarea><div class="feedback-form-actions"><button class="btn primary" id="feedbackSend" type="button">Отправить сообщение</button><button class="btn" id="feedbackAdmin" type="button">${sessionStorage.getItem(SK.ADMIN_KEY) ? 'Выйти из режима автора' : 'Я автор'}</button>${sessionStorage.getItem(SK.ADMIN_KEY) ? '<button class="btn" id="feedbackMailTest" type="button">Проверить почту</button>' : ''}<span id="feedbackHint" class="micro"></span></div></div>
    <div class="feedback-list" id="feedbackList"><div class="feedback-empty">Загрузка…</div></div>`,
    `<button class="btn" id="feedbackClose" type="button">Закрыть</button>`);
  $('feedbackClose').addEventListener('click', closeModal);
  $('feedbackSend').addEventListener('click', async () => {
    const message = $('feedbackMessage').value.trim();
    if (!message) { $('feedbackHint').textContent = 'Напишите сообщение.'; return; }
    try {
      await feedbackApi('/api/feedback', { method: 'POST', body: JSON.stringify({ name: $('feedbackName').value.trim(), email: $('feedbackEmail').value.trim(), message }) });
      $('feedbackMessage').value = '';
      $('feedbackHint').textContent = 'Сообщение опубликовано.';
      await loadFeedbackList();
    } catch (e) { $('feedbackHint').textContent = e.message; }
  });
  const mailTest = $('feedbackMailTest');
  mailTest?.addEventListener('click', async () => {
    try {
      await feedbackApi('/api/feedback/admin/test-email', { method: 'POST', body: '{}' });
      $('feedbackHint').textContent = 'Тестовое письмо отправляется. Проверьте входящие и Спам.';
    } catch (e) { $('feedbackHint').textContent = e.message; }
  });
  $('feedbackAdmin').addEventListener('click', async () => {
    if (sessionStorage.getItem(SK.ADMIN_KEY)) { sessionStorage.removeItem(SK.ADMIN_KEY); return openFeedback(); }
    const key = prompt('Введите MODFORGE_ADMIN_KEY:');
    if (!key) return;
    try {
      const r = await feedbackApi('/api/feedback/admin/login', { method: 'POST', headers: { 'X-ModForge-Admin-Key': key }, body: '{}' });
      if (r.ok) { sessionStorage.setItem(SK.ADMIN_KEY, key); openFeedback(); }
    } catch (e) { toast(e.message, 'error', 3500); }
  });
  await loadFeedbackList();
}

async function loadFeedbackList() {
  const list = $('feedbackList');
  if (!list) return;
  try {
    const d = await feedbackApi('/api/feedback');
    list.innerHTML = feedbackHtml(d.items || []);
    list.querySelectorAll('.feedback-reply').forEach(btn => btn.addEventListener('click', () => { btn.closest('.feedback-item').querySelector('.reply-box').hidden = !btn.closest('.feedback-item').querySelector('.reply-box').hidden; }));
    list.querySelectorAll('.feedback-report').forEach(btn => btn.addEventListener('click', async () => {
      const item = btn.closest('.feedback-item');
      try { await feedbackApi(`/api/feedback/${encodeURIComponent(item.dataset.feedbackId)}/report`, { method: 'POST', body: JSON.stringify({ reason: 'Пользователь пожаловался на сообщение' }) }); toast('Жалоба отправлена модерации.', 'success', 2500); } catch (e) { toast(e.message, 'error'); }
    }));
    list.querySelectorAll('.send-reply').forEach(btn => btn.addEventListener('click', async () => {
      const item = btn.closest('.feedback-item');
      const box = item.querySelector('.reply-box');
      const message = box.querySelector('.reply-message').value.trim();
      if (!message) return;
      try { await feedbackApi(`/api/feedback/${encodeURIComponent(item.dataset.feedbackId)}/reply`, { method: 'POST', body: JSON.stringify({ name: box.querySelector('.reply-name').value.trim(), message }) }); await loadFeedbackList(); toast('Ответ опубликован.', 'success', 2500); } catch (e) { toast(e.message, 'error'); }
    }));
  } catch (e) { list.innerHTML = `<div class="feedback-empty">${esc(e.message)}</div>`; }
}

els.feedbackTop?.addEventListener('click', openFeedback);
els.feedbackFooter?.addEventListener('click', openFeedback);
els.resultFeedbackBtn?.addEventListener('click', openFeedback);

els.uiModeBtn?.addEventListener('click', toggleUiMode);
els.doctorBtn?.addEventListener('click', runDoctor);
els.compareBtn?.addEventListener('click', compareMods);
els.inspectorBtn?.addEventListener('click', () => openJobData('inspector'));
els.releaseBtn?.addEventListener('click', prepareRelease);
els.healthBtn?.addEventListener('click', () => openJobData('health'));
els.previewBtn?.addEventListener('click', () => openJobData('preview'));
els.diffBtn?.addEventListener('click', () => openJobData('diff'));
(function initUiMode(){ const mode=localStorage.getItem('mf_ui_mode')||'simple'; if(els.advancedTools) els.advancedTools.hidden=mode!=='advanced'; if(els.uiModeBtn) els.uiModeBtn.textContent=mode==='advanced'?'Advanced → Simple':'Simple → Advanced'; })();


/* ══════════════════════════════════════════════════
   ERROR / HISTORY / OFFLINE UX WIRING
══════════════════════════════════════════════════ */
els.historyTop?.addEventListener('click', openHistoryDrawer);
els.historyDrawer?.querySelectorAll('[data-history-close]').forEach(el => el.addEventListener('click', closeHistoryDrawer));
els.historyClearBtn?.addEventListener('click', () => {
  if (!confirm('Очистить локальную историю скачанных сессий?')) return;
  state.history = [];
  saveHistory();
  renderHistory();
});
els.quickHelpClose?.addEventListener('click', closeQuickHelp);
window.addEventListener('online', () => {
  document.body.classList.remove('offline-error-active');
  toast('Соединение восстановлено. Проверяем backend…', 'success', 2800);
  loadHealth();
});
window.addEventListener('offline', () => {
  showError('MF-503: Устройство сейчас без интернет-соединения. Локальные сессии останутся на месте.');
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeHistoryDrawer(); closeQuickHelp(); closeInterfaceInfo(); return; }
  if ((e.key === 'i' || e.key === 'I') && !e.ctrlKey && !e.metaKey && !e.altKey && !['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)) { e.preventDefault(); openInterfaceInfo(); return; }
  if (e.key === '?' && !e.ctrlKey && !e.metaKey && !e.altKey && !['INPUT','TEXTAREA'].includes(document.activeElement?.tagName)) { e.preventDefault(); showQuickHelp(); return; }
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key === 'Enter') {
    if (!['INPUT','TEXTAREA'].includes(document.activeElement?.tagName) || state.preparedJob) { e.preventDefault(); beginTaskFromUI(); }
    return;
  }
  if (!mod || !e.shiftKey) return;
  const k = e.key.toLowerCase();
  if (k === 'u') { e.preventDefault(); els.zipInput?.click(); }
  else if (k === 'r') { e.preventDefault(); if (!state.busy && state.files.length) beginTaskFromUI(); else if (loadLastJob()?.jobId) restartLastJob(); }
  else if (k === 'p') { e.preventDefault(); if (state.jobId) openJobData('preview'); }
  else if (k === 's') { e.preventDefault(); openHistoryDrawer(); }
});

async function checkServerState(d) {
  const epoch = String(d?.state_epoch || '').trim();
  if (!epoch) return false;
  const previous = localStorage.getItem(SK.STATE_EPOCH);
  localStorage.setItem(SK.STATE_EPOCH, epoch);
  state.serverEpoch = epoch;
  if (previous && previous !== epoch) {
    state.resetDetected = true;
    showError(`MF-528: Версия состояния сервера изменилась (${previous} → ${epoch}). Все серверные данные, которые не удалось перенести после обновления, считаются сброшенными.`);
    state.history = state.history.map(x => ({ ...x, status: 'reset' }));
    saveHistory();
    renderHistory();
    return true;
  }
  return false;
}

/* ══════════════════════════════════════════════════
   HEALTH CHECK & INIT
══════════════════════════════════════════════════ */
async function loadHealth() {
  try {
    const d = await api('/api/health');
    state.release = d.release_id || d.app_version || state.release;
    const stateWasReset = await checkServerState(d);
    state.stages = d.stages || [];
    state.checkBlocks = d.config?.repair_modes?.[state.repairMode] || { count: currentRepairBlocks().length };
    if (els.brandName) els.brandName.textContent = d.config?.brand_name || 'ModForge';
    if (els.brandSub) els.brandSub.textContent = d.config?.tagline || 'Проверка модов';
    if (els.versionBadge) els.versionBadge.textContent = `${state.release} · BeamNG ${d.beamng_version || '0.39'}`;
    document.title = `ModForge · ${state.release} · BeamNG.drive ${d.beamng_version || '0.39'}`;
    if (els.suffixPreview) els.suffixPreview.textContent = state.suffix || d.config?.default_suffix || 'FIXED';
    renderStages();
    if (d.config?.ad_enabled && d.config?.ad_html) { els.adSlot.innerHTML = d.config.ad_html; els.adSlot.hidden = false; }
    if (!stateWasReset) showReleaseFlow();
  } catch (e) {
    state.stages = [];
    renderStages();
    showError(`MF-503: ${e.message}`);
  }
}

// Init sequence
loadProfile();
loadUsualSettings();
loadDraft();
loadHistory();
updateNetworkUI();
applyProfile();
applyRepairModeUI();
applyTaskModeUI();
renderStages();
loadHealth().then(() => tryRestoreOnLoad());


/* ══════════════════════════════════════════════════
   CONFETTI BURST
   Fires on successful job completion.
══════════════════════════════════════════════════ */
(function initConfetti() {
  const cv = document.getElementById('confettiCanvas');
  if (!cv) return;
  const cx = cv.getContext('2d');
  let pieces = [];
  let animId = null;

  function resize() {
    cv.width = window.innerWidth;
    cv.height = window.innerHeight;
  }
  window.addEventListener('resize', resize, { passive: true });
  resize();

  const COLORS = [
    '#f47b20','#ff9d45','#5cc88a','#6eaadf',
    '#d4b85a','#ff6b6b','#c084fc','#38bdf8'
  ];

  function makePiece(cx_, cy_) {
    const angle = Math.random() * Math.PI * 2;
    const speed = 3 + Math.random() * 6;
    return {
      x: cx_, y: cy_,
      vx: Math.cos(angle) * speed * (0.5 + Math.random()),
      vy: -(4 + Math.random() * 7),
      rotation: Math.random() * Math.PI * 2,
      rotSpeed: (Math.random() - 0.5) * 0.25,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      w: 6 + Math.random() * 6,
      h: 4 + Math.random() * 4,
      gravity: 0.18 + Math.random() * 0.08,
      life: 1,
      decay: 0.012 + Math.random() * 0.008,
    };
  }

  function burst(x, y, count) {
    if (document.documentElement.classList.contains('reduced-motion')) return;
    for (let i = 0; i < count; i++) pieces.push(makePiece(x, y));
    if (!animId) loop();
  }

  function loop() {
    cx.clearRect(0, 0, cv.width, cv.height);
    pieces = pieces.filter(p => p.life > 0.02);
    if (!pieces.length) { animId = null; return; }
    pieces.forEach(p => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += p.gravity;
      p.vx *= 0.995;
      p.rotation += p.rotSpeed;
      p.life -= p.decay;
      cx.save();
      cx.globalAlpha = Math.min(1, p.life * 2);
      cx.translate(p.x, p.y);
      cx.rotate(p.rotation);
      cx.fillStyle = p.color;
      cx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
      cx.restore();
    });
    animId = requestAnimationFrame(loop);
  }

  window.__confettiBurst = function() {
    const W = window.innerWidth;
    const H = window.innerHeight;
    // Three simultaneous sources for a festive spread
    burst(W * 0.25, H * 0.35, 40);
    burst(W * 0.5,  H * 0.25, 60);
    burst(W * 0.75, H * 0.35, 40);
  };
})();

/* ══════════════════════════════════════════════════
   ANIMATED STAT COUNTER
   Rolls numbers up when the result section appears.
══════════════════════════════════════════════════ */
function animateCounter(el, target, duration) {
  if (!el || document.documentElement.classList.contains('reduced-motion')) {
    if (el) el.textContent = target;
    return;
  }
  const start = 0;
  const startTime = performance.now();
  function step(now) {
    const t = Math.min(1, (now - startTime) / duration);
    const ease = 1 - Math.pow(1 - t, 3); // ease-out-cubic
    el.textContent = Math.round(start + (target - start) * ease);
    if (t < 1) requestAnimationFrame(step);
    else el.textContent = target;
  }
  requestAnimationFrame(step);
}

/* ══════════════════════════════════════════════════
   ISSUE FILTERS
   Filter the issue list by category after render.
══════════════════════════════════════════════════ */
function setupIssueFilters(issues) {
  if (!els.issueFilters || !issues.length) {
    if (els.issueFilters) els.issueFilters.hidden = true;
    return;
  }

  // Count by category
  let countFixed = 0, countWarn = 0, countInfo = 0;
  const articles = Array.from(els.issueList.querySelectorAll('.issue'));
  articles.forEach(a => {
    const tag = a.querySelector('.tag');
    if (!tag) return;
    const cls = tag.className;
    if (cls.includes('fixed')) countFixed++;
    else if (cls.includes('warning')) countWarn++;
    else countInfo++;
  });

  if (els.filterCountAll)   els.filterCountAll.textContent   = articles.length;
  if (els.filterCountFixed) els.filterCountFixed.textContent = countFixed;
  if (els.filterCountWarn)  els.filterCountWarn.textContent  = countWarn;
  if (els.filterCountInfo)  els.filterCountInfo.textContent  = countInfo;

  els.issueFilters.hidden = false;

  els.issueFilters.querySelectorAll('.issue-filter').forEach(btn => {
    btn.addEventListener('click', () => {
      els.issueFilters.querySelectorAll('.issue-filter').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const filter = btn.dataset.filter;
      articles.forEach(a => {
        if (filter === 'all') {
          delete a.dataset.hidden;
        } else {
          const tag = a.querySelector('.tag');
          const cls = tag ? tag.className : '';
          const match =
            (filter === 'fixed'   && cls.includes('fixed'))   ||
            (filter === 'warning' && cls.includes('warning')) ||
            (filter === 'info'    && (cls.includes('info') || cls.includes('ok')));
          if (match) delete a.dataset.hidden;
          else a.dataset.hidden = '1';
        }
      });
    });
  });
}

/* ══════════════════════════════════════════════════
   ENHANCED COPY BUTTON ANIMATION
══════════════════════════════════════════════════ */
(function patchCopyJobBtn() {
  if (!els.copyJobBtn) return;
  els.copyJobBtn.addEventListener('click', () => {
    els.copyJobBtn.classList.remove('copy-flash');
    // Force reflow so animation replays
    void els.copyJobBtn.offsetWidth;
    els.copyJobBtn.classList.add('copy-flash');
    setTimeout(() => els.copyJobBtn.classList.remove('copy-flash'), 500);
  });
})();

/* ══════════════════════════════════════════════════
   DROPZONE FILE-READY PULSE
   Pulse the dropzone briefly after a file is chosen.
══════════════════════════════════════════════════ */
(function patchDropzone() {
  if (!els.dropzone) return;
  const origUpdateSelection = window.updateSelection;
  // Patch via observer on the selection element
  const obs = new MutationObserver(() => {
    if (!els.selection.hidden) {
      els.dropzone.classList.remove('file-ready');
      void els.dropzone.offsetWidth;
      els.dropzone.classList.add('file-ready');
      setTimeout(() => els.dropzone.classList.remove('file-ready'), 3600);
    }
  });
  if (els.selection) obs.observe(els.selection, { attributes: true, attributeFilter: ['hidden'] });
})();

/* ══════════════════════════════════════════════════
   HOOK INTO renderResult FOR NEW FEATURES
   Patches the renderResult function to trigger
   confetti, animated counters, issue filters,
   and result-symbol glow.
══════════════════════════════════════════════════ */
(function patchRenderResult() {
  // We hook by observing changes to result section visibility
  if (!els.result) return;
  const resultObs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.attributeName === 'hidden' && !els.result.hidden) {
        // Result just became visible — run our enhancements
        setTimeout(() => {
          const s = {
            files:    parseInt(els.statFiles?.textContent  || '0', 10),
            fixed:    parseInt(els.statFixed?.textContent  || '0', 10),
            warnings: parseInt(els.statWarnings?.textContent || '0', 10),
            checks:   parseInt(els.statChecks?.textContent || '0', 10),
          };
          const statEls = [els.statFiles, els.statFixed, els.statWarnings, els.statChecks];
          const statVals = [s.files, s.fixed, s.warnings, s.checks];
          // Animate stats
          statEls.forEach((el, i) => {
            if (!el) return;
            el.classList.add('stat-anim');
            setTimeout(() => el.classList.remove('stat-anim'), 600);
            animateCounter(el, statVals[i], 700 + i * 80);
          });
          // Confetti on clean success
          const isSuccess = els.resultMark && !els.resultMark.classList.contains('warn');
          if (isSuccess && typeof window.__confettiBurst === 'function') {
            window.__confettiBurst();
          }
          // Glow result symbol
          if (els.resultMark && !els.resultMark.classList.contains('warn')) {
            els.resultMark.classList.add('result-done');
            setTimeout(() => els.resultMark.classList.remove('result-done'), 2000);
          }
          // Progress bar done-shine
          if (els.progressBar) {
            els.progressBar.classList.add('done-shine');
            setTimeout(() => els.progressBar.classList.remove('done-shine'), 1000);
          }
          // Issue filters
          const issues = Array.from(els.issueList?.querySelectorAll('.issue') || []);
          setupIssueFilters(issues);
        }, 80);
        break;
      }
    }
  });
  resultObs.observe(els.result, { attributes: true, attributeFilter: ['hidden'] });
})();

/* ══════════════════════════════════════════════════
   STAGE SPARKLE — pulse when a stage transitions
   from active → done.
══════════════════════════════════════════════════ */
(function watchStageCompletion() {
  if (!els.stageGrid) return;
  const stageObs = new MutationObserver(() => {
    els.stageGrid.querySelectorAll('.stage.done:not(.just-done)').forEach(s => {
      s.classList.add('just-done');
      setTimeout(() => s.classList.remove('just-done'), 800);
    });
  });
  stageObs.observe(els.stageGrid, { attributes: true, subtree: true, attributeFilter: ['class'] });
})();
})();


// Processing detail toggle and keyboard shortcut for the dedicated interface information center.
els.processDetailsBtn?.addEventListener('click',()=>{ document.documentElement.dataset.processDetails = document.documentElement.dataset.processDetails==='1'?'0':'1'; els.processDetailsBtn.textContent = document.documentElement.dataset.processDetails==='1'?'Скрыть этапы':'Показать этапы'; });
