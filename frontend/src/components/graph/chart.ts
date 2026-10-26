import * as echarts from "echarts/core";
import { PLATFORMS, PLATFORM_MAP } from "../../platforms";
import type { GraphEdge, GraphNode } from "../../types";
import { fmtNum } from "../../utils";
import type { GraphController } from "./controller";
export function buildOption(
  this: GraphController,
): echarts.EChartsCoreOption | null {
  const data = this.result;
  if (!data) return null;
  const categories = [
    { name: "关键词" },
    ...PLATFORMS.map((p) => ({ name: p.name })),
  ];
  const catIndex = (pid: string) =>
    pid === "keyword" ? 0 : PLATFORMS.findIndex((p) => p.id === pid) + 1;
  const platformName = (pid: string) =>
    pid === "keyword" ? "关键词" : PLATFORM_MAP[pid]?.name || pid;
  const rawById = new Map(data.nodes.map((n) => [n.id, n]));
  const layer = this.layoutMode === "layer";
  // 停放时把记录的坐标写进数据 x/y：正常 setOption 用不到（内部 preservedPoints 优先），
  // 但 chart.clear() 之后的重渲染靠它恢复原位
  const posMap = !layer && this.frozen ? this.frozenPos : null;
  const layerPos = layer ? this.computeLayerPositions(data) : null;
  const displayEdges = this.deriveDisplayEdges();
  // 视图筛选：只保留关键词 + 对应平台节点；手动隐藏的节点排除；大V仍在图内但灰化缩小
  const visibleIds = new Set(
    data.nodes
      .filter(
        (n) =>
          n.platform === "keyword" ||
          (!this.hiddenNodeIds.has(n.id) &&
            (this.viewFilter === "all" || n.platform === this.viewFilter)),
      )
      .map((n) => n.id),
  );
  // 边的关系说明（悬浮连线时展示）
  const edgeTip = (e: GraphEdge) => {
    const s = rawById.get(e.source);
    const t = rawById.get(e.target);
    if (!s || !t) return "";
    const sn = this.esc(s.nickname || s.uid);
    const tn = this.esc(t.nickname || t.uid);
    if (e.relation === "mutual")
      return (
        `<div class='g-tip-name'>${sn} ⇄ ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 与 <b>${tn}</b> 互相关注</div>`
      );
    if (e.relation === "follows")
      return (
        `<div class='g-tip-name'>${sn} → ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 关注了 <b>${tn}</b>（${this.esc(platformName(s.platform))}）</div>`
      );
    if (e.relation === "same")
      return (
        `<div class='g-tip-name'>${sn} ↔ ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 与 <b>${tn}</b> 跨平台昵称完全相同，疑似同一人的多个账号</div>`
      );
    if (e.relation === "alike")
      return (
        `<div class='g-tip-name'>${sn} ↔ ${tn}</div>` +
        `<div class='g-tip-rel'><b>${sn}</b> 与 <b>${tn}</b> 昵称相似，可能是同一人的多个账号</div>`
      );
    if (e.relation === "manual")
      return (
        `<div class='g-tip-name'>${sn} ↔ ${tn}</div>` +
        `<div class='g-tip-rel'>已手动标记为同一人的不同账号（点击连线可解除）</div>`
      );
    return `<div class='g-tip-rel'>关键词「${this.esc(data.keyword)}」搜索命中 <b>${tn}</b></div>`;
  };
  // 节点 badge：还有未展开的人时，在昵称旁附加一个"剩余 N"胶囊（rich 文本）
  // 有真实总数时显示精确剩余；否则提示还有更多，具体数量需点击查看
  const remainBadgeOf = (n: GraphNode) => {
    const p = this.expandProg.get(`${n.platform}:${n.uid}`);
    if (!p || n.platform === "keyword") return "";
    const parts = [];
    if (p.followsMore) {
      const remain =
        p.followsTotal != null
          ? Math.max(0, p.followsTotal - p.followsLoaded)
          : null;
      parts.push(remain != null ? `关注 余 ${remain}` : "关注 有更多");
    }
    if (p.followersMore) {
      const remain =
        p.followersTotal != null
          ? Math.max(0, p.followersTotal - p.followersLoaded)
          : null;
      parts.push(remain != null ? `粉丝 余 ${remain}` : "粉丝 有更多");
    }
    return parts.join(" · ");
  };
  const nodes = data.nodes
    .filter((n) => visibleIds.has(n.id))
    .map((n) => {
      const key = `${n.platform}:${n.uid}`;
      const expanded =
        this.expandedKeys.has(key + ":follows") ||
        this.expandedKeys.has(key + ":followers");
      const hidden = this.hiddenNodeIds.has(n.id); // 手动隐藏的节点不会进入此分支；大V弱相关走 irrelevant
      const irrelevant = this.isIrrelevant(n);
      let itemStyle;
      if (irrelevant) {
        // 粉丝 ≥1000 的大V/公众账号：灰色小圆点淡化展示，降低视觉权重
        itemStyle = {
          color: "#e3e6ea",
          borderColor: "#aeb5bf",
          borderWidth: 1,
        };
      }
      if (expanded)
        itemStyle = {
          ...(itemStyle || {}),
          borderColor: this.ACCENT,
          borderWidth: 2,
        };
      const base = {
        ...n,
        category: catIndex(n.platform),
        symbolSize:
          n.platform === "keyword"
            ? 42
            : irrelevant
              ? 7
              : this.nodeSize(n.fans),
        raw: n,
        itemStyle,
        label: irrelevant ? { show: false } : undefined,
        // 预计算"剩余未展开"徽标文本（有真实剩余数则显示数字，否则只标 +）
        _remain: n.platform === "keyword" ? "" : remainBadgeOf(n),
      };
      if (layerPos && layerPos[n.id]) {
        base.x = layerPos[n.id].x;
        base.y = layerPos[n.id].y;
      } else if (posMap && this.frozenPos.has(n.id)) {
        base.x = this.frozenPos.get(n.id)!.x;
        base.y = this.frozenPos.get(n.id)!.y;
      }
      return base;
    });
  const links = displayEdges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => {
      if (e.relation === "mutual")
        return {
          ...e,
          lineStyle: {
            color: this.MUTUAL_COLOR,
            width: 2.2,
            opacity: 0.95,
            curveness: 0.1,
          },
        };
      if (e.relation === "follows")
        return {
          ...e,
          lineStyle: {
            color: this.ACCENT,
            width: 1.3,
            opacity: 0.5,
            curveness: 0.1,
          },
        };
      if (e.relation === "same")
        return {
          ...e,
          lineStyle: {
            color: this.SAME_COLOR,
            width: 2,
            opacity: 0.9,
            curveness: 0.12,
          },
        };
      if (e.relation === "alike")
        return {
          ...e,
          lineStyle: {
            color: this.SAME_COLOR,
            width: 1.2,
            type: "dashed",
            opacity: 0.7,
            curveness: 0.18,
          },
        };
      if (e.relation === "manual")
        return {
          ...e,
          lineStyle: {
            color: this.MANUAL_COLOR,
            width: 2.4,
            opacity: 0.95,
            curveness: 0.14,
          },
        };
      return {
        ...e,
        lineStyle: { color: "source", width: 1, opacity: 0.3, curveness: 0.08 },
      };
    });
  return {
    color: [this.ACCENT, ...PLATFORMS.map((p) => p.color)],
    tooltip: {
      confine: true,
      trigger: "item",
      textStyle: { fontSize: 12 },
      formatter: (p: {
        dataType?: string;
        data?: GraphEdge & { raw?: GraphNode; _remain?: string };
      }) => {
        if (p.dataType === "edge") {
          return `<div class='g-tip'><div class='g-tip-main'>${p.data ? edgeTip(p.data) : ""}</div></div>`;
        }
        const n = p.data?.raw;
        if (!n) return "";
        const fans =
          Number(n.fans) > 0
            ? `<div class='g-tip-fans'>${fmtNum(Number(n.fans))} 粉丝</div>`
            : "";
        const warn = this.isIrrelevant(n)
          ? `<div class='g-tip-warn'>${this.esc(this.irrelevantReason(n))}，与监控对象直接关联可能性低（已灰化缩小）</div>`
          : "";
        const sig = n.signature
          ? `<div class='g-tip-sig'>${this.esc(n.signature)}</div>`
          : "";
        return (
          `<div class='g-tip'>` +
          `<img class='g-tip-avatar' src='${this.esc(n.avatarUrl)}' referrerpolicy='no-referrer' onerror=\"this.style.display='none'\" />` +
          `<div class='g-tip-main'><div class='g-tip-name'>${this.esc(n.nickname)}</div>` +
          `<div class='g-tip-plat'>${this.esc(platformName(n.platform))}</div>${fans}${warn}${sig}</div></div>`
        );
      },
    },
    series: [
      {
        type: "graph",
        layout: layer ? "none" : "force",
        roam: true,
        // 滚轮缩放/平移在整个画布生效；ECharts 6 默认 'selfRect' 只在节点包围盒内响应，
        // 缩小后包围盒收缩，画布边缘滚轮会失灵
        roamTrigger: "global",
        // 停放下节点同样可拖拽手动摆放（松手即停）
        draggable: !layer,
        categories,
        data: nodes,
        links,
        force: {
          repulsion: this.forceParams.repulsion,
          gravity: this.forceParams.gravity,
          edgeLength: this.forceParams.edgeLength,
          layoutAnimation: !layer,
          // 停放核心：friction 0 让模拟一步停摆；undefined 走 ECharts 默认 0.6
          ...(this.frozen ? { friction: 0 } : {}),
        },
        label: {
          show: true,
          position: "bottom",
          fontSize: 11,
          color: "#5c6470",
          formatter: (p: {
            dataType?: string;
            data?: GraphEdge & { raw?: GraphNode; _remain?: string };
          }) => {
            const raw = p.data?.raw;
            if (!raw) return "";
            const nick = (raw.nickname || "").slice(0, 12);
            const remain = p.data?._remain || "";
            if (!remain) return nick;
            // 有"剩余未展开"：昵称下方加橙色小徽标
            return `{nick|${nick}}\n{remain|${remain}}`;
          },
          rich: {
            nick: { fontSize: 11, color: "#5c6470", lineHeight: 14 },
            remain: {
              fontSize: 10,
              color: "#b97d10",
              backgroundColor: "#fdf3e0",
              borderRadius: 6,
              padding: [1, 5],
              lineHeight: 14,
            },
          },
        },
        labelLayout: { hideOverlap: true },
        emphasis: {
          focus: "adjacency",
          label: { fontWeight: 600, color: "#1c1f23" },
          lineStyle: { width: 2.5, opacity: 1 },
        },
        lineStyle: { width: 1, curveness: 0.1 },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 5,
        scaleLimit: { min: 0.3, max: 6 },
      },
    ],
  };
}
export function render(this: GraphController) {
  if (!this.chart) return;
  if (this.frozen) this.capturePositions(); // 先把拖拽后的最新坐标收进缓存，clear 后经数据 x/y 恢复
  const option = this.buildOption();
  if (!option) return;
  this.chart.clear();
  this.chart.setOption(option);
}
export function capturePositions(this: GraphController) {
  if (!this.chart || !this.result) return;
  const seriesModel =
    (this.chart as unknown as LayoutChart).getModel() &&
    (this.chart as unknown as LayoutChart).getModel().getSeriesByIndex(0);
  if (!seriesModel || seriesModel.type !== "series.graph") return;
  const graph = seriesModel.getGraph();
  const fromGraph = () => {
    if (!graph) return;
    graph.eachNode((node) => {
      const l = node.getLayout();
      if (l && Number.isFinite(l[0]) && Number.isFinite(l[1]))
        this.frozenPos.set(node.id, { x: l[0], y: l[1] });
    });
  };
  if (this.frozen) {
    fromGraph();
    return;
  }
  const preserved = seriesModel.preservedPoints;
  if (preserved) {
    for (const [id, p] of Object.entries(preserved)) {
      if (p && Number.isFinite(p[0]) && Number.isFinite(p[1]))
        this.frozenPos.set(id, { x: p[0], y: p[1] });
    }
  }
  if (this.frozenPos.size) return;
  fromGraph();
}
export function syncFrozenPositions(this: GraphController) {
  if (!this.frozen || !this.chart || !this.result) return;
  const seriesModel =
    (this.chart as unknown as LayoutChart).getModel() &&
    (this.chart as unknown as LayoutChart).getModel().getSeriesByIndex(0);
  if (!seriesModel || seriesModel.type !== "series.graph") return;
  this.capturePositions();
  const preserved = seriesModel.preservedPoints;
  if (!preserved) return;
  for (const [id, p] of this.frozenPos) preserved[id] = [p.x, p.y];
  const adj = new Map<string, string[]>();
  for (const e of this.result.edges) {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source)!.push(e.target);
    adj.get(e.target)!.push(e.source);
  }
  let cx = 0,
    cy = 0,
    cnt = 0;
  for (const p of this.frozenPos.values()) {
    cx += p.x;
    cy += p.y;
    cnt++;
  }
  if (cnt) {
    cx /= cnt;
    cy /= cnt;
  }
  for (const n of this.result.nodes) {
    if (preserved[n.id]) continue;
    const anchor = (adj.get(n.id) || [])
      .map((id) => this.frozenPos.get(id))
      .find((p) => p !== undefined);
    const a = Math.random() * Math.PI * 2;
    const r = anchor ? 46 : 150;
    const p: [number, number] = [
      (anchor ? anchor.x : cx) + r * Math.cos(a),
      (anchor ? anchor.y : cy) + r * Math.sin(a),
    ];
    preserved[n.id] = p;
    this.frozenPos.set(n.id, { x: p[0], y: p[1] });
  }
}
export function resetFreeze(this: GraphController) {
  this.frozen = false;
  this.frozenPos.clear();
}
export function setForceFriction(this: GraphController, v: number) {
  this.chart?.setOption({ series: [{ force: { friction: v } }] });
}
export function toggleFreeze(this: GraphController) {
  if (!this.chart || !this.nodeCount) return;
  if (this.frozen) {
    this.frozen = false;
    this.frozenPos.clear();
    this.setForceFriction(0.6); // 内部 preservedPoints 保留了坐标，从当前位置继续温和收敛
    return;
  }
  this.capturePositions();
  this.frozen = true;
  this.setForceFriction(0);
}
export function setLayoutMode(this: GraphController, m: "force" | "layer") {
  if (this.layoutMode === m) {
    if (m === "force" && this.frozen) this.toggleFreeze();
    return;
  }
  this.resetFreeze();
  this.layoutMode = m;
  this.selected = null;
  this.render();
}
export function relayout(this: GraphController) {
  this.resetFreeze();
  this.render(); // clear + 重新随机布局，力导向重新收敛
}
export function exportPng(this: GraphController) {
  if (!this.chart || !this.nodeCount) return;
  const url = this.chart.getDataURL({
    type: "png",
    pixelRatio: 2,
    backgroundColor: "#ffffff",
  });
  const a = document.createElement("a");
  a.href = url;
  a.download = `sight-关系图-${this.lastSearched || "graph"}.png`;
  a.click();
}

interface LayoutChart {
  getModel(): {
    getSeriesByIndex(index: number): {
      type: string;
      preservedPoints?: Record<string, [number, number]>;
      getGraph(): {
        eachNode(
          callback: (node: {
            id: string;
            getLayout(): [number, number];
          }) => void,
        ): void;
      };
    };
  };
}
