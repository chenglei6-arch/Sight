/**
 * 全局状态（单例 reactive store）
 *
 * 数据加载策略：
 * - 启动时立即加载当前视图；其余已设置 UID 的平台在后台逐个串行加载
 *   （快照会被后端写入 SQLite，供时间线对比），互不阻塞首屏。
 * - 时间线依赖各平台快照，在平台数据落库后再拉取。
 */
import { reactive, watch } from 'vue'
import { api } from './api'
import { PLATFORMS, PLATFORM_MAP } from './platforms'
import { fmtClock } from './utils'

const UIDS_KEY = 'sight_uids'
const LEGACY_UIDS_KEY = 'monitor_uids' // 旧版前端遗留，做一次迁移
const AUTO_REFRESH_MS = 5 * 60 * 1000

function loadStoredUids() {
  let raw = {}
  try {
    raw = JSON.parse(localStorage.getItem(UIDS_KEY) || 'null') || {}
  } catch {
    raw = {}
  }
  if (!Object.keys(raw).length) {
    try {
      raw = JSON.parse(localStorage.getItem(LEGACY_UIDS_KEY) || 'null') || {}
    } catch {
      raw = {}
    }
  }
  const uids = {}
  for (const p of PLATFORMS) uids[p.id] = String(raw[p.id] || '')
  return uids
}

function persistUids(uids) {
  try {
    localStorage.setItem(UIDS_KEY, JSON.stringify(uids))
  } catch {
    /* 隐私模式下允许失败 */
  }
}

function blankPlatformData() {
  return {
    loading: false,
    loaded: false,
    fetchedAt: null,
    error: '',
    profile: null,
    playlists: [],
    records: null,
    events: [],
    follows: [],
    followers: [],
    errors: [], // /all 部分模块失败时后端给的 _errors
  }
}

export const state = reactive({
  view: 'netease',
  uids: loadStoredUids(),
  platformsMeta: [], // /api/platforms：[{id, name, has_credential, is_alive, login_user}]
  data: {}, // 平台 id -> blankPlatformData() + /all 载荷
  timeline: {
    loading: false,
    loaded: false,
    error: '',
    source: 'live', // live 实时对比 | stored 持久化历史
    entries: [],
    fetchedAt: null,
  },
  collector: { status: null, busy: false, logs: [] },
  detailModal: null, // { platform, id }
  editEntry: null, // { id, summary, detail }
  autoRefresh: false,
  qrOpen: false,
})

for (const p of PLATFORMS) state.data[p.id] = blankPlatformData()

// ==================== 视图切换 ====================

function isValidView(v) {
  return v === 'timeline' || !!PLATFORM_MAP[v]
}

