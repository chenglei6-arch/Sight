<script setup>
/**
 * 关系图谱视图：
 * - 输入关键词，后端 /api/graph/search 并行搜索各平台用户并做跨平台同人归并
 * - 各平台可设专属搜索词（目标人物在不同平台昵称可能不同，如抖音"戾清"、B站"摆邮"）：
 *   点击平台 chip 右侧铅笔编辑，未设置的平台沿用主关键词；覆盖表随图谱持久化，调出时还原
 * - 手动标记同人：昵称不同时自动归并失效，在信息卡点"标记同人"再点另一账号，
 *   手动连一条 manual 边（紫色实线，点击连线可解除），同样随图谱持久化
 * - ECharts graph（力导向）渲染：中心节点=关键词，用户节点按平台着色，节点大小与粉丝数成反比
 * - 边：hit 命中（灰）、same 跨平台完全同名（红实线）、alike 昵称相似（红虚线）、manual 手动标记同人（紫实线）
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
import { state, setUid, setView, loadSavedGraphs, openSavedGraph } from '../store'
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

// 每个用户单次展开的关注/粉丝数量上限（可在工具栏调整，localStorage 持久化）
const EXPAND_LIMIT_KEY = 'graph_expand_limit'
function loadExpandLimit() {
  try {
    const v = parseInt(localStorage.getItem(EXPAND_LIMIT_KEY) || '', 10)
    if (v >= 10 && v <= 500) return v
  } catch { /* 忽略 */ }
  return 100
}
const expandLimit = ref(loadExpandLimit())
function setExpandLimit(v) {
  const n = Math.max(10, Math.min(500, Math.round(Number(v) || 100)))
  expandLimit.value = n
  try {
    localStorage.setItem(EXPAND_LIMIT_KEY, String(n))
  } catch { /* 忽略 */ }
}

const ACCENT = '#3565e0'
const SAME_COLOR = '#d5372f'
const MUTUAL_COLOR = '#1e9e55' // 互相关注：绿色实线
const MANUAL_COLOR = '#7c4dff' // 手动标记同人：紫色实线
// 粉丝达到该量级视为公众账号/大V：与监控对象直接关联的价值低，节点缩小+灰色淡化（可手动还原/隐藏）
const IRRELEVANT_FANS = 1000
// 达人判定：粉丝过千，或平台明确标注的公众账号（微博大V认证、B站官方机构号等）
function isIrrelevant(n) {
  if (!n || n.platform === 'keyword') return false
  if (n.verified) return true
  return Number(n.fans) >= IRRELEVANT_FANS
}
// 达人原因文案（tooltip/提示区分：认证 或 粉丝过千）
function irrelevantReason(n) {
  if (!n) return ''
  if (n.verified) return '平台认证的公众账号/达人'
  return `粉丝 ${fmtNum(Number(n.fans))}，疑似大V/公众账号`
}

// 判断用户节点是否在当前视图下被隐藏/排除
function isNodeHidden(n) {
  if (!n) return false
  const id = n.id || `${n.platform}:${n.uid}`
  return hiddenNodeIds.has(id) || isIrrelevant(n)
}
// 隐藏 removeId 后会"悬空"的节点：从关键词根 BFS（跳过 removeId 与已隐藏节点），
// 不可达的可见用户节点 = 仅通过 removeId 连入图的私有后代（含递归孙节点），需连带隐藏。
// 有 hit/same/alike 等其他连边锚在图上的节点仍可达，不会被误删
function cascadeHiddenAfter(removeId) {
  const data = result.value
  if (!data) return []
  const adj = new Map()
  for (const e of deriveDisplayEdges()) {
    if (e.source === removeId || e.target === removeId) continue
    if (hiddenNodeIds.has(e.source) || hiddenNodeIds.has(e.target)) continue
    if (!adj.has(e.source)) adj.set(e.source, new Set())
    if (!adj.has(e.target)) adj.set(e.target, new Set())
    adj.get(e.source).add(e.target)
    adj.get(e.target).add(e.source)
  }
  const seen = new Set(['keyword'])
  const queue = ['keyword']
  while (queue.length) {
    for (const nb of adj.get(queue.pop()) || []) {
      if (!seen.has(nb)) {
        seen.add(nb)
        queue.push(nb)
      }
    }
  }
  return data.nodes
    .filter((n) => n.platform !== 'keyword' && !hiddenNodeIds.has(n.id) && !seen.has(n.id))
    .map((n) => n.id)
}

