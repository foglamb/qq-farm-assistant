using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using PadLogin;

var token = Environment.GetEnvironmentVariable("PAD_TOKEN");
if (string.IsNullOrWhiteSpace(token)) throw new InvalidOperationException("PAD_TOKEN is required");
var port = int.Parse(Environment.GetEnvironmentVariable("PORT") ?? "8080");
QqTea.SelfTest();
using var session = new PadSession();
using var official = new OfficialMiniProgramService();
using var listener = new HttpListener();
listener.Prefixes.Add($"http://+:{port}/");
listener.Start();
Console.WriteLine($"PadLogin listening on {port}; AndroidPad and official mini-program flows are isolated");
if (session.SignConfigured) _ = Task.Run(() => session.StartLoginAsync());

var jsonOptions = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
while (true)
{
    var context = await listener.GetContextAsync();
    _ = Task.Run(() => Handle(context));
}

async Task Handle(HttpListenerContext context)
{
    var request = context.Request;
    var response = context.Response;
    try
    {
        var path = request.Url?.AbsolutePath ?? "/";
        if (path == "/health") { await Json(response, new { ok = true }); return; }
        if (request.Headers["x-admin-token"] != token && request.QueryString["token"] != token)
        {
            response.StatusCode = 401;
            await Json(response, new { ok = false, error = "unauthorized" });
            return;
        }
        if (path == "/api/official/sessions" && request.HttpMethod == "POST")
        {
            var created = await official.Create();
            response.StatusCode = 201;
            await Json(response, new { ok = true, data = created.StatusObject() });
            return;
        }
        if (path.StartsWith("/api/official/sessions/", StringComparison.Ordinal) && request.HttpMethod == "GET")
        {
            var item = official.Get(path.Split('/').Last());
            await Json(response, new { ok = true, data = item.StatusObject() });
            return;
        }
        if (path == "/official-qr.svg" && request.HttpMethod == "GET")
        {
            var item = official.Get(request.QueryString["id"] ?? "");
            response.ContentType = "image/svg+xml";
            await response.OutputStream.WriteAsync(Encoding.UTF8.GetBytes(item.QrSvg()));
            return;
        }
        switch (path, request.HttpMethod)
        {
            case ("/", "GET"):
                response.ContentType = "text/html; charset=utf-8";
                await response.OutputStream.WriteAsync(Encoding.UTF8.GetBytes(Html(token)));
                break;
            case ("/api/status", "GET"):
                await Json(response, new { ok = true, data = session.Status() });
                break;
            case ("/api/login", "POST"):
                var login = request.ContentLength64 > 0 ? await Body(request) : [];
                long.TryParse(login["uin"]?.GetValue<string>(), out var uin);
                var password = login["password"]?.GetValue<string>();
                _ = Task.Run(() => session.StartLoginAsync(uin, password));
                response.StatusCode = 202;
                await Json(response, new { ok = true });
                break;
            case ("/qr.png", "GET"):
                var image = session.QrImage();
                if (image is null) { response.StatusCode = 404; await Json(response, new { ok = false, error = "二维码尚未生成" }); break; }
                response.ContentType = "image/png";
                await response.OutputStream.WriteAsync(image);
                break;
            case ("/api/farm-code", "POST"):
                var farm = await session.GetFarmCodeAsync();
                await Json(response, new { ok = farm.Ret == 0, ret = farm.Ret, message = farm.Message, code = farm.Code });
                break;
            case ("/captcha", "POST"):
                var captcha = await Body(request);
                session.SubmitCaptcha(captcha["ticket"]?.GetValue<string>() ?? "", captcha["randstr"]?.GetValue<string>() ?? "");
                await Json(response, new { ok = true });
                break;
            case ("/sms", "POST"):
                var sms = await Body(request);
                session.SubmitSms(sms["code"]?.GetValue<string>() ?? "");
                await Json(response, new { ok = true });
                break;
            default:
                response.StatusCode = 404;
                await Json(response, new { ok = false, error = "not found" });
                break;
        }
    }
    catch (Exception error)
    {
        response.StatusCode = 500;
        await Json(response, new { ok = false, error = error.Message });
    }
    finally { response.Close(); }
}

