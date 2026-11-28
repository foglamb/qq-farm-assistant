"""MSF 传输层：TCP 分帧 + 0x0A/0x0B 收发 + 心跳/重连。

与 oicq `client-net.js` / `client-ext.js` 语义一致：
  * 每个响应包首 4 字节是总长（含自身）
  * 请求以 seq 关联回包，超时即丢
  * 心跳：`Heartbeat.Alive`（空 payload），官方节奏 30s，样本 45s
  * 重连：socket close 后按退避重连并重发 StatSvc.register
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import wire

DEFAULT_HOST = "msfwifi.3g.qq.com"
DEFAULT_PORT = 8080


@dataclass
class Response:
    command: str
    seq: int
    payload: bytes
    retcode: int = 0
    service: str = ""
    raw: bytes = b""


class MsfError(RuntimeError):
    pass


class MsfClient:
    """最小可用的 MSF 客户端。

    用法::

        c = MsfClient(session_id=b'\\xca\\xfe\\xba\\xbe', imei='860...', uin=10001)
        c.connect("127.0.0.1", 18080)          # 或默认官方入口
        c.set_d2(d2, d2key)
        c.send("StatSvc.register", body, use_d2=True)
    """

    def __init__(self, *, session_id: bytes, imei: str, uin: int = 0,
                 on_push: Optional[Callable[[Response], None]] = None) -> None:
        self.session_id = session_id[:4].rjust(4, b"\x00")
        self.imei = imei
        self.uin = uin
        self.d2 = b""
        self.d2key = b""
        self.seq = 0
        self.on_push = on_push
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._handlers: Dict[int, Tuple[threading.Event, List[Response]]] = {}
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.log: List[str] = []

    # ---- 连接 ----

    def connect(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 10.0) -> None:
        self.close()
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.settimeout(None)
        self._sock = sock
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, name="msf-reader", daemon=True)
        self._reader.start()
        self.log.append(f"connected {host}:{port}")

    def close(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def set_d2(self, d2: bytes, d2key: bytes) -> None:
        self.d2, self.d2key = d2, d2key

    def next_seq(self) -> int:
        with self._lock:
            self.seq = (self.seq + 1) & 0x7FFF or 1
            return self.seq

    # ---- 读写 ----

    def _read_loop(self) -> None:
        sock = self._sock
        while not self._stop.is_set() and sock is not None:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk
            while len(self._buf) > 4:
                total = struct.unpack(">I", self._buf[:4])[0]
                if total < 4 or total > 64 * 1024 * 1024:
                    self.log.append(f"bad frame length {total}")
                    self._buf.clear()
                    break
                if len(self._buf) < total:
                    break
                pkt = bytes(self._buf[4:total])
                del self._buf[:total]
                self._dispatch(pkt)
        self.log.append("reader exit")

    def _dispatch(self, pkt: bytes) -> None:
        """0x0B 走标准 SSO 解析；解析不了的（0x0A 登录族回包）整体交给 on_push。

        登录族回包的 SSO 体布局与服务包不同，且需要 ECDH/临时密钥才能解，
        所以 MsfClient 不解释它，只把原始帧透传出去。
        """
        try:
            seq, enc, cipher = wire.parse_sso_frame(pkt)
            key = self.d2key if enc == wire.ENC_D2 else b"\x00" * 16
            body = wire.parse_sso_body(cipher, enc, key)
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"raw frame -> on_push ({exc})")
            if self.on_push:
                self.on_push(Response(command="", seq=0, payload=b"", raw=pkt))
            return
        resp = Response(command=body["command"], seq=int(seq), payload=body["payload"], raw=pkt)
        waiter = self._handlers.get(resp.seq)
        if waiter:
            waiter[0].set()
            waiter[1].append(resp)
            return
        if self.on_push:
            self.on_push(resp)

    def send_raw(self, frame: bytes) -> None:
        if self._sock is None:
            raise MsfError("not connected")
        self._sock.sendall(frame)

    def send(self, command: str, payload: bytes, *, use_d2: bool = True,
             timeout: float = 10.0) -> Response:
        seq = self.next_seq()
        enc = wire.ENC_D2 if use_d2 else wire.ENC_BUF16
        frame = wire.pack_sso_frame(seq, command, payload, self.session_id, self.uin, enc,
                                    d2=self.d2, d2key=self.d2key)
        ev, box = threading.Event(), []
        self._handlers[seq] = (ev, box)
        try:
            self.send_raw(frame)
            if not ev.wait(timeout):
                raise MsfError(f"{command} timeout (seq={seq})")
            return box[0]
        finally:
            self._handlers.pop(seq, None)

    def heartbeat(self, timeout: float = 5.0) -> Response:
        return self.send("Heartbeat.Alive", b"", use_d2=True, timeout=timeout)


class Keepalive:
    """定时心跳 + 拉消息 + 失败重连。"""

    def __init__(self, client: MsfClient, *, interval: float = 30.0,
                 on_tick: Optional[Callable[[], None]] = None,
                 on_reconnect: Optional[Callable[[], None]] = None) -> None:
        self.client = client
        self.interval = interval
        self.on_tick = on_tick
        self.on_reconnect = on_reconnect
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.errors = 0

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="msf-keepalive", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if self.on_tick:
                    self.on_tick()
                self.client.heartbeat()
                self.errors = 0
            except Exception as exc:  # noqa: BLE001
                self.errors += 1
                self.client.log.append(f"keepalive error #{self.errors}: {exc}")
                if self.errors >= 2 and self.on_reconnect:
                    try:
                        self.on_reconnect()
                        self.errors = 0
                    except Exception as exc2:  # noqa: BLE001
                        self.client.log.append(f"reconnect failed: {exc2}")


__all__ = ["MsfClient", "MsfError", "Response", "Keepalive", "DEFAULT_HOST", "DEFAULT_PORT"]
