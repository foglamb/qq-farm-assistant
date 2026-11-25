# QQ 按需续登定制方案

基线：`nkooe/qq-farm-assistant@897aa101f8d082459d7c977ba469cc8b62e61518`  
定制分支：`feature/ondemand-qq`

## 结论

按需续登在程序结构上可实现，当前工作区已经做出最小实现并通过离线契约测试：

1. 首次扫码后保存 `identity.json`、`qq-data` 等 QQ 登录资料。
2. 农场 Worker 启动或断线重连时，使用保存的资料启动 QQ/NapCat。
3. 通过 `loginWithAppId` 获取新的 QQ 农场 Code。
4. Code 成功返回后关闭对应 QQ/NapCat 进程，不删除登录资料。
5. 下次续登从同一目录重新启动并恢复。
6. 凭证被明确判定失效时仍要求重新扫码，不无限重试无效凭证。

Code 状态已进一步拆分：明确的绝对 TTL 才记为 `code_expired`；游戏握手 HTTP 400 记为 `code_rejected` 并重新取码；QQ 登录资料失效才要求重扫。1006、心跳超时和顶号不再等同于 Code 过期。详见 `CODE_LIFECYCLE.md`。

这降低的是**农场在线期间的 QQ/NapCat 常驻开销**，不是取码瞬间的峰值开销。QQ/NapCat 在取码时仍需运行。

## 启用与回滚

在 Compose 环境或 `.env` 中设置：

```dotenv
QQ_LOGIN_RESIDENT=0
```

然后按正常流程构建、启动并扫码。默认 `QQ_LOGIN_RESIDENT=1`，保持上游原有常驻模式。

需要立即回到原行为时：

```dotenv
QQ_LOGIN_RESIDENT=1
```

重建容器配置即可。切换模式不会主动删除 QQ 登录资料。

按需模式下账号健康面板显示“QQ 会话：按需待命”，避免把正常释放资源误报为“未启动”。

## 已执行的功能校验

测试运行真实 `host.mjs` 和修改后的 `QqLoginService`，仅把 QQ 私有原生模块替换成离线、确定性的模拟实现；没有连接 QQ、游戏服务器或生产面板。

覆盖内容：

- 按需模式不预热 QQ 进程。
- 第一次取码成功后 QQ 子进程退出。
- `identity.json` 和 `qq-data` 保留。
- 第二次续登重新启动子进程并恢复原目录。
- 两次取得不同模拟 Code，取码计数递增。
- 取码结束后 `accountSessions` 和跟踪进程清空。
- 默认常驻模式仍然复用同一进程，行为未被全局改变。
- 上游真实宿主 IPC、资料恢复测试通过。
- 启动恢复、手动启停意图和账号运行状态契约测试通过。

测试命令：

```bash
# 在仓库根目录；依赖需先安装到环境，或用 QQ_FARM_TEST_NODE_PATH 指定隔离依赖目录
sh scripts/test-ondemand.sh
```

当前验证记录：按需/常驻、Code 分类、NapCat 双版本补丁及同步契约 **131/131 通过**；全量后端 **727/727 通过**；Web 的 `vue-tsc -b` 和 Vite 生产构建通过。测试使用 Node.js 24.15.0。

**尚未验证：** 真实 Linux QQ 的扫码成功率、QQ 进程退出后登录资料的长期有效性、真实断线到游戏恢复的完整闭环、实际内存下降数值。离线测试不能替代这些实机验收。

## 与主仓库同步且不丢失定制

上游已经配置：

```text
upstream = https://github.com/nkooe/qq-farm-assistant.git
branch   = main
```

检查更新：

```bash
python3 scripts/upstream_sync.py
```

应用更新：

```bash
python3 scripts/upstream_sync.py --apply
```

同步脚本执行顺序：

1. 拉取 `upstream/main`。
2. 要求当前工作区干净且位于自己的功能分支。
3. 使用 `--no-ff --no-commit` 合并，禁止 fast-forward 绕过检查。
4. 运行按需续登、启动恢复和账号状态契约测试。
5. 测试通过才创建合并提交。
6. 冲突时保留冲突供人工解决，不覆盖任何一侧；可用 `git merge --abort` 放弃本次合并。
7. 测试失败时取消尚未提交的合并，保留此前的定制提交。
8. 不自动推送、不自动构建、不自动重启生产服务。

因此可以持续吸收上游更新，同时保留按需续登提交。**但不能承诺所有更新都绝无冲突或语义回归**；上游修改同一取码生命周期时必须人工审查。契约测试是保护网，不是绝对兼容保证。

## 生产验收顺序

1. 固定当前基线，独立目录、独立端口、独立数据卷试跑。
2. 使用一个测试 QQ 完成首次扫码。
3. 取码后检查 QQ/NapCat 进程退出，资料目录仍存在。
4. 重启农场 Worker，确认重新取码并进入游戏。
5. 重启整个容器，确认资料从数据卷恢复。
6. 主动触发一次断线，检查退避、重新取码和游戏恢复。
7. 记录取码前后实际内存；确认收益后再扩大账号数量。
8. 真实验收通过前不替换现有生产服务。

## 代码边界

主要改动：

- `core/src/services/qq-login-service.js`：开关、禁止预热、成功后释放进程、生命周期状态。
- `core/test/qq-ondemand.test.js`：按需与默认模式回归。
- `docker-compose.yml`：传递 `QQ_LOGIN_RESIDENT`。
- `web/src/components/AccountHealthPanel.vue`：按需待命显示。
- `scripts/test-ondemand.sh`、`scripts/upstream_sync.py`：回归与上游同步保护。

本仓库公开基线的许可证边界仍需单独核实；不要仅因源码公开就假定可随意再分发。
