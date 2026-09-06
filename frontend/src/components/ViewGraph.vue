<script setup>
/**
 * 关系图谱视图：
 * - 输入关键词，后端 /api/graph/search 并行搜索各平台用户并做跨平台同人归并
 * - ECharts graph（力导向）渲染：中心节点=关键词，用户节点按平台着色，节点大小~粉丝数
 * - 边：hit 命中（灰）、same 跨平台完全同名（红实线）、alike 昵称相似（红虚线）
 * - 点击节点弹出信息卡，可一键"设为监测目标"跳回平台视图
 * - 图谱命名持久化：生成时按名称存入后端 SQLite（同名覆盖），侧边栏点击可免请求调出
 *   展开社交关系后自动静默更新同一条记录，展开状态（含已展开/已互查标记）一并持久化
 */
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import Icon from './ui/Icon.vue'
import UserAvatar from './ui/UserAvatar.vue'
import CookieModal from './CookieModal.vue'
import { api } from '../api'
import { state, setUid, setView, loadSavedGraphs } from '../store'
import { PLATFORMS, PLATFORM_MAP } from '../platforms'
import { fmtNum } from '../utils'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

// 各平台用户主页链接（无稳定主页的平台不提供）
const USER_LINKS = {
  bilibili: (n) => `https://space.bilibili.com/${n.uid}`,
  netease: (n) => `https://music.163.com/#/user/home?id=${n.uid}`,
  weibo: (n) => `https://weibo.com/u/${n.uid}`,
  xhs: (n) => `https://www.xiaohongshu.com/user/profile/${n.uid}`,
  douyin: (n) => (n.sec_uid ? `https://www.douyin.com/user/${n.sec_uid}` : ''),
}

// 支持获取任意用户关注/粉丝列表的平台（xhs/qqmusic/genshin 后端不支持）
const SOCIAL_SUPPORT = { bilibili: true, netease: true, weibo: true, douyin: true }
const SOCIAL_LIMIT = 100 // 每次展开拉取的关注/粉丝数量

const ACCENT = '#3565e0'
const SAME_COLOR = '#d5372f'
const MUTUAL_COLOR = '#1e9e55' // 互相关注：绿色实线
// 粉丝达到该量级视为公众账号/大V：与监控对象直接关联的价值低，节点缩小+灰色淡化（可手动还原/隐藏）
const IRRELEVANT_FANS = 10000
const isIrrelevant = (n) => !!n && n.platform !== 'keyword' && Number(n.fans) >= IRRELEVANT_FANS

// 判断用户节点是否在当前视图下被隐藏/排除
function isNodeHidden(n) {
  if (!n) return false
  const id = n.id || `${n.platform}:${n.uid}`
  return hiddenNodeIds.has(id) || isIrrelevant(n)
}
// 手动把选中的节点从图中"取消"（此后不展示、不参与展开，也不随持久化保存）
function hideSelectedNode() {
  if (!selected.value) return
  hiddenNodeIds.add(selectedId.value)
  const removed = result.value?.nodes.filter((n) => (n.id || `${n.platform}:${n.uid}`) === selectedId.value)
  if (removed?.length) selected.value = null
  // 展示层重渲染；结果数据里仍保留该节点，避免破坏后续展开 merge 的边索引
  if (chart && result.value) render()
  persistGraph({ quiet: true })
}

// ==================== 搜索状态 ====================

const keyword = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null) // 后端 /api/graph/search 原始响应（后续展开结果会合并进来）
const lastSearched = ref('')
const disabledPlatforms = ref([]) // 关闭的平台 id
const selected = ref(null) // 当前点中的用户节点
const searchFailedMsg = ref('') // 整体搜索请求失败的原因（有旧图时不打断浏览，只在状态条提示）
const dismissedKeys = reactive(new Set()) // 用户手动关闭的状态条提示
// 用户手动"不看"的节点 id 集合（排除节点后不参与展示与持久化）；清除不受粉丝数影响
const hiddenNodeIds = reactive(new Set())
const hiddenCount = computed(() => hiddenNodeIds.size)

// ==================== 图谱命名持久化 ====================

const graphName = ref('') // 保存到侧边栏时使用的图谱名称，默认同关键词
const saving = ref(false)
const saveMsg = ref('') // 最近一次保存的结果提示（进状态条，可关闭）
let saveQueued = false // 保存进行中又触发了新保存时，结束后补一次，保证最终状态落库

function currentGraphName() {
  return (graphName.value.trim() || lastSearched.value || '未命名图谱').slice(0, 60)
}

/**
 * 把当前图（节点/边 + 已展开标记）持久化到后端；同名图谱覆盖更新。
 * quiet=true 用于展开后的自动同步，成功时不弹提示，失败仍然告知。
 * 返回保存记录 id，失败返回 null。
 */
async function persistGraph({ quiet = false } = {}) {
  if (!result.value || !nodeCount.value) return null
  if (saving.value) {
    saveQueued = true // 上一次保存还没回来，等它结束后补存最新状态
    return null
  }
  const name = currentGraphName()
  graphName.value = name
  saving.value = true
  try {
    const res = await api.post('/graph/save', {
      name,
      keyword: result.value.keyword || lastSearched.value,
      // 图数据之外附带展开状态与手动隐藏：调出时还原"已展开/已互查/已排除"标记
      data: {
        ...result.value,
        expanded_keys: [...expandedKeys],
        interchecked_ids: [...intercheckedIds],
        hidden_ids: [...hiddenNodeIds],
      },
    })
    state.activeGraphId = res.id
    if (!quiet) saveMsg.value = `已保存为「${name}」，可在侧边栏随时调出`
    loadSavedGraphs()
    return res.id
  } catch (e) {
    saveMsg.value = `保存失败：${e.message}`
    return null
  } finally {
    saving.value = false
    if (saveQueued) {
      saveQueued = false
      persistGraph({ quiet: true })
    }
  }
}

/** 消费侧边栏点开的持久化图谱：直接用库里的节点/边渲染，不发平台请求 */
function consumePendingGraph() {
  const g = state.pendingGraph
  if (!g || !g.data) return
  state.pendingGraph = null
  bulk.stop = true // 若一键展开还在跑，立即停下
  selected.value = null
  error.value = ''
  searchFailedMsg.value = ''
  saveMsg.value = ''
  for (const k of Object.keys(expandMsgs)) delete expandMsgs[k]
  bulkMsg.value = ''
  viewFilter.value = 'all'
  expandedKeys.clear()
  intercheckedIds.clear()
  hiddenNodeIds.clear()
  dismissedKeys.clear()
  keyword.value = g.data.keyword || ''
  lastSearched.value = g.data.keyword || ''
  graphName.value = g.name || ''
  result.value = g.data
  // 还原保存时的展开/隐藏状态：展开高亮与互查去重恢复，手动排除的节点不重新出现
  for (const k of g.data.expanded_keys || []) expandedKeys.add(k)
  for (const k of g.data.interchecked_ids || []) intercheckedIds.add(k)
  for (const k of g.data.hidden_ids || []) hiddenNodeIds.add(k)
  state.activeGraphId = g.id
  nextTick(() => render())
}

