# AndroidPad 部署验收状态

更新时间：2026-11-26 18:05（Asia/Shanghai）

## 已部署

- 整合页面：`http://192.168.100.121:3009/`（访问令牌见本地凭据文件）。
- 协议：AndroidPad 9.3.65，版本专属 QUA、revision、SubAppId 和 SDK 字段。
- 签名：用户明确选择后使用公共 sign/energy；TLV553 由服务器本地服务生成。
- 原生产面板：`http://192.168.100.121:3008`。
- Pad、签名、NapCat 使用独立服务、端口和数据卷；NapCat 保持 `healthy`。

## 真实账号已通过

1. 密码首登经过图形验证和短信验证后达到 `phase=online`。
2. `hasSavedSession=true`、A2 已保存，且密码没有写入 keystore。
3. 重启 Pad 容器后未再次输入密码，自动恢复到 `online`，`hasSavedSession=true`。
4. 失败后保留 Guid/AndroidId，避免每次以新设备触发 237：
   - `DEVICE_ONLY_PERSIST=PASS`
   - `DEVICE_RESTART_REUSE=PASS`
5. `FARM_AUTH_ROUNDTRIP=PASS`，emp 与 plain 的请求/响应离线回环均通过。

## 农场 Code 的真实服务端结果

### `QQConnectLogin.auth_emp`

- A2 长度前缀和 A2Key TEA 请求构造与官方 `asbp.java` 对照一致。
- `NoEncrypt` 能收到同命令响应，但应用层 `Data` 长度为 0，没有 ret/msg/code。
- `EncryptEmpty` 和 `EncryptD2Key` 两种外层均未得到应用层响应。
- 补齐 `state`、`app_type=2`、包名和签名 MD5 后仍未得到可用 Code。

### `QQConnectLogin.auth`

- 请求为官方非 emp 的明文 AuthRequest，外层 D2Key。
- 腾讯真实响应：`ret=110401`，`message=请求的应用不存在`。
- 补齐 `app_unique_identifier=com.tencent.mobileqq` 和官方签名 MD5 后结果相同。
- 因此 plain `auth` 不能直接替代农场小程序取码。

## 关键结论

现有生产项目的农场取码并不是简单调用 `QQConnectLogin.auth_emp`。其实现通过 `start_mini_app_1112386029` 调用 QQ 原生 `MiniAppService`，再使用 `getOpenCodeWithReq` / `loginWithMiniApp` 等内部能力取得 Code。当前 Lagrange 自定义 `auth_emp` 与该原生小程序流程并不等价，不能将空包或 plain 110401 冒充 Code 成功。

## 可用替代路径

- 保留现有 3008 的 NapCat `start_mini_app_1112386029` 取码路径；Pad 登录链路不与它共享账号数据。
- 如需在 Pad 内完整替代，下一步应实现 MiniAppService 的启动、授权和 OpenCode 回调链，而不是继续盲改 TEA 或 SSO 加密类型。

## 仍需人工确认

- Windows QQ 是否在本次 AndroidPad online 后继续保持在线。
- 是否继续投入 MiniAppService/OpenCode 的 Pad 原生协议复刻；当前 Pad 的 auth/auth_emp 没有取得农场 Code。
