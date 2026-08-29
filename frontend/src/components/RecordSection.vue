<script setup>
import { computed } from 'vue'
import { fmtNum } from '../utils'

/**
 * 听歌排行（仅网易云）。records: { allTime: [], weekly: [] }
 */
const props = defineProps({
  records: { type: Object, required: true },
})

const allTime = computed(() => props.records?.allTime || [])
const weekly = computed(() => props.records?.weekly || [])

function top3(i) {
  return i < 3
}
</script>

<template>
  <div class="records">
    <div v-if="allTime.length" class="card record-panel">
      <div class="panel-head"><i class="dot dot-all" />所有时间</div>
      <div v-for="(s, i) in allTime.slice(0, 20)" :key="s.entry_id || i" class="record-row">
        <span class="rank" :class="{ top: top3(i) }">{{ i + 1 }}</span>
        <span class="r-main">
          <span class="r-title" :title="s.title">{{ s.title }}</span>
          <span class="r-sub">{{ s.artist_or_uploader }}<template v-if="s.album_or_category"> · {{ s.album_or_category }}</template></span>
        </span>
        <span class="r-count">{{ fmtNum(s.play_count) }} 次</span>
      </div>
    </div>
    <div v-if="weekly.length" class="card record-panel">
      <div class="panel-head"><i class="dot dot-week" />最近一周</div>
      <div v-for="(s, i) in weekly.slice(0, 20)" :key="s.entry_id || i" class="record-row">
        <span class="rank" :class="{ top: top3(i) }">{{ i + 1 }}</span>
        <span class="r-main">
          <span class="r-title" :title="s.title">{{ s.title }}</span>
          <span class="r-sub">{{ s.artist_or_uploader }}<template v-if="s.album_or_category"> · {{ s.album_or_category }}</template></span>
        </span>
        <span class="r-count">{{ fmtNum(s.play_count) }} 次</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.records {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
}

.record-panel {
  padding: 6px 0;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot-all {
  background: var(--accent);
}

.dot-week {
  background: #d9a514;
}

.record-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 16px;
}

.record-row + .record-row {
  border-top: 1px solid var(--surface-hover);
}

.rank {
  width: 20px;
  text-align: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.rank.top {
  color: var(--accent);
}

.r-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.r-title {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.r-sub {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.r-count {
  font-size: 12px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
</style>
