<script setup>
import { computed } from 'vue'
import Icon from './ui/Icon.vue'
import { state, setView, openSavedGraph, removeSavedGraph } from '../store'
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

// 已保存图谱条目的悬浮说明：关键词 + 规模 + 最近更新时间
function graphTitle(g) {
  const t = String(g.updated_at || '').slice(5, 16).replace('T', ' ')
  return `${g.name}\n关键词「${g.keyword || '-'}」 · ${g.node_count} 用户 · ${g.edge_count} 条关系\n更新于 ${t}（点击调出，无需重新搜索）`
}

async function removeGraph(g) {
  if (!window.confirm(`确定删除图谱「${g.name}」吗？删除后不可恢复。`)) return
  await removeSavedGraph(g.id)
}
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
      <button
        class="nav-item"
        :class="{ active: state.view === 'graph' && !state.activeGraphId }"
        @click="setView('graph')"
      >
        <span class="nav-dot nav-dot-icon"><Icon name="users" :size="14" /></span>
        <span class="nav-name">关系图谱</span>
      </button>

      <!-- 已保存的关系图谱：点击从数据库调出，不重新请求平台数据 -->
      <button
        v-for="g in state.savedGraphs"
        :key="'graph-' + g.id"
        class="nav-item nav-graph"
        :class="{ active: state.view === 'graph' && state.activeGraphId === g.id }"
        :title="graphTitle(g)"
        @click="openSavedGraph(g.id)"
      >
        <span class="nav-dot nav-dot-icon nav-graph-icon"><Icon name="share2" :size="11" /></span>
        <span class="nav-name">{{ g.name }}</span>
        <span class="nav-graph-del" title="删除该图谱" @click.stop="removeGraph(g)">
          <Icon name="x" :size="11" />
        </span>
      </button>
      <div v-if="state.savedGraphsError" class="nav-graph-err">{{ state.savedGraphsError }}</div>
    </nav>
    <div v-if="state.platformsMetaError" class="nav-graph-err">{{ state.platformsMetaError }}</div>
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

/* 已保存图谱条目：比主导航小一号，挂在"关系图谱"下面 */
.nav-graph {
  padding: 6px 10px 6px 12px;
  margin-left: 14px;
  font-size: 12.5px;
  width: auto;
}

.nav-graph-icon {
  width: 17px;
  height: 17px;
  margin: -4px;
  border-radius: 5px;
}

.nav-graph-del {
  display: none;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  color: var(--text-3);
  flex-shrink: 0;
}

.nav-graph-del:hover {
  background: var(--danger-soft, rgba(213, 55, 47, 0.12));
  color: var(--danger, #d5372f);
}

.nav-graph:hover .nav-graph-del {
  display: inline-flex;
}

.nav-graph-err {
  margin: 4px 10px 0 26px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--danger, #d5372f);
  word-break: break-all;
}
</style>
