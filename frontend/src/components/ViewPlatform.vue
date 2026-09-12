<script setup>
import { computed, ref } from 'vue'
import Icon from './ui/Icon.vue'
import SearchBox from './SearchBox.vue'
import ProfileCard from './ProfileCard.vue'
import ContentGrid from './ContentGrid.vue'
import RecordSection from './RecordSection.vue'
import EventSection from './EventSection.vue'
import SocialSection from './SocialSection.vue'
import { state, currentPlatform, loadPlatform, openQrLogin, clearPlatformCache } from '../store'

const platform = computed(() => currentPlatform())
const uid = computed(() => state.uids[state.view])
const d = computed(() => state.data[state.view])

const isInitialLoading = computed(() => d.value && d.value.loading && !d.value.loaded)
const hasFailed = computed(() => d.value && d.value.error && !d.value.loaded)
const partialWarnings = computed(() =>
  d.value && d.value.loaded && d.value.errors && d.value.errors.length ? d.value.errors : []
)

// 清理缓存：清空该平台内存缓存后强制实时重拉数据，结果以行内提示短暂展示
const clearing = ref(false)
const clearMsg = ref('')
const clearIsError = ref(false)
let clearMsgTimer = null

async function clearCache() {
  if (clearing.value) return
  clearing.value = true
  clearMsg.value = ''
  try {
    const stats = await clearPlatformCache(state.view)
    const parts = []
    if (stats?.adapters_dropped) parts.push(`适配器缓存 ×${stats.adapters_dropped}`)
    for (const [name, n] of Object.entries(stats?.cleared || {})) {
      if (n) parts.push(`${name} ${n} 条`)
    }
    if (stats?.search_cache_cleared) parts.push(`搜索缓存 ${stats.search_cache_cleared} 条`)
    clearMsg.value = parts.length ? `已清理：${parts.join('、')}，数据已重新拉取` : '缓存已清理，数据已重新拉取'
    clearIsError.value = false
  } catch (e) {
    clearMsg.value = '清理失败：' + e.message
    clearIsError.value = true
  } finally {
    clearing.value = false
    clearTimeout(clearMsgTimer)
    clearMsgTimer = setTimeout(() => { clearMsg.value = '' }, 6000)
  }
}

const sectionIcon = {
  playlist: 'grid',
  video: 'play',
  work: 'play',
  post: 'edit',
  character: 'user',
}
</script>

<template>
  <div class="content-narrow">
    <!-- 未设置目标用户 -->
    <div v-if="!uid" class="empty-state card setup-card">
      <span class="empty-icon"><Icon name="user" :size="34" /></span>
      <div class="empty-title">设置 {{ platform.name }} 目标用户</div>
      <div class="setup-hint">{{ platform.uidHint }}</div>
      <SearchBox :platform-id="state.view" class="setup-search" />
    </div>

    <!-- 首次加载 -->
    <div v-else-if="isInitialLoading" class="page-loading">
      <span class="spinner" />
      正在加载 {{ platform.name }} 数据，首次可能需要十几秒…
    </div>

    <!-- 加载失败 -->
    <div v-else-if="hasFailed" class="card error-card">
      <span class="empty-icon"><Icon name="alert" :size="32" /></span>
      <div class="empty-title">数据加载失败</div>
      <div class="error-msg">{{ d.error }}</div>
      <div class="error-hint">可能触发了平台反爬限制，稍后重试通常可以恢复</div>
      <button class="btn btn-primary" @click="loadPlatform(state.view, { force: true })">
        <Icon name="refresh" :size="13" />
        重试
      </button>
    </div>

    <!-- 正常内容 -->
    <template v-else>
      <div class="view-head">
        <SearchBox :platform-id="state.view" />
        <div class="head-actions">
          <button
            v-if="platform.hasQrLogin"
            class="btn"
            title="扫码登录后可查看登录账号的关注列表"
            @click="openQrLogin()"
          >
            <Icon name="scan" :size="13" />
            扫码查关注
          </button>
          <button
            class="btn"
            :disabled="clearing"
            title="清空该平台的内存缓存（适配器缓存、关系图搜索缓存）并绕过快照强制重新拉取数据"
            @click="clearCache"
          >
            <span v-if="clearing" class="spinner spinner-sm" />
            <Icon v-else name="trash" :size="13" />
            {{ clearing ? '清理中' : '清理缓存' }}
          </button>
        </div>
      </div>

      <p v-if="clearMsg" class="clear-msg" :class="{ 'clear-msg-err': clearIsError }">{{ clearMsg }}</p>

      <div v-if="partialWarnings.length" class="banner banner-warn">
        <Icon name="alert" :size="15" style="flex-shrink: 0; margin-top: 1px" />
        <div>
          部分模块加载失败，已展示可用数据：
          <div v-for="(e, i) in partialWarnings" :key="i" class="warn-line">{{ e }}</div>
        </div>
      </div>

      <ProfileCard v-if="d.profile" :platform-id="state.view" :profile="d.profile" />

      <div class="section-title">
        <Icon :name="sectionIcon[platform.contentKind] || 'grid'" :size="15" />
        {{ platform.contentLabel }}
        <span class="count">({{ d.playlists.length }})</span>
      </div>
      <ContentGrid :platform-id="state.view" :items="d.playlists" />

      <template v-if="platform.hasRecords && d.records">
        <div class="section-title">
          <Icon name="chart" :size="15" />
          听歌排行
        </div>
        <RecordSection :records="d.records" />
        <div v-if="!(d.records.allTime || []).length && !(d.records.weekly || []).length" class="empty-inline">
          暂无听歌数据（需要该用户的网易云凭证）
        </div>
      </template>

      <template v-if="platform.hasEvents">
        <div class="section-title">
          <Icon name="activity" :size="15" />
          最近动态
          <span class="count">({{ d.events.length }})</span>
        </div>
        <EventSection v-if="d.events.length" :events="d.events" />
        <div v-else class="empty-inline">暂无动态</div>
      </template>

      <template v-if="platform.hasSocial">
        <div class="section-title">
          <Icon name="users" :size="15" />
          社交关系
        </div>
        <SocialSection
          :platform-id="state.view"
          :profile="d.profile"
          :follows="d.follows"
          :followers="d.followers"
        />
      </template>
    </template>
  </div>
</template>

<style scoped>
.setup-card {
  padding: 56px 24px;
}

.setup-hint {
  font-size: 12px;
  color: var(--text-3);
}

.setup-search {
  margin-top: 10px;
  justify-content: center;
}

.error-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 56px 24px;
  text-align: center;
}

.error-msg {
  font-size: 13px;
  color: var(--danger);
  max-width: 480px;
  word-break: break-all;
}

.error-hint {
  font-size: 12px;
  color: var(--text-3);
}

.error-card .btn {
  margin-top: 8px;
}

.view-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.head-actions {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
}

.clear-msg {
  margin: -8px 0 12px;
  font-size: 12px;
  color: var(--success);
}

.clear-msg-err {
  color: var(--danger);
}

.warn-line {
  font-size: 12px;
  opacity: 0.85;
}

.empty-inline {
  padding: 18px 16px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  font-size: 12.5px;
  text-align: center;
}
</style>
