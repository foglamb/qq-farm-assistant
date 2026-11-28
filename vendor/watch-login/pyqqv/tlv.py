"""wtlogin TLV 包（逐字节对应 oicq `lib/wtlogin/tlv.js`）。

所有 tag 的布局都从 oicq 源码还原，字段宽度/顺序不能改：
`0x16` 里的 `0x200300EF`、`0x100` 的 `emp?2:subid`、`0x144` 的 tgtgt 加密，
任何一位错了服务端直接返回 ret != 0。
"""
from __future__ import annotations

import hashlib
import os
import struct
import time
from typing import Dict, Optional

TLV_TAGS = (
    0x01, 0x08, 0x16, 0x18, 0x1B, 0x1D, 0x1F, 0x33, 0x35,
    0x100, 0x104, 0x106, 0x107, 0x108, 0x109, 0x10A, 0x116, 0x124, 0x128,
    0x141, 0x142, 0x143, 0x144, 0x145, 0x147, 0x154, 0x16A, 0x16E, 0x174,
    0x177, 0x17A, 0x17C, 0x187, 0x188, 0x191, 0x193, 0x194, 0x197, 0x198,
    0x202, 0x400, 0x401, 0x511, 0x516, 0x521, 0x525, 0x52D,
)

# 手表包里 0x16 的固定 app 签名（qqlite）
QQLITE_SIGN = bytes.fromhex("a6b745bf24a2c277527716f6f36eb68d")
QQLITE_PKG = "com.tencent.qqlite"
QQLITE_VER = "4.0.2"
SUBCONST = 537067759          # 0x200300EF，0x16 与 sso 共用

# 0x511 默认 PSKey 域名表（官方 14 条）
PSKEY_DOMAINS = (
    "tenpay.com", "openmobile.qq.com", "docs.qq.com", "connect.qq.com",
    "qzone.qq.com", "vip.qq.com", "qun.qq.com", "game.qq.com",
    "qqweb.qq.com", "office.qq.com", "ti.qq.com", "mail.qq.com",
    "gamecenter.qq.com", "mma.qq.com",
)


def _w16(v: int) -> bytes:
    return struct.pack(">H", v)


def _w32(v: int) -> bytes:
    return struct.pack(">I", v & 0xFFFFFFFF)


def _w64(v: int) -> bytes:
    return struct.pack(">Q", v)


def tlv_s(tag: int, payload: bytes) -> bytes:
    """u16 tag | u16 len | payload。"""
    return _w16(tag) + _w16(len(payload)) + payload


def lp16(v: bytes | str) -> bytes:
    """u16 len | data —— oicq Writer.writeTlv。"""
    raw = v.encode() if isinstance(v, str) else v
    return _w16(len(raw)) + raw