watch(() => state.pendingGraph, consumePendingGraph)

function dismissStatus(key) {
  dismissedKeys.add(key)
}

// 点击状态条里的平台错误/提示 → 打开该平台 Cookie 配置（保存后自动重搜）
const cookieModal = reactive({ open: false, platform: '' })

function openCookieConfig(pid) {
  if (!pid) return
  cookieModal.platform = pid
  cookieModal.open = true
}

async function onCookieSaved() {
  if (!lastSearched.value) return
  keyword.value = lastSearched.value
  await doSearch()
}

// 社交展开状态：已展开的类型与已互查过的邻居（跨平台去重 key: "platform:uid[:type]"）
const expandedKeys = reactive(new Set())
const intercheckedIds = reactive(new Set())
// 多节点并行展开：每个节点有独立的忙碌标记和结果消息（key 均为 "platform:uid"）
const expandBusyIds = reactive(new Set())
const expandMsgs = reactive({})

// 视图分层：'all' 或单个平台 id（只显示该平台子图 + 关键词中心）
const viewFilter = ref('all')
// 布局模式：force 力导向混排 | layer 按平台分区（预计算坐标，不可拖拽重排）
const layoutMode = ref('force')
// 全图一键展开
const bulk = reactive({ busy: false, done: 0, total: 0, stop: false })
const bulkMsg = ref('')

// 平台选择 chips：附带凭证配置状态（未配置 Cookie 的平台搜索大概率失败，提前告知）
const chipPlatforms = computed(() =>
  PLATFORMS.map((p) => {
    const meta = state.platformsMeta.find((m) => m.id === p.id)
    return { id: p.id, name: p.name, color: p.color, noCookie: !!(meta && !meta.has_credential) }
  })
)

function togglePlatform(id) {
  const i = disabledPlatforms.value.indexOf(id)
  if (i >= 0) disabledPlatforms.value.splice(i, 1)
  else if (disabledPlatforms.value.length < chipPlatforms.length - 1)
    disabledPlatforms.value.push(id) // 至少保留一个平台
}

async function doSearch() {
  const kw = keyword.value.trim()
  if (!kw || loading.value) return
  loading.value = true
  error.value = ''
  searchFailedMsg.value = ''
  saveMsg.value = ''
  selected.value = null
  for (const k of Object.keys(expandMsgs)) delete expandMsgs[k]
  bulkMsg.value = ''
  viewFilter.value = 'all'
  expandedKeys.clear()
  intercheckedIds.clear()
  hiddenNodeIds.clear()
  dismissedKeys.clear()
  lastSearched.value = kw
  // 换了关键词就是一张新图：清掉继承自上一张图的名称，避免同名误覆盖旧图谱
  if (result.value && result.value.keyword && result.value.keyword !== kw) graphName.value = ''
  state.activeGraphId = null // 新生成的图尚未保存，等待下方自动持久化后回填
  try {
    const platforms = chipPlatforms.value.map((p) => p.id).filter((id) => !disabledPlatforms.value.includes(id))
    // 搜索期间保留旧图继续可交互；失败也不清空 result，错误只进状态条
    result.value = await api.get('/graph/search', { keyword: kw, platforms: platforms.join(',') })
    await nextTick()
    render()
    // 生成即持久化：按名称输入框的名称（默认同关键词）入库，同名覆盖，供侧边栏调出
    if (visibleUserNodes().length) await persistGraph()
    else saveMsg.value = '未搜到用户节点，本次未保存图谱'
  } catch (e) {
    if (result.value) searchFailedMsg.value = e.message
    else error.value = e.message
  } finally {
    loading.value = false
  }
}

// ==================== 社交关系展开 ====================

const selectedId = computed(() =>
  selected.value ? `${selected.value.platform}:${selected.value.uid}` : ''
)

// 当前选中节点的展开结果消息（每个节点独立，互不覆盖）
const selectedExpandMsg = computed(() => (selected.value ? expandMsgs[selectedId.value] || '' : ''))
const selectedExpandMsgIsError = computed(() =>
  /^(未获取到数据|展开失败)/.test(selectedExpandMsg.value)
)

// 正在展开的节点昵称（状态条汇总展示用）
const expandBusyNames = computed(() =>
  [...expandBusyIds].map((id) => result.value?.nodes.find((n) => n.id === id)?.nickname || id)
)

// 当前图中实际有结果的平台（用于视图筛选 chips）
const presentPlatforms = computed(() => {
  if (!result.value) return []
  const ids = new Set(result.value.nodes.map((n) => n.platform))
  return PLATFORMS.filter((p) => ids.has(p.id))
})

// 当前筛选视图下可见的用户节点
function visibleUserNodes() {
  if (!result.value) return []
  return result.value.nodes.filter(
    (n) => n.platform !== 'keyword' && (viewFilter.value === 'all' || n.platform === viewFilter.value)
  )
}

// 选中节点当前图内的关注/被关注数（含互相关注的双向边）
const selectedCounts = computed(() => {
  if (!selected.value) return null
  let following = 0
  let followers = 0
  for (const e of deriveDisplayEdges()) {
    if (e.relation !== 'follows' && e.relation !== 'mutual') continue
    if (e.source === selectedId.value) following++
    if (e.target === selectedId.value) followers++
  }
  return { following, followers }
})

// 图内与选中节点相邻的同平台 uid（用于补查邻居间关系）
function adjacentSamePlatformUids(n) {
  const id = `${n.platform}:${n.uid}`
  const out = new Set()
  for (const e of deriveDisplayEdges()) {
    if (e.relation !== 'follows' && e.relation !== 'mutual') continue
    if (e.source === id && e.target.startsWith(n.platform + ':')) out.add(e.target.split(':')[1])
    if (e.target === id && e.source.startsWith(n.platform + ':')) out.add(e.source.split(':')[1])
  }
  return [...out]
}

function mergeGraph(payload) {
  const nodes = result.value.nodes
  const edges = result.value.edges
  const ids = new Set(nodes.map((n) => n.id))
  const ekeys = new Set(edges.map((e) => `${e.source}|${e.target}|${e.relation}`))
  let addedNodes = 0
  let addedEdges = 0
  for (const n of payload.nodes || []) {
    if (ids.has(n.id)) continue
    ids.add(n.id)
    nodes.push(n)
    addedNodes++
  }
  const newEdges = [...(payload.edges || []), ...((payload.intercheck && payload.intercheck.edges) || [])]
  for (const e of newEdges) {
    const k = `${e.source}|${e.target}|${e.relation}`
    if (ekeys.has(k)) continue
    ekeys.add(k)
    edges.push(e)
    addedEdges++
  }
  return { nodes: addedNodes, edges: addedEdges }
}

