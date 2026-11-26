namespace PadLogin;

/// <summary>Device identity only. Never include Uin, Uid, passwords or WLoginSigs.</summary>
public sealed record PadDeviceProfile(byte[] Guid, string? AndroidId, string? Qimei, string? DeviceName);
