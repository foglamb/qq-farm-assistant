# AndroidPad 部署验收状态

更新时间：2026-11-26 18:20（Asia/Shanghai）

## 当前真实状态：全部核心链路可用

- 整合页面：`http://192.168.100.121:3009/`（访问令牌见本地凭据文件）。
- AndroidPad 9.3.65：`phase=online`、`hasSavedSession=true`、`hasDevice=true`。
- 用户已确认 Windows QQ 与 AndroidPad 同时在线。
- 农场真实命令：`LightAppSvc.mini_program_auth.GetCode`。
- 连续两次真实账号取码均返回 `ret=0`，Code 非空、长度 32；未在日志或文档输出 Code。
- 原 NapCat `qq-farm-ondemand` 保持 `healthy`，账号、容器和数据卷未修改。

## 登录与恢复证据

1. 密码首登经过图形验证和短信验证后达到 `online`。
2. A2 已保存，密码未写入 keystore。
3. 重启 Pad 容器后无需密码，自动恢复 `online`。
4. 失败后保留 Guid/AndroidId，避免反复触发新设备 237：
   - `DEVICE_ONLY_PERSIST=PASS`
   - `DEVICE_RESTART_REUSE=PASS`
5. `FARM_AUTH_ROUNDTRIP=PASS`，MiniApp GetCode 与历史 auth/auth_emp 诊断服务均通过离线回环。

## 最终农场 Code 协议

`FarmCodeService.cs` 实现：

- `RequestType.Simple + EncryptType.EncryptD2Key`。
- 外层 `StQWebReq`：
  - 字段 1：`Seq`
  - 字段 2：`qua`
  - 字段 3：`deviceInfo`
  - 字段 4：`busiBuff`
  - 字段 5：`traceid`
- `busiBuff` 为 `StGetCodeReq{appid="1112386029"}`。
- 响应先解析 `StQWebRsp{retCode=2,errMsg=3,busiBuff=4}`，再解析内层 `StGetCodeRsp{code=2}`。
- 默认 `FARM_AUTH_MODE=miniapp`。

真实验收：

```json
{"ok":true,"ret":0,"codePresent":true,"codeLength":32}
{"ok":true,"ret":0,"codePresent":true,"codeLength":32}
```

## 历史错误路径证据

- `QQConnectLogin.auth_emp + NoEncrypt`：同命令响应的 `Data` 长度为 0。
- `QQConnectLogin.auth_emp + EncryptEmpty/EncryptD2Key`：未得到应用层响应。
- `QQConnectLogin.auth + D2Key`：`ret=110401 / 请求的应用不存在`；补包名和签名后仍相同。
- 这些诊断服务保留用于对照，但不是默认取码路径。

## 签名路由

用户明确选择后，公共 `sign.qsign.icu` 提供 sign/energy；服务器本地 8082 提供 TLV553。公共端会接触 QQ 号、设备标识和签名请求数据，不发送明文密码。当前 Pad 页面不暴露签名地址。

## 后续工程项

- 将 3009 的 Pad GetCode 能力接入现有 3008 自动续期调度，替代 NapCat 临时登录取码。
- 已部署的 3009 页面现在即可手动取码和复制；自动接入前不改变原 3008 行为。
