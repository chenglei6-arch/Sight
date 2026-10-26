import type { Page } from "@playwright/test";
import type {
  Account,
  GraphData,
  GraphNode,
  TimelineEntry,
} from "../../src/types";
export const ids = [
  "netease",
  "bilibili",
  "douyin",
  "qqmusic",
  "weibo",
  "genshin",
  "xhs",
] as const;
export const graphNode = (
  platform: GraphNode["platform"],
  uid: string,
  nickname: string,
): GraphNode => ({
  id: platform === "keyword" ? "keyword" : `${platform}:${uid}`,
  platform,
  uid,
  nickname,
  fans: 12,
  signature: "公开资料示例",
});
export function sampleGraph(): GraphData {
  const nodes = [
    graphNode("keyword", "示例", "示例"),
    graphNode("netease", "1", "示例"),
    graphNode("bilibili", "2", "示例"),
    graphNode("netease", "3", "朋友"),
  ];
  return {
    keyword: "示例",
    platforms: ["netease", "bilibili"],
    searched: ids.slice(),
    nodes,
    edges: nodes
      .slice(1)
      .map((n) => ({ source: "keyword", target: n.id, relation: "hit" })),
    keywords: { netease: "专属昵称" },
    custom_metadata: { keep: true },
  };
}
export async function installMockApi(page: Page) {
  const requests: Array<{ path: string; method: string; body: unknown }> = [];
  let graph = sampleGraph(),
    name = "旧图谱",
    accountList: Account[] = [
      {
        id: "primary",
        name: "主账号",
        enabled: true,
        primary: true,
        has_credential: true,
        cookie_keys: ["session"],
      },
    ];
  let timeline: TimelineEntry[] = [
    {
      id: 1,
      platform: "netease",
      summary: "新增收藏歌单",
      detail: "测试详情",
      timestamp: 1792375200,
      event_type: "歌单",
      created_at: "2026-10-19T10:00:00",
    },
  ];
  let qrPolls = 0,
    queued = false,
    cursor = 0;
  await page.addInitScript(() => {
    // Exercise the documented SSE fallback without opening external connections.
    class UnavailableEventSource {
      static CLOSED = 2;
      readyState = 2;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onopen: (() => void) | null = null;
      constructor(_url: string) {
        queueMicrotask(() => this.onerror?.(new Event("error")));
      }
      close() {}
    }
    window.EventSource =
      UnavailableEventSource as unknown as typeof EventSource;
  });
  await page.route("**/api/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname.replace("/api", ""),
      method = req.method(),
      body = req.postDataJSON();
    requests.push({ path, method, body });
    let data: unknown = {};
    const meta = ids.map((id) => ({
      id,
      name: id,
      has_credential: true,
      is_alive: true,
      login_user: {
        uid:
          id === "genshin"
            ? "123456789"
            : id === "xhs"
              ? "5d8c00000000000010000000"
              : "100",
        nickname: `测试用户-${id}`,
      },
    }));
    if (path === "/platforms") data = meta;
    else if (path.endsWith("/all")) {
      const id = path.split("/")[1],
        uid = url.searchParams.get("uid");
      data = {
        profile: {
          platform: id,
          uid,
          nickname: `测试用户-${id}`,
          level: 9,
          signature: "这是用于界面回归的公开资料示例",
          extra: {
            followeds: 88,
            follows: 12,
            fan_count: 88,
            follow_count: 12,
            world_level: 8,
          },
        },
        playlists: [
          {
            item_id: "p1",
            title: id === "genshin" ? "胡桃 Lv.90" : "测试内容",
            count: 3,
            is_owner: true,
            creator: "测试用户",
            extra: {
              level: 90,
              element: "火",
              constellation: 1,
              weapon_name: "护摩之杖",
              weapon_level: 90,
            },
          },
        ],
        records: {
          allTime: [
            {
              entry_id: "s1",
              title: "测试歌曲",
              artist_or_uploader: "歌手",
              play_count: 42,
            },
          ],
          weekly: [],
        },
        events: [
          {
            event_id: "e1",
            event_type: "发布",
            content: "一条公开动态",
            timestamp: 1792375200,
          },
        ],
        follows: [{ uid: "200", nickname: "示例关注" }],
        followers: [{ uid: "300", nickname: "示例粉丝" }],
        _errors: [],
      };
    } else if (path.endsWith("/search") && path !== "/graph/search")
      data = [
        { uid: "201", nickname: "搜索结果甲" },
        { uid: "202", nickname: "搜索结果乙" },
      ];
    else if (path.includes("/playlist/"))
      data = {
        title: "测试歌单详情",
        count: 1,
        items: [
          { id: "s1", title: "详情歌曲", artist: "测试歌手", duration: 180000 },
        ],
      };
    else if (path === "/timeline") data = timeline;
    else if (path === "/timeline/1") {
      if (method === "PUT") timeline = [{ ...timeline[0], ...body }];
      if (method === "DELETE") timeline = [];
      data = {};
    } else if (path.startsWith("/credentials/"))
      data = { has_credential: true, cookie_keys: ["session"] };
    else if (/^\/accounts\/[^/]+$/.test(path)) {
      if (method === "POST")
        accountList.push({
          id: "extra1",
          name: body.name || "账号2",
          primary: false,
          enabled: true,
          has_credential: true,
          cookie_keys: ["session"],
        });
      data = {
        accounts: accountList,
        pool_size: accountList.filter((a) => a.enabled).length,
      };
    } else if (path.endsWith("/test"))
      data = { ok: true, latency_ms: 15, login_user: { nickname: "测试账号" } };
    else if (path.startsWith("/accounts/")) {
      const id = path.split("/")[3];
      if (method === "DELETE")
        accountList = accountList.filter((a) => a.id !== id);
      else
        accountList = accountList.map((a) =>
          a.id === id ? { ...a, ...body } : a,
        );
      data = {};
    } else if (path === "/qqmusic/qr-login/start") {
      qrPolls = 0;
      data = {};
    } else if (path === "/qqmusic/qr-login/status")
      data =
        ++qrPolls === 1
          ? {
              status: "qr_ready",
              qr_code:
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==",
            }
          : {
              status: "done",
              follow_data: {
                count: 1,
                follows: [{ uid: "2", nickname: "扫码关注示例" }],
              },
            };
    else if (path === "/graph/search")
      data = {
        ...sampleGraph(),
        keyword: url.searchParams.get("keyword") || "示例",
      };
    else if (path === "/graph/save") {
      graph = body.data;
      name = body.name;
      data = { id: 1, name };
    } else if (path === "/graph/saved")
      data = [
        {
          id: 1,
          name,
          keyword: graph.keyword,
          node_count: graph.nodes.length - 1,
          edge_count: graph.edges.length,
          updated_at: "2026-10-19T10:00:00",
        },
      ];
    else if (path === "/graph/saved/1") data = { id: 1, name, data: graph };
    else if (path === "/graph/expand/enqueue") {
      queued = true;
      data = {
        queued: body.items.length,
        duplicates: 0,
        rejected: 0,
        task_ids: body.items.map((_: unknown, i: number) => 100 + i),
      };
    } else if (path === "/graph/expand/results") {
      const task =
        queued && Number(url.searchParams.get("since_id")) < 100
          ? {
              id: 100,
              platform: "netease",
              uid: "1",
              nickname: "示例",
              status: "done",
              dirs: { follows: true, followers: true },
              result: {
                nodes: [graphNode("netease", "4", "新邻居")],
                edges: [
                  {
                    source: "netease:1",
                    target: "netease:4",
                    relation: "follows",
                  },
                ],
                counts: {
                  follows: 1,
                  followers: 0,
                  follows_more: false,
                  followers_more: false,
                },
              },
            }
          : null;
      if (task) {
        queued = false;
        cursor = 100;
      }
      data = { results: task ? [task] : [], pending: 0, cursor, paused: [] };
    } else if (path === "/graph/expand/status")
      data = {
        queues: [
          {
            platform: "netease",
            pending: 0,
            running: 0,
            paused: false,
            accounts: 1,
            interval: 1,
            running_tasks: [],
            pending_tasks: [],
          },
        ],
      };
    else if (path === "/graph/refresh_nodes")
      data = {
        nodes: graph.nodes.filter((n) => n.platform !== "keyword"),
        errors: {},
      };
    else if (path === "/logs/recent")
      data = {
        entries: [
          {
            seq: 1,
            boot: "fixture",
            ts: "10:00:00",
            text: "[netease] 资料加载完成",
            source: "netease",
            level: "info",
          },
        ],
        last_seq: 1,
      };
    else if (path.endsWith("/cache/clear")) data = { adapters_dropped: 1 };
    await route.fulfill({ json: { code: 200, data } });
  });
  return { requests, getGraph: () => graph };
}
