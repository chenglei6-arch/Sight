<script setup>
import { ref, watch, computed } from 'vue'
import Icon from './ui/Icon.vue'
import Modal from './ui/Modal.vue'
import { state, closeDetail } from '../store'
import { PLATFORM_MAP } from '../platforms'
import { api } from '../api'
import { fmtNum, fmtDuration } from '../utils'

const open = computed(() => !!state.detailModal)
const detail = ref(null)
const loading = ref(false)
const error = ref('')

const platform = computed(() =>
  state.detailModal ? PLATFORM_MAP[state.detailModal.platform] : null
)

async function load() {
  if (!state.detailModal) return
  const { platform: p, id } = state.detailModal
  loading.value = true
  error.value = ''
  detail.value = null
  try {
    detail.value = await api.get(`/${p}/playlist/${encodeURIComponent(id)}`)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

watch(
  () => state.detailModal,
  (v) => {
    if (v) load()
    else {
      detail.value = null
      error.value = ''
    }
  }
)

function items(detailObj) {
  return detailObj?.items || []
}

function artistOf(s) {
  return s.artist || s.singer || ''
}

function linkOf() {
  if (!state.detailModal || !platform.value) return ''
  return platform.value.itemLink({ item_id: state.detailModal.id }) || ''
}
</script>

<template>
  <Modal :open="open" :title="detail?.title || '内容详情'" @close="closeDetail()">
    <div v-if="loading" class="page-loading" style="padding: 40px 0">
      <span class="spinner" />
      加载详情…
    </div>

    <div v-else-if="error" class="detail-error">
      <Icon name="alert" :size="22" />
      {{ error }}
    </div>

    <template v-else-if="detail">
      <div class="detail-meta">
        <span>{{ detail.count ?? items(detail).length }} 项</span>
        <template v-if="detail.viewCount">
          <span class="sep">·</span>
          <span>{{ fmtNum(detail.viewCount) }} 次播放</span>
        </template>
        <template v-if="detail.subscribedCount">
          <span class="sep">·</span>
          <span>{{ fmtNum(detail.subscribedCount) }} 收藏</span>
        </template>
        <a
          v-if="linkOf()"
          :href="linkOf()"
          target="_blank"
          rel="noopener"
          class="detail-link"
        >
          <Icon name="external" :size="12" />
          在 {{ platform.name }} 打开
        </a>
      </div>
      <p v-if="detail.description" class="detail-desc">{{ detail.description }}</p>

      <div v-if="items(detail).length" class="song-list">
        <div v-for="(s, i) in items(detail).slice(0, 100)" :key="s.id || i" class="song-row">
          <span class="song-index">{{ i + 1 }}</span>
          <span class="song-main">
            <span class="song-title">{{ s.title || '未知' }}</span>
            <span v-if="artistOf(s) || s.album" class="song-sub">
              {{ artistOf(s) }}<template v-if="s.album"> · {{ s.album }}</template>
            </span>
          </span>
          <span v-if="s.duration" class="song-dur">{{ fmtDuration(s.duration) }}</span>
        </div>
      </div>
      <div v-else class="detail-empty">该内容没有可展示的条目</div>
    </template>
  </Modal>
</template>

<style scoped>
.detail-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-2);
  flex-wrap: wrap;
}

.sep {
  color: var(--border-strong);
}

.detail-link {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}

.detail-desc {
  margin: 10px 0 0;
  font-size: 12.5px;
  color: var(--text-3);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.song-list {
  margin-top: 14px;
  border-top: 1px solid var(--border);
}

.song-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 2px;
}

.song-row + .song-row {
  border-top: 1px solid var(--surface-hover);
}

.song-index {
  width: 22px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.song-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.song-title {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.song-sub {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.song-dur {
  font-size: 11.5px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.detail-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 24px 4px;
  color: var(--danger);
  font-size: 13px;
}

.detail-empty {
  margin-top: 14px;
  padding: 24px;
  text-align: center;
  color: var(--text-3);
  font-size: 12.5px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
}
</style>
