<script setup lang="ts">
import type { Account } from '@/stores/account'
import { useAccountStore } from '@/stores/account'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import api from '@/api'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/ui/BaseInput.vue'

const props = defineProps<{ account?: Account, initialProtocol?: 'pad' | 'napcat' | 'watch' }>()
const accountStore = useAccountStore()
const protocol = ref<'pad' | 'napcat' | 'watch'>(props.account?.qqLoginProtocol || props.initialProtocol || 'napcat')
const loginMode = ref<'qr' | 'password'>((props.account?.qqLoginProtocol || props.initialProtocol) === 'pad' ? 'password' : 'qr')
const PROTOCOL_LABELS: Record<string, string> = { pad: 'AndroidPad', napcat: 'NapCat', watch: '手表协议' }
const protocolLabel = computed(() => PROTOCOL_LABELS[protocol.value] || 'NapCat')
const loginUin = ref(props.account ? String(props.account.uin || props.account.qq || '') : '')
const loginPassword = ref('')
const verifyUrl = ref('')
const verifyPhone = ref('')
const verificationBusy = ref(false)
const smsCode = ref('')
const accountCount = computed(() => accountStore.accounts.length)
const emit = defineEmits<{ saved: [accountId: string], close: [], saving: [value: boolean] }>()
const accountName = ref('')
const image = ref('')
const stage = ref((props.account?.qqLoginProtocol || props.initialProtocol) === 'pad' && !props.account ? 'idle' : 'starting')
const message = ref((props.account?.qqLoginProtocol || props.initialProtocol) === 'pad' && !props.account ? '请输入 QQ 账号密码后开始登录' : '正在生成 QQ 二维码…')
const error = ref('')
const sessionId = ref('')
const currentCode = ref('')
const saving = ref(false)
const saved = ref(false)
const proxyProfiles = ref<Array<{ id: number, name: string }>>([])
const proxySelection = ref(props.account?.proxyMode === 'static' ? String(props.account.proxyProfileId || '') : 'direct')
const proxyReady = ref(false)
const records = ref<Array<{ code: string, time: string, copied: boolean }>>([])
let generation = 0
let stopped = false
let controller: AbortController | null = null
let delayTimer: ReturnType<typeof setTimeout> | null = null
let releaseDelay: (() => void) | null = null
const busy = computed(() => ['starting', 'scanned', 'initializing', 'requesting', 'verifying'].includes(stage.value) || saving.value || verificationBusy.value)
const newestCode = computed(() => currentCode.value)
watch(saving, value => emit('saving', value))

const requestOptions = { timeout: 12000, skipErrorToast: true } as any
function requestError(value: any, fallback: string) {
  return String(value?.response?.data?.error || fallback)
}
async function cancelSession(id: string) {
  if (!id)
    return
  try {
    await api.delete(`/api/qq-login/sessions/${encodeURIComponent(id)}`, requestOptions)
  }
  catch { /* Server expires abandoned sessions independently. */ }
}
function stopWaiting() {
  controller?.abort()
  controller = null
  if (delayTimer)
    clearTimeout(delayTimer)
  delayTimer = null
  releaseDelay?.()
  releaseDelay = null
}
async function pause() {
  await new Promise<void>((resolve) => {
    releaseDelay = resolve
    delayTimer = setTimeout(resolve, 1200)
  })
  delayTimer = null
  releaseDelay = null
}

