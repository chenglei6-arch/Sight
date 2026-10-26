import type { GraphController, GraphSnapshot } from "./controller";
export function createGraphScope(
  controller: GraphController,
  snapshot: GraphSnapshot,
  activeGraphId: number | null,
) {
  return {
    ...snapshot,
    state: { activeGraphId },
    SOCIAL_SUPPORT: controller.SOCIAL_SUPPORT,
    doSearch: (...args: Parameters<GraphController["doSearch"]>) =>
      controller.run(() => controller.doSearch(...args)),
    commitKeyword: (...args: Parameters<GraphController["commitKeyword"]>) =>
      controller.run(() => controller.commitKeyword(...args)),
    cancelEditKeyword: (
      ...args: Parameters<GraphController["cancelEditKeyword"]>
    ) => controller.run(() => controller.cancelEditKeyword(...args)),
    togglePlatform: (...args: Parameters<GraphController["togglePlatform"]>) =>
      controller.run(() => controller.togglePlatform(...args)),
    startEditKeyword: (
      ...args: Parameters<GraphController["startEditKeyword"]>
    ) => controller.run(() => controller.startEditKeyword(...args)),
    setExpandLimit: (...args: Parameters<GraphController["setExpandLimit"]>) =>
      controller.run(() => controller.setExpandLimit(...args)),
    toggleFreeze: (...args: Parameters<GraphController["toggleFreeze"]>) =>
      controller.run(() => controller.toggleFreeze(...args)),
    relayout: (...args: Parameters<GraphController["relayout"]>) =>
      controller.run(() => controller.relayout(...args)),
    exportPng: (...args: Parameters<GraphController["exportPng"]>) =>
      controller.run(() => controller.exportPng(...args)),
    persistGraph: (...args: Parameters<GraphController["persistGraph"]>) =>
      controller.run(() => controller.persistGraph(...args)),
    setLayoutMode: (...args: Parameters<GraphController["setLayoutMode"]>) =>
      controller.run(() => controller.setLayoutMode(...args)),
    bulkExpand: (...args: Parameters<GraphController["bulkExpand"]>) =>
      controller.run(() => controller.bulkExpand(...args)),
    stopBulk: (...args: Parameters<GraphController["stopBulk"]>) =>
      controller.run(() => controller.stopBulk(...args)),
    remarkNodes: (...args: Parameters<GraphController["remarkNodes"]>) =>
      controller.run(() => controller.remarkNodes(...args)),
    openCookieConfig: (
      ...args: Parameters<GraphController["openCookieConfig"]>
    ) => controller.run(() => controller.openCookieConfig(...args)),
    dismissStatus: (...args: Parameters<GraphController["dismissStatus"]>) =>
      controller.run(() => controller.dismissStatus(...args)),
    adoptTarget: (...args: Parameters<GraphController["adoptTarget"]>) =>
      controller.run(() => controller.adoptTarget(...args)),
    startLinkFrom: (...args: Parameters<GraphController["startLinkFrom"]>) =>
      controller.run(() => controller.startLinkFrom(...args)),
    hideSelectedNode: (
      ...args: Parameters<GraphController["hideSelectedNode"]>
    ) => controller.run(() => controller.hideSelectedNode(...args)),
    expandSocial: (...args: Parameters<GraphController["expandSocial"]>) =>
      controller.run(() => controller.expandSocial(...args)),
    onCookieSaved: (...args: Parameters<GraphController["onCookieSaved"]>) =>
      controller.run(() => controller.onCookieSaved(...args)),
    setKeyword: (value: GraphController["keyword"]) =>
      controller.setField("keyword", value),
    setGraphName: (value: GraphController["graphName"]) =>
      controller.setField("graphName", value),
    setEditVal: (value: GraphController["editVal"]) =>
      controller.setField("editVal", value),
    setViewFilter: (value: GraphController["viewFilter"]) =>
      controller.setField("viewFilter", value),
    setSelected: (value: GraphController["selected"]) =>
      controller.setField("selected", value),
    setLinkSource: (value: GraphController["linkSource"]) =>
      controller.setField("linkSource", value),
    setRepulsion: (value: number) =>
      controller.updateForce({ repulsion: value }),
    setGravity: (value: number) => controller.updateForce({ gravity: value }),
    setEdgeLength: (value: number) =>
      controller.updateForce({ edgeLength: value }),
    setCookieOpen: (value: boolean) => controller.setCookieOpen(value),
    restoreHidden: () => controller.run(() => controller.restoreHidden()),
    homeUrl: (...args: Parameters<GraphController["homeUrl"]>) =>
      controller.homeUrl(...args),
    canExpandMore: (...args: Parameters<GraphController["canExpandMore"]>) =>
      controller.canExpandMore(...args),
  };
}
export type GraphScope = ReturnType<typeof createGraphScope>;