async function expandSocial(type) {
  const n = selected.value
  if (!n || !result.value) return
  const nid = `${n.platform}:${n.uid}`
  if (expandBusyIds.has(nid)) return // 该节点已在展开中，其余节点不受影响、可同时展开
  expandBusyIds.add(nid)
  expandMsgs[nid] = ''
  try {
    const knownIds = result.value.nodes.filter((x) => x.platform === n.platform).map((x) => x.id)
    const platformPrefix = n.platform + ':'
    const payload = await api.post('/graph/social', {
      platform: n.platform,
      uid: n.uid,
      follows_limit: type === 'followers' ? 0 : SOCIAL_LIMIT,
      followers_limit: type === 'follows' ? 0 : SOCIAL_LIMIT,
      known_ids: knownIds,
      intercheck_skip: [...intercheckedIds]
        .filter((k) => k.startsWith(platformPrefix))
        .map((k) => k.slice(platformPrefix.length)),
      intercheck_extra: adjacentSamePlatformUids(n),
    })
    const added = mergeGraph(payload)
    for (const t of payload.intercheck?.targets || []) intercheckedIds.add(n.platform + ':' + t)
    if (type === 'both') {
      expandedKeys.add(`${n.platform}:${n.uid}:follows`)
      expandedKeys.add(`${n.platform}:${n.uid}:followers`)
    } else {
      expandedKeys.add(`${n.platform}:${n.uid}:${type}`)
    }
    const ic = payload.intercheck || {}
    const errs = Object.entries(payload.errors || {})
    if (added.nodes + added.edges === 0 && !ic.checked) {
      expandMsgs[nid] = errs.length
        ? `未获取到数据：${errs.map(([, v]) => v).join('；')}`
        : '未获取到数据（对方可能隐藏了列表，或平台需要登录 Cookie）'
    } else {
      expandMsgs[nid] =
        `新增 ${added.nodes} 人 · ${added.edges} 条关注边 · 邻居互查命中 ${ic.edges?.length || 0} 条` +
        (ic.total ? `（查了 ${ic.checked}/${ic.total} 个邻居）` : '') +
        (errs.length ? ` · 部分失败：${errs.map(([, v]) => v).join('；')}` : '')
    }
    chart?.setOption(buildOption())
    // 展开结果即时同步到已保存图谱，之后从侧边栏调出不会丢
    persistGraph({ quiet: true })
  } catch (e) {
    expandMsgs[nid] = '展开失败：' + e.message
  } finally {
    expandBusyIds.delete(nid)
  }
}

// ==================== 全图一键展开 ====================

function intercheckSkipList(platform) {
  const prefix = platform + ':'
  return [...intercheckedIds]
    .filter((k) => k.startsWith(prefix))
    .map((k) => k.slice(prefix.length))
}

async function bulkExpand() {
  if (bulk.busy) {
    bulk.stop = true
    return
  }
  const targets = visibleUserNodes().filter(
    (n) =>
      SOCIAL_SUPPORT[n.platform] &&
      !expandBusyIds.has(`${n.platform}:${n.uid}`) && // 该节点正在单独展开，跳过避免重复拉取
      !expandedKeys.has(`${n.platform}:${n.uid}:follows`)
  )
  if (!targets.length) {
    bulkMsg.value = '没有可展开的节点（当前视图下所有可查用户都已展开，或平台不支持）'
    return
  }
  bulk.busy = true
  bulk.stop = false
  bulk.done = 0
  bulk.total = targets.length
  bulkMsg.value = `开始展开 ${targets.length} 个节点（每个关注+粉丝各 20 人）…`
  let addNodes = 0
  let addEdges = 0
  let icHits = 0
  let failed = 0
  for (const n of targets) {
    if (bulk.stop) break
    bulkMsg.value = `展开中 ${bulk.done + 1}/${bulk.total}：${n.nickname}`
    try {
      const knownIds = result.value.nodes.filter((x) => x.platform === n.platform).map((x) => x.id)
      const payload = await api.post('/graph/social', {
        platform: n.platform,
        uid: n.uid,
        follows_limit: 20,
        followers_limit: 20,
        known_ids: knownIds,
        intercheck_skip: intercheckSkipList(n.platform),
        intercheck_extra: adjacentSamePlatformUids(n),
        intercheck_limit: 8,
        intercheck_follow_limit: 30,
      })
      const added = mergeGraph(payload)
      for (const t of payload.intercheck?.targets || []) intercheckedIds.add(n.platform + ':' + t)
      expandedKeys.add(`${n.platform}:${n.uid}:follows`)
      expandedKeys.add(`${n.platform}:${n.uid}:followers`)
      addNodes += added.nodes
      addEdges += added.edges
      icHits += payload.intercheck?.edges?.length || 0
      chart?.setOption(buildOption())
    } catch {
      failed++
    }
    bulk.done++
  }
  bulk.busy = false
  const scope = viewFilter.value === 'all' ? '' : `（仅 ${PLATFORM_MAP[viewFilter.value]?.name} 视图）`
  bulkMsg.value =
    `${bulk.stop ? '已停止' : '全图展开完成'}${scope}：新增 ${addNodes} 人 · ${addEdges} 条关注边 · 互查命中 ${icHits} 条` +
    (failed ? ` · 失败 ${failed} 个节点` : '')
  // 全图展开（含中途停止）的结果整体同步到已保存图谱
  if (addNodes + addEdges + icHits > 0) persistGraph({ quiet: true })
}

// ==================== ECharts ====================

const stageEl = ref(null)
let chart = null
let ro = null

// 力导向参数（截图右侧面板同款滑杆）
const forceParams = reactive({ repulsion: 260, gravity: 0.1, edgeLength: 100 })

const nodeCount = computed(() => {
  if (!result.value) return 0
  // 展示给用户的节点数：排除手动隐藏，大V弱相关照常计入（用户可再次点开查看）
  return result.value.nodes.filter((n) => n.platform !== 'keyword' && !hiddenNodeIds.has(n.id)).length
})
const edgeCount = computed(() => {
  if (!result.value) return 0
  return deriveDisplayEdges().filter(
    (e) => !hiddenNodeIds.has(e.source) && !hiddenNodeIds.has(e.target)
  ).length
})
const sameCount = computed(() =>
  result.value ? deriveDisplayEdges().filter((e) => e.relation === 'same').length : 0
)
const followsCount = computed(() => {
  if (!result.value) return 0
  const all = deriveDisplayEdges()
  const follows = all.filter((e) => e.relation === 'follows').length
  const mutual = all.filter((e) => e.relation === 'mutual').length
  return follows + mutual
})
// /graph/search 返回的各平台搜索失败信息（{ 平台id: 错误消息 }）
const searchErrors = computed(() =>
  result.value ? Object.entries(result.value.errors || {}) : []
)

