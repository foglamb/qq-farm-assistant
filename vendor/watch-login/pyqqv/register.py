"""StatSvc.register / SvcReqRegister —— 官方 oicq 实际编码 36 个 tag 的 JCE 版本。

watch_client.py 里手写的是 **精简 24 字段** 版本（tag 0..23），字段序号与官方
SvcReqRegister 一一对应，但缺 tag 24..37（含 model/brand/pb 时间戳子结构）。
两者都能被服务端解析（JCE 按 tag 解码，缺 tag 回落默认值），差异记录在
report 的「字段对比」一节。
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from .wire import JceWriter, PbWriter, pb_decode, pb_get_all

PUSH_SERVICE = "PushService"
REGISTER_METHOD = "SvcReqRegister"

STATUS_ONLINE = 11
STATUS_OFFLINE = 21
STATUS_AWAY = 31
STATUS_INVISIBLE = 41
STATUS_BUSY = 50
STATUS_QME = 60
STATUS_NODND = 70

# 客户端类型位掩码：1=PC 2=Mobile 4=Watch 8=iPad ... 官方 register 用 7(PC|Mobile|Watch 复合)
LBID_WATCH = 7


def build_svc_req_register(
    uin: int,
    guid: bytes,
    status: int = STATUS_ONLINE,
    dev_name: str = "OPPO Watch 3",
    dev_type: str = "OPPO Watch 3",
    brand: str = "OPPO",
    os_ver: str = "11",
    build_ver: str = "4.0.2",
    sdk_ver: int = 29,
    locale_id: int = 2052,
    model: Optional[str] = None,
    timestamp: Optional[int] = None,
    pb_timestamp: Optional[int] = None,
    logout: bool = False,
    protocol: str = "full",
) -> bytes:
    """构造 SvcReqRegister。

    protocol="full"    -> 官方 36 tag 布局（含 pb 子结构、brand、1000/98 尾巴）
    protocol="compact" -> watch_client.py 的 24 字段精简布局
    """
    # tag10(timeStamp) 在官方实现里是 `logout ? 44 : 0`，不是真实时间。
    # sample 传 int(time.time())：服务端接受，但字节上与官方不一致。
    ts = int(timestamp if timestamp is not None else (44 if logout else 0))
    pb_ts = int(pb_timestamp if pb_timestamp is not None else time.time())
    model = model or dev_name
    w = JceWriter()
    w.int32(0, uin)                              # lUin
    w.int32(1, LBID_WATCH)                       # lBid
    w.int32(2, 0)                                # cConnType
    w.string(3, "")                              # sOther
    w.int32(4, status)                           # iStatus
    w.int32(5, 0)                                # bOnlinePush
    w.int32(6, 0)                                # bIsOnline
    w.int32(7, 0)                                # bIsShowOnline
    w.int32(8, 0)                                # bKikPC
    w.int32(9, 0)                                # bKikWeak
    w.int32(10, ts)                              # timeStamp
    w.int32(11, sdk_ver)                         # iOSVersion (安卓 SDK int 复用)
    w.int32(12, 1)                               # cNetType 1=WiFi
    w.string(13, build_ver)                      # sBuildVer
    w.int32(14, 0)                               # bRegType
    w.bytes(16, guid)                            # vecGuid
    w.int32(17, locale_id)                       # iLocaleID
    w.int32(18, 0)                               # bSlientPush
    w.string(19, dev_name)                       # strDevName
    w.string(20, dev_type)                       # strDevType
    w.string(21, os_ver)                         # strOSVer
    w.int32(22, 1)                               # bOpenPush
    w.int32(23, 0)                               # iLargeSeq
    if protocol == "compact":
        body = w.finish()
    else:
        pb_buf = (
            PbWriter()
            .message(1, PbWriter().uint(1, 46).uint(2, pb_ts))
            .message(1, PbWriter().uint(1, 283).uint(2, 0, always=True))
            .finish()
        )
        # 官方 SvcReqRegister 数组位置 -> JCE tag（null 位置整段跳过）
        w.int32(24, 0)
        w.int32(26, 0)
        w.int32(27, 0)
        w.string(28, "")
        w.int32(29, 0)
        w.string(30, brand)                      # strBrand
        w.string(31, brand)                      # strBrand2
        w.string(32, "")
        w.bytes(33, pb_buf)                      # pb 时间戳 / 上报位
        w.int32(34, 0)
        w.int32(36, 0)
        w.int32(38, 1000)
        w.int32(39, 98)
        body = w.finish()

    wrapped = JceWriter()
    wrapped.struct(0, body)

    payload = JceWriter()
    payload.map_str_bytes(0, {REGISTER_METHOD: wrapped.finish()})

    pkt = JceWriter()
    pkt.int32(1, 3)                 # version
    pkt.int32(2, 0)                 # pkt_type
    pkt.int32(3, 0)                 # msg_type
    pkt.int32(4, 0)                 # req_id
    pkt.string(5, PUSH_SERVICE)     # service
    pkt.string(6, REGISTER_METHOD)  # method
    pkt.bytes(7, payload.finish())  # payload
    pkt.int32(8, 0)                 # timeout
    pkt.map_str_bytes(9, {})        # context
    pkt.map_str_bytes(10, {})       # status
    return pkt.finish()


def read_svc_resp_register(blob: bytes) -> Dict[str, object]:
    """解析 SvcReqRegister 响应头部（oicq 只判断 tag9 是否非空）。"""
    from .wire import JceReader

    try:
        outer = JceReader(blob).decode()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return {
        "raw_tags": sorted(outer),
        "online": bool(outer.get(9)),
        "uint32_status": outer.get(9, 0),
    }


__all__ = [
    "build_svc_req_register", "read_svc_resp_register",
    "STATUS_ONLINE", "STATUS_OFFLINE", "STATUS_AWAY", "STATUS_INVISIBLE",
    "STATUS_BUSY", "STATUS_QME", "STATUS_NODND", "LBID_WATCH",
]
