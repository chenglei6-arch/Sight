<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import Icon from './ui/Icon.vue'
import Modal from './ui/Modal.vue'
import UserAvatar from './ui/UserAvatar.vue'
import { api } from '../api'

/**
 * QQ 音乐扫码登录弹窗。
 * 流程：POST /qr-login/start -> 每 2s 轮询 /qr-login/status -> done 后展示关注列表。
 * 轮询与清理完全归属本组件。
 */
const open = defineModel({ type: Boolean, default: false })

const emit = defineEmits(['closed'])

const phase = ref('idle') // idle | starting | qr_ready | logged_in | fetching | done | error
const qrImage = ref('')
const statusText = ref('')
const errorMsg = ref('')
const followData = ref(null)
const showRaw = ref(false)

let pollTimer = null

const phaseNote = computed(
  () =>
    ({
      idle: '正在启动…',
      starting: '正在生成二维码…',
      logged_in: '扫码成功，正在获取关注列表…',
      fetching: '正在获取关注列表…',
    })[phase.value] || ''
)

async function start() {
  stopPolling()
  phase.value = 'starting'
  qrImage.value = ''
  errorMsg.value = ''
  followData.value = null
  showRaw.value = false
  try {
    await api.post('/qqmusic/qr-login/start')
    startPolling()
  } catch (e) {
    phase.value = 'error'
    errorMsg.value = e.message
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollStatus, 2000)
  pollStatus()
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollStatus() {
  try {
    const s = await api.get('/qqmusic/qr-login/status')
    applyStatus(s)
  } catch {
    /* 单次轮询失败忽略，等下一轮 */
  }
}

function applyStatus(s) {
  statusText.value = s.status || ''
  if (s.status === 'qr_ready') {
    phase.value = 'qr_ready'
    if (s.qr_code) qrImage.value = s.qr_code
  } else if (s.status === 'logged_in') {
    phase.value = 'logged_in'
  } else if (s.status === 'fetching') {
    phase.value = 'fetching'
  } else if (s.status === 'done') {
    stopPolling()
    phase.value = 'done'
    followData.value = s.follow_data || null
  } else if (s.status === 'error') {
    stopPolling()
    phase.value = 'error'
    errorMsg.value = s.error || '未知错误'
  }
}

async function cancel() {
  stopPolling()
  open.value = false
  api.post('/qqmusic/qr-login/stop').catch(() => {})
  emit('closed')
}

watch(open, (v) => {
  if (v) start()
  else stopPolling()
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <Modal :open="open" title="QQ音乐扫码登录" :width="480" @close="cancel()">
    <!-- 生成中 / 等待二维码 -->
    <div v-if="phase === 'starting' || (phase === 'qr_ready' && !qrImage)" class="qr-center">
      <span class="spinner" />
      <div class="qr-note">{{ phaseNote }}</div>
    </div>

    <!-- 二维码 -->
    <div v-else-if="phase === 'qr_ready' || phase === 'logged_in' || phase === 'fetching'" class="qr-center">
      <img
        v-if="qrImage"
        :src="'data:image/png;base64,' + qrImage"
        class="qr-img"
        alt="QQ登录二维码"
      />
      <div class="qr-note">
        <template v-if="phase === 'qr_ready'">请用手机 QQ 扫一扫登录</template>
        <template v-else>
          <span class="spinner spinner-sm" style="display: inline-block; vertical-align: -2px" />
          登录成功，{{ phaseNote }}
        </template>
      </div>
      <button class="btn btn-sm" style="margin-top: 12px" @click="start()">
        <Icon name="refresh" :size="12" />
        刷新二维码
      </button>
    </div>

    <!-- 完成：关注列表 -->
    <div v-else-if="phase === 'done'" class="qr-done">
      <div class="done-head">
        <span class="done-icon"><Icon name="check" :size="16" /></span>
        <div>
          <div class="done-title">登录成功</div>
          <div class="done-sub">
            {{ followData ? `已获取 ${followData.count ?? (followData.follows || []).length} 个关注` : '未获取到关注数据' }}
          </div>
        </div>
      </div>

      <template v-if="followData && (followData.follows || []).length">
        <div class="follow-list">
          <div v-for="(u, i) in followData.follows" :key="i" class="follow-row">
            <UserAvatar :src="u.avatarUrl || u.avatar_url" :name="u.nickname" :size="32" color="#31c27c" />
            <span class="follow-main">
              <span class="follow-name">{{ u.nickname || '未知' }}</span>
              <span v-if="u.signature || u.desc" class="follow-sig">{{ u.signature || u.desc }}</span>
            </span>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="qr-note" style="margin-top: 14px">
          未能从页面提取到关注列表（可能为空或不可见）
        </div>
        <details v-if="followData?.all_text_lines?.length" style="margin-top: 8px">
          <summary class="raw-toggle">查看页面原始文本</summary>
          <pre class="raw-pre">{{ followData.all_text_lines.join('\n') }}</pre>
        </details>
      </template>
    </div>

    <!-- 失败 -->
    <div v-else-if="phase === 'error'" class="qr-center">
      <span class="err-icon"><Icon name="alert" :size="30" /></span>
      <div class="qr-note qr-err">登录失败：{{ errorMsg }}</div>
      <div class="qr-btns">
        <button class="btn btn-sm btn-primary" @click="start()">重试</button>
        <button class="btn btn-sm" @click="cancel()">关闭</button>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.qr-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 18px 0 8px;
}

.qr-img {
  width: 240px;
  height: 240px;
  object-fit: contain;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
}

.qr-note {
  font-size: 13px;
  color: var(--text-2);
  text-align: center;
}

.qr-err {
  color: var(--danger);
}

.qr-btns {
  display: flex;
  gap: 8px;
}

.err-icon {
  color: var(--danger);
}

.qr-done {
  padding-top: 2px;
}

.done-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0 12px;
  border-bottom: 1px solid var(--border);
}

.done-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--success-soft);
  color: var(--success);
  flex-shrink: 0;
}

.done-title {
  font-size: 14.5px;
  font-weight: 600;
}

.done-sub {
  font-size: 12px;
  color: var(--text-3);
}

.follow-list {
  margin-top: 10px;
  max-height: 320px;
  overflow-y: auto;
}

.follow-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
}

.follow-row + .follow-row {
  border-top: 1px solid var(--surface-hover);
}

.follow-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.follow-name {
  font-size: 13px;
  font-weight: 500;
}

.follow-sig {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.raw-toggle {
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
}

.raw-pre {
  margin: 8px 0 0;
  padding: 10px;
  max-height: 240px;
  overflow: auto;
  background: var(--surface-hover);
  border-radius: 8px;
  font-size: 10.5px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