// ==================== 状态条（任务进度 + 错误/提示，紧凑可关闭） ====================

// 当前正在执行的任务文案；空字符串表示空闲（单节点展开与全图展开可同时进行，一并展示）
const taskText = computed(() => {
  if (loading.value) return `正在跨平台搜索「${lastSearched.value || keyword.value}」…个别平台可能较慢`
  const parts = []
  if (expandBusyIds.size) {
    const names = expandBusyNames.value
    parts.push(
      `正在展开 ${names.length} 个节点的关注/粉丝：${names.slice(0, 3).join('、')}${names.length > 3 ? ' 等' : ''}…`
    )
  }
  if (bulk.busy) parts.push(bulkMsg.value)
  return parts.join(' · ')
})

// 参与了搜索但一无所获、且根本没配 Cookie 的平台（大概率原因就是缺 Cookie）
const noCookieSearched = computed(() => {
  if (!result.value) return []
  const produced = new Set([
    ...((result.value.platforms || [])),
    ...Object.keys(result.value.errors || {}),
  ])
  const metaById = new Map(state.platformsMeta.map((m) => [m.id, m]))
  return (result.value.searched || []).filter((pid) => {
    const meta = metaById.get(pid)
    return !produced.has(pid) && meta && meta.has_credential === false
  })
})

// 状态条内容：请求失败 / 各平台错误 / 缺 Cookie 提示 / 缓存命中 / 保存结果，全部可单独关闭
const stripItems = computed(() => {
  const items = []
  if (saveMsg.value && !dismissedKeys.has('save'))
    items.push({
      key: 'save',
      kind: saveMsg.value.includes('失败') ? 'err' : 'ok',
      color: saveMsg.value.includes('失败') ? '#d5372f' : '#1e9e55',
      text: saveMsg.value,
    })
  if (searchFailedMsg.value && !dismissedKeys.has('req'))
    items.push({ key: 'req', kind: 'err', color: '#d5372f', text: `搜索请求失败：${searchFailedMsg.value}` })
  for (const [pid, msg] of searchErrors.value) {
    const key = 'err:' + pid
    if (dismissedKeys.has(key)) continue
    items.push({
      key,
      kind: 'err',
      color: PLATFORM_MAP[pid]?.color || '#d5372f',
      text: `${PLATFORM_MAP[pid]?.name || pid}：${msg}`,
      platform: pid,
    })
  }
  for (const pid of noCookieSearched.value) {
    const key = 'nc:' + pid
    if (dismissedKeys.has(key)) continue
    items.push({
      key,
      kind: 'notice',
      color: '#c9cdd3',
      text: `${PLATFORM_MAP[pid]?.name || pid}：未配置 Cookie，无法搜索`,
      platform: pid,
    })
  }
  const cached = result.value?.cached || []
  if (cached.length && !dismissedKeys.has('cached'))
    items.push({
      key: 'cached',
      kind: 'notice',
      color: '#9aa1ab',
      text: `${cached.map((p) => PLATFORM_MAP[p]?.name || p).join('、')} 的结果来自 30 分钟内缓存`,
    })
  return items
})

function nodeSize(fans) {
  const f = Number(fans) || 0
  return 12 + Math.min(28, f > 0 ? Math.log10(f) * 5 : 0)
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

// ==================== 展示层边派生 ====================
// 不改动 result 存储，每次渲染前推导：
// 1) 同平台双向关注 → 合并为一条 mutual（互相关注）边
// 2) 跨平台归一化昵称完全一致但没有 same/alike 边 → 补 same 边（后端只在搜索阶段匹配，展开拉进来的新节点需要补算）

const pairKey = (a, b) => (a < b ? `${a}\u0001${b}` : `${b}\u0001${a}`)
const platOf = (id) => String(id || '').split(':')[0]

function normNick(name) {
  return String(name || '')
    .normalize('NFKC')
    .replace(/\s+/g, '')
    .toLowerCase()
}

function deriveDisplayEdges() {
  const data = result.value
  if (!data) return []
  const out = []
  const seen = new Set()
  const follows = []
  for (const e of data.edges || []) {
    if (e.relation !== 'follows') continue
    const k = `${e.source}\u0001${e.target}`
    if (seen.has(k)) continue
    seen.add(k)
    follows.push(e)
  }
  // 互相关注：同平台 a→b 与 b→a 同时存在 → 保留一条绿色 mutual 边
  // 反向索引存"正向" key → 边下标；查"反向" key 找到对应边
  const revIndex = new Map()
  follows.forEach((e, i) => revIndex.set(`${e.source}\u0001${e.target}`, i))
  const consumed = new Set()
  for (let i = 0; i < follows.length; i++) {
    if (consumed.has(i)) continue
    const e = follows[i]
    const j = revIndex.get(`${e.target}\u0001${e.source}`)
    const samePlatform = platOf(e.source) === platOf(e.target)
    if (j !== undefined && j !== i && !consumed.has(j) && samePlatform) {
      consumed.add(i)
      consumed.add(j)
      out.push({ source: e.source, target: e.target, relation: 'mutual' })
    } else {
      consumed.add(i)
      out.push({ ...e })
    }
  }
  // 其余原始边（hit / same / alike）保持原样
  for (const e of data.edges || []) {
    if (e.relation === 'follows') continue
    out.push({ ...e })
  }
  // 补算跨平台完全同名：为展开后新增的节点匹配图中其他平台节点
  const normBuckets = new Map()
  for (const n of data.nodes || []) {
    if (n.platform === 'keyword') continue
    const norm = normNick(n.nickname || '')
    if (!norm) continue
    const id = n.id || `${n.platform}:${n.uid}`
    if (!normBuckets.has(norm)) normBuckets.set(norm, [])
    normBuckets.get(norm).push({ id, platform: n.platform })
  }
  const hasAlias = new Set()
  for (const e of out) if (e.relation === 'same' || e.relation === 'alike') hasAlias.add(pairKey(e.source, e.target))
  for (const list of normBuckets.values()) {
    if (list.length < 2) continue
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        if (list[i].platform === list[j].platform) continue // 同平台重名不连，避免误判
        const k = pairKey(list[i].id, list[j].id)
        if (hasAlias.has(k)) continue
        hasAlias.add(k)
        out.push({ source: list[i].id, target: list[j].id, relation: 'same' })
      }
    }
  }
  return out
}

