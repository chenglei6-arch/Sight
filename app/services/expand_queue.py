"""
社交关系展开队列 —— 按平台隔离的后台批量展开。

设计要点:
- 每个平台一个独立队列（PlatformQueue），队列内串行消费、队列间并行。
  限速节奏、Cookie 故障域都按平台隔离：抖音队列熔断不影响其他平台。
- 单平台内并发度随账号池规模扩展（min(账号数, 3) 个 worker 线程），
  请求本身再经 AdapterPool.lease() 轮询分配账号，N 个账号 = N 条流水线。
- 任务带入队时的图节点快照（known_ids），worker 无状态；结果即时落库，
  前端通过 /graph/expand/results 增量轮询合并，关页面/重启都不丢。
- 熔断: 连续失败达阈值自动暂停该平台队列并记录原因，恢复接口重置计数。
"""
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from app.data.store import DataStore
from app.platforms import get_pool, known_platform_ids
from app.services.social_expander import expand_social

# 各平台两次任务之间的最小间隔（秒）；适配器内部还有限速，这里是队列级兜底
PLATFORM_MIN_INTERVALS = {"douyin": 2.0, "weibo": 1.0}
DEFAULT_INTERVAL = 0.3
# 单平台最多几个 worker 同时消费（请求粒度的账号分配由 lease() 负责）
MAX_WORKERS_PER_PLATFORM = 3
# 连续失败多少个任务后熔断暂停该平台队列
BREAKER_THRESHOLD = 5
# 预算上限：单图同时排队/执行的任务数、单平台队列最大长度
MAX_PENDING_PER_GRAPH = 500
MAX_QUEUE_PER_PLATFORM = 400
# 状态接口里执行中/排队任务明细最多返回多少条（防超长队列撑爆载荷）
MAX_TASKS_IN_STATUS = 20


@dataclass
class ExpandTask:
    id: int
    platform: str
    uid: str
    nickname: str = ""
    graph_id: int | None = None
    params: dict = field(default_factory=dict)  # expand_social 的完整入参（含 known_ids）


