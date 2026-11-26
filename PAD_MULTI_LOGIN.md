# 四渠道账号登录

添加账号页面提供四个独立顶级标签：

- **手动填码**：保留原 QQ/微信小程序 Code 输入和保存逻辑。
- **AndroidPad 账密**：使用 QQ 账号密码登录，支持真实腾讯滑块、短信验证、keystore 免密恢复和 MiniApp GetCode，可与 Windows QQ 共存。
- **NapCat 扫码**：支持 UI 显示账号数量、连续扫码多个账号、原代理配置和原有恢复逻辑。
- **YYB 协议登录**：复用项目已有 yyb-go 的微信扫码、授权确认、账号导入和真实取码链；服务开关与数据卷保持原设计。

## 用户侧功能

- “QQ Pad / NapCat 登录”弹窗显示当前用户已添加的农场账号数量。
- NapCat 可连续扫码多个账号，每个会话拥有独立目录、身份校验和 Code。
- 每个账号记录 `qqLoginProtocol`，后续按需取码仍使用原协议，旧账号行为不变。
- Pad 密码登录遇到腾讯风控时，可打开真实 TencentCaptcha 滑块并提交 ticket/randstr；原生 `BotSMSEvent` 会显示验证手机并打开短信码输入框。
- 多账号默认复用 `PAD_DEVICE_PROFILE` 中的纯设备身份，减少新设备 237 风控；文件只含 Guid/AndroidId/Qimei/DeviceName，不含 Uin、密码或任何 WLoginSigs 票据。
- 已有 Pad 会话的账号可留空密码，通过 `restore:true` 恢复；新 Pad 账号必须输入 QQ 号和密码。
- 验证提交后等待腾讯返回最终状态，不把“已提交”显示成“已登录”。
- 当前 Pad 使用直连；NapCat 保留原代理配置。

## 生命周期

原 `QqLoginService` 继续统一负责：

1. 面板会话归属和过期清理。
2. 多账号 QQ 身份核验，拒绝把扫码账号导入其他账号。
3. `qq-data` 资料目录与 `identity.json` 所有权校验。
4. 账号数量限制、重复账号检测和 worker 启动。
5. `QQFARM_LOGIN` Code 消费、续期与敏感日志隔离。

Pad 只替换底层登录宿主：主镜像内置 `/app/pad-login/PadLogin`，由 Node 以 JSON-lines 子进程启动，不需要额外 HTTP 端口，也不需要 NapCat 运行。

## 配置

主镜像包含自包含 PadLogin，无需在运行容器安装 .NET。源码部署先执行 `sh scripts/build-pad-login.sh`（需要 .NET 8 SDK，可用 `DOTNET=/path/to/dotnet` 指定），再执行 Docker 构建；`server-deploy.sh` 已自动完成这一步。这样部署服务器不需要拉取 .NET SDK 镜像。网络受限且已有运行镜像时，可先构建 `web/dist`，再设置 `DOCKERFILE=core/Dockerfile.runtime`，仅增量替换 Core、Web 和 PadLogin。使用 Pad 前必须配置签名：

```bash
PAD_SIGN_URL=http://HOST:8081
# 或用户明确选择公共签名后：
# PAD_SIGN_URL=https://sign.qsign.icu
# PAD_SIGN_STYLE=remix
# PAD_LOCAL_XWID_URL=http://HOST:8082
```

9.3.65 版本字段使用 `PAD_PT_VERSION`、`PAD_QUA`、`PAD_CURRENT_VERSION`、`PAD_SUB_APP_ID`、`PAD_APP_CLIENT_VERSION`、`PAD_SDK_BUILD_TIME`、`PAD_SDK_VERSION`、`PAD_MISC_BITMAP`、`PAD_SUB_SIG_MAP`、`PAD_MAIN_SIG_MAP` 配置；留空时使用 Lagrange 默认值。

Node 默认把共享设备文件放在 `core/data/qq-login/pad-device.json`，可用 `PAD_DEVICE_PROFILE` 改写路径。首个成功登录的账号会登记设备；已有会话仍优先使用自己的 keystore。

公共签名会接触 QQ 号、设备标识和签名请求数据，不发送明文 QQ 密码。选择公共签名前应明确接受该数据边界。

## API

原接口保持不变，新增字段和验证接口：

- `POST /api/qq-login/sessions`：接受 `protocol=pad|napcat`；Pad 新登录接受 `uin/password`，已有 Pad 账号接受 `targetAccountId` 和 `restore:true`。
- `GET /api/qq-login/sessions/:id`：增加 `protocol`、`verifyUrl`、`phone`。
- `POST /api/qq-login/sessions/:id/captcha`：提交真实 `ticket/randstr`。
- `POST /api/qq-login/sessions/:id/sms`：提交真实短信码。

Pad 不带密码且不带恢复身份时，服务返回明确的密码/NapCat 指引，不启动扫码宿主。密码只通过子进程 stdin 传递，不写入账号资料、HTTP 状态或日志。keystore 是登录凭据，必须保护数据卷。

## 验证边界

- Core 测试覆盖原 NapCat 行为、Pad 密码不落盘、恢复路由、逐会话验证码/短信路由和协议持久化。
- Web 使用 Vue 3 Composition API + TypeScript，并通过 `vue-tsc` 与生产构建。
- AndroidPad 密码登录、keystore 恢复、Windows QQ 共存和 MiniApp GetCode 已在真实账号上验证。
- 2026-11-26 对实验性 Watch/Pad QR 做了三轮真实手机验证：未签名、可信设备加签名、停止重复 Pad 后均在手机端出现“当前环境存在风险”。实验代码已移出交付分支，不作为可用功能宣称。