// 手动把选中的节点从图中"取消"（此后不展示、不参与展开，也不随持久化保存）
function hideSelectedNode() {
  if (!selected.value) return
  hiddenNodeIds.add(selectedId.value)
  // 仅通过该节点连进图的子节点（及其后代）一并隐藏，避免父节点删除后留下孤立漂浮点
  const cascade = cascadeHiddenAfter(selectedId.value)
  for (const id of cascade) hiddenNodeIds.add(id)
  const removed = result.value?.nodes.filter((n) => (n.id || `${n.platform}:${n.uid}`) === selectedId.value)
  if (removed?.length) selected.value = null
  // 挂在被排除节点上的手动同人边一并清掉，避免残留到持久化数据里
  const gone = new Set([selectedId.value, ...cascade])
  result.value.edges = result.value.edges.filter(
    (e) => e.relation !== 'manual' || (!gone.has(e.source) && !gone.has(e.target))
  )
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

// 各平台专属搜索词（目标人物在不同平台昵称可能不同）：pid -> 非空覆盖词，空/缺省用主关键词。
// 换图/新搜索保留设置（通常是同一个人的多平台追踪），仅随图谱保存与调出还原
const platformKeywords = reactive({})
const editingPlatform = ref('') // 正在编辑专属搜索词的平台 id
const editVal = ref('') // 编辑中的临时值
let lastOverridesKey = '' // 当前已展示图谱使用的覆盖表序列化，用于"换词即新图"判定

function currentOverrides() {
  const out = {}
  for (const p of PLATFORMS) {
    const v = String(platformKeywords[p.id] || '').trim()
    if (v) out[p.id] = v
  }
  return out
}

function startEditKeyword(pid) {
  editingPlatform.value = pid
  editVal.value = String(platformKeywords[pid] || '')
  nextTick(() => document.querySelector(`.vg-chip-kw[data-pid="${pid}"]`)?.focus())
}

function commitKeyword(pid) {
  if (editingPlatform.value !== pid) return // Enter 提交后触发 blur，防二次执行
  const v = editVal.value.trim()
  if (v) platformKeywords[pid] = v
  else delete platformKeywords[pid]
  editingPlatform.value = ''
}

function cancelEditKeyword() {
  editingPlatform.value = ''
}

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
        // 各节点展开进度（已拉条数/还有更多/总数），用于还原“剩余未展开”显示
        expand_prog: Object.fromEntries(expandProg),
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
  stopQueuePolling() // 换图后旧图的队列结果不再合并，轮询随之停止
  expandBusyIds.clear()
  bulk.busy = false
  pausedQueues.value = []
  selected.value = null
  error.value = ''
  searchFailedMsg.value = ''
  saveMsg.value = ''
  for (const k of Object.keys(expandMsgs)) delete expandMsgs[k]
  bulkMsg.value = ''
  remarkMsg.value = ''
  viewFilter.value = 'all'
  expandedKeys.clear()
  intercheckedIds.clear()
  expandProg.clear()
  hiddenNodeIds.clear()
  dismissedKeys.clear()
  keyword.value = g.data.keyword || ''
  lastSearched.value = g.data.keyword || ''
  graphName.value = g.name || ''
  result.value = g.data
  // 还原各平台专属搜索词：chip 显示与"换词即新图"判定都要对上这张图
  for (const k of Object.keys(platformKeywords)) delete platformKeywords[k]
  for (const [k, v] of Object.entries(g.data.keywords || {})) {
    if (typeof v === 'string' && v.trim()) platformKeywords[k] = v.trim()
  }
  lastOverridesKey = JSON.stringify(currentOverrides())
  // 还原保存时的展开/隐藏状态：展开高亮与互查去重恢复，手动排除的节点不重新出现
  for (const k of g.data.expanded_keys || []) expandedKeys.add(k)
  for (const k of g.data.interchecked_ids || []) intercheckedIds.add(k)
  for (const k of g.data.hidden_ids || []) hiddenNodeIds.add(k)
  for (const [k, v] of Object.entries(g.data.expand_prog || {})) {
    if (!v) continue
    expandProg.set(k, {
      followsLoaded: v.followsLoaded || 0,
      followsMore: !!v.followsMore,
      followsTotal: v.followsTotal ?? null,
      followersLoaded: v.followersLoaded || 0,
      followersMore: !!v.followersMore,
      followersTotal: v.followersTotal ?? null,
    })
  }
  state.activeGraphId = g.id
  resetFreeze() // 载入已保存图谱：坐标缓存属于旧图，直接作废
  nextTick(() => render())
}

watch(() => state.pendingGraph, consumePendingGraph)

// ==================== 手动标记同人 ====================
// 昵称不同的跨平台账号自动归并（same/alike）覆盖不到，由用户人工确认：
// 信息卡点"标记同人"进入连线模式 → 点击另一账号连一条 manual 边（紫色实线）；
// 点击已有 manual 连线即解除。manual 边与其他边一样随图谱持久化。

const linkSource = ref(null) // 连线模式中的源节点；null 表示不在连线模式
const manualMsg = ref('') // 最近一次标记/解除的结果提示（进状态条，可关闭）

function startLinkFrom(n) {
  if (!n || !result.value) return
  linkSource.value = n
  manualMsg.value = ''
}

function addManualEdge(a, b) {
  const k = pairKey(a.id, b.id)
  if (result.value.edges.some((e) => e.relation === 'manual' && pairKey(e.source, e.target) === k)) {
    manualMsg.value = `${a.nickname} 与 ${b.nickname} 已标记过同人`
    return
  }
  result.value.edges.push({ source: a.id, target: b.id, relation: 'manual' })
  manualMsg.value = `已手动标记同人：${a.nickname} ↔ ${b.nickname}`
  chart?.setOption(buildOption())
  persistGraph({ quiet: true })
}

function removeManualEdge(source, target) {
  const k = pairKey(source, target)
  const before = result.value.edges.length
  result.value.edges = result.value.edges.filter(
    (e) => !(e.relation === 'manual' && pairKey(e.source, e.target) === k)
  )
  if (result.value.edges.length === before) return
  manualMsg.value = '已解除手动同人标记'
  chart?.setOption(buildOption())
  persistGraph({ quiet: true })
}

// 图表点击统一入口：连线模式下点节点=完成标记；平时点 manual 连线=解除标记
function onChartClick(params) {
  if (params.dataType === 'edge') {
    if (params.data?.relation === 'manual') removeManualEdge(params.data.source, params.data.target)
    return
  }
  if (params.dataType !== 'node') return
  const n = params.data?.raw
  if (linkSource.value) {
    const src = linkSource.value
    linkSource.value = null
    if (n && n.platform !== 'keyword' && n.id !== src.id) addManualEdge(src, n)
    return // 点了关键词节点或自己：视为取消连线模式
  }
  selected.value = n && n.platform !== 'keyword' ? n : null
  // 消息按节点独立保存：切换选中节点不影响其他节点的展开过程与结果
}

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
  // Cookie 更新后若该平台队列因连续失败被熔断，立即恢复
  api.post('/graph/expand/resume', {}).catch(() => {})
  pausedQueues.value = []
  // 不自动重搜：新搜索会用少量结果的新图替换当前已展开的图，
  // 且同名自动保存会把库里那张旧图一并覆盖（曾导致"重配 Cookie 后图全丢"）。
  // 当前图原样保留，需要最新数据时由用户手动重新搜索。
  if (lastSearched.value) {
    saveMsg.value = 'Cookie 已更新，当前图已保留；需要最新数据请重新搜索'
  }
}

// 社交展开状态：已展开的类型与已互查过的邻居（跨平台去重 key: "platform:uid[:type]"）
const expandedKeys = reactive(new Set())
const intercheckedIds = reactive(new Set())
// 每个节点各方向已拉取进度（"还剩多少没展开"判定用）
// key "platform:uid"，值 { followsLoaded, followsMore, followsTotal, followersLoaded, followersMore, followersTotal }
const expandProg = reactive(new Map())
function progOf(node) {
  const id = `${node.platform}:${node.uid}`
  if (!expandProg.has(id)) expandProg.set(id, {
    followsLoaded: 0, followsMore: false, followsTotal: null,
    followersLoaded: 0, followersMore: false, followersTotal: null,
  })
  return expandProg.get(id)
}
// 多节点并行展开：每个节点有独立的忙碌标记和结果消息（key 均为 "platform:uid"）
const expandBusyIds = reactive(new Set())
const expandMsgs = reactive({})

