# QQ 农场 Code 生命周期与错误分类

## 状态定义

| 状态 | 触发条件 | 含义 | 后续动作 |
| --- | --- | --- | --- |
| `code_expired` | QQ 原生授权返回明确的绝对 `expiresAt/expireAt/expireTime`，且当前时间已到 | 有元数据证明的时间过期 | 重新取码 |
| `code_rejected` | 游戏 WebSocket 握手返回 HTTP 400 | 本次登录凭据被服务器拒绝 | 退避并重新取码；不直接要求扫码 |
| `rescan_required` | QQ 登录资料缺失、身份变化或原生会话明确要求重新验证 | QQ 登录态不可用，不是单纯农场 Code 问题 | 停止无效重试并重新扫码 |
| 无分类 | 1006、心跳超时、普通网络错误、Kickout | 连接或账号会话事件 | 按网络/顶号流程处理，不能叫 Code 过期 |

HTTP 400 不能进一步区分时间到期、已消费、撤销或异地登录。因此代码和日志使用 `code_rejected`，不再笼统写成“Code 过期”。

## TTL 处理

`core/qq-login/qq-native-login.mjs` 只接受绝对时间戳：

- 秒级时间戳转换为毫秒。
- 毫秒时间戳保持不变。
- 小于 `1e9` 的值被视为时长或非法值，不作为绝对到期时间。
- 非数字、零、负数和无穷值忽略。
- 没有明确 TTL 时返回 `null`，不编造过期时间。

登录服务只在 `code-meta.json` 保存 `issuedAt`、`expiresAt` 和状态，**不写入 Code 明文**。状态中的 `code_expired` 只在明确 TTL 已到时出现。

## 握手拒绝处理

`worker-manager.js` 对 HTTP 400：

1. 记录 `code_rejected` 和状态码。
2. 进入原有退避重连。
3. 启动前重新取 Code。
4. 连接成功后清除拒绝状态。
5. 不因为 400 删除 QQ 登录资料。

1006、心跳超时和 Kickout 不进入 `code_rejected`。

## 一次性与复用边界

不同旧版实现对 QQ Code 是否可复用存在差异：旧版当前路径避免重放，其他项目保留 savedCode 重连。二改方案采取保守策略：每次建立新游戏会话前重新取 Code，不依赖旧 Code 是否仍可复用。

## 离线验证

- `code-lifecycle.test.js`：明确 TTL 才判过期，HTTP 400 判拒绝，1006 等不误判。
- `qq-native-login.test.js`：秒/毫秒 TTL、非法时长及无 TTL。
- `qq-ondemand.test.js`：按需释放、资料恢复、元数据保存且不含 Code。
- `worker-manager-yyb-start.test.js`：400 记录 `code_rejected`，自动刷新，连接成功清除。

未连接真实 QQ 或游戏服务器；真实服务端返回的 TTL 字段及 HTTP 400 细分原因仍需实机确认。
