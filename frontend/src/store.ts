import { create } from "zustand";
import { api, errorMessage } from "./api";
import { PLATFORMS, PLATFORM_MAP } from "./platforms";
import type {
  CacheStats,
  PlatformData,
  PlatformId,
  PlatformMeta,
  PlatformPayload,
  QueueStatus,
  SavedGraph,
  SavedGraphMeta,
  TimelineEntry,
  TimelineState,
  User,
  ViewId,
} from "./types";

function readStorage(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Private mode / quota. */
  }
}
function storedUids(): Record<PlatformId, string> {
  let raw: Record<string, unknown> = {};
  for (const key of ["sight_uids", "monitor_uids"]) {
    try {
      const candidate: unknown = JSON.parse(readStorage(key) || "null");
      if (
        candidate &&
        typeof candidate === "object" &&
        !Array.isArray(candidate)
      )
        raw = candidate as Record<string, unknown>;
    } catch {
      /* Try the legacy key. */
    }
    if (Object.keys(raw).length) break;
  }
  return Object.fromEntries(
    PLATFORMS.map((p) => [p.id, String(raw[p.id] || "")]),
  ) as Record<PlatformId, string>;
}
export function blankPlatformData(): PlatformData {
  return {
    loading: false,
    loaded: false,
    fetchedAt: null,
    error: "",
    profile: null,
    playlists: [],
    records: null,
    events: [],
    follows: [],
    followers: [],
    errors: [],
  };
}
interface AppState {
  view: ViewId;
  uids: Record<PlatformId, string>;
  data: Record<PlatformId, PlatformData>;
  platformsMeta: PlatformMeta[];
  platformsMetaError: string;
  timeline: TimelineState;
  detailModal: { platform: PlatformId; id: string } | null;
  editEntry: { id: number; summary: string; detail: string } | null;
  autoRefresh: boolean;
  qrOpen: boolean;
  accountModal: { open: boolean; platform: string };
  savedGraphs: SavedGraphMeta[];
  activeGraphId: number | null;
  pendingGraph: SavedGraph | null;
  savedGraphsError: string;
  terminalOpen: boolean;
  terminalTab: "logs" | "queue";
  queues: QueueStatus[];
}
export const useAppStore = create<AppState>(() => ({
  view: "netease",
  uids: storedUids(),
  data: Object.fromEntries(
    PLATFORMS.map((p) => [p.id, blankPlatformData()]),
  ) as Record<PlatformId, PlatformData>,
  platformsMeta: [],
  platformsMetaError: "",
  timeline: {
    loading: false,
    loaded: false,
    error: "",
    source: "live",
    entries: [],
    fetchedAt: null,
  },
  detailModal: null,
  editEntry: null,
  autoRefresh: false,
  qrOpen: false,
  accountModal: { open: false, platform: "" },
  savedGraphs: [],
  activeGraphId: null,
  pendingGraph: null,
  savedGraphsError: "",
  terminalOpen: readStorage("sight_terminal_open") === "1",
  terminalTab: "logs",
  queues: [],
}));
const get = useAppStore.getState;
const patch = useAppStore.setState;
const platformRequests = new Map<PlatformId, AbortController>();
let timelineRequest: AbortController | null = null;
let metaRequest: AbortController | null = null;
let queueRequest: AbortController | null = null;
let graphOpenVersion = 0;