// 分层布局：关键词居中，各平台节点簇沿椭圆环绕，簇内按连接度排同心环
function computeLayerPositions(data) {
  const pos = { keyword: { x: 0, y: 0 } }
  const users = data.nodes.filter((n) => n.platform !== 'keyword')
  const deg = {}
  for (const e of data.edges) {
    deg[e.source] = (deg[e.source] || 0) + 1
    deg[e.target] = (deg[e.target] || 0) + 1
  }
  const platformOrder = PLATFORMS.filter((p) => users.some((u) => u.platform === p.id)).map((p) => p.id)
  const R = 430
  const ringGap = 62
  const caps = [1, 6, 12, 18, 26, 34]
  platformOrder.forEach((pid, pi) => {
    const baseAng = (2 * Math.PI * pi) / platformOrder.length - Math.PI / 2
    const px = R * Math.cos(baseAng)
    const py = R * 0.72 * Math.sin(baseAng)
    const list = users
      .filter((u) => u.platform === pid)
      .sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0))
    let idx = 0
    for (let ring = 0; idx < list.length; ring++) {
      const cap = ring < caps.length ? caps[ring] : caps[caps.length - 1] + (ring - caps.length + 1) * 8
      const radius = ring * ringGap
      for (let j = 0; j < cap && idx < list.length; j++, idx++) {
        const a = (2 * Math.PI * j) / cap + baseAng
        pos[list[idx].id] =
          radius === 0
            ? { x: px, y: py }
            : { x: px + radius * Math.cos(a), y: py + radius * Math.sin(a) }
      }
    }
  })
  return pos
}

function buildOption() {
  const data = result.value
  if (!data) return null

  const categories = [{ name: '关键词' }, ...PLATFORMS.map((p) => ({ name: p.name }))]
  const catIndex = (pid) => (pid === 'keyword' ? 0 : PLATFORMS.findIndex((p) => p.id === pid) + 1)
  const platformName = (pid) => (pid === 'keyword' ? '关键词' : PLATFORM_MAP[pid]?.name || pid)
  const rawById = new Map(data.nodes.map((n) => [n.id, n]))
  const layer = layoutMode.value === 'layer'
  const layerPos = layer ? computeLayerPositions(data) : null
  const displayEdges = deriveDisplayEdges()

  // 视图筛选：只保留关键词 + 对应平台节点；手动隐藏的节点排除；大V仍在图内但灰化缩小
  const visibleIds = new Set(
    data.nodes
      .filter(
        (n) =>
          n.platform === 'keyword' ||
          (!hiddenNodeIds.has(n.id) && (viewFilter.value === 'all' || n.platform === viewFilter.value))
      )
      .map((n) => n.id)
  )

  // 边的关系说明（悬浮连线时展示）
  const edgeTip = (e) => {
    const s = rawById.get(e.source)
    const t = rawById.get(e.target)
    if (!s || !t) return ''
    const sn = esc(s.nickname || s.uid)
    const tn = esc(t.nickname || t.uid)
    if (e.relation === 'mutual')
      return `<div class='g-tip-name'>${sn} ⇄ ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 与 <b>${tn}</b> 互相关注</div>`
    if (e.relation === 'follows')
      return `<div class='g-tip-name'>${sn} → ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 关注了 <b>${tn}</b>（${esc(platformName(s.platform))}）</div>`
    if (e.relation === 'same')
      return `<div class='g-tip-name'>${sn} ↔ ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 与 <b>${tn}</b> 跨平台昵称完全相同，疑似同一人的多个账号</div>`
    if (e.relation === 'alike')
      return `<div class='g-tip-name'>${sn} ↔ ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 与 <b>${tn}</b> 昵称相似，可能是同一人的多个账号</div>`
    return `<div class='g-tip-rel'>关键词「${esc(data.keyword)}」搜索命中 <b>${tn}</b></div>`
  }

  const nodes = data.nodes
    .filter((n) => visibleIds.has(n.id))
    .map((n) => {
      const key = `${n.platform}:${n.uid}`
      const expanded = expandedKeys.has(key + ':follows') || expandedKeys.has(key + ':followers')
      const hidden = hiddenNodeIds.has(n.id) // 手动隐藏的节点不会进入此分支；大V弱相关走 irrelevant
      const irrelevant = isIrrelevant(n)
      let itemStyle
      if (irrelevant) {
        // 粉丝 ≥1 万的大V/公众账号：灰色小圆点淡化展示，降低视觉权重
        itemStyle = { color: '#e3e6ea', borderColor: '#aeb5bf', borderWidth: 1 }
      }
      if (expanded)
        itemStyle = { ...(itemStyle || {}), borderColor: ACCENT, borderWidth: 2 }
      const base = {
        ...n,
        category: catIndex(n.platform),
        symbolSize: n.platform === 'keyword' ? 42 : irrelevant ? 7 : nodeSize(n.fans),
        raw: n,
        itemStyle,
        label: irrelevant ? { show: false } : undefined,
      }
      if (layer && layerPos[n.id]) {
        base.x = layerPos[n.id].x
        base.y = layerPos[n.id].y
      }
      return base
    })

  const links = displayEdges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => {
    if (e.relation === 'mutual')
      return { ...e, lineStyle: { color: MUTUAL_COLOR, width: 2.2, opacity: 0.95, curveness: 0.1 } }
    if (e.relation === 'follows')
      return { ...e, lineStyle: { color: ACCENT, width: 1.3, opacity: 0.5, curveness: 0.1 } }
    if (e.relation === 'same')
      return { ...e, lineStyle: { color: SAME_COLOR, width: 2, opacity: 0.9, curveness: 0.12 } }
    if (e.relation === 'alike')
      return { ...e, lineStyle: { color: SAME_COLOR, width: 1.2, type: 'dashed', opacity: 0.7, curveness: 0.18 } }
    return { ...e, lineStyle: { color: 'source', width: 1, opacity: 0.3, curveness: 0.08 } }
  })

  return {
    color: [ACCENT, ...PLATFORMS.map((p) => p.color)],
    tooltip: {
      confine: true,
      trigger: 'item',
      textStyle: { fontSize: 12 },
      formatter: (p) => {
        if (p.dataType === 'edge') {
          return `<div class='g-tip'><div class='g-tip-main'>${edgeTip(p.data)}</div></div>`
        }
        const n = p.data?.raw
        if (!n) return ''
        const fans = Number(n.fans) > 0 ? `<div class='g-tip-fans'>${fmtNum(Number(n.fans))} 粉丝</div>` : ''
        const warn = isIrrelevant(n)
          ? `<div class='g-tip-warn'>粉丝过万，疑似公众账号/大V，与监控对象直接关联可能性低（已灰化缩小）</div>`
          : ''
        const sig = n.signature ? `<div class='g-tip-sig'>${esc(n.signature)}</div>` : ''
        return (
          `<div class='g-tip'>` +
          `<img class='g-tip-avatar' src='${esc(n.avatarUrl)}' referrerpolicy='no-referrer' onerror=\"this.style.display='none'\" />` +
          `<div class='g-tip-main'><div class='g-tip-name'>${esc(n.nickname)}</div>` +
          `<div class='g-tip-plat'>${esc(platformName(n.platform))}</div>${fans}${warn}${sig}</div></div>`
        )
      },
    },
    series: [
      {
        type: 'graph',
        layout: layer ? 'none' : 'force',
        roam: true,
        draggable: !layer,
        categories,
        data: nodes,
        links,
        force: {
          repulsion: forceParams.repulsion,
          gravity: forceParams.gravity,
          edgeLength: forceParams.edgeLength,
          layoutAnimation: !layer,
        },
        label: {
          show: true,
          position: 'bottom',
          fontSize: 11,
          color: '#5c6470',
          formatter: (p) => (p.data.raw.nickname || '').slice(0, 12),
        },
        labelLayout: { hideOverlap: true },
        emphasis: {
          focus: 'adjacency',
          label: { fontWeight: 600, color: '#1c1f23' },
          lineStyle: { width: 2.5, opacity: 1 },
        },
        lineStyle: { width: 1, curveness: 0.1 },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 5,
        scaleLimit: { min: 0.3, max: 6 },
      },
    ],
  }
}

