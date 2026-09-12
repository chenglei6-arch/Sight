"""
SQLite 数据存储

表结构：
  snapshots:
    - id          INTEGER PRIMARY KEY
    - platform    TEXT     (netease / bilibili / ...)
    - uid         TEXT     用户 ID
    - data_type   TEXT     (profile / playlists / records / events / follows)
    - data_json   TEXT     JSON 数据；标记快照格式为 {"_marker": true, "_hash": "..."}
    - created_at  TEXT     ISO 时间戳

核心优化——哈希去重：
  每次保存快照前，对数据内容计算 SHA256 哈希（去除了时间等元数据字段）。
  若与最近一条同类型真实快照的哈希相同 → 只存标记 {"_marker": true}，不存完整数据。
  哈希不同 → 存完整数据，后续变化检测方法会自动跳过标记只对比真实快照。
"""
import json
import sqlite3
import hashlib
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# 数据库路径
DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "snapshots.db"

# 北京时间
CST = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


class DataStore:
    """数据持久化存储"""

    def __init__(self, db_path: Path = None):
        self._db_path = db_path or DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform    TEXT    NOT NULL,
                    uid         TEXT    NOT NULL,
                    data_type   TEXT    NOT NULL,
                    data_json   TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_lookup
                ON snapshots(platform, uid, data_type, created_at DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS timeline (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform         TEXT    NOT NULL,
                    uid              TEXT    NOT NULL,
                    event_type       TEXT    NOT NULL,
                    timestamp        INTEGER DEFAULT 0,
                    time_str         TEXT    DEFAULT '',
                    time_suffix      TEXT    DEFAULT '',
                    summary          TEXT    DEFAULT '',
                    detail           TEXT    DEFAULT '',
                    time_range_since TEXT    DEFAULT '',
                    time_range_until TEXT    DEFAULT '',
                    raw_json         TEXT    DEFAULT '{}',
                    dedup_key        TEXT    NOT NULL UNIQUE,
                    created_at       TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timeline_lookup
                ON timeline(platform, uid, created_at DESC)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graphs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    NOT NULL UNIQUE,
                    keyword     TEXT    DEFAULT '',
                    node_count  INTEGER DEFAULT 0,
                    edge_count  INTEGER DEFAULT 0,
                    data_json   TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL,
                    updated_at  TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS expand_tasks (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform      TEXT    NOT NULL,
                    uid           TEXT    NOT NULL,
                    nickname      TEXT    DEFAULT '',
                    graph_id      INTEGER,
                    params_json   TEXT    NOT NULL DEFAULT '{}',
                    known_ids_json TEXT   DEFAULT '[]',
                    status        TEXT    NOT NULL DEFAULT 'pending',
                    result_json   TEXT,
                    error         TEXT,
                    created_at    TEXT    NOT NULL,
                    updated_at    TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expand_task_graph
                ON expand_tasks(graph_id, status, id)
            """)
            conn.commit()

    # ==================== 哈希计算 ====================

    @staticmethod
    def _compute_hash(data: dict) -> str:
        """对数据内容计算 SHA256 哈希（排除 _ 开头的元数据字段）"""
        content = {k: v for k, v in data.items() if not k.startswith("_")}
        raw = json.dumps(content, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_latest_hash(self, platform: str, uid: str, data_type: str) -> Optional[str]:
        """获取最近一条同类型真实快照（非标记）的哈希值"""
        row = self._connect().execute(
            "SELECT data_json FROM snapshots "
            "WHERE platform=? AND uid=? AND data_type=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (platform, uid, data_type),
        ).fetchone()
        if row:
            data = json.loads(row["data_json"])
            if not data.get("_marker"):
                return data.get("_hash")
        return None

    # ==================== 保存 ====================

    def save_snapshot(self, platform: str, uid: str, data_type: str, data: dict):
        """
        保存一份数据快照。
        若内容哈希与上一条同类型真实快照相同，只存标记不存完整数据。

        Args:
            platform: 平台标识
            uid: 用户 ID
            data_type: 数据类型 (profile / playlists / records / events / follows)
            data: 数据字典
        """
        content_hash = self._compute_hash(data)
        latest_hash = self._get_latest_hash(platform, uid, data_type)

        if latest_hash == content_hash:
            # 与上一条相同，只存标记
            marker = {"_marker": True, "_hash": content_hash}
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO snapshots (platform, uid, data_type, data_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (platform, uid, data_type, json.dumps(marker, ensure_ascii=False), _now_iso()),
                )
                conn.commit()
            return

        # 内容有变化，存完整数据
        data["_hash"] = content_hash
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO snapshots (platform, uid, data_type, data_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (platform, uid, data_type, json.dumps(data, ensure_ascii=False), _now_iso()),
            )
            conn.commit()

    # ==================== 读取 ====================

    def get_snapshots(
        self,
        platform: str,
        uid: str,
        data_type: str,
        since: str = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        获取历史快照列表

        Args:
            platform: 平台
            uid: 用户 ID
            data_type: 数据类型
            since: ISO 时间字符串，只返回此时间之后的数据
            limit: 最大返回数
        """
        if since:
            rows = self._connect().execute(
                "SELECT data_json, created_at FROM snapshots "
                "WHERE platform=? AND uid=? AND data_type=? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (platform, uid, data_type, since, limit),
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT data_json, created_at FROM snapshots "
                "WHERE platform=? AND uid=? AND data_type=? "
                "ORDER BY created_at DESC LIMIT ?",
                (platform, uid, data_type, limit),
            ).fetchall()

        result = []
        for row in rows:
            data = json.loads(row["data_json"])
            data["_snapshot_time"] = row["created_at"]
            result.append(data)
        return result

    # ==================== 活动时间线持久化 ====================

    def insert_timeline_entries(self, entries) -> int:
        """
        将时间线条目持久化到 timeline 表。
        使用 INSERT OR IGNORE + UNIQUE(dedup_key) 避免重复加入。

        Args:
            entries: TimelineEntry 对象列表

        Returns:
            实际新插入的条目数
        """
        inserted = 0
        now = _now_iso()
        with self._connect() as conn:
            for entry in entries:
                time_range = getattr(entry, "time_range", {}) or {}
                cur = conn.execute(
                    """INSERT OR IGNORE INTO timeline
                    (platform, uid, event_type, timestamp, time_str, time_suffix,
                     summary, detail, time_range_since, time_range_until,
                     raw_json, dedup_key, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.platform,
                        entry.uid,
                        entry.event_type,
                        entry.timestamp,
                        entry.time_str,
                        entry.time_suffix,
                        entry.summary,
                        entry.detail,
                        time_range.get("since", ""),
                        time_range.get("until", ""),
                        json.dumps(entry.raw, ensure_ascii=False),
                        entry.dedup_key(),
                        now,
                    ),
                )
                inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.commit()
        print(f"[DataStore] 时间线持久化: 收到 {len(entries)} 条，新增 {inserted} 条")
        return inserted

    def get_timeline_entries(
        self,
        platform: str = None,
        uid: str = None,
        event_type: str = None,
        since: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        查询持久化的时间线条目。

        Args:
            platform: 平台筛选（可选）
            uid: 用户筛选（可选）
            event_type: 事件类型筛选（可选）
            since: ISO 时间，只返回此时间之后创建的条目
            limit: 最大返回数
            offset: 偏移量

        Returns:
            时间线条目列表（dict）
        """
        conditions = []
        params = []
        if platform:
            conditions.append("platform=?")
            params.append(platform)
        if uid:
            conditions.append("uid=?")
            params.append(uid)
        if event_type:
            conditions.append("event_type=?")
            params.append(event_type)
        if since:
            conditions.append("created_at >= ?")
            params.append(since)

        where = " AND ".join(conditions) if conditions else "1=1"

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM timeline WHERE {where} "
                "ORDER BY created_at DESC, timestamp DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

        return [dict(r) for r in rows]

    def update_timeline_entry(
        self, entry_id: int, summary: str = None, detail: str = None
    ) -> bool:
        """
        更新时间线条目的 summary 和/或 detail。

        Returns:
            True 如果更新成功（存在该记录），False 如果记录不存在
        """
        updates = []
        params = []
        if summary is not None:
            updates.append("summary=?")
            params.append(summary)
        if detail is not None:
            updates.append("detail=?")
            params.append(detail)
        if not updates:
            return False

        params.append(entry_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE timeline SET {', '.join(updates)} WHERE id=?",
                params,
            )
            conn.commit()
            return conn.total_changes > 0

    def delete_timeline_entry(self, entry_id: int) -> bool:
        """删除一条时间线条目。返回 True 表示删除成功。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM timeline WHERE id=?", (entry_id,))
            conn.commit()
            return conn.total_changes > 0

    # ==================== 关系图谱持久化 ====================

    def save_graph(self, name: str, keyword: str, data: dict) -> int:
        """
        按名称保存一张关系图谱（节点/边完整 JSON）；同名图谱覆盖更新。

        Returns:
            图谱 id（新建或被更新的那条记录）
        """
        now = _now_iso()
        payload = json.dumps(data, ensure_ascii=False)
        node_count = len(data.get("nodes") or [])
        edge_count = len(data.get("edges") or [])
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM graphs WHERE name=?", (name,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE graphs SET keyword=?, data_json=?, node_count=?, edge_count=?, updated_at=? "
                    "WHERE id=?",
                    (keyword, payload, node_count, edge_count, now, row["id"]),
                )
                graph_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO graphs (name, keyword, data_json, node_count, edge_count, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, keyword, payload, node_count, edge_count, now, now),
                )
                graph_id = cur.lastrowid
            conn.commit()
        return graph_id

    def list_graphs(self) -> list[dict]:
        """列出所有已保存图谱的元信息（不含节点/边数据），按更新时间倒序。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, keyword, node_count, edge_count, created_at, updated_at "
                "FROM graphs ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_graph(self, graph_id: int) -> Optional[dict]:
        """获取一张图谱的完整数据（元信息 + data 字段里的 nodes/edges）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, keyword, data_json, node_count, edge_count, created_at, updated_at "
                "FROM graphs WHERE id=?",
                (graph_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["data"] = json.loads(result.pop("data_json"))
        return result

    def delete_graph(self, graph_id: int) -> bool:
        """删除一张已保存图谱。返回 True 表示删除成功。"""
        with self._connect() as conn:
            conn.execute("DELETE FROM graphs WHERE id=?", (graph_id,))
            conn.commit()
            return conn.total_changes > 0

    # ==================== 社交展开队列持久化 ====================

    def insert_expand_task(
        self,
        platform: str,
        uid: str,
        nickname: str,
        graph_id,
        params: dict,
        known_ids: list,
    ) -> int:
        """登记一个待执行的展开任务，返回任务 id"""
        now = _now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO expand_tasks "
                "(platform, uid, nickname, graph_id, params_json, known_ids_json, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    platform, uid, nickname, graph_id,
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(known_ids, ensure_ascii=False),
                    now, now,
                ),
            )
            conn.commit()
            return cur.lastrowid

    def update_expand_task(self, task_id: int, status: str, result: dict = None, error: str = None):
        """回写任务状态；done 时存结果载荷，failed/cancelled 时存原因"""
        sets = ["status=?", "updated_at=?"]
        params: list = [status, _now_iso()]
        if result is not None:
            sets.append("result_json=?")
            params.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            sets.append("error=?")
            params.append(error)
        params.append(task_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE expand_tasks SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()

    def get_recoverable_expand_tasks(self) -> list[dict]:
        """获取中断遗留的任务（pending/running，服务重启后重新入队）"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM expand_tasks WHERE status IN ('pending', 'running') ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_expand_results(self, graph_id, since_id: int = 0, limit: int = 50) -> list[dict]:
        """按 id 增量获取已完结任务（done/failed/cancelled），供前端轮询合并"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, platform, uid, nickname, graph_id, status, result_json, error, params_json, updated_at "
                "FROM expand_tasks WHERE graph_id=? AND id>? AND status IN ('done','failed','cancelled') "
                "ORDER BY id LIMIT ?",
                (graph_id, since_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
            # 提取任务请求的方向（limit>0 即请求了该方向），前端据此累计进度与展开标记
            dirs = {"follows": False, "followers": False}
            try:
                params = json.loads(item.pop("params_json") or "{}")
                dirs["follows"] = int(params.get("follows_limit") or 0) > 0
                dirs["followers"] = int(params.get("followers_limit") or 0) > 0
            except (ValueError, TypeError):
                pass
            item["dirs"] = dirs
            out.append(item)
        return out

    def count_expand_tasks(self, graph_id, statuses: list[str]) -> int:
        """统计某图谱指定状态的任务数（预算/轮询终止判断用）"""
        marks = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM expand_tasks WHERE graph_id=? AND status IN ({marks})",
                [graph_id] + statuses,
            ).fetchone()
        return row["c"] if row else 0

    def cancel_pending_expand_tasks(self, graph_id, platform: str = None) -> int:
        """把某图谱（可限平台）的 pending 任务标记为 cancelled。返回取消数量。"""
        sql = "UPDATE expand_tasks SET status='cancelled', error='用户停止', updated_at=? WHERE graph_id=? AND status='pending'"
        params: list = [_now_iso(), graph_id]
        if platform:
            sql += " AND platform=?"
            params.append(platform)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def purge_old_expand_tasks(self, keep_hours: int = 24) -> int:
        """清理超过保留期的已完结任务，防止表无限膨胀"""
        cutoff = (datetime.now(CST) - timedelta(hours=keep_hours)).isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM expand_tasks WHERE status IN ('done','failed','cancelled') AND updated_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    # ==================== 变化检测辅助 ====================

    def _load_today_real_snapshots(
        self, platform: str, uid: str, data_type: str
    ) -> list[sqlite3.Row]:
        """
        加载今天该类型的所有「真实」快照（排除标记），按时间升序。
        若今天真实快照不足 2 条，向前追溯到最近一天。
        """
        today_start = datetime.now(CST).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        rows = self._connect().execute(
            "SELECT data_json, created_at FROM snapshots "
            "WHERE platform=? AND uid=? AND data_type=? "
            "AND created_at >= ? "
            "ORDER BY created_at ASC",
            (platform, uid, data_type, today_start),
        ).fetchall()

        # 过滤掉标记快照
        real_rows = []
        for row in rows:
            data = json.loads(row["data_json"])
            if not data.get("_marker"):
                real_rows.append(row)

        # 若今天真实快照不足 2 条，向前补充
        if len(real_rows) < 2:
            needed = 2 - len(real_rows)
            older = self._connect().execute(
                "SELECT data_json, created_at FROM snapshots "
                "WHERE platform=? AND uid=? AND data_type=? "
                "AND created_at < ? "
                "ORDER BY created_at DESC LIMIT ?",
                (platform, uid, data_type, today_start, needed),
            ).fetchall()
            for row in reversed(older):
                data = json.loads(row["data_json"])
                if not data.get("_marker"):
                    real_rows.insert(0, row)

        return real_rows

    # ==================== 记录变化检测（听歌/观看） ====================

    def detect_record_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比今天所有 records 快照（逐对比较），累积每次播放次数的增长。

        每条变化包含:
          - song_id, song_name, artist, album, cover_url
          - change_type: "new" | "increased"
          - old_count, new_count, delta
          - time_range: {since, until}
        """
        rows = self._load_today_real_snapshots(platform, uid, "records")

        if len(rows) < 2:
            return {
                "has_data": len(rows) > 0,
                "snapshots_count": len(rows),
                "changes": [],
            }

        all_changes = []

        for i in range(len(rows) - 1):
            older = json.loads(rows[i]["data_json"])
            newer = json.loads(rows[i + 1]["data_json"])
            time_range = {
                "since": rows[i]["created_at"],
                "until": rows[i + 1]["created_at"],
            }

            # ---- 对比 allTime ----
            older_at = self._build_song_map(older.get("allTime", []))
            newer_at = self._build_song_map(newer.get("allTime", []))
            all_changes.extend(
                self._diff_song_maps(older_at, newer_at, "all", time_range)
            )

            # ---- 对比 weekly ----
            older_wk = self._build_song_map(older.get("weekly", []))
            newer_wk = self._build_song_map(newer.get("weekly", []))
            all_changes.extend(
                self._diff_song_maps(older_wk, newer_wk, "week", time_range)
            )

        # 去重：同一首歌在同一时间段 all/ week 都出现时，优先保留 weekly
        merged = self._dedup_pair_changes(all_changes)

        return {
            "has_data": True,
            "latest_time": rows[-1]["created_at"],
            "snapshots_count": len(rows),
            "changes": merged,
        }

    @staticmethod
    def _build_song_map(song_list: list) -> dict:
        """song 列表 → {song_id: {meta..., play_count}}"""
        result = {}
        for s in song_list:
            sid = str(s.get("entry_id", s.get("id", "")))
            if not sid:
                continue
            result[sid] = {
                "song_name": s.get("title", s.get("name", "")),
                "artist": s.get("artist_or_uploader", s.get("artists", "")),
                "album": s.get("album_or_category", s.get("album", "")),
                "cover_url": s.get("cover_url", s.get("coverUrl", "")),
                "play_count": int(s.get("play_count", s.get("playCount", 0)) or 0),
            }
        return result

    @staticmethod
    def _diff_song_maps(
        older: dict, newer: dict, period: str, time_range: dict
    ) -> list[dict]:
        """对比两个快照的歌曲映射，生成变化列表"""
        changes = []
        all_ids = set(older.keys()) | set(newer.keys())

        for sid in all_ids:
            old_data = older.get(sid)
            new_data = newer.get(sid)

            if old_data is None and new_data is not None:
                # 新出现的歌曲
                changes.append({
                    "song_id": sid,
                    "song_name": new_data["song_name"],
                    "artist": new_data["artist"],
                    "album": new_data["album"],
                    "cover_url": new_data["cover_url"],
                    "change_type": "new",
                    "old_count": 0,
                    "new_count": new_data["play_count"],
                    "delta": new_data["play_count"],
                    "period": period,
                    "time_range": time_range,
                })
            elif old_data is not None and new_data is not None:
                old_count = old_data["play_count"]
                new_count = new_data["play_count"]
                if new_count > old_count:
                    changes.append({
                        "song_id": sid,
                        "song_name": new_data["song_name"],
                        "artist": new_data["artist"],
                        "album": new_data["album"],
                        "cover_url": new_data["cover_url"],
                        "change_type": "increased",
                        "old_count": old_count,
                        "new_count": new_count,
                        "delta": new_count - old_count,
                        "period": period,
                        "time_range": time_range,
                    })

        return changes

    @staticmethod
    def _dedup_pair_changes(changes: list[dict]) -> list[dict]:
        """
        同一时间段内同一首歌 allTime 和 weekly 都出现时，
        优先保留有 time_range 的，都有则保留 weekly。
        不同时间段的变化全部保留。
        """
        # 按 (song_id, time_range.since, time_range.until) 分组去重
        groups: dict[tuple, dict] = {}
        for ch in changes:
            tr = ch.get("time_range") or {}
            key = (ch["song_id"], tr.get("since", ""), tr.get("until", ""))
            if key not in groups:
                groups[key] = ch
            else:
                existing = groups[key]
                # 优先保留 weekly；如果现有 all 且新来的是 week，替换
                if ch["period"] == "week" and existing["period"] == "all":
                    groups[key] = ch
                # 如果现有 week 且新来的是 week，也替换（后来居上）
                elif ch["period"] == "week":
                    groups[key] = ch
        return list(groups.values())

    # ==================== 通用集合类变化检测（关注/粉丝/内容列表） ====================

    def _detect_set_changes(
        self,
        platform: str,
        uid: str,
        data_type: str,
        id_keys: tuple,
        out_id_key: str,
        added_type: str,
        removed_type: str,
        field_map: dict,
        removed_defaults: dict,
    ) -> dict:
        """
        对比今天所有 data_type 快照（逐对比较），按条目 id 集合差异累积增减变化。

        id_keys: 条目 id 字段候选（依次取第一个非空值，如 ("item_id", "id")）
        out_id_key: 变化条目里承载 id 的字段名
        field_map: {输出字段: (来源字段候选元组, 缺省值)}
        removed_defaults: removed 条目里对缺失字段的覆盖缺省（如 title="已删除"）
        """
        rows = self._load_today_real_snapshots(platform, uid, data_type)

        if len(rows) < 2:
            return {
                "has_data": len(rows) > 0,
                "changes": [],
                "snapshots_count": len(rows),
            }

        def entry_id(item: dict) -> str:
            for key in id_keys:
                v = item.get(key, "")
                if v not in (None, ""):
                    return str(v)
            return ""

        def pick(item: dict, candidates, default):
            for key in candidates:
                v = item.get(key)
                if v not in (None, ""):
                    return v
            return default

        changes = []
        for i in range(len(rows) - 1):
            older = json.loads(rows[i]["data_json"])
            newer = json.loads(rows[i + 1]["data_json"])

            older_items = older.get("items", [])
            newer_items = newer.get("items", [])

            older_ids = {entry_id(f) for f in older_items}
            newer_ids = {entry_id(f) for f in newer_items}

            if newer_ids == older_ids:
                continue

            older_detail = {entry_id(f): f for f in older_items}
            newer_detail = {entry_id(f): f for f in newer_items}
            time_range = {"since": rows[i]["created_at"], "until": rows[i + 1]["created_at"]}

            for cid in (newer_ids - older_ids):
                item = newer_detail[cid]
                change = {out_id_key: cid, "change_type": added_type}
                for out_key, (candidates, default) in field_map.items():
                    change[out_key] = pick(item, candidates, default)
                change["time_range"] = time_range
                changes.append(change)

            for cid in (older_ids - newer_ids):
                item = older_detail.get(cid, {})
                change = {out_id_key: cid, "change_type": removed_type}
                for out_key, (candidates, default) in field_map.items():
                    change[out_key] = pick(item, candidates, removed_defaults.get(out_key, default))
                change["time_range"] = time_range
                changes.append(change)

        return {
            "has_data": len(rows) > 0,
            "latest_time": rows[-1]["created_at"],
            "snapshots_count": len(rows),
            "changes": changes,
        }

    # ==================== 变化检测对外接口 ====================

    def detect_follow_changes(self, platform: str, uid: str) -> dict:
        """关注变化（new_follow / unfollow），字段见 _detect_set_changes"""
        return self._detect_set_changes(
            platform, uid, "follows",
            id_keys=("uid",), out_id_key="follow_uid",
            added_type="new_follow", removed_type="unfollow",
            field_map={
                "nickname": (("nickname",), ""),
                "avatar": (("avatarUrl",), ""),
                "signature": (("signature",), ""),
            },
            removed_defaults={"nickname": "已取关用户"},
        )

    def detect_follower_changes(self, platform: str, uid: str) -> dict:
        """粉丝变化（new_follower / lost_follower）"""
        return self._detect_set_changes(
            platform, uid, "followers",
            id_keys=("uid",), out_id_key="follower_uid",
            added_type="new_follower", removed_type="lost_follower",
            field_map={
                "nickname": (("nickname",), ""),
                "avatar": (("avatarUrl",), ""),
                "signature": (("signature",), ""),
            },
            removed_defaults={"nickname": "已离开用户"},
        )

    def detect_playlist_changes(self, platform: str, uid: str) -> dict:
        """内容列表变化（new_playlist / removed_playlist）"""
        return self._detect_set_changes(
            platform, uid, "playlists",
            id_keys=("item_id", "id"), out_id_key="item_id",
            added_type="new_playlist", removed_type="removed_playlist",
            field_map={
                "title": (("title", "name"), ""),
                "creator": (("creator",), ""),
                "cover_url": (("cover_url", "coverImgUrl"), ""),
                "is_owner": (("is_owner",), True),
            },
            removed_defaults={"title": "已删除"},
        )

