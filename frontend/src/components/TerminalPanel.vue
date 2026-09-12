<script setup>
/**
 * 右侧终端面板
 * - 运行日志：SSE 实时流 /api/logs/stream（断线自动重连续传；失败降级为轮询
 *   /api/logs/recent?after=seq）。boot 字段变化表示后端重启过，清屏重新同步。
 * - 任务队列：展示各平台展开队列状态（数据来自 store 的全局轮询）。
 */
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import Icon from './ui/Icon.vue'
import { state, toggleTerminal, setTerminalTab, refreshQueues, queueSummary } from '../store'
import { api } from '../api'
import { platformName, platformColor } from '../platforms'

const MAX_CLIENT_ENTRIES = 2000

// ==================== 页签 ====================
const tab = computed(() => state.terminalTab)

// ==================== 运行日志 ====================
const entries = ref([])
const filter = ref('')
const paused = ref(false) // 暂停接收（新日志丢弃，恢复后重新拉 recent 补齐）
const copied = ref(false)

const logBox = ref(null)
const pinned = ref(true) // 是否钉在底部自动滚动
const unread = ref(0) // 未钉底时积压的新条数

let lastSeq = 0
let curBoot = ''
let es = null
let pollTimer = null

const filteredEntries = computed(() => {
  const kw = filter.value.trim().toLowerCase()
  if (!kw) return entries.value
  return entries.value.filter(
    (e) => e.text.toLowerCase().includes(kw) || (e.source || '').toLowerCase().includes(kw)
  )
})

async function resync() {
  // 全量重同步：用于首次加载与后端重启后
  try {
    const data = await api.get('/logs/recent', { limit: 500 })
    curBoot = data.entries.length ? data.entries[0].boot : curBoot
    entries.value = data.entries
    lastSeq = data.last_seq ?? 0
    unread.value = 0
    pinned.value = true
    await nextTick()
    scrollToBottom()
  } catch {
    /* 后端未就绪，等 SSE/轮询重试 */
  }
}

function ingest(list) {
  for (const e of list) {
    if (e.boot !== curBoot) {
      if (!curBoot) curBoot = e.boot
      else if (e.boot !== curBoot) {
        // 后端重启：seq 归零，清空重同步
        entries.value = []
        curBoot = e.boot
        lastSeq = 0
      }
    }
    if (e.seq <= lastSeq) continue
    // 允许少量跳号（SSE 重连竞态），大跳号交给 boot 重启检测兜底
    if (e.seq > lastSeq + 50 && entries.value.length) continue
    lastSeq = e.seq
    entries.value.push(e)
  }
  if (entries.value.length > MAX_CLIENT_ENTRIES) {
    entries.value.splice(0, entries.value.length - MAX_CLIENT_ENTRIES)
  }
  if (!paused.value && !pinned.value) unread.value += list.length
  if (pinned.value) {
    nextTick(scrollToBottom)
  }
}

function scrollToBottom() {
  const el = logBox.value
  if (el) el.scrollTop = el.scrollHeight
}

function onScroll() {
  const el = logBox.value
  if (!el) return
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  if (atBottom) {
    pinned.value = true
    unread.value = 0
  } else {
    pinned.value = false
  }
}

function startSse() {
  stopStreams()
  es = new EventSource(`/api/logs/stream?after=${lastSeq}`)
  es.onmessage = (ev) => {
    try {
      ingest([JSON.parse(ev.data)])
    } catch {
      /* 忽略坏帧 */
    }
  }
  es.onerror = () => {
    // 连接建立失败（后端未启动/代理不支持 SSE）→ 关闭并降级轮询
    if (es && es.readyState === EventSource.CLOSED) {
      es = null
      startPolling()
    }
    // readyState===CONNECTING 时浏览器会自动重连，不干预
  }
}

function startPolling() {
  stopStreams()
  pollTimer = setInterval(async () => {
    if (paused.value) return
    try {
      const data = await api.get('/logs/recent', { after: lastSeq, limit: 500 })
      if (data.entries.length) ingest(data.entries)
    } catch {
      /* 下次轮询重试 */
    }
  }, 2000)
}

function stopStreams() {
  if (es) {
    es.close()
    es = null
  }
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(paused, (p) => {
  if (!p) {
    // 恢复接收：补齐暂停期间的日志
    api
      .get('/logs/recent', { after: lastSeq, limit: 500 })
      .then((data) => {
        if (data.entries.length) ingest(data.entries)
      })
      .catch(() => {})
  }
})

function clearLogs() {
  entries.value = []
  unread.value = 0
}

const copyError = ref('')
async function copyLogs() {
  const text = filteredEntries.value.map((e) => `[${e.ts}] ${e.text}`).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    copyError.value = ''
    setTimeout(() => (copied.value = false), 1200)
  } catch (e) {
    copyError.value = '复制失败：' + e.message
    setTimeout(() => (copyError.value = ''), 2500)
  }
}

// ==================== 任务队列 ====================
const summary = computed(() => queueSummary())
const resuming = ref('')