async function saveCode(version = generation) {
  if (saving.value || !newestCode.value || saved.value)
    return
  saving.value = true
  error.value = ''
  message.value = '正在保存账号…'
  try {
    const { data } = await api.post(`/api/qq-login/sessions/${encodeURIComponent(sessionId.value)}/import`, {
      name: accountName.value.trim(),
      ...(props.account ? { targetAccountId: String(props.account.id) } : {}),
    }, { ...requestOptions, timeout: 100000 })
    if (data?.ok !== true)
      throw new Error(data?.error || '账号保存失败')
    if (stopped || version !== generation)
      return
    saved.value = true
    stage.value = 'success'
    message.value = data.data?.updated
      ? '已更新原账号，正在连接'
      : '账号已添加，正在连接'
    const finalCode = String(data.data?.code || newestCode.value)
    if (finalCode !== newestCode.value) {
      // The identity check can consume the initial credential. Display only
      // the fresh Code actually stored for this login.
      const record = records.value.find(item => item.code === newestCode.value)
      if (record) {
        record.code = finalCode
        record.copied = false
      }
      currentCode.value = finalCode
    }
    emit('saved', String(data.data?.accountId || ''))
    await cancelSession(sessionId.value)
    sessionId.value = ''
  }
  catch (value: any) {
    if (stopped || version !== generation)
      return
    error.value = requestError(value, '保存未确认，请检查账号列表')
    message.value = '待确认保存'
  }
  finally { saving.value = false }
}

async function poll(version: number, signal: AbortSignal) {
  let failures = 0
  for (;;) {
    if (stopped || version !== generation || signal.aborted || !sessionId.value)
      return
    try {
      const { data } = await api.get(`/api/qq-login/sessions/${encodeURIComponent(sessionId.value)}`, { ...requestOptions, signal })
      if (stopped || version !== generation || signal.aborted)
        return
      if (data?.ok !== true)
        throw new Error('无法读取 QQ 扫码状态')
      const state = data.data || {}
      failures = 0
      stage.value = String(state.status || 'starting')
      message.value = String(state.message || '正在等待扫码…')
      image.value = String(state.image || '')
      verifyUrl.value = String(state.verifyUrl || '')
      verifyPhone.value = String(state.phone || '')
      if (stage.value === 'success') {
        const code = String(state.code || '')
        if (!/^[\w.~+/=%-]{8,2048}$/.test(code) || /^[-+]?\d+$/.test(code)) {
          error.value = 'QQ 未返回有效 Code，请刷新二维码'
          stage.value = 'error'
          return
        }
        if (!records.value.some(item => item.code === code)) {
          records.value.unshift({ code, time: new Date().toLocaleTimeString(), copied: false })
          records.value = records.value.slice(0, 20)
        }
        currentCode.value = code
        await saveCode(version)
        return
      }
      if (['expired', 'error', 'login_failed', 'offline'].includes(stage.value)) {
        error.value = message.value
        return
      }
    }
    catch (value: any) {
      if (signal.aborted || stopped || version !== generation)
        return
      if ([404, 410].includes(value?.response?.status) || ++failures >= 4) {
        error.value = requestError(value, '查询 QQ 扫码状态失败，请刷新二维码')
        stage.value = 'error'
        return
      }
      message.value = '网络暂时中断，正在重新查询扫码状态…'
    }
    await pause()
  }
}

function changeProtocol() {
  loginMode.value = protocol.value === 'pad' ? 'password' : 'qr'
  void start()
}

async function start() {
  if ((protocol.value === 'napcat' && !proxyReady.value) || saving.value)
    return
  const restoringPad = protocol.value === 'pad' && props.account?.qqLoginProtocol === 'pad' && !loginPassword.value
  if (protocol.value === 'pad' && !restoringPad && (!loginUin.value.trim() || !loginPassword.value)) {
    stage.value = 'error'
    error.value = '新 Pad 账号请输入 QQ 号和密码；已有 Pad 会话可留空密码恢复'
    return
  }
  const version = ++generation
  stopWaiting()
  const previous = sessionId.value
  sessionId.value = ''
  image.value = ''
  currentCode.value = ''
  error.value = ''
  saved.value = false
  verifyUrl.value = ''
  verifyPhone.value = ''
  stage.value = 'starting'
  message.value = protocol.value === 'watch' ? '正在连接手表登录服务器…'
    : protocol.value === 'napcat' ? '正在生成 QQ 二维码…' : '正在启动 AndroidPad 登录…'
  const current = controller = new AbortController()
  await cancelSession(previous)
  try {
    // Do not abort creation: if the dialog closes during this request, its
    // eventual response still supplies the id needed to cancel the native host.
    const { data } = await api.post('/api/qq-login/sessions', {
      protocol: protocol.value,
      uin: loginUin.value.trim(),
      password: protocol.value === 'pad' && loginMode.value === 'password' ? loginPassword.value : '',
      restore: restoringPad,
      proxyMode: protocol.value === 'napcat' && proxySelection.value !== 'direct' ? 'static' : 'direct',
      proxyProfileId: protocol.value === 'napcat' && proxySelection.value !== 'direct' ? Number(proxySelection.value) : null,
      ...(props.account ? { targetAccountId: String(props.account.id) } : {}),
    }, { ...requestOptions, timeout: 25000 })
    loginPassword.value = ''
    const id = String(data?.data?.sessionId || '')
    if (stopped || version !== generation) {
      await cancelSession(id)
      return
    }
    if (data?.ok !== true || !id)
      throw new Error('未能创建 QQ 扫码会话')
    sessionId.value = id
    await poll(version, current.signal)
  }
  catch (value: any) {
    if (stopped || version !== generation)
      return
    stage.value = 'error'
    error.value = requestError(value, '生成 QQ 二维码失败，请检查扫码组件是否已启动')
  }
}