class TlvPacker:
    """按 tag 生成 TLV 字节。所有方法返回**已带 tag+len 的完整 TLV**。"""

    def __init__(self, *, uin: int, subid: int, appid: int = 16, sigmap: int = 34869472,
                 bitmap: int = 184024956, apk_ver: str = QQLITE_VER,
                 ver: str = "8.4.1", apk_id: str = "com.tencent.mobileqq",
                 apk_name: str = "A8.4.1.2703aac4", buildtime: int = 1591690260,
                 sdkver: str = "6.0.0.2428", sig: Optional[Dict[str, bytes]] = None,
                 device: Optional[Dict[str, object]] = None,
                 seq_id: int = 0, t104: bytes = b"", t174: bytes = b"") -> None:
        self.uin = uin
        self.subid = subid
        self.appid = appid
        self.sigmap = sigmap
        self.bitmap = bitmap
        self.apk_ver = apk_ver       # 0x16 里的 4.0.2（qqlite 内部版本）
        self.ver = ver               # 0x147 里的 8.4.1（对外 APK 版本）
        self.apk_id = apk_id         # 0x142 里的包名
        self.apk_name = apk_name
        self.buildtime = buildtime
        self.sdkver = sdkver
        self.sig = sig or {}
        self.seq_id = seq_id
        self.t104 = t104
        self.t174 = t174
        d = device or {}
        self.device = {
            "imei": d.get("imei", "860000000000001"),
            "mac": d.get("mac_address") or d.get("mac", "00:11:22:33:44:55"),
            "wifi_bssid": d.get("wifi_bssid") or d.get("mac_address") or "00:11:22:33:44:55",
            "wifi_ssid": d.get("wifi_ssid") or f"TP-LINK-{uin:x}",
            "android_id": d.get("android_id", "0123456789abcdef"),
            "model": d.get("model", "OPPO Watch 3"),
            "brand": d.get("brand", "OPPO"),
            "guid": d.get("guid") or hashlib.md5(
                (str(d.get("imei", "860000000000001")) + str(d.get("mac_address", "00:11:22:33:44:55"))).encode()
            ).digest(),
            "imsi": d.get("imsi", b""),
            "sim": d.get("sim", "T-Mobile"),
            "apn": d.get("apn", "wifi"),
            "os_type": d.get("os_type", "android"),
            "release": d.get("release", "11"),
            "sdk": d.get("sdk", 30),
            "bootloader": d.get("bootloader", "U-boot"),
            "proc_version": d.get("proc_version", "Linux version 4.19.71"),
            "codename": d.get("codename", "REL"),
            "incremental": d.get("incremental", 0),
            "boot_id": d.get("boot_id", "a1b2c3d4-0000-4000-8000-000000000000"),
            # 设备文件里固化的 fingerprint 优先（oicq 生成后不再重算）
            "fingerprint": d.get("fingerprint"),
            "product": d.get("product", "OPPO Watch 3"),
            "device": d.get("device", "OPPO Watch 3"),
            "board": d.get("board", "OPPO Watch 3"),
        }
        if not self.device["imsi"]:
            self.device["imsi"] = os.urandom(16)

    # -- 便捷 --
    @property
    def guid(self) -> bytes:
        return bytes(self.device["guid"])  # type: ignore[arg-type]

    @property
    def ksid(self) -> bytes:
        return f"|{self.device['imei']}|{self.apk_name}".encode()

    def _sig(self, name: str) -> bytes:
        v = self.sig.get(name)
        return v if isinstance(v, bytes) else b""

    # -- 各 tag --
    def build(self, tag: int, *args, **kw) -> bytes:
        fn = getattr(self, f"_t{tag:04x}", None)
        if fn is None:
            raise KeyError(f"TLV 0x{tag:04x} 未实现")
        return tlv_s(tag, fn(*args, **kw))

    def _t0001(self) -> bytes:
        # u16 ipver | 4B 随机 | u32 uin | u32 ts | 4B ip | u16 0
        return _w16(1) + os.urandom(4) + _w32(self.uin) + _w32(int(time.time())) + b"\x00" * 4 + _w16(0)

    def _t0008(self) -> bytes:
        return _w16(0) + _w32(2052) + _w16(0)

    def _t0016(self) -> bytes:
        # 客户端能力位：7 / 16 / SUBCONST / guid / 包名 / 版本 / 签名
        return (
            _w32(7) + _w32(16) + _w32(SUBCONST)
            + self.guid
            + lp16(QQLITE_PKG) + lp16(QQLITE_VER) + lp16(QQLITE_SIGN)
        )

    def _t0018(self) -> bytes:
        # ping ver | 1536 | appid | app_client_ver(0) | uin | 0 | 0
        return _w16(1) + _w32(1536) + _w32(self.appid) + _w32(0) + _w32(self.uin) + _w16(0) + _w16(0)

    def _t001b(self) -> bytes:
        return _w32(0) + _w32(0) + _w32(3) + _w32(4) + _w32(72) + _w32(2) + _w32(2) + _w16(0)

    def _t001d(self) -> bytes:
        return b"\x01" + _w32(184024956) + _w32(0) + b"\x00" + _w32(0)

    def _t001f(self) -> bytes:
        # 注意：0x1f 里的 sim 是**硬编码** "China Mobile GSM"，
        # 与 0x124/0x141 用的 device.sim（"T-Mobile"）不是同一来源。
        return (
            b"\x00" + lp16("android") + lp16("7.1.2")
            + _w16(2) + lp16("China Mobile GSM") + lp16(b"") + lp16("wifi")
        )

    def _t0033(self) -> bytes:
        return self.guid

    def _t0035(self) -> bytes:
        return _w32(8)

    def _t0100(self, emp: int = 0) -> bytes:
        # db buf ver | sso ver(7) | appid | emp?2:subid | app_cli_ver(0) | sigmap
        return _w16(1) + _w32(7) + _w32(self.appid) + _w32(2 if emp else self.subid) + _w32(0) + _w32(self.sigmap)

    def _t0104(self) -> bytes:
        return self.t104

    def _t0106(self, password_md5: bytes = b"", tgtgt: bytes = b"") -> bytes:
        """t106：换票核心。password_md5 为空时只能走扫码换票（A1 路径）。"""
        body = (
            _w16(4) + os.urandom(4) + _w32(7) + _w32(self.appid) + _w32(0)
            + _w64(self.uin) + _w32(int(time.time())) + b"\x00" * 4
            + b"\x01" + password_md5 + tgtgt
            + _w32(0) + b"\x01" + self.guid + _w32(self.subid)
            + _w32(1) + lp16(str(self.uin)) + _w16(0)
        )
        key = hashlib.md5(password_md5 + b"\x00" * 4 + _w32(self.uin)).digest()
        from .wire import tea_encrypt
        return tea_encrypt(body, key)

    def _t0107(self) -> bytes:
        return _w16(0) + b"\x00" + _w16(0) + b"\x01"

    def _t0108(self) -> bytes:
        return self.ksid

    def _t0109(self) -> bytes:
        return hashlib.md5(str(self.device["imei"]).encode()).digest()

    def _t010a(self) -> bytes:
        return self._sig("tgt")

    def _t0116(self) -> bytes:
        return b"\x00" + _w32(self.bitmap) + _w32(0x10400) + b"\x01" + _w32(1600000226)

    def _t0124(self) -> bytes:
        return (
            lp16(str(self.device["os_type"])[:16]) + lp16(str(self.device["release"])[:16])
            + _w16(2) + lp16(str(self.device["sim"])[:16]) + _w16(0) + lp16(str(self.device["apn"])[:16])
        )

    def _t0128(self) -> bytes:
        # u16 guid_new | u8 guid_available | u8 guid_changed | u32 guid_flag
        # | LP(model[32]) | LP(guid[16]) | LP(brand[16])
        return (
            _w16(0) + b"\x00\x01\x00" + _w32(16777216)
            + lp16(str(self.device["model"])[:32]) + lp16(self.guid[:16])
            + lp16(str(self.device["brand"])[:16])
        )

    def _t0141(self) -> bytes:
        return _w16(1) + lp16(str(self.device["sim"])) + _w16(2) + lp16(str(self.device["apn"]))

    def _t0142(self) -> bytes:
        # 手表 platform 复用 phone 的 apk 元信息（apk[3] = {...apk[1]} 只改 subid），
        # 因此这里仍是 com.tencent.mobileqq，不是 qqlite。
        return _w16(0) + lp16(self.apk_id[:32])

    def _t0143(self, d2: bytes = b"") -> bytes:
        return d2

    def _t0144(self, tgtgt: bytes = b"") -> bytes:
        """5 个内嵌 TLV 再用 tgtgt 加密 —— 设备指纹的主体。"""
        from .wire import tea_encrypt
        inner = (
            _w16(5)
            + self.build(0x109) + self.build(0x52D) + self.build(0x124)
            + self.build(0x128) + self.build(0x16E)
        )
        return tea_encrypt(inner, tgtgt or self._sig("tgtgt") or b"\x00" * 16)

    def _t0145(self) -> bytes:
        return self.guid

    def _t0147(self) -> bytes:
        # apk.ver 是 "8.4.1"（前 5 字节截断），不是 t106 里的 4.0.2
        return _w32(self.appid) + lp16(self.ver[:5]) + lp16(QQLITE_SIGN)

    def _t0154(self) -> bytes:
        return _w32(self.seq_id + 1)

    def _t016a(self) -> bytes:
        return self._sig("srm_token")

    def _t016e(self) -> bytes:
        return str(self.device["model"]).encode()

    def _t0174(self) -> bytes:
        return self.t174

    def _t0177(self) -> bytes:
        return b"\x01" + _w32(self.buildtime) + lp16(self.sdkver)

    def _t017a(self) -> bytes:
        return _w32(9)

    def _t017c(self, code: str = "") -> bytes:
        return lp16(code)

    def _t0187(self) -> bytes:
        # md5(mac_address) —— 注意不是 md5(wifi_bssid)
        return hashlib.md5(str(self.device["mac"]).encode()).digest()

    def _t0188(self) -> bytes:
        return hashlib.md5(str(self.device["android_id"]).encode()).digest()

    def _t0191(self) -> bytes:
        return b"\x82"

    def _t0193(self, ticket: bytes = b"") -> bytes:
        return ticket

    def _t0194(self) -> bytes:
        return bytes(self.device["imsi"])  # type: ignore[arg-type]

    def _t0197(self) -> bytes:
        return lp16(b"\x00")

    def _t0198(self) -> bytes:
        return lp16(b"\x00")

    def _t0202(self) -> bytes:
        # wifi_bssid / wifi_ssid 是设备文件里的**独立字段**，不是 mac_address 的别名
        return lp16(str(self.device["wifi_bssid"])[:16]) + lp16(str(self.device["wifi_ssid"])[:32])

    def _t0400(self) -> bytes:
        return (
            _w16(1) + _w64(self.uin) + self.guid + os.urandom(16)
            + _w32(1) + _w32(16) + _w32(int(time.time())) + b""
        )

    def _t0401(self) -> bytes:
        return os.urandom(16)

    def _t0511(self, domains=None) -> bytes:
        ds = tuple(domains or PSKEY_DOMAINS)
        out = bytearray(_w16(len(ds)))
        for dom in ds:
            out += b"\x01" + lp16(dom)
        return bytes(out)

    def _t0516(self) -> bytes:
        return _w32(0)

    def _t0521(self) -> bytes:
        return _w32(0) + _w16(0)

    def _t0525(self) -> bytes:
        return _w16(1) + _w16(0x536) + lp16(b"\x01\x00")

    def _t052d(self) -> bytes:
        """设备编译指纹（protobuf）。

        官方 `device.js` 里 5 号字段是组合出来的 fingerprint：
            `${brand}/${product}/${device}:10/${android_id}/${incremental}:user/release-keys`
        9 号字段与 4 号同为 incremental。
        """
        from .wire import PbWriter
        d = self.device
        # fingerprint 在设备文件生成时就固定了（oicq device.js 里拼好写进 JSON），
        # 后续改 brand/model 不会重算，所以这里优先用传入值。
        fingerprint = str(d.get("fingerprint") or (
            f"{d['brand']}/{d['product']}/{d['device']}:10/{d['android_id']}"
            f"/{d['incremental']}:user/release-keys"
        ))
        w = (
            PbWriter()
            .string(1, str(d["bootloader"]))
            .string(2, str(d["proc_version"]))
            .string(3, str(d["codename"]))
            .string(4, str(d["incremental"]))
            .string(5, fingerprint)
            .string(6, str(d["boot_id"]))
            .string(7, str(d["android_id"]))
            .bytes(8, b"", always=True)      # 官方会写出空字段（tag+len0）
            .string(9, str(d["incremental"]))
        )
        return w.finish()


__all__ = ["TlvPacker", "tlv_s", "lp16", "TLV_TAGS", "PSKEY_DOMAINS",
           "QQLITE_SIGN", "QQLITE_PKG", "QQLITE_VER", "SUBCONST"]
