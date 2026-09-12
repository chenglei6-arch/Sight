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

const UIDS_KEY = 'sight_uids'
const LEGACY_UIDS_KEY = 'monitor_uids' // 旧版前端遗留，做一次迁移
const TERMINAL_KEY = 'sight_terminal_open'
const AUTO_REFRESH_MS = 5 * 60 * 1000
const QUEUE_POLL_MS = 3000

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
  platformsMetaError: '', // 平台状态加载失败原因（侧边栏展示，空=正常）
  data: {}, // 平台 id -> blankPlatformData() + /all 载荷
  timeline: {
    loading: false,
    loaded: false,
    error: '',
    source: 'live', // live 实时对比 | stored 持久化历史
    entries: [],
    fetchedAt: null,
  },
  detailModal: null, // { platform, id }
  editEntry: null, // { id, summary, detail }
  autoRefresh: false,
  qrOpen: false,
  accountModal: { open: false, platform: '' }, // 账号池管理弹窗（顶栏入口，platform 可为空=默认第一个）
  savedGraphs: [], // 已保存的关系图谱元信息（侧边栏列表，不含节点数据）
  activeGraphId: null, // 当前在图谱视图里载入的持久化图谱 id
  pendingGraph: null, // 待 ViewGraph 消费的持久化图谱载荷（点击侧边栏后设置）
  savedGraphsError: '', // 图谱保存/打开/删除失败提示（侧边栏展示）
  terminalOpen: localStorage.getItem(TERMINAL_KEY) === '1', // 右侧终端面板
  terminalTab: 'logs', // 终端面板当前页签: logs | queue
  queues: [], // 各平台展开队列状态 /api/graph/expand/status（轮询）
})

for (const p of PLATFORMS) state.data[p.id] = blankPlatformData()

// ==================== 视图切换 ====================

function isValidView(v) {
  return v === 'timeline' || v === 'graph' || !!PLATFORM_MAP[v]
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
  if (state.view === 'timeline') loadTimeline()
  else if (state.view !== 'graph') loadPlatform(state.view) // graph 数据由搜索触发，无需加载
}

export async function refreshCurrentView() {
  if (state.view === 'timeline') {
    await loadTimeline({ force: true })
  } else if (state.view !== 'graph') {
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
    state.platformsMetaError = ''
  } catch (e) {
    state.platformsMeta = []
    state.platformsMetaError = `平台状态加载失败：${e.message}`
  }
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

// ==================== 关系图谱持久化 ====================

/** 刷新侧边栏的已保存图谱列表 */
export async function loadSavedGraphs() {
  try {
    state.savedGraphs = (await api.get('/graph/saved')) || []
    if (state.savedGraphs.length) state.savedGraphsError = ''
  } catch (e) {
    state.savedGraphsError = `图谱列表加载失败：${e.message}`
  }
}

/**
 * 打开一张已保存图谱：从后端 SQLite 取完整节点/边数据交给 ViewGraph 渲染，
 * 不再请求各平台搜索接口。
 */
export async function openSavedGraph(id) {
  try {
    const g = await api.get(`/graph/saved/${id}`)
    state.savedGraphsError = ''
    state.activeGraphId = g.id
    state.pendingGraph = g // 先备好数据再切视图，ViewGraph 挂载/监听到后立即消费
    if (state.view !== 'graph') setView('graph')
  } catch (e) {
    state.savedGraphsError = `打开图谱失败：${e.message}`
  }
}

export async function removeSavedGraph(id) {
  try {
    await api.del(`/graph/saved/${id}`)
    if (state.activeGraphId === id) state.activeGraphId = null
    state.savedGraphsError = ''
  } catch (e) {
    state.savedGraphsError = `删除失败：${e.message}`
  }
  await loadSavedGraphs()
}

// ==================== QQ 音乐扫码登录 ====================

export function openQrLogin() {
  state.qrOpen = true
}

export function openAccountModal(platformId = '') {
  state.accountModal.platform = platformId
  state.accountModal.open = true
}

export function closeAccountModal() {
  state.accountModal.open = false
}

// ==================== 终端面板与队列状态 ====================

export function toggleTerminal(open) {
  state.terminalOpen = typeof open === 'boolean' ? open : !state.terminalOpen
  try {
    localStorage.setItem(TERMINAL_KEY, state.terminalOpen ? '1' : '0')
  } catch {
    /* 隐私模式下允许失败 */
  }
}

export function setTerminalTab(tab) {
  state.terminalTab = tab === 'queue' ? 'queue' : 'logs'
}

export async function refreshQueues() {
  try {
    state.queues = (await api.get('/graph/expand/status'))?.queues || []
  } catch {
    /* 后端未就绪时静默，下次轮询重试 */
  }
}

/** 队列汇总：总排队 / 总执行中 / 熔断平台数 */
export function queueSummary(queues = state.queues) {
  let pending = 0
  let running = 0
  let paused = 0
  for (const q of queues) {
    pending += q.pending || 0
    running += q.running || 0
    if (q.paused) paused += 1
  }
  return { pending, running, paused, busy: pending + running }
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
  loadSavedGraphs()

  // 4. 队列状态轮询（TopBar 角标 + 终端面板队列页签共用）
  refreshQueues()
  setInterval(refreshQueues, QUEUE_POLL_MS)
}
