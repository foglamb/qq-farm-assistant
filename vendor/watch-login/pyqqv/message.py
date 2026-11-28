"""MessageSvc.* / OnlinePush.* —— 消息拉取、发送、推送解析。

两种布局都实现：
  variant="official" —— oicq 1.21.6 原始布局（含 PB_RESERVER 与 buildSyncCookie）
  variant="watch"    —— watch_client.py 的简化布局（无 PB_RESERVER，msg_via=1）

差异清单见 build_send_msg 的 docstring；两者对服务端都合法，
但 official 布局在群消息 message_id 回执链路上更完整。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .wire import PbWriter, pb_decode, pb_get, pb_get_all

MSG_TYPE_C2C = 0
MSG_TYPE_GROUP = 1
MSG_TYPE_DISCUSS = 2

# 官方 PB_CONTENT：{1:1, 2:0, 3:0}  —— 静态常量
PB_CONTENT_OFFICIAL = b"\x08\x01\x10\x00\x18\x00"


def build_pb_reserver() -> bytes:
    """{37:{17:0,19:{15:0,31:0,41:0}}} —— 官方每个 RichText 尾部都携带。

    注意所有值都是 0，PbWriter 默认跳过零值，必须显式 always=True。
    """
    inner = (
        PbWriter()
        .uint(15, 0, always=True)
        .uint(31, 0, always=True)
        .uint(41, 0, always=True)
    )
    f37 = PbWriter().uint(17, 0, always=True).message(19, inner)
    return PbWriter().message(37, f37).finish()


def build_sync_cookie(timestamp: Optional[int] = None, const1: int = 111,
                      const2: int = 222, const3: int = 7) -> bytes:
    """C2C 同步游标。字段乱序、随机量多，服务端按 tag 读，不校验顺序。"""
    ts = int(timestamp if timestamp is not None else time.time())
    w = (
        PbWriter()
        .uint(1, ts)
        .uint(2, ts)
        .uint(3, const1)
        .uint(4, const2)
        .uint(5, random.getrandbits(32))
        .uint(9, random.getrandbits(32))
        .uint(11, random.getrandbits(32))
        .uint(12, const3)
        .uint(13, ts)
        .uint(14, 0, always=True)
    )
    return w.finish()


def build_text_elem(text: str) -> PbWriter:
    """Text 元素：Elem{1: Text{1: str}}。"""
    return PbWriter().message(1, PbWriter().string(1, text))


def build_msg_body(text: str, variant: str = "official", reserver: Optional[bytes] = None) -> bytes:
    """MsgBody{1: RichText{2: Elem*}}。"""
    rich = PbWriter()
    rich.message(2, build_text_elem(text))
    if variant == "official":
        rich.bytes(2, reserver if reserver is not None else build_pb_reserver())
    return PbWriter().message(1, rich).finish()


def build_send_msg(
    *,
    text: str,
    seq: int,
    rand: int,
    to_uin: int = 0,
    group_code: int = 0,
    discuss_code: int = 0,
    temp_group: int = 0,
    sync_cookie: bytes = b"",
    variant: str = "official",
) -> bytes:
    """构造 MessageSvc.PbSendMsg 请求体。

    字段对照（oicq builder.buildPbSendMsgPkt）::

        1 routing        c2c   {1:{1:uin}}
                         群    {2:{1:group}}
                         讨论组 {4:{1:discuss}}
                         临时会话 {3:{1:group_uin, 2:uin}}
        2 content        PB_CONTENT {1:1,2:0,3:0}
        3 {1: rich}      RichText{2:[Elem...]}
        4 seq            客户端序号
        5 random         32bit 随机
        6 sync_cookie    仅 c2c 携带
        8 msg_via        official=0，watch_client 传 1
    """
    if group_code:
        routing = PbWriter().message(2, PbWriter().uint(1, group_code))
    elif discuss_code:
        routing = PbWriter().message(4, PbWriter().uint(1, discuss_code))
    elif temp_group:
        routing = PbWriter().message(
            3, PbWriter().uint(1, temp_group).uint(2, to_uin)
        )
    else:
        routing = PbWriter().message(1, PbWriter().uint(1, to_uin))

    content = PbWriter().uint(1, 1).uint(2, 0, always=True).uint(3, 0, always=True)

    req = PbWriter()
    req.message(1, routing)
    req.message(2, content)
    # tag3 直接是 MsgBody{1: RichText{2: Elem*}}；RichText 的 Elem 是 repeated，
    # 因此同一 tag2 连续出现多次（官方用 pb.encode 的数组展开实现）
    req.bytes(3, build_msg_body(text, variant))
    req.uint(4, seq)
    req.uint(5, rand)
    if not group_code and not discuss_code:
        req.bytes(6, sync_cookie)
    # official: oicq 显式写 tag8=0（pb.encode 会把 0 编成 varint 0，字节存在）
    # watch:   样本写 1
    req.uint(8, 0 if variant == "official" else 1, always=True)
    return req.finish()


def build_get_msg(sync_cookie: bytes, sync_flag: int = 0, variant: str = "official") -> bytes:
    """MessageSvc.PbGetMsg 请求。official 的 tag9=1，watch_client 传 0。"""
    w = (
        PbWriter()
        .uint(1, sync_flag, always=True)
        .bytes(2, sync_cookie)
        .uint(3, 0, always=True)
        .uint(4, 20)
        .uint(5, 3)
        .uint(6, 1)
        .uint(7, 1)
        .uint(9, 1 if variant == "official" else 0, always=True)
    )
    return w.finish()


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

@dataclass
class Msg:
    msg_type: str
    from_uin: int
    to_uin: int
    group_code: int
    sender_nick: str
    text: str
    seq: int
    msg_time: int
    msg_type_id: int            # 头部 tag3：166=好友 85=群 141=陌生人 ...
    raw_head: Dict[int, object]


def _extract_text(body_bytes: bytes) -> str:
    """RichText -> 所有 Text 元素拼接（图片/表情/at 忽略）。"""
    parts: List[str] = []
    body = pb_decode(body_bytes)
    rich = pb_get(body, 1)
    if not isinstance(rich, bytes):
        return ""
    for elem in pb_get_all(pb_decode(rich), 2):
        if not isinstance(elem, bytes):
            continue
        ef = pb_decode(elem)
        text_field = pb_get(ef, 1)
        if isinstance(text_field, bytes):
            raw = pb_get(pb_decode(text_field), 1)
            if isinstance(raw, bytes):
                parts.append(raw.decode("utf-8", "replace"))
    return "".join(parts)


def parse_msg(msg_bytes: bytes, default_type: str = "c2c") -> Optional[Msg]:
    fields = pb_decode(msg_bytes)
    head_b, body_b = pb_get(fields, 1), pb_get(fields, 3)
    if not isinstance(head_b, bytes) or not isinstance(body_b, bytes):
        return None
    hf = {f: v for f, _, v in pb_decode(head_b)}
    group_code, nick = 0, ""
    grp = hf.get(9)
    if isinstance(grp, bytes):
        gf = {f: v for f, _, v in pb_decode(grp)}
        group_code = int(gf.get(1, 0) or 0)
        if isinstance(gf.get(4), bytes):
            nick = gf[4].decode("utf-8", "replace")
    return Msg(
        msg_type="group" if group_code else default_type,
        from_uin=int(hf.get(1, 0) or 0),
        to_uin=int(hf.get(2, 0) or 0),
        group_code=group_code,
        sender_nick=nick,
        text=_extract_text(body_b),
        seq=int(hf.get(5, 0) or 0),
        msg_time=int(hf.get(6, 0) or 0),
        msg_type_id=int(hf.get(3, 0) or 0),
        raw_head=hf,
    )


def parse_get_msg_rsp(buf: bytes) -> Tuple[bytes, List[Msg]]:
    """PbGetMsg 响应 -> (新 cookie, 消息列表)。结构 {1: ret, 3: cookie, 5:[{4:[Msg]}]}。"""
    fields = pb_decode(buf)
    cookie = pb_get(fields, 3, b"")
    if not isinstance(cookie, bytes):
        cookie = b""
    out: List[Msg] = []
    for pair in pb_get_all(fields, 5):
        if not isinstance(pair, bytes):
            continue
        for raw in pb_get_all(pb_decode(pair), 4):
            if isinstance(raw, bytes):
                m = parse_msg(raw, "c2c")
                if m and m.text:
                    out.append(m)
    return cookie, out


def parse_push_group(buf: bytes) -> Optional[Msg]:
    """OnlinePush.PbPushGroupMsg: PushMessagePacket{1: Msg}。"""
    fields = pb_decode(buf)
    raw = pb_get(fields, 1)
    if not isinstance(raw, bytes):
        return None
    return parse_msg(raw, "group")


def parse_push_common(buf: bytes) -> Optional[Msg]:
    """OnlinePush.PbPushCommonMsg / C2CMsgSync 同构：外层 tag1 即 Msg。"""
    return parse_push_group(buf)


# 需要回执的推送命令（oicq 用 JCE OnlinePush.RespPush 回执）
PUSH_NEED_ACK = {
    "OnlinePush.PbPushGroupMsg",
    "OnlinePush.PbPushDisMsg",
    "OnlinePush.ReqPush",
    "OnlinePush.PbPushTransMsg",
    "OnlinePush.PbC2CMsgSync",
}

# MessageSvc.PushNotify 里的 sub_type -> 拉取动作
PUSH_NOTIFY_PULL_TYPES = {33, 38, 85, 141, 166, 167, 208, 529}

__all__ = [
    "MSG_TYPE_C2C", "MSG_TYPE_GROUP", "MSG_TYPE_DISCUSS",
    "PB_CONTENT_OFFICIAL", "build_pb_reserver", "build_sync_cookie",
    "build_msg_body", "build_send_msg", "build_get_msg",
    "Msg", "parse_msg", "parse_get_msg_rsp", "parse_push_group", "parse_push_common",
    "PUSH_NEED_ACK", "PUSH_NOTIFY_PULL_TYPES",
]
