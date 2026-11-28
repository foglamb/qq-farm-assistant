"""手表扫码登录端到端客户端 —— 取码 / 轮询 / 换票 / 上线 / 心跳，全在本地完成。

对照样本 `watch_client.py` 的四个方法：

    login_by_qr()        -> fetch_qrcode() + poll_once() 循环
    exchange_a1_tickets()-> exchange_emp(15)   （A1: t106 + noPicSig + tgtgt_key）
    renew_a2_tickets()   -> exchange_emp(11)   （A2 + D2 静默续期）
    register_online()    -> register() + Keepalive

与 oicq `wtlogin/login-qrcode.js` 的逐字节对应关系写在每个方法 docstring 里。
"""
from __future__ import annotations

import hashlib
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import message as M
from . import register as R
from . import tlv as T
from . import wire
from . import wtlogin as W
from .ecdh import OICQ_SERVER_PUBLIC_KEY as ECDH_SERVER_PUBLIC_KEY, Ecdh
from .transport import MsfClient, Response

CMD_FETCH = 0x31
CMD_QUERY = 0x12


class LoginError(RuntimeError):
    pass


@dataclass
class QrCode:
    qrsig: bytes
    png: bytes
    tlvs: Dict[int, bytes] = field(default_factory=dict)

    def save(self, path: str) -> str:
        with open(path, "wb") as fh:
            fh.write(self.png)
        return path


@dataclass
class PollResult:
    ret_code: int
    uin: int = 0
    t106: bytes = b""
    no_pic_sig: bytes = b""
    t318: bytes = b""
    tgtgt: bytes = b""
    tlvs: Dict[int, bytes] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.ret_code == 0 and bool(self.t106)

    @property
    def description(self) -> str:
        return {
            0x00: "已确认",
            0x01: "已扫码",
            0x02: "已取消",
            0x30: "未扫码",
            0x31: "已扫码待确认",
            0x32: "已取消",
            0x36: "已取消",
        }.get(self.ret_code, f"未知状态 0x{self.ret_code:02x}")


@dataclass
class Session:
    """登录后获得的全部票据。"""

    uin: int = 0
    guid: bytes = b""
    tgtgt: bytes = b""
    t106: bytes = b""
    no_pic_sig: bytes = b""
    t318: bytes = b""
    nickname: str = ""
    age: int = 0
    sex: str = "unknown"
    pskeys: Dict[str, str] = field(default_factory=dict)
    sig: Dict[str, bytes] = field(default_factory=dict)

    # 便于直接喂给 transport
    @property
    def d2(self) -> bytes:
        return self.sig.get("d2", b"")

    @property
    def d2key(self) -> bytes:
        return self.sig.get("d2key", b"")

    def to_json(self) -> Dict[str, object]:
        return {
            "uin": self.uin,
            "guid": self.guid.hex(),
            "tgtgt": self.tgtgt.hex(),
            "t106": self.t106.hex(),
            "no_pic_sig": self.no_pic_sig.hex(),
            "t318": self.t318.hex(),
            "nickname": self.nickname,
            "age": self.age,
            "sex": self.sex,
            "pskeys": self.pskeys,
            "sig": {k: v.hex() for k, v in self.sig.items()},
        }


def strip_login_frame(frame: bytes, key: bytes) -> bytes:
    """剥掉 0x0A/0x0B 外壳并用 key 解出明文（登录族回包）。

    结构由 `wtlogin.parse_0a_envelope` 决定：`u32 magic | u8 enc | LP(d2) | 0 | LP(uin) | TEA body`。
    **不能**用固定偏移：uin 位数变化会让 16 字节假设失效。
    """
    return W.decrypt_0a_payload(frame, key)


