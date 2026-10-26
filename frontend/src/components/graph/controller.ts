import { GraphChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { createStore, type StoreApi } from "zustand/vanilla";
import { api, errorMessage } from "../../api";
import { PLATFORMS, PLATFORM_MAP } from "../../platforms";
import {
  isPlatformId,
  invalidateGraphOpen,
  loadSavedGraphs,
  openSavedGraph,
  setUid,
  setView,
  useAppStore,
} from "../../store";
import type {
  ExpandProgress,
  GraphData,
  GraphNode,
  PausedQueue,
} from "../../types";
import {
  cascadeHiddenAfter,
  computeLayerPositions,
  deriveDisplayEdges,
  esc,
  irrelevantReason,
  isIrrelevant,
  mergeGraph,
  nodeSize,
  normNick,
} from "./algorithms";
import {
  buildOption,
  capturePositions,
  exportPng,
  relayout,
  render,
  resetFreeze,
  setForceFriction,
  setLayoutMode,
  syncFrozenPositions,
  toggleFreeze,
} from "./chart";
import {
  applyTaskResult,
  bulkExpand,
  enqueueExpandTasks,
  ensureGraphId,
  expandSocial,
  finalizeBulk,
  intercheckSkipList,
  pollQueueLoop,
  saveExpandCursors,
  sleep,
  startQueuePolling,
  stopBulk,
  stopQueuePolling,
} from "./queue";
import { consumePendingGraph, currentGraphName, persistGraph } from "./session";
export interface ChartClick {
  dataType?: string;
  data?: { raw?: GraphNode; source: string; target: string; relation: string };
}
echarts.use([GraphChart, TooltipComponent, CanvasRenderer]);
export class GraphController {
  USER_LINKS: Record<string, (node: GraphNode) => string> = {
    bilibili: (n) => `https://space.bilibili.com/${n.uid}`,
    netease: (n) => `https://music.163.com/#/user/home?id=${n.uid}`,
    weibo: (n) => `https://weibo.com/u/${n.uid}`,
    xhs: (n) => `https://www.xiaohongshu.com/user/profile/${n.uid}`,
    douyin: (n) =>
      n.sec_uid ? `https://www.douyin.com/user/${n.sec_uid}` : "",
  };
  SOCIAL_SUPPORT: Record<string, boolean> = {
    bilibili: true,
    netease: true,
    weibo: true,
    douyin: true,
  };
  EXPAND_LIMIT_KEY = "graph_expand_limit";
  expandLimit = this.loadExpandLimit();
  ACCENT = "#3565e0";
  SAME_COLOR = "#d5372f";
  MUTUAL_COLOR = "#1e9e55"; // 互相关注：绿色实线
  MANUAL_COLOR = "#7c4dff"; // 手动标记同人：紫色实线
  IRRELEVANT_FANS = 1000;
  keyword = "";
  loading = false;
  error = "";
  result: GraphData | null = null;
  lastSearched = "";
  disabledPlatforms: string[] = [];
  selected: GraphNode | null = null;
  searchFailedMsg = "";
  dismissedKeys: Set<string> = new Set<string>();
  hiddenNodeIds: Set<string> = new Set<string>();
  get hiddenCount() {
    return this.hiddenNodeIds.size;
  }
  platformKeywords: Record<string, string> = {};
  editingPlatform = "";
  editVal = "";
  lastOverridesKey = ""; // 当前已展示图谱使用的覆盖表序列化，用于"换词即新图"判定
  graphName = "";
  saving = false;
  saveMsg = "";
  linkSource: GraphNode | null = null;
  manualMsg = "";
  cookieModal = { open: false, platform: "" };
  expandedKeys: Set<string> = new Set<string>();
  intercheckedIds: Set<string> = new Set<string>();
  expandProg: Map<string, ExpandProgress> = new Map<string, ExpandProgress>();
  expandBusyIds: Set<string> = new Set<string>();
  expandMsgs: Record<string, string> = {};
  viewFilter = "all";
  layoutMode = "force";
  frozen = false;
  frozenPos: Map<string, { x: number; y: number }> = new Map<
    string,
    { x: number; y: number }
  >();
  bulk = {
    busy: false,
    done: 0,
    total: 0,
    stop: false,
    addNodes: 0,
    addEdges: 0,
    icHits: 0,
    failed: 0,
    failReasons: new Map<string, number>(),
    ids: new Set<number>(), // 本次一键展开入队的任务 id：进度只统计这些，历史积压/单独展开的结果不占进度
  };
  bulkMsg = "";
  get chipPlatforms() {
    return PLATFORMS.map((p) => {
      const meta = useAppStore
        .getState()
        .platformsMeta.find((m) => m.id === p.id);
      return {
        id: p.id,
        name: p.name,
        color: p.color,
        noCookie: !!(meta && !meta.has_credential),
      };
    });
  }
  get selectedId() {
    return this.selected
      ? `${this.selected.platform}:${this.selected.uid}`
      : "";
  }
  get selectedExpandMsg() {
    return this.selected ? this.expandMsgs[this.selectedId] || "" : "";
  }
  get selectedExpandMsgIsError() {
    return /^(未获取到数据|展开失败|接口报错)/.test(this.selectedExpandMsg);
  }
  get expandBusyNames() {
    return [...this.expandBusyIds].map(
      (id) => this.result?.nodes.find((n) => n.id === id)?.nickname || id,
    );
  }
  get selectedProgText() {
    if (!this.selected) return "";
    const p = this.expandProg.get(this.selectedId);
    if (!p || (p.followsLoaded === 0 && p.followersLoaded === 0)) return "";
    const parts = [];
    if (p.followsLoaded) {
      const tip = p.followsTotal != null ? `/${p.followsTotal}` : "";
      parts.push(
        `已展开关注 ${p.followsLoaded}${tip}${p.followsMore ? "，还有更多" : ""}`,
      );
    }
    if (p.followersLoaded) {
      const tip = p.followersTotal != null ? `/${p.followersTotal}` : "";
      parts.push(
        `粉丝 ${p.followersLoaded}${tip}${p.followersMore ? "，还有更多" : ""}`,
      );
    }
    return parts.join(" · ");
  }
  get presentPlatforms() {
    if (!this.result) return [];
    const ids = new Set(this.result!.nodes.map((n) => n.platform));
    return PLATFORMS.filter((p) => ids.has(p.id)).map(
      ({ id, name, color }) => ({ id, name, color }),
    );
  }
  get selectedCounts() {
    if (!this.selected) return null;
    let following = 0;
    let followers = 0;
    for (const e of this.deriveDisplayEdges()) {
      if (e.relation !== "follows" && e.relation !== "mutual") continue;
      if (e.source === this.selectedId) following++;
      if (e.target === this.selectedId) followers++;
    }
    return { following, followers };
  }
  EXPAND_CURSOR_KEY = "graph_expand_poll_cursors";
  queuePoll = {
    active: false,
    cursors: new Map<number, number>(this.loadExpandCursors()),
    gen: 0,
  };
  pausedQueues: PausedQueue[] = [];
  remark = { busy: false };
  remarkMsg = "";
  stageEl: HTMLDivElement | null = null;
  chart: echarts.EChartsType | null = null;
  ro: ResizeObserver | null = null;
  forceParams = { repulsion: 260, gravity: 0.1, edgeLength: 100 };
  get nodeCount() {
    if (!this.result) return 0;
    // 展示给用户的节点数：排除手动隐藏，大V弱相关照常计入（用户可再次点开查看）
    return this.result!.nodes.filter(
      (n) => n.platform !== "keyword" && !this.hiddenNodeIds.has(n.id),
    ).length;
  }
  get edgeCount() {
    if (!this.result) return 0;
    return this.deriveDisplayEdges().filter(
      (e) =>
        !this.hiddenNodeIds.has(e.source) && !this.hiddenNodeIds.has(e.target),
    ).length;
  }
  get sameCount() {
    return this.result
      ? this.deriveDisplayEdges().filter((e) => e.relation === "same").length
      : 0;
  }
  get followsCount() {
    if (!this.result) return 0;
    const all = this.deriveDisplayEdges();
    const follows = all.filter((e) => e.relation === "follows").length;
    const mutual = all.filter((e) => e.relation === "mutual").length;
    return follows + mutual;
  }
  get manualCount() {
    return this.result
      ? this.result!.edges.filter((e) => e.relation === "manual").length
      : 0;
  }
  get searchErrors() {
    return this.result ? Object.entries(this.result.errors || {}) : [];
  }
  get taskText() {
    if (this.loading)
      return `正在跨平台搜索「${this.lastSearched || this.keyword}」…个别平台可能较慢`;
    const parts = [];
    if (this.expandBusyIds.size) {
      const names = this.expandBusyNames;
      parts.push(
        `正在展开 ${names.length} 个节点的关注/粉丝：${names.slice(0, 3).join("、")}${names.length > 3 ? " 等" : ""}…`,
      );
    }
    if (this.bulk.busy) parts.push(this.bulkMsg);
    else if (this.queuePoll.active && !this.expandBusyIds.size)
      parts.push("后台展开队列执行中，结果将自动合入当前图谱…");
    if (this.remark.busy) parts.push(this.remarkMsg);
    return parts.join(" · ");
  }
  get noCookieSearched() {
    if (!this.result) return [];
    const produced = new Set([
      ...(this.result.platforms || []),
      ...Object.keys(this.result.errors || {}),
    ]);
    const metaById = new Map<string, import("../../types").PlatformMeta>(
      useAppStore.getState().platformsMeta.map((m) => [m.id, m]),
    );
    return (this.result.searched || []).filter((pid) => {
      const meta = metaById.get(pid);
      return !produced.has(pid) && meta && meta.has_credential === false;
    });
  }
  get stripItems() {
    const items = [];
    if (this.saveMsg && !this.dismissedKeys.has("save"))
      items.push({
        key: "save",
        kind: this.saveMsg.includes("失败") ? "err" : "ok",
        color: this.saveMsg.includes("失败") ? "#d5372f" : "#1e9e55",
        text: this.saveMsg,
      });
    if (this.searchFailedMsg && !this.dismissedKeys.has("req"))
      items.push({
        key: "req",
        kind: "err",
        color: "#d5372f",
        text: `搜索请求失败：${this.searchFailedMsg}`,
      });
    if (this.manualMsg && !this.dismissedKeys.has("manual"))
      items.push({
        key: "manual",
        kind: "ok",
        color: this.MANUAL_COLOR,
        text: this.manualMsg,
      });
    for (const [pid, msg] of this.searchErrors) {
      const key = "err:" + pid;
      if (this.dismissedKeys.has(key)) continue;
      items.push({
        key,
        kind: "err",
        color: PLATFORM_MAP[pid]?.color || "#d5372f",
        text: `${PLATFORM_MAP[pid]?.name || pid}：${msg}`,
        platform: pid,
      });
    }
    for (const pid of this.noCookieSearched) {
      const key = "nc:" + pid;
      if (this.dismissedKeys.has(key)) continue;
      items.push({
        key,
        kind: "notice",
        color: "#c9cdd3",
        text: `${PLATFORM_MAP[pid]?.name || pid}：未配置 Cookie，无法搜索`,
        platform: pid,
      });
    }
    const cached = this.result?.cached || [];
    if (cached.length && !this.dismissedKeys.has("cached"))
      items.push({
        key: "cached",
        kind: "notice",
        color: "#9aa1ab",
        text: `${cached.map((p) => PLATFORM_MAP[p]?.name || p).join("、")} 的结果来自 30 分钟内缓存`,
      });
    // 展开队列熔断暂停的平台（连续多次失败，典型是 Cookie 失效）：提示并支持点击配置
    for (const pq of this.pausedQueues) {
      const key = "qp:" + pq.platform;
      if (this.dismissedKeys.has(key)) continue;
      items.push({
        key,
        kind: "err",
        color: PLATFORM_MAP[pq.platform]?.color || "#d5372f",
        text: `${PLATFORM_MAP[pq.platform]?.name || pq.platform} 展开队列已暂停：${pq.reason}（配置 Cookie 后自动恢复）`,
        platform: pq.platform,
      });
    }
    return items;
  }
  NODE_SIZE_BASE = 24;
  pairKey = (a: string, b: string) =>
    a < b ? `${a}\u0001${b}` : `${b}\u0001${a}`;
  platOf = (id: string) => String(id || "").split(":")[0];
  loadExpandLimit() {
    try {
      const v = parseInt(localStorage.getItem(this.EXPAND_LIMIT_KEY) || "", 10);
      if (v >= 10 && v <= 500) return v;
    } catch {
      /* 忽略 */
    }
    return 100;
  }
  setExpandLimit(v: number | string) {
    const n = Math.max(10, Math.min(500, Math.round(Number(v) || 100)));
    this.expandLimit = n;
    try {
      localStorage.setItem(this.EXPAND_LIMIT_KEY, String(n));
    } catch {
      /* 忽略 */
    }
  }
  isIrrelevant = isIrrelevant.bind(this);
  irrelevantReason = irrelevantReason.bind(this);
  cascadeHiddenAfter = cascadeHiddenAfter.bind(this);
  hideSelectedNode() {
    if (!this.selected) return;
    this.hiddenNodeIds.add(this.selectedId);
    // 仅通过该节点连进图的子节点（及其后代）一并隐藏，避免父节点删除后留下孤立漂浮点
    const cascade = this.cascadeHiddenAfter(this.selectedId);
    for (const id of cascade) this.hiddenNodeIds.add(id);
    const removed = this.result?.nodes.filter(
      (n) => (n.id || `${n.platform}:${n.uid}`) === this.selectedId,
    );
    if (removed?.length) this.selected = null;
    // 挂在被排除节点上的手动同人边一并清掉，避免残留到持久化数据里
    const gone = new Set([this.selectedId, ...cascade]);
    this.result!.edges = this.result!.edges.filter(
      (e) =>
        e.relation !== "manual" || (!gone.has(e.source) && !gone.has(e.target)),
    );
    // 展示层重渲染；结果数据里仍保留该节点，避免破坏后续展开 merge 的边索引
    if (this.chart && this.result) this.render();
    this.persistGraph({ quiet: true });
  }
  currentOverrides() {
    const out: Record<string, string> = {};
    for (const p of PLATFORMS) {
      const v = String(this.platformKeywords[p.id] || "").trim();
      if (v) out[p.id] = v;
    }
    return out;
  }
  startEditKeyword(pid: string) {
    this.editingPlatform = pid;
    this.editVal = String(this.platformKeywords[pid] || "");
  }
  commitKeyword(pid: string) {
    if (this.editingPlatform !== pid) return; // Enter 提交后触发 blur，防二次执行
    const v = this.editVal.trim();
    if (v) this.platformKeywords[pid] = v;
    else delete this.platformKeywords[pid];
    this.editingPlatform = "";
  }
  cancelEditKeyword() {
    this.editingPlatform = "";
  }
  currentGraphName = currentGraphName.bind(this);
  persistGraph = persistGraph.bind(this);
  consumePendingGraph = consumePendingGraph.bind(this);
  startLinkFrom(n: GraphNode | null) {
    if (!n || !this.result) return;
    this.linkSource = n;
    this.manualMsg = "";
  }
  addManualEdge(a: GraphNode, b: GraphNode) {
    const k = this.pairKey(a.id, b.id);
    if (
      this.result!.edges.some(
        (e) =>
          e.relation === "manual" && this.pairKey(e.source, e.target) === k,
      )
    ) {
      this.manualMsg = `${a.nickname} 与 ${b.nickname} 已标记过同人`;
      return;
    }
    this.result!.edges.push({ source: a.id, target: b.id, relation: "manual" });
    this.manualMsg = `已手动标记同人：${a.nickname} ↔ ${b.nickname}`;
    this.refreshChart();
    this.persistGraph({ quiet: true });
  }
  removeManualEdge(source: string, target: string) {
    const k = this.pairKey(source, target);
    const before = this.result!.edges.length;
    this.result!.edges = this.result!.edges.filter(
      (e) =>
        !(e.relation === "manual" && this.pairKey(e.source, e.target) === k),
    );
    if (this.result!.edges.length === before) return;
    this.manualMsg = "已解除手动同人标记";
    this.refreshChart();
    this.persistGraph({ quiet: true });
  }
  onChartClick(params: ChartClick) {
    if (params.dataType === "edge") {
      if (params.data?.relation === "manual")
        this.removeManualEdge(params.data.source, params.data.target);
      return;
    }
    if (params.dataType !== "node") return;
    const n = params.data?.raw;
    if (this.linkSource) {
      const src = this.linkSource;
      this.linkSource = null;
      if (n && n.platform !== "keyword" && n.id !== src.id)
        this.addManualEdge(src, n);
      return; // 点了关键词节点或自己：视为取消连线模式
    }
    this.selected = n && n.platform !== "keyword" ? n : null;
    // 消息按节点独立保存：切换选中节点不影响其他节点的展开过程与结果
  }
  dismissStatus(key: string) {
    this.dismissedKeys.add(key);
  }
  openCookieConfig(pid: string) {
    if (!pid) return;
    this.cookieModal.platform = pid;
    this.cookieModal.open = true;
  }
  async onCookieSaved() {
    // Cookie 更新后若该平台队列因连续失败被熔断，立即恢复
    api.post("/graph/expand/resume", {}).catch(() => {});
    this.pausedQueues = [];
    // 不自动重搜：新搜索会用少量结果的新图替换当前已展开的图，
    // 且同名自动保存会把库里那张旧图一并覆盖（曾导致"重配 Cookie 后图全丢"）。
    // 当前图原样保留，需要最新数据时由用户手动重新搜索。
    if (this.lastSearched) {
      this.saveMsg = "Cookie 已更新，当前图已保留；需要最新数据请重新搜索";
    }
  }
  progOf(node: { platform: string; uid: string }) {
    const id = `${node.platform}:${node.uid}`;
    if (!this.expandProg.has(id))
      this.expandProg.set(id, {
        followsLoaded: 0,
        followsMore: false,
        followsTotal: null,
        followersLoaded: 0,
        followersMore: false,
        followersTotal: null,
      });
    return this.expandProg.get(id)!;
  }
  togglePlatform(id: string) {
    const i = this.disabledPlatforms.indexOf(id);
    if (i >= 0) this.disabledPlatforms.splice(i, 1);
    else if (this.disabledPlatforms.length < this.chipPlatforms.length - 1)
      this.disabledPlatforms.push(id); // 至少保留一个平台
  }
  async doSearch() {
    const kw = this.keyword.trim();
    if (!kw || this.loading) return;
    this.beginGraph();
    const version = this.version;
    this.loading = true;
    this.error = "";
    this.searchFailedMsg = "";
    this.saveMsg = "";
    this.selected = null;
    for (const k of Object.keys(this.expandMsgs)) delete this.expandMsgs[k];
    this.bulkMsg = "";
    this.remarkMsg = "";
    this.viewFilter = "all";
    this.expandedKeys.clear();
    this.intercheckedIds.clear();
    this.expandProg.clear();
    this.hiddenNodeIds.clear();
    this.dismissedKeys.clear();
    // 新搜索是一张新图：停掉旧图的队列轮询，清掉遗留的展开占用标记
    this.stopQueuePolling();
    this.expandBusyIds.clear();
    this.bulk.busy = false; // 旧图的队列进度不再跨图延续
    this.pausedQueues = [];
    this.lastSearched = kw;
    const overrides = this.currentOverrides();
    const overridesKey = JSON.stringify(overrides);
    // 换了主关键词或各平台专属搜索词就是一张新图：清掉继承自上一张图的名称，避免同名误覆盖旧图谱
    if (
      this.result &&
      this.result.keyword &&
      (this.result.keyword !== kw || overridesKey !== this.lastOverridesKey)
    )
      this.graphName = "";
    this.lastOverridesKey = overridesKey;
    useAppStore.setState({ activeGraphId: null }); // 新生成的图尚未保存，等待下方自动持久化后回填
    this.resetFreeze(); // 新图从随机布局开始，不继承上一张图的停放状态
    try {
      const platforms = this.chipPlatforms
        .map((p) => p.id)
        .filter((id) => !this.disabledPlatforms.includes(id));
      // 搜索期间保留旧图继续可交互；失败也不清空 result，错误只进状态条
      const params: Record<string, string> = {
        keyword: kw,
        platforms: platforms.join(","),
      };
      if (Object.keys(overrides).length)
        params.keywords = JSON.stringify(overrides);
      const payload = await api.get<GraphData>(
        "/graph/search",
        params,
        this.work.signal,
      );
      if (!this.isCurrent(version)) return;
      this.result = payload;
      this.result.keywords = overrides; // 覆盖表并入结果，persistGraph 随图自动保存
      this.render();
      // 生成即持久化：按名称输入框的名称（默认同关键词）入库，同名覆盖，供侧边栏调出
      if (this.visibleUserNodes().length) await this.persistGraph();
      else this.saveMsg = "未搜到用户节点，本次未保存图谱";
    } catch (e) {
      if (!this.isCurrent(version)) return;
      if (this.result) this.searchFailedMsg = errorMessage(e);
      else this.error = errorMessage(e);
    } finally {
      if (this.isCurrent(version)) this.loading = false;
    }
  }
  canExpandMore(node: GraphNode | null) {
    if (!node) return false;
    const p = this.expandProg.get(`${node.platform}:${node.uid}`);
    if (!p) return false;
    return (
      (p.followsLoaded > 0 && p.followsMore) ||
      (p.followersLoaded > 0 && p.followersMore)
    );
  }
  visibleUserNodes() {
    if (!this.result) return [];
    return this.result!.nodes.filter(
      (n) =>
        n.platform !== "keyword" &&
        !this.hiddenNodeIds.has(n.id) &&
        (this.viewFilter === "all" || n.platform === this.viewFilter),
    );
  }
  adjacentSamePlatformUids(n: GraphNode) {
    const id = `${n.platform}:${n.uid}`;
    const out = new Set<string>();
    for (const e of this.deriveDisplayEdges()) {
      if (e.relation !== "follows" && e.relation !== "mutual") continue;
      if (e.source === id && e.target.startsWith(n.platform + ":"))
        out.add(e.target.split(":")[1]);
      if (e.target === id && e.source.startsWith(n.platform + ":"))
        out.add(e.source.split(":")[1]);
    }
    return [...out];
  }
  mergeGraph = mergeGraph.bind(this);
  expandSocial = expandSocial.bind(this);
  intercheckSkipList = intercheckSkipList.bind(this);
  bulkExpand = bulkExpand.bind(this);
  stopBulk = stopBulk.bind(this);
  ensureGraphId = ensureGraphId.bind(this);
  enqueueExpandTasks = enqueueExpandTasks.bind(this);
  loadExpandCursors(): Array<[number, number]> {
    try {
      const raw: unknown = JSON.parse(
        localStorage.getItem(this.EXPAND_CURSOR_KEY) || "[]",
      );
      if (!Array.isArray(raw)) return [];
      return raw.filter(
        (v): v is [number, number] =>
          Array.isArray(v) &&
          v.length === 2 &&
          typeof v[0] === "number" &&
          typeof v[1] === "number",
      );
    } catch {
      return [];
    }
  }
  saveExpandCursors = saveExpandCursors.bind(this);
  startQueuePolling = startQueuePolling.bind(this);
  stopQueuePolling = stopQueuePolling.bind(this);
  sleep = sleep.bind(this);
  pollQueueLoop = pollQueueLoop.bind(this);
  applyTaskResult = applyTaskResult.bind(this);
  finalizeBulk = finalizeBulk.bind(this);
  async remarkNodes() {
    const version = this.version;
    if (this.remark.busy || !this.result) return;
    const targets = this.result!.nodes.filter(
      (n) => n.platform !== "keyword" && !this.hiddenNodeIds.has(n.id),
    );
    if (!targets.length) {
      this.remarkMsg = "当前图没有可重新标记的节点";
      return;
    }
    this.remark.busy = true;
    this.remarkMsg = `正在重新标记 ${targets.length} 个节点（逐个拉取平台资料，可能较慢）…`;
    try {
      const payload = await api.post<{
        nodes: GraphNode[];
        errors?: Record<string, string>;
      }>("/graph/refresh_nodes", {
        nodes: targets.map((n) => ({ platform: n.platform, uid: n.uid })),
      });
      if (!this.isCurrent(version)) return;
      let updated = 0;
      let bigV = 0;
      for (const r of payload.nodes || []) {
        const n = this.result!.nodes.find((x) => x.id === r.id);
        if (!n) continue;
        n.fans = r.fans;
        if (r.verified !== undefined) n.verified = r.verified;
        updated++;
        if (this.isIrrelevant(n)) bigV++;
      }
      this.syncFrozenPositions();
      this.refreshChart();
      const failedCnt = Object.keys(payload.errors || {}).length;
      this.remarkMsg =
        `重新标记完成：更新 ${updated} 个节点（其中大V ${bigV} 个）` +
        (failedCnt ? ` · ${failedCnt} 个失败（多为平台不支持或接口报错）` : "");
      // 新字段即时入库，之后调出这张图不用再刷
      if (updated > 0) this.persistGraph({ quiet: true });
    } catch (e) {
      if (!this.isCurrent(version)) return;
      this.remarkMsg = "重新标记失败：" + errorMessage(e);
    } finally {
      if (this.isCurrent(version)) this.remark.busy = false;
    }
  }
  nodeSize = nodeSize.bind(this);
  esc = esc.bind(this);
  normNick = normNick.bind(this);
  deriveDisplayEdges = deriveDisplayEdges.bind(this);
  computeLayerPositions = computeLayerPositions.bind(this);
  buildOption = buildOption.bind(this);
  render = render.bind(this);
  capturePositions = capturePositions.bind(this);
  syncFrozenPositions = syncFrozenPositions.bind(this);
  resetFreeze = resetFreeze.bind(this);
  setForceFriction = setForceFriction.bind(this);
  toggleFreeze = toggleFreeze.bind(this);
  setLayoutMode = setLayoutMode.bind(this);
  relayout = relayout.bind(this);
  exportPng = exportPng.bind(this);
  adoptTarget() {
    if (!this.selected || !isPlatformId(this.selected.platform)) return;
    setUid(this.selected.platform, this.selected.uid);
    setView(this.selected.platform);
  }
  homeUrl(n: GraphNode) {
    const fn = this.USER_LINKS[n.platform];
    return fn ? fn(n) : "";
  }

  work = new AbortController();
  pollEpoch = 0;
  pollRequest: AbortController | null = null;
  waitTimer: ReturnType<typeof setTimeout> | undefined;
  wakeWait: (() => void) | null = null;
  seenTaskIds = new Set<number>();
  saveRevision = 0;
  beginGraph() {
    invalidateGraphOpen();
    this.version++;
    this.work.abort();
    this.work = new AbortController();
    this.stopQueuePolling();
    this.seenTaskIds.clear();
    this.loading = false;
    this.saving = false;

    this.remark.busy = false;
    this.linkSource = null;
  }
  isCurrent(version: number) {
    return !this.disposed && version === this.version;
  }
  refreshChart() {
    const option = this.buildOption();
    if (option) this.chart?.setOption(option);
  }
  disposed = false;
  version = 0;
  unsubscribe: (() => void) | null = null;
  store: StoreApi<GraphSnapshot>;
  constructor() {
    this.store = createStore(() => this.getSnapshot());
  }
  getSnapshot() {
    return structuredClone({
      keyword: this.keyword,
      loading: this.loading,
      error: this.error,
      result: this.result,
      lastSearched: this.lastSearched,
      disabledPlatforms: this.disabledPlatforms,
      selected: this.selected,
      searchFailedMsg: this.searchFailedMsg,
      platformKeywords: this.platformKeywords,
      editingPlatform: this.editingPlatform,
      editVal: this.editVal,
      graphName: this.graphName,
      saving: this.saving,
      saveMsg: this.saveMsg,
      linkSource: this.linkSource,
      manualMsg: this.manualMsg,
      cookieModal: this.cookieModal,
      expandLimit: this.expandLimit,
      expandBusyIds: this.expandBusyIds,
      viewFilter: this.viewFilter,
      layoutMode: this.layoutMode,
      frozen: this.frozen,
      bulk: this.bulk,
      bulkMsg: this.bulkMsg,
      remark: this.remark,
      remarkMsg: this.remarkMsg,
      forceParams: this.forceParams,
      hiddenNodeIds: this.hiddenNodeIds,
      hiddenCount: this.hiddenCount,
      chipPlatforms: this.chipPlatforms,
      selectedId: this.selectedId,
      selectedExpandMsg: this.selectedExpandMsg,
      selectedExpandMsgIsError: this.selectedExpandMsgIsError,
      expandBusyNames: this.expandBusyNames,
      selectedProgText: this.selectedProgText,
      presentPlatforms: this.presentPlatforms,
      selectedCounts: this.selectedCounts,
      nodeCount: this.nodeCount,
      edgeCount: this.edgeCount,
      sameCount: this.sameCount,
      followsCount: this.followsCount,
      manualCount: this.manualCount,
      searchErrors: this.searchErrors,
      taskText: this.taskText,
      noCookieSearched: this.noCookieSearched,
      stripItems: this.stripItems,
    });
  }

  publish() {
    if (!this.disposed) this.store.setState(this.getSnapshot(), true);
  }
  run<T>(action: () => T): T {
    const result = action();
    this.publish();
    if (result instanceof Promise)
      void result.then(
        () => this.publish(),
        () => this.publish(),
      );
    return result;
  }
  setField<
    K extends
      | "keyword"
      | "graphName"
      | "editVal"
      | "viewFilter"
      | "selected"
      | "linkSource",
  >(key: K, value: GraphController[K]) {
    Object.assign(this, { [key]: value });
    if (key === "viewFilter") {
      this.selected = null;
      this.render();
    }
    this.publish();
  }
  updateForce(value: Partial<GraphController["forceParams"]>) {
    Object.assign(this.forceParams, value);
    if (!this.frozen)
      this.chart?.setOption({ series: [{ force: this.forceParams }] });
    this.publish();
  }
  setCookieOpen(value: boolean) {
    this.cookieModal.open = value;
    this.publish();
  }
  restoreHidden() {
    this.hiddenNodeIds.clear();
    this.render();
    void this.persistGraph({ quiet: true });
    this.publish();
  }
  async mount(stage: HTMLDivElement) {
    this.disposed = false;
    this.stageEl = stage;
    this.chart = echarts.init(stage);
    if (import.meta.env.DEV) window.__vgChart = this.chart;
    this.chart.on("click", (params) =>
      this.run(() => this.onChartClick(params as unknown as ChartClick)),
    );
    this.ro = new ResizeObserver(() => this.chart?.resize());
    this.ro.observe(stage);
    this.unsubscribe = useAppStore.subscribe((next, prev) => {
      if (next.pendingGraph && next.pendingGraph !== prev.pendingGraph)
        this.run(() => this.consumePendingGraph());
      else if (next.platformsMeta !== prev.platformsMeta) this.publish();
    });
    this.consumePendingGraph();
    this.publish();
    const version = this.version;
    if (!this.result && !useAppStore.getState().pendingGraph) {
      await loadSavedGraphs();
      if (this.disposed || version !== this.version || this.result) return;
      const latest = useAppStore.getState().savedGraphs[0];
      if (latest) await openSavedGraph(latest.id);
    }
  }
  dispose() {
    this.disposed = true;
    this.version++;
    this.work.abort();
    this.stopQueuePolling();
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.ro?.disconnect();
    if (window.__vgChart === this.chart) delete window.__vgChart;
    this.chart?.dispose();
    this.chart = null;
  }
}
export type GraphSnapshot = ReturnType<GraphController["getSnapshot"]>;
declare global {
  interface Window {
    __vgChart?: echarts.EChartsType;
  }
}
