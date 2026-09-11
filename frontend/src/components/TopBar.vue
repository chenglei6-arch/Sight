<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import {
  state,
  refreshCurrentView,
  currentPlatform,
  openAccountModal,
  toggleTerminal,
  queueSummary,
} from '../store'

const platform = computed(() => currentPlatform())
const VIEW_TITLES = { timeline: '活动时间线', graph: '关系图谱' }
const title = computed(() =>
  platform.value ? platform.value.name : VIEW_TITLES[state.view] || 'Sight'
)

// 终端按钮角标：排队/执行任务数；有熔断平台时红色
const queueInfo = computed(() => {
  const s = queueSummary()
  return { busy: s.busy, paused: s.paused }
})

const updatedAt = computed(() => {
  if (state.view === 'timeline') {
    return state.timeline.fetchedAt
  }
  const d = state.data[state.view]
  return d && d.loaded ? d.fetchedAt : null
})

const busy = computed(() => {
  if (state.view === 'timeline') return state.timeline.loading
  const d = state.data[state.view]
  return !!(d && d.loading)
})
</script>

<template>
  <header class="topbar">
    <div class="topbar-title">
      <span class="title-dot" :style="platform ? { background: platform.color } : {}" />
      {{ title }}
    </div>

    <div class="topbar-right">
      <span v-if="updatedAt" class="topbar-updated">更新于 {{ updatedAt.toLocaleTimeString('zh-CN', { hour12: false }) }}</span>

      <label class="topbar-switch" title="每 5 分钟自动刷新当前视图">
        <span>自动刷新</span>
        <span class="switch">
          <input v-model="state.autoRefresh" type="checkbox" />
          <span class="track" />
        </span>
      </label>

      <button
        class="btn terminal-btn"
        :class="{ active: state.terminalOpen }"
        title="终端面板：运行日志与任务队列"
        @click="toggleTerminal()"
      >
        <Icon name="terminal" :size="13" />
        终端
        <span v-if="queueInfo.paused > 0" class="term-badge err">{{ queueInfo.paused }}</span>
        <span v-else-if="queueInfo.busy > 0" class="term-badge">{{ queueInfo.busy }}</span>
      </button>
      <button class="btn" title="配置各平台 Cookie 与多账号池（多账号并行查询加速）" @click="openAccountModal(platform?.id || '')">
        <Icon name="users" :size="13" />
        账号
      </button>
      <button class="btn" :disabled="busy" @click="refreshCurrentView()">
        <Icon name="refresh" :size="13" :class="{ spinning: busy }" />
        刷新
      </button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  height: var(--topbar-h);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 24px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.topbar-title {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 15px;
  font-weight: 700;
}

.title-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--border-strong);
}

.topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}

.topbar-updated {
  font-size: 12px;
  color: var(--text-3);
}

.terminal-btn {
  position: relative;
}

.terminal-btn.active {
  color: var(--accent);
  border-color: var(--accent);
}

.term-badge {
  position: absolute;
  top: -7px;
  right: -7px;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 10.5px;
  line-height: 16px;
  text-align: center;
  font-weight: 600;
}

.term-badge.err {
  background: var(--danger);
}

.topbar-switch {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  color: var(--text-2);
  cursor: pointer;
  user-select: none;
}

.spinning {
  animation: icon-spin 0.9s linear infinite;
}

@keyframes icon-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
