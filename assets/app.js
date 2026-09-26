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
};
const SESSION_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days

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
  'brandName','brandSub','versionBadge','adSlot','brand','feedbackTop','feedbackFooter','resultFeedbackBtn',
  'zipBtn','folderBtn','fileBtn','zipInput','folderInput','fileInput',
  'dropzone','dropTitle','dropSub','selection',
  'priorityChips','wishes','outputType','repairMode','modeInfo','vehicleDetect','vehicleDetectTitle','vehicleDetectMeta','resultMode','applyStatus',
  'settingsBtn','settingsTop','suffixPreview','clearBtn',
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
  'toastContainer','snakePromoBtn'
].forEach(id => els[id] = $(id));

/* ══════════════════════════════════════════════════
   APP STATE
══════════════════════════════════════════════════ */
const state = {
  files: [], kind: '', sourceName: '',
  jobId: null, pollTimer: null,
  priority: new Set(),
  suffix: localStorage.getItem(SK.SUFFIX) || 'FIXED',
  repairMode: localStorage.getItem('mf_repair_mode') || 'standard',
  release: 'v1 (0.31-beta)',
  stages: [],
  busy: false,
  uploadXhr: null,
  lastRun: null,
  downloadUrl: null,
  downloadName: null,
};

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

    if (job.status === 'running' || job.status === 'processing' || job.status === 'paused' || job.status === 'queued' || job.status === 'rebuilding') {
      saveSession({ ...candidate, jobId: candidate.jobId, stageIndex: job.stage_index || 0 });
      beginVisual();
      setPhase('processing');
      poll();
      toast('Сохранённая задача восстановлена автоматически', 'success', 4000);
    } else if (job.status === 'done') {
      if (job.report) renderResult(job.report);
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

function showGame() {
  if (!els.gameOverlay) return;
  els.gameOverlay.hidden = false;
  if (!snake) snake = new Snake(els.snakeCanvas);
  if (els.snakeHi) els.snakeHi.textContent = parseInt(localStorage.getItem(SK.SNAKE_HI) || '0');
}

function hideGame() {
  if (!els.gameOverlay) return;
  els.gameOverlay.hidden = true;
}

if (els.gameMinimize) els.gameMinimize.addEventListener('click', () => {
  const panel = els.gameOverlay.querySelector('.game-panel');
  gameMinimized = !gameMinimized;
  if (panel) panel.style.height = gameMinimized ? '50px' : '';
  const canvas = els.snakeCanvas;
  if (canvas) canvas.style.display = gameMinimized ? 'none' : '';
  els.gameMinimize.textContent = gameMinimized ? '□' : '─';
});
if (els.gameClose) els.gameClose.addEventListener('click', hideGame);
if (els.snakePromoBtn) els.snakePromoBtn.addEventListener('click', showGame);

/* ══════════════════════════════════════════════════
   API
══════════════════════════════════════════════════ */
async function api(url, opts = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 16000);
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal, headers: { ...(opts.headers || {}), 'Cache-Control': 'no-cache' } });
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
  els.stageGrid.innerHTML = state.stages.map((s, i) =>
    `<article class="stage" data-stage="${i+1}">
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
  els.pauseBtn.textContent = job.status === 'paused' ? 'Продолжить' : 'Пауза';

  // Transition from preparing → processing when first real stage starts
  if (idx >= 1 && document.documentElement.getAttribute('data-phase') === 'preparing') {
    setPhase('processing');
  }

  // Save session continuously
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
    <p class="modal-lead">Крупное обновление. Ниже только то, что реально изменилось.</p>
    <div class="change-grid">
      <section><b>ИСПРАВЛЕНО</b><ul>
        <li>Кнопки «Пауза» и «Файлы» скрыты на этапе подготовки.</li>
        <li>Корректная смена фаз ПОДГОТОВКА → ОБРАБОТКА.</li>
        <li>Восстановление после F5 и случайных обрывов.</li>
      </ul></section>
      <section><b>ДОБАВЛЕНО</b><ul>
        <li>Змейка — мини-игра во время загрузки файла.</li>
        <li>Сохранение сессии до 7 дней с восстановлением.</li>
        <li>Анимированный фон с частицами.</li>
        <li>Тост-уведомления о ключевых событиях.</li>
      </ul></section>
      <section><b>ОСТАЛОСЬ</b><ul>
        <li>BeamNG.drive 0.39 — целевая версия.</li>
        <li>Консервативные автоисправления.</li>
        <li>11 этапов с повторной проверкой.</li>
      </ul></section>
    </div>`,
    `<button class="btn primary" id="relCont" type="button">Понятно</button>`
  );
  $('relCont').addEventListener('click', () => { localStorage.setItem(SK.RELEASE, state.release); closeModal(); if (np) showPrivacy(ng); else if (ng) showGuide(); });
}

