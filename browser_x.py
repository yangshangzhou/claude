import json
import os
import tempfile
import threading
import time
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

COMPOSE_URL = "https://x.com/compose/tweet"
_HOME_URL = "https://x.com/home"
_BROWSER_LOCK = threading.Lock()
_TASK_STATE_LOCK = threading.Lock()
_TASK_STATE: dict[str, Any] = {"busy": False, "stage": "idle", "started_at": None, "elapsed_seconds": 0, "text": "", "last_result": None}
TASK_HARD_TIMEOUT = 60


def _storage_state() -> str | None:
    value = os.getenv("X_STORAGE_STATE", "").strip()
    if value:
        try:
            json.loads(value)
        except json.JSONDecodeError:
            return None
        return value
    path = os.getenv("X_STORAGE_STATE_FILE", "x_state.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def _task_snapshot() -> dict[str, Any]:
    with _TASK_STATE_LOCK:
        state = dict(_TASK_STATE)
        started = state.get("started_at")
        if state.get("busy") and started:
            state["elapsed_seconds"] = round(time.time() - started, 1)
        return state


def _set_task(**updates: Any) -> None:
    with _TASK_STATE_LOCK:
        _TASK_STATE.update(updates)
        started = _TASK_STATE.get("started_at")
        if _TASK_STATE.get("busy") and started:
            _TASK_STATE["elapsed_seconds"] = round(time.time() - started, 1)


def _check_deadline(started_at: float) -> None:
    if time.time() - started_at > TASK_HARD_TIMEOUT:
        raise TimeoutError(f"X browser task exceeded the {TASK_HARD_TIMEOUT}s hard timeout.")


def browser_status():
    configured = bool(_storage_state())
    return {"ready": configured, "message": "X browser session is configured." if configured else "No X browser session configured. Set X_STORAGE_STATE to a Playwright storage_state JSON.", "task": _task_snapshot()}


def _element_visible(candidate) -> bool:
    try:
        return bool(candidate.evaluate("""el => {const s=getComputedStyle(el);const r=el.getBoundingClientRect();return s.visibility!=='hidden'&&s.display!=='none'&&r.width>0&&r.height>0;}""", timeout=800))
    except Exception:
        return False


def _find_visible_editor(page):
    try:
        info = page.evaluate("""() => {
            const selectors=['[data-testid="tweetTextarea_0"]','div[contenteditable="true"][role="textbox"]','[role="textbox"][contenteditable="true"]','[contenteditable="true"]','textarea'];
            const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0};
            for(const selector of selectors){for(const el of document.querySelectorAll(selector)){if(visible(el))return {selector,testid:el.getAttribute('data-testid')};}}
            return null;
        }""")
    except Exception:
        return None
    if not info:
        return None
    try:
        loc=page.locator(f'[data-testid="{info["testid"]}"]').first if info.get('testid') else page.locator(info['selector']).first
        return loc if _element_visible(loc) else None
    except Exception:
        return None


def _editor_text(editor) -> str:
    try:
        return (editor.evaluate("el => (el.innerText || el.textContent || '').trim()", timeout=1000) or '').strip()
    except Exception:
        return ''


def _focus_editor(page, editor) -> bool:
    try:
        editor.scroll_into_view_if_needed(timeout=1500)
        editor.click(timeout=1500)
        editor.focus(timeout=1500)
        return bool(page.evaluate("""() => {const el=document.activeElement;return !!el && (el.getAttribute('data-testid')==='tweetTextarea_0'||el.getAttribute('role')==='textbox'||el.getAttribute('contenteditable')==='true');}"""))
    except Exception:
        return False


def _type_into_editor(page, editor, text: str) -> bool:
    if not _focus_editor(page, editor):
        return False
    try:
        editor.press_sequentially(text, delay=20, timeout=8000)
    except Exception:
        try:
            page.keyboard.type(text, delay=20)
        except Exception:
            return False
    page.wait_for_timeout(500)
    return text.strip() in _editor_text(editor)


def _find_post_button(page):
    try:
        info=page.evaluate("""() => {
            const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0};
            for(const el of [...document.querySelectorAll('[data-testid="tweetButtonInline"]'),...document.querySelectorAll('[data-testid="tweetButton"]')]){
                if(visible(el)&&!el.disabled&&el.getAttribute('aria-disabled')!=='true')return {testid:el.getAttribute('data-testid')};
            }
            const buttons=[...document.querySelectorAll('button')];
            for(let i=0;i<buttons.length;i++){const el=buttons[i];if(!visible(el)||el.disabled||el.getAttribute('aria-disabled')==='true')continue;const aria=(el.getAttribute('aria-label')||'').trim(),text=(el.innerText||'').trim();if(aria==='Post'||aria==='Tweet'||text==='Post'||text==='Tweet')return {testid:el.getAttribute('data-testid')||'',index:i};}
            return null;
        }""")
    except Exception:
        return None
    if not info:
        return None
    try:
        if info.get('testid'):
            loc=page.locator(f'[data-testid="{info["testid"]}"]')
            for i in range(min(loc.count(),5)):
                c=loc.nth(i)
                if _element_visible(c):
                    return c
        idx=info.get('index',-1)
        if isinstance(idx,int) and idx>=0:
            return page.locator('button').nth(idx)
    except Exception:
        pass
    return None


def _find_new_post_button(page):
    try:
        info=page.evaluate("""() => {const sels=['[data-testid="SideNav_NewTweet_Button"]','a[href="/compose/post"]','a[href="/compose/tweet"]'];const v=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return s.display!=='none'&&s.visibility!=='hidden'&&r.width>0&&r.height>0};for(const s of sels){const el=[...document.querySelectorAll(s)].find(v);if(el)return {selector:s};}return null;}""")
        if not info:
            return None
        loc=page.locator(info['selector']).first
        return loc if _element_visible(loc) else None
    except Exception:
        return None


def _diagnostics(page):
    out={"url":page.url if page else "","title":"","ready_state":"","html_length":0,"body_exists":False,"body_children":0,"body":"","test_ids":[]}
    if not page:
        return out
    try:
        out.update(page.evaluate("() => ({ready_state:document.readyState,html_length:document.documentElement?.outerHTML?.length||0,body_exists:!!document.body,body_children:document.body?.children?.length||0})"))
    except Exception:
        pass
    try: out['title']=page.title()
    except Exception: pass
    try: out['body']=page.locator('body').inner_text(timeout=1200)[:2000]
    except Exception: pass
    try: out['test_ids']=page.locator('[data-testid]').evaluate_all("els=>Array.from(new Set(els.map(e=>e.getAttribute('data-testid')).filter(Boolean))).slice(0,80)")
    except Exception: pass
    return out


def _install_lightweight_network_policy(page):
    # Do not abort images: X needs image resources for the composer/media preview.
    def route_handler(route):
        if route.request.resource_type in {'media','font'}:
            route.abort()
        else:
            route.continue_()
    page.route('**/*',route_handler)


def _launch_context(p,state):
    browser=p.chromium.launch(headless=True,timeout=20000,args=['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-software-rasterizer','--disable-background-timer-throttling','--disable-backgrounding-occluded-windows','--disable-breakpad','--disable-component-update','--disable-default-apps','--disable-extensions','--disable-plugins','--disable-sync','--disable-translate','--disable-features=Translate,BackForwardCache','--mute-audio','--no-first-run','--no-default-browser-check'])
    sf=tempfile.NamedTemporaryFile('w',suffix='.json',delete=False,encoding='utf-8');sf.write(state);sf.close()
    ctx=browser.new_context(storage_state=sf.name,viewport={'width':1280,'height':900},locale='en-US');page=ctx.new_page();page.set_default_timeout(5000);_install_lightweight_network_policy(page)
    return browser,ctx,sf.name,page


def _wait_for_app(page,started_at,timeout_ms=15000):
    deadline=time.time()+timeout_ms/1000
    while time.time()<deadline:
        _check_deadline(started_at)
        try:
            if page.evaluate('() => !!document.body && document.body.children.length>0'):
                return True
        except Exception: pass
        page.wait_for_timeout(500)
    return False


def _open_compose(page,started_at):
    _set_task(stage='opening_home');page.goto(_HOME_URL,wait_until='domcontentloaded',timeout=20000);_wait_for_app(page,started_at,12000)
    if _login_state(page) or _onboarding_state(page): return page.url
    _set_task(stage='opening_compose');entry=_find_new_post_button(page)
    if entry:
        try:
            entry.click(timeout=2500);page.wait_for_timeout(1200);return page.url
        except Exception: pass
    page.goto(COMPOSE_URL,wait_until='domcontentloaded',timeout=20000);_wait_for_app(page,started_at,12000);return page.url


def _wait_for_editor(page,started_at,timeout_ms=12000):
    deadline=time.time()+timeout_ms/1000
    while time.time()<deadline:
        _check_deadline(started_at);ed=_find_visible_editor(page)
        if ed: return ed
        page.wait_for_timeout(500)
    return None


def _acquire_task(stage):
    if not _BROWSER_LOCK.acquire(blocking=False):
        return None,{"success":False,"busy":True,"stage":"lock","message":"Another X browser task is currently running.","task":_task_snapshot()}
    started_at=time.time();_set_task(busy=True,stage=stage,started_at=started_at,elapsed_seconds=0,text='',last_result=None);return started_at,None


def _cleanup_task(started_at,browser,context,state_file):
    if context:
        try: context.close()
        except Exception: pass
    if browser:
        try: browser.close()
        except Exception: pass
    if state_file:
        try: os.unlink(state_file)
        except Exception: pass
    try: _BROWSER_LOCK.release()
    except RuntimeError: pass
    with _TASK_STATE_LOCK:
        _TASK_STATE.update(busy=False,stage='idle',elapsed_seconds=round(time.time()-started_at,1))


def _login_state(page): return '/i/flow/login' in page.url or '/login' in page.url

def _onboarding_state(page): return '/i/jf/' in page.url or '/onboarding' in page.url


def test_x_browser():
    state=_storage_state()
    if not state: return {'success':False,'stage':'configuration','message':'No X browser session configured.'}
    started,error=_acquire_task('test_starting')
    if error: return error
    b=c=sf=page=None
    try:
        with sync_playwright() as p:
            _set_task(stage='test_launching_browser');b,c,sf,page=_launch_context(p,state);_set_task(stage='test_opening_x');page.goto(_HOME_URL,wait_until='domcontentloaded',timeout=20000);mounted=_wait_for_app(page,started,15000);page.wait_for_timeout(1000);d=_diagnostics(page);lr=_login_state(page);ob=_onboarding_state(page);r={'success':not lr and mounted,'stage':'test_complete' if not lr and mounted else ('login_required' if lr else 'x_dom_not_mounted'),'message':'Playwright launched and X mounted with the saved browser session.' if not lr and mounted else 'X did not finish mounting its web application in the browser.','login_redirect':lr,'onboarding':ob,'diagnostics':d};_set_task(stage=r['stage'],last_result=r);return r
    except Exception as e:
        r={'success':False,'stage':'timeout' if isinstance(e,(TimeoutError,PlaywrightTimeoutError)) else 'exception','message':f'Playwright/X diagnostic failed: {type(e).__name__}: {e}','diagnostics':_diagnostics(page) if page else {}};_set_task(stage='failed',last_result=r);return r
    finally: _cleanup_task(started,b,c,sf)


def test_x_compose():
    state=_storage_state()
    if not state: return {'success':False,'stage':'configuration','message':'No X browser session configured.'}
    started,error=_acquire_task('compose_starting')
    if error: return error
    b=c=sf=page=None
    try:
        with sync_playwright() as p:
            b,c,sf,page=_launch_context(p,state);_open_compose(page,started);lr=_login_state(page);ob=_onboarding_state(page)
            if lr or ob: return {'success':False,'stage':'login_required','message':'X did not open the compose page in the saved session.','login_redirect':lr,'onboarding':ob,'diagnostics':_diagnostics(page)}
            _set_task(stage='compose_waiting_editor');editor=_wait_for_editor(page,started,12000);ef=editor is not None;_set_task(stage='compose_checking_post_button');button=_find_post_button(page) if ef else None
            r={'success':ef,'stage':'compose_ready' if ef else 'editor_not_found','message':'X compose UI loaded and the tweet editor was found.' if ef else 'X opened, but the tweet editor was not rendered.','login_redirect':lr,'onboarding':ob,'editor_found':ef,'editor':None if not ef else {'data_testid':editor.get_attribute('data-testid'),'role':editor.get_attribute('role'),'contenteditable':editor.get_attribute('contenteditable')},'post_button_found':button is not None,'post_button':None if button is None else {'data_testid':button.get_attribute('data-testid'),'aria_label':button.get_attribute('aria-label'),'enabled':not button.is_disabled(timeout=800)},'diagnostics':_diagnostics(page)};_set_task(stage=r['stage'],last_result=r);return r
    except Exception as e:
        r={'success':False,'stage':'timeout' if isinstance(e,(TimeoutError,PlaywrightTimeoutError)) else 'exception','message':f'X compose diagnostic failed: {type(e).__name__}: {e}','diagnostics':_diagnostics(page) if page else {}};_set_task(stage='failed',last_result=r);return r
    finally: _cleanup_task(started,b,c,sf)
