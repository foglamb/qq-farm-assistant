"""wtlogin.trans_emp / wtlogin.login / wtlogin.exchange_emp —— 手表扫码登录全链路。

本模块是 oicq 1.21.6 对应函数的逐字节 Python 等价实现（已用官方向量校验）：
  * `_buildLoginPacket`        -> build_login_packet
  * `_buildOICQPacket`         -> build_oicq_body（含 EMP 分支）
  * `_buildTransEmpPacket`     -> build_trans_emp_packet
  * `_decodeLoginResponse`     -> parse_login_response
  * `decodeT119` / `readT106`  -> parse_t119
  * `fetchQrcode` / `qrcodeLogin` / `_qrcodeLogin` -> 请求体构造
  * `exchangeEmp` / `refreshD2` -> subCmd 15 / 11 的 TLV 集合

关键结构（务必与响应侧区分，两侧布局不同）：

请求 SSO 体（0x0A / 0x0B 共用）
    u32(cmd_len+20) | u32(cmd_len+4) cmd | u32(8) session[4]
    | u32(4) u32(payload_len+4) payload

响应 SSO 体（0x0B 回包，解密后）
    i32 headlen | i32 seq | i32 retcode | u32 svc_len(含4) svc
    | u32 sess_len(含4) sess | i32 flag(0=原样 1=deflate 8=裸)
    | payload（0/1 时自 headlen+4 起，8 时自 headlen 起）

0x810 登录回包（TEA 解密后）
    [2B 版本] [1B type: 0=成功 2=滑验证码 160/162=设备锁 204=设备锁已验]
    [2B] TLV*
"""
from __future__ import annotations

import hashlib
import os
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from . import wire
from .wire import PbWriter, tea_decrypt, tea_encrypt, with_len

SERVICE_TRANS_EMP = "wtlogin.trans_emp"
SERVICE_LOGIN = "wtlogin.login"
SERVICE_EXCHANGE_EMP = "wtlogin.exchange_emp"

CMD_FETCH_QRCODE = 0x31
CMD_QUERY_QRCODE = 0x12

# 手表 / NT 客户端统一用 537067759（0x2005006F）作为 sso 里的 const
SSO_CONST = 537067759
BUF_UNKNOWN = bytes.fromhex("010000000000000000000100")

# 二维码头部魔数（oicq fetchQrcode / qrcodeLogin 里的硬编码）
QR_FETCH_HEAD = bytes.fromhex("0001110000001000000072000000")
QR_QUERY_HEAD = bytes.fromhex("0000620000001000000072000000")


@dataclass
class ClientProfile:
    """客户端画像：subAppId / apk 元信息 / 设备指纹。"""

    sub_appid: int
    appid: int = 16
    sigmap: int = 34869472
    bitmap: int = 184024956
    apk_ver: bytes = b"4.0.2"
    apk_name: str = "A8.4.1.2703aac4"
    apk_id: str = "com.tencent.qqlite"
    apk_sign: bytes = bytes.fromhex("a6b745bf24a2c277527716f6f36eb68d")
    buildtime: int = 1591690260
    sdkver: str = "6.0.0.2428"
    device_model: str = "OPPO Watch 3"
    device_brand: str = "OPPO"
    os_version: str = "11"

    def ksid(self, imei: str) -> bytes:
        """官方 ksid = `|imei|apk.name`（注意不是设备型号）。"""
        return f"|{imei}|{self.apk_name}".encode()


# 手表两个版本画像（sample 里的 PROFILE_ANDROID_WATCH / _208）
PROFILE_WATCH_205 = ClientProfile(sub_appid=537061176, apk_ver=b"2.0.5", apk_name="A2.0.5")
PROFILE_WATCH_208 = ClientProfile(sub_appid=537061176, apk_ver=b"2.0.8", apk_name="A2.0.8")


# ---------------------------------------------------------------------------
# 0x810 / 0x812 帧
# ---------------------------------------------------------------------------

