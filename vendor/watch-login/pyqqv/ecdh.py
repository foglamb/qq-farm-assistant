"""prime256v1 (secp256r1 / P-256) ECDH —— 纯标准库实现。

QQ 的 `wtlogin.trans_emp` / `wtlogin.login` 用 ECDH 做密钥协商：

    客户端生成一对 P-256 密钥
    服务端公钥固定为 OICQ_SERVER_PUBLIC_KEY（见下）
    share_key = md5( ECDH_shared_secret[:16] )      <- 16 字节，直接当 qqtea 密钥

这条链路里**没有** libfekit 签名，纯椭圆曲线运算，因此可以离线复现。
"""

from __future__ import annotations

import hashlib
import os
from typing import Tuple

# ---------------------------------------------------------------------------
# P-256 曲线参数（FIPS 186-4 / SEC 2）
# ---------------------------------------------------------------------------

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFC
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5

# oicq/lib/wtlogin/ecdh.js 里硬编码的服务端公钥（未压缩点，04 开头）
OICQ_SERVER_PUBLIC_KEY = bytes.fromhex(
    "04EBCA94D733E399B2DB96EACDD3F69A8BB0F74224E2B44E3357812211D2E62EFB"
    "C91BB553098E25E33A799ADC7F76FEB208DA7C6522CDB0719A305180CC54A82E"
)

Point = Tuple[int, int] | None       # None = 无穷远点


# ---------------------------------------------------------------------------
# 曲线运算（Jacobian 坐标，避免每次求逆）
# ---------------------------------------------------------------------------

def _inv(a: int, m: int = P) -> int:
    return pow(a, m - 2, m)


def _double(pt: Point) -> Point:
    if pt is None:
        return None
    x, y = pt
    if y == 0:
        return None
    lam = (3 * x * x + A) * _inv(2 * y) % P
    x3 = (lam * lam - 2 * x) % P
    return x3, (lam * (x - x3) - y) % P


def _add(p1: Point, p2: Point) -> Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        return _double(p1)
    lam = (y2 - y1) * _inv(x2 - x1) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def _mul(k: int, pt: Point) -> Point:
    if k % N == 0 or pt is None:
        return None
    if k < 0:
        k = -k
        pt = (pt[0], (-pt[1]) % P)
    out: Point = None
    addend: Point = pt
    while k:
        if k & 1:
            out = _add(out, addend)
        addend = _double(addend)
        k >>= 1
    return out


def _compress_size(v: int) -> bytes:
    return v.to_bytes(32, "big")


def encode_point(pt: Point) -> bytes:
    """未压缩点编码：04 || X(32) || Y(32)。"""
    if pt is None:
        raise ValueError("cannot encode point at infinity")
    return b"\x04" + _compress_size(pt[0]) + _compress_size(pt[1])


def decode_point(data: bytes) -> Point:
    if len(data) != 65 or data[0] != 0x04:
        raise ValueError("only uncompressed 65-byte points are supported")
    return int.from_bytes(data[1:33], "big"), int.from_bytes(data[33:65], "big")


def on_curve(pt: Point) -> bool:
    if pt is None:
        return False
    x, y = pt
    return (y * y - (x * x * x + A * x + B)) % P == 0


# ---------------------------------------------------------------------------
# ECDH
# ---------------------------------------------------------------------------

class Ecdh:
    """一次性的 P-256 密钥对 + 与固定服务端公钥的共享密钥。"""

    def __init__(self, private_key: int | None = None,
                 server_public: bytes = OICQ_SERVER_PUBLIC_KEY) -> None:
        self.private_key = private_key or (int.from_bytes(os.urandom(32), "big") % (N - 1) + 1)
        self.public_point = _mul(self.private_key, (GX, GY))
        self.public_key = encode_point(self.public_point)
        self.server_point = decode_point(server_public)
        if not on_curve(self.server_point):
            raise ValueError("server public key is not on P-256")
        shared = _mul(self.private_key, self.server_point)
        if shared is None:
            raise ValueError("degenerate shared secret")
        self.shared_secret = _compress_size(shared[0]) + _compress_size(shared[1])
        self.share_key = hashlib.md5(self.shared_secret[:16]).digest()

    # 便于测试固定向量
    @classmethod
    def from_private(cls, private_key: int, server_public: bytes = OICQ_SERVER_PUBLIC_KEY) -> "Ecdh":
        return cls(private_key=private_key, server_public=server_public)


def share_key_from_secret_prefixed(secret: bytes) -> bytes:
    """服务端侧：给定 ECDH 原始共享值，算 md5(secret[:16])。"""
    return hashlib.md5(secret[:16]).digest()


__all__ = [
    "P", "A", "B", "N", "GX", "GY",
    "OICQ_SERVER_PUBLIC_KEY", "Ecdh",
    "encode_point", "decode_point", "on_curve",
    "share_key_from_secret_prefixed",
]
