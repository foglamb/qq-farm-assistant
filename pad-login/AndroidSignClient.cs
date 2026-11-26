using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lagrange.Core.Common;

namespace PadLogin;

/// <summary>Android signing client supporting both Lagrange JSON and Ktor GET APIs.</summary>
public sealed class AndroidSignClient(string baseUrl) : AndroidBotSignProvider, IDisposable
{
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromMinutes(5) };
    private readonly string _baseUrl = baseUrl.TrimEnd('/');
    private readonly bool _ktorStyle = string.Equals(Environment.GetEnvironmentVariable("PAD_SIGN_STYLE"), "ktor", StringComparison.OrdinalIgnoreCase);
    private readonly HashSet<long> _registered = new();
    private readonly SemaphoreSlim _registerLock = new(1, 1);

    public override bool IsWhiteListCommand(string cmd) => AndroidSignWhitelist.Commands.Contains(cmd);

    public override async Task<SsoSecureInfo?> GetSecSign(long uin, string cmd, int seq, ReadOnlyMemory<byte> body)
    {
        JsonNode? data;
        if (_ktorStyle)
        {
            var root = await GetKtor("/sign", new()
            {
                ["uin"] = uin.ToString(), ["cmd"] = cmd, ["seq"] = seq.ToString(),
                ["buffer"] = Convert.ToHexString(body.Span), ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
                ["qua"] = Context.AppInfo.Qua,
            });
            data = root?["data"];
        }
        else
        {
            var payload = new JsonObject
            {
                ["uin"] = uin, ["cmd"] = cmd, ["seq"] = seq, ["buffer"] = Convert.ToHexString(body.Span),
                ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
                ["version"] = Context.AppInfo.PtVersion, ["qua"] = Context.AppInfo.Qua,
            };
            var response = await Post("/sign", payload);
            data = response?["data"];
        }
        if (data is null) return null;
        return new SsoSecureInfo
        {
            SecSign = Hex(data["sign"]?.GetValue<string>()),
            SecToken = Hex(data["token"]?.GetValue<string>()),
            SecExtra = Hex(data["extra"]?.GetValue<string>()),
        };
    }

    public override Task<byte[]> GetEnergy(long uin, string data)
    {
        if (_ktorStyle) return GetKtorBytes("/energy", new()
        {
            ["uin"] = uin.ToString(), ["data"] = data, ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
            ["ver"] = Context.AppInfo.SdkInfo.SdkVersion, ["version"] = Context.AppInfo.PtVersion, ["qua"] = Context.AppInfo.Qua,
        });
        return GetBytes("/energy", new JsonObject
        {
            ["uin"] = uin, ["data"] = data, ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
            ["ver"] = Context.AppInfo.SdkInfo.SdkVersion, ["version"] = Context.AppInfo.PtVersion, ["qua"] = Context.AppInfo.Qua,
        });
    }

    public override Task<byte[]> GetDebugXwid(long uin, string data)
    {
        if (_ktorStyle)
        {
            var guid = Convert.ToHexString(Context.Keystore.Guid);
            return GetKtorBytes("/getXwDebugId", new() { ["uin"] = uin.ToString(), ["android_id"] = guid, ["guid"] = guid });
        }
        return GetBytes("/get_tlv553", new JsonObject
        {
            ["uin"] = uin, ["data"] = data, ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
            ["version"] = Context.AppInfo.PtVersion, ["qua"] = Context.AppInfo.Qua,
        });
    }

    private async Task<byte[]> GetBytes(string path, JsonObject payload)
    {
        var response = await Post(path, payload);
        return Hex(response?["data"]?.GetValue<string>());
    }

    private async Task<byte[]> GetKtorBytes(string path, Dictionary<string, string> query)
    {
        var response = await GetKtor(path, query);
        return Hex(response?["data"]?.GetValue<string>());
    }

    private async Task<JsonObject?> GetKtor(string path, Dictionary<string, string> query)
    {
        if (_ktorStyle && path != "/register" && query.TryGetValue("uin", out var uin) && long.TryParse(uin, out var number)) await EnsureKtorSession(number);
        var url = _baseUrl + path + "?" + string.Join("&", query.Select(item => $"{Uri.EscapeDataString(item.Key)}={Uri.EscapeDataString(item.Value)}"));
        try
        {
            using var response = await _http.GetAsync(url);
            if (!response.IsSuccessStatusCode) return null;
            var root = JsonNode.Parse(await response.Content.ReadAsStringAsync())?.AsObject();
            return root is null || root["code"]?.GetValue<int>() != 0 ? null : root;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or JsonException) { return null; }
    }

    private async Task EnsureKtorSession(long uin)
    {
        if (_registered.Contains(uin)) return;
        await _registerLock.WaitAsync();
        try
        {
            if (_registered.Contains(uin)) return;
            var guid = Convert.ToHexString(Context.Keystore.Guid).ToLowerInvariant();
            var root = await GetKtor("/register", new()
            {
                ["uin"] = uin.ToString(), ["android_id"] = guid, ["guid"] = guid,
                ["qimei36"] = guid + "0000", ["key"] = Environment.GetEnvironmentVariable("PAD_SIGN_KEY") ?? "114514",
                ["qua"] = Context.AppInfo.Qua, ["version"] = Context.AppInfo.PtVersion, ["code"] = Context.AppInfo.AppClientVersion.ToString(),
            });
            if (root is null) throw new InvalidOperationException("签名服务注册失败");
            _registered.Add(uin);
        }
        finally { _registerLock.Release(); }
    }

    private async Task<JsonObject?> Post(string path, JsonObject payload)
    {
        using var content = new StringContent(payload.ToJsonString(), Encoding.UTF8, "application/json");
        try
        {
            using var response = await _http.PostAsync(_baseUrl + path, content);
            if (!response.IsSuccessStatusCode) return null;
            var root = JsonNode.Parse(await response.Content.ReadAsStringAsync())?.AsObject();
            if (root is null || root["code"]?.GetValue<int>() != 0) return null;
            return root;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or JsonException) { return null; }
    }

    private static byte[] Hex(string? value) => string.IsNullOrEmpty(value) ? [] : Convert.FromHexString(value);

    public void Dispose() => _http.Dispose();
}

/// <summary>Reads Lagrange's own Android command set without copying a stale list.</summary>
public static class AndroidSignWhitelist
{
    public static readonly HashSet<string> Commands = Load();

    private static HashSet<string> Load()
    {
        var type = typeof(BotSignProvider).Assembly.GetType("Lagrange.Core.Common.DefaultAndroidBotSignProvider", true)!;
        var field = type.GetField("WhiteListCommand", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static)
            ?? throw new InvalidOperationException("Lagrange Android signing command set is unavailable");
        return new HashSet<string>((HashSet<string>)field.GetValue(null)!, StringComparer.Ordinal);
    }
}
