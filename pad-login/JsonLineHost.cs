using System.Text.Json;
using System.Text.Json.Serialization;

namespace PadLogin;

internal sealed record JsonLineCommand(
    string Command,
    string? Mode = null,
    long Uin = 0,
    string? Password = null,
    string? Ticket = null,
    string? Randstr = null,
    string? Code = null,
    string? RequestId = null)
{
    public static JsonLineCommand Parse(string line)
    {
        using var document = JsonDocument.Parse(line);
        if (document.RootElement.ValueKind != JsonValueKind.Object) throw new JsonException("命令必须是 JSON 对象");
        var root = document.RootElement;
        var command = RequiredString(root, "command");
        return new JsonLineCommand(
            command,
            OptionalString(root, "mode"),
            OptionalUin(root),
            OptionalString(root, "password"),
            OptionalString(root, "ticket"),
            OptionalString(root, "randstr"),
            OptionalString(root, "code"),
            OptionalString(root, "requestId"));
    }

    private static string RequiredString(JsonElement root, string name) => OptionalString(root, name) is { Length: > 0 } value ? value : throw new JsonException($"缺少 {name}");

    private static string? OptionalString(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value) || value.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return null;
        if (value.ValueKind != JsonValueKind.String) throw new JsonException($"{name} 必须是字符串");
        return value.GetString();
    }

    private static long OptionalUin(JsonElement root)
    {
        if (!root.TryGetProperty("uin", out var value) || value.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return 0;
        if (value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var number)) return number;
        if (value.ValueKind == JsonValueKind.String && long.TryParse(value.GetString(), out number)) return number;
        if (value.ValueKind == JsonValueKind.String && string.IsNullOrEmpty(value.GetString())) return 0;
        throw new JsonException("uin 必须是 QQ 号字符串或整数");
    }
}

internal static class JsonLineProtocol
{
    public const string Prefix = "QQFARM_LOGIN:";
    public static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    public static void EmitTo(TextWriter output, string kind, object value)
    {
        var json = JsonSerializer.Serialize(new { kind, value }, SerializerOptions);
        output.Write(Prefix);
        output.Write(json);
        output.Write('\n');
        output.Flush();
    }
}

public sealed class JsonLineHost : IDisposable
{
    private readonly PadSession _session;
    private readonly TextWriter _output;
    private readonly object _outputLock = new();
    private readonly CancellationTokenSource _closing = new();
    private Task? _startTask;
    private bool _requesting;
    private PadSessionSnapshot? _lastSnapshot;
    private long? _sessionUin;

    private JsonLineHost(PadSession session, TextWriter output)
    {
        _session = session;
        _output = output;
    }

    public static async Task RunAsync(string sessionDirectory, TextReader? input = null, TextWriter? output = null, CancellationToken cancellationToken = default)
    {
        using var session = new PadSession(sessionDirectory);
        using var host = new JsonLineHost(session, output ?? Console.Out);
        await host.Run(input ?? Console.In, cancellationToken);
    }