let captchaLoader: Promise<void> | null = null
function loadTencentCaptcha() {
  if ((window as any).TencentCaptcha)
    return Promise.resolve()
  if (!captchaLoader) {
    captchaLoader = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://captcha.gtimg.com/TCaptcha.js'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('腾讯验证码组件加载失败，请检查网络'))
      document.head.append(script)
    })
  }
  return captchaLoader
}
async function showCaptcha() {
  if (!verifyUrl.value || verificationBusy.value)
    return
  verificationBusy.value = true
  error.value = ''
  try {
    await loadTencentCaptcha()
    const query = new URLSearchParams(new URL(verifyUrl.value).search)
    const options = {
      type: 'full', showHeader: false, uin: query.get('uin') || '0', sid: query.get('sid') || '', enableAged: true,
      ...(query.get('login_appid') ? { login_appid: query.get('login_appid') } : {}),
    }
    const Captcha = (window as any).TencentCaptcha
    const captcha = new Captcha(query.get('aid') || '2081081773', async (result: any) => {
      if (result.ret !== 0) {
        error.value = String(result.info || '腾讯验证未完成')
        return
      }
      try {
        await api.post(`/api/qq-login/sessions/${encodeURIComponent(sessionId.value)}/captcha`, {
          ticket: result.ticket, randstr: result.randstr,
        }, requestOptions)
        stage.value = 'needs_sms'
        message.value = '滑块已提交；如腾讯已发送短信，请输入手机短信验证码完成登录'
      }
      catch (value: any) {
        error.value = requestError(value, '验证票据提交失败')
      }
    }, options)
    captcha.show()
  }
  catch (value: any) {
    error.value = String(value?.message || value || '无法打开腾讯验证码')
  }
  finally { verificationBusy.value = false }
}
async function submitSms() {
  if (!smsCode.value.trim() || verificationBusy.value)
    return
  verificationBusy.value = true
  error.value = ''
  try {
    await api.post(`/api/qq-login/sessions/${encodeURIComponent(sessionId.value)}/sms`, { code: smsCode.value.trim() }, requestOptions)
    smsCode.value = ''
    stage.value = 'verifying'
    message.value = '短信码已提交，正在等待登录结果…'
  }
  catch (value: any) {
    error.value = requestError(value, '短信码提交失败')
  }
  finally { verificationBusy.value = false }
}