function showPrivacy(ng) {
  openModal(
    `<span class="eyebrow">ПЕРВЫЙ ВХОД</span><h2>Политика конфиденциальности</h2>
    <p>Файл нужен только для обработки задания. ModForge использует временную рабочую копию для проверки и создания результата. Сервис не должен использовать загруженный мод как публичную раздачу.</p>
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
    <p class="micro">💡 Во время загрузки откроется мини-игра Змейка — держит вас в тонусе!</p>`,
    `<button class="btn primary" id="guideDone" type="button">Начать работу</button>`
  );
  $('guideDone').addEventListener('click', () => { localStorage.setItem(SK.GUIDE, '1'); closeModal(); });
}

/* ══════════════════════════════════════════════════
   REPAIR MODE
══════════════════════════════════════════════════ */
els.repairMode?.querySelectorAll('.mode-card').forEach(card=>card.addEventListener('click',()=>{state.repairMode=card.dataset.mode||'standard';localStorage.setItem('mf_repair_mode',state.repairMode);applyRepairModeUI();saveDraft();}));
els.modeInfo?.addEventListener('click',()=>{openModal(`<span class=\"eyebrow\">РЕЖИМЫ ИСПРАВЛЕНИЯ</span><h2>Глубина ремонта</h2><div class=\"mode-explain\"><section><b>Стандартный</b><p>Безопасные подтверждённые исправления; спорные случаи остаются в отчёте.</p></section><section><b>Средний</b><p>Добавляется более глубокий подбор ресурсов, исправление типовых ошибок конфигурации и дополнительные JBeam-проверки.</p></section><section><b>Агрессивный</b><p>Добавляется эвристический ремонт неоднозначных ресурсов и очевидно нулевых параметров физики с повторной проверкой.</p></section></div>`,`<button class=\"btn primary\" id=\"modeInfoClose\" type=\"button\">Понятно</button>`);$('modeInfoClose')?.addEventListener('click',closeModal);});

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
  openModal(
    `<span class="eyebrow">НАСТРОЙКИ</span><h2>Персонализация</h2>
    <label class="field-label">Суффикс результата</label>
    <input class="field" id="suffixInput" maxlength="48" value="${esc(state.suffix)}">
    <span class="micro">FIXED → CLEAN → REPAIRED или любое своё.</span>`,
    `<button class="btn" id="sCancel" type="button">Отмена</button>
     <button class="btn primary" id="sSave" type="button">Сохранить</button>`
  );
  $('sCancel').addEventListener('click', closeModal);
  $('sSave').addEventListener('click', () => {
    state.suffix = $('suffixInput').value.trim() || 'FIXED';
    localStorage.setItem(SK.SUFFIX, state.suffix);
    els.suffixPreview.textContent = state.suffix;
    saveDraft();
    closeModal();
    toast('Настройки сохранены', 'success', 2000);
  });
}
els.settingsBtn.addEventListener('click', showSettings);
els.settingsTop.addEventListener('click', showSettings);

