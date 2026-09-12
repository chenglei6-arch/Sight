<script setup>
/**
 * 平台 Cookie / 多账号配置弹窗：
 * - 主账号: credentials/<platform>_cookie.txt（原单账号行为，历史记录等私有数据固定走它）
 * - 附加账号: 存于 credentials/accounts.json，与主账号组成账号池，
 *   图谱展开等批量查询会并行使用所有账号，速度近似按账号数提升
 * - 附加账号控制: 添加 / 启停 / 删除
 * - QQ音乐支持扫码登录（复用全局 QrLoginModal）
 * 保存成功后 emit('saved')，由父组件刷新平台状态并重试搜索
 */
import { ref, computed, watch } from 'vue'
import Modal from './ui/Modal.vue'
import Icon from './ui/Icon.vue'
import { api } from '../api'
import { loadPlatformsMeta, openQrLogin } from '../store'
import { PLATFORMS, PLATFORM_MAP } from '../platforms'

const props = defineProps({
  open: { type: Boolean, default: false },
  platform: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved'])

// 弹窗内可切换平台（顶栏入口未指定平台时默认第一个）
const selPlatform = ref(props.platform || PLATFORMS[0]?.id || '')
watch(
  () => props.platform,
  (v) => { if (v) selPlatform.value = v }
)

const status = ref(null) // GET /credentials/<platform> 的返回（主账号）
const accounts = ref([]) // GET /accounts/<platform> 的返回
const loadingStatus = ref(false)
const saving = ref(false)
const cookieText = ref('')
const message = ref('')
const messageIsError = ref(false)

// 附加账号表单
const extraName = ref('')
const extraCookie = ref('')
const addingAccount = ref(false)
const rowBusy = ref({}) // {id: true} 行级操作进行中
const rowTesting = ref({}) // {id: true} 行级可用性测试进行中
const testResults = ref({}) // {id: {ok, text}} 各账号最近一次测试结果

const platformName = computed(() => PLATFORM_MAP[selPlatform.value]?.name || selPlatform.value)
const canQrLogin = computed(() => selPlatform.value === 'qqmusic')
const extraAccounts = computed(() => (accounts.value?.accounts || []).filter(a => !a.primary))
const parallelHint = computed(() => {
  const n = accounts.value?.pool_size || 0
  if (n >= 2) return `当前 ${n} 个账号并行查询，批量展开速度约 ×${n}`
  return '添加附加账号后，图谱展开等批量查询将并行进行，速度按账号数提升'
})

const HOWTO = {
  douyin: '浏览器登录 douyin.com → F12 打开开发者工具 → Network(网络) → 刷新页面 → 点击任意 douyin.com 请求 → Request Headers(请求标头) 里复制完整 Cookie 值粘贴到下方',
  xhs: '浏览器登录 xiaohongshu.com → F12 → Network → 刷新 → 复制任意请求的 Cookie 请求头',
}
const howto = computed(() => HOWTO[selPlatform.value] ||
  '浏览器登录该平台网页版 → F12 打开开发者工具 → Network(网络) → 刷新页面 → 复制任意请求的 Cookie 请求头，粘贴到下方')

async function loadAll() {
  loadingStatus.value = true
  try {
    status.value = await api.get(`/credentials/${selPlatform.value}`)
    accounts.value = await api.get(`/accounts/${selPlatform.value}`)
    message.value = ''
    messageIsError.value = false
  } catch (e) {
    // 后端不可达时如实提示，而不是伪装成"未配置 Cookie"
    status.value = null
    accounts.value = null
    message.value = '加载凭证状态失败：' + e.message
    messageIsError.value = true
  } finally {
    loadingStatus.value = false
  }
}

function switchPlatform() {
  // 切换平台后重置表单并重新加载该平台的账号
  cookieText.value = ''
  extraName.value = ''
  extraCookie.value = ''
  message.value = ''
  rowTesting.value = {}
  testResults.value = {}
  loadAll()
}

watch(
  () => props.open,
  async (v) => {
    if (!v) return
    if (!props.platform) selPlatform.value = PLATFORMS[0]?.id || selPlatform.value
    cookieText.value = ''
    extraName.value = ''
    extraCookie.value = ''
    message.value = ''
    rowBusy.value = {}
    rowTesting.value = {}
    testResults.value = {}
    accounts.value = null
    await loadAll()
  }
)

async function save() {
  const raw = cookieText.value.trim()
  if (!raw || saving.value) return
  saving.value = true
  message.value = ''
  try {
    await api.post(`/credentials/${selPlatform.value}`, { cookie: raw })
    message.value = '主账号已保存'
    messageIsError.value = false
    await afterChange()
  } catch (e) {
    message.value = '保存失败：' + e.message
    messageIsError.value = true
  } finally {
    saving.value = false
  }
}

async function addAccount() {
  const raw = extraCookie.value.trim()
  if (!raw || addingAccount.value) return
  addingAccount.value = true
  message.value = ''
  try {
    await api.post(`/accounts/${selPlatform.value}`, { cookie: raw, name: extraName.value.trim() })
    extraName.value = ''
    extraCookie.value = ''
    message.value = '附加账号已添加'
    messageIsError.value = false
    await afterChange()
  } catch (e) {
    message.value = '添加失败：' + e.message
    messageIsError.value = true
  } finally {
    addingAccount.value = false
  }
}

async function toggleAccount(a) {
  if (rowBusy.value[a.id]) return
  rowBusy.value = { ...rowBusy.value, [a.id]: true }
  try {
    await api.post(`/accounts/${selPlatform.value}/${a.id}`, { enabled: !a.enabled })
    await afterChange()
  } catch (e) {
    message.value = '操作失败：' + e.message
    messageIsError.value = true
  } finally {
    rowBusy.value = { ...rowBusy.value, [a.id]: false }
  }
}

async function delAccount(a) {
  if (rowBusy.value[a.id]) return
  if (!confirm(`确定删除附加账号「${a.name}」？`)) return
  rowBusy.value = { ...rowBusy.value, [a.id]: true }
  try {
    await api.del(`/accounts/${selPlatform.value}/${a.id}`)
    await afterChange()
  } catch (e) {
    message.value = '删除失败：' + e.message
    messageIsError.value = true
  } finally {
    rowBusy.value = { ...rowBusy.value, [a.id]: false }
  }
}

// 真实调用平台接口探测账号可用性（主账号 id 固定为 primary）
async function testAccount(a) {
  const id = a.id
  if (rowTesting.value[id]) return
  rowTesting.value = { ...rowTesting.value, [id]: true }
  try {
    const r = await api.post(`/accounts/${selPlatform.value}/${id}/test`)
    let text
    if (r.ok) {
      const who = r.login_user?.nickname || r.login_user?.uid || ''
      text = `可用${who ? `（登录：${who}）` : ''} · ${r.latency_ms}ms`
      if (r.warning) text += `，注意：${r.warning}`
    } else {
      text = '不可用' + (r.error ? `：${r.error}` : '')
    }
    testResults.value = { ...testResults.value, [id]: { ok: !!r.ok, text } }
  } catch (e) {
    testResults.value = { ...testResults.value, [id]: { ok: false, text: '测试失败：' + e.message } }
  } finally {
    rowTesting.value = { ...rowTesting.value, [id]: false }
  }
}

async function afterChange() {
  await loadPlatformsMeta() // 刷新侧栏/平台 chips 的凭证状态
  await loadAll()
  emit('saved')
}

function qrLogin() {
  emit('close')
  openQrLogin()
}
</script>

<template>
  <Modal :open="open" :title="`配置 ${platformName} 账号`" :width="640" @close="emit('close')">
    <!-- 平台切换（顶栏入口进入时可在此选择要配置的平台） -->
    <div class="ck-platform-row">
      <span class="ck-platform-label">平台</span>
      <select v-model="selPlatform" class="ck-platform-select" @change="switchPlatform">
        <option v-for="p in PLATFORMS" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>

    <!-- ===== 主账号 ===== -->
    <div class="ck-section-title">
      <Icon name="user" :size="13" /> 主账号
      <span class="ck-section-note">历史记录等私有数据固定使用主账号</span>
    </div>
    <div class="ck-status">
      <template v-if="loadingStatus"><span class="spinner spinner-sm" />读取凭证状态…</template>
      <template v-else-if="status?.has_credential">
        <Icon name="check" :size="13" class="ck-ok" />
        已配置 Cookie（{{ status.cookie_keys.length }} 个字段，保存于 credentials/{{ selPlatform }}_cookie.txt）
        <button
          class="btn btn-sm ck-status-btn"
          :disabled="rowTesting['primary']"
          @click="testAccount({ id: 'primary' })"
        >
          <span v-if="rowTesting['primary']" class="spinner spinner-sm" />
          {{ rowTesting['primary'] ? '测试中' : '测试可用性' }}
        </button>
      </template>
      <template v-else>
        <Icon name="alert" :size="13" class="ck-miss" />
        未配置 Cookie —— 搜索/资料接口大概率失败
      </template>
    </div>

    <p v-if="testResults['primary']" class="ck-test-result" :class="{ 'ck-test-err': !testResults['primary'].ok }">
      {{ testResults['primary'].text }}
    </p>

    <p class="ck-howto">{{ howto }}</p>

    <textarea
      v-model="cookieText"
      class="ck-input"
      rows="5"
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
        {{ saving ? '保存中' : '保存为主账号' }}
      </button>
    </div>

    <!-- ===== 附加账号（多账号并发） ===== -->
    <div class="ck-divider" />
    <div class="ck-section-title">
      <Icon name="users" :size="13" /> 附加账号
      <span class="ck-section-note">{{ parallelHint }}</span>
    </div>

    <div v-if="extraAccounts.length" class="ck-accounts">
      <div
        v-for="a in extraAccounts"
        :key="a.id"
        class="ck-acc-row"
        :class="{ 'ck-acc-disabled': !a.enabled }"
      >
        <div class="ck-acc-main">
          <div class="ck-acc-name">
            {{ a.name }}
            <span v-if="!a.enabled" class="ck-badge ck-badge-off">已停用</span>
          </div>
          <div class="ck-acc-meta">
            {{ a.has_credential ? `Cookie ${a.cookie_keys.length} 个字段` : '未配置 Cookie' }}
          </div>
          <div v-if="testResults[a.id]" class="ck-acc-test" :class="{ 'ck-test-err': !testResults[a.id].ok }">
            {{ testResults[a.id].text }}
          </div>
        </div>
        <div class="ck-acc-ops">
          <button class="btn btn-sm" :disabled="rowTesting[a.id]" @click="testAccount(a)">
            <span v-if="rowTesting[a.id]" class="spinner spinner-sm" />
            {{ rowTesting[a.id] ? '测试中' : '测试' }}
          </button>
          <button class="btn btn-sm" :disabled="rowBusy[a.id]" @click="toggleAccount(a)">
            {{ a.enabled ? '停用' : '启用' }}
          </button>
          <button class="btn btn-sm ck-del" :disabled="rowBusy[a.id]" @click="delAccount(a)">
            <Icon name="trash" :size="12" />
          </button>
        </div>
      </div>
    </div>
    <p v-else class="ck-empty">还没有附加账号，粘贴另一个账号的 Cookie 添加即可开始并行查询</p>

    <div class="ck-add">
      <div class="ck-add-row">
        <input v-model="extraName" class="ck-name-input" placeholder="备注名（可选，如：小号1）" />
      </div>
      <textarea
        v-model="extraCookie"
        class="ck-input"
        rows="3"
        spellcheck="false"
        placeholder="粘贴另一个账号的 Cookie，添加后与主账号并行查询"
      />
      <div class="ck-add-actions">
        <span class="ck-add-tip">附加账号仅用于公开数据加速（搜索/关注/粉丝/互查），不会影响主账号的历史记录</span>
        <button class="btn btn-primary" :disabled="addingAccount || !extraCookie.trim()" @click="addAccount">
          <span v-if="addingAccount" class="spinner spinner-sm" />
          添加账号
        </button>
      </div>
    </div>

    <p v-if="canQrLogin" class="ck-tip">QQ音乐支持扫码登录；其他平台请粘贴 Cookie</p>
  </Modal>
</template>

<style scoped>
.ck-platform-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.ck-platform-label {
  font-size: 12px;
  color: var(--text-3);
}

.ck-platform-select {
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  font-size: 12.5px;
  color: var(--text);
  background: var(--surface);
  outline: none;
}

.ck-platform-select:focus {
  border-color: var(--accent);
}

.ck-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin: 4px 0 8px;
}

.ck-section-note {
  font-weight: 400;
  font-size: 11.5px;
  color: var(--text-3);
}

.ck-divider {
  height: 1px;
  background: var(--border);
  margin: 16px 0 12px;
}

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

.ck-status-btn {
  margin-left: auto;
}

.ck-test-result {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--success);
}

