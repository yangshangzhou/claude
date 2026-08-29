"""X post v3: wait for the X app to finish mounting before editor detection."""
import time
from typing import Any

import browser_x as bx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def _app_ready(page):
    """Require the main X UI to be mounted before looking for the editor."""
    try:
        return bool(page.evaluate("""
        () => {
          if (document.readyState !== 'complete') return false;
          if (!document.body || document.body.children.length < 5) return false;
          const text = document.body.innerText || '';
          const hasComposer = text.includes("What's happening?") || text.includes('What’s happening?');
          const hasPostButton = !!document.querySelector('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]');
          return hasComposer && hasPostButton;
        }
        """, timeout=1500))
    except Exception:
        return False


def _find_editor_dom(page):
    try:
        return page.evaluate("""
        () => {
          const el = document.querySelector('[data-testid="tweetTextarea_0"]')
                || document.querySelector('[contenteditable="true"][role="textbox"]');
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {testid:el.getAttribute('data-testid'),role:el.getAttribute('role'),contenteditable:el.getAttribute('contenteditable'),text:(el.innerText||el.textContent||'').trim(),html:el.innerHTML,rect:{x:r.x,y:r.y,w:r.width,h:r.height},focused:document.activeElement===el};
        }
        """, timeout=1500)
    except Exception:
        return None


def _read_editor(page):
    info = _find_editor_dom(page)
    if not info:
        return {"found":False,"text":"","html":"","focused":False}
    return {"found":True,"testid":info.get("testid"),"role":info.get("role"),"contenteditable":info.get("contenteditable"),"text":info.get("text",""),"html":info.get("html",""),"focused":info.get("focused",False),"rect":info.get("rect")}


def _post_button(page):
    for selector in ['[data-testid="tweetButtonInline"]','[data-testid="tweetButton"]']:
        try:
            loc=page.locator(selector)
            count=min(loc.count(),10)
            for i in range(count):
                b=loc.nth(i)
                try:
                    if b.is_visible(timeout=700): return b
                except Exception: continue
        except Exception: continue
    return None


def _post_state(page):
    b=_post_button(page)
    if not b: return {"found":False,"data_testid":None,"disabled":None,"aria_disabled":None}
    try: return {"found":True,"data_testid":b.get_attribute('data-testid',timeout=1000),"disabled":b.is_disabled(timeout=1000),"aria_disabled":b.get_attribute('aria-disabled',timeout=1000)}
    except Exception as exc: return {"found":True,"data_testid":None,"disabled":None,"aria_disabled":None,"error":f"{type(exc).__name__}: {exc}"}


def _wait_for_app_then_editor(page, started, app_seconds=15, editor_seconds=12):
    app_deadline=min(time.time()+app_seconds, started+bx.TASK_HARD_TIMEOUT-3)
    app_checks=0
    while time.time()<app_deadline:
        bx._check_deadline(started); app_checks+=1
        if _app_ready(page): break
        page.wait_for_timeout(300)
    else:
        return None,{"app_ready":False,"app_checks":app_checks}

    editor_deadline=min(time.time()+editor_seconds, started+bx.TASK_HARD_TIMEOUT-2)
    editor_checks=0
    while time.time()<editor_deadline:
        bx._check_deadline(started); editor_checks+=1
        info=_read_editor(page)
        if info.get('found'):
            return info,{"app_ready":True,"app_checks":app_checks,"editor_checks":editor_checks}
        page.wait_for_timeout(300)
    return None,{"app_ready":True,"app_checks":app_checks,"editor_checks":editor_checks}


def _clear_editor(page):
    try:
        page.evaluate("""() => { const el=document.querySelector('[data-testid="tweetTextarea_0"]')||document.querySelector('[contenteditable="true"][role="textbox"]'); if(!el)return false; el.focus(); const r=document.createRange(); r.selectNodeContents(el); const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); document.execCommand('delete'); return true; }""", timeout=1500)
    except Exception: pass
    page.wait_for_timeout(300)