const resumeError = ref('')
async function resumeQueue(platform) {
  resuming.value = platform
  try {
    await api.post('/graph/expand/resume', platform ? { platform } : {})
    await refreshQueues()
    resumeError.value = ''
  } catch (e) {
    resumeError.value = '恢复失败：' + e.message
  } finally {
    resuming.value = ''
  }
}

function queueState(q) {
  if (q.paused) return { label: '已熔断', cls: 'st-paused', title: q.pause_reason }
  if (q.running > 0) return { label: `运行中 ×${q.running}`, cls: 'st-running', title: '' }
  if (q.pending > 0) return { label: `排队 ${q.pending}`, cls: 'st-pending', title: '' }
  return { label: '空闲', cls: 'st-idle', title: '' }
}

function showQueueLogs() {
  // 跳到日志页签并清空平台过滤，便于查看全部队列日志
  setTerminalTab('logs')
  filter.value = ''
}

// ==================== 生命周期 ====================
onMounted(() => {
  resync().finally(startSse)
})

onBeforeUnmount(stopStreams)

watch(
  () => state.terminalOpen,
  (open) => {
    if (open && pinned.value) nextTick(scrollToBottom)
  }
)
</script>

<template>
  <aside class="terminal-panel" :class="{ open: state.terminalOpen }">
    <div class="terminal-inner">
      <div class="terminal-head">
        <div class="terminal-tabs">
          <button
            class="t-tab"
            :class="{ active: tab === 'logs' }"
            @click="setTerminalTab('logs')"
          >
            运行日志
          </button>
          <button
            class="t-tab"
            :class="{ active: tab === 'queue', warn: summary.paused > 0 }"
            @click="setTerminalTab('queue')"
          >
            任务队列
            <span v-if="summary.busy > 0" class="tab-badge">{{ summary.busy }}</span>
            <span v-else-if="summary.paused > 0" class="tab-badge err">!</span>
          </button>
        </div>
        <button class="t-close" title="收起面板" @click="toggleTerminal(false)">
          <Icon name="x" :size="14" />
        </button>
      </div>

      <!-- ================ 运行日志 ================ -->
      <template v-if="tab === 'logs'">
        <div class="terminal-toolbar">
          <input
            v-model="filter"
            class="t-filter"
            type="text"
            placeholder="过滤：平台 / 状态 / 关键字…"
          />
          <button
            class="t-btn"
            :class="{ on: !paused }"
            :title="paused ? '已暂停接收，点击恢复' : '接收中，点击暂停'"
            @click="paused = !paused"
          >
            <Icon :name="paused ? 'play' : 'pause'" :size="13" />
          </button>
          <button class="t-btn" title="清屏（仅本地显示）" @click="clearLogs()">
            <Icon name="trash" :size="13" />
          </button>
          <button class="t-btn" :title="copyError || (copied ? '已复制' : '复制当前显示的日志')" @click="copyLogs()">
            <Icon :name="copied ? 'check' : 'edit'" :size="13" />
          </button>
        </div>

        <div ref="logBox" class="log-box" @scroll="onScroll">
          <div v-if="copyError" class="log-line lv-error"><span class="log-text">{{ copyError }}</span></div>
          <div v-if="!filteredEntries.length" class="log-empty">
            {{ filter ? '没有匹配的日志' : '暂无日志，触发一次数据刷新试试' }}
          </div>
          <div
            v-for="e in filteredEntries"
            :key="e.seq"
            class="log-line"
            :class="`lv-${e.level}`"
          >
            <span class="log-ts">{{ e.ts }}</span>
            <span
              v-if="e.source && e.source !== 'console' && e.source !== 'stderr'"
              class="log-src"
              :style="{ color: platformColor(e.source.replace('fetch:', '')) }"
            >
              {{ e.source }}
            </span>
            <span class="log-text">{{ e.text }}</span>
          </div>
        </div>

        <button v-if="unread > 0" class="new-badge" @click="pinned = true; scrollToBottom()">
          ↓ {{ unread }} 条新日志
        </button>
      </template>

      <!-- ================ 任务队列 ================ -->
      <template v-else>
        <div class="queue-summary">
          <span>排队 <b :class="{ hot: summary.pending > 0 }">{{ summary.pending }}</b></span>
          <span>执行中 <b :class="{ hot: summary.running > 0 }">{{ summary.running }}</b></span>
          <span>熔断 <b :class="{ err: summary.paused > 0 }">{{ summary.paused }}</b></span>
          <button
            v-if="summary.paused > 0"
            class="t-btn resume-all"
            :disabled="resuming === 'all'"
            @click="resumeQueue('')"
          >
            <Icon name="refresh" :size="13" />
            全部恢复
          </button>
        </div>
        <div v-if="resumeError" class="log-line lv-error"><span class="log-text">{{ resumeError }}</span></div>

        <div class="queue-list">
          <div v-for="q in state.queues" :key="q.platform" class="queue-row">
            <span class="q-dot" :style="{ background: platformColor(q.platform) }" />
            <span class="q-name">{{ platformName(q.platform) }}</span>
            <span class="q-state" :class="queueState(q).cls" :title="queueState(q).title">
              {{ queueState(q).label }}
            </span>
            <span class="q-meta" :title="`账号池 ${q.accounts} 个 · 任务间隔 ${q.interval}s`">
              {{ q.accounts }} 账号
            </span>
            <button
              v-if="q.paused"
              class="t-btn"
              :disabled="resuming === q.platform"
              title="解除熔断，恢复该平台队列"
              @click="resumeQueue(q.platform)"
            >
              <Icon name="refresh" :size="13" />
            </button>
          </div>
          <div v-if="!state.queues.length" class="log-empty">队列状态加载中…</div>
        </div>

        <div class="queue-hint">
          熔断 = 平台队列连续失败 5 次后自动暂停；配置 Cookie 后可点恢复。
          <a href="#" @click.prevent="showQueueLogs()">查看相关日志 →</a>
        </div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.terminal-panel {
  width: 0;
  flex-shrink: 0;
  overflow: hidden;
  transition: width 0.25s ease;
  background: #16181d;
}