class WatchLogin:
    """手表扫码登录客户端。"""

    def __init__(self, *, profile: W.ClientProfile = W.PROFILE_WATCH_205,
                 imei: str = "860000000000001", mac: str = "00:11:22:33:44:55",
                 device: Optional[Dict[str, object]] = None,
                 server_public: bytes = ECDH_SERVER_PUBLIC_KEY,
                 on_log: Optional[Callable[[str], None]] = None) -> None:
        self.profile = profile
        self.imei = imei
        self.mac = mac
        self.on_log = on_log or (lambda _m: None)

        d = dict(device or {})
        d.setdefault("imei", imei)
        d.setdefault("mac_address", mac)
        d.setdefault("guid", hashlib.md5((imei + mac).encode()).digest())
        self.device = d

        self.guid: bytes = d["guid"]  # type: ignore[assignment]
        self.session_id = os.urandom(4)
        # 服务端公钥在真实环境是硬编码常量；离线回环时由 mock 注入自己的一对密钥
        self.server_public = server_public
        self.ecdh = Ecdh(server_public=server_public)
        self.random_key = os.urandom(16)

        self.uin = 0
        self.session = Session(guid=self.guid)
        self.msf = MsfClient(session_id=self.session_id, imei=imei, uin=0)
        self.seq = 0

    # ---------------------------------------------------------------- 基础设施

    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0x7FFF or 1
        self.msf.seq = self.seq
        return self.seq

    def _packer(self, *, seq_id: int = 0) -> T.TlvPacker:
        return T.TlvPacker(
            uin=self.uin,
            subid=self.profile.sub_appid,
            appid=self.profile.appid,
            sigmap=self.profile.sigmap,
            bitmap=self.profile.bitmap,
            apk_ver=self.profile.apk_ver.decode(),
            apk_name=self.profile.apk_name,
            sig=self.session.sig,
            device=self.device,
            seq_id=seq_id or self.seq,
        )

    def connect(self, host: str = "msfwifi.3g.qq.com", port: int = 8080) -> None:
        self.msf.connect(host, port)
        self.on_log(f"connected {host}:{port}")

    def close(self) -> None:
        self.msf.close()

    # ---------------------------------------------------------------- 阶段 1

    def fetch_qrcode(self) -> QrCode:
        """`wtlogin.trans_emp` cmdid=0x31 取二维码。

        oicq `fetchQrcode`：body = u16 0 | u32 16 | u64 0 | u8 8 | TLV(0) | u16 6 | TLV{16,1b,1d,1f,33,35}
        回包：明文 55B | u16 siglen | qrsig | u16 | TLV{0x17=PNG}
        """
        packer = self._packer()
        body = W.build_fetch_qrcode_body(
            tlv={
                0x16: packer.build(0x16),
                0x1B: packer.build(0x1B),
                0x1D: packer.build(0x1D),
                0x1F: packer.build(0x1F),
                0x33: packer.build(0x33),
                0x35: packer.build(0x35),
            }
        )
        pkt = W.build_trans_emp_packet(
            seq=self._next_seq(),
            head=W.QR_FETCH_HEAD,
            cmdid=CMD_FETCH,
            body=body,
            random_key=self.random_key,
            ecdh_public_key=self.ecdh.public_key,
            share_key=self.ecdh.share_key,
            session_id=self.session_id,
            imei=self.imei,
            ksid=packer.ksid,
        )
        rsp = self._send_raw_expect(pkt, "wtlogin.trans_emp")
        plain = strip_login_frame(rsp, self.ecdh.share_key)
        info = W.parse_fetch_qrcode_response(plain)
        self.on_log(f"二维码已获取 sig={info['qrsig'].hex()[:16]} png={len(info['png'])}B")
        return QrCode(qrsig=info["qrsig"], png=info["png"], tlvs=info["tlvs"])

    def poll_once(self, qrsig: bytes) -> PollResult:
        """cmdid=0x12 查询扫码状态。"""
        packer = self._packer()
        body = W.build_query_qrcode_body(qrsig)
        pkt = W.build_trans_emp_packet(
            seq=self._next_seq(),
            head=W.QR_QUERY_HEAD,
            cmdid=CMD_QUERY,
            body=body,
            random_key=self.random_key,
            ecdh_public_key=self.ecdh.public_key,
            share_key=self.ecdh.share_key,
            session_id=self.session_id,
            imei=self.imei,
            ksid=packer.ksid,
        )
        rsp = self._send_raw_expect(pkt, "wtlogin.trans_emp")
        plain = strip_login_frame(rsp, self.ecdh.share_key)
        info = W.parse_query_qrcode_response(plain)
        res = PollResult(
            ret_code=int(info["ret_code"]),
            uin=int(info["uin"]),
            t106=info["t106"],
            no_pic_sig=info["no_pic_sig"],
            t318=info["t318"],
            tgtgt=info["tgtgt"],
            tlvs=info["tlvs"],
        )
        self.on_log(f"poll uin={res.uin} {res.description}")
        return res

    def wait_for_scan(self, qr: QrCode, *, interval: float = 2.0,
                      timeout: float = 120.0) -> PollResult:
        deadline = time.time() + timeout
        while time.time() < deadline:
            res = self.poll_once(qr.qrsig)
            if res.ok:
                return res
            if res.ret_code in (0x02, 0x32, 0x36):
                raise LoginError(f"扫码被取消（0x{res.ret_code:02x}）")
            time.sleep(interval)
        raise TimeoutError("等待扫码超时")

    # ---------------------------------------------------------------- 阶段 2

    def login_with_qr(self, poll: PollResult,
                      tlv_extra: Optional[Dict[int, bytes]] = None) -> Session:
        """扫码确认后走 `wtlogin.login`（0x810 + 0x0A，enc=2）。

        oicq `_qrcodeLogin`：subCmd 区 u16 9 | u16 24，然后固定 TLV 序列，
        其中 0x106 原样、0x16A=t16a(noPicSig)、0x318=t318。
        """
        self.uin = poll.uin
        self.msf.uin = poll.uin
        self.session.uin = poll.uin
        self.session.t106 = poll.t106
        self.session.no_pic_sig = poll.no_pic_sig
        self.session.t318 = poll.t318
        self.session.tgtgt = poll.tgtgt or self.session.tgtgt

        packer = self._packer()
        packer.uin = poll.uin
        tlv_map = {tag: packer.build(tag) for tag in T.TLV_TAGS if hasattr(packer, f"_t{tag:04x}")}
        if tlv_extra:
            tlv_map.update(tlv_extra)

        body = W.build_qrcode_login_body(
            tlv=tlv_map, t106=poll.t106, t16a=poll.no_pic_sig, t318=poll.t318
        )
        inner = W.build_oicq_body(
            body,
            random_key=self.random_key,
            ecdh_public_key=self.ecdh.public_key,
            share_key=self.ecdh.share_key,
        )
        # _buildLoginPacket 的第二个参数是**已建好的 0x810 帧**，不是裸 body
        frame = wire.pack_0810_frame(poll.uin, wire.ENC_LOGIN, inner)
        pkt = W.build_login_packet(
            seq=self._next_seq(),
            subid=self.profile.sub_appid,
            session_id=self.session_id,
            imei=self.imei,
            ksid=packer.ksid,
            command=W.SERVICE_LOGIN,
            payload=frame,
            uin=poll.uin,
            enc_type=wire.ENC_BUF16,
            d2=self.session.d2,
            tgt=self.session.sig.get("tgt", b""),
        )
        rsp = self._send_raw_expect(pkt, W.SERVICE_LOGIN)
        plain = strip_login_frame(rsp, self.ecdh.share_key)
        parsed = W.parse_login_response(plain)
        if parsed["type"] != 0:
            raise LoginError(f"登录被拒 type={parsed['type']} tlvs={[hex(t) for t in parsed['tlvs']]}")
        t119 = parsed["tlvs"].get(0x119)
        if not t119:
            raise LoginError("回包无 0x119")
        self._apply_t119(t119, self.session.tgtgt)
        self.on_log(f"登录成功 uin={self.session.uin} nick={self.session.nickname!r}")
        return self.session

    # ---------------------------------------------------------------- 阶段 3

    def exchange_emp(self, sub_cmd: int = 15) -> Session:
        """`wtlogin.exchange_emp`：15 = A1 换全套票据；11 = A2/D2 静默续期。

        EMP 分支（0x45）的 body = TLV(sig_key) | TEA(payload, ticket_key)，
        外层再包 0x810，最后套 0x0A（enc=2）。
        """
        packer = self._packer()
        tlv_map = {tag: packer.build(tag) for tag in T.TLV_TAGS if hasattr(packer, f"_t{tag:04x}")}
        if sub_cmd == 15:
            tlv_map[0x100] = packer.build(0x100, 1)      # emp 分支写 2
            body = W.build_exchange_emp_body(
                sub_cmd=15, tlv=tlv_map, t106=self.session.t106,
                t16a=self.session.no_pic_sig,
            )
        elif sub_cmd == 11:
            tlv_map[0x100] = packer.build(0x100)
            body = W.build_exchange_emp_body(sub_cmd=11, tlv=tlv_map, d2=self.session.d2)
        else:
            raise ValueError(f"不支持的 subCmd {sub_cmd}")

        sig_key = self.session.sig.get("sig_key") or os.urandom(16)
        ticket_key = self.session.sig.get("ticket_key") or self.session.tgtgt
        emp_body = W.build_oicq_body(
            body, random_key=self.random_key, ecdh_public_key=self.ecdh.public_key,
            share_key=self.ecdh.share_key, sig_key=sig_key, ticket_key=ticket_key, emp=True,
        )
        frame = wire.pack_0810_frame(self.uin, wire.ENC_EMP, emp_body)
        pkt = W.build_login_packet(
            seq=self._next_seq(),
            subid=self.profile.sub_appid,
            session_id=self.session_id,
            imei=self.imei,
            ksid=packer.ksid,
            command=W.SERVICE_EXCHANGE_EMP,
            payload=frame,
            uin=self.uin,
            enc_type=wire.ENC_BUF16,
            d2=self.session.d2,
            tgt=self.session.sig.get("tgt", b""),
        )
        rsp = self._send_raw_expect(pkt, W.SERVICE_EXCHANGE_EMP)
        # EMP 回包的 0x0A 体用 ticket_key 解（登录回包才是 share_key）
        plain = strip_login_frame(rsp, ticket_key)
        parsed = W.parse_login_response(plain)
        if parsed["type"] != 0:
            raise LoginError(f"exchange_emp({sub_cmd}) 失败 type={parsed['type']}")
        t119 = parsed["tlvs"].get(0x119)
        if not t119:
            raise LoginError("exchange_emp 回包无 0x119")
        # t119 的密钥：subCmd=15 用 device.tgtgt；subCmd=11 用 md5(d2key)（oicq refreshD2）
        if sub_cmd == 11:
            self.device["tgtgt"] = hashlib.md5(self.session.d2key).digest()
        t119_key = bytes(self.device.get("tgtgt") or self.session.tgtgt)  # type: ignore[arg-type]
        self._apply_t119(t119, t119_key)
        self.on_log(f"exchange_emp({sub_cmd}) 成功 d2={len(self.session.d2)}B d2key={len(self.session.d2key)}B")
        return self.session

    def _apply_t119(self, t119: bytes, key: bytes) -> None:
        info = W.parse_t119(t119, key)
        sig = info.get("sig") or {}
        self.session.sig.update({k: v for k, v in sig.items() if v})
        if info.get("nickname"):
            self.session.nickname = str(info["nickname"])
        if info.get("age"):
            self.session.age = int(info["age"])
        if info.get("sex"):
            self.session.sex = str(info["sex"])
        if info.get("pskeys"):
            self.session.pskeys.update(info["pskeys"])  # type: ignore[arg-type]
        self.session.t106 = self.session.t106 or info.get("t106", b"")  # type: ignore[assignment]
        self.msf.set_d2(self.session.d2, self.session.d2key)

    # ---------------------------------------------------------------- 阶段 4

    def register_online(self, status: int = R.STATUS_ONLINE) -> Response:
        packer = self._packer()
        body = R.build_svc_req_register(
            uin=self.uin,
            guid=self.guid,
            status=status,
            dev_name=str(self.device.get("model", self.profile.device_model)),
            dev_type=str(self.device.get("model", self.profile.device_model)),
            brand=str(self.device.get("brand", self.profile.device_brand)),
            os_ver=self.profile.os_version,
            build_ver=self.profile.apk_ver.decode(),
            protocol="full",
        )
        rsp = self.msf.send("StatSvc.register", body, use_d2=True)
        self.on_log(f"register -> {len(rsp.payload)}B")
        return rsp

    def heartbeat(self) -> Response:
        return self.msf.send("Heartbeat.Alive", b"", use_d2=True)

    def pull_messages(self, cookie: bytes = b"") -> tuple[bytes, List[M.Msg]]:
        if not cookie:
            cookie = M.build_sync_cookie()
        rsp = self.msf.send("MessageSvc.PbGetMsg", M.build_get_msg(cookie), use_d2=True)
        return M.parse_get_msg_rsp(rsp.payload)

    def send_c2c(self, to_uin: int, text: str, seq: int = 0, rand: int = 0) -> Response:
        body = M.build_send_msg(
            text=text, seq=seq or self._next_seq(), rand=rand or int.from_bytes(os.urandom(4), "big"),
            to_uin=to_uin, sync_cookie=M.build_sync_cookie(),
        )
        return self.msf.send("MessageSvc.PbSendMsg", body, use_d2=True)

    def send_group(self, group_code: int, text: str, seq: int = 0, rand: int = 0) -> Response:
        body = M.build_send_msg(
            text=text, seq=seq or self._next_seq(), rand=rand or int.from_bytes(os.urandom(4), "big"),
            group_code=group_code,
        )
        return self.msf.send("MessageSvc.PbSendMsg", body, use_d2=True)

    # ---------------------------------------------------------------- 内部

    def _send_raw_expect(self, pkt: bytes, command: str, timeout: float = 15.0) -> bytes:
        """登录类命令：直接写 socket，收集下一个**未被 seq 匹配**的回包原始帧。

        登录族回包在 0x0A 外壳里，MsfClient 不解析（见 transport._dispatch），
        会以 `command=""` 透传到 on_push。
        """
        if not self.msf.connected:
            raise LoginError("未连接")
        got: List[bytes] = []
        prev = self.msf.on_push

        def _hook(resp: Response) -> None:
            if resp.raw:
                got.append(resp.raw)
            elif prev is not None:
                prev(resp)

        self.msf.on_push = _hook
        try:
            self.msf.send_raw(pkt)
            deadline = time.time() + timeout
            while time.time() < deadline and not got:
                time.sleep(0.02)
        finally:
            self.msf.on_push = prev
        if not got:
            raise LoginError(f"{command} 无响应（{timeout:.0f}s）")
        return got[0]


__all__ = ["WatchLogin", "QrCode", "PollResult", "Session", "LoginError", "strip_login_frame"]
