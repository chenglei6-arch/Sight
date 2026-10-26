import { api, errorMessage } from "../../api";
import { PLATFORM_MAP } from "../../platforms";
import { useAppStore } from "../../store";
import type {
  EnqueueStats,
  ExpandItem,
  ExpandTask,
  QueueResults,
} from "../../types";
import type { GraphController } from "./controller";

export async function expandSocial(
  this: GraphController,
  type: "follows" | "followers" | "both",
) {
  const version = this.version;
  const n = this.selected;
  if (!n || !this.result) return;
  const nid = `${n.platform}:${n.uid}`;
  if (this.expandBusyIds.has(nid)) return; // 该节点已有任务在排队/执行，其余节点不受影响
  const directions = type === "both" ? ["follows", "followers"] : [type];
  // "继续展开"：只拉还没展开/还有更多的方向（已确认拉完的方向跳过，避免重复请求）
  const p0 = this.progOf(n);
  const wantFollows =
    directions.includes("follows") &&
    (p0.followsLoaded === 0 || p0.followsMore);
  const wantFollowers =
    directions.includes("followers") &&
    (p0.followersLoaded === 0 || p0.followersMore);
  if (!wantFollows && !wantFollowers) {
    this.expandMsgs[nid] = "该用户的关注/粉丝已全部展开完毕";
    return;
  }
  const stats = await this.enqueueExpandTasks([
    {
      platform: n.platform,
      uid: n.uid,
      nickname: n.nickname,
      follows_limit: wantFollows ? this.expandLimit : 0,
      followers_limit: wantFollowers ? this.expandLimit : 0,
      follows_skip: wantFollows ? p0.followsLoaded : 0,
      followers_skip: wantFollowers ? p0.followersLoaded : 0,
      known_ids: this.result!.nodes.filter(
        (x) => x.platform === n.platform,
      ).map((x) => x.id),
      intercheck_skip: this.intercheckSkipList(n.platform),
      intercheck_extra: [...this.adjacentSamePlatformUids(n)],
    },
  ]);
  if (!this.isCurrent(version)) return;
  if (!stats.queued) {
    const pausedQ = (stats.paused || []).find((p) => p.platform === n.platform);
    this.expandMsgs[nid] = pausedQ
      ? `该平台队列已暂停（连续失败）：${pausedQ.reason}。配置 Cookie 后自动恢复，也可展开其他平台的用户`
      : stats.duplicates
        ? "该用户的展开任务已在队列中，等待执行结果"
        : `任务入队失败${stats.error ? "：" + stats.error : "（超出预算或平台不可用）"}`;
    return;
  }
  this.expandBusyIds.add(nid);
  this.expandMsgs[nid] = "已加入展开队列，等待执行…";
  this.startQueuePolling(); // 单独展开也必须启动轮询：否则结果（含报错）永远取不回来，节点一直"展开中"
}

export function intercheckSkipList(this: GraphController, platform: string) {
  const prefix = platform + ":";
  return [...this.intercheckedIds]
    .filter((k) => k.startsWith(prefix))
    .map((k) => k.slice(prefix.length));
}

