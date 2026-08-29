<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import {
  state,
  loadTimeline,
  setTimelineSource,
  timelineUidPairs,
  deleteTimelineEntry,
} from '../store'
import { PLATFORM_MAP } from '../platforms'
import { fmtDate, fmtTimeHM } from '../utils'

/**
 * 多平台统一活动时间线。
 * live 模式：后端实时对比快照生成（time_str / time_suffix 字段）
 * stored 模式：数据库持久化条目（带 id，可编辑删除；时间从 timestamp 还原）
 */
const t = computed(() => state.timeline)

const groups = computed(() => {
  const out = []
  let current = null
  for (const e of t.value.entries) {
    const g = entryGroup(e)
    if (!current || current.key !== g.key) {
      current = { key: g.key, label: g.label, tone: g.tone, entries: [] }
      out.push(current)
    }
    current.entries.push({ ...e, _display: entryDisplay(e) })
  }
  return out
})

function entryGroup(e) {
  if (e.time_str !== undefined) {
    const date = (e.time_str || '').split(' ')[0]
    if (date) return { key: date, label: date, tone: '' }
    const suffix = e.time_suffix || ''
    if (suffix === '首次采集') return { key: 'first', label: '首次采集', tone: 'first' }
    if (suffix.startsWith('至少从')) return { key: 'ongoing', label: '持续进行', tone: 'ongoing' }
    return { key: 'unknown', label: '时间未知', tone: 'unknown' }
  }
  // stored 条目：优先用事件时间戳，缺失时退回记录时间
  const ts = Number(e.timestamp) || 0
  const date = ts ? fmtDate(ts) : (e.created_at || '').slice(0, 10)
  return date
    ? { key: date, label: date, tone: '' }
    : { key: 'unknown', label: '时间未知', tone: 'unknown' }
}

function entryDisplay(e) {
  const platformName =
    e.platform_name || PLATFORM_MAP[e.platform]?.name || e.platform
  if (e.time_str !== undefined) {
    const time = (e.time_str || '').split(' ')[1] || ''
    return { platformName, time, suffix: e.time_suffix || '' }
  }
  const ts = Number(e.timestamp) || 0
  const time = ts ? fmtTimeHM(ts) : (e.created_at || '').slice(11, 16)
  return { platformName, time, suffix: '' }
}

function platformColor(id) {
  return PLATFORM_MAP[id]?.color || '#9aa1ab'
}

function suffixClass(suffix) {
  if (suffix === '时间未知' || suffix === '首次采集') return 's-unknown'
  if ((suffix || '').startsWith('至少从')) return 's-ongoing'
  return 's-range'
}

async function removeEntry(entry) {
  if (!entry?.id) return
  if (!window.confirm('确定删除这条时间线记录吗？')) return
  try {
    await deleteTimelineEntry(entry.id)
  } catch (e) {
    window.alert(`删除失败：${e.message}`)
  }
}
</script>