class PlatformQueue:
    """单平台的展开任务队列 + worker 线程组"""

    def __init__(self, platform: str, store: DataStore):
        self.platform = platform
        self._store = store
        self._queue: deque[ExpandTask] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._workers: list[threading.Thread] = []
        self._running = 0  # 正在执行的任务数
        self._paused = False
        self._pause_reason = ""
        self._consecutive_fail = 0
        self._in_flight: dict[int, ExpandTask] = {}  # task_id -> task（执行中，stop 不取消）
        # task_id -> {方向: 账号标签集合}，方向为 follows/followers/intercheck
        # （队列面板"哪个账号在展开哪个用户的哪个方向"）
        self._task_accounts: dict[int, dict[str, set[str]]] = {}

    @property
    def interval(self) -> float:
        return PLATFORM_MIN_INTERVALS.get(self.platform, DEFAULT_INTERVAL)

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> str:
        return self._pause_reason

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def running_count(self) -> int:
        return self._running

    # ==================== 任务明细（队列面板展示用） ====================

    def running_tasks_snapshot(self) -> list[dict]:
        """执行中任务明细：用户 + 各方向（关注/粉丝/互查）动用的账号标签"""
        with self._lock:
            tasks = list(self._in_flight.values())[:MAX_TASKS_IN_STATUS]
            accs = {
                tid: {name: sorted(labels) for name, labels in m.items()}
                for tid, m in self._task_accounts.items()
            }
        out = []
        for t in tasks:
            m = accs.get(t.id, {})
            flat = sorted({label for labels in m.values() for label in labels})
            out.append({
                "id": t.id,
                "uid": t.uid,
                "nickname": t.nickname,
                "accounts": flat,          # 兼容：任务动用账号的并集
                "account_map": m,          # 方向级明细：follows/followers/intercheck -> 账号列表
            })
        return out

    def pending_tasks_snapshot(self) -> list[dict]:
        """排队任务明细（按入队顺序，最多前 MAX_TASKS_IN_STATUS 条）"""
        with self._lock:
            tasks = list(self._queue)[:MAX_TASKS_IN_STATUS]
        return [{"id": t.id, "uid": t.uid, "nickname": t.nickname} for t in tasks]

    # ==================== 入队 / 取消 ====================

    def push(self, task: ExpandTask) -> bool:
        """任务入队；队列超长返回 False"""
        with self._lock:
            if len(self._queue) >= MAX_QUEUE_PER_PLATFORM:
                return False
            self._queue.append(task)
        self._wake.set()
        self._ensure_workers()
        return True

    def cancel_pending(self, predicate, reason: str = "用户停止") -> int:
        """按条件移除排队中的任务并标记 cancelled；执行中的不动"""
        removed = []
        with self._lock:
            kept = deque()
            for t in self._queue:
                if predicate(t):
                    removed.append(t)
                else:
                    kept.append(t)
            self._queue = kept
        for t in removed:
            try:
                self._store.update_expand_task(t.id, "cancelled", error=reason)
            except Exception as e:
                print(f"[ExpandQueue] 任务 {t.id} 取消状态落库失败: {e}")
        return len(removed)

    def resume(self):
        """解除熔断暂停，重置失败计数"""
        self._consecutive_fail = 0
        self._paused = False
        self._pause_reason = ""
        self._wake.set()

    # ==================== worker ====================

    def _ensure_workers(self):
        pool = get_pool(self.platform)
        n = min(max(pool.size if pool else 1, 1), MAX_WORKERS_PER_PLATFORM)
        with self._lock:
            if len(self._workers) >= n:
                return
            while len(self._workers) < n:
                t = threading.Thread(target=self._worker_loop, daemon=True,
                                     name=f"expand-{self.platform}-{len(self._workers)}")
                t.start()
                self._workers.append(t)

    def _pop(self) -> ExpandTask | None:
        with self._lock:
            if self._queue and not self._paused:
                return self._queue.popleft()
        return None

    def _worker_loop(self):
        while True:
            task = self._pop()
            if task is None:
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            self._running += 1
            self._in_flight[task.id] = task
            acc_map = self._task_accounts.setdefault(task.id, {})

            def account_sink(name: str, label: str, _m=acc_map):
                _m.setdefault(name, set()).add(label)

            try:
                self._store.update_expand_task(task.id, "running")
            except Exception as e:
                print(f"[ExpandQueue] 任务 {task.id} running 状态落库失败: {e}")
            try:
                payload = expand_social(task.params, account_sink=account_sink)
                self._finish(task, payload)
            except Exception as e:
                self._finish(task, None, error=str(e))
            finally:
                self._running -= 1
                self._in_flight.pop(task.id, None)
                self._task_accounts.pop(task.id, None)
                time.sleep(self.interval)

    def _finish(self, task: ExpandTask, payload: dict | None, error: str = None):
        """任务收尾：结果落库 + 熔断计数。既无数据又带错误视为一次失败。"""
        failed = error is not None
        if payload is not None and not failed:
            empty = (
                not payload.get("nodes")
                and not payload.get("edges")
                and not (payload.get("intercheck") or {}).get("checked")
            )
            failed = empty and bool(payload.get("errors"))
        if failed:
            self._consecutive_fail += 1
            if self._consecutive_fail >= BREAKER_THRESHOLD and not self._paused:
                self._paused = True
                self._pause_reason = error or "；".join(
                    (payload or {}).get("errors", {}).values()
                ) or "连续多次展开失败"
                print(f"[ExpandQueue] {self.platform} 队列已熔断暂停: {self._pause_reason}")
                # 快速失败：取消该平台剩余排队任务，避免积压拖死整体进度
                # （典型如对方列表隐私/接口限制，重试也是失败；Cookie 修复后可重新入队）
                dropped = self.cancel_pending(
                    lambda t: True, reason=f"队列熔断暂停：{self._pause_reason}"
                )
                if dropped:
                    print(f"[ExpandQueue] {self.platform} 已取消 {dropped} 个排队任务")
        else:
            self._consecutive_fail = 0
        try:
            if failed:
                self._store.update_expand_task(
                    task.id, "failed",
                    error=error or "；".join((payload or {}).get("errors", {}).values()),
                )
            else:
                self._store.update_expand_task(task.id, "done", result=payload)
        except Exception as e:
            print(f"[ExpandQueue] 任务 {task.id} 结果落库失败: {e}")


