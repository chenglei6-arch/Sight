<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import Icon from './ui/Icon.vue'
import UserAvatar from './ui/UserAvatar.vue'
import { state, setUid, searchUsers } from '../store'

/**
 * 平台目标用户搜索框：
 * - 输入内容形似 UID（纯数字 / sec_uid 等，按平台判断）时回车直接设为目标
 * - 否则调用搜索接口，结果展示在下拉里；仅一条结果时自动选中
 */
const props = defineProps({
  platformId: { type: String, required: true },
})

import { PLATFORM_MAP } from '../platforms'
const platform = PLATFORM_MAP[props.platformId]

const keyword = ref('')
const searching = ref(false)
const results = ref([])
const dropdownOpen = ref(false)
const searchError = ref('')

const uid = computed(() => state.uids[props.platformId])

async function onEnter() {
  const kw = keyword.value.trim()
  if (!kw) return
  if (platform.looksLikeUid(kw)) {
    selectUid(kw)
    return
  }
  await doSearch(kw)
}

async function doSearch(kw) {
  searching.value = true
  searchError.value = ''
  results.value = []
  dropdownOpen.value = true
  try {
    const list = await searchUsers(props.platformId, kw)
    results.value = Array.isArray(list) ? list : []
    // 仅一条结果时直接选中，少点一次
    if (results.value.length === 1) {
      select(platform.resultUid(results.value[0]), results.value[0].nickname)
      return
    }
  } catch (e) {
    searchError.value = e.message
  } finally {
    searching.value = false
  }
}

function selectUid(value) {
  setUid(props.platformId, value)
  dropdownOpen.value = false
  results.value = []
}

function select(value, nickname) {
  selectUid(value)
  keyword.value = nickname || ''
}

function clearTarget() {
  selectUid('')
  keyword.value = ''
}

function onDocClick(e) {
  if (!e.target.closest('.searchbox')) dropdownOpen.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div class="searchbox">
    <div class="sb-field">
      <Icon name="search" :size="14" class="sb-icon" />
      <input
        v-model="keyword"
        class="sb-input"
        :placeholder="platform.searchPlaceholder"
        :title="platform.uidHint"
        @keydown.enter="onEnter"
        @focus="results.length && (dropdownOpen = true)"
      />
      <button class="btn btn-sm sb-btn" :disabled="searching || !keyword.trim()" @click="onEnter">
        {{ searching ? '搜索中' : '搜索' }}
      </button>
    </div>

    <span v-if="uid" class="sb-uid" :title="'当前目标：' + uid">
      {{ uid.length > 18 ? uid.slice(0, 16) + '…' : uid }}
      <button class="sb-uid-x" title="清除目标用户" @click="clearTarget">
        <Icon name="x" :size="10" />
      </button>
    </span>

    <div v-if="dropdownOpen" class="sb-dropdown card">
      <div v-if="searching" class="sb-note"><span class="spinner spinner-sm" />搜索中…</div>
      <div v-else-if="searchError" class="sb-note sb-err">{{ searchError }}</div>
      <div v-else-if="!results.length" class="sb-note">
        无结果<span class="sb-hint">（{{ platform.uidHint }}）</span>
      </div>
      <button
        v-for="(u, i) in results.slice(0, 12)"
        :key="i"
        class="sb-item"
        @click="select(platform.resultUid(u), u.nickname)"
      >
        <UserAvatar :src="u.avatarUrl" :name="u.nickname" :size="30" :color="platform.color" />
        <span class="sb-item-main">
          <span class="sb-item-name">{{ u.nickname || '未知用户' }}</span>
          <span v-if="u.signature" class="sb-item-sig">{{ u.signature }}</span>
        </span>
        <span class="sb-item-uid">{{ platform.resultUid(u) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.searchbox {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sb-field {
  display: flex;
  align-items: center;
  width: min(460px, 100%);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

.sb-field:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.sb-icon {
  margin-left: 11px;
  color: var(--text-3);
  flex-shrink: 0;
}

.sb-input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  color: var(--text);
  background: transparent;
}

.sb-input::placeholder {
  color: var(--text-3);
}

.sb-btn {
  margin: 3px;
  border: none;
  background: var(--accent-soft);
  color: var(--accent);
}

.sb-btn:hover:not(:disabled) {
  background: var(--accent-soft);
  filter: brightness(0.96);
}

.sb-uid {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 4px 3px 10px;
  border-radius: 999px;
  background: var(--surface-hover);
  border: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-2);
  max-width: 220px;
  overflow: hidden;
}

.sb-uid-x {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
}

.sb-uid-x:hover {
  background: var(--border);
  color: var(--text);
}

.sb-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 30;
  width: min(460px, 100%);
  max-height: 320px;
  overflow-y: auto;
  padding: 5px;
  box-shadow: var(--shadow-pop);
}

.sb-note {
  padding: 12px 10px;
  font-size: 12.5px;
  color: var(--text-3);
  display: flex;
  align-items: center;
  gap: 8px;
}

.sb-err {
  color: var(--danger);
}

.sb-hint {
  color: var(--text-3);
}

.sb-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 7px 8px;
  border: none;
  border-radius: 7px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.sb-item:hover {
  background: var(--surface-hover);
}

.sb-item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.sb-item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-item-sig {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-item-uid {
  font-size: 11px;
  color: var(--text-3);
  flex-shrink: 0;
}
</style>