/* ══════════════════════════════════════════════════
   FILE PICKER STATE
══════════════════════════════════════════════════ */
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
  const total = state.files.reduce((s, f) => s + f.size, 0);
  detectVehicle(state.files);
  els.selection.hidden = false;
  const type = state.kind === 'zip' ? 'ZIP' : state.kind === 'folder' ? 'Папка' : 'Файл';
  setPickerVisual(state.kind);
  saveDraft();
  els.selection.innerHTML = `<strong>${esc(state.sourceName)}</strong><span>${type} · ${state.files.length} объектов · ${bytes(total)}</span>`;
  const valid = state.files.length > 0 && total <= 2 * 1024 * 1024 * 1024;
  els.startBtn.disabled = !valid || state.busy;
  setReady(valid ? 'Готово к проверке' : 'Нужен поддерживаемый файл', 'Перед запуском ModForge проверит связь с backend.');
  if (valid) checkFileAgainstSession(state.files);
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
}));

els.outputType?.addEventListener('change', saveDraft);
els.wishes?.addEventListener('input', saveDraft);

/* ══════════════════════════════════════════════════
   RESET UI
══════════════════════════════════════════════════ */
function resetUI() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  if (state.uploadXhr) { state.uploadXhr.abort(); state.uploadXhr = null; }
  state.pollTimer = null; state.jobId = null;
  state.files = []; state.kind = ''; state.sourceName = ''; state.busy = false;
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
  els.downloadUrl = null;
  els.resultFileNote.textContent = '';
  state.downloadUrl = null;
  state.downloadName = null;
  els.dropTitle.textContent = 'Выберите то, что хотите проверить';
  els.dropSub.textContent = 'ZIP-архив, папка мода или отдельный BeamNG-файл.';
  setReady('Ожидается файл', 'Перед запуском ModForge проверит связь с backend.');
  setPhase('idle');
  renderStages();
  hideGame();
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
  els.stageCount.textContent = `0 / ${state.stages.length || 12}`;
  els.progressState.textContent = 'Проверяем связь с backend…';
  els.eta.textContent = 'Подключение…';
}

/* ══════════════════════════════════════════════════
   START UPLOAD
══════════════════════════════════════════════════ */
async function startUpload() {
  if (!state.files.length || state.busy) return;
  beginVisual();
  state.lastRun = { kind: state.kind, sourceName: state.sourceName, wishes: els.wishes.value, priority: Array.from(state.priority), outputType: els.outputType.value, suffix: state.suffix };
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
  fd.append('output_suffix', state.suffix || 'FIXED');
  fd.append('manifest_json', JSON.stringify(state.files.map(f => f.webkitRelativePath || f.name)));
  state.files.forEach(f => fd.append('files', f, f.name));

  els.startLabel.textContent = 'Загрузка…';
  els.progressState.textContent = 'Передаём файлы на сервер…';

  // Show snake game during upload
  showGame();
  toast('Файл загружается. Сыграйте пока в Змейку! 🐍', 'info', 5000);

  const xhr = new XMLHttpRequest();
  state.uploadXhr = xhr;
  xhr.open('POST', '/api/analyze', true);
  xhr.timeout = 20 * 60 * 1000;

  let uploadStart = Date.now();
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round(e.loaded / e.total * 100);
    const elapsed = (Date.now() - uploadStart) / 1000;
    const speed = e.loaded / elapsed;
    const rem = (e.total - e.loaded) / speed;
    els.progressBar.style.width = `${p}%`;
    els.overallPct.textContent = `${p}%`;
    els.progressState.textContent = `Загрузка · ${p}% · ${bytes(speed)}/с`;
    els.eta.textContent = `До обработки: ~${Math.max(1, Math.ceil(rem))} сек.`;
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
    const lastJob = { jobId: d.job_id, fingerprint: fp, sourceName: state.sourceName, kind: state.kind, priority: [...state.priority], wishes: els.wishes.value || '', outputType: out, suffix: state.suffix, repairMode: state.repairMode }; 
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
    const job = await api(`/api/jobs/${state.jobId}`);
    setStageUI(job);

    if (job.status === 'done') {
      renderResult(job.report);
      hideGame();
      clearSession();
      saveLastJob({ ...(loadLastJob() || {}), jobId: state.jobId, sourceName: state.sourceName || (loadLastJob()?.sourceName || ''), repairMode: job.repair_mode || state.repairMode, kind: state.kind });
      return;
    }
    if (job.status === 'error') { showError(job.error || job.stage_detail || 'MF-503: ошибка обработки.'); hideGame(); clearSession(); return; }
    if (job.status === 'cancelled') { showError('MF-CANCELLED: обработка остановлена пользователем.'); hideGame(); clearSession(); return; }

    state.pollTimer = setTimeout(poll, 700);
  } catch (e) { showError(e.message); }
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

