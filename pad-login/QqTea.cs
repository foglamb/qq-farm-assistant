using System.Reflection;
using System.Security.Cryptography;
using Lagrange.Core.Common;

namespace PadLogin;

/// <summary>Strongly typed Span delegates to Lagrange's built-in QQ TEA implementation.</summary>
internal static class QqTea
{
    private delegate byte[] TeaDelegate(ReadOnlySpan<byte> data, ReadOnlySpan<byte> key);
    private static readonly TeaDelegate ReferenceEncrypt = Load("Encrypt");
    private static readonly TeaDelegate ReferenceDecrypt = Load("Decrypt");

    public static byte[] Encrypt(ReadOnlySpan<byte> source, ReadOnlySpan<byte> key) => ReferenceEncrypt(source, key);
    public static byte[] Decrypt(ReadOnlySpan<byte> source, ReadOnlySpan<byte> key) => ReferenceDecrypt(source, key);

    private static TeaDelegate Load(string name)
    {
        var type = typeof(BotSignProvider).Assembly.GetType("Lagrange.Core.Utility.Cryptography.TeaProvider", true)!;
        const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
        return (TeaDelegate)type.GetMethod(name, flags, [typeof(ReadOnlySpan<byte>), typeof(ReadOnlySpan<byte>)])!.CreateDelegate(typeof(TeaDelegate));
    }

    public static void SelfTest()
    {
        var key = Convert.FromHexString("00112233445566778899AABBCCDDEEFF");
        foreach (var length in new[] { 1, 7, 8, 9, 64, 1024 })
        {
            var source = new byte[length];
            Random.Shared.NextBytes(source);
            if (!Decrypt(Encrypt(source, key), key).AsSpan().SequenceEqual(source)) throw new CryptographicException($"QQ TEA delegate mismatch at {length}");
        }
    }
}