def build_oicq_body(body: bytes, *, random_key: bytes, ecdh_public_key: bytes,
                    share_key: bytes, sig_key: bytes = b"", ticket_key: bytes = b"",
                    emp: bool = False) -> bytes:
    """0x810 内层 body（oicq `_buildOICQPacket`）。

    常规（enc=0x87）::

        02 01 | random_key[16] | 0131 | 0001 | u16(pub_len) pub | TEA(payload, share_key)

    EMP（enc=0x45）::

        u16(sig_key_len) sig_key | TEA(payload, ticket_key)
    """
    if emp:
        return struct.pack(">H", len(sig_key)) + sig_key + tea_encrypt(body, ticket_key)
    head = b"\x02\x01" + random_key + struct.pack(">HH", 0x0131, 0x0001)
    return head + struct.pack(">H", len(ecdh_public_key)) + ecdh_public_key + tea_encrypt(body, share_key)


def build_login_packet(*, seq: int, subid: int, session_id: bytes, imei: bytes | str,
                       ksid: bytes, command: str, payload: bytes, uin: int,
                       enc_type: int, d2: bytes = b"", tgt: bytes = b"",
                       d2key: bytes = b"") -> bytes:
    """0x0A 外壳 + 0x810 定长头 + body。

    type=0 心跳 / type=1 上线（D2Key 加密）/ type=2 登录（BUF16 加密）。
    """
    if isinstance(imei, str):
        imei = imei.encode()
    sso = bytearray()
    sso += struct.pack(">I", seq)
    sso += struct.pack(">I", subid)
    sso += struct.pack(">I", subid)
    sso += BUF_UNKNOWN
    sso += with_len(tgt)
    sso += with_len(command.encode())
    sso += with_len(session_id[:4])
    sso += with_len(imei)
    sso += struct.pack(">I", 4)
    sso += struct.pack(">H", len(ksid) + 2) + ksid
    sso += struct.pack(">I", 4)
    plain = with_len(bytes(sso)) + with_len(payload)
    # type=0 心跳不加密（oicq: 只有 type 1/2 走 TEA），密文字段与明文同构
    if enc_type == 1:
        cipher = tea_encrypt(plain, d2key)
    elif enc_type == 2:
        cipher = tea_encrypt(plain, b"\x00" * 16)
    else:
        cipher = plain
    inner = bytearray()
    inner += struct.pack(">I", 0x0A)
    inner += bytes([enc_type])
    inner += with_len(d2)
    inner += b"\x00"
    inner += with_len(str(uin).encode())
    inner += cipher
    return with_len(bytes(inner))


def pack_0810_frame(uin: int, enc_type: int, body: bytes) -> bytes:
    """裸 0x810 帧（不带 0x0A 外壳），用于 trans_emp 内层。"""
    return wire.pack_0810_frame(uin, enc_type, body)


