<script setup lang="ts">
import { onMounted, ref } from 'vue'
import api from '@/api'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseInput from '@/components/ui/BaseInput.vue'

interface SignForm {
  signUrl: string
  xwidUrl: string
  ptVersion: string
  qua: string
  currentVersion: string
  sdkVersion: string
  sdkBuildTime: string
  appClientVersion: string
  subAppId: string
  miscBitmap: string
  subSigMap: string
  mainSigMap: string
}

const SIGN_KEYS = [
  'signUrl', 'xwidUrl', 'ptVersion', 'qua', 'currentVersion', 'sdkVersion',
  'sdkBuildTime', 'appClientVersion', 'subAppId', 'miscBitmap', 'subSigMap', 'mainSigMap',
] as const

function emptyForm(): SignForm {
  return {
    signUrl: '', xwidUrl: '', ptVersion: '', qua: '', currentVersion: '', sdkVersion: '',
    sdkBuildTime: '', appClientVersion: '', subAppId: '', miscBitmap: '', subSigMap: '', mainSigMap: '',
  }
}

const form = ref<SignForm>(emptyForm())
const effective = ref({ signUrl: '', xwidUrl: '', ptVersion: '', qua: '' })
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const error = ref('')

function applySaved(saved: Record<string, unknown> | null | undefined) {
  const next = emptyForm()
  for (const key of SIGN_KEYS) next[key] = String(saved?.[key] ?? '')
  form.value = next
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/api/qq-login/sign')
    applySaved(data?.data)
    effective.value = data?.effective || effective.value
  }
  catch (value: any) {
    error.value = String(value?.response?.data?.error || value?.message || '签名配置读取失败')
  }
  finally { loading.value = false }
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    const { data } = await api.post('/api/qq-login/sign', { ...form.value })
    applySaved(data?.data)
    message.value = '签名服务已保存，下次启动账号时生效'
  }
  catch (value: any) {
    error.value = String(value?.response?.data?.error || value?.message || '签名配置保存失败')
  }
  finally { saving.value = false }
}

async function testSigner() {
  error.value = ''
  message.value = ''
  if (!form.value.signUrl) {
    error.value = '请先填写签名服务地址'
    return
  }
  try {
    const { data } = await api.post('/api/qq-login/sign/test', { signUrl: form.value.signUrl })
    message.value = data?.data?.ok
      ? `签名服务可用${data.data.version ? `：${data.data.version}` : ''}`
      : '签名服务返回异常'
  }
  catch (value: any) {
    error.value = String(value?.response?.data?.error || value?.message || '签名服务不可用')
  }
}

onMounted(load)
</script>

<template>
  <div class="border border-gray-200 rounded-lg bg-white p-4 max-sm:p-3 dark:border-gray-700 dark:bg-gray-800">
    <h4 class="mb-3 flex items-center gap-2 text-base text-gray-900 font-bold dark:text-gray-100 max-sm:text-sm">
      <div class="i-carbon-certificate" />
      QQ 登录签名服务
    </h4>

    <p class="mb-3 text-xs text-gray-500 dark:text-gray-400">
      可填写自建签名服务（例如本地 unidbg 9.3.75）。留空则使用部署时的环境变量配置。修改后下次启动账号生效。
    </p>

    <div v-if="loading" class="py-6 text-center text-sm text-gray-500">
      <div class="i-svg-spinners-ring-resize mx-auto mb-2 text-2xl" />
      <p>加载中...</p>
    </div>

    <div v-else class="space-y-3">
      <BaseInput v-model="form.signUrl" label="签名接口地址（/sign、/energy）" type="text" placeholder="http://172.17.0.1:8085" />
      <BaseInput v-model="form.xwidUrl" label="XWID 接口地址（/getXwDebugId）" type="text" placeholder="http://172.17.0.1:8085" />
      <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <BaseInput v-model="form.ptVersion" label="协议版本" type="text" placeholder="9.3.75" />
        <BaseInput v-model="form.qua" label="QUA" type="text" placeholder="V1_AND_SQ_9.3.75_16580_YYB_D" />
      </div>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
        <BaseInput v-model="form.currentVersion" label="当前版本号" type="text" placeholder="9.3.75.16580" />
        <BaseInput v-model="form.sdkVersion" label="SDK 版本" type="text" placeholder="6.0.0.2591" />
      </div>
      <div class="grid grid-cols-1 gap-3 md:grid-cols-3">
        <BaseInput v-model="form.miscBitmap" label="MiscBitmap" type="text" placeholder="150470524" />
        <BaseInput v-model="form.subSigMap" label="SubSigMap" type="text" placeholder="66560" />
        <BaseInput v-model="form.mainSigMap" label="MainSigMap" type="text" placeholder="16724722" />
      </div>

      <p v-if="effective.signUrl" class="text-xs text-gray-500 dark:text-gray-400">
        当前生效（环境变量）：{{ effective.signUrl }} / XWID {{ effective.xwidUrl || '同签名' }} / {{ effective.ptVersion || '版本未设置' }}
      </p>

      <div class="flex flex-wrap items-center gap-2">
        <BaseButton :disabled="saving" @click="save">
          {{ saving ? '保存中...' : '保存签名配置' }}
        </BaseButton>
        <BaseButton variant="secondary" :disabled="saving" @click="testSigner">
          测试连通性
        </BaseButton>
        <BaseButton variant="secondary" :disabled="saving" @click="load">
          重新读取
        </BaseButton>
      </div>

      <p v-if="message" class="text-xs text-green-600 dark:text-green-400">{{ message }}</p>
      <p v-if="error" class="text-xs text-red-600 dark:text-red-400">{{ error }}</p>
    </div>
  </div>
</template>
