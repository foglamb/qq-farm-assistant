using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Lagrange.Core.Common;

namespace PadLogin;

/// <summary>
/// Android 9.2.20 signing API client. The signing service is explicitly
/// configured by the operator; no third-party endpoint is implied.
/// </summary>
public sealed class AndroidSignClient(string baseUrl) : AndroidBotSignProvider, IDisposable
{
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(15) };
    private readonly string _baseUrl = baseUrl.TrimEnd('/');

    public override bool IsWhiteListCommand(string cmd) => AndroidSignWhitelist.Commands.Contains(cmd);

    public override async Task<SsoSecureInfo?> GetSecSign(long uin, string cmd, int seq, ReadOnlyMemory<byte> body)
    {
        var payload = new JsonObject
        {
            ["uin"] = uin,
            ["cmd"] = cmd,
            ["seq"] = seq,
            ["buffer"] = Convert.ToHexString(body.Span),
            ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
            ["version"] = Context.AppInfo.PtVersion,
            ["qua"] = Context.AppInfo.Qua,
        };
        var response = await Post("/sign", payload);
        if (response is null) return null;
        var data = response["data"];
        if (data is null) return null;
        return new SsoSecureInfo
        {
            SecSign = Hex(data["sign"]?.GetValue<string>()),
            SecToken = Hex(data["token"]?.GetValue<string>()),
            SecExtra = Hex(data["extra"]?.GetValue<string>()),
        };
    }

    public override Task<byte[]> GetEnergy(long uin, string data) => GetBytes("/energy", new JsonObject
    {
        ["uin"] = uin,
        ["data"] = data,
        ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
        ["ver"] = Context.AppInfo.SdkInfo.SdkVersion,
        ["version"] = Context.AppInfo.PtVersion,
        ["qua"] = Context.AppInfo.Qua,
    });

    public override Task<byte[]> GetDebugXwid(long uin, string data) => GetBytes("/get_tlv553", new JsonObject
    {
        ["uin"] = uin,
        ["data"] = data,
        ["guid"] = Convert.ToHexString(Context.Keystore.Guid),
        ["version"] = Context.AppInfo.PtVersion,
        ["qua"] = Context.AppInfo.Qua,
    });

    private async Task<byte[]> GetBytes(string path, JsonObject payload)
    {
        var response = await Post(path, payload);
        return Hex(response?["data"]?.GetValue<string>());
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
        catch (HttpRequestException) { return null; }
        catch (TaskCanceledException) { return null; }
        catch (JsonException) { return null; }
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
