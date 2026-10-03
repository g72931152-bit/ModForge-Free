(() => {
  const root = document.documentElement;
  const CLICK_KEY = 'modforge-halloween-clicks-2026';
  const UNLOCK_KEY = 'modforge-halloween-unlocked-2026';
  const styleId = 'mfHalloweenStyles';
  const now = () => new Date();
  const inSeason = () => now().getMonth() === 9 && now().getDate() >= 1 && now().getDate() <= 31;
  const isDay31 = () => inSeason() && now().getDate() === 31;
  const styles = `
  html.halloween-season { --halloween-primary:#c483ff; --halloween-secondary:#ff8a3d; }
  html.halloween-season body::before{background:radial-gradient(circle at 14% 18%,rgba(139,75,255,.12),transparent 35%),radial-gradient(circle at 82% 72%,rgba(255,105,24,.09),transparent 38%)}
  html.halloween-season .release-pill::after{content:'OCT';margin-left:6px;color:#d9a4ff;font-size:8px;letter-spacing:.12em}
  html.halloween-egg { --accent:#c77dff; --accent-rgb:199,125,255; --accent-soft:rgba(199,125,255,.10); --accent-line:rgba(199,125,255,.42); --accent-strong:#e0b1ff; }
  html.halloween-egg .topbar,html.halloween-egg .panel,html.halloween-egg .config-box,html.halloween-egg .dropzone,html.halloween-egg .process,html.halloween-egg .result,html.halloween-egg .interface-info-card,html.halloween-egg .modal-card{box-shadow:0 18px 70px rgba(94,37,130,.16),inset 0 1px 0 rgba(255,255,255,.015)}
  html.halloween-egg .start-button,html.halloween-egg .btn.primary{background:linear-gradient(135deg,#a85cff,#ff7a32);color:#fff;border-color:rgba(255,255,255,.16)}
  html.halloween-egg .brand img{filter:sepia(.28) hue-rotate(226deg) saturate(1.35)}
  html.halloween-egg .hero-banner-media{border-color:rgba(199,125,255,.28)}
  html.halloween-egg .preparation-state{color:#dda9ff;border-color:rgba(199,125,255,.38);background:rgba(96,51,128,.16)}
  html.halloween-egg::after{content:'MODFORGE // NIGHT MODE';position:fixed;right:14px;bottom:14px;z-index:10;padding:7px 9px;border:1px solid rgba(199,125,255,.35);border-radius:6px;background:rgba(9,5,14,.9);color:#d9b9ff;font:800 8px/1 ui-monospace,monospace;letter-spacing:.16em;pointer-events:none}
  html.halloween-day .hero-banner-media::after{content:'31 OCT';position:absolute;top:10px;right:12px;padding:5px 7px;border:1px solid rgba(255,126,61,.35);border-radius:5px;background:rgba(20,8,0,.72);color:#ffaf73;font:800 8px/1 ui-monospace,monospace;letter-spacing:.12em}
  `;
  function ensureStyles(){ if(!inSeason()) return; let el=document.getElementById(styleId); if(!el){el=document.createElement('style');el.id=styleId;el.textContent=styles;document.head.appendChild(el);} root.classList.add('halloween-season'); root.classList.toggle('halloween-day',isDay31()); const unlocked=localStorage.getItem(UNLOCK_KEY)==='1' || Number(localStorage.getItem(CLICK_KEY)||0)>=31; root.classList.toggle('halloween-egg',unlocked); }
  function clicks(){ return Number(localStorage.getItem(CLICK_KEY)||0); }
  function bind(){ const target=document.getElementById('brand') || document.querySelector('.brand-button'); if(!target || target.dataset.mfHalloweenBound) return; target.dataset.mfHalloweenBound='1'; target.addEventListener('click',()=>{ if(!inSeason()) return; const n=clicks()+1; localStorage.setItem(CLICK_KEY,String(n)); if(n>=31){ localStorage.setItem(UNLOCK_KEY,'1'); root.classList.add('halloween-egg'); try{window.dispatchEvent(new CustomEvent('modforge:toast',{detail:'Хэллоуин-режим активирован · 31 нажатие'}));}catch{} } }); }
  ensureStyles(); if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{bind();ensureStyles()},{once:true}); else bind(); setInterval(ensureStyles,60000);
})();