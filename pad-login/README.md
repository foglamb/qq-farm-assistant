# AndroidPad 与官方小程序取码隔离 PoC

独立进程、独立端口、独立数据卷，不读取或修改现有 NapCat 容器和账号数据。

## 已验证

- `Lagrange.Core 2.1.3` / .NET 8 编译通过。
- Android 签名客户端实现 `/sign`、`/energy`、`/get_tlv553`，使用 AndroidPad 9.2.20 / `11650` 对应字段。
- 官方小程序 `GetLoginCode`、`QueryLoginCode` 实测可用，二维码 SVG 生成通过。
- HTTP 鉴权、健康检查、Pad 配置状态和官方二维码创建通过。

## AndroidPad 的真实限制

1. Lagrange 只提供签名 HTTP 客户端，不包含签名服务端。必须自行提供兼容 Android 9.2.20 的 `PAD_SIGN_URL`。
2. 当前 V2 的 `WtExchangeLogic.ManualLogin` 明确拒绝 Android 空密码 QR 登录，`TransEmpService` 也只给 PC/AndroidWatch 注册 QR 服务。因此 AndroidPad 首次登录需要 QQ 号和密码，成功后再用 keystore 免密恢复。
3. `QQConnectLogin.pre_auth_emp/auth_emp` 不是简单明文 `loginWithAppId`。公开客户端源码还经过 `OpenSdkVirtualUtil` 对请求进行账号相关处理，不能把未验证的 Proto 当成可用 Code 实现。本 PoC 尚未声称 Pad 原生取码成功。

## 官方小程序旧接口状态（已停用）

2026-11-26 实测：`GetLoginCode` 虽仍返回标识，但 `QueryLoginCode` 和 `LoginCode` 均返回 `code:-4 / 命令字不存在`，旧扫码链已被服务端下线。PoC 已改为 fail-closed，不再生成无效二维码。主面板 3008 的 QQ 原生扫码不受此旧接口影响。

## 启动

```bash
export PAD_TOKEN='replace-with-random-token'
export PAD_SIGN_URL=''  # 仅官方小程序取码时留空
docker compose up -d --build
```

页面：`http://HOST:3009/?token=...`

配置 AndroidPad 时，将 `PAD_SIGN_URL` 设为签名服务基址，例如 `http://127.0.0.1:8081`，不要包含 `/sign` 后缀。首次在页面输入 QQ 号和密码；密码只随本次请求进入内存，不写入 keystore 或状态接口。keystore 本身属于敏感登录凭据，应保护数据卷。

## HTTP 接口

除 `/health` 外均需 `x-admin-token: PAD_TOKEN` 或 `?token=...`：

- `GET /api/status`：Pad 状态，不返回密码或签名地址。
- `POST /api/login`：`{uin,password}` 启动 Pad 登录。
- `GET /qr.png`：Pad/兼容 QR 流程二维码（如产生）。
- `POST /captcha`、`POST /sms`：登录验证。
- `POST /api/official/sessions`：创建官方小程序二维码。
- `GET /api/official/sessions/:id`：扫码状态、uin 和成功后的 Code。
- `GET /official-qr.svg?id=...`：官方二维码 SVG。
