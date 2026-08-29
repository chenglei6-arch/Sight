<script setup>
import { computed } from 'vue'
import UserAvatar from './ui/UserAvatar.vue'
import { PLATFORM_MAP } from '../platforms'

/**
 * 用户资料卡。各平台的统计项、meta 行、徽标由 platforms.js 的配置函数生成。
 */
const props = defineProps({
  platformId: { type: String, required: true },
  profile: { type: Object, required: true },
})

const platform = PLATFORM_MAP[props.platformId]

const badges = computed(() => {
  const out = []
  const vip = platform.vipLabel(props.profile)
  if (vip) out.push(vip)
  return out
})

const metaItems = computed(() => platform.metaLine(props.profile))
const stats = computed(() => platform.stats(props.profile))
const signature = computed(() => (props.profile.signature || '').trim())
</script>

<template>
  <div class="card profile">
    <UserAvatar
      :src="profile.avatar_url"
      :name="profile.nickname"
      :size="62"
      :color="platform.color"
    />

    <div class="profile-main">
      <div class="profile-name-row">
        <span class="profile-name">{{ profile.nickname || '未知用户' }}</span>
        <span v-for="b in badges" :key="b" class="tag">{{ b }}</span>
      </div>
      <div class="profile-meta">
        <span>UID {{ profile.uid }}</span>
        <template v-for="(m, i) in metaItems" :key="i">
          <span class="meta-sep">·</span>
          <span class="meta-item">{{ m }}</span>
        </template>
      </div>
      <div v-if="signature" class="profile-sig">{{ signature }}</div>
    </div>

    <div v-if="stats.length" class="profile-stats">
      <div v-for="s in stats" :key="s.label" class="stat">
        <div class="stat-value">{{ s.value }}</div>
        <div class="stat-label">{{ s.label }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 18px 20px;
}

.profile-main {
  flex: 1;
  min-width: 0;
}

.profile-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.profile-name {
  font-size: 18px;
  font-weight: 700;
}

.profile-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-3);
}

.meta-sep {
  color: var(--border-strong);
}

.meta-item {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-sig {
  margin-top: 7px;
  font-size: 12.5px;
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.profile-stats {
  display: flex;
  flex-shrink: 0;
  gap: 22px;
  padding-left: 18px;
  border-left: 1px solid var(--border);
  align-self: stretch;
  align-items: center;
  flex-wrap: wrap;
}

.stat {
  text-align: center;
  min-width: 46px;
}

.stat-value {
  font-size: 16px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 1px;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .profile {
    flex-direction: column;
  }

  .profile-stats {
    border-left: none;
    padding-left: 0;
    align-self: auto;
  }
}
</style>