// 视图分层：'all' 或单个平台 id（只显示该平台子图 + 关键词中心）
const viewFilter = ref('all')
// 布局模式：force 力导向混排 | layer 按平台分区（预计算坐标，不可拖拽重排）
const layoutMode = ref('force')
// 布局停放：不切换布局，只把力模拟的 friction 设为 0——所有斥力/引力/弹力位移
// 都乘以 friction，为 0 时模拟一步即停，节点原地冻结（可拖拽手动摆放，松手即停）；
// 恢复时把 friction 还原为默认值 0.6，从当前位置继续温和收敛。
// 相比切成 layout:'none' + 固定坐标，坐标系不变，节点尺寸/缩放不会被重新适配。
const frozen = ref(false)
// 节点 id -> {x,y}：停放期间记录的坐标。chart.clear() 会丢失内部模拟坐标，
// 重渲染前把当前坐标收进缓存、再经数据 x/y 写回（simpleLayout 以此为初始位置）
const frozenPos = new Map()
// 全图一键展开（任务入后端队列执行，这里只做入队与结果计数）
const bulk = reactive({
  busy: false, done: 0, total: 0, stop: false,
  addNodes: 0, addEdges: 0, icHits: 0, failed: 0, failReasons: new Map(),
})
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
  remarkMsg.value = ''
  viewFilter.value = 'all'
  expandedKeys.clear()
  intercheckedIds.clear()
  expandProg.clear()
  hiddenNodeIds.clear()
  dismissedKeys.clear()
  // 新搜索是一张新图：停掉旧图的队列轮询，清掉遗留的展开占用标记
  stopQueuePolling()
  expandBusyIds.clear()
  bulk.busy = false // 旧图的队列进度不再跨图延续
  pausedQueues.value = []
  lastSearched.value = kw
  const overrides = currentOverrides()
  const overridesKey = JSON.stringify(overrides)
  // 换了主关键词或各平台专属搜索词就是一张新图：清掉继承自上一张图的名称，避免同名误覆盖旧图谱
  if (result.value && result.value.keyword && (result.value.keyword !== kw || overridesKey !== lastOverridesKey))
    graphName.value = ''
  lastOverridesKey = overridesKey
  state.activeGraphId = null // 新生成的图尚未保存，等待下方自动持久化后回填
  resetFreeze() // 新图从随机布局开始，不继承上一张图的停放状态
  try {
    const platforms = chipPlatforms.value.map((p) => p.id).filter((id) => !disabledPlatforms.value.includes(id))
    // 搜索期间保留旧图继续可交互；失败也不清空 result，错误只进状态条
    const params = { keyword: kw, platforms: platforms.join(',') }
    if (Object.keys(overrides).length) params.keywords = JSON.stringify(overrides)
    result.value = await api.get('/graph/search', params)
    result.value.keywords = overrides // 覆盖表并入结果，persistGraph 随图自动保存
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
  /^(未获取到数据|展开失败|接口报错)/.test(selectedExpandMsg.value)
)

// 正在展开的节点昵称（状态条汇总展示用）
const expandBusyNames = computed(() =>
  [...expandBusyIds].map((id) => result.value?.nodes.find((n) => n.id === id)?.nickname || id)
)

// 选中节点是否已展开过、且还有更多可继续展开
function canExpandMore(node) {
  if (!node) return false
  const p = expandProg.get(`${node.platform}:${node.uid}`)
  if (!p) return false
  return (p.followsLoaded > 0 && p.followsMore) || (p.followersLoaded > 0 && p.followersMore)
}

// 选中节点已展开量的进度描述（信息卡提示用）
const selectedProgText = computed(() => {
  if (!selected.value) return ''
  const p = expandProg.get(selectedId.value)
  if (!p || (p.followsLoaded === 0 && p.followersLoaded === 0)) return ''
  const parts = []
  if (p.followsLoaded) {
    const tip = p.followsTotal != null ? `/${p.followsTotal}` : ''
    parts.push(`已展开关注 ${p.followsLoaded}${tip}${p.followsMore ? '，还有更多' : ''}`)
  }
  if (p.followersLoaded) {
    const tip = p.followersTotal != null ? `/${p.followersTotal}` : ''
    parts.push(`粉丝 ${p.followersLoaded}${tip}${p.followersMore ? '，还有更多' : ''}`)
  }
  return parts.join(' · ')
})

// 当前图中实际有结果的平台（用于视图筛选 chips）
const presentPlatforms = computed(() => {
  if (!result.value) return []
  const ids = new Set(result.value.nodes.map((n) => n.platform))
  return PLATFORMS.filter((p) => ids.has(p.id))
})