function render() {
  if (!chart) return
  const option = buildOption()
  if (!option) return
  chart.clear()
  chart.setOption(option)
}

function relayout() {
  render() // clear + 重新随机布局，力导向重新收敛
}

function exportPng() {
  if (!chart || !nodeCount.value) return
  const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' })
  const a = document.createElement('a')
  a.href = url
  a.download = `sight-关系图-${lastSearched.value || 'graph'}.png`
  a.click()
}

watch(forceParams, () => {
  if (!chart || !result.value) return
  chart.setOption({
    series: [
      {
        force: {
          repulsion: forceParams.repulsion,
          gravity: forceParams.gravity,
          edgeLength: forceParams.edgeLength,
        },
      },
    ],
  })
})

// 切换视图筛选 / 布局模式：整体重渲染（分层布局坐标确定，力导向重新收敛）
watch([viewFilter, layoutMode], () => {
  if (!chart || !result.value) return
  selected.value = null
  render()
})

function onNodeClick(params) {
  if (params.dataType !== 'node') return
  const n = params.data?.raw
  selected.value = n && n.platform !== 'keyword' ? n : null
  // 消息按节点独立保存：切换选中节点不影响其他节点的展开过程与结果
}

function adoptTarget() {
  if (!selected.value) return
  setUid(selected.value.platform, selected.value.uid)
  setView(selected.value.platform)
}

function homeUrl(n) {
  const fn = USER_LINKS[n.platform]
  return fn ? fn(n) : ''
}

onMounted(() => {
  chart = echarts.init(stageEl.value)
  chart.on('click', onNodeClick)
  ro = new ResizeObserver(() => chart && chart.resize())
  ro.observe(stageEl.value)
  if (import.meta.env.DEV) window.__vgChart = chart // 调试句柄：控制台可直接检查/驱动图表
  // 侧边栏点击已保存图谱后切到这里：立即用库内数据渲染
  consumePendingGraph()
})