def build_trans_emp_packet(*, seq: int, head: bytes, cmdid: int, body: bytes,
                           random_key: bytes, ecdh_public_key: bytes, share_key: bytes,
                           session_id: bytes, imei: bytes | str,
                           ksid: bytes | None = None) -> bytes:
    """wtlogin.trans_emp 五层封装（层次顺序极易写错，逐层校验过）::

        L1 = head | u32 ts | u8 2 | u16(44+len) | u16 cmdid | 21×00 | u8 3
             | u16 0 | u16 50 | u32 seq | u64 0 | payload | u8 3
        L2 = 02 01 | random_key | 0131 | 0001 | TLV(ecdh_pub) | TEA(L1, share_key)
        L3 = u8 2 | u16(29+len(L2)) | u16 8001 | u16 0x0812 | u16 1 | u32 0
             | u8 3 | u8 0x87 | u8 0 | u32 2 | u32 0 | u32 0 | L2 | u8 3
        sso = u32 seq | u32 const | u32 const | BUF_UNKNOWN | LP('') | LP(cmd)
              | LP(session) | LP(imei) | u32 4 | u16(len+2) ksid | u32 4
        plain  = LP(sso) | LP(L3)
        cipher = TEA(plain, BUF16)
        frame  = LP( u32 0x0A | u8 2 | LP('') | u8 0 | LP('0') | cipher )
    """
    if isinstance(imei, str):
        imei = imei.encode()
    l1 = bytearray()
    l1 += head
    l1 += struct.pack(">I", int(time.time()))
    l1 += b"\x02"
    l1 += struct.pack(">H", 44 + len(body))
    l1 += struct.pack(">H", cmdid)
    l1 += b"\x00" * 21
    l1 += b"\x03"
    l1 += struct.pack(">H", 0)
    l1 += struct.pack(">H", 50)
    l1 += struct.pack(">I", seq)
    l1 += b"\x00" * 8
    l1 += body
    l1 += b"\x03"

    l2 = bytearray(b"\x02\x01" + random_key + struct.pack(">HH", 0x0131, 0x0001))
    l2 += struct.pack(">H", len(ecdh_public_key)) + ecdh_public_key
    l2 += tea_encrypt(bytes(l1), share_key)

    l3 = bytearray()
    l3 += b"\x02"
    l3 += struct.pack(">H", 29 + len(l2))
    l3 += struct.pack(">H", 8001)
    l3 += struct.pack(">H", 0x0812)
    l3 += struct.pack(">H", 1)
    l3 += struct.pack(">I", 0)
    l3 += b"\x03"
    l3 += b"\x87"
    l3 += b"\x00"
    l3 += struct.pack(">I", 2)
    l3 += struct.pack(">I", 0)
    l3 += struct.pack(">I", 0)
    l3 += bytes(l2)
    l3 += b"\x03"

    sso = bytearray()
    sso += struct.pack(">I", seq)
    sso += struct.pack(">I", SSO_CONST)
    sso += struct.pack(">I", SSO_CONST)
    sso += BUF_UNKNOWN
    sso += with_len(b"")
    sso += with_len(SERVICE_TRANS_EMP.encode())
    sso += with_len(session_id[:4])
    sso += with_len(imei)
    sso += struct.pack(">I", 4)
    ksid_b = ksid if ksid is not None else b"|" + imei + b"|"
    sso += struct.pack(">H", len(ksid_b) + 2) + ksid_b
    sso += struct.pack(">I", 4)

    plain = with_len(bytes(sso)) + with_len(bytes(l3))
    cipher = tea_encrypt(plain, b"\x00" * 16)

    frame = bytearray()
    frame += struct.pack(">I", 0x0A)
    frame += b"\x02"
    frame += with_len(b"")
    frame += b"\x00"
    frame += with_len(b"0")
    frame += cipher
    return with_len(bytes(frame))


# ---------------------------------------------------------------------------
# 请求体：二维码 / 扫码结果 / exchange_emp
# ---------------------------------------------------------------------------

def build_fetch_qrcode_body(*, tlv: Dict[int, bytes], order: Sequence[int] = (0x16, 0x1B, 0x1D, 0x1F, 0x33, 0x35)) -> bytes:
    """cmdid=0x31 请求体：`u16 0 | u32 16 | u64 0 | u8 8 | 00 00 | u16 6 | TLV*`。"""
    out = bytearray()
    out += struct.pack(">HIQ", 0, 16, 0)
    out += b"\x08"
    out += struct.pack(">H", 0)              # writeTlv(BUF0) => u16 0
    out += struct.pack(">H", len(order))
    for tag in order:
        out += tlv[tag]
    return bytes(out)


def build_query_qrcode_body(qrcode_sig: bytes) -> bytes:
    """cmdid=0x12 请求体：`u16 5 | u8 1 | u32 8 | u32 16 | TLV(4B) sig | u64 0 | u8 8 | 00 00 | u16 0`。"""
    out = bytearray()
    out += struct.pack(">HBI", 5, 1, 8)
    out += struct.pack(">I", 16)
    out += struct.pack(">H", len(qrcode_sig)) + qrcode_sig
    out += struct.pack(">Q", 0)
    out += b"\x08"
    out += struct.pack(">H", 0)
    out += struct.pack(">H", 0)
    return bytes(out)


