(() => {
  'use strict';
  const KEY = 'mf_language';
  const DICT = {
    'Закрыть':'Close','История сессий':'Session history','Прошлые сессии':'Previous sessions','Хранятся локально на этом устройстве. Серверные результаты могут истечь по сроку хранения.':'Stored locally on this device. Server-side results may expire after the retention period.','Очистить историю':'Clear history',
    'Мини-игры':'Mini-games','ПОКА ИДЁТ ЗАДАЧА':'WHILE A TASK IS RUNNING','Счёт':'Score','Рекорд':'Best','Свернуть':'Minimize','Игра':'Game','ГОТОВЬСЯ':'GET READY','Пробел или тап для старта':'Press Space or tap to start',
    'Палитра':'Palette','Профиль':'Profile','Профиль и персонализация':'Profile and personalization','Гость':'Guest','Локальный профиль':'Local profile','Настройки':'Settings','Рабочее пространство готово':'Workspace ready','Настроить профиль':'Customize profile',
    'Входные данные':'Input','Сбросить':'Reset','Выберите то, что хотите проверить':'Choose what you want to check','ZIP-архив, папка мода или отдельный BeamNG-файл.':'ZIP archive, mod folder or a single BeamNG resource.','Папка':'Folder','Файл':'File',
    'Режим интерфейса':'Interface mode','Simple → Advanced':'Simple → Advanced','Advanced → Simple':'Advanced → Simple','Диагностика, безопасный ремонт и повторная проверка в отдельном контуре.':'Diagnostics, safe repair and verification in a separate workflow.','Изолированная лаборатория: выбрать вариант, изменить параметры и отдельно экспортировать результат.':'Isolated lab: choose a variant, change parameters and export separately.',
    'Что проверять в первую очередь':'What to check first','Можно выбрать несколько':'Choose multiple','Текстуры':'Textures','Стекло':'Glass','Освещение':'Lighting','Конфигурации':'Configurations','Колёса':'Wheels','Звуки':'Sounds','Материалы':'Materials','Полная проверка':'Full check','Выбор не отключает остальные проверки: после прицельной проверки ModMendryx всё равно проходит типовые проблемы.':'This only sets priority; the full set of common checks still runs.',
    'Опишите проблему своими словами':'Describe the problem in your own words','Можно без терминов':'No technical terms required','Пока ничего не выбрано':'Nothing selected yet','Диагностировать':'Diagnose','Сравнить моды':'Compare mods','Открыть Resource Inspector':'Open Resource Inspector','VE 1 · рабочее изменение':'VE 1 · workspace change','Текстовое задание':'Text request','Мягче':'Softer','Жёстче':'Stiffer','Двигатель +10%':'Engine +10%','+2 конфигурации':'+2 configurations',
    'Режим исправления VA 2':'VA 2 repair mode','Глубина':'Depth','Стандартный':'Standard','Средний':'Medium','Агрессивный':'Aggressive','Чем отличаются режимы':'How modes differ','Подтверждённые изменения и базовая целостность.':'Confirmed changes and baseline integrity.','Глубже: связанные ресурсы и типовые проблемы.':'Deeper checks for linked resources and common problems.','Самая глубокая проверка и повторная валидация.':'Deepest checks and result validation.',
    'Формат результата':'Output format','До старта':'Before start','Исправленный ZIP':'Repaired ZIP','Тот же формат (один файл)':'Same format (single file)','Папка и набор файлов → ZIP с сохранением структуры.':'Folders and file sets are exported as ZIP while preserving structure.',
    'Скорость обработки':'Processing speed','Отдельно от глубины Repair':'Independent from repair depth','Стандарт':'Standard','Обычная':'Normal','Быстрее':'Faster','Приоритет скорости':'Speed priority','Агрессивно быстрее':'Fastest','Максимум':'Maximum','баланс скорости и нагрузки':'Balanced speed and load','больше параллельной обработки':'More parallel processing','предел текущего хостинга':'Current hosting limit','Профиль':'Profile','Интенсивность':'Intensity',
    'Имя результата':'Result name','Персонализация':'Personalization','Суффикс':'Suffix','Автомобильный мод обнаружен':'Vehicle mod detected','В результат добавится метка ModMendryx: название автомобиля и его preview-изображение. UI Apps вручную добавлять не нужно.':'The result gets a ModMendryx marker with the vehicle name and preview image. No UI Apps need to be added manually.',
    'Начать проверку':'Start check','Запустить VA 2':'Run VA 2','Запустить VE 1':'Run VE 1','Ожидается файл':'Waiting for a file','Готово к проверке':'Ready to check','Перед запуском ModMendryx проверит связь с backend.':'ModMendryx checks the backend connection before starting.',
    'ТЕКУЩИЙ РЕЛИЗ':'CURRENT RELEASE','этапов':'stages','сессии':'sessions','ВАШ ПРОФИЛЬ':'YOUR PROFILE','задач':'tasks','исправлений':'fixes','режим':'mode','Персонализировать':'Personalize','Что сервис не обещает':'What the service does not promise','МИНИ-ИГРА':'MINI-GAME','Змейка + реакция':'Snake + reaction','Открыть игры':'Open games',
    'ПРЕДВАРИТЕЛЬНЫЙ ОСМОТР':'PRE-FLIGHT','Файл разобран — движок ещё не запущен':'File inspected — engine has not started','СВОДКА':'SUMMARY','AI-ТРАФИК':'AI TRAFFIC','Проверка не выполнялась':'Not checked yet','ХРАНЕНИЕ':'STORAGE','РЕКОМЕНДАЦИЯ':'RECOMMENDATION','Подробнее о находках':'Finding details','Отменить':'Cancel','Запустить движок':'Run engine',
    'ОБРАБОТКА':'PROCESSING','Подготовка':'Preparing','Показать этапы':'Show stages','Скрыть этапы':'Hide stages','Соединение с backend замедлилось':'Backend connection is slow','Пауза':'Pause','Продолжить':'Resume','Файлы':'Files','Остановить':'Stop','РЕЗУЛЬТАТ':'RESULT','Готово':'Done','Скачать результат':'Download result','JSON-отчёт':'JSON report','Копировать ID':'Copy ID','Health':'Health','Repair Preview':'Repair Preview','Diff':'Diff','Обратная связь':'Feedback','Новая задача':'New task','Перезапустить':'Restart',
    'ФАКТИЧЕСКИЕ ИСПРАВЛЕНИЯ':'ACTUAL FIXES','Все':'All','✓ Исправлено':'✓ Fixed','⚠ Предупреждения':'⚠ Warnings','ℹ Инфо':'ℹ Info','Горячие клавиши':'Keyboard shortcuts','БЫСТРЫЕ ДЕЙСТВИЯ':'QUICK ACTIONS','Информация об интерфейсе':'Interface information','ЦЕНТР ИНТЕРФЕЙСА':'INTERFACE CENTER','Разделы справки':'Help sections',
    'Обычные настройки применены.':'Usual settings applied.','Локальный профиль · без аккаунта':'Local profile · no account','Локальный профиль · настройки сохранены':'Local profile · settings saved','Последняя задача: пока нет запусков':'Last task: no runs yet','Рабочее пространство готово':'Workspace ready',
    'Ожидается файл':'Waiting for a file','Файл готов к скачиванию':'File is ready to download','Понятно':'OK','Начать работу':'Start working','Сохранить':'Save','Отмена':'Cancel','Применить':'Apply','Подробнее':'Details','Выбрать':'Select','Назад':'Back','Готово':'Done',
    'Восстановление данных':'Data recovery','Сайт не отвечает':'Site unavailable','Ответ слишком долго не приходит':'Response is taking too long','Конфликт операции':'Operation conflict','Сессия потеряна':'Session lost','Backend перезапущен':'Backend restarted','Слишком большой файл':'File too large','Неподдерживаемый формат':'Unsupported format','Неверные данные':'Invalid data','Лимит задач':'Task limit','Доступ запрещён':'Access denied','Задача остановлена':'Task stopped','Ресурс не найден':'Resource not found','Внутренняя ошибка':'Internal error',
    'Почему:':'Why:','Что делать:':'What to do:','Проверка изменений':'Change verification','Повторная проверка':'Re-check','Итоговая диагностика':'Final diagnostics','Короткая разгрузка':'Short cooldown','Завершено':'Completed','Ошибка':'Error','Выполняется':'Running','Ожидает':'Waiting','Операция остановлена':'Operation stopped','Нужен повтор или восстановление':'Retry or recovery required',
    'Оптимизация':'Optimization','Высокая':'High','Ультра':'Ultra','Максимально экономный интерфейс. Обработка файлов не изменяется.':'Lowest UI overhead. File processing is unchanged.','Чуть более плавные переходы при умеренной нагрузке.':'Balanced effects with moderate load.','Расширенная плавность и больше живых микро-анимаций.':'More animation and richer effects.','Максимально плавный интерфейс и декоративные эффекты.':'Maximum effects and decorative motion.'
  };
  const reverse = Object.fromEntries(Object.entries(DICT).map(([ru,en]) => [en,ru]));
  const PATTERNS = [
    [/^Осталось: —$/, 'Remaining: —'],
    [/^Осталось: ~([0-9]+) сек\.$/, 'Remaining: ~$1 sec.'],
    [/^Осталось: ~([0-9]+) мин\.$/, 'Remaining: ~$1 min.'],
    [/^([0-9]+) мин\. назад$/, '$1 min ago'],
    [/^([0-9]+) ч\. назад$/, '$1 hr ago'],
    [/^Добро пожаловать, (.+)$/, 'Welcome, $1'],
    [/^Последняя задача: (.+)$/, 'Last task: $1'],
    [/^Сессия #([0-9]+) сохранена в истории\.$/, 'Session #$1 saved to history.'],
    [/^Сессия #([0-9]+) открыта\.$/, 'Session #$1 opened.'],
    [/^([0-9]+) задач · ([0-9]+) исправлений · (.+) акцент$/, '$1 tasks · $2 fixes · $3 accent'],
    [/^([0-9]+) запусков$/, '$1 runs'],
    [/^Обычно вы выбираете: (.+)\.$/, 'You usually choose: $1.'],
    [/^Готово · (.+)$/, 'Ready · $1'],
    [/^🎃 Ты поймал тыкву!$/, '🎃 You caught a pumpkin!']
  ];
  let lang = localStorage.getItem(KEY) === 'en' ? 'en' : 'ru';
  const original = new WeakMap();
  const attrOriginal = new WeakMap();
  const translateString = (value) => {
    const text = String(value ?? '').replace(/\s+/g,' ').trim();
    if (!text) return value;
    if (lang === 'ru') return reverse[text] || text;
    if (DICT[text]) return DICT[text];
    for (const [re,en] of PATTERNS) if (re.test(text)) return text.replace(re,en);
    return text;
  };
  function walk(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes=[]; while(walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (!original.has(node)) original.set(node, node.nodeValue);
      const source = original.get(node);
      const next = lang === 'ru' ? (reverse[source?.trim()] || source) : translateString(source);
      if (node.nodeValue !== next) node.nodeValue = next;
    }
    const elements = root.querySelectorAll ? root.querySelectorAll('[placeholder],[title],[aria-label]') : [];
    for (const el of elements) {
      let saved=attrOriginal.get(el); if(!saved){saved={}; attrOriginal.set(el,saved);}
      for (const attr of ['placeholder','title','aria-label']) if (el.hasAttribute(attr)) { if (!(attr in saved)) saved[attr]=el.getAttribute(attr); const src=saved[attr]; const next = lang==='ru' ? (reverse[src]||src) : translateString(src); if (el.getAttribute(attr) !== next) el.setAttribute(attr, next); }
    }
    if (root.nodeType===1 && root.matches?.('[placeholder],[title],[aria-label]')) {
      let saved=attrOriginal.get(root); if(!saved){saved={};attrOriginal.set(root,saved);} for(const attr of ['placeholder','title','aria-label']) if(root.hasAttribute(attr)){if(!(attr in saved))saved[attr]=root.getAttribute(attr);const src=saved[attr];const next = lang==='ru'?(reverse[src]||src):translateString(src); if(root.getAttribute(attr)!==next) root.setAttribute(attr,next);}
    }
  }
  function apply() {
    document.documentElement.lang=lang;
    document.documentElement.dataset.language=lang;
    const btn=document.getElementById('languageTop');
    if(btn){btn.textContent=lang==='ru'?'EN':'RU';btn.setAttribute('aria-label',lang==='ru'?'Switch to English':'Переключить на русский');btn.title=lang==='ru'?'English':'Русский';}
    walk(document.body);
  }
  window.__mfLanguage = () => lang;
  window.__mfSetLanguage = (next, emit=true) => {
    const value=next==='en'?'en':'ru'; if(value===lang){apply();return;}
    lang=value; localStorage.setItem(KEY,lang); apply();
    if(emit) window.dispatchEvent(new CustomEvent('modmendryx:language-changed',{detail:{language:lang}}));
  };
  window.addEventListener('modmendryx:toggle-language',()=>window.__mfSetLanguage(lang==='ru'?'en':'ru'));
  document.addEventListener('click',e=>{if(e.target.closest?.('#languageTop')){e.preventDefault();window.__mfSetLanguage(lang==='ru'?'en':'ru');}});
  const observer=new MutationObserver(muts=>{ if(lang==='ru' || !muts.length)return; for(const m of muts){ if(m.type==='childList') m.addedNodes.forEach(n=>{if(n.nodeType===1)walk(n);}); else if(m.type==='characterData'){ const node=m.target; if(!original.has(node)) original.set(node,node.nodeValue); const next=translateString(original.get(node)); if(node.nodeValue!==next) node.nodeValue=next; } else if(m.type==='attributes' && m.target.nodeType===1) walk(m.target); } });
  observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label']});
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',apply,{once:true}); else apply();
})();
