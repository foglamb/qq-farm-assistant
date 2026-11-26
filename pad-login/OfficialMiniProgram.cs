using System.Collections.Concurrent;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.RegularExpressions;
using Net.Codecrete.QrCodeGenerator;

namespace PadLogin;

public sealed class OfficialMiniProgramService : IDisposable
{
    private readonly ConcurrentDictionary<string, OfficialSession> _sessions = new();
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(20) };

    public OfficialMiniProgramService()
    {
        _http.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("qua", "V1_HT5_QDT_0.70.2209190_x64_0_DEV_D");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("referer", "https://q.qq.com/ide/devtoolAuth/LoginCode");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("origin", "https://q.qq.com");
    }

    public async Task<OfficialSession> Create()
    {
        var result = await _http.GetFromJsonAsync<JsonElement>("https://q.qq.com/ide/devtoolAuth/GetLoginCode");
        if (result.GetProperty("code").GetInt32() != 0) throw new InvalidOperationException("官方小程序二维码接口暂时不可用");
        var key = result.GetProperty("data").GetProperty("code").GetString() ?? throw new InvalidOperationException("官方小程序未返回扫码标识");
        var probe = await _http.GetStringAsync($"https://q.qq.com/ide/devtoolAuth/QueryLoginCode?code={key}");
        if (probe.Contains("命令字不存在", StringComparison.Ordinal)) throw new InvalidOperationException("腾讯已下线旧版小程序扫码接口，请使用主面板的 QQ 原生扫码");
        var item = new OfficialSession(key);
        _sessions[item.Id] = item;
        _ = Task.Run(() => Poll(item));
        return item;
    }

    public OfficialSession Get(string id) => _sessions.TryGetValue(id, out var item) ? item : throw new KeyNotFoundException("扫码会话不存在");

    private async Task Poll(OfficialSession item)
    {
        var failures = 0;
        while (DateTimeOffset.UtcNow - item.CreatedAt < TimeSpan.FromMinutes(10))
        {
            try
            {
                var raw = await _http.GetStringAsync($"https://q.qq.com/ide/devtoolAuth/QueryLoginCode?code={item.Key}");
                var match = Regex.Match(raw, @"ptuiCB\('(?<status>\d+)',(?<rest>.*)\);?$", RegexOptions.Singleline);
                if (!match.Success) throw new InvalidOperationException("官方扫码状态格式变化");
                var status = match.Groups["status"].Value;
                var text = match.Groups["rest"].Value;
                if (status is "65" or "66") { item.Status = "expired"; item.Message = "二维码已失效，请重新生成"; return; }
                if (status == "0" && text.Contains("&ticket="))
                {
                    item.Uin = Regex.Match(text, @"&uin=(\d+)&").Groups[1].Value;
                    var ticket = Uri.UnescapeDataString(Regex.Match(text, @"&ticket=([^&]+)&").Groups[1].Value);
                    item.Code = await Exchange(ticket);
                    item.Status = "success";
                    item.Message = "已获取农场 Code";
                    return;
                }
                item.Status = status == "67" ? "scanned" : "waiting_scan";
                item.Message = status == "67" ? "已扫码，请在手机 QQ 上确认" : "请用手机 QQ 扫码";
                failures = 0;
            }
            catch (Exception error)
            {
                if (++failures >= 5) { item.Status = "error"; item.Message = error.Message; return; }
            }
            await Task.Delay(2000);
        }
        item.Status = "expired";
        item.Message = "扫码会话已过期";
    }

    private async Task<string> Exchange(string ticket)
    {
        var response = await _http.PostAsJsonAsync("https://q.qq.com/ide/login", new { appid = "1112386029", ticket });
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        string? code = null;
        if (body.ValueKind == JsonValueKind.Object && body.TryGetProperty("data", out var data) && data.ValueKind == JsonValueKind.Object && data.TryGetProperty("code", out var nested)) code = nested.GetString();
        if (string.IsNullOrEmpty(code) && body.TryGetProperty("code", out var direct) && direct.ValueKind == JsonValueKind.String) code = direct.GetString();
        if (code is null || !Regex.IsMatch(code, @"^[\w.~+/=%-]{8,2048}$") || Regex.IsMatch(code, @"^[-+]?\d+$")) throw new InvalidOperationException("官方授权未返回有效农场 Code");
        return code;
    }

    public void Dispose() => _http.Dispose();
}

public sealed class OfficialSession(string key)
{
    public string Id { get; } = Guid.NewGuid().ToString();
    public string Key { get; } = key;
    public string QrUrl { get; } = $"https://q.qq.com/ide/devtoolAuth/LoginCode?code={key}";
    public DateTimeOffset CreatedAt { get; } = DateTimeOffset.UtcNow;
    public string Status { get; set; } = "waiting_scan";
    public string Message { get; set; } = "请用手机 QQ 扫码";
    public string Uin { get; set; } = "";
    public string Code { get; set; } = "";
    public string QrSvg() => QrCode.EncodeText(QrUrl, QrCode.Ecc.Low).ToSvgString(4);
    public object StatusObject() => new { sessionId = Id, status = Status, message = Message, uin = Uin, code = Code, hasQr = true };
}
