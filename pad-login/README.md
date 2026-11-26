# AndroidPad 登录与农场 Code 隔离验证

独立进程、独立端口、独立数据卷，不读取或修改现有 NapCat 容器和账号数据。

## 已验证

- `Lagrange.Core 2.1.3` / .NET 8 编译通过。
- AndroidPad 9.2.20 / `11650` 登录配置通过。
- 本地签名服务 `/sign`、`/energy`、`/get_tlv553` 在服务器上均实测 `code=0`，构建和证据见 `../qsign-service/`。
- QQ TEA 通过 Lagrange 内置实现的 Span 委托调用，启动自检通过。
- HTTP 鉴权、健康检查、Pad 到签名服务的容器网络连接通过。
- `FARM_AUTH_ROUNDTRIP=PASS`：真实 `FarmAuthService.Build/Parse` 已完成 A2 前缀、TEA、Proto 请求字段及响应 Code 的离线回环测试（`PAD_SELF_TEST=1`）。
- 当前状态为 `needs_password`：等待真实账号首登，尚未声称腾讯在线登录或农场 Code 已成功。

## AndroidPad 首登

当前 Lagrange V2 的 `WtExchangeLogic.ManualLogin` 拒绝 Android 空密码 QR 登录，`TransEmpService` 也只给 PC/AndroidWatch 注册 QR 服务。因此 AndroidPad 首次登录需要 QQ 号和密码；成功后保存 keystore，后续可免密恢复。

密码只随本次请求进入内存，不写入 keystore 或状态接口。keystore 本身属于敏感登录凭据，应保护数据卷。为降低新设备风控，失败时也会保留 Guid/AndroidId 等设备字段；只有 A2 非空才计为可恢复的登录会话，`hasDevice` 与 `hasSavedSession` 分开显示。

## 农场 Code 自定义服务

`FarmAuthService.cs` 注册 `QQConnectLogin.auth_emp`：

- `RequestType.D2Auth + EncryptType.NoEncrypt`，避免被二次使用 D2Key 加密。
- 请求体为 `BE32(A2.Length) || A2 || QQ_TEA_Encrypt(auth.AuthRequest, A2Key)`。
- 默认 `appid=1112386029`、`pf=openmobile_android`、`sdkp=android`、`sdkv=1.5.9`。
- 解析 `auth.AuthResponse` 的字段 1 `ret`、字段 2 `msg`、字段 4 `code`。
- 可用 `FARM_PACKAGE_NAME`、`FARM_CERT_MD5`、`FARM_OPENAPI`、`FARM_APPID` 调整应用签名和权限列表。
- 未登录时 `/api/farm-code` 会拒绝请求；真实 `ret/msg/code` 以腾讯响应为准，不预置假 Code。

## 官方小程序旧接口状态（已停用）

2026-11-26 实测：`GetLoginCode` 虽仍返回标识，但 `QueryLoginCode` 和 `LoginCode` 均返回 `code:-4 / 命令字不存在`，旧扫码链已被服务端下线。PoC 已 fail-closed，不再生成无效二维码。

## 启动

```bash
export PAD_TOKEN='replace-with-random-token'
export PAD_SIGN_URL='http://172.17.0.1:8081'
export PAD_SIGN_STYLE=''
docker compose up -d --build
```

页面：`http://HOST:3009/?token=...`

未携带或输错页面令牌时，根路径会显示“AndroidPad 登录页访问验证”表单，不再只返回 JSON `unauthorized`。输入令牌后进入 QQ 登录页；API 仍保持 401 保护。

## HTTP 接口

除 `/health` 外均需 `x-admin-token: PAD_TOKEN` 或 `?token=...`：

- `GET /api/status`：Pad 状态，不返回密码或签名地址；`errors` 仅保留最近 20 条 Warning/Error/Critical 日志，用于定位腾讯登录失败。
- `POST /api/login`：`{uin,password}` 启动 Pad 登录。
- `POST /api/farm-code`：调用 `QQConnectLogin.auth_emp`，返回真实 `ret/message/code`。
- `GET /qr.png`：兼容 QR 流程二维码（如产生）。
- `POST /captcha`、`POST /sms`：登录验证。