export async function bulkExpand(this: GraphController) {
  const version = this.version;
  const targets = this.visibleUserNodes().filter(
    (n) =>
      this.SOCIAL_SUPPORT[n.platform] &&
      !this.isIrrelevant(n) && // 大V/公众账号灰化节点不参与一键展开（仍可点开单独展开）
      !this.expandBusyIds.has(`${n.platform}:${n.uid}`) && // 该节点已有单独任务在队列，跳过避免重复拉取
      !this.expandedKeys.has(`${n.platform}:${n.uid}:follows`),
  );
  if (!targets.length) {
    this.bulkMsg = this.bulk.busy
      ? "当前视图没有新增可展开的节点（其余平台队列仍在执行，互不影响）"
      : "没有可展开的节点（当前视图下所有可查用户都已展开，或平台不支持）";
    return;
  }
  const wasBusy = this.bulk.busy;
  if (!wasBusy) {
    this.bulk.stop = false;
    this.bulk.done = 0;
    this.bulk.total = 0;
    this.bulk.addNodes = 0;
    this.bulk.addEdges = 0;
    this.bulk.icHits = 0;
    this.bulk.failed = 0;
    this.bulk.failReasons = new Map();
    this.bulk.ids = new Set();
  }
  this.bulkMsg = `正在把 ${targets.length} 个节点加入展开队列…`;
  const stats = await this.enqueueExpandTasks(
    targets.map((n) => ({
      platform: n.platform,
      uid: n.uid,
      nickname: n.nickname,
      follows_limit: 20,
      followers_limit: 20,
      known_ids: this.result!.nodes.filter(
        (x) => x.platform === n.platform,
      ).map((x) => x.id),
      intercheck_skip: this.intercheckSkipList(n.platform),
      intercheck_extra: [...this.adjacentSamePlatformUids(n)],
      intercheck_limit: 8,
      intercheck_follow_limit: 30,
    })),
  );
  if (!this.isCurrent(version)) return;
  if (!stats.queued && !stats.duplicates && !wasBusy) {
    const pausedText = (stats.paused || [])
      .map(
        (p) => `${PLATFORM_MAP[p.platform]?.name || p.platform}：${p.reason}`,
      )
      .join("；");
    this.bulkMsg = `没有任务成功入队${stats.rejected ? `（${stats.rejected} 个被拒绝）` : ""}${pausedText ? ` · ${pausedText}` : ""}`;
    return;
  }
  this.bulk.busy = true;
  // 被拒的任务计入 total 并立即记为已处理（失败）：否则分母失真，
  // 队列已满大量拒单时进度永远到不了 100%
  this.bulk.total += stats.queued + stats.duplicates + stats.rejected;
  this.bulk.done += stats.duplicates + stats.rejected;
  for (const id of stats.task_ids || []) this.bulk.ids.add(id); // 圈定本批任务：轮询只对它们计进度
  this.bulk.failed += stats.rejected;
  if (stats.rejected)
    this.bulk.failReasons.set(
      "入队被拒（预算超限/队列满/队列暂停/平台不可用）",
      stats.rejected,
    );
  this.bulkMsg = stats.queued
    ? `已入队 ${stats.queued} 个展开任务（每个关注+粉丝各 20 人），各平台队列并行执行…`
    : "所选节点均已在队列中，等待执行结果";
  this.startQueuePolling();
}

export function stopBulk(this: GraphController) {
  this.bulk.stop = true;
  const gid = useAppStore.getState().activeGraphId;
  if (gid != null)
    api.post("/graph/expand/stop", { graph_id: gid }).catch(() => {});
  this.bulkMsg = "正在停止队列中的剩余任务…";
}

export async function ensureGraphId(this: GraphController) {
  if (useAppStore.getState().activeGraphId != null)
    return useAppStore.getState().activeGraphId;
  const id = await this.persistGraph({ quiet: true });
  if (id != null) useAppStore.setState({ activeGraphId: id });
  return useAppStore.getState().activeGraphId;
}

export async function enqueueExpandTasks(
  this: GraphController,
  items: ExpandItem[],
): Promise<EnqueueStats> {
  const version = this.version;
  const gid = await this.ensureGraphId();
  try {
    if (gid == null || !this.isCurrent(version))
      return {
        queued: 0,
        duplicates: 0,
        rejected: items.length,
        error: "图谱未保存或已切换",
      };
    return await api.post<EnqueueStats>(
      "/graph/expand/enqueue",
      { graph_id: gid, items },
      undefined,
      this.work.signal,
    );
  } catch (e) {
    return {
      queued: 0,
      duplicates: 0,
      rejected: items.length,
      error: errorMessage(e),
    };
  }
}

export function startQueuePolling(this: GraphController) {
  this.queuePoll.gen++;
  if (this.queuePoll.active) return;
  this.queuePoll.active = true;
  void this.pollQueueLoop();
}