def build_qrcode_login_body(*, tlv: Dict[int, bytes], t106: bytes, t16a: bytes, t318: bytes) -> bytes:
    """扫码成功后走 0x810 `wtlogin.login`，subCmd 区先写 `u16 9 u16 24`。

    TLV 顺序（官方）：18,1,106,116,100,107,142,144,145,147,16A(t16a),154,141,8,511,187,188,194,191,202,177,516,521,318(t318)
    """
    out = bytearray()
    out += struct.pack(">HH", 9, 24)
    for tag in (0x18, 0x1):
        out += tlv[tag]
    out += struct.pack(">HH", 0x106, len(t106)) + t106
    for tag in (0x116, 0x100, 0x107, 0x142, 0x144, 0x145, 0x147):
        out += tlv[tag]
    out += struct.pack(">HH", 0x16A, len(t16a)) + t16a
    for tag in (0x154, 0x141, 0x8, 0x511, 0x187, 0x188, 0x194, 0x191, 0x202, 0x177, 0x516, 0x521):
        out += tlv[tag]
    out += struct.pack(">HH", 0x318, len(t318)) + t318
    return bytes(out)


def build_exchange_emp_body(*, sub_cmd: int, tlv: Dict[int, bytes],
                            t106: Optional[bytes] = None,
                            t16a: Optional[bytes] = None,
                            d2: Optional[bytes] = None,
                            order: Optional[Sequence[int]] = None) -> bytes:
    """wtlogin.exchange_emp 请求体。

    subCmd=15（A1 -> 全套票据）：u16 15 | u16 24 | TLV*(含 0x106 原样 tag)
    subCmd=11（A2/D2 静默续期）：u16 11 | u16 16 | TLV*(含 0x10a/0x143)
    """
    if sub_cmd == 15:
        seq_tlvs = order or (0x18, 0x1, 0x116, 0x100, 0x107, 0x144, 0x142, 0x145,
                             0x16A, 0x154, 0x141, 0x8, 0x511, 0x147, 0x177, 0x400,
                             0x187, 0x188, 0x194, 0x202, 0x516, 0x521, 0x525)
        out = bytearray(struct.pack(">HH", 15, 24))
        for tag in seq_tlvs:
            if tag == 0x18:
                out += tlv[0x18]
            elif tag == 0x1:
                out += tlv[0x1]
            elif tag == 0x106:
                raw = t106 or b""
                out += struct.pack(">HH", 0x106, len(raw)) + raw
            elif tag == 0x16A:
                raw = t16a or b""
                out += struct.pack(">HH", 0x16A, len(raw)) + raw
            else:
                out += tlv[tag]
        return bytes(out)

    if sub_cmd == 11:
        out = bytearray(struct.pack(">HH", 11, 16))
        for tag in (0x100, 0x10A, 0x116, 0x144):
            out += tlv[tag]
        out += struct.pack(">H", 0x143) + struct.pack(">H", len(d2 or b"")) + (d2 or b"")
        for tag in (0x142, 0x154, 0x18, 0x141, 0x8, 0x147, 0x177, 0x187, 0x188, 0x202, 0x511):
            out += tlv[tag]
        return bytes(out)

    raise ValueError(f"unsupported exchange_emp subCmd {sub_cmd}")


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def parse_0a_envelope(frame: bytes) -> Dict[str, object]:
    """解析 0x0A 外壳，返回 {magic, enc, d2, uin, cipher}。

    `_buildLoginPacket` 的逆运算::

        u32 0x0A | u8 enc | LP(d2) | u8 0 | LP(uin) | cipher

    LP = u32(len+4) 自含长度。**不要**用固定偏移（不同 uin 长度会错位）。
    """
    buf = frame
    if len(buf) >= 8 and struct.unpack(">I", buf[4:8])[0] in (0x0A, 0x0B):
        buf = buf[4:]
    if len(buf) < 6:
        raise ValueError("0x0A 帧过短")
    magic = struct.unpack(">I", buf[0:4])[0]
    if magic not in (0x0A, 0x0B):
        raise ValueError(f"非 0x0A/0x0B 帧（magic=0x{magic:x}）")
    enc = buf[4]
    off = 5
    d2_len = struct.unpack(">I", buf[off : off + 4])[0]
    d2 = buf[off + 4 : off + d2_len]
    off += d2_len
    off += 1                                   # 分隔 0x00
    uin_len = struct.unpack(">I", buf[off : off + 4])[0]
    uin = buf[off + 4 : off + uin_len].decode("ascii", "replace")
    off += uin_len
    cipher = buf[off:-1] if buf[-1:] == b"\x03" else buf[off:]
    return {"magic": magic, "enc": enc, "d2": d2, "uin": uin, "cipher": cipher}