def _direct_assignment(page,text):
    return page.evaluate("""(value)=>{const el=document.querySelector('[data-testid="tweetTextarea_0"]')||document.querySelector('[contenteditable="true"][role="textbox"]');if(!el)return{found:false,before:'',after:''};const before=(el.innerText||el.textContent||'').trim();el.focus();el.textContent=value;el.dispatchEvent(new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertText',data:value}));el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:value}));el.dispatchEvent(new Event('change',{bubbles:true}));return{found:true,before,after:(el.innerText||el.textContent||'').trim(),html:el.innerHTML,focused:document.activeElement===el};}""", text, timeout=2000)


def _keyboard_input(page,text):
    try:
        page.locator('[data-testid="tweetTextarea_0"]').first.click(timeout=2500)
        page.wait_for_timeout(200); page.keyboard.type(text,delay=120); page.wait_for_timeout(800)
        return {"success":True}
    except Exception as exc: return {"success":False,"error":f"{type(exc).__name__}: {exc}"}


def post_x(text: str, image_base64=None, image_filename="image.png") -> dict[str, Any]:
    state=bx._storage_state()
    if not state: return {"success":False,"stage":"configuration","message":"No X browser session configured."}
    started,lock_error=bx._acquire_task('input_experiment_start')
    if lock_error: lock_error['text']=text; return lock_error
    browser=context=state_file=page=None
    try:
        with sync_playwright() as p:
            bx._set_task(stage='launching_browser'); browser,context,state_file,page=bx._launch_context(p,state)
            bx._set_task(stage='opening_compose'); page.goto(bx.COMPOSE_URL,wait_until='commit',timeout=12000)

            # STEP 0: wait for the X application/plugin UI to finish mounting.
            bx._set_task(stage='step0_waiting_for_x_app')
            editor_before,ready=_wait_for_app_then_editor(page,started)
            post_before=_post_state(page)
            if not ready.get('app_ready'):
                return {"success":False,"stage":"step0_x_app_not_ready","step":0,"message":"0、X 页面插件/UI 尚未加载完成。","app":ready,"post_button":post_before,"diagnostics":bx._diagnostics(page)}

            # STEP 1: only after the app is ready, report editor detection.
            if not editor_before:
                return {"success":False,"stage":"step1_editor_not_found","step":1,"message":"1、X 插件/UI 已加载完成，但没有找到 editor。","editor":{"found":False},"app":ready,"post_button":post_before,"diagnostics":bx._diagnostics(page)}

            step1={"found":True,"data_testid":editor_before.get('testid'),"role":editor_before.get('role'),"contenteditable":editor_before.get('contenteditable'),"text":editor_before.get('text',''),'focused':editor_before.get('focused',False)}

            # TEST 1: direct assignment.
            bx._set_task(stage='test1_direct_assignment'); _clear_editor(page); a_before=_read_editor(page); a_result=_direct_assignment(page,text); page.wait_for_timeout(1000); a_after=_read_editor(page); a_post=_post_state(page); a_ok=text.strip() in a_after.get('text','')

            # TEST 2: keyboard input from a clean editor.
            bx._set_task(stage='test2_keyboard_input'); _clear_editor(page); b_before=_read_editor(page); b_result=_keyboard_input(page,text); page.wait_for_timeout(500); b_after=_read_editor(page); b_post=_post_state(page); b_ok=text.strip() in b_after.get('text','')

            result={"success":False,"stage":"input_experiment_complete","message":"Editor 输入实验完成；未点击 POST。","step0_app_ready":ready,"step1_editor":step1,"step1_post_button":post_before,"test1_direct_assignment":{"method":"直接给 editor.textContent 赋值 + beforeinput/input/change","before":a_before,"operation":a_result,"after":a_after,"text_verified":a_ok,"post_button":a_post},"test2_keyboard_input":{"method":"模拟真实键盘输入 page.keyboard.type","before":b_before,"operation":b_result,"after":b_after,"text_verified":b_ok,"post_button":b_post},"diagnostics":bx._diagnostics(page)}
            bx._set_task(stage=result['stage'],last_result=result); return result
    except Exception as exc:
        result={"success":False,"stage":"timeout" if isinstance(exc,(TimeoutError,PlaywrightTimeoutError)) else 'exception',"message":f"X input experiment failed: {type(exc).__name__}: {exc}","diagnostics":bx._diagnostics(page) if page else {}}; bx._set_task(stage='failed',last_result=result); return result
    finally:
        if started is not None: bx._cleanup_task(started,browser,context,state_file)
