"""
SQLite 数据存储

表结构：
  snapshots:
    - id          INTEGER PRIMARY KEY
    - platform    TEXT     (netease / bilibili / ...)
    - uid         TEXT     用户 ID
    - data_type   TEXT     (profile / playlists / records / events / follows / playlist_songs)
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
            data_type: 数据类型 (profile / playlists / records / events / follows / playlist_songs)
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

    def get_latest_snapshot(
        self, platform: str, uid: str, data_type: str
    ) -> Optional[dict]:
        """获取最新的一份快照"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json, created_at FROM snapshots "
                "WHERE platform=? AND uid=? AND data_type=? "
                "ORDER BY created_at DESC LIMIT 1",
                (platform, uid, data_type),
            ).fetchone()

        if row:
            data = json.loads(row["data_json"])
            data["_snapshot_time"] = row["created_at"]
            return data
        return None

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

    def get_all_tracked_users(self) -> list[dict]:
        """获取所有被追踪过的用户"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT platform, uid FROM snapshots ORDER BY platform, uid"
            ).fetchall()
        return [{"platform": r["platform"], "uid": r["uid"]} for r in rows]

    # ==================== 对比 ====================

    def compare_snapshots(
        self, platform: str, uid: str, data_type: str
    ) -> dict:
        """
        对比最新两次快照，生成变化报告

        Returns:
            {
                platform, uid, data_type,
                latest_time, previous_time,
                changes: [{field, old_value, new_value}, ...]
            }
        """
        rows = self._connect().execute(
            "SELECT data_json, created_at FROM snapshots "
            "WHERE platform=? AND uid=? AND data_type=? "
            "ORDER BY created_at DESC LIMIT 2",
            (platform, uid, data_type),
        ).fetchall()

        if len(rows) < 2:
            return {
                "platform": platform,
                "uid": uid,
                "data_type": data_type,
                "has_changes": False,
                "reason": "insufficient_data" if not rows else "only_one_snapshot",
                "snapshots_count": len(rows),
            }

        latest = json.loads(rows[0]["data_json"])
        previous = json.loads(rows[1]["data_json"])

        changes = []
        self._diff_dict(latest, previous, "", changes)

        return {
            "platform": platform,
            "uid": uid,
            "data_type": data_type,
            "has_changes": len(changes) > 0,
            "latest_time": rows[0]["created_at"],
            "previous_time": rows[1]["created_at"],
            "changes": changes,
        }

    @staticmethod
    def _diff_dict(new: dict, old: dict, prefix: str, changes: list):
        """递归对比两个字典，记录变化"""
        all_keys = set(new.keys()) | set(old.keys())
        for key in all_keys:
            if key.startswith("_"):
                continue  # 跳过元数据字段
            full_key = f"{prefix}.{key}" if prefix else key
            new_val = new.get(key)
            old_val = old.get(key)

            if isinstance(new_val, dict) and isinstance(old_val, dict):
                DataStore._diff_dict(new_val, old_val, full_key, changes)
            elif isinstance(new_val, list) and isinstance(old_val, list):
                if len(new_val) != len(old_val):
                    changes.append({
                        "field": full_key,
                        "old_value": f"length={len(old_val)}",
                        "new_value": f"length={len(new_val)}",
                        "type": "list_length",
                    })
                # 对于简单元素列表，逐项对比
                if new_val and old_val and isinstance(new_val[0], (str, int, float)):
                    added = set(new_val) - set(old_val)
                    removed = set(old_val) - set(new_val)
                    if added:
                        changes.append({
                            "field": full_key,
                            "type": "list_added",
                            "added": list(added),
                        })
                    if removed:
                        changes.append({
                            "field": full_key,
                            "type": "list_removed",
                            "removed": list(removed),
                        })
            elif new_val != old_val:
                changes.append({
                    "field": full_key,
                    "old_value": str(old_val),
                    "new_value": str(new_val),
                    "type": "changed",
                })

    # ==================== 清理 ====================

    def clean_old_snapshots(self, keep_days: int = 90):
        """清理超过指定天数的旧快照"""
        cutoff = datetime.now(CST) - timedelta(days=keep_days)
        cutoff_str = cutoff.isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM snapshots WHERE created_at < ?", (cutoff_str,)
            )
            conn.commit()

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

    # ==================== 关注变化检测 ====================

    def detect_follow_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比今天所有 follows 快照（逐对比较），累积每次关注/取关变化。

        Returns:
            {
                has_data, latest_time, previous_time,
                changes: [{follow_uid, nickname, avatar, change_type, time_range}, ...]
            }
            change_type: "new_follow" | "unfollow"
        """
        rows = self._load_today_real_snapshots(platform, uid, "follows")

        if len(rows) < 2:
            return {
                "has_data": len(rows) > 0,
                "changes": [],
                "snapshots_count": len(rows),
            }

        changes = []
        for i in range(len(rows) - 1):
            older = json.loads(rows[i]["data_json"])
            newer = json.loads(rows[i + 1]["data_json"])

            older_items = older.get("items", [])
            newer_items = newer.get("items", [])

            older_uids = {str(f.get("uid", "")) for f in older_items}
            newer_uids = {str(f.get("uid", "")) for f in newer_items}

            if newer_uids == older_uids:
                continue

            newer_detail = {str(f.get("uid", "")): f for f in newer_items}
            older_detail = {str(f.get("uid", "")): f for f in older_items}
            time_range = {"since": rows[i]["created_at"], "until": rows[i + 1]["created_at"]}

            for fuid in (newer_uids - older_uids):
                user = newer_detail[fuid]
                changes.append({
                    "follow_uid": fuid,
                    "nickname": user.get("nickname", ""),
                    "avatar": user.get("avatarUrl", ""),
                    "signature": user.get("signature", ""),
                    "change_type": "new_follow",
                    "time_range": time_range,
                })

            for fuid in (older_uids - newer_uids):
                user = older_detail.get(fuid, {})
                changes.append({
                    "follow_uid": fuid,
                    "nickname": user.get("nickname", "已取关用户"),
                    "avatar": user.get("avatarUrl", ""),
                    "signature": user.get("signature", ""),
                    "change_type": "unfollow",
                    "time_range": time_range,
                })

        return {
            "has_data": len(rows) > 0,
            "latest_time": rows[-1]["created_at"],
            "snapshots_count": len(rows),
            "changes": changes,
        }

    # ==================== 歌单/内容列表变化检测 ====================

    def detect_playlist_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比今天所有 playlists 快照（逐对比较），累积每次歌单/内容变化。

        Returns:
            {
                has_data, latest_time, previous_time,
                changes: [{item_id, title, creator, change_type, time_range}, ...]
            }
            change_type: "new_playlist" | "removed_playlist"
        """
        rows = self._load_today_real_snapshots(platform, uid, "playlists")

        if len(rows) < 2:
            return {
                "has_data": len(rows) > 0,
                "changes": [],
                "snapshots_count": len(rows),
            }

        changes = []
        for i in range(len(rows) - 1):
            older = json.loads(rows[i]["data_json"])
            newer = json.loads(rows[i + 1]["data_json"])

            older_items = older.get("items", [])
            newer_items = newer.get("items", [])

            older_ids = {str(it.get("item_id", it.get("id", ""))) for it in older_items}
            newer_ids = {str(it.get("item_id", it.get("id", ""))) for it in newer_items}

            if newer_ids == older_ids:
                continue

            newer_detail = {str(it.get("item_id", it.get("id", ""))): it for it in newer_items}
            older_detail = {str(it.get("item_id", it.get("id", ""))): it for it in older_items}
            time_range = {"since": rows[i]["created_at"], "until": rows[i + 1]["created_at"]}

            for pid in (newer_ids - older_ids):
                item = newer_detail[pid]
                changes.append({
                    "item_id": pid,
                    "title": item.get("title", item.get("name", "")),
                    "creator": item.get("creator", ""),
                    "cover_url": item.get("cover_url", item.get("coverImgUrl", "")),
                    "is_owner": item.get("is_owner", True),
                    "change_type": "new_playlist",
                    "time_range": time_range,
                })

            for pid in (older_ids - newer_ids):
                item = older_detail.get(pid, {})
                changes.append({
                    "item_id": pid,
                    "title": item.get("title", item.get("name", "已删除")),
                    "creator": item.get("creator", ""),
                    "cover_url": item.get("cover_url", item.get("coverImgUrl", "")),
                    "is_owner": item.get("is_owner", True),
                    "change_type": "removed_playlist",
                    "time_range": time_range,
                })

        return {
            "has_data": len(rows) > 0,
            "latest_time": rows[-1]["created_at"],
            "snapshots_count": len(rows),
            "changes": changes,
        }

    # ==================== 歌单歌曲变化检测 ====================

    def detect_playlist_song_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比今天所有 playlist_songs 快照（逐对比较），累积每次歌单内歌曲增减。

        Returns:
            changes: [{
                playlist_id, playlist_title,
                song_id, song_title, artist,
                change_type: "song_added" | "song_removed",
                time_range: {since, until}
            }, ...]
        """
        rows = self._load_today_real_snapshots(platform, uid, "playlist_songs")

        if len(rows) < 2:
            return {"has_data": len(rows) > 0, "changes": [], "snapshots_count": len(rows)}

        changes = []
        for i in range(len(rows) - 1):
            older = json.loads(rows[i]["data_json"])
            newer = json.loads(rows[i + 1]["data_json"])

            if older.get("fetching") or newer.get("fetching"):
                continue

            older_pls = older.get("playlists", {})
            newer_pls = newer.get("playlists", {})

            # 检查是否有差异
            all_pl_ids = set(older_pls.keys()) | set(newer_pls.keys())
            has_diff = False
            for pl_id in all_pl_ids:
                older_songs = {s.get("id", "") for s in older_pls.get(pl_id, {}).get("songs", [])}
                newer_songs = {s.get("id", "") for s in newer_pls.get(pl_id, {}).get("songs", [])}
                if older_songs != newer_songs:
                    has_diff = True
                    break

            if not has_diff:
                continue

            time_range = {"since": rows[i]["created_at"], "until": rows[i + 1]["created_at"]}

            for pl_id in all_pl_ids:
                older_songs_map = {s.get("id", ""): s for s in older_pls.get(pl_id, {}).get("songs", [])}
                newer_songs_map = {s.get("id", ""): s for s in newer_pls.get(pl_id, {}).get("songs", [])}
                pl_info = newer_pls.get(pl_id, older_pls.get(pl_id, {}))

                for sid in (set(newer_songs_map.keys()) - set(older_songs_map.keys())):
                    song = newer_songs_map[sid]
                    changes.append({
                        "playlist_id": pl_id,
                        "playlist_title": pl_info.get("title", ""),
                        "song_id": sid,
                        "song_title": song.get("title", ""),
                        "artist": song.get("artist", ""),
                        "change_type": "song_added",
                        "time_range": time_range,
                    })

                for sid in (set(older_songs_map.keys()) - set(newer_songs_map.keys())):
                    song = older_songs_map.get(sid, {})
                    changes.append({
                        "playlist_id": pl_id,
                        "playlist_title": pl_info.get("title", ""),
                        "song_id": sid,
                        "song_title": song.get("title", "已移除"),
                        "artist": song.get("artist", ""),
                        "change_type": "song_removed",
                        "time_range": time_range,
                    })

        return {
            "has_data": len(rows) > 0,
            "latest_time": rows[-1]["created_at"] if rows else None,
            "snapshots_count": len(rows),
            "changes": changes,
        }
