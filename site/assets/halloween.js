(() => {
  'use strict';
  const root = document.documentElement;
  const styleId = 'mfHalloweenStyles';
  const now = () => new Date();
  const inSeason = () => now().getMonth() === 9 && now().getDate() >= 1 && now().getDate() <= 31;
  const isDay31 = () => inSeason() && now().getDate() === 31;
  const styles = `
  html.halloween-season { --halloween-orange:#a65a32; --halloween-orange-strong:#c97846; --halloween-ink:#0b0908; }
  html.halloween-season body::before{background:radial-gradient(circle at 14% 18%,rgba(166,90,50,.10),transparent 34%),radial-gradient(circle at 82% 72%,rgba(96,42,22,.10),transparent 38%)}
  html.halloween-season .release-pill::after{content:'OCT';margin-left:6px;color:#c97846;font-size:8px;letter-spacing:.12em}
  html.halloween-preview-active { --accent:#a65a32 !important; --accent-rgb:166 90 50 !important; --accent-soft:rgb(166 90 50 / .10) !important; --accent-line:rgb(166 90 50 / .42) !important; --accent-strong:#c97846 !important; }
  html.halloween-preview-active .topbar,html.halloween-preview-active .panel,html.halloween-preview-active .config-box,html.halloween-preview-active .dropzone,html.halloween-preview-active .process,html.halloween-preview-active .result,html.halloween-preview-active .interface-info-card,html.halloween-preview-active .modal-card{box-shadow:0 18px 58px rgba(52,25,15,.18),inset 0 1px 0 rgba(255,255,255,.018)}
  html.halloween-preview-active .start-button,html.halloween-preview-active .btn.primary{background:linear-gradient(135deg,#8f4929,#b5653b);color:#fff;border-color:rgba(255,255,255,.12)}
  html.halloween-preview-active .brand{padding:4px 7px;border:1px solid rgba(166,90,50,.24);border-radius:9px;background:rgba(11,9,8,.78)}
  html.halloween-preview-active .brand img{filter:sepia(.20) saturate(.85) brightness(.82);background:rgba(0,0,0,.24);border-radius:7px}
  html.halloween-preview-active .hero-banner-media{border-color:rgba(166,90,50,.24)}
  html.halloween-preview-active .preparation-state{color:#d28a5d;border-color:rgba(166,90,50,.38);background:rgba(92,46,26,.14)}
  html.halloween-preview-active .halloween-restore-btn{display:inline-flex}
  html.halloween-preview-active .hero-tags span{border-color:rgba(166,90,50,.18);background:rgba(166,90,50,.045)}
  html.halloween-preview-active .halloween-restore-btn{border-color:rgba(166,90,50,.36);color:#d28a5d}
  html.halloween-day .hero-banner-media::after{content:'31 OCT';position:absolute;top:10px;right:12px;padding:5px 7px;border:1px solid rgba(166,90,50,.35);border-radius:5px;background:rgba(20,8,3,.72);color:#d58a5c;font:800 8px/1 ui-monospace,monospace;letter-spacing:.12em}
  .mf-pumpkin{position:fixed;z-index:9999;border:0;background:transparent;font-size:clamp(34px,5vw,62px);line-height:1;padding:0;cursor:pointer;filter:drop-shadow(0 8px 16px rgba(166,90,50,.30));opacity:0;transform:var(--pumpkin-hidden,translate(0,0)) scale(.78);transition:opacity .25s ease,transform .95s cubic-bezier(.22,.7,.2,1),filter .45s ease;pointer-events:auto;}
  .mf-pumpkin.show{opacity:1;transform:var(--pumpkin-peek,translate(0,0)) scale(1)}
  .mf-pumpkin.warning{filter:drop-shadow(0 0 14px rgba(220,45,45,.72)) saturate(1.5) hue-rotate(-12deg);}
  .mf-pumpkin.returning{opacity:0;transform:var(--pumpkin-hidden) scale(.82);}
  .mf-pumpkin.caught{transform:var(--pumpkin-peek) scale(1.28) rotate(-12deg);opacity:0;transition:.16s}
  `;
  function ensureStyles(){
    if(!inSeason()) return;
    let el=document.getElementById(styleId);
    if(!el){el=document.createElement('style');el.id=styleId;el.textContent=styles;document.head.appendChild(el);}
    root.classList.add('halloween-season');
    root.classList.toggle('halloween-day',isDay31());
  }
  let pumpkinTimer=null, pumpkinId=0;
  function pumpkinEnabled(){ return root.classList.contains('halloween-preview-active') && ['preparing','processing'].includes(root.getAttribute('data-phase')||''); }
  function spawnPumpkin(){
    if(!pumpkinEnabled() || document.querySelector('.mf-pumpkin')) return;
    const p=document.createElement('button'); p.type='button'; p.className='mf-pumpkin'; p.setAttribute('aria-label','Поймать хэллоуинскую тыкву'); p.textContent='🎃'; p.dataset.pumpkinId=String(++pumpkinId);
    const edge=Math.floor(Math.random()*4); const pos=(16+Math.random()*68); const peek='24px';
    if(edge===0){p.style.left=`calc(${pos}vw - 24px)`;p.style.top='-30px';p.style.setProperty('--pumpkin-hidden','translateY(-38px)');p.style.setProperty('--pumpkin-peek',`translateY(${peek})`);}
    else if(edge===1){p.style.right='-30px';p.style.top=`calc(${pos}vh - 24px)`;p.style.setProperty('--pumpkin-hidden','translateX(38px)');p.style.setProperty('--pumpkin-peek',`translateX(-${peek})`);}
    else if(edge===2){p.style.left=`calc(${pos}vw - 24px)`;p.style.bottom='-30px';p.style.setProperty('--pumpkin-hidden','translateY(38px)');p.style.setProperty('--pumpkin-peek',`translateY(-${peek})`);}
    else {p.style.left='-30px';p.style.top=`calc(${pos}vh - 24px)`;p.style.setProperty('--pumpkin-hidden','translateX(-38px)');p.style.setProperty('--pumpkin-peek',`translateX(${peek})`);}
    document.body.appendChild(p);
    requestAnimationFrame(()=>p.classList.add('show'));
    const remove=()=>p.remove();
    p.addEventListener('click',()=>{p.classList.add('caught');setTimeout(remove,170);try{window.dispatchEvent(new CustomEvent('modmendryx:toast',{detail:'🎃 Ты поймал тыкву!'}));}catch{}},{once:true});
    // After three seconds without a click, mark the pumpkin red and return it to the same edge.
    setTimeout(()=>{if(!p.isConnected)return;p.classList.add('warning');setTimeout(()=>{if(!p.isConnected)return;p.classList.add('returning');setTimeout(remove,980);},260);},3000);
  }
  function pumpkinLoop(){
    clearTimeout(pumpkinTimer);
    if(!pumpkinEnabled()) return;
    pumpkinTimer=setTimeout(()=>{spawnPumpkin();pumpkinLoop();},5200+Math.random()*4200);
  }
  window.addEventListener('modmendryx:phase',()=>{
    if(pumpkinEnabled()){if(!document.querySelector('.mf-pumpkin'))spawnPumpkin();pumpkinLoop();}
    else{document.querySelectorAll('.mf-pumpkin').forEach(x=>x.remove());clearTimeout(pumpkinTimer);}
  });
  window.addEventListener('modmendryx:halloween-state',e=>{
    const active=!!e.detail?.active;
    root.classList.toggle('halloween-preview-active',active);
    if(!active){document.querySelectorAll('.mf-pumpkin').forEach(x=>x.remove());clearTimeout(pumpkinTimer);} else pumpkinLoop();
  });
  ensureStyles();
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{ensureStyles();pumpkinLoop();},{once:true});else pumpkinLoop();
  setInterval(()=>{ensureStyles();pumpkinLoop();},60000);
})();
