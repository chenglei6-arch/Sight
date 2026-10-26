import { api, errorMessage } from "../../api";
import { loadSavedGraphs, useAppStore } from "../../store";
import type { GraphController } from "./controller";
import { graphSaves } from "./persistence";

export function currentGraphName(this: GraphController) {
  return (this.graphName.trim() || this.lastSearched || "未命名图谱").slice(
    0,
    60,
  );
}

export async function persistGraph(
  this: GraphController,
  { quiet = false } = {},
): Promise<number | null> {
  if (!this.result || !this.nodeCount) return null;
  const version = this.version,
    revision = ++this.saveRevision,
    name = this.currentGraphName();
  this.graphName = name;
  this.saving = true;
  this.publish();
  const data = structuredClone({
    ...this.result,
    expanded_keys: [...this.expandedKeys],
    interchecked_ids: [...this.intercheckedIds],
    hidden_ids: [...this.hiddenNodeIds],
    expand_prog: Object.fromEntries(this.expandProg),
  });
  try {
    const id = await graphSaves.enqueue(async () => {
      try {
        const saved = await api.post<{ id: number }>("/graph/save", {
          name,
          keyword: data.keyword || this.lastSearched,
          data,
        });
        if (this.isCurrent(version)) {
          useAppStore.setState({ activeGraphId: saved.id });
          if (!quiet) this.saveMsg = `已保存为「${name}」，可在侧边栏随时调出`;
          this.publish();
        }
        void loadSavedGraphs();
        return saved.id;
      } catch (e) {
        if (this.isCurrent(version)) {
          this.saveMsg = `保存失败：${errorMessage(e)}`;
          this.publish();
        }
        return null;
      }
    }, name);
    return this.isCurrent(version) ? id : null;
  } finally {
    if (this.isCurrent(version) && revision === this.saveRevision) {
      this.saving = false;
      this.publish();
    }
  }
}

export function consumePendingGraph(this: GraphController) {
  const g = useAppStore.getState().pendingGraph;
  if (!g || !g.data) return;
  useAppStore.setState({ pendingGraph: null });
  this.beginGraph();
  this.bulk.stop = true; // 若一键展开还在跑，立即停下
  this.stopQueuePolling(); // 换图后旧图的队列结果不再合并，轮询随之停止
  this.expandBusyIds.clear();
  this.bulk.busy = false;
  this.pausedQueues = [];
  this.selected = null;
  this.error = "";
  this.searchFailedMsg = "";
  this.saveMsg = "";
  for (const k of Object.keys(this.expandMsgs)) delete this.expandMsgs[k];
  this.bulkMsg = "";
  this.remarkMsg = "";
  this.viewFilter = "all";
  this.expandedKeys.clear();
  this.intercheckedIds.clear();
  this.expandProg.clear();
  this.hiddenNodeIds.clear();
  this.dismissedKeys.clear();
  this.keyword = g.data.keyword || "";
  this.lastSearched = g.data.keyword || "";
  this.graphName = g.name || "";
  this.result = structuredClone(g.data);
  // 还原各平台专属搜索词：chip 显示与"换词即新图"判定都要对上这张图
  for (const k of Object.keys(this.platformKeywords))
    delete this.platformKeywords[k];
  for (const [k, v] of Object.entries(g.data.keywords || {})) {
    if (typeof v === "string" && v.trim()) this.platformKeywords[k] = v.trim();
  }
  this.lastOverridesKey = JSON.stringify(this.currentOverrides());
  // 还原保存时的展开/隐藏状态：展开高亮与互查去重恢复，手动排除的节点不重新出现
  for (const k of g.data.expanded_keys || []) this.expandedKeys.add(k);
  for (const k of g.data.interchecked_ids || []) this.intercheckedIds.add(k);
  for (const k of g.data.hidden_ids || []) this.hiddenNodeIds.add(k);
  for (const [k, v] of Object.entries(g.data.expand_prog || {})) {
    if (!v) continue;
    this.expandProg.set(k, {
      followsLoaded: v.followsLoaded || 0,
      followsMore: !!v.followsMore,
      followsTotal: v.followsTotal ?? null,
      followersLoaded: v.followersLoaded || 0,
      followersMore: !!v.followersMore,
      followersTotal: v.followersTotal ?? null,
    });
  }
  useAppStore.setState({ activeGraphId: g.id });
  this.resetFreeze(); // 载入已保存图谱：坐标缓存属于旧图，直接作废
  const version = this.version;
  queueMicrotask(() => {
    if (this.isCurrent(version)) {
      this.render();
      this.startQueuePolling();
    }
  });
}
