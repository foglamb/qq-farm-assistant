#!/usr/bin/env python3
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PAD_TOKEN = os.environ["PAD_TOKEN"]
UPSTREAM = os.environ.get("UPSTREAM", "http://127.0.0.1:3009")
PORT = int(os.environ.get("PORT", "3010"))


def upstream(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(UPSTREAM + path, data=data, method="GET" if body is None else "POST")
    request.add_header("x-admin-token", PAD_TOKEN)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def page(status):
    verify_url = status.get("data", {}).get("verifyUrl") or ""
    query = parse_qs(urlparse(verify_url).query)
    options = {
        "type": "full",
        "showHeader": False,
        "uin": query.get("uin", ["0"])[0],
        "sid": query.get("sid", [""])[0],
        "enableAged": True,
    }
    login_appid = query.get("login_appid", [""])[0]
    if login_appid:
        options["login_appid"] = login_appid
    appid = query.get("aid", ["2081081773"])[0]
    config = json.dumps({"token": PAD_TOKEN, "status": status, "appid": appid, "options": options}, ensure_ascii=False)
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AndroidPad 腾讯验证助手</title><style>body{font-family:sans-serif;max-width:760px;margin:24px auto;padding:16px;background:#111827;color:#e5e7eb}pre{white-space:pre-wrap;word-break:break-all;background:#1f2937;padding:14px;border-radius:8px}button{padding:10px 18px;background:#60a5fa;border:0;border-radius:8px;font-weight:bold}</style></head><body><h2>AndroidPad 腾讯验证助手</h2><p>完成腾讯验证码后，ticket/randstr 会自动提交到当前登录会话，不需要重启 3009。</p><div id="captcha"></div><p><button onclick="showCaptcha()">开始腾讯安全验证</button></p><pre id="result">正在读取登录状态…</pre><script src="https://captcha.gtimg.com/TCaptcha.js"></script><script>const cfg=__CONFIG__;
function render(x){document.querySelector('#result').textContent=JSON.stringify(x,null,2)}
async function refresh(){const r=await fetch('/api/status?token='+encodeURIComponent(cfg.token));render(await r.json())}
function showCaptcha(){if(!window.TencentCaptcha){alert('腾讯验证码脚本尚未加载，请检查网络后刷新');return}const captcha=new TencentCaptcha(cfg.appid,async res=>{if(res.ret!==0){render(res);return}document.querySelector('#result').textContent='验证成功，正在提交登录票据…';const r=await fetch('/captcha?token='+encodeURIComponent(cfg.token),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket:res.ticket,randstr:res.randstr})});render(await r.json());setTimeout(refresh,1500)},cfg.options);captcha.show()}
render(cfg.status);refresh();setInterval(refresh,3000);showCaptcha()
</script></body></html>""".replace("__CONFIG__", config)


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
        if not self.authorized():
            self.send(401, '{"ok":false,"error":"unauthorized"}')
            return
        try:
            code, body = upstream("/api/status")
            status = json.loads(body)
            if path == "/":
                self.send(200, page(status), "text/html; charset=utf-8")
            elif path == "/api/status":
                self.send(code, body)
            else:
                self.send(404, '{"ok":false,"error":"not found"}')
        except Exception as error:
            self.send(502, json.dumps({"ok": False, "error": str(error)}))

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authorized():
            self.send(401, '{"ok":false,"error":"unauthorized"}')
            return
        if path not in ("/captcha", "/sms"):
            self.send(404, '{"ok":false,"error":"not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            code, response = upstream(path, body)
            self.send(code, response)
        except Exception as error:
            self.send(502, json.dumps({"ok": False, "error": str(error)}))

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
