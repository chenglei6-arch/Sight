<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import UserAvatar from './ui/UserAvatar.vue'
import { PLATFORM_MAP } from '../platforms'
import { setUid } from '../store'

/**
 * 关注 / 粉丝两栏。列表项可点击，把该用户设为当前平台的目标。
 * QQ音乐加密 uin 用户拿不到列表，只有计数（profile.extra.fan_count 等），展示提示。
 */
const props = defineProps({
  platformId: { type: String, required: true },
  profile: { type: Object, default: null },
  follows: { type: Array, default: () => [] },
  followers: { type: Array, default: () => [] },
})

const platform = PLATFORM_MAP[props.platformId]
const MAX = 20

const followsCountOnly = computed(() => {
  if (props.follows.length || !props.profile) return 0
  const e = props.profile.extra || {}
  return Number(e.follow_count ?? e.mFollowNum) || 0
})

const followersCountOnly = computed(() => {
  if (props.followers.length || !props.profile) return 0
  const e = props.profile.extra || {}
  return Number(e.fan_count ?? e.mFansNum) || 0
})

function pickUid(u) {
  return String(u.sec_uid || u.uid || u.uin || '')
}

function goUser(u) {
  const uid = pickUid(u)
  if (uid) setUid(props.platformId, uid)
}

const panels = computed(() => [
  { icon: 'user', label: '关注', list: props.follows, countOnly: followsCountOnly.value },
  { icon: 'users', label: '粉丝', list: props.followers, countOnly: followersCountOnly.value },
])
</script>

<template>
  <div class="social">
    <div v-for="p in panels" :key="p.label" class="card social-panel">
      <div class="panel-head">
        <Icon :name="p.icon" :size="13" />
        {{ p.label }}
        <span class="panel-count">{{ p.list.length || p.countOnly || '' }}</span>
      </div>
      <template v-if="p.list.length">
        <button v-for="(u, i) in p.list.slice(0, MAX)" :key="i" class="social-row" @click="goUser(u)">
          <UserAvatar :src="u.avatarUrl" :name="u.nickname" :size="32" :color="platform.color" />
          <span class="s-main">
            <span class="s-name">{{ u.nickname || '未知' }}</span>
            <span v-if="u.signature" class="s-sig">{{ u.signature }}</span>
          </span>
        </button>
        <div v-if="p.list.length > MAX" class="social-more">仅显示前 {{ MAX }} 个</div>
      </template>
      <div v-else-if="p.countOnly" class="social-note">
        共 {{ p.countOnly }} 人，加密账号暂无法获取列表
      </div>
      <div v-else class="social-note">暂无数据</div>
    </div>
  </div>
</template>

<style scoped>
.social {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
}

.social-panel {
  padding: 6px 0;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  border-bottom: 1px solid var(--border);
}

.panel-count {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-3);
}

.social-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 16px;
  border: none;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.social-row:hover {
  background: var(--surface-hover);
}

.s-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.s-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.s-sig {
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.social-note {
  padding: 18px 16px;
  font-size: 12.5px;
  color: var(--text-3);
  text-align: center;
}

.social-more {
  padding: 8px 16px 10px;
  font-size: 11.5px;
  color: var(--text-3);
  text-align: center;
}
</style>