.terminal-panel.open {
  width: 430px;
}

.terminal-inner {
  position: relative;
  width: 430px;
  height: 100%;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #2a2e36;
  color: #c9d1d9;
}

/* ---------- 头部 ---------- */
.terminal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid #2a2e36;
  flex-shrink: 0;
}

.terminal-tabs {
  display: flex;
  gap: 4px;
}

.t-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #8b93a1;
  font-size: 12.5px;
  cursor: pointer;
}

.t-tab:hover {
  color: #c9d1d9;
}

.t-tab.active {
  background: #262a33;
  color: #e6edf3;
}

.t-tab.warn {
  color: #f0a04b;
}

.tab-badge {
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #3565e0;
  color: #fff;
  font-size: 10.5px;
  line-height: 16px;
  text-align: center;
}

.tab-badge.err {
  background: #d5372f;
}

.t-close {
  display: flex;
  align-items: center;
  padding: 5px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #8b93a1;
  cursor: pointer;
}

.t-close:hover {
  color: #e6edf3;
  background: #262a33;
}

/* ---------- 日志工具条 ---------- */
.terminal-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid #2a2e36;
  flex-shrink: 0;
}

.t-filter {
  flex: 1;
  min-width: 0;
  padding: 4px 9px;
  border: 1px solid #2a2e36;
  border-radius: 6px;
  background: #1d2026;
  color: #e6edf3;
  font-size: 12px;
  outline: none;
}

.t-filter:focus {
  border-color: #3565e0;
}

.t-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 7px;
  border: 1px solid #2a2e36;
  border-radius: 6px;
  background: #1d2026;
  color: #8b93a1;
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
}

.t-btn:hover:not(:disabled) {
  color: #e6edf3;
  border-color: #3a404c;
}

.t-btn.on {
  color: #4ade80;
  border-color: #2c4a38;
}

.t-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

/* ---------- 日志区 ---------- */
.log-box {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
  font-family: 'Cascadia Code', Consolas, 'JetBrains Mono', monospace;
  font-size: 11.5px;
  line-height: 1.7;
}

.log-empty {
  padding: 24px 0;
  text-align: center;
  color: #586069;
  font-size: 12px;
}

.log-line {
  display: flex;
  gap: 8px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #b3bcc9;
}

.log-ts {
  color: #586069;
  flex-shrink: 0;
}

.log-src {
  flex-shrink: 0;
  font-weight: 600;
}

.log-text {
  flex: 1;
  min-width: 0;
}

.lv-success .log-text {
  color: #4ade80;
}

.lv-error .log-text {
  color: #f87171;
}

.lv-warn .log-text {
  color: #fbbf24;
}

.new-badge {
  position: absolute;
  right: 24px;
  bottom: 18px;
  padding: 5px 12px;
  border: none;
  border-radius: 14px;
  background: #3565e0;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}

/* ---------- 队列页签 ---------- */
.queue-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 14px;
  border-bottom: 1px solid #2a2e36;
  font-size: 12.5px;
  color: #8b93a1;
  flex-shrink: 0;
}

.queue-summary b {
  color: #c9d1d9;
  font-weight: 600;
}

.queue-summary b.hot {
  color: #fbbf24;
}

.queue-summary b.err {
  color: #f87171;
}

.resume-all {
  margin-left: auto;
}

.queue-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 10px;
}

.queue-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 8px;
  border-radius: 8px;
  font-size: 12.5px;
}

.queue-row:hover {
  background: #1d2026;
}

.q-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.q-name {
  width: 76px;
  flex-shrink: 0;
  color: #e6edf3;
}

.q-state {
  flex: 1;
  font-weight: 600;
}

.st-running {
  color: #4ade80;
}

.st-pending {
  color: #fbbf24;
}

.st-paused {
  color: #f87171;
  cursor: help;
}

.st-idle {
  color: #586069;
  font-weight: 400;
}

.q-meta {
  color: #586069;
  font-size: 11.5px;
}

.queue-hint {
  padding: 10px 14px;
  border-top: 1px solid #2a2e36;
  color: #586069;
  font-size: 11.5px;
  line-height: 1.6;
  flex-shrink: 0;
}

.queue-hint a {
  color: #6d94ea;
}
</style>