<template>
  <div class="content-narrow">
    <div class="tl-head">
      <div class="seg">
        <button
          class="seg-btn"
          :class="{ active: t.source === 'live' }"
          @click="setTimelineSource('live')"
        >
          实时对比
        </button>
        <button
          class="seg-btn"
          :class="{ active: t.source === 'stored' }"
          @click="setTimelineSource('stored')"
        >
          历史记录
        </button>
      </div>
      <span class="tl-desc">
        {{ t.source === 'live'
          ? '对比两次采集之间的快照差异，推断变化发生的时间窗口'
          : '查看已持久化的时间线条目，可编辑修正' }}
      </span>
    </div>

    <!-- 未设置任何用户 -->
    <div v-if="t.error === 'NO_UIDS'" class="empty-state card">
      <span class="empty-icon"><Icon name="clock" :size="34" /></span>
      <div class="empty-title">还没有可分析的目标用户</div>
      <div>先到各平台页搜索并设置要关注的用户，采集到两批快照后这里就会出现活动时间线</div>
    </div>

    <!-- 加载中 -->
    <div v-else-if="t.loading" class="page-loading">
      <span class="spinner" />
      正在{{ t.source === 'live' ? '对比快照' : '读取历史记录' }}…
    </div>

    <!-- 加载失败 -->
    <div v-else-if="t.error" class="card error-card">
      <span class="empty-icon"><Icon name="alert" :size="32" /></span>
      <div class="empty-title">时间线加载失败</div>
      <div class="tl-err">{{ t.error }}</div>
      <button class="btn" @click="loadTimeline({ force: true })">重试</button>
    </div>

    <!-- 空 -->
    <div v-else-if="!t.entries.length" class="empty-state card">
      <span class="empty-icon"><Icon name="inbox" :size="34" /></span>
      <div class="empty-title">暂无活动记录</div>
      <div>
        已监控平台：{{ timelineUidPairs().map((p) => p.split(':')[0]).join('、') || '无' }}<br />
        平台数据采集后会自动写入快照，检测到变化（听歌、关注、发布等）就会出现在这里
      </div>
      <button class="btn btn-primary" @click="loadTimeline({ force: true })">
        <Icon name="refresh" :size="13" />
        重新检查
      </button>
    </div>

    <!-- 时间线 -->
    <div v-else class="card timeline">
      <template v-for="g in groups" :key="g.key">
        <div class="tl-date" :class="'tone-' + g.tone">
          <Icon :name="g.tone ? 'clock' : 'calendar'" :size="12" />
          {{ g.label }}
        </div>
        <div v-for="(e, i) in g.entries" :key="(e.id || i) + '-' + e.summary" class="tl-entry">
          <span class="tl-dot" :style="{ background: platformColor(e.platform) }" />
          <div class="tl-body">
            <div class="tl-meta">
              <span class="tl-platform">
                <span class="pl-dot" :style="{ background: platformColor(e.platform) }" />
                {{ e._display.platformName }}
              </span>
              <span class="tl-type">{{ e.event_type }}</span>
              <span class="tl-time">{{ e._display.time }}</span>
              <span
                v-if="e._display.suffix && e._display.suffix !== e._display.time"
                class="tl-suffix"
                :class="suffixClass(e._display.suffix)"
              >
                {{ e._display.suffix }}
              </span>
            </div>
            <div class="tl-summary">{{ e.summary }}</div>
            <div v-if="e.detail" class="tl-detail">{{ e.detail }}</div>
            <div v-if="t.source === 'stored' && e.id" class="tl-actions">
              <button class="btn btn-sm" @click="state.editEntry = { id: e.id, summary: e.summary || '', detail: e.detail || '' }">
                <Icon name="edit" :size="11" />
                编辑
              </button>
              <button class="btn btn-sm btn-danger-ghost" title="删除此条记录" @click="removeEntry(e)">
                <Icon name="trash" :size="11" />
                删除
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tl-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.seg {
  display: inline-flex;
  background: var(--surface-hover);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 3px;
}

.seg-btn {
  padding: 5px 14px;
  border: none;
  border-radius: 7px;
  background: transparent;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-2);
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}

.seg-btn.active {
  background: var(--surface);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--shadow-card);
}

.tl-desc {
  font-size: 12px;
  color: var(--text-3);
}

.error-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 56px 24px;
  text-align: center;
}

.tl-err {
  font-size: 13px;
  color: var(--danger);
}

.timeline {
  padding: 6px 0;
}

.tl-date {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 14px 20px 8px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-2);
}

.tl-date.tone-unknown {
  color: var(--text-3);
}

.tl-date.tone-ongoing {
  color: #8b6f2e;
}

.tl-entry {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 9px 20px 9px 24px;
}

.tl-dot {
  position: absolute;
  left: 11px;
  top: 17px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.tl-entry::before {
  content: '';
  position: absolute;
  left: 14.5px;
  top: 28px;
  bottom: -12px;
  width: 1px;
  background: var(--border);
}

.tl-entry:last-child::before {
  display: none;
}

.tl-body {
  flex: 1;
  min-width: 0;
}

.tl-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-3);
}

.tl-platform {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 500;
  color: var(--text-2);
}

.pl-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.tl-type {
  padding: 0 6px;
  border-radius: 4px;
  background: var(--surface-hover);
  color: var(--text-2);
}

.tl-time {
  font-variant-numeric: tabular-nums;
}

.tl-suffix {
  padding: 0 6px;
  border-radius: 4px;
}

.tl-suffix.s-unknown {
  background: var(--surface-hover);
  color: var(--text-3);
}

.tl-suffix.s-ongoing {
  background: var(--warn-soft);
  color: var(--warn);
}

.tl-suffix.s-range {
  background: var(--accent-soft);
  color: var(--accent);
}

.tl-summary {
  margin-top: 3px;
  font-size: 13.5px;
  color: var(--text);
  word-break: break-word;
}

.tl-detail {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-3);
  word-break: break-word;
}

.tl-actions {
  margin-top: 6px;
}
</style>
