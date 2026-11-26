namespace PadLogin;

public sealed record PadSessionSnapshot(string Phase, string Message, bool CanRequest, string? VerifyUrl, string? Phone, long? Uin);
