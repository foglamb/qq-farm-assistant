# Android 9.2.20 签名服务兼容层

基于 `Linxiaoyaa/unidbg-fetch-qsign` 提交 `58091e6c8134afb9c60878d29656db2bc17b9151`（GPL-3.0，许可证见 `UPSTREAM_LICENSE`）。适配 Lagrange.Core 2.1.3 AndroidPad 的 JSON POST `/sign`、`/energy`、`/get_tlv553`。

## 已实测

- QQ 9.2.20 / versionCode 11650 的 `libfekit.so` 可由 unidbg 加载。
- 9.2.20 的 Dtn 初始化必须调用 `initContext(Context,String)` 和 `initLog(IFEKitLog)`，旧版 `initNativeContext` 会失败。
- `/energy`：184 HEX 字符。
- `/get_tlv553`：300 HEX 字符。
- `/sign`：sign 184、token 24、extra 354 HEX 字符。
- 服务器 `192.168.100.121:8081` 三端点再次实测全部 `code=0`。

这些是原生签名生成验证，不等于腾讯在线登录已经通过；在线风控和农场 Code 仍需真实账号验收。

## APK 与原生库证据

来源：腾讯官方签名 APK 的第三方历史存档：

- 页面：https://www.wandoujia.com/apps/566489/history_v11650
- APK MD5：`f6d68c44bc64d089ac066eb56efdd662`
- APK SHA256：`54930164077cd01ebc1677ac53c118ecf6dafdd646af2005edee41c3a4f9841d`
- APK 签名证书 MD5：`A6:B7:45:BF:24:A2:C2:77:52:77:16:F6:F3:6E:B6:8D`
- `libfekit.so` SHA256：`d8ea7376b5456c05e3ccfa98da1f870392afa63e6c2ffea45c9ef4f83c25fd82`

证书 MD5 与 Lagrange Android 9.2.20 `BotAppInfo.ApkSignatureMd5` 一致；APK 已通过 `jarsigner --verify`。

## 本地构建

需要 JDK 21、Git、curl、Python 3：

```bash
chmod +x build-local.sh
./build-local.sh
```

脚本会：

1. 固定上游提交并恢复被该提交删除的 `libs/unidbg-android.jar`。
2. 应用 `patches/` 中的 Lagrange API 和 9.2.20 JNI 兼容补丁。
3. 下载并校验 APK，只提取对应 `libfekit.so`，不把 APK 或 JAR 写入 Git。
4. 生成带随机密钥的 `txlib/9.2.20/config.json`。
5. 构建 `build/libs/unidbg-fetch-qsign-1.1.9-all.jar`。

## 启动

```bash
java \
  --add-opens=java.base/java.lang=ALL-UNNAMED \
  --add-opens=java.base/java.util=ALL-UNNAMED \
  --add-opens=java.base/java.nio=ALL-UNNAMED \
  --add-opens=java.base/sun.security.x509=ALL-UNNAMED \
  --add-opens=java.base/sun.nio.ch=ALL-UNNAMED \
  --add-exports=java.base/sun.security.x509=ALL-UNNAMED \
  -Djdk.attach.allowAttachSelf=true \
  -jar build/libs/unidbg-fetch-qsign-1.1.9-all.jar \
  --basePath=./txlib/9.2.20
```

PadLogin 使用标准 Lagrange JSON 模式：

```env
PAD_SIGN_URL=http://172.17.0.1:8081
PAD_SIGN_STYLE=
```

服务监听端口应与 `config.json` 的 `server.port` 一致。生产环境不要把签名端口暴露到公网。
