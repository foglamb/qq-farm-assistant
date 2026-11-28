"""QQ Watch 协议分析基线（纯标准库实现，与 oicq 1.21.6 逐字节对齐）。"""

from .wire import (  # noqa: F401
    ENC_BUF16, ENC_D2, ENC_EMP, ENC_LOGIN, ENC_NONE,
    JceReader, JceType, JceWriter,
    PbWriter, TeaError,
    pack_0810_frame, pack_sso_frame, parse_0810_response, parse_sso_body, parse_sso_frame,
    pb_decode, pb_get, pb_get_all, read_tlvs, tea_decrypt, tea_encrypt, with_len,
)
from .register import (  # noqa: F401
    STATUS_ONLINE, build_svc_req_register, read_svc_resp_register,
)

__version__ = "1.0.0"