async Task<JsonObject> Body(HttpListenerRequest request)
{
    using var reader = new StreamReader(request.InputStream, Encoding.UTF8);
    return JsonNode.Parse(await reader.ReadToEndAsync())?.AsObject() ?? [];
}

async Task Json(HttpListenerResponse response, object value)
{
    response.ContentType = "application/json; charset=utf-8";
    await response.OutputStream.WriteAsync(JsonSerializer.SerializeToUtf8Bytes(value, jsonOptions));
}

static string Html(string token) => """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QQ Pad 与官方小程序取码验证</title><style>body{font-family:sans-serif;max-width:760px;margin:32px auto;padding:0 16px;background:#111827;color:#e5e7eb}button{padding:10px 18px;border:0;border-radius:8px;background:#60a5fa;font-weight:bold}input{padding:8px}img{display:block;max-width:320px;width:100%;margin:20px 0;background:white;padding:12px;border-radius:12px}pre{white-space:pre-wrap;background:#1f2937;padding:16px;border-radius:8px;word-break:break-all}section{border:1px solid #374151;border-radius:12px;padding:18px;margin-bottom:18px}</style></head>
<body><h2>QQ Pad 与官方小程序取码验证</h2>
<section><h3>AndroidPad 9.2.20</h3><p>首次登录使用密码，成功后只保存 keystore。此页面不连接现有 NapCat 容器。</p><p><input id="uin" inputmode="numeric" placeholder="QQ 号"> <input id="password" type="password" placeholder="QQ 密码（仅本次内存使用）"></p><button onclick="login()">开始 Pad 登录</button> <button onclick="farmCode()">获取农场 Code</button><div id="qr"></div><pre id="status">读取中…</pre><pre id="farmCodeResult">登录后可测试 QQConnectLogin.auth_emp</pre></section>
<section><h3>官方小程序旧扫码接口（已失效）</h3><p>腾讯服务端已返回“命令字不存在”，本入口已停止生成无效二维码。请使用 <a href="http://192.168.100.121:3008">主面板 3008</a> 的 QQ 原生扫码。</p><pre id="officialStatus">旧官方接口已停用</pre></section>
<script>
const token=__TOKEN__;let officialId='';
async function refresh(){const r=await fetch('/api/status?token='+encodeURIComponent(token));const x=await r.json();document.querySelector('#status').textContent=JSON.stringify(x.data,null,2);document.querySelector('#qr').innerHTML=x.data.hasQr?'<img src="/qr.png?token='+encodeURIComponent(token)+'&v='+Date.now()+'">':''}
async function login(){await fetch('/api/login',{method:'POST',headers:{'x-admin-token':token,'Content-Type':'application/json'},body:JSON.stringify({uin:document.querySelector('#uin').value,password:document.querySelector('#password').value})});document.querySelector('#password').value='';setTimeout(refresh,500)}
async function farmCode(){document.querySelector('#farmCodeResult').textContent='正在请求 QQConnectLogin.auth_emp…';const r=await fetch('/api/farm-code',{method:'POST',headers:{'x-admin-token':token,'Content-Length':'0'}});const x=await r.json();document.querySelector('#farmCodeResult').textContent=JSON.stringify(x,null,2)}
async function startOfficial(){const r=await fetch('/api/official/sessions',{method:'POST',headers:{'x-admin-token':token,'Content-Length':'0'}});const x=await r.json();officialId=x.data.sessionId;refreshOfficial()}
async function refreshOfficial(){if(!officialId)return;const r=await fetch('/api/official/sessions/'+officialId+'?token='+encodeURIComponent(token));const x=await r.json();const d=x.data;document.querySelector('#officialStatus').textContent=JSON.stringify(d,null,2);document.querySelector('#officialQr').innerHTML=d.status==='waiting_scan'?'<img src="/official-qr.svg?id='+officialId+'&token='+encodeURIComponent(token)+'&v='+Date.now()+'">':''}
setInterval(()=>{refresh();refreshOfficial()},2000);refresh()
</script></body></html>
""".Replace("__TOKEN__", JsonSerializer.Serialize(token));
