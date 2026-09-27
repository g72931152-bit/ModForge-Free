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
};
const SESSION_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days
const API_TIMEOUT_MS = 60000;
const RESULT_TIMEOUT_MS = 120000;

/* ══════════════════════════════════════════════════
   DOM HELPERS
══════════════════════════════════════════════════ */
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes = n => { n = Number(n) || 0; const u = ['B','KB','MB','GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return `${n.toFixed(i ? 1 : 0)} ${u[i]}`; };
const etaStr = s => { s = Number(s); if (!Number.isFinite(s) || s <= 0) return 'Осталось: —'; if (s < 60) return `Осталось: ~${Math.max(1, Math.round(s))} сек.`; return `Осталось: ~${Math.ceil(s / 60)} мин.`; };
const timeAgo = ts => { const d = Math.round((Date.now() - ts) / 60000); if (d < 1) return 'только что'; if (d < 60) return `${d} мин. назад`; return `${Math.floor(d / 60)} ч. назад`; };

/* ══════════════════════════════════════════════════
   ELEMENT REFS
══════════════════════════════════════════════════ */
const els = {};
[
  'brandName','brandSub','versionBadge','adSlot','brand','feedbackTop','feedbackFooter','resultFeedbackBtn','profileTop','profileAvatar','profileName','profileState','heroProfileBtn','greetingLine','profileSummary','profileCard','profileStateDot','profileAvatarLarge','profileCardName','profileCardMeta','profileEditBtn','metricRuns','metricFixed','metricMode','profileLast',
  'zipBtn','folderBtn','fileBtn','zipInput','folderInput','fileInput',
  'dropzone','dropTitle','dropSub','selection',
  'priorityChips','wishes','outputType','repairMode','modeInfo','vehicleDetect','vehicleDetectTitle','vehicleDetectMeta','resultMode','applyStatus',
  'taskMode','repairConfig','wishesBox','modLab','modRequest','modShortcuts','requestPreview',
  'settingsBtn','settingsTop','suffixPreview','uiModeBtn','advancedTools','doctorQuery','doctorBtn','compareA','compareB','compareBtn','inspectorBtn','releaseBtn','healthBtn','previewBtn','diffBtn','clearBtn','issueFilters','filterCountAll','filterCountFixed','filterCountWarn','filterCountInfo',
  'startBtn','startLabel','startSpinner','readyState',
  'process','processTitle','processDetail',
  'overallPct','stageCount','progressBar','progressState','eta',
  'pauseBtn','filesBtn','resetJobBtn','stageGrid',
  'result','resultTitle','resultLead','resultMark',
  'statFiles','statFixed','statWarnings','statChecks',
  'issueList','downloadBtn','reportBtn','copyJobBtn','restartJobBtn','newJobBtn','resultFileNote',
  'modal','modalContent','modalActions','modalClose',
  'gameOverlay','snakeCanvas','snakeScore','snakeHi','gameStatus',
  'gameMinimize','gameClose',
  'sessionBanner','sessionDesc','sessionResume','sessionDismiss',
  'toastContainer','snakePromoBtn','networkPresets','networkLimitLabel','networkUsageLabel','heroBannerMedia','brandTaskDot','reactionTarget','reactionTimer','gameTitle','gameControlsHint'
].forEach(id => els[id] = $(id));

const ASSET_TYPES = [
  ['vehicle','Машина'], ['map','Карта / уровень'], ['prop','Предмет / проп'],
  ['texture','Текстуры / материалы'], ['sound','Звуки'], ['other','Другое']
];
const PROBLEM_HINTS = [
  ['mirror_reflection','В зеркалах не отражается машина'],
  ['glass_transparency','Проблема со стеклом / прозрачностью'],
  ['no_texture','На стекле/детали появляется NO TEXTURE'],
  ['missing_texture','Не хватает текстуры'],
  ['not_visible','Деталь или машина не видна'],
  ['wheels','Проблема с колёсами'], ['lights','Проблема со светом / фонарями'],
  ['sound','Проблема со звуком'], ['physics','Проблема с физикой / JBeam']
];

/* ══════════════════════════════════════════════════
   APP STATE
══════════════════════════════════════════════════ */
const state = {
  files: [], kind: '', sourceName: '',
  jobId: null, pollTimer: null,
  priority: new Set(),
  suffix: localStorage.getItem(SK.SUFFIX) || 'FIXED',
  repairMode: localStorage.getItem('mf_repair_mode') || 'standard',
  taskMode: localStorage.getItem('mf_task_mode') || 'repair',
  networkProfile: localStorage.getItem('mf_network_profile') || 'standard',
  networkMbps: Number(localStorage.getItem('mf_network_mbps') || 2) || 2,
  profile: { name: 'Гость', accent: 'orange', density: 'comfortable', reducedMotion: false },
  metrics: { runs: 0, fixed: 0, lastMode: 'standard', lastTaskMode: 'repair', lastSource: '' },
  pollFailures: 0,
  release: 'v1 (0.42)',
  stages: [],
  busy: false,
  uploadXhr: null,
  lastRun: null,
  downloadUrl: null,
  downloadName: null,
  previewShownJob: null,
  assetType: '',
  problemHints: new Set(),
  largeStageVisible: false,
};

/* ══════════════════════════════════════════════════
   LOCAL PROFILE & PERSONALIZATION
══════════════════════════════════════════════════ */
function loadProfile() {
  try {
    const p = JSON.parse(localStorage.getItem(SK.PROFILE) || 'null');
    if (p && typeof p === 'object') {
      state.profile = {
        name: typeof p.name === 'string' && p.name.trim() ? p.name.trim().slice(0, 32) : 'Гость',
        accent: ['orange','blue','mint'].includes(p.accent) ? p.accent : 'orange',
        density: ['comfortable','compact'].includes(p.density) ? p.density : 'comfortable',
        reducedMotion: !!p.reducedMotion,
      };
    }
  } catch {}
  try {
    const m = JSON.parse(localStorage.getItem(SK.METRICS) || 'null');
    if (m && typeof m === 'object') state.metrics = { ...state.metrics, ...m };
  } catch {}
}
function saveProfile() { try { localStorage.setItem(SK.PROFILE, JSON.stringify(state.profile)); } catch {} }
function saveMetrics() { try { localStorage.setItem(SK.METRICS, JSON.stringify(state.metrics)); } catch {} }
function initials(name) {
  const n = String(name || 'Гость').trim();
  if (!n || n === 'Гость') return 'G';
  return n.split(/\s+/).slice(0,2).map(x => x[0]).join('').toUpperCase().slice(0,2) || 'M';
}
function applyProfile() {
  const root = document.documentElement;
  root.dataset.accent = state.profile.accent;
  root.dataset.density = state.profile.density;
  root.classList.toggle('reduced-motion', !!state.profile.reducedMotion);
  const name = state.profile.name || 'Гость';
  const ini = initials(name);
  ['profileAvatar','profileAvatarLarge'].forEach(id => { if (els[id]) els[id].textContent = ini; });
  if (els.profileName) els.profileName.textContent = name;
  if (els.profileState) els.profileState.textContent = name === 'Гость' ? 'Локальный профиль' : 'Персональный профиль';
  if (els.profileCardName) els.profileCardName.textContent = name;
  if (els.profileCardMeta) els.profileCardMeta.textContent = name === 'Гость' ? 'Локальный профиль · без аккаунта' : 'Локальный профиль · настройки сохранены';
  if (els.greetingLine) els.greetingLine.textContent = name === 'Гость' ? 'Рабочее пространство готово' : `Добро пожаловать, ${name}`;
  if (els.profileSummary) els.profileSummary.textContent = `${state.metrics.runs || 0} задач · ${state.metrics.fixed || 0} исправлений · ${state.profile.accent === 'orange' ? 'оранжевый' : state.profile.accent === 'blue' ? 'синий' : 'мятный'} акцент`;
  if (els.metricRuns) els.metricRuns.textContent = state.metrics.runs || 0;
  if (els.metricFixed) els.metricFixed.textContent = state.metrics.fixed || 0;
  if (els.metricMode) els.metricMode.textContent = state.metrics.lastTaskMode === 'modify' ? 'LAB' : String(state.metrics.lastMode || 'standard').slice(0,4).toUpperCase();
  if (els.profileLast) els.profileLast.textContent = state.metrics.lastSource ? `Последняя задача: ${state.metrics.lastSource}` : 'Последняя задача: пока нет запусков';
  if (els.profileStateDot) els.profileStateDot.classList.toggle('custom', name !== 'Гость');
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
setPhase('idle');

/* ══════════════════════════════════════════════════
   ANIMATED BACKGROUND (particle grid)
══════════════════════════════════════════════════ */
(function initBg() {
  const canvas = $('bgCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, particles = [], raf;

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function makeParticles() {
    particles = [];
    const count = Math.min(70, Math.floor((W * H) / 28000));
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - .5) * .3,
        vy: (Math.random() - .5) * .3,
        r: Math.random() * 1.2 + .3,
        a: Math.random() * .4 + .1,
      });
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    // Moving dot grid
    const t = Date.now() / 1000;
    const gridSpacing = 44;
    const offsetX = (t * 4) % gridSpacing;
    const offsetY = (t * 3) % gridSpacing;
    ctx.fillStyle = 'rgba(244,123,32,0.09)';
    for (let x = -gridSpacing + offsetX; x < W + gridSpacing; x += gridSpacing) {
      for (let y = -gridSpacing + offsetY; y < H + gridSpacing; y += gridSpacing) {
        ctx.beginPath();
        ctx.arc(x, y, 1, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    // Floating particles
    particles.forEach(p => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0) p.x = W; if (p.x > W) p.x = 0;
      if (p.y < 0) p.y = H; if (p.y > H) p.y = 0;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(244,123,32,${Math.min(.28, p.a * .72)})`;
      ctx.fill();
    });
    // Subtle connection lines
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.strokeStyle = `rgba(244,123,32,${.075 * (1 - dist / 120)})`;
          ctx.lineWidth = .5;
          ctx.stroke();
        }
      }
    }
    raf = requestAnimationFrame(draw);
  }

  resize();
  makeParticles();
  draw();
  window.addEventListener('resize', () => { resize(); makeParticles(); });
})();

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

function setTaskActivity(active, progress=0) {
  const ratio = Math.max(0, Math.min(1, Number(progress) / 100));
  document.documentElement.style.setProperty('--task-progress', ratio.toFixed(3));
  document.body.classList.toggle('task-active', !!active);
  if (els.brandTaskDot) els.brandTaskDot.classList.toggle('active', !!active);
  const hue = Math.round(22 + ratio * 110);
  const favicon = document.querySelector('link[rel="icon"]');
  if (favicon) {
    const color = `hsl(${hue} 76% 55%)`;
    const dot = active ? `<circle cx="27" cy="5" r="2.6" fill="${color}"/>` : '';
    favicon.href = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0b0d0e"/><image href="/assets/logo.png" x="4" y="4" width="24" height="24" preserveAspectRatio="xMidYMid meet"/>${dot}</svg>`)}`;
  }
}

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
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.shiftKey && !e.altKey && !state.busy && els.startBtn && !els.startBtn.disabled) {
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
      networkProfile: state.networkProfile || 'standard',
      networkMbps: state.networkMbps || 2,
      modRequest: els.modRequest?.value || '',
      assetType: state.assetType || '',
      problemHints: Array.from(state.problemHints || []),
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
    if (['standard','balanced','aggressive'].includes(d.networkProfile)) state.networkProfile=d.networkProfile;
    if ([2,5,20].includes(Number(d.networkMbps))) state.networkMbps=Number(d.networkMbps);
    if (els.modRequest && typeof d.modRequest === 'string') els.modRequest.value=d.modRequest;
    if (typeof d.assetType === 'string') state.assetType=d.assetType;
    if (Array.isArray(d.problemHints)) state.problemHints=new Set(d.problemHints.filter(Boolean));
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
    if (Array.isArray(candidate.problemHints)) state.problemHints=new Set(candidate.problemHints);
    if (typeof job.asset_type === 'string' && !state.assetType) state.assetType=job.asset_type;
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
    if (session) toast('Сервис временно недоступен. Последняя задача сохранена.', 'warning', 4500);
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
  const timeoutMs = Number(opts.__timeoutMs || API_TIMEOUT_MS);
  const requestOpts = { ...opts };
  delete requestOpts.__timeoutMs;
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...requestOpts, signal: ctrl.signal, headers: { ...(requestOpts.headers || {}), 'Cache-Control': 'no-cache' } });
    let d = {};
    try { d = await r.json(); } catch {}
    if (!r.ok) { const code = d.code || `MF-${r.status}`; throw new Error(`${code}: ${d.message || `HTTP ${r.status}`}`); }
    return d;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('MF-TIMEOUT: backend не ответил вовремя.');
    if (String(e.message).includes('Failed to fetch')) throw new Error('MF-503: не удалось достучаться до backend.');
    throw e;
  } finally { clearTimeout(t); }
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
function renderStages() {
  const stages = state.largeStageVisible ? [...state.stages, { key:'large-files', label:'Крупные файлы', description:'Отдельная потоковая проверка, не блокирующая обычный скан.' }] : state.stages;
  els.stageGrid.innerHTML = stages.map((s, i) =>
    `<article class="stage ${s.key==='large-files'?'large-stage':''}" data-stage="${i+1}">
      <div class="stage-top">
        <div class="stage-number">${String(i+1).padStart(2,'0')}</div>
        <div class="stage-main"><b>${esc(s.label)}</b><span>${esc(s.description)}</span></div>
        <strong data-stage-p="${i+1}">0%</strong>
      </div>
      <button class="stage-more" data-toggle="${i+1}" type="button">⋯ Подробнее</button>
      <div class="stage-detail" data-detail="${i+1}">Ожидает запуска.</div>
    </article>`
  ).join('');
  els.stageGrid.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', () => b.closest('.stage').classList.toggle('open')));
}

function setLargeStageUI(job) {
  if (job.large_file_count > 0 && !state.largeStageVisible) { state.largeStageVisible = true; renderStages(); }
  const idx = state.stages.length + 1;
  const card = els.stageGrid.querySelector(`[data-stage="${idx}"]`);
  if (!card) return;
  const status = job.large_task_status || 'queued';
  card.classList.toggle('done', status === 'done');
  card.classList.toggle('active', status === 'running');
  card.classList.toggle('error', status === 'error');
  const p = card.querySelector(`[data-stage-p="${idx}"]`);
  if (p) p.textContent = `${Number(job.large_task_progress)||0}%`;
  const d = card.querySelector(`[data-detail="${idx}"]`);
  const files = (job.large_files || []).map(x => `<span class="large-file-line"><b>${esc(x.file || '')}</b><em>${esc(bytes(x.size || 0))}</em></span>`).join('');
  if (d) d.innerHTML = `<div class="large-file-summary"><strong>${esc(job.large_task_detail || 'Файл вынесен из обычного скана.')}</strong>${files || ''}</div>`;
}

function setStageUI(job) {
  const idx = Number(job.stage_index || 0);
  els.processTitle.textContent = job.stage_label || 'Проверка';
  els.processDetail.textContent = job.stage_detail || '—';
  els.overallPct.textContent = `${Math.round(job.progress || 0)}%`;
  els.stageCount.textContent = `${Math.min(idx, state.stages.length)} / ${state.stages.length}`;
  els.progressBar.style.width = `${Math.min(100, Math.max(0, Number(job.progress) || 0))}%`;
  els.progressState.textContent = job.status === 'paused' ? 'Пауза' : job.status === 'done' ? 'Завершено' : ['error','rebuilding'].includes(job.status) ? (job.status === 'rebuilding' ? 'Восстановление файла' : 'Ошибка') : job.stage_label || 'Обработка';
  els.eta.textContent = etaStr(job.eta_seconds);

  state.stages.forEach((_, i) => {
    const card = els.stageGrid.querySelector(`[data-stage="${i+1}"]`);
    if (!card) return;
    card.classList.toggle('done', i+1 < idx || job.status === 'done');
    card.classList.toggle('active', i+1 === idx && !['done','error'].includes(job.status));
    card.classList.toggle('error', i+1 === idx && job.status === 'error');
  });
  if (idx) {
    const p = els.stageGrid.querySelector(`[data-stage-p="${idx}"]`);
    if (p) p.textContent = `${Number(job.stage_progress) || 0}%`;
    const d = els.stageGrid.querySelector(`[data-detail="${idx}"]`);
    if (d && job.stage_detail) d.textContent = job.stage_detail;
  }
  setLargeStageUI(job);
  els.pauseBtn.textContent = job.status === 'paused' ? 'Продолжить' : 'Пауза';

  if (job.repair_preview && idx >= 10 && state.previewShownJob !== state.jobId) {
    state.previewShownJob = state.jobId;
    showDataModal('REPAIR PREVIEW · до исправления', job.repair_preview);
  }
  if (idx >= 1 && document.documentElement.getAttribute('data-phase') === 'preparing') setPhase('processing');
  if (state.jobId) updateSession({ stageIndex: idx, ts: Date.now() });
}

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
    <p class="modal-lead">Стабильный релиз. Основные изменения этой версии:</p>
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
        <li>BeamNG.drive 0.39 — целевой профиль; 0.42 — версия сайта ModForge.</li>
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
      <li>Выберите ZIP, папку или поддерживаемый BeamNG-файл.</li>
      <li>Настройте приоритет и формат до начала загрузки.</li>
      <li>После полной проверки скачайте результат и JSON-отчёт.</li>
    </ol>
    <p>Если ModForge не может уверенно доказать, что изменение безопасно, он оставляет предупреждение вместо рискованного исправления.</p>
    <p class="micro">Во время обработки можно открыть мини-игру; она не влияет на задачу.</p>`,
    `<button class="btn primary" id="guideDone" type="button">Начать работу</button>`
  );
  $('guideDone').addEventListener('click', () => { localStorage.setItem(SK.GUIDE, '1'); closeModal(); });
}

/* ══════════════════════════════════════════════════
   REPAIR MODE
══════════════════════════════════════════════════ */
els.repairMode?.querySelectorAll('.mode-card').forEach(card=>card.addEventListener('click',()=>{state.repairMode=card.dataset.mode||'standard';localStorage.setItem('mf_repair_mode',state.repairMode);applyRepairModeUI();saveDraft();}));
els.modeInfo?.addEventListener('click', () => {
  openModal(
    `<span class="eyebrow">РЕЖИМЫ ИСПРАВЛЕНИЯ</span><h2>Глубина ремонта</h2>
    <div class="mode-explain">
      <section><b>Стандартный</b><p>Безопасные подтверждённые исправления; спорные случаи остаются в отчёте. Рекомендуется для большинства модов.</p></section>
      <section><b>Средний</b><p>Добавляется более глубокий подбор ресурсов, исправление типовых ошибок конфигурации и дополнительные JBeam-проверки.</p></section>
      <section><b>Агрессивный</b><p>Добавляется эвристический ремонт неоднозначных ресурсов и очевидно нулевых параметров физики с повторной проверкой.</p></section>
    </div>`,
    `<button class="btn primary" id="modeInfoClose" type="button">Понятно</button>`
  );
  $('modeInfoClose')?.addEventListener('click', closeModal);
});

/* ══════════════════════════════════════════════════
   BRAND / HOME
══════════════════════════════════════════════════ */
if (els.brand) els.brand.addEventListener('click', e => {
  e.preventDefault();
  saveDraft();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

/* ══════════════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════════════ */
function showSettings() {
  const profiles = {standard:2, balanced:5, aggressive:20};
  openModal(
    `<span class="eyebrow">ПРОФИЛЬ</span><h2>Персонализация рабочего пространства</h2>
    <p class="modal-lead">Все параметры ниже сохраняются локально в браузере. Регистрация не требуется.</p>
    <label class="field-label">Имя</label>
    <input class="field" id="profileNameInput" maxlength="32" value="${esc(state.profile.name === 'Гость' ? '' : state.profile.name)}" placeholder="Например, Alex">
    <span class="micro">Имя показывается только в интерфейсе на этом устройстве.</span>
    <label class="field-label" style="margin-top:16px">Акцент</label>
    <div class="accent-picker" id="accentPicker">
      <button class="accent-option ${state.profile.accent==='orange'?'active':''}" data-accent-option="orange" type="button"><i></i><b>Оранжевый</b><small>ModForge</small></button>
      <button class="accent-option ${state.profile.accent==='blue'?'active':''}" data-accent-option="blue" type="button"><i></i><b>Синий</b><small>Холодный</small></button>
      <button class="accent-option ${state.profile.accent==='mint'?'active':''}" data-accent-option="mint" type="button"><i></i><b>Мятный</b><small>Нейтральный</small></button>
    </div>
    <label class="field-label" style="margin-top:16px">Плотность интерфейса</label>
    <div class="segmented" id="densityPicker">
      <button class="segment ${state.profile.density==='comfortable'?'active':''}" data-density-option="comfortable" type="button">Комфортная</button>
      <button class="segment ${state.profile.density==='compact'?'active':''}" data-density-option="compact" type="button">Компактная</button>
    </div>
    <label class="toggle-row"><input id="reducedMotionInput" type="checkbox" ${state.profile.reducedMotion?'checked':''}><span><b>Уменьшить анимации</b><small>Оставляет только функциональные переходы.</small></span></label>
    <hr class="settings-divider">
    <span class="eyebrow">РЕЗУЛЬТАТ</span>
    <label class="field-label">Суффикс результата</label>
    <input class="field" id="suffixInput" maxlength="48" value="${esc(state.suffix)}">
    <span class="micro">FIXED → CLEAN → REPAIRED или любое своё.</span>
    <label class="field-label" style="margin-top:16px">Сетевой профиль</label>
    <div class="network-modal-grid">
      <button class="network-card ${state.networkProfile==='standard'?'active':''}" data-modal-network="standard" type="button"><strong>Стандарт</strong><span>2 MB/s</span><small>минимальный поток</small></button>
      <button class="network-card ${state.networkProfile==='balanced'?'active':''}" data-modal-network="balanced" type="button"><strong>Быстрее</strong><span>5 MB/s</span><small>баланс</small></button>
      <button class="network-card ${state.networkProfile==='aggressive'?'active':''}" data-modal-network="aggressive" type="button"><strong>Агрессивный</strong><span>20 MB/s</span><small>максимум доступной скорости</small></button>
    </div>`,
    `<button class="btn" id="sCancel" type="button">Отмена</button><button class="btn primary" id="sSave" type="button">Сохранить</button>`
  );
  let chosen = state.networkProfile;
  let accent = state.profile.accent;
  let density = state.profile.density;
  els.modalContent.querySelectorAll('[data-modal-network]').forEach(btn=>btn.addEventListener('click',()=>{chosen=btn.dataset.modalNetwork;els.modalContent.querySelectorAll('[data-modal-network]').forEach(x=>x.classList.toggle('active',x===btn));}));
  els.modalContent.querySelectorAll('[data-accent-option]').forEach(btn=>btn.addEventListener('click',()=>{accent=btn.dataset.accentOption;els.modalContent.querySelectorAll('[data-accent-option]').forEach(x=>x.classList.toggle('active',x===btn));}));
  els.modalContent.querySelectorAll('[data-density-option]').forEach(btn=>btn.addEventListener('click',()=>{density=btn.dataset.densityOption;els.modalContent.querySelectorAll('[data-density-option]').forEach(x=>x.classList.toggle('active',x===btn));}));
  $('sCancel').addEventListener('click', closeModal);
  $('sSave').addEventListener('click', () => {
    const typedName = $('profileNameInput').value.trim().replace(/\s+/g,' ');
    state.profile.name = typedName.slice(0,32) || 'Гость';
    state.profile.accent = accent;
    state.profile.density = density;
    state.profile.reducedMotion = !!$('reducedMotionInput').checked;
    state.suffix = $('suffixInput').value.trim() || 'FIXED';
    state.networkProfile = chosen;
    state.networkMbps = profiles[chosen];
    localStorage.setItem(SK.SUFFIX, state.suffix);
    localStorage.setItem('mf_repair_mode', state.repairMode);
    localStorage.setItem('mf_network_profile', state.networkProfile);
    localStorage.setItem('mf_network_mbps', String(state.networkMbps));
    saveProfile();
    els.suffixPreview.textContent = state.suffix;
    updateNetworkUI();
    applyProfile();
    saveDraft();
    closeModal();
    toast(`Профиль сохранён · ${state.profile.name === 'Гость' ? 'гость' : state.profile.name}`, 'success', 2500);
  });
}

els.settingsBtn.addEventListener('click', showSettings);
els.settingsTop.addEventListener('click', showSettings);
els.profileTop?.addEventListener('click', showSettings);
els.heroProfileBtn?.addEventListener('click', showSettings);
els.profileEditBtn?.addEventListener('click', showSettings);

/* ══════════════════════════════════════════════════
   FILE PICKER STATE
══════════════════════════════════════════════════ */
function updateNetworkUI() {
  const map = {standard:2, balanced:5, aggressive:20};
  if (!map[state.networkProfile]) state.networkProfile = 'standard';
  state.networkMbps = map[state.networkProfile];
  els.networkPresets?.querySelectorAll('[data-network]').forEach(btn => btn.classList.toggle('active', btn.dataset.network === state.networkProfile));
  if (els.networkLimitLabel) els.networkLimitLabel.textContent = `${state.networkMbps} MB/s`;
}

els.networkPresets?.querySelectorAll('[data-network]').forEach(btn => btn.addEventListener('click', () => {
  state.networkProfile = btn.dataset.network || 'standard';
  state.networkMbps = {standard:2, balanced:5, aggressive:20}[state.networkProfile] || 2;
  localStorage.setItem('mf_network_profile', state.networkProfile);
  localStorage.setItem('mf_network_mbps', String(state.networkMbps));
  updateNetworkUI(); saveDraft();
}));

function setPickerVisual(kind) {
  const buttons = [els.zipBtn, els.folderBtn, els.fileBtn].filter(Boolean);
  buttons.forEach(btn => {
    const active = (kind === 'zip' && btn === els.zipBtn) || (kind === 'folder' && btn === els.folderBtn) || (kind === 'single' && btn === els.fileBtn);
    btn.classList.toggle('selected', active);
    if (active) {
      const label = btn.dataset.label || '';
      btn.setAttribute('aria-label', `${label} выбран`);
      btn.title = `${label} выбран`;
    } else {
      btn.setAttribute('aria-label', btn.dataset.label || 'Выбрать');
      btn.title = btn.dataset.label || 'Выбрать';
    }
  });
}

/* ══════════════════════════════════════════════════
   FILE SELECTION
══════════════════════════════════════════════════ */
function setReady(text, sub) {
  if (els.readyState) els.readyState.textContent = text;
  if (els.readyState?.nextElementSibling) els.readyState.nextElementSibling.textContent = sub;
}

function applyRepairModeUI(){ els.repairMode?.querySelectorAll('.mode-card').forEach(c=>c.classList.toggle('active',c.dataset.mode===state.repairMode)); }
function detectVehicle(files){ const names=files.map(f=>(f.webkitRelativePath||f.name||'').replace(/\\/g,'/')); const hit=names.find(n=>/(^|\/)vehicles\/[^\/]+\//i.test(n)); if(!hit||!els.vehicleDetect) return; const m=hit.match(/(?:^|\/)vehicles\/([^\/]+)\//i); els.vehicleDetect.hidden=false; els.vehicleDetectTitle.textContent=`Автомобильный мод: ${m?m[1]:'обнаружен'}`; }

function updateSelection() {
  updateNetworkUI();
  const total = state.files.reduce((s, f) => s + f.size, 0);
  detectVehicle(state.files);
  els.selection.hidden = false;
  const type = state.kind === 'zip' ? 'ZIP' : state.kind === 'folder' ? 'Папка' : 'Файл';
  setPickerVisual(state.kind);
  saveDraft();
  const typeLabel = ASSET_TYPES.find(x => x[0] === state.assetType)?.[1] || 'Тип не указан';
  const hintCount = state.problemHints.size;
  els.selection.innerHTML = `<div class="selection-main"><strong>${esc(state.sourceName)}</strong><span>${type} · ${state.files.length} объектов · ${bytes(total)}</span><small>${esc(typeLabel)}${hintCount ? ` · проблем отмечено: ${hintCount}` : ''}</small></div><button class="selection-more" id="selectionMore" type="button" aria-label="Дополнительные сведения" title="Тип ресурса и типовые проблемы">⋯</button>`;
  $('selectionMore')?.addEventListener('click', openSelectionMenu);
  const valid = state.files.length > 0 && total <= 2 * 1024 * 1024 * 1024;
  els.startBtn.disabled = !valid || state.busy;
  setReady(valid ? 'Готово к проверке' : 'Нужен поддерживаемый файл', 'Перед запуском ModForge проверит связь с backend.');
  if (valid) checkFileAgainstSession(state.files);
}

function openSelectionMenu() {
  const typeButtons = ASSET_TYPES.map(([key,label]) => `<button class="choice-card ${state.assetType===key?'active':''}" data-asset-type="${key}" type="button"><b>${esc(label)}</b><small>${key==='vehicle'?'JBeam, колёса, стекло, свет':key==='map'?'уровни, сцены и их ресурсы':key==='prop'?'отдельные объекты/декорации':key==='texture'?'материалы и карты текстур':key==='sound'?'аудиоресурсы':'без дополнительной классификации'}</small></button>`).join('');
  const problemButtons = PROBLEM_HINTS.map(([key,label]) => `<button class="hint-chip ${state.problemHints.has(key)?'active':''}" data-problem-hint="${key}" type="button">${esc(label)}</button>`).join('');
  openModal(`<span class="eyebrow">ДОПОЛНИТЕЛЬНО</span><h2>Что загружено и что болит?</h2><p class="modal-lead">Необязательно. Это даёт ModForge контекст и позволяет раньше сосредоточиться на нужной области. Остальные проверки не отключаются.</p><label class="field-label">1 · Тип ресурса</label><div class="choice-grid">${typeButtons}</div><label class="field-label" style="margin-top:18px">2 · Типовые проблемы</label><div class="hint-grid">${problemButtons}</div>`, `<button class="btn" id="selectionMetaClear" type="button">Очистить</button><button class="btn primary" id="selectionMetaSave" type="button">Готово</button>`);
  els.modalContent.querySelectorAll('[data-asset-type]').forEach(btn => btn.addEventListener('click',()=>{ state.assetType=btn.dataset.assetType||''; els.modalContent.querySelectorAll('[data-asset-type]').forEach(x=>x.classList.toggle('active',x===btn)); }));
  els.modalContent.querySelectorAll('[data-problem-hint]').forEach(btn => btn.addEventListener('click',()=>{ const key=btn.dataset.problemHint; if(state.problemHints.has(key)){state.problemHints.delete(key);btn.classList.remove('active')}else{state.problemHints.add(key);btn.classList.add('active')} }));
  $('selectionMetaClear').addEventListener('click',()=>{ state.assetType=''; state.problemHints.clear(); closeModal(); updateSelection(); });
  $('selectionMetaSave').addEventListener('click',()=>{ saveDraft(); closeModal(); updateSelection(); });
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
  if (els.startLabel) els.startLabel.textContent = state.taskMode === 'modify' ? 'Запустить Mod Lab' : 'Начать проверку';
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
   RESET UI
══════════════════════════════════════════════════ */
function resetUI() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  if (state.uploadXhr) { state.uploadXhr.abort(); state.uploadXhr = null; }
  state.pollTimer = null; state.jobId = null;
  state.files = []; state.kind = ''; state.sourceName = ''; state.assetType = ''; state.problemHints = new Set(); state.largeStageVisible = false; state.busy = false; state.metricsRecordedJob = null;
  els.zipInput.value = ''; els.folderInput.value = ''; els.fileInput.value = '';
  els.selection.hidden = true;
  setPickerVisual('');
  els.startBtn.disabled = true;
  els.startBtn.classList.remove('loading','success','error');
  els.startLabel.textContent = 'Начать проверку';
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
async function startUpload() {
  if (!state.files.length || state.busy) return;
  beginVisual();
  state.lastRun = { kind: state.kind, sourceName: state.sourceName, wishes: els.wishes?.value || '', modRequest: els.modRequest?.value || '', priority: Array.from(state.priority), outputType: els.outputType.value, suffix: state.suffix, taskMode: state.taskMode };
  saveDraft();
  setPhase('preparing');
  try { await api('/api/health'); } catch (e) { showError(e.message); return; }

  const total = state.files.reduce((s, f) => s + f.size, 0);
  if (total > 2 * 1024 * 1024 * 1024) { showError('MF-413: общий размер превышает 2 ГБ.'); return; }

  const fd = new FormData();
  fd.append('source_kind', state.kind);
  fd.append('source_name', state.sourceName);
  fd.append('wishes', els.wishes.value || '');
  fd.append('priority_json', JSON.stringify([...state.priority]));
  let out = els.outputType.value;
  if (state.kind !== 'single' && out === 'same') out = 'zip';
  fd.append('output_type', out);
  fd.append('repair_mode', state.repairMode || 'standard');
  fd.append('task_mode', state.taskMode || 'repair');
  fd.append('modification_request', els.modRequest?.value || '');
  fd.append('network_profile', state.networkProfile || 'standard');
  fd.append('output_suffix', state.suffix || 'FIXED');
  fd.append('manifest_json', JSON.stringify(state.files.map(f => f.webkitRelativePath || f.name)));
  fd.append('asset_type', state.assetType || '');
  fd.append('problem_hints_json', JSON.stringify([...state.problemHints]));
  state.files.forEach(f => fd.append('files', f, f.name));

  els.startLabel.textContent = 'Загрузка…';
  els.progressState.textContent = 'Передаём файлы на сервер…';

  // Show snake game during upload
  showGame();
  toast('Файл загружается. Можно пока открыть мини-игру или оставить страницу на обработку.', 'info', 5000);

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
    els.startLabel.textContent = 'Задача запущена';
    // Save active session + a durable last-job reference. The latter survives a closed browser.
    const fp = makeFingerprint(state.files);
    const lastJob = { jobId: d.job_id, fingerprint: fp, sourceName: state.sourceName, kind: state.kind, priority: [...state.priority], wishes: els.wishes.value || '', outputType: out, suffix: state.suffix, repairMode: state.repairMode, assetType: state.assetType, problemHints: [...state.problemHints] }; 
    saveSession({ ...lastJob, stageIndex: 0 });
    saveLastJob(lastJob);
    toast('Задача создана · ID: ' + d.job_id.slice(0, 8), 'success', 4000);
    poll();
  };
  xhr.onerror = () => { state.uploadXhr = null; showError('MF-503: не удалось достучаться до backend.'); hideGame(); };
  xhr.ontimeout = () => { state.uploadXhr = null; showError('MF-TIMEOUT: загрузка заняла слишком долго.'); hideGame(); };
  xhr.onabort = () => { state.uploadXhr = null; };
  xhr.send(fd);
}

els.startBtn.addEventListener('click', startUpload);

/* ══════════════════════════════════════════════════
   POLLING
══════════════════════════════════════════════════ */
async function poll() {
  if (!state.jobId) return;
  try {
    const job = await api(`/api/jobs/${state.jobId}`, { __timeoutMs: 30000 });
    state.pollFailures = 0;
    setStageUI(job);

    if (job.status === 'done') {
      // Fetch the potentially large result only after the lightweight status call
      // confirms completion. This keeps progress polling fast and reliable.
      const report = await api(`/api/jobs/${state.jobId}/report`, { __timeoutMs: RESULT_TIMEOUT_MS });
      renderResult(report);
      hideGame();
      clearSession();
      saveLastJob({ ...(loadLastJob() || {}), jobId: state.jobId, sourceName: state.sourceName || (loadLastJob()?.sourceName || ''), repairMode: job.repair_mode || state.repairMode, kind: state.kind, assetType: job.asset_type || state.assetType, problemHints: job.problem_hints || [...state.problemHints] });
      return;
    }
    if (job.status === 'error') { showError(job.error || job.stage_detail || 'MF-503: ошибка обработки.'); hideGame(); clearSession(); return; }
    if (job.status === 'cancelled') { showError('MF-CANCELLED: обработка остановлена пользователем.'); hideGame(); clearSession(); return; }

    const pollMs = state.networkProfile === 'aggressive' ? 320 : state.networkProfile === 'balanced' ? 550 : 900;
    state.pollTimer = setTimeout(poll, pollMs);
  } catch (e) {
    // A transient timeout must not turn a still-running repair into a fake failure.
    // Keep the job alive and continue polling with bounded exponential backoff.
    const raw = String(e?.message || e || '');
    const transient = /MF-TIMEOUT|MF-503|MF-502|Failed to fetch|NetworkError|Load failed/i.test(raw);
    if (!transient) { showError(raw); return; }
    state.pollFailures = (state.pollFailures || 0) + 1;
    els.processDetail.textContent = `Связь с backend прервалась на мгновение. Задача продолжает выполняться. Повторяем подключение…`;
    els.progressState.textContent = 'Восстанавливаем связь';
    const retryMs = Math.min(10000, 1200 * Math.pow(1.5, Math.min(state.pollFailures - 1, 5)));
    state.pollTimer = setTimeout(poll, retryMs);
  }
}

/* ══════════════════════════════════════════════════
   PAUSE / STOP / FILES
══════════════════════════════════════════════════ */
async function togglePause() {
  if (!state.jobId) return;
  try { const d = await api(`/api/jobs/${state.jobId}/pause`, { method: 'POST' }); await poll(); setReady(d.paused ? 'Пауза' : 'Продолжается', 'Можно продолжить в любой момент.'); }
  catch (e) { showError(e.message); }
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
  if (!state.jobId) return;
  try {
    const d = await api(`/api/jobs/${state.jobId}/files`);
    openModal(
      `<span class="eyebrow">ФАЙЛЫ</span><h2>Что сейчас проверяется</h2>
      <div class="files-box">${esc((d.files || []).join('\n'))}${d.truncated ? '\n… список сокращён' : ''}</div>`,
      `<button class="btn primary" id="filesClose" type="button">Закрыть</button>`
    );
    $('filesClose').addEventListener('click', closeModal);
  } catch (e) { showError(e.message); }
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
  recordRunMetrics(report);
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
  if(els.resultMode) els.resultMode.innerHTML=`<span class="mode-result">${report.task_mode==='modify'?'Mod Lab':'Проверка'} · ${esc(report.repair_mode_label||report.repair_mode||state.repairMode)} · target ${esc(report.beamng_version||'0.39')}</span>`;
  const vs=report.vehicle_status||{};
  if(els.applyStatus){ const branded=vs.status==='repaired-artifact' || !!(vs.branding && (vs.branding.thumbnail_watermark || (vs.branding.info_files||[]).length)); if(branded){ els.applyStatus.hidden=false; els.applyStatus.innerHTML='<b>ModForge</b><span>Название автомобиля и доступные preview/thumbnail-файлы помечены ModForge. Отдельно добавлять UI Apps больше не нужно.</span>'; } else { els.applyStatus.hidden=true; els.applyStatus.innerHTML=''; } }
  els.resultMark.className = 'result-symbol' + (s.ok ? '' : ' warn');
  els.resultMark.textContent = s.ok ? '✓' : '!';
  els.statFiles.textContent = s.files_checked || 0;
  els.statFixed.textContent = s.fixed || 0;
  els.statWarnings.textContent = s.warnings || 0;
  els.statChecks.textContent = s.ok_checks || 0;

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
  state.busy = false;
  els.startBtn.classList.remove('loading','success');
  els.startBtn.classList.add('error');
  els.startLabel.textContent = 'Повторить проверку';
  els.startSpinner.style.display = 'none';
  els.startBtn.disabled = false;
  els.process.hidden = false;
  els.processTitle.textContent = 'Операция не завершена';
  els.processDetail.textContent = msg;
  els.progressState.textContent = 'Нужен повтор';
  els.eta.textContent = '';
  els.result.hidden = false;
  els.resultTitle.textContent = 'Не удалось подготовить результат';
  els.resultLead.textContent = msg;
  els.resultMark.textContent = '!';
  els.resultMark.className = 'result-symbol warn';
  els.issueList.innerHTML = `<article class="issue"><div><span class="tag warning">ОШИБКА</span><b>ModForge остановил операцию</b></div><small>${esc(msg)}</small></article>`;
  els.restartJobBtn.hidden = false;
  els.restartJobBtn.textContent = 'Перезапустить';
  els.resultFileNote.textContent = 'Перезапуск повторит загрузку и обработку текущего выбора без необходимости выбирать файл заново.';
  setReady('Требуется повтор', 'Можно перезапустить текущую задачу.');
  setPhase('error');
  toast(msg, 'error', 7000);
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
async function downloadResult(){const job=loadLastJob();if(!state.jobId&&job?.jobId)state.jobId=job.jobId;if(!state.jobId)return showArtifactError('MF-404','Задание больше не найдено.');const url=state.downloadUrl||`/api/jobs/${state.jobId}/download`;const popup=openDownloadWindow();const original=els.downloadBtn.textContent;els.downloadBtn.disabled=true;els.downloadBtn.textContent='Проверяем файл…';try{const r=await fetch(url,{method:'HEAD',cache:'no-store'});if(!r.ok){let d={};try{d=await r.json()}catch{}throw new Error(`${d.code||`MF-${r.status}`}: ${d.message||'Готовый файл сейчас недоступен.'}`);}startDownloadInWindow(url,popup);els.downloadBtn.textContent='Скачивание запущено';toast('Скачивание запущено в отдельной вкладке. Текущая страница не сбрасывается.','success',3500)}catch(e){try{if(popup&&!popup.closed)popup.close()}catch{}const raw=String(e.message||e);const code=raw.match(/MF-[A-Z0-9-]+/)?.[0]||'MF-404';showArtifactError(code,raw.replace(`${code}: `,''))}finally{setTimeout(()=>{els.downloadBtn.disabled=false;els.downloadBtn.textContent=original},2200)}}
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
   HEALTH CHECK & INIT
══════════════════════════════════════════════════ */
async function loadHealth() {
  try {
    const d = await api('/api/health');
    state.release = d.release_id || d.app_version || state.release;
    state.stages = d.stages || [];
    if (els.brandName) els.brandName.textContent = d.config?.brand_name || 'ModForge';
    if (els.brandSub) els.brandSub.textContent = d.config?.tagline || 'Проверка модов';
    if (els.versionBadge) els.versionBadge.textContent = `${state.release} · BeamNG ${d.beamng_version || '0.39'}`;
    if (els.suffixPreview) els.suffixPreview.textContent = state.suffix || d.config?.default_suffix || 'FIXED';
    renderStages();
    if (d.config?.ad_enabled && d.config?.ad_html) { els.adSlot.innerHTML = d.config.ad_html; els.adSlot.hidden = false; }
    showReleaseFlow();
  } catch (e) {
    state.stages = [];
    renderStages();
    showError(`MF-503: ${e.message}`);
  }
}

// Init sequence
loadProfile();
loadDraft();
updateNetworkUI();
applyProfile();
applyRepairModeUI();
applyTaskModeUI();
renderStages();
loadHealth().then(() => tryRestoreOnLoad());

})();

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
  const origClick = els.copyJobBtn.onclick;
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