def decrypt_0a_payload(frame: bytes, key: bytes) -> bytes:
    """0x0A 外壳 + TEA(key) -> 明文（登录类回包）。"""
    env = parse_0a_envelope(frame)
    return tea_decrypt(env["cipher"], key)  # type: ignore[arg-type]


class WtError(RuntimeError):
    pass


def parse_sso_response(plain: bytes) -> Tuple[int, int, str, bytes]:
    """服务端方向 SSO 体解析（委托 wire 实现，保持单一真源）。"""
    return wire.parse_sso_response_body(plain)


def parse_login_response(decrypted: bytes) -> Dict[str, object]:
    """0x810 回包（已 TEA 解密）：`2B ver | u8 type | 2B | TLV*`。

    type: 0 成功 / 2 滑块 / 160,162 设备锁 / 204 设备锁已通过
    """
    if len(decrypted) < 5:
        raise WtError("login response too short")
    rtype = decrypted[2]
    tlvs = wire.read_tlvs(decrypted[5:])
    return {"type": rtype, "tlvs": tlvs, "version": decrypted[:2].hex()}


def parse_t119(t119: bytes, tgtgt: bytes) -> Dict[str, object]:
    """t119 = TEA(tgtgt) 包裹的 TLV 集合，含 A2/D2/D2Key/SKey/PSKey 与用户信息。

    tag 速查：
      0x106  t106（换票凭据）      0x11a  用户信息(age/sex/nick)
      0x10a  A2(tgt)              0x10d  A2 的 key(tgt_key)
      0x10e  ST/微信侧 key        0x103  st_web_sig
      0x120  SKey                 0x143  D2
      0x305  D2Key                0x512  PSKey 列表
      0x16a  srm_token            0x133/0x134  sig_key / ticket_key
      0x322  device_token
    """
    inner = tea_decrypt(t119, tgtgt)
    tlvs = wire.read_tlvs(inner)
    out: Dict[str, object] = {"tlvs": tlvs, "t106": tlvs.get(0x106, b"")}
    if 0x11A in tlvs:
        info = tlvs[0x11A]
        # 2B | age(1) | sex(1) | 1B len + nick
        if len(info) >= 5:
            age = info[2]
            sex = {0: "unknown", 1: "male", 2: "female"}.get(info[3], "unknown")
            nick_len = info[4]
            nick = info[5 : 5 + nick_len].decode("utf-8", "replace")
            out.update({"age": age, "sex": sex, "nickname": nick})
    if 0x512 in tlvs:
        out["pskeys"] = parse_pskeys(tlvs[0x512])
    out["sig"] = {
        "a2": tlvs.get(0x10A, b""),
        "a2_key": tlvs.get(0x10D, b""),
        "st_key": tlvs.get(0x10E, b""),
        "st_web_sig": tlvs.get(0x103, b""),
        "skey": tlvs.get(0x120, b""),
        "d2": tlvs.get(0x143, b""),
        "d2key": tlvs.get(0x305, b""),
        "srm_token": tlvs.get(0x16A, b""),
        "sig_key": tlvs.get(0x133, b""),
        "ticket_key": tlvs.get(0x134, b""),
        "device_token": tlvs.get(0x322, b""),
    }
    return out


