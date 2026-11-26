using System.Text;
using Lagrange.Core;
using Lagrange.Core.Common;
using Lagrange.Core.Common.Entity;
using Lagrange.Core.Events;
using Lagrange.Core.Services;
using Lagrange.Proto;
using Lagrange.Proto.Serialization;

namespace PadLogin;

public sealed class FarmCodeRequest : ProtocolEvent;

[EventSubscribe<FarmCodeRequest>(Protocols.AndroidPad)]
[Service("LightAppSvc.mini_program_auth.GetCode", RequestType.Simple, EncryptType.EncryptD2Key)]
public sealed class FarmCodeService : BaseService<FarmCodeRequest, FarmAuthResponse>
{
    protected override ValueTask<ReadOnlyMemory<byte>> Build(FarmCodeRequest input, BotContext context)
    {
        var request = new MiniQWebRequest
        {
            Seq = 3,
            Qua = context.AppInfo.Qua,
            DeviceInfo = "",
            BusiBuff = ProtoSerializer.Serialize(new MiniGetCodeRequest
            {
                AppId = Environment.GetEnvironmentVariable("FARM_APPID") ?? "1112386029",
            }),
            TraceId = context.Keystore.Uin.ToString(),
        };
        return ValueTask.FromResult<ReadOnlyMemory<byte>>(ProtoSerializer.Serialize(request));
    }

    protected override ValueTask<FarmAuthResponse> Parse(ReadOnlyMemory<byte> input, BotContext context)
    {
        try
        {
            var response = ProtoSerializer.Deserialize<MiniQWebResponse>(input.Span);
            var message = Encoding.UTF8.GetString(response.ErrMsg);
            var code = "";
            if (response.BusiBuff.Length > 0)
            {
                code = ProtoSerializer.Deserialize<MiniGetCodeResponse>(response.BusiBuff).Code;
            }
            else if (response.RetCode == 0 && response.Seq == 0)
            {
                // 兼容少数服务端直接返回 StGetCodeRsp 的情况；不接受空/default 成功。
                code = ProtoSerializer.Deserialize<MiniGetCodeResponse>(input.Span).Code;
            }
            var ret = response.RetCode >= 0 && response.RetCode <= uint.MaxValue
                ? (uint)response.RetCode
                : uint.MaxValue;
            if (ret == 0 && string.IsNullOrEmpty(code))
            {
                return ValueTask.FromResult(new FarmAuthResponse(uint.MaxValue, "GetCode ret=0 但 busiBuff/code 为空", ""));
            }
            return ValueTask.FromResult(new FarmAuthResponse(ret, message, code));
        }
        catch (Exception error)
        {
            return ValueTask.FromResult(new FarmAuthResponse(uint.MaxValue, $"GetCode响应解析失败 len={input.Length} {error.GetType().Name}: {error.Message}", ""));
        }
    }
}

public sealed class MiniQWebRequest
{
    [ProtoMember(1)] public ulong Seq { get; set; }
    [ProtoMember(2)] public string Qua { get; set; } = "";
    [ProtoMember(3)] public string DeviceInfo { get; set; } = "";
    [ProtoMember(4)] public byte[] BusiBuff { get; set; } = [];
    [ProtoMember(5)] public string TraceId { get; set; } = "";
}

public sealed class MiniGetCodeRequest
{
    [ProtoMember(1)] public string AppId { get; set; } = "";
}

public sealed class MiniQWebResponse
{
    [ProtoMember(1)] public ulong Seq { get; set; }
    [ProtoMember(2)] public long RetCode { get; set; }
    [ProtoMember(3)] public byte[] ErrMsg { get; set; } = [];
    [ProtoMember(4)] public byte[] BusiBuff { get; set; } = [];
}

public sealed class MiniGetCodeResponse
{
    [ProtoMember(2)] public string Code { get; set; } = "";
}