async function copyRecord(record: { code: string, copied: boolean }) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(record.code)
    }
    else {
      const input = document.createElement('textarea')
      input.value = record.code
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.append(input)
      try {
        input.select()
        if (!document.execCommand('copy'))
          throw new Error('Copy failed')
      }
      finally { input.remove() }
    }
    record.copied = true
  }
  catch {
    error.value = '复制失败，请选中 Code 文本手动复制'
  }
}
async function loadProxyOptions() {
  proxyReady.value = false
  error.value = ''
  if (protocol.value === 'pad') {
    proxySelection.value = 'direct'
    proxyProfiles.value = []
    proxyReady.value = true
    if (props.account) await start()
    return
  }
  try {
    const { data } = await api.get('/api/yyb/proxy-profiles', requestOptions)
    if (stopped)
      return
    if (data?.ok !== true || !Array.isArray(data.data))
      throw new Error('代理配置读取失败')
    proxyProfiles.value = data.data
    if (proxySelection.value !== 'direct' && !proxyProfiles.value.some(profile => String(profile.id) === proxySelection.value))
      throw new Error('原账号的代理配置已不可用，请先修复该代理配置')
    proxyReady.value = true
    await start()
  }
  catch (value: any) {
    if (!stopped) {
      stage.value = 'error'
      error.value = requestError(value, value?.message || '代理配置读取失败，请重试')
      message.value = '等待读取代理配置'
    }
  }
}
onMounted(() => {
  void loadProxyOptions()
})
onBeforeUnmount(() => {
  stopped = true
  generation++
  stopWaiting()
  void cancelSession(sessionId.value)
})
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between rounded-lg px-3 py-2 text-sm" :style="{ background: 'color-mix(in srgb, var(--theme-primary) 10%, transparent)', color: 'var(--theme-text)' }">
      <span>已添加 <strong>{{ accountCount }}</strong> 个农场账号</span>
      <span>{{ protocolLabel }}</span>
    </div>
    <label v-if="!initialProtocol && !account" class="block text-sm" :style="{ color: 'var(--theme-text)' }">
      QQ 登录协议
      <select v-model="protocol" aria-label="QQ 登录协议" class="mt-1 block w-full border border-gray-300 rounded-lg p-2 dark:border-gray-600" :style="{ background: 'var(--theme-bg)', color: 'var(--theme-text)' }" :disabled="busy" @change="changeProtocol">
        <option value="napcat">NapCat（多账号扫码）</option>
        <option value="pad">AndroidPad（密码/恢复，可与 Windows QQ 共存）</option>
        <option value="watch">手表协议（扫码，无需签名服务）</option>
      </select>
    </label>
    <template v-if="protocol === 'pad'">
      <BaseInput v-model="loginUin" label="QQ 号" placeholder="输入 QQ 号" :disabled="busy" />
      <BaseInput v-model="loginPassword" label="QQ 密码" type="password" placeholder="只用于本次登录，不保存" :disabled="busy" />
    </template>
    <BaseInput v-if="!account" v-model="accountName" label="账号备注（可选）" placeholder="留空则使用默认账号名" :disabled="saving" />
    <label v-if="protocol === 'napcat'" class="block text-sm" :style="{ color: 'var(--theme-text)' }">
      连接方式
      <select v-model="proxySelection" aria-label="QQ 连接方式" class="mt-1 block w-full border border-gray-300 rounded-lg p-2 dark:border-gray-600" :style="{ background: 'var(--theme-bg)', color: 'var(--theme-text)' }" :disabled="!proxyReady || busy" @change="start">
        <option value="direct">直连</option>
        <option v-for="profile in proxyProfiles" :key="profile.id" :value="String(profile.id)">{{ profile.name }}</option>
      </select>
    </label>
    <p v-if="!saved" class="text-sm opacity-70" :style="{ color: 'var(--theme-text)' }">
      <template v-if="protocol === 'pad' && loginMode === 'password'">
        新账号使用密码登录；腾讯要求时会显示真实滑块或短信验证。已有 Pad 会话可留空密码直接恢复。
      </template>
      <template v-else-if="account">
        请用原 QQ 扫码。
      </template>
      <template v-else>
        请用手机 QQ 扫码。
      </template>
    </p>
    <div v-if="image && !saved" class="mx-auto max-w-60 w-full border border-gray-200 rounded-lg bg-white p-3">
      <img :src="image" alt="QQ 登录二维码" class="aspect-square w-full object-contain" width="224" height="224">
    </div>
    <div v-else-if="!saved && stage !== 'success' && protocol !== 'pad'" class="mx-auto aspect-square max-w-60 w-full flex items-center justify-center rounded-lg bg-gray-100 dark:bg-gray-800">
      <span class="text-5xl" :class="busy ? 'i-svg-spinners-ring-resize animate-spin' : 'i-carbon-qr-code'" :style="{ color: 'var(--theme-primary)' }" />
    </div>
    <div role="status" class="rounded-lg px-3 py-3 text-center text-sm leading-6" :style="{ color: 'var(--theme-text)', background: 'color-mix(in srgb, var(--theme-primary) 10%, transparent)' }">
      {{ message }}
    </div>
    <div v-if="!saved && (verifyUrl || ['needs_captcha', 'needs_device_verify', 'needs_sms'].includes(stage) || (protocol === 'pad' && stage === 'verifying'))" class="space-y-3 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
      <div class="text-sm font-medium" :style="{ color: 'var(--theme-text)' }">{{ stage === 'needs_sms' ? '手机短信验证码' : '腾讯安全验证' }}</div>
      <p v-if="verifyPhone" class="text-xs opacity-70" :style="{ color: 'var(--theme-text)' }">验证手机：{{ verifyPhone }}</p>
      <p v-if="stage === 'needs_sms'" class="text-xs opacity-70" :style="{ color: 'var(--theme-text)' }">滑块已提交。腾讯发送短信后，将收到的验证码填入下方并完成登录。</p>
      <a v-if="verifyUrl" :href="verifyUrl" target="_blank" rel="noopener" class="block break-all text-xs text-blue-500">{{ verifyUrl }}</a>
      <BaseButton v-if="verifyUrl" variant="primary" :loading="verificationBusy" @click="showCaptcha">开始腾讯滑块验证</BaseButton>
      <label class="block text-sm" :style="{ color: 'var(--theme-text)' }">
        手机验证码
        <div class="mt-1 flex flex-wrap gap-2">
          <input v-model="smsCode" aria-label="手机短信验证码" inputmode="numeric" autocomplete="one-time-code" maxlength="8" class="min-w-0 flex-1 border border-gray-300 rounded-lg p-2 dark:border-gray-600" :style="{ background: 'var(--theme-bg)', color: 'var(--theme-text)' }" placeholder="输入收到的短信验证码">
          <BaseButton variant="outline" :disabled="!smsCode.trim() || verificationBusy" @click="submitSms">提交手机验证码</BaseButton>
        </div>
      </label>
    </div>
    <p v-if="error" role="alert" class="break-words text-sm text-red-600 dark:text-red-400">
      {{ error }}
    </p>
    <div v-if="records.length" class="space-y-2">
      <div v-for="record in records" :key="record.code" class="min-w-0 flex items-start gap-2 border border-gray-200 rounded-lg p-2 dark:border-gray-700">
        <div class="min-w-0 flex-1">
          <div class="text-xs opacity-60" :style="{ color: 'var(--theme-text)' }">
            {{ record.time }}
          </div>
          <code class="select-all break-all text-xs" :style="{ color: 'var(--theme-text)' }">{{ record.code }}</code>
        </div>
        <BaseButton variant="outline" class="shrink-0" @click="copyRecord(record)">
          {{ record.copied ? '已复制' : '复制' }}
        </BaseButton>
      </div>
    </div>
    <div class="flex flex-wrap justify-end gap-2">
      <BaseButton variant="outline" :disabled="saving" @click="emit('close')">
        {{ saved ? '完成' : '取消' }}
      </BaseButton>
      <BaseButton v-if="newestCode && !saved" variant="primary" :loading="saving" @click="saveCode()">
        重试保存
      </BaseButton>
      <BaseButton v-if="!account || !saved" variant="primary" :disabled="saving" :loading="stage === 'starting'" @click="proxyReady ? start() : loadProxyOptions()">
        {{ !proxyReady ? '重试加载' : saved ? '再扫一个账号' : protocol === 'pad' && loginMode === 'password' ? '开始登录' : '刷新二维码' }}
      </BaseButton>
    </div>
  </div>
</template>
