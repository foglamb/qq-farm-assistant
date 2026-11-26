# AndroidPad TencentCaptcha 验证助手

用于 Lagrange AndroidPad 首登触发 `BotCaptchaEvent` 时，在不重启当前登录进程的情况下完成腾讯验证。

## 作用

- 从 3009 `/api/status` 读取 `verifyUrl` 中的 `aid/sid/uin/login_appid`。
- 直接加载腾讯 `TencentCaptcha`，捕获 `ticket/randstr`。
- 自动 POST 到当前 3009 `/captcha`，避免用户在浏览器开发者工具里手工找票据。
- 独立 3010 服务，不修改或重启 Pad/NapCat 容器。

## 配置

```bash
export PAD_TOKEN='replace-with-token'
export UPSTREAM='http://127.0.0.1:3009'
export PORT=3010
python3 server.py
```

页面：`http://HOST:3010/?token=...`

只有 `/health` 不需要令牌；状态、验证码和短信接口均要求同一个 `PAD_TOKEN`。服务不记录 ticket、randstr、短信码或 QQ 密码。