def parse_pskeys(buf: bytes) -> Dict[str, str]:
    """0x512：u16 count，然后 count × (u16 len domain, u16 len pskey, u16 len pt4token)。"""
    out: Dict[str, str] = {}
    if len(buf) < 2:
        return out
    n = struct.unpack(">H", buf[:2])[0]
    pos = 2
    for _ in range(n):
        row = []
        for _ in range(3):
            if pos + 2 > len(buf):
                return out
            ln = struct.unpack(">H", buf[pos : pos + 2])[0]
            pos += 2
            row.append(buf[pos : pos + ln])
            pos += ln
        out[row[0].decode("utf-8", "replace")] = row[1].decode("utf-8", "replace")
    return out


def parse_fetch_qrcode_response(payload: bytes) -> Dict[str, object]:
    """取码回包（已解密）：`55B | u16 len sig | sig | u16 | TLV*`，0x17 = PNG。"""
    if len(payload) < 55:
        raise WtError("fetch qrcode response too short")
    pos = 55
    sig_len = struct.unpack(">H", payload[pos : pos + 2])[0]
    pos += 2
    sig = payload[pos : pos + sig_len]
    pos += sig_len + 2
    tlvs = wire.read_tlvs(payload[pos:])
    return {"qrsig": sig, "png": tlvs.get(0x17, b""), "tlvs": tlvs}


def parse_query_qrcode_response(payload: bytes) -> Dict[str, object]:
    """扫码结果回包：48B | u16 len(+可选 0x02 段) | 4B | u8 retcode | 4B | u32 uin | 6B | TLV*。

    retcode: 0 已确认 0x30 未扫 0x31 已扫未确认 0x36 已取消
    成功时 TLV：0x18=t106  0x19=t16a(noPicSig)  0x65=t318  0x1E=tgtgt
    """
    if len(payload) < 60:
        raise WtError("query qrcode response too short")
    pos = 48
    ln = struct.unpack(">H", payload[pos : pos + 2])[0]
    pos += 2
    if ln:
        ln -= 1
        if payload[pos] == 2:
            pos += 1 + 8
            ln -= 8
        if ln > 0:
            pos += ln
    pos += 4
    retcode = payload[pos]
    pos += 1 + 4
    uin = struct.unpack(">I", payload[pos : pos + 4])[0]
    pos += 4 + 6
    tlvs = wire.read_tlvs(payload[pos:])
    return {
        "ret_code": retcode,
        "uin": uin,
        "t106": tlvs.get(0x18, b""),
        "no_pic_sig": tlvs.get(0x19, b""),
        "t318": tlvs.get(0x65, b""),
        "tgtgt": tlvs.get(0x1E, b""),
        "tlvs": tlvs,
    }


# ---------------------------------------------------------------------------
# 设备指纹
# ---------------------------------------------------------------------------

def make_guid(imei: str, mac: str) -> bytes:
    """官方：md5(imei + mac)。sample 用 md5(f"watch-device-{sub_appid}")，全设备同值。"""
    return hashlib.md5((imei + mac).encode()).digest()


def make_tgtgt_key(password_md5: bytes, uin: int) -> bytes:
    """t106 的 TEA 密钥：md5(password_md5 + 4×00 + u32(uin))。"""
    return hashlib.md5(password_md5 + b"\x00" * 4 + struct.pack(">I", uin)).digest()


__all__ = [
    "ClientProfile", "PROFILE_WATCH_205", "PROFILE_WATCH_208",
    "SERVICE_TRANS_EMP", "SERVICE_LOGIN", "SERVICE_EXCHANGE_EMP",
    "CMD_FETCH_QRCODE", "CMD_QUERY_QRCODE", "QR_FETCH_HEAD", "QR_QUERY_HEAD", "SSO_CONST",
    "build_oicq_body", "build_login_packet", "pack_0810_frame",
    "build_trans_emp_packet", "build_fetch_qrcode_body", "build_query_qrcode_body",
    "build_qrcode_login_body", "build_exchange_emp_body",
    "parse_sso_response", "parse_login_response", "parse_t119", "parse_pskeys",
    "parse_0a_envelope", "decrypt_0a_payload",
    "parse_fetch_qrcode_response", "parse_query_qrcode_response",
    "make_guid", "make_tgtgt_key", "WtError",
]