function applyHash() {
  const h = decodeURIComponent(location.hash || '').replace(/^#\/?/, '')
  if (isValidView(h) && h !== state.view) state.view = h
}

export function setView(v) {
  if (!isValidView(v) || v === state.view) return
  state.view = v
  history.replaceState(null, '', `#/${v}`)
  loadCurrentView()
}

// ==================== 平台数据 ====================

export function currentPlatform() {
  return PLATFORM_MAP[state.view] || null
}

export async function loadPlatform(platformId, { force = false } = {}) {
  const uid = state.uids[platformId]
  if (!uid) return
  const d = state.data[platformId]
  if (d.loading || (d.loaded && !force)) return

  d.loading = true
  d.error = ''
  try {
    const payload = await api.get(`/${platformId}/all`, { uid })
    Object.assign(d, blankPlatformData(), payload, {
      loading: false,
      loaded: true,
      fetchedAt: new Date(),
      errors: payload._errors || [],
    })
    delete d._errors
  } catch (e) {
    Object.assign(d, blankPlatformData(), { error: e.message })
  }
}

async function chainLoadOtherPlatforms() {
  for (const p of PLATFORMS) {
    if (p.id === state.view) continue
    const d = state.data[p.id]
    if (state.uids[p.id] && !d.loaded && !d.loading) {
      await loadPlatform(p.id)
    }
  }
}

export function loadCurrentView() {
  if (state.view === 'timeline') {
    loadTimeline()
  } else {
    loadPlatform(state.view)
  }
}

export async function refreshCurrentView() {
  if (state.view === 'timeline') {
    await loadTimeline({ force: true })
  } else {
    await loadPlatform(state.view, { force: true })
    if (state.view) await loadTimeline({ force: true }) // 平台数据落库后同步时间线
  }
}

// ==================== UID 设置 ====================

export function setUid(platformId, uid) {
  state.uids[platformId] = uid
  persistUids(state.uids)
  state.data[platformId] = blankPlatformData()
  if (uid) loadPlatform(platformId, { force: true })
}

// ==================== 用户搜索 ====================

export async function searchUsers(platformId, keyword) {
  return api.get(`/${platformId}/search`, { keyword })
}

// ==================== 平台元数据 ====================

export async function loadPlatformsMeta() {
  try {
    state.platformsMeta = (await api.get('/platforms')) || []
  } catch {
    state.platformsMeta = []
  }
}

export function platformMeta(platformId) {
  return state.platformsMeta.find((p) => p.id === platformId) || null
}

// ==================== 时间线 ====================

export function timelineUidPairs() {
  return PLATFORMS.filter((p) => state.uids[p.id]).map((p) => `${p.id}:${state.uids[p.id]}`)
}

export async function loadTimeline({ force = false } = {}) {
  const t = state.timeline
  const pairs = timelineUidPairs()
  if (!pairs.length) {
    t.error = 'NO_UIDS'
    t.loaded = true
    t.entries = []
    return
  }
  if (t.loading || (t.loaded && !force && t.error !== 'NO_UIDS')) return

  t.loading = true
  t.error = ''
  try {
    const entries = await api.get('/timeline', {
      uids: pairs.join(','),
      limit: 60,
      source: t.source,
    })
    t.entries = Array.isArray(entries) ? entries : []
    t.loaded = true
    t.fetchedAt = new Date()
  } catch (e) {
    t.error = e.message
    t.loaded = true
  } finally {
    t.loading = false
  }
}

export function setTimelineSource(source) {
  if (state.timeline.source === source) return
  state.timeline.source = source
  state.timeline.loaded = false
  loadTimeline({ force: true })
}

export async function saveTimelineEntry(id, summary, detail) {
  await api.put(`/timeline/${id}`, { summary, detail })
  await loadTimeline({ force: true })
}

export async function deleteTimelineEntry(id) {
  await api.del(`/timeline/${id}`)
  await loadTimeline({ force: true })
}

// ==================== 歌单详情弹窗 ====================

export function openDetail(platformId, itemId) {
  state.detailModal = { platform: platformId, id: String(itemId) }
}

export function closeDetail() {
  state.detailModal = null
}

// ==================== 采集器 ====================

function collectorLog(text, kind = 'info') {
  state.collector.logs.unshift({ time: fmtClock(new Date()), text, kind })
  if (state.collector.logs.length > 40) state.collector.logs.pop()
}

function activeTargets() {
  const targets = {}
  for (const p of PLATFORMS) {
    if (state.uids[p.id]) targets[p.id] = state.uids[p.id]
  }
  return targets
}

export async function refreshCollectorStatus() {
  try {
    state.collector.status = await api.get('/collector/status')
  } catch {
    /* 状态获取失败保持原样 */
  }
}

export async function startCollector(intervalMinutes) {
  const targets = activeTargets()
  if (!Object.keys(targets).length) {
    collectorLog('启动失败：请先在平台页设置目标用户', 'warn')
    return false
  }
  state.collector.busy = true
  try {
    await api.post('/collector/start', { targets, interval_minutes: intervalMinutes })
    collectorLog(`采集器已启动（每 ${intervalMinutes} 分钟）`, 'ok')
    await refreshCollectorStatus()
    return true
  } catch (e) {
    collectorLog(`启动失败：${e.message}`, 'warn')
    return false
  } finally {
    state.collector.busy = false
  }
}

export async function stopCollector() {
  state.collector.busy = true
  try {
    await api.post('/collector/stop')
    collectorLog('采集器已停止', 'info')
    await refreshCollectorStatus()
  } catch (e) {
    collectorLog(`停止失败：${e.message}`, 'warn')
  } finally {
    state.collector.busy = false
  }
}

/**
 * 手动采集一次。
 * 采集器已运行 -> 直接触发 collect；未运行 -> 临时启动（后端会立即执行一轮采集），
 * 等待其完成后停止，并刷新当前视图数据。
 */
export async function collectOnce(intervalMinutes) {
  state.collector.busy = true
  try {
    const running = state.collector.status?.running
    if (running) {
      collectorLog('手动采集中…')
      await api.post('/collector/collect')
    } else {
      const targets = activeTargets()
      if (!Object.keys(targets).length) {
        collectorLog('采集失败：请先在平台页设置目标用户', 'warn')
        return
      }
      collectorLog('手动采集中…')
      await api.post('/collector/start', { targets, interval_minutes: intervalMinutes })
      await new Promise((r) => setTimeout(r, 3000))
      api.post('/collector/stop').catch(() => {})
    }
    collectorLog('采集完成，正在刷新数据…', 'ok')
    await refreshCollectorStatus()
    await refreshCurrentView()
  } catch (e) {
    collectorLog(`采集失败：${e.message}`, 'warn')
    refreshCollectorStatus()
  } finally {
    state.collector.busy = false
  }
}

// ==================== QQ 音乐扫码登录 ====================

export function openQrLogin() {
  state.qrOpen = true
}

export function closeQrLogin() {
  state.qrOpen = false
}

// ==================== 初始化 ====================

let autoTimer = null

export async function initStore() {
  applyHash()
  window.addEventListener('hashchange', applyHash)

  watch(
    () => state.autoRefresh,
    (on) => {
      if (autoTimer) {
        clearInterval(autoTimer)
        autoTimer = null
      }
      if (on) {
        autoTimer = setInterval(() => {
          if (state.view === 'timeline') {
            loadTimeline({ force: true })
          } else {
            loadPlatform(state.view, { force: true })
          }
        }, AUTO_REFRESH_MS)
      }
    }
  )

  // 1. 当前视图立即可见（已有 UID 时）
  loadCurrentView()

  // 2. 平台元数据兜底：未设置 UID 的平台尝试用登录用户
  await loadPlatformsMeta()
  for (const meta of state.platformsMeta) {
    const uid = meta.login_user && meta.login_user.uid ? String(meta.login_user.uid) : ''
    if (uid && !state.uids[meta.id]) {
      state.uids[meta.id] = uid
      persistUids(state.uids)
    }
  }
  loadCurrentView()

  // 3. 其余平台后台串行加载（写快照供时间线使用）
  chainLoadOtherPlatforms()
  refreshCollectorStatus()
}