onBeforeUnmount(() => {
  ro?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="view-graph">
    <div class="vg-toolbar">
      <div class="vg-field">
        <Icon name="search" :size="14" class="vg-icon" />
        <input
          v-model="keyword"
          class="vg-input"
          placeholder="输入关键词，跨平台搜索用户生成关系图"
          @keydown.enter="doSearch"
        />
        <button class="btn btn-sm vg-btn" :disabled="loading || !keyword.trim()" @click="doSearch">
          {{ loading ? '搜索中' : '生成关系图' }}
        </button>
      </div>

      <div class="vg-field vg-name-field">
        <Icon name="share2" :size="14" class="vg-icon" />
        <input
          v-model="graphName"
          class="vg-input"
          placeholder="图谱名称，留空则用关键词"
          title="生成成功后按此名称保存到侧边栏；同名图谱会被覆盖更新"
          @keydown.enter="doSearch"
        />
      </div>

      <div class="vg-chips">
        <button
          v-for="p in chipPlatforms"
          :key="p.id"
          class="vg-chip"
          :class="{ off: disabledPlatforms.includes(p.id) }"
          :title="p.noCookie
            ? p.name + '：未配置 Cookie，搜索大概率失败（点击停用/启用该平台）'
            : (disabledPlatforms.includes(p.id) ? '点击启用该平台' : '点击停用该平台')"
          @click="togglePlatform(p.id)"
        >
          <span class="vg-chip-dot" :class="{ hollow: p.noCookie }" :style="{ background: p.noCookie ? 'transparent' : p.color }" />{{ p.name }}
        </button>
      </div>

      <div class="vg-ctls">
        <label class="vg-ctl" :class="{ dim: layoutMode === 'layer' }"><span>斥力 {{ forceParams.repulsion }}</span>
          <input v-model.number="forceParams.repulsion" type="range" min="50" max="800" step="10" :disabled="layoutMode === 'layer'" />
        </label>
        <label class="vg-ctl" :class="{ dim: layoutMode === 'layer' }"><span>引力 {{ forceParams.gravity.toFixed(2) }}</span>
          <input v-model.number="forceParams.gravity" type="range" min="0" max="0.5" step="0.01" :disabled="layoutMode === 'layer'" />
        </label>
        <label class="vg-ctl" :class="{ dim: layoutMode === 'layer' }"><span>边长 {{ forceParams.edgeLength }}</span>
          <input v-model.number="forceParams.edgeLength" type="range" min="30" max="300" step="10" :disabled="layoutMode === 'layer'" />
        </label>
        <button class="btn btn-sm" :disabled="!nodeCount" title="重新随机布局并收敛" @click="relayout">
          <Icon name="refresh" :size="13" /> 重排
        </button>
        <button class="btn btn-sm" :disabled="!nodeCount" @click="exportPng">
          <Icon name="external" :size="13" /> 导出图片
        </button>
        <button
          class="btn btn-sm"
          :disabled="!nodeCount || saving"
          title="把当前图（含已展开的社交关系）保存到侧边栏；同名图谱直接覆盖更新"
          @click="persistGraph()"
        >
          <span v-if="saving" class="spinner spinner-sm" />
          <Icon v-else name="check" :size="13" />
          {{ state.activeGraphId ? '更新图谱' : '保存图谱' }}
        </button>
      </div>

      <div class="vg-toolbar2">
        <div class="vg-group">
          <span class="vg-group-label">视图</span>
          <button
            class="vg-chip"
            :class="{ on: viewFilter === 'all' }"
            @click="viewFilter = 'all'"
          >全部</button>
          <button
            v-for="p in presentPlatforms"
            :key="p.id"
            class="vg-chip"
            :class="{ on: viewFilter === p.id }"
            :title="'只看' + p.name + '的子图'"
            @click="viewFilter = viewFilter === p.id ? 'all' : p.id"
          >
            <span class="vg-chip-dot" :style="{ background: p.color }" />{{ p.name }}
          </button>
        </div>

        <div class="vg-group">
          <span class="vg-group-label">布局</span>
          <div class="vg-seg">
            <button :class="{ on: layoutMode === 'force' }" @click="layoutMode = 'force'">力导向</button>
            <button :class="{ on: layoutMode === 'layer' }" title="按平台分区排布，关键词居中" @click="layoutMode = 'layer'">分层</button>
          </div>
        </div>

        <div class="vg-group">
          <button
            class="btn btn-sm"
            :class="{ 'btn-primary': !bulk.busy }"
            :disabled="!nodeCount"
            :title="viewFilter === 'all' ? '对当前图所有用户节点展开关注+粉丝（每人每方向限 20 人）' : '对当前筛选视图下的用户节点展开关注+粉丝（每人每方向限 20 人）'"
            @click="bulkExpand"
          >
            <span v-if="bulk.busy" class="spinner spinner-sm" />
            {{ bulk.busy ? `停止 (${bulk.done}/${bulk.total})` : '一键展开' }}
          </button>
          <span v-if="bulkMsg" class="vg-bulk-msg">{{ bulkMsg }}</span>
        </div>
      </div>
    </div>

    <!-- 状态条：当前任务 + 各平台错误/提示（紧凑、可逐条关闭，不遮挡画布） -->
    <div v-if="taskText || stripItems.length" class="vg-status card">
      <div v-if="taskText" class="vg-status-task">
        <span class="spinner spinner-sm" />{{ taskText }}
      </div>
      <div v-if="stripItems.length" class="vg-status-msgs">
        <span
          v-for="it in stripItems"
          :key="it.key"
          class="vg-status-item"
          :class="[it.kind, { clickable: it.platform }]"
          :title="it.platform ? '点击配置该平台 Cookie / 登录' : ''"
          @click="it.platform && openCookieConfig(it.platform)"
        >
          <span class="vg-chip-dot" :style="{ background: it.color }" />{{ it.text }}
          <span v-if="it.platform" class="vg-status-action" @click.stop="openCookieConfig(it.platform)">配置 Cookie</span>
          <button class="vg-status-x" title="隐藏该提示" @click.stop="dismissStatus(it.key)">
            <Icon name="x" :size="9" />
          </button>
        </span>
      </div>
    </div>

    <div class="vg-stage card">
      <div ref="stageEl" class="vg-canvas" />

      <!-- 空态 / 错误（仅在没有任何图的时候占位；有图时一律用状态条与胶囊提示，不遮挡） -->
      <div v-if="!loading && !result && !error" class="vg-note">
        <Icon name="users" :size="28" />
        <p>输入关键词生成跨平台用户关系图</p>
        <p class="vg-note-sub">
          绿色粗线 = 互相关注；红色实线 = 跨平台完全同名（疑似同一人）；红色虚线 = 昵称相似；<br />
          蓝色箭头 = 单向关注（谁指向谁就是谁在关注谁）；灰色小点 = 粉丝 1 万+ 的公众账号/大V；<br />
          悬浮在连线或节点上可查看关系说明；节点大小 ≈ 粉丝数；点击节点可在卡片中选择"不看"来排除干扰节点
        </p>
      </div>
      <div v-else-if="!loading && !result && error" class="vg-note vg-err">
        <Icon name="alert" :size="20" />
        <p>{{ error }}</p>
      </div>
      <div v-else-if="!loading && result && !nodeCount" class="vg-note"><p>所有平台均无结果</p></div>

      <!-- 搜索中：小型悬浮胶囊，画布仍可缩放/拖拽/点选 -->
      <div v-if="loading" class="vg-loading-pill">
        <span class="spinner spinner-sm" />正在跨平台搜索「{{ keyword || lastSearched }}」…
      </div>

      <!-- 节点信息卡 -->
      <div v-if="selected" class="vg-info card">
        <button class="vg-info-x" @click="selected = null"><Icon name="x" :size="11" /></button>
        <div class="vg-info-head">
          <UserAvatar
            :src="selected.avatarUrl"
            :name="selected.nickname"
            :size="44"
            :color="PLATFORM_MAP[selected.platform]?.color"
          />
          <div class="vg-info-name">
            <div class="vg-info-nick">{{ selected.nickname || '未知用户' }}</div>
            <div class="vg-info-plat">
              <span class="vg-chip-dot" :style="{ background: PLATFORM_MAP[selected.platform]?.color }" />
              {{ PLATFORM_MAP[selected.platform]?.name || selected.platform }}
              <span v-if="Number(selected.fans) > 0" class="vg-info-fans">{{ fmtNum(Number(selected.fans)) }} 粉丝</span>
            </div>
          </div>
        </div>
        <div class="vg-info-uid">UID：{{ selected.uid }}</div>
        <p v-if="selected.signature" class="vg-info-sig">{{ selected.signature }}</p>

        <div v-if="selectedCounts && (selectedCounts.following || selectedCounts.followers)" class="vg-info-soc">
          图内关注 {{ selectedCounts.following }} · 被关注 {{ selectedCounts.followers }}
        </div>
        <div class="vg-info-actions">
          <button class="btn btn-sm btn-primary" @click="adoptTarget">设为监测目标</button>
          <a v-if="homeUrl(selected)" class="btn btn-sm" :href="homeUrl(selected)" target="_blank" rel="noopener">
            <Icon name="external" :size="12" /> 打开主页
          </a>
          <button
            class="btn btn-sm vg-btn-danger"
            title="把该节点从图中移除（认为价值不大）；可随时点击下方计数还原"
            @click="hideSelectedNode"
          ><Icon name="x" :size="12" /> 不看</button>
        </div>
        <template v-if="SOCIAL_SUPPORT[selected.platform]">
          <div class="vg-info-actions">
            <button
              class="btn btn-sm"
              :disabled="expandBusyIds.has(selectedId)"
              @click="expandSocial('both')"
            >
              <span v-if="expandBusyIds.has(selectedId)" class="spinner spinner-sm" />
              {{ expandBusyIds.has(selectedId) ? '展开中…' : '一键展开' }}
            </button>
          </div>
          <p class="vg-info-tip">
            拉取该用户的关注+粉丝（各最多 {{ SOCIAL_LIMIT }} 人），并自动互查邻居之间的关注关系；可同时展开多个节点
          </p>
        </template>
        <p v-else class="vg-info-tip">该平台暂不支持获取关注/粉丝列表</p>
        <p v-if="selectedExpandMsg" class="vg-info-msg" :class="{ 'vg-info-err': selectedExpandMsgIsError }">
          {{ selectedExpandMsg }}
        </p>
      </div>
    </div>

    <div v-if="result" class="vg-foot">
      <span>
        已搜索 <b>{{ result.searched?.length ?? result.platforms.length }}</b> 个平台 · <b>{{ nodeCount }}</b> 个用户 ·
        <b>{{ edgeCount }}</b> 条关系（同名 {{ sameCount }} · 关注 {{ followsCount }}）
        <button
          v-if="hiddenCount"
          class="vg-restore"
          title="把手动隐藏的节点恢复显示"
          @click="hiddenNodeIds.clear(); render(); persistGraph({ quiet: true })"
        >已排除 {{ hiddenCount }} 个节点，点击还原</button>
      </span>
      <span class="vg-foot-tip">滚轮缩放 · 拖拽节点/画布 · 点击节点展开社交关系</span>
    </div>

    <!-- 平台 Cookie 配置弹窗（点击状态条错误/提示打开；保存后自动重搜） -->
    <CookieModal
      :open="cookieModal.open"
      :platform="cookieModal.platform"
      @close="cookieModal.open = false"
      @saved="onCookieSaved"
    />
  </div>
</template>

<style scoped>
.view-graph {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.vg-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.vg-field {
  display: flex;
  align-items: center;
  width: min(420px, 100%);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.vg-field:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.vg-icon {
  margin-left: 11px;
  color: var(--text-3);
}

.vg-input {
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

.vg-input::placeholder {
  color: var(--text-3);
}

.vg-btn {
  margin: 3px;
  border: none;
  background: var(--accent-soft);
  color: var(--accent);
}

/* 图谱名称输入框：比关键词框窄，保存在侧边栏显示的名字 */
.vg-name-field {
  width: min(230px, 100%);
  flex-shrink: 0;
}

.vg-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.vg-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  transition: opacity 0.15s;
}

.vg-chip.off {
  opacity: 0.38;
}

.vg-chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.vg-chip-dot.hollow {
  border: 1.5px solid #c9cdd3;
}

/* 状态条：任务进度 + 错误/提示，紧凑不遮挡画布 */
.vg-status {
  display: flex;
  align-items: baseline;
  gap: 14px;
  flex-wrap: wrap;
  padding: 7px 12px;
  font-size: 12px;
}

.vg-status-task {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--accent);
  flex-shrink: 0;
}

.vg-status-msgs {
  display: flex;
  align-items: center;
  gap: 6px 14px;
  flex-wrap: wrap;
  min-width: 0;
  max-height: 66px;
  overflow-y: auto;
}

.vg-status-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-2);
  min-width: 0;
}

.vg-status-item.err {
  color: var(--danger);
}

.vg-status-item.clickable {
  cursor: pointer;
  border-radius: 6px;
  padding: 1px 4px;
  margin: -1px -4px;
}

.vg-status-item.clickable:hover {
  background: var(--surface-hover);
}

.vg-status-action {
  color: var(--accent);
  font-size: 11px;
  flex-shrink: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.vg-status-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
}

.vg-status-x:hover {
  background: var(--surface-hover);
  color: var(--text);
}

/* 搜索中的悬浮胶囊：不遮画布、可继续交互 */
.vg-loading-pill {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 4;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 14px;
  border-radius: 999px;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-pop);
  font-size: 12px;
  color: var(--text-2);
  pointer-events: none;
}