.ck-test-err {
  color: var(--danger);
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

/* ===== 附加账号列表 ===== */
.ck-accounts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}

.ck-acc-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-hover);
}

.ck-acc-disabled {
  opacity: 0.55;
}

.ck-acc-main {
  flex: 1;
  min-width: 0;
}

.ck-acc-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 6px;
}

.ck-badge {
  font-size: 10.5px;
  font-weight: 400;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-hover);
  color: var(--text-3);
}

.ck-badge-off {
  border: 1px solid var(--border);
}

.ck-acc-meta {
  font-size: 11.5px;
  color: var(--text-3);
  margin-top: 2px;
}

.ck-acc-test {
  font-size: 11.5px;
  margin-top: 3px;
  color: var(--success);
}

.ck-acc-test.ck-test-err {
  color: var(--danger);
}

.ck-empty {
  font-size: 12px;
  color: var(--text-3);
  padding: 10px;
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  margin: 0 0 10px;
}

.ck-acc-ops {
  display: flex;
  gap: 4px;
  flex: none;
}

.ck-del {
  color: var(--danger);
}

.btn-sm {
  padding: 3px 8px;
  font-size: 11.5px;
}

/* ===== 添加表单 ===== */
.ck-add {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ck-add-row {
  display: flex;
}

.ck-name-input {
  flex: 1;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text);
  background: var(--surface);
  outline: none;
}

.ck-name-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.ck-add-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ck-add-tip {
  flex: 1;
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.5;
}
</style>
