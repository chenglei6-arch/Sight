import { PLATFORMS } from "../../platforms";
import type {
  GraphData,
  GraphEdge,
  GraphNode,
  ExpandPayload,
} from "../../types";
import { fmtNum } from "../../utils";
import type { GraphController } from "./controller";
export function isIrrelevant(
  this: GraphController,
  n: GraphNode | null | undefined,
) {
  if (!n || n.platform === "keyword") return false;
  if (n.verified) return true;
  return Number(n.fans) >= this.IRRELEVANT_FANS;
}
export function irrelevantReason(
  this: GraphController,
  n: GraphNode | null | undefined,
) {
  if (!n) return "";
  if (n.verified) return "平台认证的公众账号/达人";
  return `粉丝 ${fmtNum(Number(n.fans))}，疑似大V/公众账号`;
}
export function cascadeHiddenAfter(this: GraphController, removeId: string) {
  const data = this.result;
  if (!data) return [];
  const adj = new Map<string, Set<string>>();
  for (const e of this.deriveDisplayEdges()) {
    if (e.source === removeId || e.target === removeId) continue;
    if (this.hiddenNodeIds.has(e.source) || this.hiddenNodeIds.has(e.target))
      continue;
    if (!adj.has(e.source)) adj.set(e.source, new Set());
    if (!adj.has(e.target)) adj.set(e.target, new Set());
    adj.get(e.source)!.add(e.target);
    adj.get(e.target)!.add(e.source);
  }
  const seen = new Set(["keyword"]);
  const queue = ["keyword"];
  while (queue.length) {
    for (const nb of adj.get(queue.pop()!) || []) {
      if (!seen.has(nb)) {
        seen.add(nb);
        queue.push(nb);
      }
    }
  }
  return data.nodes
    .filter(
      (n) =>
        n.platform !== "keyword" &&
        !this.hiddenNodeIds.has(n.id) &&
        !seen.has(n.id),
    )
    .map((n) => n.id);
}
export function nodeSize(this: GraphController, fans: unknown) {
  const f = Number(fans) || 0;
  // 对数映射：10 粉及以下 → 125%，100 万粉及以上 → 50%（图内多为小粉丝量账号，
  // 区间取宽才能让低粉丝段也有可见的大小差异，否则全部顶在上限）
  const t = f > 10 ? Math.min(1, Math.max(0, (Math.log10(f) - 1) / 5)) : 0;
  return this.NODE_SIZE_BASE * (1.25 - 0.75 * t);
}
export function esc(this: GraphController, s: unknown) {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
}
export function normNick(this: GraphController, name: string) {
  return String(name || "")
    .normalize("NFKC")
    .replace(/\s+/g, "")
    .toLowerCase();
}
export function deriveDisplayEdges(this: GraphController) {
  const data = this.result;
  if (!data) return [];
  const out: GraphEdge[] = [];
  const seen = new Set<string>();
  const follows: GraphEdge[] = [];
  for (const e of data.edges || []) {
    if (e.relation !== "follows") continue;
    const k = `${e.source}\u0001${e.target}`;
    if (seen.has(k)) continue;
    seen.add(k);
    follows.push(e);
  }
  // 互相关注：同平台 a→b 与 b→a 同时存在 → 保留一条绿色 mutual 边
  // 反向索引存"正向" key → 边下标；查"反向" key 找到对应边
  const revIndex = new Map<string, number>();
  follows.forEach((e, i) => revIndex.set(`${e.source}\u0001${e.target}`, i));
  const consumed = new Set<number>();
  for (let i = 0; i < follows.length; i++) {
    if (consumed.has(i)) continue;
    const e = follows[i];
    const j = revIndex.get(`${e.target}\u0001${e.source}`);
    const samePlatform = this.platOf(e.source) === this.platOf(e.target);
    if (j !== undefined && j !== i && !consumed.has(j) && samePlatform) {
      consumed.add(i);
      consumed.add(j);
      out.push({ source: e.source, target: e.target, relation: "mutual" });
    } else {
      consumed.add(i);
      out.push({ ...e });
    }
  }
  // 其余原始边（hit / same / alike / manual）保持原样
  for (const e of data.edges || []) {
    if (e.relation === "follows") continue;
    out.push({ ...e });
  }
  // 补算跨平台完全同名：为展开后新增的节点匹配图中其他平台节点
  const normBuckets = new Map<
    string,
    Array<{ id: string; platform: string }>
  >();
  for (const n of data.nodes || []) {
    if (n.platform === "keyword") continue;
    const norm = this.normNick(n.nickname || "");
    if (!norm) continue;
    const id = n.id || `${n.platform}:${n.uid}`;
    if (!normBuckets.has(norm)) normBuckets.set(norm, []);
    normBuckets.get(norm)!.push({ id, platform: n.platform });
  }
  const hasAlias = new Set<string>();
  for (const e of out)
    if (e.relation === "same" || e.relation === "alike")
      hasAlias.add(this.pairKey(e.source, e.target));
  for (const list of normBuckets.values()) {
    if (list.length < 2) continue;
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        if (list[i].platform === list[j].platform) continue; // 同平台重名不连，避免误判
        const k = this.pairKey(list[i].id, list[j].id);
        if (hasAlias.has(k)) continue;
        hasAlias.add(k);
        out.push({ source: list[i].id, target: list[j].id, relation: "same" });
      }
    }
  }
  return out;
}
export function computeLayerPositions(this: GraphController, data: GraphData) {
  const pos: Record<string, { x: number; y: number }> = {
    keyword: { x: 0, y: 0 },
  };
  const users = data.nodes.filter((n) => n.platform !== "keyword");
  const deg: Record<string, number> = {};
  for (const e of data.edges) {
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  }
  const platformOrder = PLATFORMS.filter((p) =>
    users.some((u) => u.platform === p.id),
  ).map((p) => p.id);
  const R = 430;
  const ringGap = 62;
  const caps = [1, 6, 12, 18, 26, 34];
  platformOrder.forEach((pid, pi) => {
    const baseAng = (2 * Math.PI * pi) / platformOrder.length - Math.PI / 2;
    const px = R * Math.cos(baseAng);
    const py = R * 0.72 * Math.sin(baseAng);
    const list = users
      .filter((u) => u.platform === pid)
      .sort((a, b) => (deg[b.id] || 0) - (deg[a.id] || 0));
    let idx = 0;
    for (let ring = 0; idx < list.length; ring++) {
      const cap =
        ring < caps.length
          ? caps[ring]
          : caps[caps.length - 1] + (ring - caps.length + 1) * 8;
      const radius = ring * ringGap;
      for (let j = 0; j < cap && idx < list.length; j++, idx++) {
        const a = (2 * Math.PI * j) / cap + baseAng;
        pos[list[idx].id] =
          radius === 0
            ? { x: px, y: py }
            : { x: px + radius * Math.cos(a), y: py + radius * Math.sin(a) };
      }
    }
  });
  return pos;
}

export function mergeGraph(this: GraphController, payload: ExpandPayload) {
  const nodes = this.result!.nodes;
  const edges = this.result!.edges;
  const ids = new Set(nodes.map((n) => n.id));
  const ekeys = new Set(
    edges.map((e) => `${e.source}|${e.target}|${e.relation}`),
  );
  let addedNodes = 0;
  let addedEdges = 0;
  for (const n of payload.nodes || []) {
    if (ids.has(n.id)) continue;
    ids.add(n.id);
    nodes.push(n);
    addedNodes++;
  }
  const newEdges = [
    ...(payload.edges || []),
    ...((payload.intercheck && payload.intercheck.edges) || []),
  ];
  for (const e of newEdges) {
    const k = `${e.source}|${e.target}|${e.relation}`;
    if (ekeys.has(k)) continue;
    ekeys.add(k);
    edges.push(e);
    addedEdges++;
  }
  return { nodes: addedNodes, edges: addedEdges };
}
