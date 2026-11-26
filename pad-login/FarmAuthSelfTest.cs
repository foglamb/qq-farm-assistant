using System.Buffers.Binary;
using System.Text;
using Lagrange.Core;
using Lagrange.Core.Common;
using Lagrange.Core.Common.Interface;
using Lagrange.Core.Services;
using Lagrange.Proto.Serialization;

namespace PadLogin;

internal static class FarmAuthSelfTest
{
    public static async Task RunAsync()
    {
        var service = new FarmAuthService();
        var plainService = new FarmPlainService();
        var codeService = new FarmCodeService();
        using var context = BotFactory.Create(new BotConfig
        {
            Protocol = Protocols.AndroidPad,
            CustomServices = [service, plainService, codeService],
        });
        context.Keystore.WLoginSigs.A2 = Encoding.ASCII.GetBytes("synthetic-a2");
        context.Keystore.WLoginSigs.A2Key = Convert.FromHexString("00112233445566778899AABBCCDDEEFF");
        context.Keystore.WLoginSigs.SKey = Encoding.ASCII.GetBytes("synthetic-skey");

        var request = FarmAuthPayloadRequest.Create(context);
        var bodyArray = (await ((IService)service).Build(new FarmAuthRequest(request), context)).ToArray();
        var ticketLength = BinaryPrimitives.ReadInt32BigEndian(bodyArray);
        if (ticketLength != context.Keystore.WLoginSigs.A2.Length) throw new InvalidDataException("A2 prefix length mismatch");
        if (!bodyArray.AsSpan(4, ticketLength).SequenceEqual(context.Keystore.WLoginSigs.A2)) throw new InvalidDataException("A2 prefix content mismatch");
        var decodedRequest = ProtoSerializer.Deserialize<FarmAuthPayloadRequest>(QqTea.Decrypt(bodyArray.AsSpan(4 + ticketLength), context.Keystore.WLoginSigs.A2Key));
        if (decodedRequest.AppId != 1112386029 || decodedRequest.SKey != "synthetic-skey" || decodedRequest.Pf != "openmobile_android") throw new InvalidDataException("auth_emp request fields mismatch");

        var responsePayload = new FarmAuthPayloadResponse { Ret = 0, Msg = "ok", Code = "synthetic-code" };
        var encrypted = QqTea.Encrypt(ProtoSerializer.Serialize(responsePayload), context.Keystore.WLoginSigs.A2Key);
        var responseBody = new byte[4 + context.Keystore.WLoginSigs.A2.Length + encrypted.Length];
        BinaryPrimitives.WriteInt32BigEndian(responseBody, context.Keystore.WLoginSigs.A2.Length);
        context.Keystore.WLoginSigs.A2.CopyTo(responseBody, 4);
        encrypted.CopyTo(responseBody, 4 + context.Keystore.WLoginSigs.A2.Length);
        var parsed = (FarmAuthResponse)await ((IService)service).Parse(responseBody, context);
        if (parsed.Ret != 0 || parsed.Code != "synthetic-code") throw new InvalidDataException("auth_emp response code mismatch");

        var plainBody = await ((IService)plainService).Build(new FarmPlainRequest(request), context);
        if (ProtoSerializer.Deserialize<FarmAuthPayloadRequest>(plainBody.Span).AppId != 1112386029) throw new InvalidDataException("auth plain request mismatch");
        var plainParsed = (FarmAuthResponse)await ((IService)plainService).Parse(ProtoSerializer.Serialize(responsePayload), context);
        if (plainParsed.Ret != 0 || plainParsed.Code != "synthetic-code") throw new InvalidDataException("auth plain response mismatch");

        var codeBody = await ((IService)codeService).Build(new FarmCodeRequest(), context);
        var qweb = ProtoSerializer.Deserialize<MiniQWebRequest>(codeBody.Span);
        if (qweb.Seq != 3 || qweb.Qua != context.AppInfo.Qua || qweb.TraceId != "0") throw new InvalidDataException("GetCode outer fields mismatch");
        if (ProtoSerializer.Deserialize<MiniGetCodeRequest>(qweb.BusiBuff).AppId != "1112386029") throw new InvalidDataException("GetCode appid mismatch");
        var codeResponse = ProtoSerializer.Serialize(new MiniQWebResponse
        {
            Seq = 3,
            RetCode = 0,
            BusiBuff = ProtoSerializer.Serialize(new MiniGetCodeResponse { Code = "synthetic-code" }),
        });
        var codeParsed = (FarmAuthResponse)await ((IService)codeService).Parse(codeResponse, context);
        if (codeParsed.Ret != 0 || codeParsed.Code != "synthetic-code") throw new InvalidDataException("GetCode response mismatch");
    }
}