export function stopQueuePolling(this: GraphController) {
  this.queuePoll.active = false;
  this.pollEpoch++;
  this.pollRequest?.abort();
  this.pollRequest = null;
  clearTimeout(this.waitTimer);
  this.wakeWait?.();
  this.wakeWait = null;
}

export function sleep(this: GraphController, ms: number): Promise<void> {
  return new Promise((resolve) => {
    this.wakeWait = resolve;
    this.waitTimer = setTimeout(() => {
      this.wakeWait = null;
      resolve();
    }, ms);
  });
}

export async function pollQueueLoop(this: GraphController) {
  const epoch = ++this.pollEpoch,
    version = this.version,
    gid = useAppStore.getState().activeGraphId;
  let failures = 0;
  try {
    while (
      this.queuePoll.active &&
      this.isCurrent(version) &&
      epoch === this.pollEpoch
    ) {
      if (gid == null || gid !== useAppStore.getState().activeGraphId) break;
      const observed = this.queuePoll.gen,
        request = new AbortController();
      this.pollRequest = request;
      let data: QueueResults;
      try {
        data = await api.get<QueueResults>(
          "/graph/expand/results",
          {
            graph_id: gid,
            since_id: this.queuePoll.cursors.get(gid) || 0,
            limit: 50,
          },
          request.signal,
        );
        failures = 0;
      } catch (e) {
        if (
          request.signal.aborted ||
          !this.isCurrent(version) ||
          epoch !== this.pollEpoch
        )
          break;
        if (++failures >= 5) {
          this.bulkMsg = `轮询展开结果连续失败 ${failures} 次：${errorMessage(e)}`;
          this.publish();
        }
        await this.sleep(2000);
        continue;
      }
      if (
        request.signal.aborted ||
        !this.isCurrent(version) ||
        epoch !== this.pollEpoch ||
        gid !== useAppStore.getState().activeGraphId
      )
        break;
      let changed = false;
      for (const task of data.results || []) {
        try {
          if (this.applyTaskResult(task)) changed = true;
        } catch (e) {
          this.bulkMsg = "应用展开结果失败：" + errorMessage(e);
        }
      }
      this.pausedQueues = data.paused || [];
      this.queuePoll.cursors.set(
        gid,
        data.cursor || this.queuePoll.cursors.get(gid) || 0,
      );
      this.saveExpandCursors();
      if (changed) {
        this.syncFrozenPositions();
        this.refreshChart();
      }
      if (data.results?.length) void this.persistGraph({ quiet: true });
      this.publish();
      if (
        !(data.pending > 0) &&
        (data.results || []).length < 50 &&
        observed === this.queuePoll.gen
      ) {
        if (this.bulk.busy) this.finalizeBulk();
        break;
      }
      await this.sleep(data.pending > 0 ? 1500 : 300);
    }
  } finally {
    if (epoch === this.pollEpoch) {
      this.queuePoll.active = false;
      this.pollRequest = null;
      this.publish();
    }
  }
}

