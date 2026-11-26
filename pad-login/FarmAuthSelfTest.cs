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
        using var context = BotFactory.Create(new BotConfig
        {
            Protocol = Protocols.AndroidPad,
            CustomServices = [service],
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
    }
}