export function isPlatformId(value: string): value is PlatformId {
  return !!PLATFORM_MAP[value];
}
function validView(value: string): value is ViewId {
  return value === "timeline" || value === "graph" || isPlatformId(value);
}
function updatePlatform(id: PlatformId, fields: Partial<PlatformData>) {
  patch((s) => ({ data: { ...s.data, [id]: { ...s.data[id], ...fields } } }));
}
function updateTimeline(fields: Partial<TimelineState>) {
  patch((s) => ({ timeline: { ...s.timeline, ...fields } }));
}
export function currentPlatform() {
  return PLATFORM_MAP[get().view] || null;
}
function applyHash() {
  let value = "";
  try {
    value = decodeURIComponent(location.hash).replace(/^#\/?/, "");
  } catch {
    return;
  }
  if (validView(value)) {
    patch({ view: value });
    loadCurrentView();
  }
}
export function setView(view: ViewId) {
  if (!validView(view) || view === get().view) return;
  invalidateGraphOpen();
  patch({ view });
  history.replaceState(null, "", `#/${view}`);
  loadCurrentView();
}
export async function loadPlatform(
  id: PlatformId,
  { force = false, refresh = false } = {},
) {
  const uid = get().uids[id];
  if (
    !uid ||
    (get().data[id].loading && !force) ||
    (get().data[id].loaded && !force)
  )
    return;
  const request = new AbortController();
  platformRequests.get(id)?.abort();
  platformRequests.set(id, request);
  updatePlatform(id, { loading: true, error: "" });
  try {
    const payload = await api.get<PlatformPayload>(
      `/${id}/all`,
      { uid, refresh: refresh ? 1 : undefined },
      request.signal,
    );
    if (
      request.signal.aborted ||
      get().uids[id] !== uid ||
      platformRequests.get(id) !== request
    )
      return;
    const { _errors, ...data } = payload;
    updatePlatform(id, {
      ...blankPlatformData(),
      ...data,
      loaded: true,
      fetchedAt: new Date(),
      errors: _errors || [],
    });
  } catch (error) {
    if (!request.signal.aborted && platformRequests.get(id) === request)
      updatePlatform(id, {
        ...blankPlatformData(),
        error: errorMessage(error),
      });
  } finally {
    if (platformRequests.get(id) === request) {
      platformRequests.delete(id);
      updatePlatform(id, { loading: false });
    }
  }
}
export function loadCurrentView() {
  const view = get().view;
  if (view === "timeline") void loadTimeline();
  else if (isPlatformId(view)) void loadPlatform(view);
}
export async function refreshCurrentView() {
  const view = get().view;
  if (view === "timeline") await loadTimeline({ force: true });
  else if (isPlatformId(view)) {
    await loadPlatform(view, { force: true });
    await loadTimeline({ force: true });
  }
}
export async function clearPlatformCache(id: PlatformId) {
  const stats = await api.post<CacheStats>(`/${id}/cache/clear`);
  await loadPlatform(id, { force: true, refresh: true });
  await loadTimeline({ force: true });
  return stats;
}
export function setUid(id: PlatformId, uid: string) {
  platformRequests.get(id)?.abort();
  platformRequests.delete(id);
  timelineRequest?.abort();
  timelineRequest = null;
  patch((s) => ({
    uids: { ...s.uids, [id]: uid },
    data: { ...s.data, [id]: blankPlatformData() },
    timeline: { ...s.timeline, loaded: false, loading: false },
  }));
  writeStorage("sight_uids", JSON.stringify(get().uids));
  if (uid)
    void loadPlatform(id, { force: true }).then(() =>
      loadTimeline({ force: true }),
    );
  else void loadTimeline({ force: true });
}
export function searchUsers(
  id: PlatformId,
  keyword: string,
  signal?: AbortSignal,
) {
  return api.get<User[]>(`/${id}/search`, { keyword }, signal);
}
export async function loadPlatformsMeta() {
  const request = new AbortController();
  metaRequest?.abort();
  metaRequest = request;
  try {
    const platformsMeta = await api.get<PlatformMeta[]>(
      "/platforms",
      undefined,
      request.signal,
    );
    if (!request.signal.aborted)
      patch({ platformsMeta: platformsMeta || [], platformsMetaError: "" });
  } catch (e) {
    if (!request.signal.aborted)
      patch({
        platformsMeta: [],
        platformsMetaError: `平台状态加载失败：${errorMessage(e)}`,
      });
  } finally {
    if (metaRequest === request) metaRequest = null;
  }
}
export function timelineUidPairs() {
  return PLATFORMS.filter((p) => get().uids[p.id]).map(
    (p) => `${p.id}:${get().uids[p.id]}`,
  );
}
export async function loadTimeline({ force = false } = {}) {
  const pairs = timelineUidPairs();
  const source = get().timeline.source;
  if (!pairs.length) {
    timelineRequest?.abort();
    updateTimeline({
      error: "NO_UIDS",
      loaded: true,
      loading: false,
      entries: [],
    });
    return;
  }
  if (
    (get().timeline.loading && !force) ||
    (get().timeline.loaded && !force && get().timeline.error !== "NO_UIDS")
  )
    return;
  const request = new AbortController();
  timelineRequest?.abort();
  timelineRequest = request;
  updateTimeline({ loading: true, error: "" });
  try {
    const entries = await api.get<TimelineEntry[]>(
      "/timeline",
      { uids: pairs.join(","), limit: 60, source },
      request.signal,
    );
    if (
      !request.signal.aborted &&
      source === get().timeline.source &&
      pairs.join(",") === timelineUidPairs().join(",")
    )
      updateTimeline({
        entries: Array.isArray(entries) ? entries : [],
        loaded: true,
        fetchedAt: new Date(),
      });
  } catch (e) {
    if (!request.signal.aborted)
      updateTimeline({ error: errorMessage(e), loaded: true });
  } finally {
    if (timelineRequest === request) {
      timelineRequest = null;
      updateTimeline({ loading: false });
    }
  }
}
export function setTimelineSource(source: "live" | "stored") {
  if (source === get().timeline.source) return;
  timelineRequest?.abort();
  timelineRequest = null;
  updateTimeline({ source, loaded: false, loading: false });
  void loadTimeline({ force: true });
}
export async function saveTimelineEntry(
  id: number,
  summary: string,
  detail: string,
) {
  await api.put(`/timeline/${id}`, { summary, detail });
  await loadTimeline({ force: true });
}
export async function deleteTimelineEntry(id: number) {
  await api.del(`/timeline/${id}`);
  await loadTimeline({ force: true });
}
export function setEditEntry(editEntry: AppState["editEntry"]) {
  patch({ editEntry });
}
export function openDetail(platform: PlatformId, id: string) {
  patch({ detailModal: { platform, id: String(id) } });
}
export function closeDetail() {
  patch({ detailModal: null });
}
export async function loadSavedGraphs() {
  try {
    patch({
      savedGraphs: (await api.get<SavedGraphMeta[]>("/graph/saved")) || [],
      savedGraphsError: "",
    });
  } catch (e) {
    patch({ savedGraphsError: `图谱列表加载失败：${errorMessage(e)}` });
  }
}
export async function openSavedGraph(id: number) {
  const version = ++graphOpenVersion;
  try {
    const graph = await api.get<SavedGraph>(`/graph/saved/${id}`);
    if (version !== graphOpenVersion) return;
    patch({
      activeGraphId: graph.id,
      pendingGraph: graph,
      savedGraphsError: "",
    });
    setView("graph");
  } catch (e) {
    if (version === graphOpenVersion)
      patch({ savedGraphsError: `打开图谱失败：${errorMessage(e)}` });
  }
}
export function invalidateGraphOpen() {
  graphOpenVersion++;
}
export async function removeSavedGraph(id: number) {
  try {
    await api.del(`/graph/saved/${id}`);
    patch((s) => ({
      activeGraphId: s.activeGraphId === id ? null : s.activeGraphId,
      savedGraphsError: "",
    }));
  } catch (e) {
    patch({ savedGraphsError: `删除失败：${errorMessage(e)}` });
  }
  await loadSavedGraphs();
}
export function setActiveGraphId(activeGraphId: number | null) {
  patch({ activeGraphId });
}
export function consumePendingGraph() {
  const graph = get().pendingGraph;
  patch({ pendingGraph: null });
  return graph;
}
export function openQrLogin() {
  patch({ qrOpen: true });
}
export function closeQrLogin() {
  patch({ qrOpen: false });
}
export function openAccountModal(platform = "") {
  patch({ accountModal: { open: true, platform } });
}
export function closeAccountModal() {
  patch((s) => ({ accountModal: { ...s.accountModal, open: false } }));
}
export function toggleTerminal(open?: boolean) {
  const value = typeof open === "boolean" ? open : !get().terminalOpen;
  patch({ terminalOpen: value });
  writeStorage("sight_terminal_open", value ? "1" : "0");
}
export function setTerminalTab(terminalTab: "logs" | "queue") {
  patch({ terminalTab });
}
export function setAutoRefresh(autoRefresh: boolean) {
  patch({ autoRefresh });
}
export async function refreshQueues() {
  if (queueRequest) return;
  const request = new AbortController();
  queueRequest = request;
  try {
    const response = await api.get<{ queues: QueueStatus[] }>(
      "/graph/expand/status",
      undefined,
      request.signal,
    );
    if (!request.signal.aborted) patch({ queues: response.queues || [] });
  } catch {
    /* Backend not ready; retry on the next tick. */
  } finally {
    if (queueRequest === request) queueRequest = null;
  }
}
export function queueSummary(queues = get().queues) {
  const summary = queues.reduce(
    (s, q) => ({
      pending: s.pending + (q.pending || 0),
      running: s.running + (q.running || 0),
      paused: s.paused + Number(q.paused),
    }),
    { pending: 0, running: 0, paused: 0 },
  );
  return { ...summary, busy: summary.pending + summary.running };
}

/** One application owner; every StrictMode setup has a matching, complete disposal. */
export function initStore() {
  let disposed = false;
  let autoTimer: ReturnType<typeof setInterval> | undefined;
  const configureAutoRefresh = () => {
    clearInterval(autoTimer);
    autoTimer = undefined;
    if (get().autoRefresh)
      autoTimer = setInterval(() => {
        void refreshCurrentView();
      }, 300000);
  };
  const unsubscribe = useAppStore.subscribe((next, prev) => {
    if (next.autoRefresh !== prev.autoRefresh) configureAutoRefresh();
  });
  window.addEventListener("hashchange", applyHash);
  configureAutoRefresh();
  // Deferral avoids duplicate startup work during StrictMode's setup/cleanup probe.
  queueMicrotask(async () => {
    if (disposed) return;
    applyHash();
    loadCurrentView();
    await loadPlatformsMeta();
    if (disposed) return;
    for (const meta of get().platformsMeta) {
      const uid = meta.login_user?.uid;
      if (uid && !get().uids[meta.id])
        patch((s) => ({ uids: { ...s.uids, [meta.id]: String(uid) } }));
    }
    writeStorage("sight_uids", JSON.stringify(get().uids));
    loadCurrentView();
    void loadSavedGraphs();
    void refreshQueues();
    for (const platform of PLATFORMS) {
      if (disposed) return;
      if (get().uids[platform.id] && !get().data[platform.id].loaded)
        await loadPlatform(platform.id);
    }
    if (!disposed) await loadTimeline({ force: true });
  });
  const queueTimer = setInterval(() => {
    void refreshQueues();
  }, 3000);
  return () => {
    disposed = true;
    clearInterval(autoTimer);
    clearInterval(queueTimer);
    unsubscribe();
    window.removeEventListener("hashchange", applyHash);
    platformRequests.forEach((request) => request.abort());
    platformRequests.clear();
    metaRequest?.abort();
    metaRequest = null;
    timelineRequest?.abort();
    timelineRequest = null;
    queueRequest?.abort();
    queueRequest = null;
    graphOpenVersion++;
    patch((s) => ({
      data: Object.fromEntries(
        PLATFORMS.map((p) => [p.id, { ...s.data[p.id], loading: false }]),
      ) as Record<PlatformId, PlatformData>,
      timeline: { ...s.timeline, loading: false },
    }));
  };
}
