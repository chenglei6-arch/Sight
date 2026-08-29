<script setup>
import { ref, computed } from 'vue'
import Icon from './ui/Icon.vue'
import {
  state,
  startCollector,
  stopCollector,
  collectOnce,
} from '../store'

const interval = ref(30)
const showLogs = ref(false)

const running = computed(() => !!state.collector.status?.running)
// last_run 形如 { netease: "2026-06-26T10:30:00+08:00", ... }，取最新一条
const lastRun = computed(() => {
  const lr = state.collector.status?.last_run
  if (!lr || typeof lr !== 'object') return ''
  const times = Object.values(lr).filter(Boolean).sort()
  if (!times.length) return ''
  return times[times.length - 1].replace('T', ' ').slice(0, 19)
})
</script>

<template>
  <div class="collector">
    <button class="collector-head" @click="showLogs = !showLogs">
      <Icon name="activity" :size="14" />
      <span class="collector-title">自动采集</span>
      <span class="collector-pill" :class="running ? 'on' : 'off'">
        {{ running ? `运行中 · ${state.collector.status?.interval_minutes ?? interval}分` : '已停止' }}
      </span>
    </button>

    <div class="collector-row">
      <span class="interval-label">间隔</span>
      <input v-model.number="interval" type="number" min="1" max="1440" class="input interval-input" />
      <span class="interval-unit">分钟</span>
      <button
        v-if="!running"
        class="btn btn-sm btn-primary"
        :disabled="state.collector.busy"
        @click="startCollector(interval)"
      >
        启动
      </button>
      <button
        v-else
        class="btn btn-sm"
        :disabled="state.collector.busy"
        @click="stopCollector()"
      >
        <Icon name="square" :size="11" />
        停止
      </button>
    </div>

    <button class="btn btn-sm collector-collect" :disabled="state.collector.busy" @click="collectOnce(interval)">
      <Icon name="refresh" :size="11" />
      采集一次
    </button>

    <div v-if="lastRun" class="collector-last">上次采集：{{ lastRun }}</div>

    <div v-if="showLogs && state.collector.logs.length" class="collector-logs">
      <div
        v-for="(log, i) in state.collector.logs.slice(0, 8)"
        :key="i"
        class="collector-log"
        :class="log.kind"
      >
        <span class="log-time">{{ log.time }}</span>{{ log.text }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.collector {
  font-size: 12px;
}

.collector-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 2px;
  border: none;
  background: transparent;
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.collector-title {
  flex: 1;
  text-align: left;
}

.collector-pill {
  font-size: 10.5px;
  font-weight: 500;
  padding: 1px 7px;
  border-radius: 999px;
}

.collector-pill.on {
  background: var(--success-soft);
  color: var(--success);
}

.collector-pill.off {
  background: var(--surface-hover);
  color: var(--text-3);
}

.collector-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.interval-label {
  color: var(--text-3);
}

.interval-input {
  width: 46px;
  padding: 4px 6px;
  font-size: 12px;
  text-align: center;
}

.interval-unit {
  color: var(--text-3);
  margin-right: auto;
}

.collector-collect {
  width: 100%;
  margin-top: 6px;
}

.collector-last {
  margin-top: 7px;
  font-size: 11px;
  color: var(--text-3);
}

.collector-logs {
  margin-top: 7px;
  max-height: 110px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.collector-log {
  font-size: 10.5px;
  color: var(--text-2);
  line-height: 1.5;
}

.collector-log.ok {
  color: var(--success);
}

.collector-log.warn {
  color: var(--danger);
}

.log-time {
  color: var(--text-3);
  margin-right: 5px;
}
</style>
