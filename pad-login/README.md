# AndroidPad 登录与农场 Code 隔离验证

独立进程、独立端口、独立数据卷，不读取或修改现有 NapCat 容器和账号数据。

## 已验证

- `Lagrange.Core 2.1.3` / .NET 8 编译通过。
- AndroidPad 9.3.65 真实账号登录、短信验证和 keystore 重启免密恢复通过，Windows QQ 可共存。
- 公共 sign/energy（用户明确选择）和本地 TLV553 路由可用。
- QQ TEA 通过 Lagrange 内置实现的 Span 委托调用，启动自检通过。
- HTTP 鉴权、健康检查、Pad 到签名服务的容器网络连接通过。
- `FARM_AUTH_ROUNDTRIP=PASS`：MiniApp GetCode 与旧 auth/auth_emp 诊断服务均通过离线回环测试（`PAD_SELF_TEST=1`）。
- `LightAppSvc.mini_program_auth.GetCode` 真实账号连续两次返回 `ret=0` 和非空 32 位 Code。

## AndroidPad 首登

当前 Lagrange V2 的 `WtExchangeLogic.ManualLogin` 拒绝 Android 空密码 QR 登录，`TransEmpService` 也只给 PC/AndroidWatch 注册 QR 服务。因此 AndroidPad 首次登录需要 QQ 号和密码；成功后保存 keystore，后续可免密恢复。

密码只随本次请求进入内存，不写入 keystore 或状态接口。keystore 本身属于敏感登录凭据，应保护数据卷。为降低新设备风控，失败时也会保留 Guid/AndroidId 等设备字段；只有 A2 非空才计为可恢复的登录会话，`hasDevice` 与 `hasSavedSession` 分开显示。

## 农场 Code 自定义服务

默认 `FarmCodeService.cs` 注册 `LightAppSvc.mini_program_auth.GetCode`：

- `RequestType.Simple + EncryptType.EncryptD2Key`。
- 外层 `StQWebReq`：字段 1 `Seq`、字段 2 `qua`、字段 3 `deviceInfo`、字段 4 `busiBuff`、字段 5 `traceid`。
- `busiBuff` 内是 `StGetCodeReq`，字段 1 为农场 AppID `1112386029`。
- 解析 `StQWebRsp` 的字段 2 `retCode`、字段 3 `errMsg`、字段 4 `busiBuff`，再从内层 `StGetCodeRsp` 字段 2 取 Code。
- `FARM_AUTH_MODE=miniapp` 为默认；`emp` 和 `plain` 仅保留为历史诊断路径。
- 未登录时 `/api/farm-code` 会拒绝请求；真实 `ret/message/code` 以腾讯响应为准，不预置假 Code。

`QQConnectLogin.auth_emp` 实测为空应用包，`QQConnectLogin.auth` 实测 `110401 请求的应用不存在`，二者均不是农场取码默认路径。

## 官方小程序旧接口状态（已停用）

2026-11-26 实测：`GetLoginCode` 虽仍返回标识，但 `QueryLoginCode` 和 `LoginCode` 均返回 `code:-4 / 命令字不存在`，旧扫码链已被服务端下线。PoC 已 fail-closed，不再生成无效二维码。

## 启动

```bash
export PAD_TOKEN='replace-with-random-token'
export PAD_SIGN_URL='https://sign.qsign.icu'  # 需用户明确选择公共签名
export PAD_SIGN_STYLE='remix'
export PAD_LOCAL_XWID_URL='http://172.17.0.1:8082'
docker compose up -d --build
```

页面：`http://HOST:3009/?token=...`

未携带或输错页面令牌时，根路径会显示“AndroidPad 登录页访问验证”表单，不再只返回 JSON `unauthorized`。输入令牌后进入 QQ 登录页；API 仍保持 401 保护。

## HTTP 接口

除 `/health` 外均需 `x-admin-token: PAD_TOKEN` 或 `?token=...`：

- `GET /api/status`：Pad 状态，不返回密码或签名地址；`errors` 仅保留最近 20 条 Warning/Error/Critical 日志，用于定位腾讯登录失败。
- `POST /api/login`：`{uin,password}` 启动 Pad 登录。
- `POST /api/farm-code`：默认调用 `LightAppSvc.mini_program_auth.GetCode`，返回真实 `ret/message/code`。
- `GET /qr.png`：兼容 QR 流程二维码（如产生）。
- `POST /captcha`、`POST /sms`：登录验证。
