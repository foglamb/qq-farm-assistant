using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using Lagrange.Core;
using Lagrange.Core.Common;
using Lagrange.Core.Common.Entity;
using Lagrange.Core.Events;
using Lagrange.Core.Services;
using Lagrange.Proto;
using Lagrange.Proto.Serialization;

namespace PadLogin;

[EventSubscribe<FarmAuthRequest>(Protocols.AndroidPad)]
[Service("QQConnectLogin.auth_emp", RequestType.D2Auth, EncryptType.NoEncrypt)]
public sealed class FarmAuthService : BaseService<FarmAuthRequest, FarmAuthResponse>
{
    protected override ValueTask<ReadOnlyMemory<byte>> Build(FarmAuthRequest input, BotContext context)
    {
        var sigs = context.Keystore.WLoginSigs;
        if (sigs.A2.Length == 0 || sigs.A2Key.Length != 16) throw new InvalidOperationException("AndroidPad A2 登录票据尚未就绪");
        var encrypted = QqTea.Encrypt(ProtoSerializer.Serialize(input.Payload), sigs.A2Key);
        var output = new byte[4 + sigs.A2.Length + encrypted.Length];
        BinaryPrimitives.WriteInt32BigEndian(output, sigs.A2.Length);
        sigs.A2.CopyTo(output, 4);
        encrypted.CopyTo(output, 4 + sigs.A2.Length);
        return ValueTask.FromResult<ReadOnlyMemory<byte>>(output);
    }

    protected override ValueTask<FarmAuthResponse> Parse(ReadOnlyMemory<byte> input, BotContext context)
    {
        var sigs = context.Keystore.WLoginSigs;
        var span = input.Span;
        if (span.Length < 8 || sigs.A2Key.Length != 16) throw new InvalidDataException("auth_emp 响应长度不足");
        var ticketLength = BinaryPrimitives.ReadInt32BigEndian(span);
        var encrypted = ticketLength >= 0 && 4 + ticketLength < span.Length ? span[(4 + ticketLength)..] : span;
        var payload = ProtoSerializer.Deserialize<FarmAuthPayloadResponse>(QqTea.Decrypt(encrypted, sigs.A2Key));
        return ValueTask.FromResult(new FarmAuthResponse(payload.Ret, payload.Msg, payload.Code));
    }
}

public sealed class FarmAuthRequest(FarmAuthPayloadRequest payload) : ProtocolEvent
{
    public FarmAuthPayloadRequest Payload { get; } = payload;
}

public sealed class FarmAuthResponse(uint ret, string message, string code) : ProtocolEvent
{
    public uint Ret { get; } = ret;
    public string Message { get; } = message;
    public string Code { get; } = code;
}

public sealed class FarmAuthPayloadRequest
{
    [ProtoMember(1)] public int ResponseType { get; set; }
    [ProtoMember(2)] public ulong AppId { get; set; }
    [ProtoMember(3)] public List<uint> OpenApi { get; set; } = [];
    [ProtoMember(4)] public string Pf { get; set; } = "openmobile_android";
    [ProtoMember(5)] public string SdkP { get; set; } = "android";
    [ProtoMember(6)] public string SdkV { get; set; } = "1.5.9";
    [ProtoMember(7)] public string QqV { get; set; } = "9.2.20";
    [ProtoMember(8)] public string Os { get; set; } = "14";
    [ProtoMember(11)] public string SKey { get; set; } = "";
    [ProtoMember(15)] public long Md5Time { get; set; }
    [ProtoMember(16)] public string Sign { get; set; } = "";
    [ProtoMember(19)] public long Vid { get; set; }
    [ProtoMember(20)] public int AppType { get; set; } = 1;
    [ProtoMember(21)] public int NeedPayToken { get; set; } = 1;
    [ProtoMember(30)] public string AppUniqueIdentifier { get; set; } = "";
    [ProtoMember(31)] public int Referer { get; set; } = 1;
    [ProtoMember(60)] public string State { get; set; } = "";

    public static FarmAuthPayloadRequest Create(BotContext context)
    {
        var package = Environment.GetEnvironmentVariable("FARM_PACKAGE_NAME") ?? "";
        var certMd5 = (Environment.GetEnvironmentVariable("FARM_CERT_MD5") ?? "").Replace(":", "").ToLowerInvariant();
        var time = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var sign = package.Length > 0 && certMd5.Length == 32
            ? Convert.ToHexString(MD5.HashData(Encoding.UTF8.GetBytes($"{package}_{certMd5}_{time}"))).ToLowerInvariant()
            : "";
        var openApi = (Environment.GetEnvironmentVariable("FARM_OPENAPI") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Select(uint.Parse).ToList();
        return new FarmAuthPayloadRequest
        {
            AppId = ulong.Parse(Environment.GetEnvironmentVariable("FARM_APPID") ?? "1112386029"),
            OpenApi = openApi,
            QqV = context.AppInfo.PtVersion,
            SKey = Encoding.UTF8.GetString(context.Keystore.WLoginSigs.SKey),
            Md5Time = string.IsNullOrEmpty(sign) ? 0 : time,
            Sign = sign,
            AppUniqueIdentifier = package,
        };
    }
}

public sealed class FarmAuthPayloadResponse
{
    [ProtoMember(1)] public uint Ret { get; set; }
    [ProtoMember(2)] public string Msg { get; set; } = "";
    [ProtoMember(3)] public string AccessToken { get; set; } = "";
    [ProtoMember(4)] public string Code { get; set; } = "";
    [ProtoMember(5)] public long ExpiresIn { get; set; }
    [ProtoMember(6)] public string OpenId { get; set; } = "";
}
