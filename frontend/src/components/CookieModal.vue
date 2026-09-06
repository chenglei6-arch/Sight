<script setup>
/**
 * 平台 Cookie 配置弹窗：
 * - 展示当前凭证状态（是否已配置 / 字段）
 * - 粘贴新 Cookie 保存（POST /api/credentials/<platform>，后端会重建适配器使其立即生效）
 * - QQ音乐支持扫码登录（复用全局 QrLoginModal）
 * 保存成功后 emit('saved')，由父组件刷新平台状态并重试搜索
 */
import { ref, computed, watch } from 'vue'
import Modal from './ui/Modal.vue'
import Icon from './ui/Icon.vue'
import { api } from '../api'
import { state, loadPlatformsMeta, openQrLogin } from '../store'
import { PLATFORM_MAP } from '../platforms'

const props = defineProps({
  open: { type: Boolean, default: false },
  platform: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

const status = ref(null) // GET /credentials/<platform> 的返回
const loadingStatus = ref(false)
const saving = ref(false)
const cookieText = ref('')
const message = ref('')
const messageIsError = ref(false)

const platformName = computed(() => PLATFORM_MAP[props.platform]?.name || props.platform)
const canQrLogin = computed(() => props.platform === 'qqmusic')

const HOWTO = {
  douyin: '浏览器登录 douyin.com → F12 打开开发者工具 → Network(网络) → 刷新页面 → 点击任意 douyin.com 请求 → Request Headers(请求标头) 里复制完整 Cookie 值粘贴到下方',
  xhs: '浏览器登录 xiaohongshu.com → F12 → Network → 刷新 → 复制任意请求的 Cookie 请求头',
}
const howto = computed(() => HOWTO[props.platform] ||
  '浏览器登录该平台网页版 → F12 打开开发者工具 → Network(网络) → 刷新页面 → 复制任意请求的 Cookie 请求头，粘贴到下方')

watch(
  () => props.open,
  async (v) => {
    if (!v) return
    cookieText.value = ''
    message.value = ''
    status.value = null
    loadingStatus.value = true
    try {
      status.value = await api.get(`/credentials/${props.platform}`)
    } catch {
      status.value = { has_credential: false, cookie_keys: [] }
    } finally {
      loadingStatus.value = false
    }
  }
)

async function save() {
  const raw = cookieText.value.trim()
  if (!raw || saving.value) return
  saving.value = true
  message.value = ''
  try {
    await api.post(`/credentials/${props.platform}`, { cookie: raw })
    message.value = '已保存'
    messageIsError.value = false
    await loadPlatformsMeta() // 刷新侧栏/平台 chips 的凭证状态
    emit('saved')
    emit('close')
  } catch (e) {
    message.value = '保存失败：' + e.message
    messageIsError.value = true
  } finally {
    saving.value = false
  }
}

function qrLogin() {
  emit('close')
  openQrLogin()
}
</script>

<template>
  <Modal :open="open" :title="`配置 ${platformName} Cookie`" :width="580" @close="emit('close')">
    <div class="ck-status">
      <template v-if="loadingStatus"><span class="spinner spinner-sm" />读取凭证状态…</template>
      <template v-else-if="status?.has_credential">
        <Icon name="check" :size="13" class="ck-ok" />
        已配置 Cookie（{{ status.cookie_keys.length }} 个字段，保存于 credentials/{{ platform }}_cookie.txt）
      </template>
      <template v-else>
        <Icon name="alert" :size="13" class="ck-miss" />
        未配置 Cookie —— 搜索/资料接口大概率失败
      </template>
    </div>

    <p class="ck-howto">{{ howto }}</p>

    <textarea
      v-model="cookieText"
      class="ck-input"
      rows="6"
      spellcheck="false"
      placeholder="把复制的 Cookie 粘贴到这里（格式：k=v; k2=v2; ...）"
    />

    <p v-if="message" class="ck-msg" :class="{ 'ck-msg-err': messageIsError }">{{ message }}</p>

    <div class="ck-actions">
      <button v-if="canQrLogin" class="btn" :disabled="saving" @click="qrLogin">
        <Icon name="scan" :size="13" /> 扫码登录
      </button>
      <span class="ck-spacer" />
      <button class="btn" @click="emit('close')">取消</button>
      <button class="btn btn-primary" :disabled="saving || !cookieText.trim()" @click="save">
        <span v-if="saving" class="spinner spinner-sm" />
        {{ saving ? '保存中' : '保存并生效' }}
      </button>
    </div>
    <p v-if="canQrLogin" class="ck-tip">QQ音乐支持扫码登录；其他平台请粘贴 Cookie</p>
  </Modal>
</template>

<style scoped>
.ck-status {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  color: var(--text-2);
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  background: var(--surface-hover);
}

.ck-ok {
  color: var(--success);
}

.ck-miss {
  color: var(--warn);
}

.ck-howto {
  margin: 10px 0 8px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
}

.ck-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: 12px;
  font-family: var(--font, inherit);
  color: var(--text);
  background: var(--surface);
  resize: vertical;
  outline: none;
}

.ck-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.ck-msg {
  margin: 8px 0 0;
  font-size: 12.5px;
  color: var(--success);
}

.ck-msg-err {
  color: var(--danger);
}

.ck-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}

.ck-spacer {
  flex: 1;
}

.ck-tip {
  margin: 10px 0 0;
  font-size: 11.5px;
  color: var(--text-3);
}
</style>
