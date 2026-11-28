"""QQ 手表 / NT 协议线格式基线（纯标准库）。

包含四层，全部与 oicq 1.21.6 官方实现逐字节对齐：
  1. qqtea   —— QQ TEA（CBC 变体 + 7 字节零尾巴 + 首字节长度掩码）
  2. jce     —— Tars/JCE 编码器（StatSvc.register 等 JCE 服务）
  3. pb      —— protobuf wire 编解码（MessageSvc.* / OnlinePush.*）
  4. sso     —— 0x0A / 0x0B MSF 信封 + 0x810 / 0x812 wtlogin 帧

设计原则：只依赖 hashlib/struct/os，可直接被 watch_client 这类样本 import。
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

# ============================================================================
# 1. qqtea
# ============================================================================

TEA_DELTA = 0x9E3779B9
_MASK32 = 0xFFFFFFFF
TEA_ZERO7 = b"\x00" * 7


def _u32(v: int) -> int:
    return v & _MASK32


class TeaError(ValueError):
    pass


def _tea_rounds(v: Sequence[int], k: Sequence[int], encrypt: bool) -> Tuple[int, int]:
    x, y = v
    if encrypt:
        s = 0
        for _ in range(16):
            s = _u32(s + TEA_DELTA)
            x = _u32(x + (((_u32(y << 4) + k[0]) ^ _u32(y + s)) ^ (_u32(y >> 5) + k[1])))
            y = _u32(y + (((_u32(x << 4) + k[2]) ^ _u32(x + s)) ^ (_u32(x >> 5) + k[3])))
        return x, y
    s = _u32(TEA_DELTA * 16)
    for _ in range(16):
        y = _u32(y - (((_u32(x << 4) + k[2]) ^ _u32(x + s)) ^ (_u32(x >> 5) + k[3])))
        x = _u32(x - (((_u32(y << 4) + k[0]) ^ _u32(y + s)) ^ (_u32(y >> 5) + k[1])))
        s = _u32(s - TEA_DELTA)
    return x, y


def _tea_keys(key: bytes) -> List[int]:
    if len(key) != 16:
        raise TeaError(f"qqtea key must be 16 bytes, got {len(key)}")
    return list(struct.unpack(">4I", key))


def tea_encrypt(data: bytes, key: bytes) -> bytes:
    """QQ TEA 加密。明文前 1 字节填充长度，尾部 7 字节 0。"""
    k = _tea_keys(key)
    n = (6 - len(data)) & 0xFFFFFFFF
    n = (n % 8) + 2
    plain = bytes([(n - 2) | 0xF8]) + os.urandom(n) + bytes(data) + TEA_ZERO7
    out = bytearray(plain)
    r1 = r2 = t1 = t2 = 0
    for i in range(0, len(out), 8):
        a1, a2 = struct.unpack(">2I", out[i : i + 8])
        b1, b2 = a1 ^ r1, a2 ^ r2
        x, y = _tea_rounds((b1, b2), k, True)
        r1, r2 = x ^ t1, y ^ t2
        t1, t2 = b1, b2
        struct.pack_into(">2I", out, i, r1, r2)
    return bytes(out)


def tea_decrypt(cipher: bytes, key: bytes) -> bytes:
    """QQ TEA 解密；长度非 8 倍数或尾巴不合规时抛 TeaError。"""
    if len(cipher) % 8:
        raise TeaError("qqtea cipher length must be a multiple of 8")
    k = _tea_keys(key)
    buf = bytearray(cipher)
    x = y = t1 = t2 = 0
    for i in range(0, len(buf), 8):
        a1, a2 = struct.unpack(">2I", buf[i : i + 8])
        b1, b2 = a1 ^ x, a2 ^ y
        x, y = _tea_rounds((b1, b2), k, False)
        struct.pack_into(">2I", buf, i, x ^ t1, y ^ t2)
        t1, t2 = a1, a2
    if bytes(buf[-7:]) != TEA_ZERO7:
        raise TeaError("qqtea padding check failed (wrong key or truncated body)")
    return bytes(buf[(buf[0] & 0x07) + 3 : len(buf) - 7])


# ============================================================================
# 2. JCE / Tars
# ============================================================================

class JceType:
    BYTE = 0
    SHORT = 1
    INT = 2
    LONG = 3
    STRING1 = 6
    STRING4 = 7
    MAP = 8
    LIST = 9
    STRUCT_BEGIN = 10
    STRUCT_END = 11
    ZERO = 12
    SIMPLE_LIST = 13


class JceWriter:
    """最小 JCE 编码器。tag>=15 走 0xF0 + tag 扩展。"""

    def __init__(self) -> None:
        self.buf = bytearray()

    def _head(self, tag: int, jtype: int) -> None:
        if tag < 15:
            self.buf.append((tag << 4) | (jtype & 0x0F))
        else:
            self.buf.append(0xF0 | (jtype & 0x0F))
            self.buf.append(tag & 0xFF)

    # -- scalars --
    def byte(self, tag: int, val: int) -> "JceWriter":
        if val == 0:
            self._head(tag, JceType.ZERO)
        else:
            self._head(tag, JceType.BYTE)
            self.buf += struct.pack(">b", val)
        return self

    def short(self, tag: int, val: int) -> "JceWriter":
        if -128 <= val <= 127:
            return self.byte(tag, val)
        self._head(tag, JceType.SHORT)
        self.buf += struct.pack(">h", val)
        return self

    def int32(self, tag: int, val: int) -> "JceWriter":
        if -32768 <= val <= 32767:
            return self.short(tag, val)
        self._head(tag, JceType.INT)
        self.buf += struct.pack(">i", val)
        return self

    def int64(self, tag: int, val: int) -> "JceWriter":
        if -2147483648 <= val <= 2147483647:
            return self.int32(tag, val)
        self._head(tag, JceType.LONG)
        self.buf += struct.pack(">q", val)
        return self

    def string(self, tag: int, s: str | bytes) -> "JceWriter":
        raw = s.encode() if isinstance(s, str) else s
        if len(raw) <= 255:
            self._head(tag, JceType.STRING1)
            self.buf.append(len(raw))
        else:
            self._head(tag, JceType.STRING4)
            self.buf += struct.pack(">I", len(raw))
        self.buf += raw
        return self

    def bytes(self, tag: int, data: bytes) -> "JceWriter":
        self._head(tag, JceType.SIMPLE_LIST)
        self._head(0, JceType.BYTE)
        self.int32(0, len(data))
        self.buf += data
        return self

    def struct(self, tag: int, inner: bytes) -> "JceWriter":
        self._head(tag, JceType.STRUCT_BEGIN)
        self.buf += inner
        self._head(0, JceType.STRUCT_END)
        return self

    def map_str_bytes(self, tag: int, mapping: Dict[str, bytes]) -> "JceWriter":
        self._head(tag, JceType.MAP)
        self.int32(0, len(mapping))
        for k, v in mapping.items():
            self.string(0, k)
            self.bytes(1, v)
        return self

    def finish(self) -> bytes:
        return bytes(self.buf)


class JceReader:
    """最小 JCE 解码器；返回 {tag: value}，struct 递归成 dict。"""

    _END = object()

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise ValueError("jce truncated")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def _head(self) -> Tuple[int, int]:
        b = self._take(1)[0]
        jtype = b & 0x0F
        tag = (b & 0xF0) >> 4
        if tag == 0xF:
            tag = self._take(1)[0]
        return tag, jtype

    def _value(self, jtype: int):
        if jtype == JceType.ZERO:
            return 0
        if jtype == JceType.BYTE:
            return struct.unpack(">b", self._take(1))[0]
        if jtype == JceType.SHORT:
            return struct.unpack(">h", self._take(2))[0]
        if jtype == JceType.INT:
            return struct.unpack(">i", self._take(4))[0]
        if jtype == JceType.LONG:
            return struct.unpack(">q", self._take(8))[0]
        if jtype == JceType.STRING1:
            return self._take(self._take(1)[0]).decode("utf-8", "replace")
        if jtype == JceType.STRING4:
            return self._take(struct.unpack(">I", self._take(4))[0]).decode("utf-8", "replace")
        if jtype == JceType.SIMPLE_LIST:
            self._head()
            n = self._value(*self._head()[::-1][::-1]) if False else self._value(self._head()[1])
            return self._take(n)
        if jtype == JceType.MAP:
            n = self._value(self._head()[1])
            out: Dict[object, object] = {}
            for _ in range(n):
                k = self._value(self._head()[1])
                out[k] = self._value(self._head()[1])
            return out
        if jtype == JceType.LIST:
            n = self._value(self._head()[1])
            return [self._value(self._head()[1]) for _ in range(n)]
        if jtype == JceType.STRUCT_BEGIN:
            return self._struct()
        if jtype == JceType.STRUCT_END:
            return self._END
        raise ValueError(f"unsupported jce type {jtype}")

    def _struct(self) -> Dict[int, object]:
        out: Dict[int, object] = {}
        while self.pos < len(self.data):
            tag, jtype = self._head()
            val = self._value(jtype)
            if val is self._END:
                return out
            out[tag] = val
        return out

    def decode(self) -> Dict[int, object]:
        return self._struct()


# ============================================================================
# 3. protobuf wire
# ============================================================================

class PbWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    @staticmethod
    def varint(val: int) -> bytes:
        if val < 0:
            val &= (1 << 64) - 1
        out = bytearray()
        while True:
            b = val & 0x7F
            val >>= 7
            if val:
                out.append(b | 0x80)
            else:
                out.append(b)
                return bytes(out)

    def _tag(self, field_no: int, wire: int) -> bytes:
        return self.varint((field_no << 3) | wire)

    def uint(self, field_no: int, val: int, always: bool = False) -> "PbWriter":
        if val or always:
            self.buf += self._tag(field_no, 0) + self.varint(val)
        return self

    def bytes(self, field_no: int, data: bytes, always: bool = False) -> "PbWriter":
        if data or always:
            self.buf += self._tag(field_no, 2) + self.varint(len(data)) + data
        return self

    def string(self, field_no: int, s: str) -> "PbWriter":
        return self.bytes(field_no, s.encode())

    def message(self, field_no: int, sub: "PbWriter") -> "PbWriter":
        return self.bytes(field_no, sub.finish())

    def finish(self) -> bytes:
        return bytes(self.buf)


def pb_decode(buf: bytes, max_fields: int = 65536) -> List[Tuple[int, int, object]]:
    out: List[Tuple[int, int, object]] = []
    pos, n = 0, len(buf)

    def varint() -> int:
        nonlocal pos
        shift, val, cnt = 0, 0, 0
        while True:
            if pos >= n:
                raise ValueError("pb varint truncated")
            b = buf[pos]
            pos += 1
            val |= (b & 0x7F) << shift
            if not (b & 0x80):
                return val
            shift += 7
            cnt += 1
            if cnt >= 10:
                raise ValueError("pb varint too long")

    while pos < n:
        if len(out) >= max_fields:
            raise ValueError("pb too many fields")
        tag = varint()
        fno, wire = tag >> 3, tag & 7
        if fno == 0:
            raise ValueError("pb invalid field 0")
        if wire == 0:
            out.append((fno, wire, varint()))
        elif wire == 2:
            ln = varint()
            if pos + ln > n:
                raise ValueError("pb length out of range")
            out.append((fno, wire, buf[pos : pos + ln]))
            pos += ln
        elif wire == 5:
            out.append((fno, wire, buf[pos : pos + 4]))
            pos += 4
        elif wire == 1:
            out.append((fno, wire, buf[pos : pos + 8]))
            pos += 8
        else:
            raise ValueError(f"pb unsupported wire {wire}")
    return out


def pb_get(fields: List[Tuple[int, int, object]], fno: int, default=None):
    for f, _, v in fields:
        if f == fno:
            return v
    return default


def pb_get_all(fields: List[Tuple[int, int, object]], fno: int) -> List[object]:
    return [v for f, _, v in fields if f == fno]


# ============================================================================
# 4. SSO 信封（0x0A login / 0x0B uni）
# ============================================================================

SERVICE_NAME = "msfwifi.3g.qq.com"
SERVICE_PORT = 8080

ENC_NONE = 0x00
ENC_D2 = 0x01        # 0x0B 正常命令，D2Key 做 TEA 密钥
ENC_BUF16 = 0x02     # 0x0B wtlogin.exchange_emp / 0x0A 登录，全零密钥
ENC_EMP = 0x45       # 0x810 内的 EMP 分支
ENC_LOGIN = 0x87     # 0x810 内的常规登录分支


def pack_u32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def with_len(payload: bytes) -> bytes:
    """u32(len+4) + payload —— QQ 的 LengthPrefixed 写法。"""
    return pack_u32(len(payload) + 4) + payload


def pack_sso_frame(seq: int, command: str, payload: bytes, session_id: bytes,
                   uin: int | str, enc_type: int, d2: bytes = b"", d2key: bytes = b"") -> bytes:
    """构造 0x0A/0x0B 统一帧。

    SSO 结构（与 oicq client-ext._buildUniPacket 完全一致）::

        sso  = u32(cmd_len+20)
               u32(cmd_len+4) cmd
               u32(8) session_id
               u32(4) u32(len+4) payload   # 注意：这里的 4 是 payload 长度前缀自身
    """
    cmd = command.encode()
    head = bytearray()
    head += pack_u32(len(cmd) + 20)
    head += pack_u32(len(cmd) + 4) + cmd
    head += pack_u32(8) + session_id[:4].rjust(4, b"\x00")
    head += pack_u32(4) + pack_u32(len(payload) + 4) + payload
    sso = bytes(head)
    body = tea_encrypt(sso, d2key if enc_type == ENC_D2 else b"\x00" * 16)
    uin_b = str(uin).encode()
    # uin 长度字段是自含的：u32(uin_len+4) 本身占 4 字节，uin 紧随其后（偏移 18）
    total = len(body) + len(uin_b) + 18
    out = bytearray()
    out += pack_u32(total)
    out += pack_u32(0x0B if enc_type != ENC_LOGIN else 0x0A)
    out += bytes([enc_type])
    out += struct.pack(">i", seq)
    out += b"\x00"
    out += pack_u32(len(uin_b) + 4) + uin_b
    out += body
    return bytes(out)


def parse_sso_frame(buf: bytes) -> Tuple[int, int, bytes]:
    """解析 0x0A/0x0B 帧，返回 (seq, enc_type, cipher_body)。

    既接受带 u32 总长前缀的整帧（线上格式），也接受已剥掉前缀的帧体。
    归一化后布局：u32 0x0A|0x0B | u8 enc | i32 seq | u8 0 | u32(uin_len+4) uin | body
    """
    # 归一化：统一到「以 u32 命令字开头」的视图
    if len(buf) >= 8 and struct.unpack(">I", buf[4:8])[0] in (0x0A, 0x0B):
        buf = buf[4:]           # 剥掉 u32 总长前缀
    if len(buf) < 14:
        raise ValueError("sso frame too short")
    magic = struct.unpack(">I", buf[0:4])[0]
    if magic not in (0x0A, 0x0B):
        raise ValueError(f"unexpected sso magic 0x{magic:x}")
    enc = buf[4]
    seq = struct.unpack(">i", buf[5:9])[0]
    uin_len = struct.unpack(">I", buf[10:14])[0]
    if uin_len < 4:
        raise ValueError("bad uin length")
    return seq, enc, buf[14 + (uin_len - 4):]


def decrypt_sso_body(cipher: bytes, enc_type: int, d2key: bytes = b"") -> bytes:
    if enc_type == ENC_D2:
        if len(d2key) != 16:
            raise TeaError("ENC_D2 requires a 16-byte d2key")
        return tea_decrypt(cipher, d2key)
    if enc_type == ENC_BUF16:
        return tea_decrypt(cipher, b"\x00" * 16)
    return cipher


def parse_sso_response_body(plain: bytes) -> Tuple[int, int, str, bytes]:
    """服务端方向 SSO 体（0x0B 回包）。

    布局：i32 headlen | i32 seq | i32 retcode | u32(svc_len+4) svc
          | u32(sess_len+4) sess | i32 flag | payload

    flag：0=明文 1=deflate 8=裸
    """
    import zlib

    if len(plain) < 16:
        raise ValueError("sso response too short")
    headlen, seq, retcode = struct.unpack(">iIi", plain[:12])
    off = struct.unpack(">I", plain[12:16])[0] + 12
    svc_len = struct.unpack(">I", plain[off : off + 4])[0]
    service = plain[off + 4 : off + svc_len].decode("utf-8", "replace")
    off += svc_len
    sess_len = struct.unpack(">I", plain[off : off + 4])[0]
    off += sess_len
    flag = struct.unpack(">i", plain[off : off + 4])[0]
    if flag == 0:
        payload = plain[headlen + 4 :]
    elif flag == 1:
        payload = zlib.decompress(plain[headlen + 4 :])
    elif flag == 8:
        payload = plain[headlen:]
    else:
        raise ValueError(f"unknown compress flag {flag}")
    return seq, retcode, service, payload


def parse_sso_body(cipher_or_plain: bytes, enc_type: int, d2key: bytes = b"") -> Dict[str, object]:
    """解出 {seq, command, payload, session_id}。"""
    plain = cipher_or_plain
    if enc_type == ENC_D2:
        plain = tea_decrypt(cipher_or_plain, d2key)
    elif enc_type == ENC_BUF16:
        plain = tea_decrypt(cipher_or_plain, b"\x00" * 16)
    if len(plain) < 8:
        raise ValueError("sso body too short")
    cmd_len = struct.unpack(">I", plain[4:8])[0] - 4
    command = plain[8 : 8 + cmd_len].decode("utf-8", "replace")
    off = 8 + cmd_len
    sess_len = struct.unpack(">I", plain[off : off + 4])[0]
    session_id = plain[off + 4 : off + sess_len]
    off += sess_len
    off += 4  # 固定 4
    pay_len = struct.unpack(">I", plain[off : off + 4])[0] - 4
    payload = plain[off + 4 : off + 4 + pay_len]
    return {
        # 请求侧 SSO 体首字段是 u32(cmd_len+20) 自含长度，不含 seq；
        # seq 在 0x0A/0x0B 明文头（parse_sso_frame）里。
        "sso_len": struct.unpack(">I", plain[0:4])[0],
        "command": command,
        "session_id": session_id,
        "payload": payload,
    }


# ============================================================================
# 5. wtlogin 0x810 / 0x812 帧
# ============================================================================

def pack_0810_frame(uin: int, enc_type: int, body: bytes) -> bytes:
    """0x810 外层：2 字节类型 + 29 字节定长头 + 加密体 + 0x03。

    与 oicq `_buildOICQPacket` 逐字节等价（除随机字段外）。
    """
    head = bytearray()
    head += b"\x02"
    head += struct.pack(">H", 29 + len(body))
    head += struct.pack(">H", 8001)
    head += struct.pack(">H", 0x0810)
    head += struct.pack(">H", 1)
    head += pack_u32(uin)
    head += b"\x03"
    head += bytes([enc_type])
    head += b"\x00"
    head += pack_u32(2)
    head += pack_u32(0)
    head += pack_u32(0)
    return bytes(head) + body + b"\x03"


def build_oicq_inner_body(body: bytes, random_key: bytes, ecdh_public_key: bytes,
                         share_key: bytes) -> bytes:
    """0x810 常规分支的 body 包装（oicq `_buildOICQPacket(body, emp=false)`）::

        02 01 <random_key:16> 0131 0001 <u16 len+ecdh_pub> TEA(body, share_key)
    """
    head = bytearray()
    head += b"\x02\x01"
    head += random_key
    head += struct.pack(">HH", 0x0131, 0x0001)
    head += struct.pack(">H", len(ecdh_public_key)) + ecdh_public_key
    return bytes(head) + tea_encrypt(body, share_key)


def build_emp_inner_body(body: bytes, sig_key: bytes, ticket_key: bytes) -> bytes:
    """0x810 EMP 分支（enc=0x45）的 body 包装::

        <u16 len+sig_key> TEA(body, ticket_key)
    """
    return struct.pack(">H", len(sig_key)) + sig_key + tea_encrypt(body, ticket_key)


@dataclass
class Tlv:
    tag: int
    value: bytes

    def to_bytes(self) -> bytes:
        return struct.pack(">HH", self.tag, len(self.value)) + self.value


def read_tlvs(buf: bytes) -> Dict[int, bytes]:
    out: Dict[int, bytes] = {}
    pos = 0
    while pos + 4 <= len(buf):
        tag, ln = struct.unpack(">HH", buf[pos : pos + 4])
        pos += 4
        out[tag] = buf[pos : pos + ln]
        pos += ln
    return out


def parse_0810_response(body: bytes, t119_key: bytes) -> Dict[str, object]:
    """解析 wtlogin 响应：外层 TEA(t119_key) -> 定长头 -> 结果码 -> TLV。

    对应 oicq `_decodeLoginResponse`::

        payload = tea.decrypt(payload[16:-1], share_key)
        skip 2, type=u8, skip 2, readTlv
    """
    head = tea_decrypt(body[16:-1], t119_key)
    result = head[2]
    tlvs = read_tlvs(head[5:])
    out: Dict[str, object] = {"result": result, "tlvs": tlvs}
    if 0x119 in tlvs:
        out["t119"] = read_tlvs(tea_decrypt(tlvs[0x119], t119_key))
    return out


__all__ = [
    "TeaError", "tea_encrypt", "tea_decrypt",
    "JceWriter", "JceReader", "JceType",
    "PbWriter", "pb_decode", "pb_get", "pb_get_all",
    "SERVICE_NAME", "SERVICE_PORT",
    "ENC_NONE", "ENC_D2", "ENC_BUF16", "ENC_EMP", "ENC_LOGIN",
    "pack_sso_frame", "parse_sso_frame", "parse_sso_body", "decrypt_sso_body",
    "parse_sso_response_body",
    "pack_0810_frame", "build_oicq_inner_body", "build_emp_inner_body",
    "read_tlvs", "parse_0810_response", "with_len",
]
