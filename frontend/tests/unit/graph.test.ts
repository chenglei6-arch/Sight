import { beforeEach, describe, it, expect, vi } from "vitest";
import { GraphController } from "../../src/components/graph/controller";
import { SerializedGraphSaver } from "../../src/components/graph/persistence";
import { useAppStore } from "../../src/store";
import type { GraphData, GraphNode, SavedGraph } from "../../src/types";
const node = (
  platform: GraphNode["platform"],
  uid: string,
  nickname = uid,
): GraphNode => ({
  id: platform === "keyword" ? "keyword" : `${platform}:${uid}`,
  platform,
  uid,
  nickname,
});
const graph = (): GraphData => ({
  keyword: "test",
  platforms: ["netease"],
  nodes: [node("keyword", "test"), node("netease", "1"), node("netease", "2")],
  edges: [
    { source: "keyword", target: "netease:1", relation: "hit" },
    { source: "netease:1", target: "netease:2", relation: "follows" },
  ],
});
const ok = (data: unknown) => new Response(JSON.stringify({ code: 200, data }));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
beforeEach(() => {
  localStorage.clear();
  useAppStore.setState({ activeGraphId: 1, pendingGraph: null });
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(ok(url.includes("/saved") ? [] : { id: 1 })),
    ),
  );
});
describe("graph data and persistence", () => {
  it("publishes immutable view snapshots without leaking mutable model references", () => {
    const c = new GraphController();
    c.result = graph();
    c.publish();
    const previous = c.store.getState();
    c.result.nodes.push(node("weibo", "4"));
    c.hiddenNodeIds.add("netease:2");
    c.publish();
    expect(previous.result?.nodes).toHaveLength(3);
    expect(previous.hiddenNodeIds.size).toBe(0);
    expect(c.store.getState().result?.nodes).toHaveLength(4);
    c.dispose();
  });
  it("keeps pending saves for different graph names instead of discarding the older graph", async () => {
    const saver = new SerializedGraphSaver(),
      first = deferred<number | null>(),
      calls: string[] = [];
    const a = saver.enqueue(() => {
      calls.push("a");
      return first.promise;
    }, "a");
    const b = saver.enqueue(async () => {
      calls.push("b");
      return 2;
    }, "b");
    const a2 = saver.enqueue(async () => {
      calls.push("a2");
      return 3;
    }, "a");
    first.resolve(1);
    expect(await Promise.all([a, b, a2])).toEqual([3, 2, 3]);
    expect(calls).toEqual(["a", "b", "a2"]);
  });
  it("merges nodes and edges without duplicates and derives mutual/cross-platform aliases", () => {
    const c = new GraphController();
    c.result = graph();
    c.result.nodes[1].nickname = " A ";
    c.mergeGraph({
      nodes: [node("netease", "2"), node("bilibili", "3", "a")],
      edges: [
        { source: "netease:1", target: "netease:2", relation: "follows" },
        { source: "netease:2", target: "netease:1", relation: "follows" },
      ],
    });
    expect(c.result.nodes).toHaveLength(4);
    expect(c.result.edges).toHaveLength(3);
    expect(
      c.deriveDisplayEdges().filter((e) => e.relation === "mutual"),
    ).toHaveLength(1);
    expect(c.deriveDisplayEdges().some((e) => e.relation === "same")).toBe(
      true,
    );
    c.dispose();
  });
  it("only cascades hidden nodes that lose every path to the root", () => {
    const c = new GraphController();
    c.result = graph();
    expect(c.cascadeHiddenAfter("netease:1")).toEqual([
      "netease:1",
      "netease:2",
    ]);
    c.result.edges.push({
      source: "keyword",
      target: "netease:2",
      relation: "hit",
    });
    expect(c.cascadeHiddenAfter("netease:1")).toEqual(["netease:1"]);
    c.dispose();
  });
  it("retains manual identity edges without duplicates and supports removing them", async () => {
    const c = new GraphController();
    c.result = graph();
    const [a, b] = c.result.nodes.slice(1);
    c.addManualEdge(a, b);
    c.addManualEdge(b, a);
    expect(c.result.edges.filter((e) => e.relation === "manual")).toHaveLength(
      1,
    );
    c.removeManualEdge(a.id, b.id);
    expect(c.result.edges.some((e) => e.relation === "manual")).toBe(false);
    await c.persistGraph();
    c.dispose();
  });
  it("restores old graph fields and round-trips expansion/hidden state and unknown metadata", async () => {
    const c = new GraphController();
    const data = {
      ...graph(),
      keywords: { netease: "专属" },
      hidden_ids: ["netease:2"],
      expanded_keys: ["netease:1:follows"],
      interchecked_ids: ["netease:1"],
      expand_prog: {
        "netease:1": {
          followsLoaded: 20,
          followsMore: true,
          followsTotal: 50,
          followersLoaded: 0,
          followersMore: false,
          followersTotal: null,
        },
      },
      custom_metadata: { keep: true },
    };
    useAppStore.setState({
      pendingGraph: {
        id: 1,
        name: "旧图",
        keyword: data.keyword,
        node_count: 2,
        edge_count: 2,
        updated_at: "2026-10-19",
        data,
      } satisfies SavedGraph,
    });
    c.consumePendingGraph();
    c.stopQueuePolling();
    expect(c.graphName).toBe("旧图");
    expect(c.platformKeywords.netease).toBe("专属");
    expect(c.expandProg.get("netease:1")?.followsMore).toBe(true);
    await c.persistGraph();
    const fetch = vi.mocked(globalThis.fetch);
    const call = fetch.mock.calls.find(([url]) => url === "/api/graph/save")!;
    const body = JSON.parse(call[1]!.body as string);
    expect(body.data.custom_metadata).toEqual({ keep: true });
    expect(body.data.hidden_ids).toEqual(["netease:2"]);
    expect(body.data.expanded_keys).toEqual(["netease:1:follows"]);
    c.dispose();
  });
  it("coalesces pending saves and runs the latest snapshot after the in-flight request", async () => {
    const saver = new SerializedGraphSaver(),
      first = deferred<number | null>(),
      calls: string[] = [];
    const a = saver.enqueue(() => {
      calls.push("a");
      return first.promise;
    });
    const b = saver.enqueue(async () => {
      calls.push("b");
      return 2;
    });
    const c = saver.enqueue(async () => {
      calls.push("c");
      return 3;
    });
    expect(calls).toEqual(["a"]);
    first.resolve(1);
    expect(await Promise.all([a, b, c])).toEqual([3, 3, 3]);
    expect(calls).toEqual(["a", "c"]);
  });
  it("consumes all result pages before declaring the queue drained and ignores repeated tasks", async () => {
    const c = new GraphController();
    c.result = graph();
    const tasks = Array.from({ length: 50 }, (_, i) => ({
      id: i + 1,
      platform: "netease",
      uid: "1",
      status: "cancelled",
    }));
    let pages = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          ok(
            url.includes("/results")
              ? ++pages === 1
                ? { results: tasks, cursor: 50, pending: 0, paused: [] }
                : { results: [], cursor: 50, pending: 0, paused: [] }
              : url.includes("/saved")
                ? []
                : { id: 1 },
          ),
        ),
      ),
    );
    vi.spyOn(c, "sleep").mockResolvedValue();
    c.queuePoll.active = true;
    await c.pollQueueLoop();
    expect(pages).toBe(2);
    expect(c.queuePoll.active).toBe(false);
    expect(c.seenTaskIds.size).toBe(50);
    expect(c.applyTaskResult(tasks[0])).toBe(false);
    c.dispose();
  });
  it("does not merge a delayed response or save ID into another graph", async () => {
    const queue = deferred<Response>(),
      save = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("/results")
          ? queue.promise
          : url === "/api/graph/save"
            ? save.promise
            : Promise.resolve(ok([])),
      ),
    );
    const c = new GraphController();
    c.result = graph();
    c.queuePoll.active = true;
    const polling = c.pollQueueLoop();
    const saving = c.persistGraph();
    c.beginGraph();
    c.result = { ...graph(), keyword: "other" };
    useAppStore.setState({ activeGraphId: 2 });
    queue.resolve(
      ok({
        results: [
          {
            id: 99,
            platform: "netease",
            uid: "1",
            status: "done",
            result: { nodes: [node("weibo", "999")] },
          },
        ],
        cursor: 99,
        pending: 0,
        paused: [],
      }),
    );
    save.resolve(ok({ id: 1 }));
    await Promise.all([polling, saving]);
    expect(c.result.nodes.some((n) => n.uid === "999")).toBe(false);
    expect(useAppStore.getState().activeGraphId).toBe(2);
    c.dispose();
  });
  it("builds escaped tooltips and preserves frozen/layout behavior", () => {
    const c = new GraphController();
    c.result = graph();
    c.result.nodes[1].nickname = "<script>x</script>";
    expect(c.esc(c.result.nodes[1].nickname)).toBe(
      "&lt;script&gt;x&lt;/script&gt;",
    );
    expect(c.computeLayerPositions(c.result)["netease:1"]).toBeDefined();
    expect(c.buildOption()).toBeTruthy();
    c.dispose();
  });
});
