(() => {
  const root=document.documentElement;
  const storageKey='modforge-halloween-clicks-2026';
  const now=()=>new Date();
  const inSeason=()=>{const d=now();return d.getMonth()===9 && d.getDate()>=1 && d.getDate()<=31;};
  const isDay31=()=>inSeason() && now().getDate()===31;
  const styles=`
  html.halloween-season body::before{background:radial-gradient(circle at 15% 20%,rgba(154,64,255,.10),transparent 34%),radial-gradient(circle at 80% 75%,rgba(255,102,0,.08),transparent 36%)}
  html.halloween-season .release-pill::after{content:'OCT';margin-left:6px;color:#d9a4ff;font-size:8px;letter-spacing:.12em}
  html.halloween-season .brand-task-dot.active{background:#b86bff;box-shadow:0 0 0 0 rgba(184,107,255,.45)}
  html.halloween-day{--halloween-primary:#ff7b00;--halloween-secondary:#b26cff}
  html.halloween-day .panel,html.halloween-day .config-box{border-color:rgba(255,123,0,.18)}
  html.halloween-day .hero-banner-media::after{content:'31 OCT';position:absolute;top:10px;right:12px;padding:5px 7px;border:1px solid rgba(255,123,0,.35);border-radius:5px;background:rgba(20,8,0,.72);color:#ff9f4c;font:800 8px/1 ui-monospace,monospace;letter-spacing:.12em}
  html.halloween-egg body::after{content:'MODFORGE // 31 CLICKS';position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:9998;padding:7px 10px;border:1px solid rgba(195,140,255,.48);border-radius:5px;background:rgba(7,4,12,.92);color:#d9b9ff;font:800 8px/1 ui-monospace,monospace;letter-spacing:.18em;box-shadow:0 0 30px rgba(141,73,255,.15);pointer-events:none}
  html.halloween-egg .brand img{filter:sepia(.35) hue-rotate(228deg) saturate(1.28)}
  html.halloween-egg .hero{box-shadow:0 0 0 1px rgba(191,118,255,.08),0 24px 90px rgba(98,48,140,.10)}
  `;
  function inject(){if(!inSeason())return;let st=document.getElementById('mfHalloweenStyles');if(!st){st=document.createElement('style');st.id='mfHalloweenStyles';st.textContent=styles;document.head.appendChild(st);}root.classList.add('halloween-season');if(isDay31())root.classList.add('halloween-day');else root.classList.remove('halloween-day');
    const clicks=Number(sessionStorage.getItem(storageKey)||'0'); if(clicks>=31)root.classList.add('halloween-egg');
  }
  function bind(){const brand=document.getElementById('brand') || document.querySelector('.brand-button');if(!brand||!inSeason())return;brand.addEventListener('click',()=>{let clicks=Number(sessionStorage.getItem(storageKey)||'0')+1;sessionStorage.setItem(storageKey,String(clicks));if(clicks===31){root.classList.add('halloween-egg');try{window.dispatchEvent(new CustomEvent('modforge:toast',{detail:'Пасхалка активирована · 31 нажатие'}));}catch{} }});}
  inject(); if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();setInterval(inject,60000);
})();
