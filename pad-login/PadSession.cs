using System.Text.Json;
using Lagrange.Core;
using Lagrange.Core.Common;
using Lagrange.Core.Common.Entity;
using Lagrange.Core.Common.Interface;
using Lagrange.Core.Events.EventArgs;

namespace PadLogin;

public sealed partial class PadSession : IDisposable
{
    private readonly string _dataDir;
    private readonly string _keystorePath;
    private readonly SemaphoreSlim _loginLock = new(1, 1);
    private readonly CancellationTokenSource _closing = new();
    private readonly object _sync = new();
    private readonly BotAppInfo _appInfo;
    private BotContext? _context;
    private byte[]? _qrImage;
    private string _phase = "idle";
    private string _detail = "尚未开始 Pad 登录";
    private string? _loginError;
    private readonly List<string> _errors = new();
    private string? _verifyUrl;
    private string? _phone;

    public PadSession(string? sessionDirectory = null)
    {
        _dataDir = sessionDirectory is null
            ? Environment.GetEnvironmentVariable("PAD_DATA_DIR") ?? Path.Combine(Directory.GetCurrentDirectory(), "data")
            : Path.Combine(Path.GetFullPath(sessionDirectory), "qq-data");
        Directory.CreateDirectory(_dataDir);
        _keystorePath = Path.Combine(_dataDir, "keystore.json");
        _appInfo = CreateAppInfo();
    }

