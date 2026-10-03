from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text('utf-8')


def test_release_is_063_and_local_update_is_non_destructive():
    js = read('site/assets/app.js')
    main = read('app/main.py')
    assert 'SITE_VERSION = "0.63-A"' in main
    assert 'localStorage.removeItem(key)' not in js
    assert 'keys.forEach(key => localStorage.removeItem(key))' not in js
    assert 'preserveLocalStateOnUpdate' in js


def test_ui_performance_has_exactly_four_real_profiles():
    js = read('site/assets/app.js')
    block = re.search(r'const UI_PERFORMANCE = \{(.*?)\n\};', js, re.S).group(1)
    keys = re.findall(r'^\s{2}([a-z]+):\{', block, re.M)
    assert keys == ['standard', 'high', 'ultra', 'optimization']
    for key in keys:
        assert f'{key}:' in block
    css = read('site/assets/styles.css')
    assert 'data-ui-performance="optimization"' in css
    assert 'data-ui-performance="ultra"' in css


def test_processing_lock_contract_covers_result_name_speed_and_repair_mode():
    js = read('site/assets/app.js')
    assert "setWorkspaceLocked(true)" in js
    assert "'settingsBtn','settingsTop','paletteTop','profileTop','heroProfileBtn','profileEditBtn','languageTop'" in js
    assert "els.repairMode?.querySelectorAll('.mode-card')" in js
    assert "els.networkPresets?.querySelectorAll('.network-card')" in js
    assert "if (state.busy) { toast('Настройки заблокированы во время обработки.'" in js


def test_favicon_is_static_primary_logo_and_not_personalized():
    html = read('site/index.html')
    js = read('site/assets/app.js')
    assert 'rel="icon" type="image/png" href="/assets/logo.png?v=063a"' in html
    assert "favicon.href = '/assets/logo.png?v=063a'" in js
    assert 'favicon.href = `data:image/svg+xml' not in js


def test_halloween_is_optional_and_has_separate_preview_module():
    html = read('site/index.html')
    assert 'assets/halloween-preview.js?v=063a' in html
    assert 'assets/halloween.js?v=063a' in html
    assert (ROOT / 'site/assets/halloween-preview.js').exists()
    assert (ROOT / 'site/assets/halloween.js').exists()
    preview = read('site/assets/halloween-preview.js')
    halloween = read('site/assets/halloween.js')
    assert 'LIMIT=31' in preview
    assert 'modmendryx:personalization-changed' in preview
    assert 'setTimeout(()=>{if(!p.isConnected)return;p.classList.add(\'warning\')' in halloween
    assert 'setTimeout(remove,980)' in halloween
    assert 'MODMENDRYX // NIGHT MODE' not in halloween


def test_va2_has_one_post_repair_verify_call_and_no_second_recheck():
    source = read('app/main.py')
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'run_va2_engine')
    calls = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute) or n.func.attr != 'to_thread' or not n.args:
            continue
        target = n.args[0]
        if isinstance(target, ast.Name) and target.id == 'verify_tree':
            calls.append(n)
    assert len(calls) == 1
    fn_text = ast.get_source_segment(source, fn)
    assert 'Повторная проверка' not in fn_text
    assert 'Итоговая диагностика' in fn_text


def test_backend_failure_context_keeps_real_exception_cause():
    main = read('app/main.py')
    assert 'record_job_failure' in main
    assert 'exception_type' in main
    assert 'error_id' in main
    assert 'LOGGER.exception("job failure' in main
    assert 'persistence_error' in main


def test_i18n_module_and_language_switch_exist():
    html = read('site/index.html')
    i18n = read('site/assets/i18n.js')
    assert 'id="languageTop"' in html
    assert 'window.__mfSetLanguage' in i18n
    assert "localStorage.getItem(KEY) === 'en'" in i18n
    assert 'modmendryx:language-changed' in i18n