// 当前筛选视图下可见的用户节点（手动"不看"排除的节点不参与展开/统计）
function visibleUserNodes() {
  if (!result.value) return []
  return result.value.nodes.filter(
    (n) =>
      n.platform !== 'keyword' &&
      !hiddenNodeIds.has(n.id) &&
      (viewFilter.value === 'all' || n.platform === viewFilter.value)
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

/**
 * 展开一个节点的社交关系：把任务加入后端按平台隔离的展开队列，
 * 结果由队列轮询循环（pollQueueLoop）合并进图。
 * type: 'follows' | 'followers' | 'both'
 * 达上限后再次调用（type 为对应方向）即"继续展开"：从已拉取的位置往后取下一批。
 */
async function expandSocial(type) {
  const n = selected.value
  if (!n || !result.value) return
  const nid = `${n.platform}:${n.uid}`
  if (expandBusyIds.has(nid)) return // 该节点已有任务在排队/执行，其余节点不受影响
  const directions = type === 'both' ? ['follows', 'followers'] : [type]
  // "继续展开"：只拉还没展开/还有更多的方向（已确认拉完的方向跳过，避免重复请求）
  const p0 = progOf(n)
  const wantFollows =
    directions.includes('follows') &&
    (p0.followsLoaded === 0 || p0.followsMore)
  const wantFollowers =
    directions.includes('followers') &&
    (p0.followersLoaded === 0 || p0.followersMore)
  if (!wantFollows && !wantFollowers) {
    expandMsgs[nid] = '该用户的关注/粉丝已全部展开完毕'
    return
  }
  const stats = await enqueueExpandTasks([{
    platform: n.platform,
    uid: n.uid,
    nickname: n.nickname,
    follows_limit: wantFollows ? expandLimit.value : 0,
    followers_limit: wantFollowers ? expandLimit.value : 0,
    follows_skip: wantFollows ? p0.followsLoaded : 0,
    followers_skip: wantFollowers ? p0.followersLoaded : 0,
    known_ids: result.value.nodes.filter((x) => x.platform === n.platform).map((x) => x.id),
    intercheck_skip: intercheckSkipList(n.platform),
    intercheck_extra: [...adjacentSamePlatformUids(n)],
  }])
  if (!stats.queued) {
    const pausedQ = (stats.paused || []).find((p) => p.platform === n.platform)
    expandMsgs[nid] = pausedQ
      ? `该平台队列已暂停（连续失败）：${pausedQ.reason}。配置 Cookie 后自动恢复，也可展开其他平台的用户`
      : stats.duplicates
        ? '该用户的展开任务已在队列中，等待执行结果'
        : `任务入队失败${stats.error ? '：' + stats.error : '（超出预算或平台不可用）'}`
    return
  }
  expandBusyIds.add(nid)
  expandMsgs[nid] = '已加入展开队列，等待执行…'
}

// ==================== 全图一键展开 ====================

function intercheckSkipList(platform) {
  const prefix = platform + ':'
  return [...intercheckedIds]
    .filter((k) => k.startsWith(prefix))
    .map((k) => k.slice(prefix.length))
}

async function bulkExpand() {
  const targets = visibleUserNodes().filter(
    (n) =>
      SOCIAL_SUPPORT[n.platform] &&
      !isIrrelevant(n) && // 大V/公众账号灰化节点不参与一键展开（仍可点开单独展开）
      !expandBusyIds.has(`${n.platform}:${n.uid}`) && // 该节点已有单独任务在队列，跳过避免重复拉取
      !expandedKeys.has(`${n.platform}:${n.uid}:follows`)
  )
  if (!targets.length) {
    bulkMsg.value = bulk.busy
      ? '当前视图没有新增可展开的节点（其余平台队列仍在执行，互不影响）'
      : '没有可展开的节点（当前视图下所有可查用户都已展开，或平台不支持）'
    return
  }
  const wasBusy = bulk.busy
  if (!wasBusy) {
    bulk.stop = false
    bulk.done = 0
    bulk.total = 0
    bulk.addNodes = 0
    bulk.addEdges = 0
    bulk.icHits = 0
    bulk.failed = 0
    bulk.failReasons = new Map()
  }
  bulkMsg.value = `正在把 ${targets.length} 个节点加入展开队列…`
  const stats = await enqueueExpandTasks(
    targets.map((n) => ({
      platform: n.platform,
      uid: n.uid,
      nickname: n.nickname,
      follows_limit: 20,
      followers_limit: 20,
      known_ids: result.value.nodes.filter((x) => x.platform === n.platform).map((x) => x.id),
      intercheck_skip: intercheckSkipList(n.platform),
      intercheck_extra: [...adjacentSamePlatformUids(n)],
      intercheck_limit: 8,
      intercheck_follow_limit: 30,
    }))
  )
  if (!stats.queued && !stats.duplicates && !wasBusy) {
    const pausedText = (stats.paused || []).map((p) => `${PLATFORM_MAP[p.platform]?.name || p.platform}：${p.reason}`).join('；')
    bulkMsg.value = `没有任务成功入队${stats.rejected ? `（${stats.rejected} 个被拒绝）` : ''}${pausedText ? ` · ${pausedText}` : ''}`
    return
  }
  bulk.busy = true
  bulk.total += stats.queued + stats.duplicates
  bulk.done += stats.duplicates // 去重跳过的视为已完成，保证 done/total 对得上
  bulk.failed += stats.rejected
  if (stats.rejected) bulk.failReasons.set('入队被拒（预算超限/队列暂停/平台不可用）', stats.rejected)
  bulkMsg.value = stats.queued
    ? `已入队 ${stats.queued} 个展开任务（每个关注+粉丝各 20 人），各平台队列并行执行…`
    : '所选节点均已在队列中，等待执行结果'
  startQueuePolling()
}

// 停止当前图的排队任务（执行中的照常完成）；一键展开按钮本身可随时追加新目标
function stopBulk() {
  bulk.stop = true
  const gid = state.activeGraphId
  if (gid != null) api.post('/graph/expand/stop', { graph_id: gid }).catch(() => {})
  bulkMsg.value = '正在停止队列中的剩余任务…'
}

// ==================== 展开队列轮询（结果合并进图） ====================

// 入队前确保图已持久化：轮询与停止都按 graph_id 过滤，没有 id 就先落库换一个
async function ensureGraphId() {
  if (state.activeGraphId != null) return state.activeGraphId
  const id = await persistGraph({ quiet: true })
  if (id != null) state.activeGraphId = id
  return state.activeGraphId
}

async function enqueueExpandTasks(items) {
  const gid = await ensureGraphId()
  try {
    return await api.post('/graph/expand/enqueue', { graph_id: gid, items })
  } catch (e) {
    return { queued: 0, duplicates: 0, rejected: items.length, error: e.message }
  }
}

// 轮询循环：有排队/执行中的任务时每 1.5s 增量拉一次完结结果并合并；空闲即退出。
// gen 计数防竞态：轮询期间又发生了入队则不退出，避免新任务的结果没人合并
const queuePoll = reactive({ active: false, cursors: new Map(), gen: 0 }) // cursors: graph_id -> 已读到的任务 id
const pausedQueues = ref([]) // 熔断暂停的平台队列 [{platform, reason}]

function startQueuePolling() {
  queuePoll.gen++
  if (queuePoll.active) return
  queuePoll.active = true
  pollQueueLoop()
}

function stopQueuePolling() {
  queuePoll.active = false
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function pollQueueLoop() {
  const myGen = queuePoll.gen
  while (queuePoll.active) {
    const gid = state.activeGraphId
    if (gid == null) break
    let data
    try {
      data = await api.get('/graph/expand/results', {
        graph_id: gid,
        since_id: queuePoll.cursors.get(gid) || 0,
        limit: 50,
      })
    } catch {
      await sleep(2000) // 网络抖动：下一轮再试，不中断循环
      continue
    }
    let changed = false
    for (const r of data.results || []) {
      if (applyTaskResult(r)) changed = true
    }
    pausedQueues.value = data.paused || []
    queuePoll.cursors.set(gid, data.cursor || queuePoll.cursors.get(gid) || 0)
    if (changed) {
      syncFrozenPositions()
      chart?.setOption(buildOption())
    }
    if (!(data.pending > 0) && queuePoll.gen === myGen) {
      // 当前图队列已清空且期间没有新入队：一键展开收尾，轮询退出
      if (bulk.busy) finalizeBulk()
      break
    }
    await sleep(data.pending > 0 ? 1500 : 300)
  }
  if (queuePoll.gen === myGen) queuePoll.active = false
}

/**
 * 应用一个完结任务：合并节点/边、累计进度与标记、更新消息。
 * 返回图是否有变化。
 */
function applyTaskResult(r) {
  const nid = `${r.platform}:${r.uid}`
  const payload = r.status === 'done' ? r.result : null
  let added = { nodes: 0, edges: 0 }
  if (payload) {
    added = mergeGraph(payload)
    for (const t of payload.intercheck?.targets || []) intercheckedIds.add(r.platform + ':' + t)
    // 记录各方向已拉取进度与"还有更多/总数"；任务请求了哪个方向就标记哪个方向已展开
    const c = payload.counts || {}
    const p = progOf({ platform: r.platform, uid: r.uid })
    if (r.dirs?.follows) {
      p.followsLoaded = (c.follows_offset || 0) + (c.follows || 0)
      p.followsMore = !!c.follows_more
      if (typeof c.follows_total === 'number') p.followsTotal = c.follows_total
      expandedKeys.add(`${nid}:follows`)
    }
    if (r.dirs?.followers) {
      p.followersLoaded = (c.followers_offset || 0) + (c.followers || 0)
      p.followersMore = !!c.followers_more
      if (typeof c.followers_total === 'number') p.followersTotal = c.followers_total
      expandedKeys.add(`${nid}:followers`)
    }
  }
  // 单独展开的任务：把结果消息挂到节点信息卡（与旧同步版文案一致）
  if (expandBusyIds.has(nid)) {
    expandBusyIds.delete(nid)
    if (r.status === 'failed') {
      expandMsgs[nid] = `接口报错：${r.error || '未知原因'}`
    } else if (r.status === 'cancelled') {
      expandMsgs[nid] = '任务已停止'
    } else if (payload) {
      const ic = payload.intercheck || {}
      const errs = Object.entries(payload.errors || {})
      expandMsgs[nid] =
        (added.nodes + added.edges === 0 && !ic.checked && errs.length
          ? `接口报错：${errs.map(([, v]) => v).join('；')}`
          : `新增 ${added.nodes} 人 · ${added.edges} 条关注边 · 邻居互查命中 ${ic.edges?.length || 0} 条` +
            (ic.total ? `（查了 ${ic.checked}/${ic.total} 个邻居）` : '') +
            (errs.length ? ` · 部分失败：${errs.map(([, v]) => v).join('；')}` : ''))
    }
  }
  // 一键展开计数（任务可能同时被单独展开与一键展开引用，两边各自累计）
  if (bulk.busy) {
    bulk.done++
    if (r.status !== 'done') {
      bulk.failed++
      const reason = r.status === 'cancelled' ? '已停止' : (r.error || '未知原因')
      bulk.failReasons.set(reason, (bulk.failReasons.get(reason) || 0) + 1)
    } else if (payload) {
      bulk.addNodes += added.nodes
      bulk.addEdges += added.edges
      bulk.icHits += payload.intercheck?.edges?.length || 0
      bulkMsg.value = `队列执行中 ${bulk.done}/${bulk.total}：${r.nickname || nid}`
    }
  }
  return added.nodes + added.edges > 0
}

// 当前图队列清空后的一键展开收尾：汇总消息 + 同步图谱
function finalizeBulk() {
  bulk.busy = false
  const scope = viewFilter.value === 'all' ? '' : `（仅 ${PLATFORM_MAP[viewFilter.value]?.name} 视图）`
  const failText = [...bulk.failReasons.entries()]
    .map(([msg, cnt]) => `${msg}${cnt > 1 ? ` ×${cnt}` : ''}`)
    .join('；')
  bulkMsg.value =
    `${bulk.stop ? '已停止' : '全图展开完成'}${scope}：新增 ${bulk.addNodes} 人 · ${bulk.addEdges} 条关注边 · 互查命中 ${bulk.icHits} 条` +
    (failText ? ` · ${bulk.failed} 个任务未成功：${failText}` : '') +
    (bulk.failed && !failText ? ` · 失败 ${bulk.failed} 个任务` : '')
  // 全图展开（含中途停止）的结果整体同步到已保存图谱
  if (bulk.addNodes + bulk.addEdges + bulk.icHits > 0) persistGraph({ quiet: true })
}

// ==================== 重新标记（重拉节点粉丝数/认证，修正旧图大V判定） ====================

const remark = reactive({ busy: false })
const remarkMsg = ref('')

async function remarkNodes() {
  if (remark.busy || !result.value) return
  const targets = result.value.nodes.filter(
    (n) => n.platform !== 'keyword' && !hiddenNodeIds.has(n.id)
  )
  if (!targets.length) {
    remarkMsg.value = '当前图没有可重新标记的节点'
    return
  }
  remark.busy = true
  remarkMsg.value = `正在重新标记 ${targets.length} 个节点（逐个拉取平台资料，可能较慢）…`
  try {
    const payload = await api.post('/graph/refresh_nodes', {
      nodes: targets.map((n) => ({ platform: n.platform, uid: n.uid })),
    })
    let updated = 0
    let bigV = 0
    for (const r of payload.nodes || []) {
      const n = result.value.nodes.find((x) => x.id === r.id)
      if (!n) continue
      n.fans = r.fans
      if (r.verified !== undefined) n.verified = r.verified
      updated++
      if (isIrrelevant(n)) bigV++
    }
    syncFrozenPositions()
    chart?.setOption(buildOption())
    const failedCnt = Object.keys(payload.errors || {}).length
    remarkMsg.value =
      `重新标记完成：更新 ${updated} 个节点（其中大V ${bigV} 个）` +
      (failedCnt ? ` · ${failedCnt} 个失败（多为平台不支持或接口报错）` : '')
    // 新字段即时入库，之后调出这张图不用再刷
    if (updated > 0) persistGraph({ quiet: true })
  } catch (e) {
    remarkMsg.value = '重新标记失败：' + e.message
  } finally {
    remark.busy = false
  }
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
// 手动标记的同人连线数（底部统计展示）
const manualCount = computed(() =>
  result.value ? result.value.edges.filter((e) => e.relation === 'manual').length : 0
)
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
  else if (queuePoll.active && !expandBusyIds.size)
    parts.push('后台展开队列执行中，结果将自动合入当前图谱…')
  if (remark.busy) parts.push(remarkMsg.value)
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
  if (manualMsg.value && !dismissedKeys.has('manual'))
    items.push({ key: 'manual', kind: 'ok', color: MANUAL_COLOR, text: manualMsg.value })
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
  // 展开队列熔断暂停的平台（连续多次失败，典型是 Cookie 失效）：提示并支持点击配置
  for (const pq of pausedQueues.value) {
    const key = 'qp:' + pq.platform
    if (dismissedKeys.has(key)) continue
    items.push({
      key,
      kind: 'err',
      color: PLATFORM_MAP[pq.platform]?.color || '#d5372f',
      text: `${PLATFORM_MAP[pq.platform]?.name || pq.platform} 展开队列已暂停：${pq.reason}（配置 Cookie 后自动恢复）`,
      platform: pq.platform,
    })
  }
  return items
})

// 节点大小与粉丝数成反比（粉丝越多节点越小），幅度限定在基准 24px 的 50%~125%
const NODE_SIZE_BASE = 24
function nodeSize(fans) {
  const f = Number(fans) || 0
  // 对数映射：10 粉及以下 → 125%，100 万粉及以上 → 50%（图内多为小粉丝量账号，
  // 区间取宽才能让低粉丝段也有可见的大小差异，否则全部顶在上限）
  const t = f > 10 ? Math.min(1, Math.max(0, (Math.log10(f) - 1) / 5)) : 0
  return NODE_SIZE_BASE * (1.25 - 0.75 * t)
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
  // 其余原始边（hit / same / alike / manual）保持原样
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
  // 停放时把记录的坐标写进数据 x/y：正常 setOption 用不到（内部 preservedPoints 优先），
  // 但 chart.clear() 之后的重渲染靠它恢复原位
  const posMap = !layer && frozen.value ? frozenPos : null
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
    if (e.relation === 'manual')
      return `<div class='g-tip-name'>${sn} ↔ ${tn}</div>` +
        `<div class='g-tip-rel'>已手动标记为同一人的不同账号（点击连线可解除）</div>`
    return `<div class='g-tip-rel'>关键词「${esc(data.keyword)}」搜索命中 <b>${tn}</b></div>`
  }

  // 节点 badge：还有未展开的人时，在昵称旁附加一个"剩余 N"胶囊（rich 文本）
  // 有真实总数时显示精确剩余；否则提示还有更多，具体数量需点击查看
  function remainBadgeOf(n) {
    const p = expandProg.get(`${n.platform}:${n.uid}`)
    if (!p || n.platform === 'keyword') return ''
    const parts = []
    if (p.followsMore) {
      const remain = p.followsTotal != null ? Math.max(0, p.followsTotal - p.followsLoaded) : null
      parts.push(remain != null ? `关注 余 ${remain}` : '关注 有更多')
    }
    if (p.followersMore) {
      const remain = p.followersTotal != null ? Math.max(0, p.followersTotal - p.followersLoaded) : null
      parts.push(remain != null ? `粉丝 余 ${remain}` : '粉丝 有更多')
    }
    return parts.join(' · ')
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
        // 粉丝 ≥1000 的大V/公众账号：灰色小圆点淡化展示，降低视觉权重
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
        // 预计算"剩余未展开"徽标文本（有真实剩余数则显示数字，否则只标 +）
        _remain: n.platform === 'keyword' ? '' : remainBadgeOf(n),
      }
      if (layer && layerPos[n.id]) {
        base.x = layerPos[n.id].x
        base.y = layerPos[n.id].y
      } else if (posMap && frozenPos.has(n.id)) {
        base.x = frozenPos.get(n.id).x
        base.y = frozenPos.get(n.id).y
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
    if (e.relation === 'manual')
      return { ...e, lineStyle: { color: MANUAL_COLOR, width: 2.4, opacity: 0.95, curveness: 0.14 } }
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
          ? `<div class='g-tip-warn'>${esc(irrelevantReason(n))}，与监控对象直接关联可能性低（已灰化缩小）</div>`
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
        // 滚轮缩放/平移在整个画布生效；ECharts 6 默认 'selfRect' 只在节点包围盒内响应，
        // 缩小后包围盒收缩，画布边缘滚轮会失灵
        roamTrigger: 'global',
        // 停放下节点同样可拖拽手动摆放（松手即停）
        draggable: !layer,
        categories,
        data: nodes,
        links,
        force: {
          repulsion: forceParams.repulsion,
          gravity: forceParams.gravity,
          edgeLength: forceParams.edgeLength,
          layoutAnimation: !layer,
          // 停放核心：friction 0 让模拟一步停摆；undefined 走 ECharts 默认 0.6
          ...(frozen.value ? { friction: 0 } : {}),
        },
        label: {
          show: true,
          position: 'bottom',
          fontSize: 11,
          color: '#5c6470',
          formatter: (p) => {
            const raw = p.data?.raw
            if (!raw) return ''
            const nick = (raw.nickname || '').slice(0, 12)
            const remain = p.data?._remain || ''
            if (!remain) return nick
            // 有"剩余未展开"：昵称下方加橙色小徽标
            return `{nick|${nick}}\n{remain|${remain}}`
          },
          rich: {
            nick: { fontSize: 11, color: '#5c6470', lineHeight: 14 },
            remain: {
              fontSize: 10,
              color: '#b97d10',
              backgroundColor: '#fdf3e0',
              borderRadius: 6,
              padding: [1, 5],
              lineHeight: 14,
            },
          },
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
  if (frozen.value) capturePositions() // 先把拖拽后的最新坐标收进缓存，clear 后经数据 x/y 恢复
  const option = buildOption()
  if (!option) return
  chart.clear()
  chart.setOption(option)
}

// 抓取节点当前坐标。力导向动画中：模拟器逐帧把坐标写进 seriesModel.preservedPoints
//（id -> [x,y]），模型图谱节点上是同一份布局，作兜底；
// 停放中：布局即数据坐标（含手动拖拽的最新位置），preservedPoints 已过期必须跳过
function capturePositions() {
  if (!chart || !result.value) return
  const seriesModel = chart.getModel() && chart.getModel().getSeriesByIndex(0)
  if (!seriesModel || seriesModel.type !== 'series.graph') return
  const graph = seriesModel.getGraph()
  const fromGraph = () => {
    if (!graph) return
    graph.eachNode((node) => {
      const l = node.getLayout()
      if (l && Number.isFinite(l[0]) && Number.isFinite(l[1])) frozenPos.set(node.id, { x: l[0], y: l[1] })
    })
  }
  if (frozen.value) {
    fromGraph()
    return
  }
  const preserved = seriesModel.preservedPoints
  if (preserved) {
    for (const [id, p] of Object.entries(preserved)) {
      if (p && Number.isFinite(p[0]) && Number.isFinite(p[1])) frozenPos.set(id, { x: p[0], y: p[1] })
    }
  }
  if (frozenPos.size) return
  fromGraph()
}

// 停放期间增量 setOption（展开节点）前调用：把当前节点布局（含拖拽后的位置）
// 同步回 preservedPoints，并把新增节点锚定到邻居附近——否则新节点会被随机放置
// 且因 friction=0 冻在原地，被拖过的节点也会跳回停放时的位置
function syncFrozenPositions() {
  if (!frozen.value || !chart || !result.value) return
  const seriesModel = chart.getModel() && chart.getModel().getSeriesByIndex(0)
  if (!seriesModel || seriesModel.type !== 'series.graph') return
  capturePositions()
  const preserved = seriesModel.preservedPoints
  if (!preserved) return
  for (const [id, p] of frozenPos) preserved[id] = [p.x, p.y]
  const adj = new Map()
  for (const e of result.value.edges) {
    if (!adj.has(e.source)) adj.set(e.source, [])
    if (!adj.has(e.target)) adj.set(e.target, [])
    adj.get(e.source).push(e.target)
    adj.get(e.target).push(e.source)
  }
  let cx = 0, cy = 0, cnt = 0
  for (const p of frozenPos.values()) { cx += p.x; cy += p.y; cnt++ }
  if (cnt) { cx /= cnt; cy /= cnt }
  for (const n of result.value.nodes) {
    if (preserved[n.id]) continue
    const anchor = (adj.get(n.id) || []).map((id) => frozenPos.get(id)).find(Boolean)
    const a = Math.random() * Math.PI * 2
    const r = anchor ? 46 : 150
    const p = [(anchor ? anchor.x : cx) + r * Math.cos(a), (anchor ? anchor.y : cy) + r * Math.sin(a)]
    preserved[n.id] = p
    frozenPos.set(n.id, { x: p[0], y: p[1] })
  }
}

function resetFreeze() {
  frozen.value = false
  frozenPos.clear()
}

// friction 0.6 是 ECharts force 的默认初值；置 0 时模拟一步即停、节点原地冻结
function setForceFriction(v) {
  chart?.setOption({ series: [{ force: { friction: v } }] })
}

function toggleFreeze() {
  if (!chart || !nodeCount.value) return
  if (frozen.value) {
    frozen.value = false
    frozenPos.clear()
    setForceFriction(0.6) // 内部 preservedPoints 保留了坐标，从当前位置继续温和收敛
    return
  }
  capturePositions()
  frozen.value = true
  setForceFriction(0)
}

// 布局模式切换：离开力导向即解除停放（分层布局坐标固定，与停放互斥）
function setLayoutMode(m) {
  if (layoutMode.value === m) {
    if (m === 'force' && frozen.value) toggleFreeze()
    return
  }
  resetFreeze()
  layoutMode.value = m // 触发下方 watch 整体重渲染
}

function relayout() {
  resetFreeze()
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
  if (!chart || !result.value || frozen.value) return // 停放时力参数不起作用，不触发重布局
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

function adoptTarget() {
  if (!selected.value) return
  setUid(selected.value.platform, selected.value.uid)
  setView(selected.value.platform)
}

function homeUrl(n) {
  const fn = USER_LINKS[n.platform]
  return fn ? fn(n) : ''
}

onMounted(async () => {
  chart = echarts.init(stageEl.value)
  chart.on('click', onChartClick)
  ro = new ResizeObserver(() => chart && chart.resize())
  ro.observe(stageEl.value)
  if (import.meta.env.DEV) window.__vgChart = chart // 调试句柄：控制台可直接检查/驱动图表
  // 侧边栏点击已保存图谱后切到这里：立即用库内数据渲染
  consumePendingGraph()
  // 图数据全部存后端：进入图谱页时若没有待恢复的图，自动调出最近一张，
  // 这样刷新页面/重配 Cookie 后画布不再空空如也
  if (!result.value && !state.pendingGraph) {
    try {
      await loadSavedGraphs()
      const latest = state.savedGraphs[0]
      if (latest) await openSavedGraph(latest.id)
    } catch {
      /* 后端不可达时保持空态，用户可正常搜索 */
    }
  }
})

onBeforeUnmount(() => {
  stopQueuePolling()
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
        <span
          v-for="p in chipPlatforms"
          :key="p.id"
          class="vg-chip"
          :class="{ off: disabledPlatforms.includes(p.id) }"
          :title="p.noCookie
            ? p.name + '：未配置 Cookie，搜索大概率失败（点击停用/启用该平台；铅笔可设专属搜索词）'
            : (disabledPlatforms.includes(p.id) ? '点击启用该平台（铅笔可设专属搜索词）' : '点击停用该平台（铅笔可设专属搜索词）')"
        >
          <template v-if="editingPlatform === p.id">
            <span class="vg-chip-dot" :style="{ background: p.color }" />
            <input
              v-model="editVal"
              class="vg-chip-kw"
              :data-pid="p.id"
              :placeholder="`搜索词，留空用主关键词`"
              @keydown.enter.prevent="commitKeyword(p.id)"
              @keydown.esc.prevent="cancelEditKeyword"
              @blur="commitKeyword(p.id)"
            />
          </template>
          <template v-else>
            <span class="vg-chip-click" @click="togglePlatform(p.id)">
              <span class="vg-chip-dot" :class="{ hollow: p.noCookie }" :style="{ background: p.noCookie ? 'transparent' : p.color }" />{{ p.name }}
            </span>
            <span
              v-if="platformKeywords[p.id]"
              class="vg-chip-ov"
              :title="p.name + ' 专属搜索词：' + platformKeywords[p.id]"
            >{{ platformKeywords[p.id] }}</span>
            <button
              class="vg-chip-edit"
              :title="'设置 ' + p.name + ' 专属搜索词（该平台搜别的词）'"
              @click="startEditKeyword(p.id)"
            >
              <Icon name="edit" :size="10" />
            </button>
          </template>
        </span>
      </div>

      <div class="vg-ctls">
        <label class="vg-ctl" :class="{ dim: layoutMode === 'layer' || frozen }"><span>斥力 {{ forceParams.repulsion }}</span>
          <input v-model.number="forceParams.repulsion" type="range" min="50" max="800" step="10" :disabled="layoutMode === 'layer' || frozen" />
        </label>
        <label class="vg-ctl" :class="{ dim: layoutMode === 'layer' || frozen }"><span>引力 {{ forceParams.gravity.toFixed(2) }}</span>
          <input v-model.number="forceParams.gravity" type="range" min="0" max="0.5" step="0.01" :disabled="layoutMode === 'layer' || frozen" />
        </label>
        <label class="vg-ctl" :class="{ dim: layoutMode === 'layer' || frozen }"><span>边长 {{ forceParams.edgeLength }}</span>
          <input v-model.number="forceParams.edgeLength" type="range" min="30" max="300" step="10" :disabled="layoutMode === 'layer' || frozen" />
        </label>
        <label class="vg-ctl vg-ctl-num" title="单次展开一个用户时，关注/粉丝各最多拉取多少人（10~500）；达上限且对方还有更多人时，可再次展开">
          <span>每次展开上限 {{ expandLimit }}</span>
          <input
            type="number"
            :value="expandLimit"
            min="10"
            max="500"
            step="10"
            @change="setExpandLimit($event.target.value)"
            @keydown.enter="setExpandLimit($event.target.value); $event.target.blur()"
          />
        </label>
        <button
          class="btn btn-sm"
          :class="{ 'btn-primary': frozen }"
          :disabled="!nodeCount || layoutMode === 'layer'"
          :title="frozen
            ? '解除停放：节点从当前位置继续自动收敛（也可切回分层布局）'
            : '停放：冻结当前布局，之后节点不再自动运动，可拖拽手动摆放'"
          @click="toggleFreeze"
        >
          <Icon :name="frozen ? 'play' : 'pause'" :size="13" /> {{ frozen ? '恢复' : '停放' }}
        </button>
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
            <button :class="{ on: layoutMode === 'force' }" @click="setLayoutMode('force')">力导向</button>
            <button :class="{ on: layoutMode === 'layer' }" title="按平台分区排布，关键词居中" @click="setLayoutMode('layer')">分层</button>
          </div>
        </div>

        <div class="vg-group">
          <button
            class="btn btn-sm"
            :class="{ 'btn-primary': !bulk.busy }"
            :disabled="!nodeCount"
            :title="viewFilter === 'all' ? '对当前图所有用户节点展开关注+粉丝（每人每方向限 20 人）；执行中再点可追加其他节点/平台' : '对当前筛选视图下的用户节点展开关注+粉丝（每人每方向限 20 人）'"
            @click="bulkExpand"
          >
            <span v-if="bulk.busy" class="spinner spinner-sm" />
            {{ bulk.busy ? `展开中 (${bulk.done}/${bulk.total})，点击追加` : '一键展开' }}
          </button>
          <button
            v-if="bulk.busy"
            class="btn btn-sm"
            title="停止当前图还在排队的展开任务（已在执行的照常完成）"
            @click="stopBulk"
          >
            停止
          </button>
          <span v-if="bulkMsg" class="vg-bulk-msg">{{ bulkMsg }}</span>
          <button
            class="btn btn-sm"
            :disabled="!nodeCount || remark.busy"
            title="重新拉取图内每个节点的粉丝数/认证标记，修正旧图的大V判定（旧图灰化不准时使用）"
            @click="remarkNodes"
          >
            <span v-if="remark.busy" class="spinner spinner-sm" />
            {{ remark.busy ? '重新标记中…' : '重新标记' }}
          </button>
          <span v-if="remarkMsg && !remark.busy" class="vg-bulk-msg">{{ remarkMsg }}</span>
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
          绿色粗线 = 互相关注；红色实线 = 跨平台完全同名（疑似同一人）；红色虚线 = 昵称相似；紫色实线 = 手动标记同人（点击连线解除）；<br />
          蓝色箭头 = 单向关注（谁指向谁就是谁在关注谁）；灰色小点 = 粉丝 1000+ 或平台认证的公众账号/达人；<br />
          各平台昵称不同？点平台 chip 旁的铅笔给该平台设专属搜索词；信息卡里可"标记同人"手动关联跨平台账号；<br />
          悬浮在连线或节点上可查看关系说明；节点大小与粉丝数成反比（粉丝越多节点越小）；点击节点可在卡片中选择"不看"来排除干扰节点
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

      <!-- 布局已停放：提示可手动拖拽摆放节点 -->
      <div v-if="frozen" class="vg-loading-pill vg-frozen-pill">
        <Icon name="pause" :size="12" />
        布局已停放：节点不再自动运动，可直接拖拽摆放；点击工具栏「恢复」继续收敛
      </div>

      <!-- 手动标记同人连线模式：点击另一账号完成连线 -->
      <div v-if="linkSource" class="vg-loading-pill vg-link-pill">
        <Icon name="users" :size="12" />
        标记同人「{{ linkSource.nickname }}」：点击图中另一账号完成连线（点它自己取消）
        <button class="vg-link-cancel" @click="linkSource = null">取消</button>
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
            class="btn btn-sm"
            title="把该账号与图中另一账号手动连为同一人（目标人物跨平台昵称不同时使用），点错可再点连线解除"
            @click="startLinkFrom(selected)"
          ><Icon name="users" :size="12" /> 标记同人</button>
          <button
            class="btn btn-sm vg-btn-danger"
            title="把该节点从图中移除（认为价值不大），仅通过它连入图的子节点会一并排除；可随时点击下方计数还原"
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
              {{ expandBusyIds.has(selectedId) ? '展开中…' : canExpandMore(selected) ? '继续展开' : '一键展开' }}
            </button>
          </div>
          <p class="vg-info-tip">
            <template v-if="selectedProgText">{{ selectedProgText }}；</template>
            拉取该用户的关注+粉丝（关注各最多 {{ expandLimit }} 人），并自动互查邻居之间的关注关系；可同时展开多个节点
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
        <b>{{ edgeCount }}</b> 条关系（同名 {{ sameCount }} · 关注 {{ followsCount }}<template v-if="manualCount"> · 手动同人 {{ manualCount }}</template>）
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

/* 平台 chip 内部：主体点击区（开关平台）+ 专属搜索词预览 + 编辑入口 */
.vg-chip-click {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
}

.vg-chip-ov {
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0 6px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  line-height: 16px;
}

.vg-chip-edit {
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
  padding: 0;
}

.vg-chip-edit:hover {
  background: var(--surface-hover);
  color: var(--accent);
}

/* chip 内的专属搜索词输入态 */
.vg-chip-kw {
  width: 110px;
  border: none;
  outline: none;
  padding: 0;
  font-size: 12px;
  font-family: inherit;
  color: var(--text);
  background: transparent;
}

.vg-chip-kw::placeholder {
  color: var(--text-3);
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

.vg-frozen-pill {
  top: 48px;
  color: var(--accent, #2f7d5d);
}

/* 手动标记同人连线模式提示：pointer-events 默认关闭会挡取消按钮，单独恢复 */
.vg-link-pill {
  top: 48px;
  color: #7c4dff;
  pointer-events: auto;
  gap: 9px;
}

.vg-link-cancel {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  padding: 1px 9px;
  font-size: 11px;
  color: var(--text-2);
  cursor: pointer;
}

.vg-link-cancel:hover {
  color: #7c4dff;
  border-color: #7c4dff;
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

.vg-ctl-num input[type='number'] {
  width: 72px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 3px 6px;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-2);
  background: var(--surface);
}

.vg-ctl-num input[type='number']:focus {
  outline: none;
  border-color: var(--accent);
}

.vg-ctl-num input[type='number']::-webkit-inner-spin-button {
  opacity: 1;
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
  flex-wrap: wrap;
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