/* ══════════════════════════════════════════════════
   RESULT
══════════════════════════════════════════════════ */
function renderResult(report) {
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

  const s = report.summary || {};
  els.resultTitle.textContent = s.ok ? 'Результат готов' : 'Результат готов с предупреждениями';
  els.resultLead.textContent = `Исправлено: ${s.fixed || 0}. Предупреждений: ${s.warnings || 0}.`;
  if(els.resultMode) els.resultMode.innerHTML=`<span class="mode-result">Режим: ${esc(report.repair_mode_label||report.repair_mode||state.repairMode)}</span>`;
  const vs=report.vehicle_status||{};
  if(els.applyStatus){ if(vs.vehicle_status_app){ els.applyStatus.hidden=false; els.applyStatus.innerHTML='<b>ModForge Status</b><span>Прозрачный индикатор добавлен в ZIP. В BeamNG добавьте его в UI Apps один раз.</span>'; } else { els.applyStatus.hidden=true; els.applyStatus.innerHTML=''; } }
  els.resultMark.className = 'result-symbol' + (s.ok ? '' : ' warn');
  els.resultMark.textContent = s.ok ? '✓' : '!';
  els.statFiles.textContent = s.files_checked || 0;
  els.statFixed.textContent = s.fixed || 0;
  els.statWarnings.textContent = s.warnings || 0;
  els.statChecks.textContent = s.ok_checks || 0;

  els.issueList.innerHTML = (report.issues || []).map(x => {
    const cls = x.level === 'fixed' ? 'fixed' : x.level === 'warning' ? 'warning' : x.level === 'ok' ? 'ok' : 'info';
    const lab = x.level === 'fixed' ? 'ИСПРАВЛЕНО' : x.level === 'warning' ? 'ПРЕДУПРЕЖДЕНИЕ' : x.level === 'ok' ? 'OK' : 'ИНФО';
    return `<article class="issue"><div><span class="tag ${cls}">${lab}</span><b>${esc(x.title || 'Результат')}</b></div><small>${esc(x.details || '')}</small></article>`;
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
    <div class="feedback-form"><input class="field" id="feedbackName" maxlength="40" placeholder="Ваше имя (необязательно)"><input class="field" id="feedbackEmail" maxlength="160" type="email" placeholder="Email для ответа (необязательно)"><textarea class="field" id="feedbackMessage" maxlength="1200" rows="4" placeholder="Опишите проблему или предложение"></textarea><div class="feedback-form-actions"><button class="btn primary" id="feedbackSend" type="button">Отправить сообщение</button><button class="btn" id="feedbackAdmin" type="button">${sessionStorage.getItem(SK.ADMIN_KEY) ? 'Выйти из режима автора' : 'Я автор'}</button><span id="feedbackHint" class="micro"></span></div></div>
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

/* ══════════════════════════════════════════════════
   HEALTH CHECK & INIT
══════════════════════════════════════════════════ */
async function loadHealth() {
  try {
    const d = await api('/api/health');
    state.release = d.app_version || state.release;
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
loadDraft();
applyRepairModeUI();
renderStages();
tryRestoreOnLoad().then(() => loadHealth());

})();
