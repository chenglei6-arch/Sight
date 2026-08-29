<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import CollectorPanel from './CollectorPanel.vue'
import { state, setView } from '../store'
import { PLATFORMS } from '../platforms'

const items = computed(() =>
  PLATFORMS.map((p) => {
    const meta = state.platformsMeta.find((m) => m.id === p.id)
    // 凭证状态点：绿=可用，黄=有凭证但验证失败，灰=未配置
    let statusColor = '#c9cdd3'
    if (meta) {
      if (meta.is_alive) statusColor = '#1e9e55'
      else if (meta.has_credential) statusColor = '#d9a514'
    }
    return { ...p, statusColor, hasMeta: !!meta }
  })
)
</script>

<template>
  <aside class="app-sidebar">
    <div class="brand">
      <span class="brand-icon"><Icon name="eye" :size="17" /></span>
      <div class="brand-text">
        <div class="brand-name">Sight</div>
        <div class="brand-sub">多平台数据监控</div>
      </div>
    </div>

    <nav class="nav">
      <div class="nav-label">平台</div>
      <button
        v-for="p in items"
        :key="p.id"
        class="nav-item"
        :class="{ active: state.view === p.id }"
        @click="setView(p.id)"
      >
        <span class="nav-dot" :style="{ background: p.color }" />
        <span class="nav-name">{{ p.name }}</span>
        <span class="nav-status" :style="{ background: p.statusColor }" :title="p.hasMeta ? (p.statusColor === '#1e9e55' ? '凭证可用' : p.statusColor === '#d9a514' ? '凭证已失效' : '未配置凭证') : '检测中'" />
      </button>

      <div class="nav-label">分析</div>
      <button
        class="nav-item"
        :class="{ active: state.view === 'timeline' }"
        @click="setView('timeline')"
      >
        <span class="nav-dot nav-dot-icon"><Icon name="clock" :size="14" /></span>
        <span class="nav-name">活动时间线</span>
      </button>
    </nav>

    <div class="sidebar-foot">
      <CollectorPanel />
    </div>
  </aside>
</template>

<style scoped>
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 16px 14px;
}

.brand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  background: var(--accent);
  color: #fff;
  flex-shrink: 0;
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.2px;
  line-height: 1.2;
}

.brand-sub {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.3;
}

.nav {
  flex: 1;
  overflow-y: auto;
  padding: 2px 8px 8px;
}

.nav-label {
  padding: 12px 10px 5px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  margin-bottom: 1px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  font-size: 13.5px;
  cursor: pointer;
  text-align: left;
  transition:
    background 0.13s,
    color 0.13s;
}

.nav-item:hover {
  background: var(--surface-hover);
  color: var(--text);
}

.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.nav-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex-shrink: 0;
}

.nav-dot-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin: -5.5px;
  background: var(--surface-hover);
  color: var(--text-2);
  border-radius: 6px;
}

.nav-item.active .nav-dot-icon {
  background: transparent;
  color: inherit;
}

.nav-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-status {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sidebar-foot {
  border-top: 1px solid var(--border);
  padding: 10px;
}
</style>
