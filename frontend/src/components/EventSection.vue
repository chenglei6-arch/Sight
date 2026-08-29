<script setup>
import { ref, computed } from 'vue'
import { fmtEventTime } from '../utils'

/**
 * 用户动态列表。网易云动态 extra.pics 可能带图片，一并展示。
 */
const props = defineProps({
  events: { type: Array, default: () => [] },
})

const PAGE = 10
const expanded = ref(false)

const shown = computed(() =>
  expanded.value ? props.events : props.events.slice(0, PAGE)
)

function pics(ev) {
  const p = ev.extra?.pics
  return Array.isArray(p) ? p.filter(Boolean).slice(0, 6) : []
}
</script>

<template>
  <div class="card event-list">
    <div v-for="(ev, i) in shown" :key="ev.event_id || i" class="event-row">
      <div class="ev-side">
        <span class="ev-time">{{ fmtEventTime(ev.timestamp) || '时间未知' }}</span>
        <span v-if="ev.event_type" class="ev-type">{{ ev.event_type }}</span>
      </div>
      <div class="ev-main">
        <div v-if="ev.content" class="ev-content">{{ ev.content }}</div>
        <div v-if="ev.media_title" class="ev-media">
          《{{ ev.media_title }}》<span v-if="ev.media_artist" class="ev-artist">{{ ev.media_artist }}</span>
        </div>
        <div v-if="pics(ev).length" class="ev-pics">
          <img
            v-for="(p, j) in pics(ev)"
            :key="j"
            :src="p"
            referrerpolicy="no-referrer"
            loading="lazy"
            alt=""
            @error="$event.target.style.display = 'none'"
          />
        </div>
      </div>
    </div>

    <button
      v-if="events.length > PAGE"
      class="ev-more"
      @click="expanded = !expanded"
    >
      {{ expanded ? '收起' : `展开其余 ${events.length - PAGE} 条` }}
    </button>
  </div>
</template>

<style scoped>
.event-list {
  padding: 4px 0;
}

.event-row {
  display: flex;
  gap: 14px;
  padding: 11px 18px;
}

.event-row + .event-row {
  border-top: 1px solid var(--surface-hover);
}

.ev-side {
  width: 118px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}

.ev-time {
  font-size: 11.5px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

.ev-type {
  font-size: 10.5px;
  font-weight: 500;
  padding: 0 6px;
  border-radius: 4px;
  background: var(--surface-hover);
  color: var(--text-2);
}

.ev-main {
  flex: 1;
  min-width: 0;
}

.ev-content {
  font-size: 13px;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}

.ev-media {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--accent);
}

.ev-artist {
  margin-left: 6px;
  color: var(--text-3);
  font-size: 11.5px;
}

.ev-pics {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.ev-pics img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--border);
}

.ev-more {
  width: 100%;
  padding: 9px;
  border: none;
  border-top: 1px solid var(--border);
  background: transparent;
  color: var(--accent);
  font-size: 12.5px;
  cursor: pointer;
}

.ev-more:hover {
  background: var(--surface-hover);
}
</style>
