import json, os, shutil
from pathlib import Path
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ["POLARIS_BROWSER_OUTPUT"])
ROOT.mkdir(parents=True, exist_ok=True)
BASE = os.environ.get("POLARIS_BROWSER_BASE_URL", "http://127.0.0.1:4318")
fixture = json.loads((REPO / "tests/fixtures/audit-browser.json").read_text(encoding="utf-8"))
observations, errors, requests, cases = [], [], [], []
accepted = True
consent_error = False
consent_writes = []
notice = json.loads((REPO / 'backend/app/processing_notice.json').read_text(encoding="utf-8"))
features = {key: {'availability': 'available', 'execution': 'provider', 'can_submit': True, 'can_deliver_images': True}
    for key in ['domestic_main_image', 'detail_pack', 'crossborder_detail', 'amazon_visual_suite', 'reference_remix', 'creative_image', 'product_image', 'local_edit', 'model_pose_transfer']}

def api(route):
    global accepted
    path = urlparse(route.request.url).path
    payload = {'items': [], 'total': 0, 'next_cursor': None}
    if path == '/api/v1/me/processing-consent':
        if consent_error:
            route.fulfill(status=503,content_type='application/json',body='{}'); return
        if route.request.method == 'POST':
            consent_writes.append(route.request.post_data_json); accepted = True
        elif route.request.method == 'DELETE': accepted = False
        payload = {'policy_version':notice['version'],'accepted':accepted,'accepted_at':'2026-10-30T00:00:00Z' if accepted else None,'notice':notice}
    elif path.startswith('/api/auth/'): payload = {'status': 'OK', 'isVerified': True}
    elif path == '/api/v1/workspaces': payload = [{'id': 'ws_browser', 'name': '界面验收', 'role': 'owner'}]
    elif path == '/api/v1/me': payload = {'id': 'usr_browser', 'email': 'browser@example.invalid', 'email_verified': True, 'status': 'active'}
    elif path == '/api/v1/runtime': payload = {'environment': 'test', 'capabilities': {'features': features, **features}}
    elif path.endswith('/credits'): payload = {'enforcement_enabled': True, 'available_credits': 987654321, 'reserved_credits': 48, 'balance_credits': 1048, 'pricing': fixture['pricing']}
    elif path.endswith('/membership'): payload = {'plan_name': '专业版', 'plan_id': 'pro', 'monthly_credits': 1500, 'membership_status': 'active', 'ends_at': '2026-12-31T00:00:00Z', 'pack_credits': 1000, 'member_credits': 48, 'expiring_credits': 0}
    elif path.endswith('/packages'): payload = {'enabled': True, 'packages': fixture['packages']}
    elif path.endswith('/creation-summary'): payload = {'active': 25, 'needs_attention': 1, 'completed': 3, 'total': 29}
    elif path.endswith('/product-platforms'): payload = [{'code': 'tmall', 'label': '天猫'}, {'code': 'taobao', 'label': '淘宝'}]
    elif '/documents/missing-old-session' in path:
        route.fulfill(status=404, content_type='application/json', body='{"error":{"message":"过期草稿"}}'); return
    elif path.endswith('/replica/sessions') and route.request.method == 'POST':
        data = route.request.post_data_json; requests.append(data)
        payload = {'id': 'rep_synthetic', 'kind': 'session', 'status': 'analysing', 'created_at': '2026-10-30T00:00:00Z', 'payload': data}
    elif path.endswith(('/replica/records', '/replica/sessions')): payload = []
    elif path.endswith('/access-url'): payload = {'url': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jTXYAAAAASUVORK5CYII=', 'expires_at': '2099-01-01T00:00:00Z'}
    elif path.endswith('/support-cases'):
        if route.request.method == 'POST':
            cases.append({'id': 'sup_mock', 'workspace_id': 'ws_browser', 'job_id': None, 'issue': route.request.post_data_json['issue'], 'status': 'open', 'resolution': ''})
            payload = cases[-1]
        else: payload = cases
    route.fulfill(status=201 if path.endswith('/support-cases') and route.request.method == 'POST' else 200, content_type='application/json', body=json.dumps(payload))

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=os.environ.get('POLARIS_BROWSER_EXECUTABLE') or shutil.which('google-chrome') or shutil.which('chromium'), args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN')
    context.route(BASE+'/api/**',api)
    context.route('https://**',lambda route:route.abort())
    context.add_init_script("document.cookie='sFrontToken='+btoa(JSON.stringify({uid:'usr_browser',ate:Date.now()+3600000,up:{'st-ev':{v:true,t:Date.now()}}}))+';path=/';document.cookie='st-last-access-token-update='+Date.now()+';path=/';")
    page=context.new_page()
    page.on('pageerror',lambda error:errors.append(str(error)))
    def visit(path,expected):
        page.goto(BASE+path,wait_until='domcontentloaded',timeout=30000)
        page.get_by_text(expected,exact=False).first.wait_for(timeout=25000)
        page.wait_for_timeout(300)
    try:
        for width in [320,360,390,768,960,1280,1440]:
            page.set_viewport_size({'width':width,'height':1000})
            for path,expected in [('/','先选一件'),('/tools','全部工具'),('/style-replica','商品原图'),('/workspace/detail-pack','生成版本'),('/account#settings','图片处理与授权')]:
                print('CHECK',width,path,flush=True)
                visit(path,expected)
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),(width,path,'overflow')
                if path in ['/','/tools']:
                    for offset in range(0,page.evaluate('document.body.scrollHeight'),750):
                        page.evaluate('y=>window.scrollTo(0,y)',offset);page.wait_for_timeout(70)
                    page.wait_for_timeout(400)
                    assert page.evaluate('Array.from(document.images).filter(i=>i.complete&&i.naturalWidth===0).map(i=>i.src)')==[]
                    assert page.evaluate('Array.from(document.images).some(i=>i.currentSrc.includes("/images/display/"))')
                    page.evaluate('window.scrollTo(0,0)')
                observations.append({'width':width,'path':path,'passed':True})
            menu=page.locator('button[aria-controls="polaris-account-summary"]')
            menu.click();panel=page.get_by_role('region',name='会员与积分摘要');panel.wait_for()
            assert '987,654,321' in panel.inner_text()
            assert panel.evaluate('(e)=>e.scrollWidth<=e.clientWidth'),(width,'account menu clipping')
            page.screenshot(path=str(ROOT/f'account-{width}.png'),full_page=True)
            page.keyboard.press('Escape')
        accepted=False
        visit('/workspace/detail-pack','请分别确认以下处理事项')
        choices=page.get_by_role('checkbox');assert choices.count()==2
        assert not choices.nth(0).is_checked() and not choices.nth(1).is_checked()
        submit=page.get_by_role('button',name='确认并继续',exact=True)
        assert submit.is_disabled();choices.nth(0).check();assert submit.is_disabled();choices.nth(1).check();submit.click()
        page.get_by_text('生成版本',exact=False).first.wait_for()
        assert consent_writes[-1]=={'policyVersion':notice['version'],'hongKongProcessing':True,'aiTraining':True}
        visit('/account#settings','你已确认香港处理与模型训练说明')
        page.get_by_role('button',name='撤回处理授权',exact=True).click()
        assert accepted
        page.get_by_role('button',name='确认撤回',exact=True).click()
        page.get_by_role('button',name='确认并继续',exact=True).wait_for()
        assert not accepted
        for path,expected in [('/jobs','任务'),('/account#membership','专业版'),('/account#help','任务与售后帮助'),('/assets','图片处理与授权')]:
            visit(path,expected)
        visit('/workspace/detail-pack','请分别确认以下处理事项')
        assert page.get_by_text('生成版本',exact=False).count()==0
        visit('/style-replica?sessionId=missing-old-session','商品原图')
        assert page.get_by_role('button',name='确认并继续',exact=True).count()==0
        consent_error=True
        visit('/workspace/detail-pack','授权记录暂时无法读取')
        consent_error=False;accepted=True
        page.get_by_role('button',name='重新读取',exact=True).click()
        page.get_by_text('生成版本',exact=False).first.wait_for()
        assert not errors,errors
        print(json.dumps({'passed':True,'layouts':len(observations),'consent_accept_withdraw_retry':True,'old_results_payments_support_readable':True}))
    finally:
        (ROOT/'browser-audit.json').write_text(json.dumps({'observations':observations,'errors':errors,'consent_writes':consent_writes},ensure_ascii=False,indent=2),encoding='utf-8')
        (ROOT/'browser-last-text.txt').write_text(page.locator('body').inner_text(timeout=3000) if page.locator('body').count() else page.url,encoding='utf-8')
        page.screenshot(path=str(ROOT/'browser-last.png'),full_page=True)
        browser.close()

