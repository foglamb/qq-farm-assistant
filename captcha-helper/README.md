# AndroidPad 3009 整合登录中心

`server.py` 在 3009 提供统一的响应式页面和同源 API 代理，覆盖 QQ 密码首登、TencentCaptcha、短信码、状态展示和农场 Code 获取。页面不再跳到 3010，也不显示已失效的官方小程序入口。

## 当前部署结构

- 用户只访问 `http://192.168.100.121:3009/`。
- `qq-farm-pad-web.service` 提供整合页面。
- API 转发到运行中的 `qq-farm-pad-login` 容器私网地址 `172.17.0.5:8080`。
- `claim-port.py` 只停止 3009 的 Docker userland proxy，并删除对应的旧 Docker DNAT；不会停止或重启 Pad 容器。
- 原 NapCat、签名服务和 Pad 登录进程保持运行。

此结构用于在不中断待验证码登录会话的情况下替换页面。真实在线验收完成后，也可以把整合页面直接编回 PadLogin，再恢复单一进程。

## 配置

```bash
export PAD_TOKEN='replace-with-token'
export UPSTREAM='http://172.17.0.5:8080'
export PORT=3009
python3 server.py
```

页面：`http://HOST:3009/?token=...`

只有 `/health` 不需要令牌；其他页面和 API 均要求同一个 `PAD_TOKEN`。服务不记录 ticket、randstr、短信码或 QQ 密码。

## 回滚

如需恢复 Docker 原始端口映射，先停止 `qq-farm-pad-web`，再重启 `qq-farm-pad-login` 让 Docker 重建 proxy/NAT。该回滚会重启 Pad 进程，等待验证码时不要执行。
