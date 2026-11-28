#!/usr/bin/env python3
"""手表协议扫码登录宿主 —— 与 NapCat / AndroidPad 并列的第三条扫码渠道。

宿主协议与 farm 的 `core/src/services/qq-login-service.js` 一致：
逐行读 JSON 命令，逐行写 ``QQFARM_LOGIN:`` 前缀的事件。

    {"command":"start"}                          生成二维码
    {"command":"request_code","requestId":"..."}  取农场 Code
    {"command":"shutdown"}                        退出

输出事件：

    {"kind":"qr",   "value":{"png":"<base64>","expireTimeRaw":120}}
    {"kind":"state","value":{"phase":"waiting_scan","message":"...","canRequest":false}}
    {"kind":"session","value":{"uin":"12345678"}}
    {"kind":"code", "value":{"code":"...","requestId":"..."}}

手表链路不需要 ``libfekit.so`` 签名：扫码走纯 P-256 ECDH + TLV 换票。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pyqqv import watch_login as WL  # noqa: E402
from pyqqv import wire as W  # noqa: E402

PREFIX = "QQFARM_LOGIN:"
FARM_APP_ID = "1112386029"
FARM_CODE_COMMAND = "LightAppSvc.mini_program_auth.GetCode"


class Host:
    """一个进程服务一个账号：登录一次，Code 可取多次。"""

    def __init__(self, session_dir: Path, out, *, host: str, port: int,
                 imei: str, mac: str, timeout: float) -> None:
        self.session_dir = session_dir
        self.out = out
        self.host = host
        self.port = port
        self.imei = imei
        self.mac = mac
        self.timeout = timeout
        self.lock = threading.Lock()
        self.login: Optional[WL.WatchLogin] = None
        self.session: Optional[WL.Session] = None
        self.started = False
        self.requesting = False
        self.uin = ""

    # ---------------------------------------------------------------- 输出

    def emit(self, kind: str, value: Dict[str, object]) -> None:
        line = PREFIX + json.dumps({"kind": kind, "value": value}, ensure_ascii=False)
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()

    def state(self, phase: str, message: str, can_request: bool = False,
              request_id: str = "", reason: str = "") -> None:
        payload = {"phase": phase, "message": message, "canRequest": can_request,
                   "verifyUrl": None, "phone": None, "requestId": request_id or None}
        if reason:
            payload["reason"] = reason
        self.emit("state", payload)

    def error(self, message: str, request_id: str = "", reason: str = "") -> None:
        self.state("error", message, request_id=request_id, reason=reason)

    # ---------------------------------------------------------------- 命令

    def handle(self, line: str) -> bool:
        """返回 False 表示要求退出。"""
        try:
            command = json.loads(line)
        except json.JSONDecodeError as error:
            self.error("命令 JSON 无效：" + str(error), reason="invalid_command")
            return True
        if not isinstance(command, dict):
            self.error("命令必须是 JSON 对象", reason="invalid_command")
            return True
        name = str(command.get("command") or "")
        if name == "start":
            self.start()
        elif name == "request_code":
            self.request_code(str(command.get("requestId") or ""))
        elif name == "shutdown":
            self.shutdown()
            return False
        else:
            self.error("未知命令：" + name, reason="invalid_command")
        return True

    def start(self) -> None:
        if self.started:
            self.error("登录操作已在进行", reason="busy")
            return
        self.started = True
        thread = threading.Thread(target=self._login_worker, daemon=True)
        thread.start()

    def _login_worker(self) -> None:
        try:
            self.state("starting", "正在连接手表登录服务器")
            login = WL.WatchLogin(imei=self.imei, mac=self.mac,
                                 on_log=lambda m: self.state("starting", str(m)))
            self.login = login
            login.connect(self.host, self.port)
            self.state("starting", "正在申请二维码")
            qr = login.fetch_qrcode()
            self._emit_qr(qr)
            self.state("waiting_scan", "请用手机 QQ 扫码并确认登录")
            poll = login.wait_for_scan(qr, interval=2.0, timeout=self.timeout)
            if not poll.ok:
                self.error("扫码未完成：" + poll.description, reason="login_failed")
                return
            self.state("scanned", "已扫码，正在完成登录")
            session = login.login_with_qr(poll)
            session = login.exchange_emp() if not session.d2 else session
            self.session = session
            self.uin = str(session.uin)
            self.emit("session", {"uin": self.uin})
            login.register_online()
            self.state("online", "手表协议登录成功", can_request=True)
            # The farm expects a Code right after login, not only on demand: its
            # restore path waits for one before it will reuse a saved profile.
            self.request_code("")
        except Exception as error:  # noqa: BLE001 - 任何失败都要回传给宿主
            self.error("手表扫码失败：" + str(error) or error.__class__.__name__)
        finally:
            self.started = False

    def _emit_qr(self, qr: "WL.QrCode") -> None:
        png = bytes(getattr(qr, "png", b"") or b"")
        if not png:
            path = getattr(qr, "path", "")
            if path and os.path.exists(path):
                png = Path(path).read_bytes()
        if not png:
            self.error("二维码图片生成失败")
            return
        self.emit("qr", {"png": base64.b64encode(png).decode(), "expireTimeRaw": 120})

    def request_code(self, request_id: str) -> None:
        if self.requesting:
            self.error("正在获取农场 Code，请稍后重试", request_id, reason="busy")
            return
        if not self.session or not self.login:
            self.error("手表协议尚未在线，不能请求 Code", request_id, reason="offline")
            return
        self.requesting = True
        self.state("requesting", "正在调用 " + FARM_CODE_COMMAND, request_id=request_id)
        try:
            code = self.fetch_farm_code()
            if not code:
                self.error("GetCode 未返回有效 Code", request_id)
                return
            self.emit("code", {"code": code, "requestId": request_id or None})
            self.state("success", "已获取真实农场 Code", can_request=True, request_id=request_id)
        except Exception as error:  # noqa: BLE001
            self.error("GetCode 调用失败：" + str(error), request_id)
        finally:
            self.requesting = False

    def fetch_farm_code(self) -> str:
        """向 LightAppSvc.mini_program_auth.GetCode 取农场 Code。"""
        assert self.session is not None and self.login is not None
        request = _build_get_code(self.session, self.login.profile)
        response = self.login.msf.send(FARM_CODE_COMMAND, request, use_d2=True, timeout=20.0)
        return _parse_get_code(response.payload)

    def shutdown(self) -> None:
        try:
            if self.login:
                self.login.close()
        except Exception:  # noqa: BLE001
            pass
        self.state("offline", "手表协议宿主已停止")


# ------------------------------------------------------------------ protobuf

def _pb_bytes(field: int, data: bytes) -> bytes:
    varint = W.PbWriter.varint
    return varint((field << 3) | 2) + varint(len(data)) + data


def _pb_varint(field: int, value: int) -> bytes:
    return W.PbWriter.varint((field << 3) | 0) + W.PbWriter.varint(value)


def _build_get_code(session: "WL.Session", profile) -> bytes:
    """MiniQWebRequest { seq, qua, device_info, busi_buff, trace_id }。"""
    qua = getattr(profile, "qua", "") or "V1_AND_SQ_9.3.75_16580_YYB_D"
    busi = _pb_bytes(1, FARM_APP_ID.encode())  # MiniGetCodeRequest { appid }
    return (_pb_varint(1, 3)
            + _pb_bytes(2, qua.encode())
            + _pb_bytes(3, b"")
            + _pb_bytes(4, busi)
            + _pb_bytes(5, str(session.uin).encode()))


def _parse_get_code(plain: bytes) -> str:
    """MiniQWebResponse { seq, retcode, errmsg, busi_buff{MiniGetCodeResponse{code}} }。"""
    fields = W.pb_decode(plain)
    busi = W.pb_get(fields, 4)
    if isinstance(busi, (bytes, bytearray)) and busi:
        code = W.pb_get(W.pb_decode(bytes(busi)), 1)
        if isinstance(code, (bytes, bytearray)):
            return code.decode("utf-8", "ignore")
    # 少数服务端直接返回 StGetCodeRsp，没有 busi_buff 外壳。
    code = W.pb_get(fields, 1)
    if isinstance(code, (bytes, bytearray)):
        text = code.decode("utf-8", "ignore")
        if text and not text.isdigit():
            return text
    return ""


# ------------------------------------------------------------------ 入口

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir")
    parser.add_argument("--host", default=os.environ.get("WATCH_LOGIN_HOST", "msfwifi.3g.qq.com"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("WATCH_LOGIN_PORT", "8080")))
    parser.add_argument("--imei", default=os.environ.get("WATCH_IMEI", "860000000000001"))
    parser.add_argument("--mac", default=os.environ.get("WATCH_MAC", "00:11:22:33:44:55"))
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    directory = Path(args.session_dir)
    directory.mkdir(parents=True, exist_ok=True)
    host = Host(directory, sys.stdout, host=args.host, port=args.port,
                imei=args.imei, mac=args.mac, timeout=args.timeout)
    host.state("starting", "手表协议宿主已启动")
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if len(line) > 65536:
                host.error("命令行过长", reason="invalid_command")
                continue
            if not host.handle(line):
                break
    except KeyboardInterrupt:
        pass
    finally:
        host.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