    public bool SignConfigured => !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("PAD_SIGN_URL"));

    internal string KeystorePath => _keystorePath;
    public long? Uin => _context?.Keystore.Uin > 0 ? _context.Keystore.Uin : null;
    public bool CanRequestCode => _context?.IsOnline == true;
    public string? Phone { get { lock (_sync) return _phone; } }

    public object Status()
    {
        lock (_sync)
        {
            return new
            {
                protocol = "AndroidPad",
                protocolVersion = _appInfo.PtVersion,
                phase = _phase,
                detail = _detail,
                signConfigured = SignConfigured,
                signMode = Environment.GetEnvironmentVariable("PAD_SIGN_STYLE") ?? "json",
                hasQr = _qrImage is not null,
                verifyUrl = _verifyUrl,
                phone = _phone,
                hasSavedSession = HasSavedSession(),
                hasDevice = HasDevice(),
                errors = _errors.ToArray(),
            };
        }
    }

    public PadSessionSnapshot Snapshot()
    {
        lock (_sync)
        {
            return new PadSessionSnapshot(_phase, _detail, CanRequestCode, _verifyUrl, _phone, _context?.Keystore.Uin > 0 ? _context.Keystore.Uin : null);
        }
    }

    public byte[]? QrImage()
    {
        lock (_sync) return _qrImage?.ToArray();
    }

    public async Task StartLoginAsync(long uin = 0, string? password = null)
    {
        if (!SignConfigured)
        {
            lock (_sync) { _phase = "error"; _detail = "未配置 PAD_SIGN_URL；需要兼容当前 AndroidPad 版本的签名服务"; }
            return;
        }
        var hasSaved = HasSavedSession();
        if (!hasSaved && (uin <= 0 || string.IsNullOrEmpty(password)))
        {
            lock (_sync) { _phase = "needs_password"; _detail = "Lagrange V2 的 AndroidPad 首次登录需要 QQ 号和密码；成功后仅保存 keystore，之后可免密恢复"; }
            return;
        }
        if (!await _loginLock.WaitAsync(0)) return;
        try
        {
            lock (_sync)
            {
                if (_phase is "starting" or "waiting_scan" or "scanned" or "online") return;
                _phase = "starting";
                _detail = "正在初始化 AndroidPad 登录";
                _qrImage = null;
                _verifyUrl = null;
                _loginError = null;
                _errors.Clear();
                _phone = null;
            }
            var sign = new AndroidSignClient(Environment.GetEnvironmentVariable("PAD_SIGN_URL")!);
            var config = new BotConfig
            {
                Protocol = Protocols.AndroidPad,
                SignProvider = sign,
                AutoReconnect = true,
                AutoReLogin = true,
                CustomServices = [new FarmCodeService(), new FarmAuthService(), new FarmPlainService()],
            };
            _context?.Dispose();
            BotKeystore? saved = null;
            if (File.Exists(_keystorePath))
            {
                try { saved = JsonSerializer.Deserialize<BotKeystore>(await File.ReadAllTextAsync(_keystorePath, _closing.Token)); }
                catch (JsonException) { saved = null; }
            }
            _context = saved is null
                ? BotFactory.Create(config, appInfo: _appInfo)
                : BotFactory.Create(config, saved, _appInfo);
            RegisterEvents(_context);
            await PersistKeystore(_context.Keystore);
            var success = uin > 0 && !string.IsNullOrEmpty(password)
                ? await _context.Login(uin, password, _closing.Token)
                : await _context.Login(_closing.Token);
            lock (_sync)
            {
                _phase = success ? "online" : "error";
                _detail = success ? "AndroidPad 登录成功，可同时观察 Windows QQ 在线状态" : _loginError ?? "AndroidPad 登录未完成，请重新登录";
            }
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            lock (_sync) { _phase = "error"; _detail = error.Message; }
        }
        finally { _loginLock.Release(); }
    }

    private static string? OptionalEnv(string name) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } value ? value : null;

    private static BotAppInfo CreateAppInfo()
    {
        using var defaultContext = BotFactory.Create(new BotConfig { Protocol = Protocols.AndroidPad });
        var source = defaultContext.AppInfo;
        return new BotAppInfo
        {
            Os = source.Os,
            VendorOs = source.VendorOs,
            Kernel = source.Kernel,
            Qua = OptionalEnv("PAD_QUA") ?? source.Qua,
            CurrentVersion = OptionalEnv("PAD_CURRENT_VERSION") ?? source.CurrentVersion,
            PtVersion = OptionalEnv("PAD_PT_VERSION") ?? source.PtVersion,
            SsoVersion = source.SsoVersion,
            PackageName = source.PackageName,
            ApkSignatureMd5 = source.ApkSignatureMd5,
            SdkInfo = new WtLoginSdkInfo
            {
                SdkBuildTime = uint.TryParse(Environment.GetEnvironmentVariable("PAD_SDK_BUILD_TIME"), out var buildTime) ? buildTime : source.SdkInfo.SdkBuildTime,
                SdkVersion = OptionalEnv("PAD_SDK_VERSION") ?? source.SdkInfo.SdkVersion,
                MiscBitMap = uint.TryParse(Environment.GetEnvironmentVariable("PAD_MISC_BITMAP"), out var miscBitmap) ? miscBitmap : source.SdkInfo.MiscBitMap,
                SubSigMap = uint.TryParse(Environment.GetEnvironmentVariable("PAD_SUB_SIG_MAP"), out var subSigMap) ? subSigMap : source.SdkInfo.SubSigMap,
                MainSigMap = uint.TryParse(Environment.GetEnvironmentVariable("PAD_MAIN_SIG_MAP"), out var mainSigMap) ? (Sig)mainSigMap : source.SdkInfo.MainSigMap,
            },
            AppId = source.AppId,
            SubAppId = int.TryParse(Environment.GetEnvironmentVariable("PAD_SUB_APP_ID"), out var subAppId) ? subAppId : source.SubAppId,
            AppClientVersion = ushort.TryParse(Environment.GetEnvironmentVariable("PAD_APP_CLIENT_VERSION"), out var clientVersion) ? clientVersion : source.AppClientVersion,
        };
    }

    private bool HasSavedSession()
    {
        try
        {
            if (!File.Exists(_keystorePath)) return false;
            using var document = JsonDocument.Parse(File.ReadAllText(_keystorePath));
            var a2 = document.RootElement.GetProperty("WLoginSigs").GetProperty("A2");
            return a2.ValueKind switch
            {
                JsonValueKind.String => !string.IsNullOrEmpty(a2.GetString()),
                JsonValueKind.Array => a2.GetArrayLength() > 0,
                _ => false,
            };
        }
        catch (Exception error) when (error is IOException or JsonException or KeyNotFoundException or InvalidOperationException) { return false; }
    }

    private bool HasDevice()
    {
        try
        {
            if (!File.Exists(_keystorePath)) return false;
            using var document = JsonDocument.Parse(File.ReadAllText(_keystorePath));
            var guid = document.RootElement.GetProperty("Guid");
            return guid.ValueKind switch
            {
                JsonValueKind.String => !string.IsNullOrEmpty(guid.GetString()),
                JsonValueKind.Array => guid.GetArrayLength() > 0,
                _ => false,
            };
        }
        catch (Exception error) when (error is IOException or JsonException or KeyNotFoundException) { return false; }
    }

    private async Task PersistKeystore(BotKeystore keystore)
    {
        await File.WriteAllTextAsync(_keystorePath, JsonSerializer.Serialize(keystore), _closing.Token);
        try { File.SetUnixFileMode(_keystorePath, UnixFileMode.UserRead | UnixFileMode.UserWrite); } catch { }
    }

    private void RegisterEvents(BotContext context)
    {
        context.EventInvoker.RegisterEvent<BotLogEvent>((_, args) =>
        {
            if (args.Level < LogLevel.Warning) return Task.CompletedTask;
            var message = args.Message.Length > 800 ? args.Message[..800] : args.Message;
            lock (_sync)
            {
                _errors.Add($"{args.Level} {args.Tag}: {message}");
                if (_errors.Count > 20) _errors.RemoveAt(0);
                if (args.Level >= LogLevel.Error) _loginError = $"{args.Tag}: {message}";
            }
            return Task.CompletedTask;
        });
        context.EventInvoker.RegisterEvent<BotQrCodeEvent>((_, args) =>
        {
            lock (_sync)
            {
                _qrImage = args.Image.ToArray();
                _phase = "waiting_scan";
                _detail = "请用手机 QQ 扫描 AndroidPad 二维码";
            }
            return Task.CompletedTask;
        });
        context.EventInvoker.RegisterEvent<BotQrCodeQueryEvent>((_, args) =>
        {
            lock (_sync)
            {
                var state = args.State.ToString();
                if (state.Contains("Confirm", StringComparison.OrdinalIgnoreCase)) _phase = "scanned";
                _detail = "Pad 扫码状态: " + state;
            }
            return Task.CompletedTask;
        });
        context.EventInvoker.RegisterEvent<BotLoginEvent>((_, args) =>
        {
            if (!args.Success)
            {
                lock (_sync) { _loginError = $"腾讯登录失败：state={args.State}，{args.Error?.Tag ?? "登录"}：{args.Error?.Message ?? "未知错误"}"; }
            }
            return Task.CompletedTask;
        });
        context.EventInvoker.RegisterEvent<BotRefreshKeystoreEvent>(async (_, args) =>
        {
            if (args.Keystore.WLoginSigs.A2.Length == 0) return;
            await PersistKeystore(args.Keystore);
        });
        context.EventInvoker.RegisterEvent<BotNewDeviceVerifyEvent>((_, args) =>
        {
            lock (_sync) { _verifyUrl = args.Url; _phase = "needs_device_verify"; _detail = "需要新设备验证，请打开下方验证链接"; }
            return Task.CompletedTask;
        });
        context.EventInvoker.RegisterEvent<BotCaptchaEvent>((_, args) =>
        {
            lock (_sync) { _verifyUrl = args.CaptchaUrl; _phase = "needs_captcha"; _detail = "需要腾讯验证码/短信验证，请打开下方链接并提交结果"; }
            return Task.CompletedTask;
        });
    }

    public bool SubmitCaptcha(string ticket, string randstr) => SubmitCaptchaAsync(ticket, randstr).GetAwaiter().GetResult();

    public bool SubmitSms(string code) => SubmitSmsAsync(code).GetAwaiter().GetResult();

    public async Task<bool> SubmitCaptchaAsync(string ticket, string randstr)
    {
        var context = _context ?? throw new InvalidOperationException("登录会话不存在，请重新登录");
        var accepted = context.SubmitCaptcha(ticket, randstr);
        lock (_sync)
        {
            _phase = accepted ? "needs_sms" : "error";
            _detail = accepted ? "滑块已提交；如腾讯已发送短信，请输入手机短信验证码完成登录" : "验证码会话已结束，请重新输入密码登录";
            if (accepted) _verifyUrl = null;
        }
        await Task.CompletedTask;
        return accepted;
    }

    public async Task<bool> SubmitSmsAsync(string code)
    {
        var context = _context ?? throw new InvalidOperationException("登录会话不存在，请重新登录");
        var accepted = context.SubmitSMSCode(code);
        lock (_sync)
        {
            _phase = accepted ? "verifying" : "error";
            _detail = accepted ? "短信码已提交，正在等待腾讯登录结果" : "短信验证会话已结束，请重新输入密码登录";
            if (accepted) _verifyUrl = null;
        }
        await Task.CompletedTask;
        return accepted;
    }

    public async Task<FarmAuthResponse> GetFarmCodeAsync()
    {
        var context = _context ?? throw new InvalidOperationException("请先完成 AndroidPad 登录");
        if (!context.IsOnline) throw new InvalidOperationException("AndroidPad 当前不在线");
        var mode = Environment.GetEnvironmentVariable("FARM_AUTH_MODE") ?? "miniapp";
        if (string.Equals(mode, "plain", StringComparison.OrdinalIgnoreCase))
        {
            return await context.SendEvent<FarmAuthResponse>(new FarmPlainRequest(FarmAuthPayloadRequest.Create(context)));
        }
        if (string.Equals(mode, "emp", StringComparison.OrdinalIgnoreCase))
        {
            return await context.SendEvent<FarmAuthResponse>(new FarmAuthRequest(FarmAuthPayloadRequest.Create(context)));
        }
        return await context.SendEvent<FarmAuthResponse>(new FarmCodeRequest());
    }

    public void Dispose()
    {
        _closing.Cancel();
        try { _context?.Logout().GetAwaiter().GetResult(); } catch { }
        _context?.Dispose();
        _closing.Dispose();
        _loginLock.Dispose();
    }
}