.vg-ctls {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-left: auto;
  flex-wrap: wrap;
}

.vg-ctl {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--text-3);
}

.vg-ctl input[type='range'] {
  width: 96px;
  accent-color: var(--accent);
}

.vg-ctl.dim {
  opacity: 0.4;
}

.vg-toolbar2 {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  width: 100%;
}

.vg-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.vg-group-label {
  font-size: 12px;
  color: var(--text-3);
  margin-right: 2px;
}

.vg-chip.on {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.vg-seg {
  display: inline-flex;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.vg-seg button {
  border: none;
  background: var(--surface);
  padding: 5px 12px;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-2);
  cursor: pointer;
}

.vg-seg button + button {
  border-left: 1px solid var(--border);
}

.vg-seg button.on {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.vg-bulk-msg {
  font-size: 12px;
  color: var(--text-2);
}

.vg-stage {
  position: relative;
  flex: 1;
  min-height: 420px;
  overflow: hidden;
}

.vg-canvas {
  position: absolute;
  inset: 0;
}

.vg-note {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 13px;
  background: var(--surface);
  z-index: 2;
}

.vg-note p {
  margin: 0;
}

.vg-note-sub {
  font-size: 12px;
  max-width: 420px;
  text-align: center;
  line-height: 1.7;
}

.vg-err {
  color: var(--danger);
}

.vg-info {
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 3;
  width: 264px;
  padding: 14px;
  box-shadow: var(--shadow-pop);
}

.vg-info-x {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
}

.vg-info-x:hover {
  background: var(--surface-hover);
  color: var(--text);
}

.vg-info-head {
  display: flex;
  gap: 10px;
  align-items: center;
}

.vg-info-nick {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vg-info-plat {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-3);
}

.vg-info-fans {
  color: var(--text-2);
}

.vg-info-uid {
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vg-info-sig {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.vg-info-soc {
  margin-top: 10px;
  font-size: 12px;
  color: var(--accent);
  background: var(--accent-soft);
  border-radius: 6px;
  padding: 4px 8px;
}

.vg-info-tip {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-3);
}

.vg-info-msg {
  margin: 8px 0 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-2);
  word-break: break-all;
}

.vg-info-err {
  color: var(--danger);
}

.vg-info-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.vg-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-3);
}

.vg-foot b {
  color: var(--text-2);
}

.vg-foot-err {
  color: var(--danger);
  cursor: help;
}

/* 底部"还原隐藏节点"入口 */
.vg-restore {
  margin-left: 10px;
  border: none;
  background: var(--surface-hover);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 11px;
  color: var(--text-2);
  cursor: pointer;
  vertical-align: 1px;
}

.vg-restore:hover {
  color: var(--accent);
}

/* 信息卡"不看"按钮 */
.vg-btn-danger {
  border: 1px solid var(--danger, #d5372f) !important;
  color: var(--danger, #d5372f) !important;
  background: transparent !important;
}

.vg-btn-danger:hover {
  background: rgba(213, 55, 47, 0.08) !important;
}

/* tooltip 内容（非 scoped，由 ECharts 挂 body） */
:deep(.g-tip) {
  display: flex;
  gap: 8px;
  max-width: 260px;
}

:deep(.g-tip-avatar) {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}

:deep(.g-tip-main) {
  min-width: 0;
}

:deep(.g-tip-name) {
  font-weight: 600;
  color: #1c1f23;
}

:deep(.g-tip-plat) {
  font-size: 11px;
  color: #9aa1ab;
}

:deep(.g-tip-fans) {
  font-size: 11px;
  color: #5c6470;
}

:deep(.g-tip-sig) {
  font-size: 11px;
  color: #9aa1ab;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

:deep(.g-tip-rel) {
  font-size: 12px;
  color: #5c6470;
  margin-top: 2px;
  max-width: 240px;
}

:deep(.g-tip-warn) {
  font-size: 11px;
  color: #b97d10;
  margin-top: 3px;
}
</style>
