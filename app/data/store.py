"""
SQLite 数据存储

表结构：
  snapshots:
    - id          INTEGER PRIMARY KEY
    - platform    TEXT     (netease / bilibili / ...)
    - uid         TEXT     用户 ID
    - data_type   TEXT     (profile / playlists / records / events)
    - data_json   TEXT     JSON 数据
    - created_at  TEXT     ISO 时间戳
"""
import json
import sqlite3
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

    # ==================== 保存 ====================

    def save_snapshot(self, platform: str, uid: str, data_type: str, data: dict):
        """
        保存一份数据快照

        Args:
            platform: 平台标识
            uid: 用户 ID
            data_type: 数据类型 (profile / playlists / records / events)
            data: 数据字典
        """
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

    # ==================== 记录变化检测（听歌/观看） ====================

    def detect_record_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比所有历史 records 快照，推断每首歌的听歌时间。

        核心思路：
          - 遍历全部快照（按时间升序），追踪每首歌在各快照中的出现情况
          - 找到每首歌首次出现的快照 → 推断"开始听"的时间窗口
          - 检测相邻快照间播放次数的增长 → 推断"又在听"的时间窗口
          - 对于首个快照就已存在的歌 → 标注为 "ongoing"（持续在听，无法推断起点）

        返回值中每条变化包含:
          - song_id, song_name, artist, album, cover_url
          - change_type:
              "new"         — 在最近两次快照之间新出现（开始听）
              "increased"   — 最近两次快照之间播放次数增加了（又在听）
              "first_seen"  — 在更早的快照中首次出现，最近无变化
              "ongoing"     — 在最早快照中就已存在，最近无变化
              "new_first"   — 只有一次快照，无法推断
          - old_count, new_count: 播放次数（变化前后）
          - time_range: {since, until} 推断的时间范围（ISO 字符串）
          - first_seen_time: 首次出现的快照时间
          - first_seen_range: {since, until} 首次出现的时间窗口
          - total_snapshots_seen: 该歌曲出现在多少个快照中
        """
        # 获取最近的 records 快照（最多 500 条），按时间升序排列
        # 子查询先按 DESC 取最新 N 条，外层再按 ASC 排序供时间线分析
        rows = self._connect().execute(
            "SELECT data_json, created_at FROM ("
            "  SELECT data_json, created_at FROM snapshots "
            "  WHERE platform=? AND uid=? AND data_type='records' "
            "  ORDER BY created_at DESC LIMIT 500"
            ") ORDER BY created_at ASC",
            (platform, uid),
        ).fetchall()

        if not rows:
            return {"has_data": False, "changes": [], "time_range": None}

        # 解析所有快照
        snapshots = []
        for row in rows:
            data = json.loads(row["data_json"])
            snapshots.append({
                "time": row["created_at"],
                "allTime": data.get("allTime", []),
                "weekly": data.get("weekly", []),
            })

        total_snaps = len(snapshots)
        latest = snapshots[-1]
        latest_time = latest["time"]
        previous_time = snapshots[-2]["time"] if total_snaps >= 2 else None
        has_previous = total_snaps >= 2

        # 分别分析 allTime 和 weekly
        all_changes = self._analyze_song_history(
            snapshots, "allTime", latest["allTime"],
        )
        week_changes = self._analyze_song_history(
            snapshots, "weekly", latest["weekly"],
        )

        # 去重：同一首歌可能在 allTime 和 weekly 同时出现，优先保留 weekly
        # （周榜数据更有近期参考价值），同时合并两者的有用信息
        merged = self._deduplicate_changes(all_changes, week_changes)

        return {
            "has_data": True,
            "latest_time": latest_time,
            "previous_time": previous_time,
            "has_previous": has_previous,
            "snapshots_count": total_snaps,
            "changes": merged,
        }

    @staticmethod
    def _deduplicate_changes(
        all_changes: list[dict],
        week_changes: list[dict],
    ) -> list[dict]:
        """去重：同一首歌在 allTime 和 weekly 同时出现时，优先保留 weekly 条目"""
        merged = {}
        # 先放 allTime（会被 weekly 覆盖）
        for ch in all_changes:
            merged[ch["song_id"]] = ch
        # weekly 覆盖同 song_id 的条目
        for ch in week_changes:
            sid = ch["song_id"]
            if sid in merged:
                # 保留 weekly 的时间推断，但合并 total_snapshots_seen 等字段
                existing = merged[sid]
                ch["total_snapshots_seen"] = max(
                    ch.get("total_snapshots_seen", 0),
                    existing.get("total_snapshots_seen", 0),
                )
            merged[sid] = ch
        return list(merged.values())

    @staticmethod
    def _analyze_song_history(
        snapshots: list[dict],
        period: str,
        latest_song_list: list[dict],
    ) -> list[dict]:
        """
        跨所有快照分析每首歌的历史轨迹。

        Args:
            snapshots: 全部快照列表（按时间升序），每项含 {time, allTime, weekly}
            period: "allTime" | "weekly"
            latest_song_list: 最新快照中的歌曲列表（用于获取元数据）

        Returns:
            变化列表，按 song_id 去重，每条包含完整的时间推断信息
        """
        total_snaps = len(snapshots)

        # ---- 第一遍：建立每首歌的历史轨迹 ----
        # song_history[song_id] = [(snap_idx, time, play_count), ...]
        song_history: dict[str, list[tuple]] = {}
        for idx, snap in enumerate(snapshots):
            for song in snap.get(period, []):
                sid = str(song.get("entry_id", song.get("id", "")))
                if not sid:
                    continue
                count = song.get("play_count", song.get("playCount", 0))
                if sid not in song_history:
                    song_history[sid] = []
                song_history[sid].append((idx, snap["time"], count))

        # ---- 第二遍：为最新快照中的每首歌生成变化条目 ----
        changes = []
        seen_sids = set()

        for song in latest_song_list:
            sid = str(song.get("entry_id", song.get("id", "")))
            if not sid or sid in seen_sids:
                continue
            seen_sids.add(sid)

            song_name = song.get("title", song.get("name", ""))
            artist = song.get("artist_or_uploader", song.get("artists", ""))
            album = song.get("album_or_category", song.get("album", ""))
            cover = song.get("cover_url", song.get("coverUrl", ""))
            new_count = song.get("play_count", song.get("playCount", 0))

            history = song_history.get(sid, [])

            if not history:
                # 理论上不会走到这里（song 来自 latest，history 必然非空）
                continue

            first_idx, first_time, first_count = history[0]
            last_idx, last_time, last_count = history[-1]

            is_first_snapshot_song = (first_idx == 0)   # 在最早快照中就存在
            is_only_one_snapshot = (total_snaps == 1)

            # ---- 计算首次出现的时间窗口 ----
            first_seen_range = None
            if not is_first_snapshot_song:
                # 在 snapshot[first_idx-1] 时还不存在，在 snapshot[first_idx] 时出现
                prev_snap_time = snapshots[first_idx - 1]["time"]
                first_seen_range = {"since": prev_snap_time, "until": first_time}

            # ---- 检测最近一次快照间的变化（最近两次快照对比） ----
            recent_activity = None
            if len(history) >= 2:
                prev_entry = history[-2]
                curr_entry = history[-1]
                prev_count = prev_entry[2]
                curr_count = curr_entry[2]
                if curr_count > prev_count:
                    recent_activity = {
                        "since": prev_entry[1],
                        "until": curr_entry[1],
                        "old_count": prev_count,
                        "new_count": curr_count,
                        "delta": curr_count - prev_count,
                    }

            # ---- 确定 change_type 和展示用的 time_range ----
            if recent_activity:
                # 最近有变化 → 优先展示"又在听"
                change_type = "increased"
                time_range = {
                    "since": recent_activity["since"],
                    "until": recent_activity["until"],
                }
                old_count = recent_activity["old_count"]
                delta = recent_activity["delta"]
            elif is_only_one_snapshot:
                # 只有一次快照，无法对比
                change_type = "new_first"
                time_range = None
                old_count = 0
                delta = 0
            elif first_idx == total_snaps - 1:
                # 在最新快照中首次出现 → "开始听"
                change_type = "new"
                time_range = first_seen_range
                old_count = 0
                delta = last_count
            elif not is_first_snapshot_song:
                # 在更早快照中首次出现，但最近无变化 → "首次检测到"
                change_type = "first_seen"
                time_range = first_seen_range
                old_count = 0
                delta = 0
            else:
                # 在最早快照中就存在，最近无变化 → "持续在听"
                change_type = "ongoing"
                time_range = None
                old_count = first_count
                delta = 0

            changes.append({
                "song_id": sid,
                "song_name": song_name,
                "artist": artist,
                "album": album,
                "cover_url": cover,
                "change_type": change_type,
                "old_count": old_count,
                "new_count": last_count,
                "delta": delta,
                "period": period,
                "time_range": time_range,
                "first_seen_time": first_time,
                "first_seen_range": first_seen_range,
                "total_snapshots_seen": len(history),
                "recent_activity": recent_activity,
            })

        # 按 song_id 排序保证稳定输出
        changes.sort(key=lambda c: c["song_id"])
        return changes

    # ==================== 关注变化检测 ====================

    def detect_follow_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比最近两次 follows 快照，检测关注变化。

        Returns:
            {
                has_data, latest_time, previous_time,
                changes: [{follow_uid, nickname, avatar, change_type, time_range}, ...]
            }
            change_type: "new_follow" | "unfollow"
        """
        rows = self._connect().execute(
            "SELECT data_json, created_at FROM snapshots "
            "WHERE platform=? AND uid=? AND data_type='follows' "
            "ORDER BY created_at DESC, id DESC LIMIT 2",
            (platform, uid),
        ).fetchall()

        if len(rows) < 2:
            return {
                "has_data": len(rows) > 0,
                "changes": [],
                "snapshots_count": len(rows),
            }

        latest_data = json.loads(rows[0]["data_json"])
        previous_data = json.loads(rows[1]["data_json"])
        latest_time = rows[0]["created_at"]
        previous_time = rows[1]["created_at"]

        latest_items = latest_data.get("items", [])
        previous_items = previous_data.get("items", [])

        # 用 uid 建立索引
        latest_uids = {str(f.get("uid", "")) for f in latest_items}
        previous_uids = {str(f.get("uid", "")) for f in previous_items}

        # 用最新数据建立详情查找表
        latest_detail = {str(f.get("uid", "")): f for f in latest_items}
        previous_detail = {str(f.get("uid", "")): f for f in previous_items}

        new_follows = latest_uids - previous_uids
        unfollows = previous_uids - latest_uids

        changes = []
        time_range = {"since": previous_time, "until": latest_time}

        for fuid in new_follows:
            user = latest_detail[fuid]
            changes.append({
                "follow_uid": fuid,
                "nickname": user.get("nickname", ""),
                "avatar": user.get("avatarUrl", ""),
                "signature": user.get("signature", ""),
                "change_type": "new_follow",
                "time_range": time_range,
            })

        for fuid in unfollows:
            user = previous_detail.get(fuid, {})
            changes.append({
                "follow_uid": fuid,
                "nickname": user.get("nickname", "已取关用户"),
                "avatar": user.get("avatarUrl", ""),
                "signature": user.get("signature", ""),
                "change_type": "unfollow",
                "time_range": time_range,
            })

        return {
            "has_data": True,
            "latest_time": latest_time,
            "previous_time": previous_time,
            "snapshots_count": len(rows),
            "changes": changes,
        }

    # ==================== 歌单/内容列表变化检测 ====================

    def detect_playlist_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比最近两次 playlists 快照，检测新增的歌单/收藏夹。

        Returns:
            {
                has_data, latest_time, previous_time,
                changes: [{item_id, title, creator, change_type, time_range}, ...]
            }
            change_type: "new_playlist" | "removed_playlist"
        """
        rows = self._connect().execute(
            "SELECT data_json, created_at FROM snapshots "
            "WHERE platform=? AND uid=? AND data_type='playlists' "
            "ORDER BY created_at DESC, id DESC LIMIT 2",
            (platform, uid),
        ).fetchall()

        if len(rows) < 2:
            return {
                "has_data": len(rows) > 0,
                "changes": [],
                "snapshots_count": len(rows),
            }

        latest_data = json.loads(rows[0]["data_json"])
        previous_data = json.loads(rows[1]["data_json"])
        latest_time = rows[0]["created_at"]
        previous_time = rows[1]["created_at"]

        latest_items = latest_data.get("items", [])
        previous_items = previous_data.get("items", [])

        # 用 item_id 建立索引
        latest_ids = {str(it.get("item_id", it.get("id", ""))) for it in latest_items}
        previous_ids = {str(it.get("item_id", it.get("id", ""))) for it in previous_items}

        latest_detail = {str(it.get("item_id", it.get("id", ""))): it for it in latest_items}
        previous_detail = {str(it.get("item_id", it.get("id", ""))): it for it in previous_items}

        new_playlists = latest_ids - previous_ids
        removed = previous_ids - latest_ids

        changes = []
        time_range = {"since": previous_time, "until": latest_time}

        for pid in new_playlists:
            item = latest_detail[pid]
            changes.append({
                "item_id": pid,
                "title": item.get("title", item.get("name", "")),
                "creator": item.get("creator", ""),
                "cover_url": item.get("cover_url", item.get("coverImgUrl", "")),
                "is_owner": item.get("is_owner", True),
                "change_type": "new_playlist",
                "time_range": time_range,
            })

        for pid in removed:
            item = previous_detail.get(pid, {})
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
            "has_data": True,
            "latest_time": latest_time,
            "previous_time": previous_time,
            "snapshots_count": len(rows),
            "changes": changes,
        }

    # ==================== 歌单歌曲变化检测 ====================

    def detect_playlist_song_changes(
        self, platform: str, uid: str
    ) -> dict:
        """
        对比最近两次 playlist_songs 快照，检测歌单内歌曲增减。

        Returns:
            changes: [{
                playlist_id, playlist_title,
                song_id, song_title, artist,
                change_type: "song_added" | "song_removed",
                time_range: {since, until}
            }, ...]
        """
        rows = self._connect().execute(
            "SELECT data_json, created_at FROM snapshots "
            "WHERE platform=? AND uid=? AND data_type='playlist_songs' "
            "ORDER BY created_at DESC, id DESC LIMIT 2",
            (platform, uid),
        ).fetchall()

        if len(rows) < 2:
            return {"has_data": len(rows) > 0, "changes": [], "snapshots_count": len(rows)}

        latest_data = json.loads(rows[0]["data_json"])
        previous_data = json.loads(rows[1]["data_json"])
        latest_time = rows[0]["created_at"]
        previous_time = rows[1]["created_at"]

        # 跳过仍在拉取中的快照
        if latest_data.get("fetching") or previous_data.get("fetching"):
            return {"has_data": True, "changes": [], "snapshots_count": len(rows),
                    "skipped": "fetching_in_progress"}

        latest_pls = latest_data.get("playlists", {})
        previous_pls = previous_data.get("playlists", {})

        changes = []
        time_range = {"since": previous_time, "until": latest_time}

        for pl_id, pl_info in latest_pls.items():
            prev_info = previous_pls.get(pl_id, {})
            latest_songs = {s.get("id", ""): s for s in pl_info.get("songs", [])}
            prev_songs = {s.get("id", ""): s for s in prev_info.get("songs", [])}

            new_ids = set(latest_songs.keys()) - set(prev_songs.keys())
            removed_ids = set(prev_songs.keys()) - set(latest_songs.keys())

            for sid in new_ids:
                song = latest_songs[sid]
                changes.append({
                    "playlist_id": pl_id,
                    "playlist_title": pl_info.get("title", ""),
                    "song_id": sid,
                    "song_title": song.get("title", ""),
                    "artist": song.get("artist", ""),
                    "change_type": "song_added",
                    "time_range": time_range,
                })

            for sid in removed_ids:
                song = prev_songs.get(sid, {})
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
            "has_data": True,
            "latest_time": latest_time,
            "previous_time": previous_time,
            "snapshots_count": len(rows),
            "changes": changes,
        }
