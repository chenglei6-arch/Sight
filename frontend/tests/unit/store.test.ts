import { beforeEach, describe, it, expect, vi } from "vitest";
const ok = (data: unknown) => new Response(JSON.stringify({ code: 200, data }));
const platform = (nickname: string) => ({
  profile: { uid: nickname, nickname, level: 0 },
  playlists: [],
  records: null,
  events: [],
  follows: [],
  followers: [],
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  history.replaceState(null, "", "/");
});
describe("application state", () => {
  it("does not reopen a saved graph after the user navigates elsewhere", async () => {
    const pending = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => pending.promise),
    );
    const store = await import("../../src/store");
    const opening = store.openSavedGraph(1);
    store.setView("bilibili");
    pending.resolve(ok({ id: 1, name: "old", data: { nodes: [] } }));
    await opening;
    expect(store.useAppStore.getState().view).toBe("bilibili");
    expect(store.useAppStore.getState().pendingGraph).toBeNull();
  });
  it("loads legacy UIDs and tolerates malformed local storage", async () => {
    localStorage.setItem("sight_uids", "broken");
    localStorage.setItem("monitor_uids", JSON.stringify({ netease: 123 }));
    const { useAppStore } = await import("../../src/store");
    expect(useAppStore.getState().uids.netease).toBe("123");
  });
  it("discards a response from the previous target even when fetch ignores abort", async () => {
    const old = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("uid=old")
          ? old.promise
          : Promise.resolve(
              ok(url.includes("/timeline") ? [] : platform("new")),
            ),
      ),
    );
    const store = await import("../../src/store");
    store.useAppStore.setState((s) => ({
      uids: { ...s.uids, netease: "old" },
    }));
    const first = store.loadPlatform("netease");
    store.setUid("netease", "new");
    await vi.waitFor(() =>
      expect(store.useAppStore.getState().data.netease.profile?.nickname).toBe(
        "new",
      ),
    );
    old.resolve(ok(platform("old")));
    await first;
    expect(store.useAppStore.getState().data.netease.profile?.nickname).toBe(
      "new",
    );
    expect(JSON.parse(localStorage.getItem("sight_uids")!).netease).toBe("new");
  });
  it("keeps partial failures visible", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          ok({ ...platform("target"), _errors: ["[微博] 凭证失效"] }),
        ),
    );
    const store = await import("../../src/store");
    store.useAppStore.setState((s) => ({
      uids: { ...s.uids, weibo: "target" },
    }));
    await store.loadPlatform("weibo");
    expect(store.useAppStore.getState().data.weibo.errors).toEqual([
      "[微博] 凭证失效",
    ]);
    expect(store.useAppStore.getState().data.weibo.loaded).toBe(true);
  });
  it("does not mix live and stored timeline responses", async () => {
    const live = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("source=live")
          ? live.promise
          : Promise.resolve(
              ok([{ id: 2, summary: "stored", platform: "netease" }]),
            ),
      ),
    );
    const store = await import("../../src/store");
    store.useAppStore.setState((s) => ({ uids: { ...s.uids, netease: "1" } }));
    const first = store.loadTimeline();
    store.setTimelineSource("stored");
    await vi.waitFor(() =>
      expect(store.useAppStore.getState().timeline.entries[0]?.summary).toBe(
        "stored",
      ),
    );
    live.resolve(ok([{ summary: "old", platform: "netease" }]));
    await first;
    expect(store.useAppStore.getState().timeline.entries[0].summary).toBe(
      "stored",
    );
  });
  it("survives StrictMode setup/cleanup and disposes every timer", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn((url: string) =>
      Promise.resolve(
        ok(
          url.includes("/platforms") || url.includes("/saved")
            ? []
            : { queues: [] },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const store = await import("../../src/store");
    const first = store.initStore();
    first();
    const stop = store.initStore();
    for (let i = 0; i < 20; i++) await Promise.resolve();
    expect(
      fetch.mock.calls.filter(([url]) => url === "/api/platforms"),
    ).toHaveLength(1);
    store.setAutoRefresh(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(2);
    store.setView("graph");
    await vi.advanceTimersByTimeAsync(300000);
    expect(fetch.mock.calls.some(([url]) => url.includes("/graph/all"))).toBe(
      false,
    );
    stop();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("loads the view on hash changes and ignores malformed hashes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(ok(url.includes("/all") ? platform("bili") : [])),
      ),
    );
    const store = await import("../../src/store");
    const stop = store.initStore();
    store.useAppStore.setState((s) => ({ uids: { ...s.uids, bilibili: "2" } }));
    location.hash = "#/bilibili";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await vi.waitFor(() =>
      expect(store.useAppStore.getState().data.bilibili.loaded).toBe(true),
    );
    location.hash = "#/%E0%A4";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(store.useAppStore.getState().view).toBe("bilibili");
    stop();
  });
});