    private async Task Run(TextReader input, CancellationToken cancellationToken)
    {
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, _closing.Token);
        var token = linked.Token;
        EmitState(new PadSessionSnapshot("starting", "AndroidPad JSON-lines 宿主已启动", false, null, null, null));
        var monitor = Task.Run(() => Monitor(token), CancellationToken.None);
        try
        {
            while (!token.IsCancellationRequested)
            {
                var line = await input.ReadLineAsync(token);
                if (line is null) break;
                if (line.Length == 0) continue;
                if (line.Length > 65536) { EmitError("命令行过长", reason: "invalid_command"); continue; }
                JsonLineCommand command;
                try { command = JsonLineCommand.Parse(line); }
                catch (Exception error) when (error is JsonException or FormatException)
                {
                    EmitError("命令 JSON 无效：" + error.Message, reason: "invalid_command");
                    continue;
                }
                switch (command.Command)
                {
                    case "start":
                        Start(command);
                        break;
                    case "request_code":
                        await RequestCode(command.RequestId);
                        break;
                    case "submit_captcha":
                        await SubmitCaptcha(command);
                        break;
                    case "submit_sms":
                        await SubmitSms(command);
                        break;
                    case "shutdown":
                        _closing.Cancel();
                        break;
                    default:
                        EmitError("未知命令：" + command.Command, reason: "invalid_command");
                        break;
                }
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        finally
        {
            _closing.Cancel();
            if (_startTask is not null) try { await _startTask; } catch { }
            try { await monitor; } catch (OperationCanceledException) { }
        }
    }

    private void Start(JsonLineCommand command)
    {
        if (_startTask is { IsCompleted: false }) { EmitError("登录操作已在进行", reason: "busy"); return; }
        var mode = command.Mode ?? "qr";
        if (mode is not ("qr" or "password" or "restore")) { EmitError("start.mode 必须是 qr/password/restore", reason: "invalid_command"); return; }
        if (mode == "password" && (command.Uin <= 0 || string.IsNullOrEmpty(command.Password)))
        {
            EmitError("密码登录需要有效 uin/password", reason: "invalid_command");
            return;
        }
        if (mode == "qr")
        {
            EmitError("AndroidPad 使用账号密码登录；多账号扫码请使用 NapCat", reason: "pad_qr_blocked");
            return;
        }
        _lastSnapshot = null;
        _sessionUin = null;
        EmitState(new PadSessionSnapshot("starting", "正在启动 AndroidPad 登录", false, null, null, null));
        _startTask = Task.Run(async () =>
        {
            try
            {
                await _session.StartLoginAsync(command.Uin, mode == "password" ? command.Password : null);
                if (_session.CanRequestCode) await RequestCode(null);
            }
            catch (Exception error) { EmitError("登录启动失败：" + error.Message); }
        });
    }

    private async Task RequestCode(string? requestId)
    {
        if (_requesting) { EmitError("正在获取农场 Code，请稍后重试", requestId, "busy"); return; }
        if (!_session.CanRequestCode) { EmitError("AndroidPad 尚未在线，不能请求 Code", requestId, "offline"); return; }
        _requesting = true;
        EmitState(_session.Snapshot() with { Phase = "requesting", Message = "正在调用 LightAppSvc.mini_program_auth.GetCode", CanRequest = false }, requestId);
        try
        {
            var result = await _session.GetFarmCodeAsync();
            _requesting = false;
            if (result.Ret == 0 && !string.IsNullOrEmpty(result.Code))
            {
                Emit("code", new Dictionary<string, object?>
                {
                    ["code"] = result.Code,
                    ["requestId"] = requestId,
                });
                EmitState(_session.Snapshot() with { Phase = "success", Message = "已获取真实农场 Code", CanRequest = true }, requestId);
            }
            else
            {
                EmitError($"GetCode 返回错误：ret={result.Ret} {result.Message}".Trim(), requestId);
            }
        }
        catch (Exception error) { _requesting = false; EmitError("GetCode 调用失败：" + error.Message, requestId); }
        finally { _requesting = false; }
    }

    private async Task SubmitCaptcha(JsonLineCommand command)
    {
        if (string.IsNullOrEmpty(command.Ticket)) { EmitError("submit_captcha 需要 ticket", reason: "invalid_command"); return; }
        try { await _session.SubmitCaptchaAsync(command.Ticket, command.Randstr ?? ""); }
        catch (Exception error) { EmitError("验证码提交失败：" + error.Message); }
    }

    private async Task SubmitSms(JsonLineCommand command)
    {
        if (string.IsNullOrEmpty(command.Code)) { EmitError("submit_sms 需要 code", reason: "invalid_command"); return; }
        try { await _session.SubmitSmsAsync(command.Code); }
        catch (Exception error) { EmitError("短信码提交失败：" + error.Message); }
    }

    private async Task Monitor(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            var snapshot = _session.Snapshot();
            if (snapshot.Phase != "idle")
            {
                if (_sessionUin != snapshot.Uin && snapshot.Uin is > 0)
                {
                    _sessionUin = snapshot.Uin;
                    Emit("session", new { uin = snapshot.Uin.Value.ToString() });
                }
                if (!_requesting && snapshot != _lastSnapshot) EmitState(snapshot);
            }
            await Task.Delay(100, token);
        }
    }

    private void EmitError(string message, string? requestId = null, string? reason = null) =>
        EmitState(_session.Snapshot() with { Phase = "error", Message = message, CanRequest = false }, requestId, reason);

    private void EmitState(PadSessionSnapshot snapshot, string? requestId = null, string? reason = null)
    {
        _lastSnapshot = snapshot;
        Emit("state", new Dictionary<string, object?>
        {
            ["phase"] = snapshot.Phase,
            ["message"] = snapshot.Message,
            ["canRequest"] = snapshot.CanRequest && !_requesting && snapshot.Phase != "requesting",
            ["verifyUrl"] = snapshot.VerifyUrl,
            ["phone"] = snapshot.Phone,
            ["requestId"] = requestId,
            ["reason"] = reason,
        });
    }

    private void Emit(string kind, object value)
    {
        lock (_outputLock) JsonLineProtocol.EmitTo(_output, kind, value);
    }

    public void Dispose()
    {
        _closing.Cancel();
        _closing.Dispose();
    }
}
