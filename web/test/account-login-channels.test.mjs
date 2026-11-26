import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../src/components')
const modal = fs.readFileSync(path.join(root, 'AccountModal.vue'), 'utf8')
const qq = fs.readFileSync(path.join(root, 'QqScanLogin.vue'), 'utf8')

test('add-account exposes four independent login channels', () => {
  for (const label of ['手动填码', 'Pad 账密', 'NapCat 扫码', 'YYB 协议登录']) assert(modal.includes(label), label)
  assert(modal.includes("type AccountTab = 'manual' | 'pad' | 'napcat' | 'yyb'"))
  assert(modal.includes(':initial-protocol="activeTab"'))
  assert(!modal.includes('QQ Pad / NapCat 登录'))
})

test('Pad and NapCat keep their real login modes and YYB keeps its real API chain', () => {
  assert(qq.includes("props.account?.qqLoginProtocol || props.initialProtocol || 'napcat'"))
  assert(qq.includes("loginMode.value = protocol.value === 'pad' ? 'password' : 'qr'"))
  assert(qq.includes("protocol.value === 'napcat' ? '正在生成 QQ 二维码…' : '正在启动 AndroidPad 登录…'"))
  assert(qq.includes('if (props.account) await start()'))
  assert(qq.includes("stage !== 'success' && protocol === 'napcat'"))
  for (const endpoint of ['/api/yyb/qr/create', '/api/yyb/qr/poll', '/api/yyb/qr/confirm', '/api/yyb/getcode']) assert(modal.includes(endpoint), endpoint)
})
