#!/usr/bin/env python3
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PAD_TOKEN = os.environ["PAD_TOKEN"]
UPSTREAM = os.environ["UPSTREAM"].rstrip("/")
PORT = int(os.environ.get("PORT", "3010"))

ACCESS_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AndroidPad 访问验证</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#08111f;color:#e8eef8;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}.card{width:min(440px,90vw);padding:36px;border:1px solid #223552;border-radius:24px;background:#101d30;box-shadow:0 24px 80px #0006}h1{font-size:25px}p{color:#91a4bd}input{box-sizing:border-box;width:100%;padding:14px;margin:18px 0;border:1px solid #304664;border-radius:12px;background:#091525;color:white}button{width:100%;padding:13px;border:0;border-radius:12px;background:#4f8cff;color:white;font-weight:700;cursor:pointer}</style></head><body><main class="card"><h1>AndroidPad 登录中心</h1><p>输入页面访问令牌。此令牌不是 QQ 密码。</p><form onsubmit="location.href='/?token='+encodeURIComponent(document.querySelector('#token').value.trim());return false"><input id="token" type="password" placeholder="页面访问令牌" autofocus><button>进入登录中心</button></form></main></body></html>"""

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AndroidPad 登录与农场 Code</title><style>
:root{color-scheme:dark;--bg:#07101d;--card:#101d2e;--line:#243751;--text:#edf4ff;--muted:#8fa5bf;--blue:#5591ff;--green:#35d39a;--orange:#ffb95c}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top right,#17335c 0,transparent 38%),var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif}button,input,textarea{font:inherit}button{cursor:pointer}.wrap{max-width:1060px;margin:auto;padding:28px 18px 50px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:24px}.brand{display:flex;align-items:center;gap:14px}.logo{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:linear-gradient(135deg,#4d8cff,#755ff5);font-size:24px;font-weight:800}.muted{color:var(--muted)}h1{font-size:25px;margin:0 0 4px}h2{font-size:18px;margin:0 0 18px}.pill{padding:7px 12px;border:1px solid var(--line);border-radius:99px;color:var(--muted);font-size:13px;white-space:nowrap}.pill.online{color:var(--green);border-color:#35d39a55}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:linear-gradient(145deg,#122138dd,#0d1929dd);border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:0 16px 50px #0003}.wide{grid-column:1/-1}.row{display:flex;gap:12px;flex-wrap:wrap}.field{margin-bottom:14px}.field label{display:block;color:var(--muted);font-size:13px;margin-bottom:7px}input,textarea{width:100%;border:1px solid #304664;border-radius:12px;background:#091525;color:var(--text);padding:12px 13px;outline:none}input:focus,textarea:focus{border-color:var(--blue);box-shadow:0 0 0 3px #5591ff20}textarea{min-height:110px;resize:vertical;word-break:break-all}.btn{border:0;border-radius:12px;padding:12px 17px;background:var(--blue);color:white;font-weight:700}.btn.secondary{background:#1c304a;border:1px solid #345072}.btn:disabled{opacity:.55;cursor:wait}.status{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.stat{padding:12px;border-radius:12px;background:#091525}.stat small{display:block;color:var(--muted);margin-bottom:5px}.stat b{font-size:14px}.notice{padding:12px 14px;border-radius:12px;background:#ffb95c12;border:1px solid #ffb95c40;color:#ffd698;line-height:1.6}.success{color:var(--green)}pre{white-space:pre-wrap;word-break:break-all;color:var(--muted);font-size:13px;line-height:1.55}.hidden{display:none!important}.toast{position:fixed;right:20px;bottom:20px;max-width:min(420px,90vw);padding:13px 18px;border-radius:12px;background:#213858;box-shadow:0 12px 35px #0007;opacity:0;pointer-events:none;transition:.2s}.toast.show{opacity:1}.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.captcha-box{min-height:24px;margin-top:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}.status{grid-template-columns:1fr 1fr}.top{align-items:flex-start}.wrap{padding:18px 12px}.card{padding:18px}}
</style></head><body><div class="wrap"><header class="top"><div class="brand"><div class="logo">Q</div><div><h1>AndroidPad 登录中心</h1><div id="topVersion" class="muted">检测中 · 与 Windows QQ 分开登录 · 独立 NapCat 数据</div></div></div><span id="phasePill" class="pill">连接中</span></header><main class="grid">
<section class="card wide"><h2>运行状态</h2><div class="status"><div class="stat"><small>协议</small><b id="protocolVersion">检测中</b></div><div class="stat"><small>签名服务</small><b id="signState">检查中</b></div><div class="stat"><small>登录状态</small><b id="loginState">检查中</b></div><div class="stat"><small>保存的登录态</small><b id="savedState">检查中</b></div></div></section>
<section class="card wide hidden" id="errorBanner"><h2>登录错误详情</h2><div id="errorText" class="notice"></div></section>
<section class="card"><h2>① QQ 密码首登</h2><div class="field"><label>QQ 号</label><input id="uin" inputmode="numeric" autocomplete="username" placeholder="输入 QQ 号"></div><div class="field"><label>QQ 密码（只用于本次登录，不保存）</label><input id="password" type="password" autocomplete="current-password" placeholder="输入 QQ 密码"></div><div class="actions"><button id="loginBtn" class="btn" onclick="login()">开始 Pad 登录</button><button class="btn secondary" onclick="refresh()">刷新状态</button></div><p class="muted">首次登录需要密码；成功后仅保存 keystore，后续可免密恢复。</p><div id="qr"></div></section>
<section class="card"><h2>② 腾讯安全验证</h2><div id="noVerify" class="notice">需要验证码时，这里会自动显示验证入口。</div><div id="verifyArea" class="hidden"><p class="muted">验证完成后 ticket/randstr 会自动提交到当前登录会话。</p><div class="actions"><button class="btn" onclick="showCaptcha()">开始腾讯安全验证</button></div><div id="captcha" class="captcha-box"></div><div class="field" style="margin-top:16px"><label>如果收到的是短信码</label><div class="row"><input id="smsCode" inputmode="numeric" placeholder="输入短信验证码" style="flex:1;min-width:180px"><button class="btn secondary" onclick="submitSms()">提交短信码</button></div></div></div><pre id="verifyResult"></pre></section>
<section class="card wide"><h2>③ 获取农场 Code</h2><div class="actions"><button id="codeBtn" class="btn" onclick="farmCode()">调用 QQConnectLogin.auth_emp</button><button class="btn secondary" onclick="copyCode()">复制 Code</button></div><p class="muted">只有腾讯返回 ret=0 时才表示成功；这里不会生成或显示假 Code。</p><textarea id="codeOutput" readonly placeholder="登录成功后点击上方按钮，真实 ret/message/code 会显示在这里"></textarea></section>
<section class="card wide"><h2>当前会话详情</h2><pre id="detail">正在读取…</pre></section></main></div><div id="toast" class="toast"></div><script src="https://captcha.gtimg.com/TCaptcha.js"></script><script>
const token=__TOKEN__;let current=null;let toastTimer;
const $=s=>document.querySelector(s);const phaseNames={idle:'未开始',needs_password:'等待密码',starting:'正在登录',needs_captcha:'等待安全验证',needs_device_verify:'等待设备验证',verifying:'正在提交验证',online:'已在线',error:'登录错误'};
function toast(text){const el=$('#toast');el.textContent=text;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),3500)}
async function api(path,method='GET',body){const headers={'x-admin-token':token};if(body!==undefined)headers['Content-Type']='application/json';const r=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body)});const type=r.headers.get('content-type')||'';return type.includes('json')?await r.json():await r.text()}
function render(d){current=d;$('#topVersion').textContent='AndroidPad '+d.protocolVersion+' · 与 Windows QQ 分开登录 · 独立 NapCat 数据';$('#protocolVersion').textContent='AndroidPad '+d.protocolVersion;const phase=d.phase||'unknown';$('#phasePill').textContent=phaseNames[phase]||phase;$('#phasePill').classList.toggle('online',phase==='online');$('#signState').textContent=d.signConfigured?(d.signMode==='remix'?'公共 + 本地':'已连接'):'未配置';$('#signState').className=d.signConfigured?'success':'';$('#loginState').textContent=phaseNames[phase]||phase;$('#savedState').textContent=d.hasSavedSession?'已保存':'未保存';$('#detail').textContent=JSON.stringify(d,null,2);const canVerify=!!d.verifyUrl&&phase!=='error'&&phase!=='online';$('#verifyArea').classList.toggle('hidden',!canVerify);$('#noVerify').classList.toggle('hidden',canVerify);$('#errorBanner').classList.toggle('hidden',phase!=='error');$('#errorText').textContent=phase==='error'?(d.detail||'未知登录错误'):'';$('#codeBtn').disabled=phase!=='online';$('#qr').innerHTML=d.hasQr?'<img alt="Pad 登录二维码" src="/qr.png?token='+encodeURIComponent(token)+'&v='+Date.now()+'" style="max-width:280px;width:100%;background:white;padding:10px;border-radius:12px;margin-top:14px">':''}
async function refresh(){try{const x=await api('/api/status');if(x.ok)render(x.data);else $('#detail').textContent=JSON.stringify(x,null,2)}catch(e){$('#detail').textContent='状态读取失败：'+e.message}}
async function login(){const uin=$('#uin').value.trim(),password=$('#password').value;if(!uin||!password){toast('请输入 QQ 号和密码');return}$('#loginBtn').disabled=true;try{const x=await api('/api/login','POST',{uin,password});if(!x.ok)throw new Error(x.error||'登录请求失败');$('#password').value='';toast('登录请求已提交，请留意安全验证');setTimeout(refresh,700)}catch(e){toast(e.message)}finally{$('#loginBtn').disabled=false}}
function showCaptcha(){if(!current?.verifyUrl){toast('当前没有待完成的验证码');return}if(!window.TencentCaptcha){toast('腾讯验证码脚本未加载，请检查网络后刷新');return}const q=new URLSearchParams(new URL(current.verifyUrl).search);const options={type:'full',showHeader:false,uin:q.get('uin')||'0',sid:q.get('sid')||'',enableAged:true};if(q.get('login_appid'))options.login_appid=q.get('login_appid');const appid=q.get('aid')||'2081081773';const captcha=new TencentCaptcha(appid,async res=>{if(res.ret!==0){$('#verifyResult').textContent=JSON.stringify(res,null,2);return}$('#verifyResult').textContent='验证成功，正在提交票据…';try{const x=await api('/captcha','POST',{ticket:res.ticket,randstr:res.randstr});$('#verifyResult').textContent=JSON.stringify(x,null,2);setTimeout(refresh,1000)}catch(e){$('#verifyResult').textContent=e.message}},options);captcha.show()}
async function submitSms(){const code=$('#smsCode').value.trim();if(!code){toast('请输入短信验证码');return}const x=await api('/sms','POST',{code});$('#verifyResult').textContent=JSON.stringify(x,null,2);setTimeout(refresh,1000)}
async function farmCode(){$('#codeOutput').value='正在请求 QQConnectLogin.auth_emp…';try{const x=await api('/api/farm-code','POST',{});$('#codeOutput').value=JSON.stringify(x,null,2)}catch(e){$('#codeOutput').value=e.message}}
async function copyCode(){const text=$('#codeOutput').value;if(!text){toast('还没有可复制的内容');return}await navigator.clipboard.writeText(text);toast('已复制')}
refresh();setInterval(refresh,2000)
</script></body></html>"""


def upstream(path, method="GET", body=None, content_type=None):
    request = Request(UPSTREAM + path, data=body, method=method)
    request.add_header("x-admin-token", PAD_TOKEN)
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, response.headers.get("Content-Type", "application/octet-stream"), response.read()
    except HTTPError as error:
        return error.code, error.headers.get("Content-Type", "application/json"), error.read()


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        return self.headers.get("x-admin-token") == PAD_TOKEN or parse_qs(urlparse(self.path).query).get("token", [""])[0] == PAD_TOKEN

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send(200, '{"ok":true}')
            return
        if path == "/" and not self.authorized():
            self.send(200, ACCESS_PAGE, "text/html; charset=utf-8")
            return
        if not self.authorized():
            self.send(401, '{"ok":false,"error":"unauthorized"}')
            return
        if path == "/":
            self.send(200, PAGE.replace("__TOKEN__", json.dumps(PAD_TOKEN)), "text/html; charset=utf-8")
            return
        try:
            status, content_type, body = upstream(self.path)
            self.send(status, body, content_type)
        except Exception as error:
            self.send(502, json.dumps({"ok": False, "error": str(error)}))

    def do_POST(self):
        if not self.authorized():
            self.send(401, '{"ok":false,"error":"unauthorized"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            status, content_type, response = upstream(self.path, "POST", body, self.headers.get("Content-Type"))
            self.send(status, response, content_type)
        except Exception as error:
            self.send(502, json.dumps({"ok": False, "error": str(error)}))

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
