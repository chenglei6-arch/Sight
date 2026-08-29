<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import {
  state,
  refreshCurrentView,
  currentPlatform,
} from '../store'

const platform = computed(() => currentPlatform())
const title = computed(() => (platform.value ? platform.value.name : '活动时间线'))

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
