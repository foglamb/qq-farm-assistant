<script setup lang="ts">
import { onMounted, shallowRef } from 'vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import api from '@/api'

interface YybRuntimeStatus {
  enabled: boolean
  running: boolean
  external: boolean
  pid: number | null
  error: string | null
}

const status = shallowRef<YybRuntimeStatus | null>(null)
const loading = shallowRef(false)
const saving = shallowRef(false)
const errorMessage = shallowRef('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const { data } = await api.get('/api/yyb/runtime')
    status.value = data.data
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.error || '读取应用宝状态失败'
  } finally {
    loading.value = false
  }
}

async function setEnabled() {
  if (!status.value || saving.value) return
  saving.value = true
  errorMessage.value = ''
  try {
    const { data } = await api.post('/api/yyb/runtime', { enabled: !status.value.enabled })
    status.value = data.data
  } catch (error: any) {
    errorMessage.value = error?.response?.data?.error || '应用宝开关操作失败'
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="border border-gray-200 rounded-lg bg-white p-4 max-sm:p-3 dark:border-gray-700 dark:bg-gray-800">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h4 class="mb-1 flex items-center gap-2 text-base text-gray-900 font-bold dark:text-gray-100 max-sm:text-sm">
          <div class="i-carbon-application-web" />
          应用宝协议
        </h4>
        <p class="text-xs text-gray-500 dark:text-gray-400">
          默认关闭，不占用 Go 服务资源。开启后才能使用应用宝扫码和换码，选择会跨重启保留。
        </p>
      </div>
      <BaseButton
        variant="primary"
        size="sm"
        :loading="saving"
        :disabled="loading || !status"
        @click="setEnabled"
      >
        {{ status?.enabled ? '关闭应用宝' : '开启应用宝' }}
      </BaseButton>
    </div>
    <div v-if="status" class="mt-3 text-xs" :class="status.running ? 'text-green-600' : 'text-gray-500'">
      {{ status.running ? '服务运行中' : status.enabled ? '已开启，服务未就绪' : '当前已关闭' }}
      <span v-if="status.external">（复用已有服务）</span>
    </div>
    <p v-if="errorMessage" class="mt-3 text-xs text-red-500">{{ errorMessage }}</p>
  </div>
</template>