export function applyTaskResult(this: GraphController, r: ExpandTask) {
  if (this.seenTaskIds.has(r.id)) return false;
  this.seenTaskIds.add(r.id);
  const nid = `${r.platform}:${r.uid}`;
  const payload = r.status === "done" ? r.result : null;
  let added = { nodes: 0, edges: 0 };
  if (payload) {
    added = this.mergeGraph(payload);
    for (const t of payload.intercheck?.targets || [])
      this.intercheckedIds.add(r.platform + ":" + t);
    // 记录各方向已拉取进度与"还有更多/总数"；任务请求了哪个方向就标记哪个方向已展开
    const c = payload.counts || {};
    const p = this.progOf({ platform: r.platform, uid: r.uid });
    if (r.dirs?.follows) {
      p.followsLoaded = (c.follows_offset || 0) + (c.follows || 0);
      p.followsMore = !!c.follows_more;
      if (typeof c.follows_total === "number") p.followsTotal = c.follows_total;
      this.expandedKeys.add(`${nid}:follows`);
    }
    if (r.dirs?.followers) {
      p.followersLoaded = (c.followers_offset || 0) + (c.followers || 0);
      p.followersMore = !!c.followers_more;
      if (typeof c.followers_total === "number")
        p.followersTotal = c.followers_total;
      this.expandedKeys.add(`${nid}:followers`);
    }
  }
  // 单独展开的任务：把结果消息挂到节点信息卡（与旧同步版文案一致）
  if (this.expandBusyIds.has(nid)) {
    this.expandBusyIds.delete(nid);
    if (r.status === "failed") {
      this.expandMsgs[nid] = `接口报错：${r.error || "未知原因"}`;
    } else if (r.status === "cancelled") {
      this.expandMsgs[nid] = "任务已停止";
    } else if (payload) {
      const ic = payload.intercheck || {};
      const errs = Object.entries(payload.errors || {});
      this.expandMsgs[nid] =
        added.nodes + added.edges === 0 && !ic.checked && errs.length
          ? `接口报错：${errs.map(([, v]) => v).join("；")}`
          : `新增 ${added.nodes} 人 · ${added.edges} 条关注边 · 邻居互查命中 ${ic.edges?.length || 0} 条` +
            (ic.total ? `（查了 ${ic.checked}/${ic.total} 个邻居）` : "") +
            (errs.length
              ? ` · 部分失败：${errs.map(([, v]) => v).join("；")}`
              : "");
    }
  }
  // 一键展开计数：只统计本次批量入队的任务（bulk.ids）。
  // 历史积压结果（刷新后重读）与单独展开的任务不在集合里，合并进图但不占进度。
  if (this.bulk.busy && this.bulk.ids.has(r.id)) {
    this.bulk.done++;
    if (r.status !== "done") {
      this.bulk.failed++;
      const reason =
        r.status === "cancelled" ? "已停止" : r.error || "未知原因";
      this.bulk.failReasons.set(
        reason,
        (this.bulk.failReasons.get(reason) || 0) + 1,
      );
    } else if (payload) {
      this.bulk.addNodes += added.nodes;
      this.bulk.addEdges += added.edges;
      this.bulk.icHits += payload.intercheck?.edges?.length || 0;
      this.bulkMsg = `队列执行中 ${this.bulk.done}/${this.bulk.total}：${r.nickname || nid}`;
    }
  }
  return added.nodes + added.edges > 0;
}

export function finalizeBulk(this: GraphController) {
  this.bulk.busy = false;
  const scope =
    this.viewFilter === "all"
      ? ""
      : `（仅 ${PLATFORM_MAP[this.viewFilter]?.name} 视图）`;
  const failText = [...this.bulk.failReasons.entries()]
    .map(([msg, cnt]) => `${msg}${cnt > 1 ? ` ×${cnt}` : ""}`)
    .join("；");
  this.bulkMsg =
    `${this.bulk.stop ? "已停止" : "全图展开完成"}${scope}：新增 ${this.bulk.addNodes} 人 · ${this.bulk.addEdges} 条关注边 · 互查命中 ${this.bulk.icHits} 条` +
    (failText ? ` · ${this.bulk.failed} 个任务未成功：${failText}` : "") +
    (this.bulk.failed && !failText ? ` · 失败 ${this.bulk.failed} 个任务` : "");
  // 全图展开（含中途停止）的结果整体同步到已保存图谱
  if (this.bulk.addNodes + this.bulk.addEdges + this.bulk.icHits > 0)
    this.persistGraph({ quiet: true });
}

export function saveExpandCursors(this: GraphController) {
  try {
    localStorage.setItem(
      this.EXPAND_CURSOR_KEY,
      JSON.stringify([...this.queuePoll.cursors]),
    );
  } catch {
    /* 存储不可写时退化为内存游标 */
  }
}
