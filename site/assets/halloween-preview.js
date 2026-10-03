(() => {
  'use strict';
  const root=document.documentElement;
  const CLICKS='mf-halloween-preview-clicks-2026';
  const ACTIVE='mf-halloween-preview-active-2026';
  const SNAPSHOT='mf-halloween-previous-profile-2026';
  const LIMIT=31;
  const season=()=>{const d=new Date();return d.getMonth()===9 && d.getDate()>=1 && d.getDate()<=31;};
  const getClicks=()=>Number(localStorage.getItem(CLICKS)||0);
  const setClicks=n=>localStorage.setItem(CLICKS,String(Math.max(0,n)));
  const isActive=()=>localStorage.getItem(ACTIVE)==='1';
  const setActive=active=>{localStorage.setItem(ACTIVE,active?'1':'0');root.classList.toggle('halloween-preview-active',active);window.dispatchEvent(new CustomEvent('modmendryx:halloween-state',{detail:{active}}));};
  function bridge(){return window.__mfHalloweenBridge;}
  function toast(msg,type='info'){bridge()?.toast?.(msg,type,3000);}
  function saveSnapshot(){const p=bridge()?.getProfile?.();if(p)localStorage.setItem(SNAPSHOT,JSON.stringify(p));}
  function loadSnapshot(){try{return JSON.parse(localStorage.getItem(SNAPSHOT)||'null')}catch{return null}}
  function applyHalloweenProfile(){const b=bridge();if(!b)return false;const current=b.getProfile?.();if(!current)return false;saveSnapshot();return b.applyProfile?.({...current,accent:'custom',customColor:'#9b532f',density:'compact',uiPerformance:'standard'})!==false;}
  function restorePrevious(){
    const b=bridge();
    const saved=loadSnapshot();
    const restored=!!(saved && b?.restoreProfile?.(saved));
    if(!restored) b?.restoreProfile?.({id:b?.getProfile?.()?.id||'',name:b?.getProfile?.()?.name||'Гость',accent:'orange',customColor:'#f47b20',density:'comfortable',reducedMotion:false,uiPerformance:'standard'});
    localStorage.removeItem(SNAPSHOT);setClicks(0);setActive(false);
    b?.toast?.(restored?'Предыдущая персонализация восстановлена.':'Включён стандартный интерфейс.', 'success',3200);
  }
  function showActivationWarning(){
    const b=bridge();
    const content='<span class="eyebrow">HALLOWEEN · 31</span><h2>Включить предварительный Halloween-интерфейс?</h2><p class="modal-lead">Текущая персонализация будет временно заменена приглушённой Halloween-палитрой и компактным профилем. Старая персонализация сохранится и будет доступна через «Восстановить предыдущий интерфейс».</p><p class="micro">Ваши файлы, история, черновики и серверные задачи не удаляются.</p>';
    const actions='<button class="btn" id="halloweenCancel" type="button">Отмена</button><button class="btn primary" id="halloweenConfirm" type="button">Включить Halloween</button>';
    if(!b?.openModal){if(window.confirm('Halloween временно заменит текущую персонализацию. Старые настройки будут сохранены. Включить?'))activate();return;}
    b.openModal(content,actions);
    document.getElementById('halloweenCancel')?.addEventListener('click',()=>b.closeModal());
    document.getElementById('halloweenConfirm')?.addEventListener('click',()=>{b.closeModal();activate();});
  }
  function activate(){if(!applyHalloweenProfile())return;setClicks(0);setActive(true);toast('Предварительный Halloween-интерфейс активирован.','success');}
  function deactivate(){setClicks(0);const saved=loadSnapshot();const b=bridge();if(saved&&b?.restoreProfile?.(saved))localStorage.removeItem(SNAPSHOT);setActive(false);toast('Предварительный Halloween-интерфейс отключён.','info');}
  function onBrandClick(e){
    if(!season())return;
    const active=isActive(); const next=getClicks()+1;
    if(next<LIMIT){setClicks(next);return;}
    e.preventDefault();e.stopImmediatePropagation();
    if(active)deactivate();else showActivationWarning();
  }
  function bind(){
    const brand=document.getElementById('brand'); if(!brand || brand.dataset.mfHalloweenPreviewBound)return;
    brand.dataset.mfHalloweenPreviewBound='1'; document.addEventListener('click',e=>{if(e.target.closest?.('#brand'))onBrandClick(e);},true);
    const restore=document.getElementById('halloweenRestoreBtn');restore?.addEventListener('click',restorePrevious);
    if(isActive())root.classList.add('halloween-preview-active');
    window.dispatchEvent(new CustomEvent('modmendryx:halloween-state',{detail:{active:isActive()}}));
  }
  window.addEventListener('modmendryx:personalization-changed',()=>{if(!isActive())return;localStorage.removeItem(SNAPSHOT);setClicks(0);setActive(false);toast('Halloween отключён: персонализация изменена.','info');});
  window.addEventListener('modmendryx:language-changed',()=>{if(!isActive())return;localStorage.removeItem(SNAPSHOT);setClicks(0);setActive(false);});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
