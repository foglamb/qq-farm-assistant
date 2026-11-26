using System.Text.Json;
using Lagrange.Core;
using Lagrange.Core.Common;
using Lagrange.Core.Common.Entity;
using Lagrange.Core.Common.Interface;
using Lagrange.Core.Events.EventArgs;

namespace PadLogin;

public sealed class PadSession : IDisposable
{
    private readonly string _dataDir;
    private readonly string _keystorePath;
    private readonly SemaphoreSlim _loginLock = new(1, 1);
    private readonly CancellationTokenSource _closing = new();
    private readonly object _sync = new();
    private BotContext? _context;
    private byte[]? _qrImage;
    private string _phase = "idle";
    private string _detail = "尚未开始 Pad 登录";
    private string? _verifyUrl;

    public PadSession()
    {
        _dataDir = Environment.GetEnvironmentVariable("PAD_DATA_DIR") ?? Path.Combine(Directory.GetCurrentDirectory(), "data");
        Directory.CreateDirectory(_dataDir);
        _keystorePath = Path.Combine(_dataDir, "keystore.json");
    }

    public bool SignConfigured => !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("PAD_SIGN_URL"));

    public object Status()
    {
        lock (_sync)
        {
            return new
            {
                protocol = "AndroidPad",
                protocolVersion = "9.2.20",
                phase = _phase,
                detail = _detail,
                signConfigured = SignConfigured,
                hasQr = _qrImage is not null,
                verifyUrl = _verifyUrl,
                hasSavedSession = File.Exists(_keystorePath),
            };
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
            lock (_sync) { _phase = "error"; _detail = "未配置 PAD_SIGN_URL；需要 Android 9.2.20 签名服务"; }
            return;
        }
        if (!File.Exists(_keystorePath) && (uin <= 0 || string.IsNullOrEmpty(password)))
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
            }
            var sign = new AndroidSignClient(Environment.GetEnvironmentVariable("PAD_SIGN_URL")!);
            var config = new BotConfig
            {
                Protocol = Protocols.AndroidPad,
                SignProvider = sign,
                AutoReconnect = true,
                AutoReLogin = true,
                CustomServices = [new FarmAuthService()],
            };
            if (File.Exists(_keystorePath))
            {
                var saved = JsonSerializer.Deserialize<BotKeystore>(await File.ReadAllTextAsync(_keystorePath, _closing.Token))
                    ?? throw new InvalidOperationException("保存的 Pad 登录态无法读取，请删除隔离数据后重试");
                _context = BotFactory.Create(config, saved);
            }
            else _context = BotFactory.Create(config);
            RegisterEvents(_context);
            var success = uin > 0 && !string.IsNullOrEmpty(password)
                ? await _context.Login(uin, password, _closing.Token)
                : await _context.Login(_closing.Token);
            lock (_sync)
            {
                _phase = success ? "online" : "error";
                _detail = success ? "AndroidPad 登录成功，可同时观察 Windows QQ 在线状态" : "AndroidPad 登录未完成";
            }
        }
        catch (Exception error) when (error is not OperationCanceledException)
        {
            lock (_sync) { _phase = "error"; _detail = error.Message; }
        }
        finally { _loginLock.Release(); }
    }

    private void RegisterEvents(BotContext context)
    {
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
        context.EventInvoker.RegisterEvent<BotRefreshKeystoreEvent>(async (_, args) =>
        {
            await File.WriteAllTextAsync(_keystorePath, JsonSerializer.Serialize(args.Keystore), _closing.Token);
            try { File.SetUnixFileMode(_keystorePath, UnixFileMode.UserRead | UnixFileMode.UserWrite); } catch { }
        });
        context.EventInvoker.RegisterEvent<BotNewDeviceVerifyEvent>((_, args) =>
        {
            lock (_sync) { _verifyUrl = args.Url; _detail = "需要新设备验证"; }
            return Task.CompletedTask;
        });
        context.EventInvoker.RegisterEvent<BotCaptchaEvent>((_, args) =>
        {
            lock (_sync) { _verifyUrl = args.CaptchaUrl; _detail = "需要验证码后调用 /captcha"; }
            return Task.CompletedTask;
        });
    }

    public void SubmitCaptcha(string ticket, string randstr) => _context?.SubmitCaptcha(ticket, randstr);
    public void SubmitSms(string code) => _context?.SubmitSMSCode(code);

    public async Task<FarmAuthResponse> GetFarmCodeAsync()
    {
        var context = _context ?? throw new InvalidOperationException("请先完成 AndroidPad 登录");
        if (!context.IsOnline) throw new InvalidOperationException("AndroidPad 当前不在线");
        return await context.SendEvent<FarmAuthResponse>(new FarmAuthRequest(FarmAuthPayloadRequest.Create(context)));
    }

    public void Dispose()
    {
        _closing.Cancel();
        try { _context?.Logout().GetAwaiter().GetResult(); } catch { }
        _closing.Dispose();
        _loginLock.Dispose();
    }
}
