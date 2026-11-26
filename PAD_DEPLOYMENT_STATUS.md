# AndroidPad 部署验收状态

更新时间：2026-11-26 14:10（Asia/Shanghai）

## 已部署

- Pad 页面：`http://192.168.100.121:3009/`（访问令牌见本地凭据文件）
- 签名服务：`qq-farm-qsign.service`，监听 `8081`
- 原生产面板：`http://192.168.100.121:3008`
- Pad 与 NapCat 使用不同容器、端口和数据卷。

## 已通过

1. Android 9.2.20 签名原生库哈希校验通过。
2. 服务器原生签名实测：
   - `/energy`：`code=0`，184 HEX。
   - `/get_tlv553`：`code=0`，300 HEX。
   - `/sign`：`code=0`，sign/token/extra 均生成。
3. Pad 容器到签名服务网络连接通过。
4. 本地 `FARM_AUTH_ROUNDTRIP=PASS`。
5. 服务器部署镜像内 `DEPLOYED_FARM_AUTH_ROUNDTRIP=PASS`。
6. QQ TEA 使用 Lagrange 内置实现，启动自检通过。
7. 原 NapCat 容器保持 `healthy`。

## 当前真实状态

```json
{
  "phase": "needs_password",
  "signConfigured": true,
  "hasSavedSession": false
}
```

## 尚未完成

- 真实 QQ 账号 AndroidPad 首登。
- 腾讯在线返回的 `auth_emp ret/msg/code` 验收。
- 真实 keystore 重启恢复。
- Windows QQ 与 AndroidPad 同时在线观察。
- 农场 Code 接入现有面板自动续期。

当前唯一需要用户操作的是：在 `3009` 页面输入 QQ 号和密码并点击“开始 Pad 登录”。不能从 NapCat 的二维码登录态反推出 QQ 密码，也不能伪造真实在线验收。