class ExpandQueueManager:
    """按平台隔离的展开队列管理器（全局单例）"""

    def __init__(self):
        self._store = DataStore()
        self._queues: dict[str, PlatformQueue] = {}
        self._lock = threading.Lock()
        self._recovered = False
        self.recover()

    def _queue_for(self, platform: str) -> PlatformQueue:
        with self._lock:
            q = self._queues.get(platform)
            if q is None:
                q = PlatformQueue(platform, self._store)
                self._queues[platform] = q
            return q

    # ==================== 服务重启恢复 ====================

    def recover(self):
        """把数据库里遗留的 pending/running 任务重新入队（断点续跑），并清理过期完结任务"""
        if self._recovered:
            return
        self._recovered = True
        try:
            self._store.purge_old_expand_tasks()
        except Exception as e:
            print(f"[ExpandQueue] 清理过期任务失败: {e}")
        try:
            rows = self._store.get_recoverable_expand_tasks()
        except Exception as e:
            print(f"[ExpandQueue] 恢复遗留任务失败: {e}")
            return
        for row in rows:
            try:
                params = json.loads(row["params_json"] or "{}")
            except (ValueError, TypeError):
                continue
            if not params.get("known_ids"):
                try:
                    params["known_ids"] = json.loads(row["known_ids_json"] or "[]")
                except (ValueError, TypeError):
                    params["known_ids"] = []
            task = ExpandTask(
                id=row["id"], platform=row["platform"], uid=row["uid"],
                nickname=row.get("nickname") or "", graph_id=row["graph_id"],
                params=params,
            )
            self._queue_for(task.platform).push(task)
        if rows:
            print(f"[ExpandQueue] 已恢复 {len(rows)} 个遗留展开任务")

    # ==================== 入队 ====================

    def enqueue(self, graph_id, items: list[dict]) -> dict:
        """
        批量入队。items 每项: platform, uid, nickname?, 以及 expand_social 的参数
        （follows_limit/followers_limit/skip/known_ids/intercheck_*）。
        同图同 uid 已在排队/执行中时跳过（去重），预算超限或平台队列熔断暂停的拒绝。
        返回 {queued, duplicates, rejected, task_ids, paused: [{platform, reason}]}，
        task_ids 为本次新入队任务的自增 id，前端以此圈定进度统计范围。
        """
        self.recover()
        queued = duplicates = rejected = 0
        task_ids: list[int] = []
        paused_now = self.paused_queues()
        paused_by_pid = {p["platform"] for p in paused_now}
        in_flight_keys = {
            (q.platform, t.uid)
            for q in self._queues.values()
            for t in list(q._in_flight.values())
        }
        for item in items:
            platform = str((item or {}).get("platform", "")).strip()
            uid = str((item or {}).get("uid", "")).strip()
            if not platform or not uid or get_pool(platform) is None:
                rejected += 1
                continue
            # 熔断暂停的平台不收新任务，避免任务卡在暂停队列里拖死整体进度
            if platform in paused_by_pid:
                rejected += 1
                continue
            q = self._queue_for(platform)
            # 去重：同图同 uid 已排队或在执行
            with q._lock:
                dup = any(t.graph_id == graph_id and t.uid == uid for t in q._queue)
            if dup or (platform, uid) in in_flight_keys:
                duplicates += 1
                continue
            # 预算：单图排队任务数上限
            pending = self._store.count_expand_tasks(graph_id, ["pending", "running"])
            if pending >= MAX_PENDING_PER_GRAPH:
                rejected += 1
                continue
            params = dict(item)
            params["platform"] = platform
            params["uid"] = uid
            known_ids = params.pop("known_ids", []) or []
            task_id = self._store.insert_expand_task(
                platform, uid, str(params.get("nickname", "") or ""),
                graph_id, params, known_ids,
            )
            task = ExpandTask(id=task_id, platform=platform, uid=uid,
                              nickname=str(params.get("nickname", "") or ""),
                              graph_id=graph_id, params={**params, "known_ids": known_ids})
            if q.push(task):
                queued += 1
                task_ids.append(task.id)
            else:
                # 队列满：回滚登记记录
                try:
                    self._store.update_expand_task(task_id, "cancelled", error="平台队列已满")
                except Exception as e:
                    print(f"[ExpandQueue] 任务 {task_id} 回滚落库失败: {e}")
                rejected += 1
        return {
            "queued": queued, "duplicates": duplicates, "rejected": rejected,
            "task_ids": task_ids, "paused": paused_now,
        }

    # ==================== 控制 / 查询 ====================

    def stop(self, graph_id, platform: str = None) -> int:
        """停止某图谱（可限平台）的排队任务；执行中的任务照常完成"""
        cancelled = 0
        for pid, q in self._queues.items():
            if platform and pid != platform:
                continue
            cancelled += q.cancel_pending(lambda t, g=graph_id: t.graph_id == graph_id)
        if graph_id is not None:
            cancelled += self._store.cancel_pending_expand_tasks(graph_id, platform)
        return cancelled

    def resume(self, platform: str = None):
        """恢复暂停的队列；platform 为空时恢复全部"""
        for pid, q in self._queues.items():
            if platform and pid != platform:
                continue
            q.resume()

    def paused_queues(self) -> list[dict]:
        return [
            {"platform": pid, "reason": q.pause_reason}
            for pid, q in self._queues.items() if q.paused
        ]

    def platform_status(self) -> list[dict]:
        # 合并平台全集：从未入过队的平台也展示（空闲态），避免前端列表缺行
        out = []
        for pid in sorted(set(self._queues.keys()) | set(known_platform_ids())):
            q = self._queues.get(pid)
            pool = get_pool(pid)
            out.append({
                "platform": pid,
                "pending": q.pending_count() if q else 0,
                "running": q.running_count() if q else 0,
                "paused": bool(q and q.paused),
                "pause_reason": q.pause_reason if q else "",
                "accounts": pool.size if pool else 0,
                "interval": q.interval if q else 0.3,
                # 任务明细与账号占用（队列面板展示"正在展开哪些用户、哪个账号在展开"）
                "active_accounts": pool.active_labels() if pool else [],
                "running_tasks": q.running_tasks_snapshot() if q else [],
                "pending_tasks": q.pending_tasks_snapshot() if q else [],
            })
        return out

    def graph_pending(self, graph_id) -> int:
        return self._store.count_expand_tasks(graph_id, ["pending", "running"])

    def results(self, graph_id, since_id: int = 0, limit: int = 50) -> dict:
        """增量拉取完结任务 + 当前图的排队余量 + 暂停中的队列（一次轮询全知道）"""
        rows = self._store.get_expand_results(graph_id, since_id, limit)
        cursor = rows[-1]["id"] if rows else since_id
        return {
            "results": rows,
            "cursor": cursor,
            "pending": self.graph_pending(graph_id),
            "paused": self.paused_queues(),
        }


# 全局单例（首次访问时恢复遗留任务并启动 worker）
_manager: ExpandQueueManager | None = None
_manager_lock = threading.Lock()


def get_expand_queue() -> ExpandQueueManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ExpandQueueManager()
        return _manager
