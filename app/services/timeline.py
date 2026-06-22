"""
统一活动时间线服务

将多个平台的数据合并为按时间排序的统一活动日志。
- 动态使用精确时间戳
- 听歌/观看记录通过快照对比推断时间范围
- 无变化的记录标注为"时间未知"
"""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

from app.platforms import get_adapter
from app.data.store import DataStore

CST = timezone(timedelta(hours=8))


@dataclass
class TimelineEntry:
    """时间线条目"""
    timestamp: int = 0              # Unix 毫秒时间戳；0 = 时间未知
    platform: str = ""              # 平台标识
    uid: str = ""                   # 用户 ID
    platform_name: str = ""         # 平台中文名
    event_type: str = ""            # 活动类型
    summary: str = ""               # 一句话摘要
    detail: str = ""                # 详细信息
    time_str: str = ""              # 人类可读时间
    time_suffix: str = ""           # 时间标注（如 "约10:30"、"时间未知"、"10:00~10:30"）
    time_range: dict = field(default_factory=dict)  # {since, until} 或 None
    raw: dict = field(default_factory=dict)          # 原始数据

    def dedup_key(self) -> str:
        """
        生成去重键，用于防止时间线中重复加入同一事件。
        基于事件的平台、用户、类型及具体业务字段组合生成唯一标识。
        """
        raw_type = self.raw.get("type", "")
        data = self.raw.get("data", {}) or {}

        if raw_type == "event":
            # 动态（直接获取）：基于 timestamp + event_type + content 的哈希
            ts = data.get("timestamp", 0)
            ev_type = data.get("event_type", "")
            content = data.get("content", "")
            fingerprint = f"{ts}:{ev_type}:{content}"
            h = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
            return f"{self.platform}:{self.uid}:event:{h}"

        elif raw_type == "content":
            # 发布内容
            item_id = data.get("item_id", data.get("id", ""))
            create_time = data.get("create_time", "")
            return f"{self.platform}:{self.uid}:content:{item_id}:{create_time}"

        elif raw_type == "record_change":
            song_id = data.get("song_id", "")
            change_type = data.get("change_type", "")
            period = data.get("period", "")
            tr = data.get("time_range", {}) or {}
            since = tr.get("since", "")
            until = tr.get("until", "")
            return f"{self.platform}:{self.uid}:record:{song_id}:{change_type}:{period}:{since}:{until}"

        elif raw_type == "follow_change":
            follow_uid = data.get("follow_uid", "")
            change_type = data.get("change_type", "")
            tr = data.get("time_range", {}) or {}
            since = tr.get("since", "")
            until = tr.get("until", "")
            return f"{self.platform}:{self.uid}:follow:{follow_uid}:{change_type}:{since}:{until}"

        elif raw_type == "follower_change":
            follower_uid = data.get("follower_uid", "")
            change_type = data.get("change_type", "")
            tr = data.get("time_range", {}) or {}
            since = tr.get("since", "")
            until = tr.get("until", "")
            return f"{self.platform}:{self.uid}:follower:{follower_uid}:{change_type}:{since}:{until}"

        elif raw_type == "playlist_change":
            item_id = data.get("item_id", "")
            change_type = data.get("change_type", "")
            tr = data.get("time_range", {}) or {}
            since = tr.get("since", "")
            until = tr.get("until", "")
            return f"{self.platform}:{self.uid}:playlist:{item_id}:{change_type}:{since}:{until}"

        elif raw_type == "song_change":
            playlist_id = data.get("playlist_id", "")
            song_id = data.get("song_id", "")
            change_type = data.get("change_type", "")
            tr = data.get("time_range", {}) or {}
            since = tr.get("since", "")
            until = tr.get("until", "")
            return f"{self.platform}:{self.uid}:song_change:{playlist_id}:{song_id}:{change_type}:{since}:{until}"

        else:
            # 兜底：对整个 raw 做哈希
            raw_str = json.dumps(self.raw, sort_keys=True, ensure_ascii=False)
            h = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]
            return f"{self.platform}:{self.uid}:unknown:{h}"


class TimelineBuilder:
    """多平台活动时间线构建器"""

    PLATFORM_NAME_MAP = {
        "netease": "网易云音乐",
        "bilibili": "哔哩哔哩",
        "douyin": "抖音",
    }

    # 各平台内容类型标签
    CONTENT_TYPE_MAP = {
        "netease": "歌单",
        "bilibili": "视频",
        "douyin": "作品",
    }

    @staticmethod
    def _quicksort(arr: list, key, reverse: bool = False):
        """三路快排，按 key 函数取值排序。稳定 O(n log n)，原地操作。"""
        if len(arr) <= 1:
            return arr

        import random
        pivot = key(random.choice(arr))
        lt, eq, gt = [], [], []
        for item in arr:
            k = key(item)
            if k < pivot:
                lt.append(item)
            elif k > pivot:
                gt.append(item)
            else:
                eq.append(item)

        TimelineBuilder._quicksort(lt, key, reverse)
        TimelineBuilder._quicksort(gt, key, reverse)

        if reverse:
            arr[:] = gt + eq + lt
        else:
            arr[:] = lt + eq + gt
        return arr

    @classmethod
    def build(
        cls,
        platform_uids: dict[str, str],
        limit_per_platform: int = 30,
        store: DataStore = None,
    ) -> list[TimelineEntry]:
        """
        构建统一时间线。
        对听歌记录使用快照对比推断时间。
        """
        entries: list[TimelineEntry] = []
        if store is None:
            store = DataStore()

        for platform_id, uid in platform_uids.items():
            if not uid:
                continue

            adapter = get_adapter(platform_id)
            if not adapter:
                continue

            pname = cls.PLATFORM_NAME_MAP.get(platform_id, platform_id)
            content_label = cls.CONTENT_TYPE_MAP.get(platform_id, "内容")
            platform_count = 0  # 该平台添加到时间线的条目数

            # ---- 动态事件（非抖音：抖音作品由内容列表处理，避免重复）----
            if platform_id == "douyin":
                print(f"[Timeline] douyin: 跳过动态（由内容列表代替）")
            else:
                try:
                    all_event_snaps = store.get_snapshots(platform_id, uid, "events", limit=2)
                    print(f"[Timeline] {platform_id}:{uid} events 快照数={len(all_event_snaps)}")
                    events_snap = None
                    for snap in all_event_snaps:
                        if snap.get("items"):
                            events_snap = snap
                            break

                    if events_snap and events_snap.get("items"):
                        event_count = 0
                        for ev_data in events_snap["items"]:
                            ts = ev_data.get("timestamp", 0) or 0
                            time_str = ""
                            if ts and ts > 0:
                                try:
                                    dt = datetime.fromtimestamp(ts / 1000, CST)
                                    time_str = dt.strftime("%Y.%m.%d %H:%M")
                                except (OSError, OverflowError, ValueError):
                                    time_str = ""
                            entries.append(TimelineEntry(
                                timestamp=ts if ts > 0 else 0,
                                platform=platform_id,
                                uid=uid,
                                platform_name=pname,
                                event_type=ev_data.get("event_type", "动态"),
                                summary=cls._summarize_snapshot_event(pname, ev_data),
                                detail=ev_data.get("content", ""),
                                time_str=time_str,
                                time_suffix="",
                                raw={"type": "event", "data": ev_data},
                            ))
                            event_count += 1
                        platform_count += event_count
                        print(f"[Timeline] {platform_id}:{uid} 动态加入 {event_count} 条（快照）")
                    else:
                        events = adapter.get_events(uid, limit=limit_per_platform)
                        event_count = 0
                        for ev in events:
                            ts = ev.timestamp
                            time_str = ""
                            if ts and ts > 0:
                                try:
                                    dt = datetime.fromtimestamp(ts / 1000, CST)
                                    time_str = dt.strftime("%Y.%m.%d %H:%M")
                                except (OSError, OverflowError, ValueError):
                                    time_str = ""
                            entries.append(TimelineEntry(
                                timestamp=ts,
                                platform=platform_id,
                                uid=uid,
                                platform_name=pname,
                                event_type=ev.event_type,
                                summary=cls._summarize_event(pname, ev),
                                detail=ev.content,
                                time_str=time_str,
                                time_suffix="",
                                raw={"type": "event", "data": _to_dict(ev)},
                            ))
                            event_count += 1
                        platform_count += event_count
                        print(f"[Timeline] {platform_id}:{uid} 动态加入 {event_count} 条（实时）")
                except Exception as e:
                    print(f"[Timeline] {platform_id} 动态获取失败: {e}")

            # ---- 内容发布（歌单/视频/作品）：从快照读取，无快照时实时拉取 ----
            try:
                all_content_snaps = store.get_snapshots(platform_id, uid, "playlists", limit=2)
                print(f"[Timeline] {platform_id}:{uid} playlists 快照数={len(all_content_snaps)}")
                content_snap = None
                for snap in all_content_snaps:
                    if snap.get("items"):
                        content_snap = snap
                        break

                if content_snap and content_snap.get("items"):
                    # 从快照读取
                    added = 0
                    for item in content_snap["items"][:10]:
                        ts = 0
                        create_time = item.get("create_time", "")
                        if create_time and create_time.isdigit():
                            raw_ts = int(create_time)
                            if raw_ts > 1000000000000:
                                ts = raw_ts
                            else:
                                ts = raw_ts * 1000
                        time_str = ""
                        if ts and ts > 0:
                            try:
                                dt = datetime.fromtimestamp(ts / 1000, CST)
                                time_str = dt.strftime("%Y.%m.%d %H:%M")
                            except (OSError, OverflowError, ValueError):
                                time_str = ""

                        title = item.get("title", item.get("name", ""))
                        view_count = item.get("view_count", item.get("playCount", 0))
                        summary = f"[{pname}] 发布了{content_label}《{title}》"
                        detail = f"播放 {view_count} 次" if view_count else ""

                        entries.append(TimelineEntry(
                            timestamp=ts,
                            platform=platform_id,
                            uid=uid,
                            platform_name=pname,
                            event_type=f"发布{content_label}",
                            summary=summary,
                            detail=detail,
                            time_str=time_str,
                            time_suffix="",
                            raw={"type": "content", "data": item},
                        ))
                        added += 1
                    platform_count += added
                    print(f"[Timeline] {platform_id}:{uid} 内容加入 {added} 条（快照）")
                else:
                    # 快照不存在，实时获取（对抖音等平台首次使用时无快照）
                    try:
                        items = adapter.get_content_lists(uid)
                        if items:
                            added = 0
                            for item in items[:10]:
                                ts = 0
                                create_time = item.create_time
                                if create_time and create_time.isdigit():
                                    raw_ts = int(create_time)
                                    if raw_ts > 1000000000000:
                                        ts = raw_ts
                                    else:
                                        ts = raw_ts * 1000
                                time_str = ""
                                if ts and ts > 0:
                                    try:
                                        dt = datetime.fromtimestamp(ts / 1000, CST)
                                        time_str = dt.strftime("%Y.%m.%d %H:%M")
                                    except (OSError, OverflowError, ValueError):
                                        time_str = ""

                                title = item.title or ""
                                view_count = item.view_count or 0
                                summary = f"[{pname}] 发布了{content_label}《{title}》"
                                detail = f"播放 {view_count} 次" if view_count else ""

                                entries.append(TimelineEntry(
                                    timestamp=ts,
                                    platform=platform_id,
                                    uid=uid,
                                    platform_name=pname,
                                    event_type=f"发布{content_label}",
                                    summary=summary,
                                    detail=detail,
                                    time_str=time_str,
                                    time_suffix="",
                                    raw={"type": "content", "data": {
                                        "item_id": item.item_id,
                                        "title": item.title,
                                        "create_time": item.create_time,
                                        "view_count": item.view_count,
                                        "cover_url": item.cover_url,
                                        "creator": item.creator,
                                    }},
                                ))
                                added += 1
                            platform_count += added
                            print(f"[Timeline] {platform_id}:{uid} 内容加入 {added} 条（实时）")
                        else:
                            print(f"[Timeline] {platform_id}:{uid} 内容实时拉取为空")
                    except Exception as e:
                        print(f"[Timeline] {platform_id}:{uid} 内容实时拉取失败: {e}")
            except Exception as e:
                print(f"[Timeline] {platform_id} 内容获取失败: {e}")

            # ---- 听歌/观看记录（快照对比推断时间）----
            if platform_id == "netease":
                try:
                    record_changes = store.detect_record_changes(platform_id, uid)

                    if record_changes.get("has_data"):
                        inferred = []
                        for ch in record_changes["changes"]:
                            entry = cls._build_record_entry(platform_id, uid, pname, ch)
                            if entry.time_range:
                                inferred.append(entry)

                        cls._quicksort(inferred, key=lambda e: e.timestamp, reverse=True)
                        entries.extend(inferred)
                        platform_count += len(inferred)
                        print(f"[Timeline] {platform_id}:{uid} 听歌记录加入 {len(inferred)} 条")
                except Exception as e:
                    print(f"[Timeline] {platform_id} 记录对比失败: {e}")

            # ---- 关注变化（快照对比推断，所有平台通用）----
            try:
                follow_changes = store.detect_follow_changes(platform_id, uid)
                if follow_changes.get("has_data") and follow_changes["changes"]:
                    fc_added = 0
                    for fc in follow_changes["changes"]:
                        entry = cls._build_follow_entry(platform_id, uid, pname, fc)
                        entries.append(entry)
                        fc_added += 1
                    platform_count += fc_added
                    print(f"[Timeline] {platform_id}:{uid} 关注变化加入 {fc_added} 条")
            except Exception as e:
                print(f"[Timeline] {platform_id} 关注检测失败: {e}")

            # ---- 粉丝变化（快照对比推断，所有平台通用）----
            try:
                follower_changes = store.detect_follower_changes(platform_id, uid)
                if follower_changes.get("has_data") and follower_changes["changes"]:
                    fcr_added = 0
                    for fc in follower_changes["changes"]:
                        entry = cls._build_follower_entry(platform_id, uid, pname, fc)
                        entries.append(entry)
                        fcr_added += 1
                    platform_count += fcr_added
                    print(f"[Timeline] {platform_id}:{uid} 粉丝变化加入 {fcr_added} 条")
            except Exception as e:
                print(f"[Timeline] {platform_id} 粉丝检测失败: {e}")

            # ---- 作品/内容列表变化（快照对比推断，所有平台通用）----
            try:
                pl_changes = store.detect_playlist_changes(platform_id, uid)
                if pl_changes.get("has_data") and pl_changes["changes"]:
                    pl_added = 0
                    for pc in pl_changes["changes"]:
                        entry = cls._build_playlist_entry(platform_id, uid, pname, pc)
                        entries.append(entry)
                        pl_added += 1
                    platform_count += pl_added
                    print(f"[Timeline] {platform_id}:{uid} {content_label}变化加入 {pl_added} 条")
            except Exception as e:
                print(f"[Timeline] {platform_id} 作品检测失败: {e}")

            # ---- 歌单内歌曲变化（快照对比推断）----
            try:
                song_changes = store.detect_playlist_song_changes(platform_id, uid)
                if song_changes.get("has_data") and song_changes["changes"]:
                    sc_added = 0
                    for sc in song_changes["changes"]:
                        entry = cls._build_song_change_entry(platform_id, uid, pname, sc)
                        entries.append(entry)
                        sc_added += 1
                    platform_count += sc_added
                    print(f"[Timeline] {platform_id}:{uid} 歌单歌曲变化加入 {sc_added} 条")
            except Exception as e:
                print(f"[Timeline] {platform_id} 歌曲变化检测失败: {e}")

            print(f"[Timeline] {platform_id}:{uid} 本平台共加入 {platform_count} 条")

        print(f"[Timeline] 合计 {len(entries)} 条，来自 {list(platform_uids.keys())}")

        # 按时间戳倒序排列
        cls._quicksort(entries, key=lambda e: e.timestamp, reverse=True)
        return entries

    @classmethod
    def _build_record_entry(
        cls, platform: str, uid: str, pname: str, change: dict
    ) -> TimelineEntry:
        """根据一条记录变化构建时间线条目"""
        song_name = change.get("song_name", "")
        artist = change.get("artist", "")
        change_type = change.get("change_type", "ongoing")
        delta = change.get("delta", 0)
        new_count = change.get("new_count", 0)
        time_range = change.get("time_range")
        first_seen_time = change.get("first_seen_time", "")
        first_seen_range = change.get("first_seen_range")
        period = change.get("period", "all")

        period_label = "周榜" if period == "week" else ""

        if time_range:
            since_str = time_range.get("since", "")
            until_str = time_range.get("until", "")

            since_readable = cls._iso_to_readable(since_str)
            until_readable = cls._iso_to_readable(until_str)

            try:
                dt_until = datetime.fromisoformat(until_str)
                timestamp = int(dt_until.timestamp() * 1000)
                time_str = until_readable or until_str
            except (ValueError, TypeError):
                timestamp = 0
                time_str = ""

            if since_readable and until_readable:
                time_suffix = f"{since_readable} ~ {until_readable}"
            elif until_readable:
                time_suffix = f"≈ {until_readable}"
            else:
                time_suffix = "时间未知"

            if change_type == "new":
                summary = f"[{pname}] {period_label}开始听《{song_name}》"
                detail = f"首次出现，已听 {new_count} 次"
            elif change_type == "increased":
                summary = f"[{pname}] {period_label}又在听《{song_name}》"
                detail = f"播放 +{delta} 次（共 {new_count} 次）"
            else:
                summary = f"[{pname}] {period_label}在听《{song_name}》"
                detail = f"已听 {new_count} 次"
        else:
            timestamp = 0
            time_str = ""

            if change_type == "ongoing":
                ongoing_since = cls._iso_to_readable(first_seen_time)
                if ongoing_since:
                    time_suffix = f"⏳ 至少从 {ongoing_since} 开始"
                else:
                    time_suffix = "持续在听"
                summary = f"[{pname}] {period_label}持续在听《{song_name}》"
                detail = f"已听 {new_count} 次"
                if first_seen_time:
                    try:
                        dt_first = datetime.fromisoformat(first_seen_time)
                        timestamp = int(dt_first.timestamp() * 1000)
                        time_str = ongoing_since
                    except (ValueError, TypeError):
                        pass

            elif change_type == "first_seen":
                first_seen_readable = cls._iso_to_readable(first_seen_time)
                if first_seen_readable:
                    time_suffix = f"⏳ 首次检测于 {first_seen_readable}"
                else:
                    time_suffix = "首次检测"
                summary = f"[{pname}] {period_label}在听《{song_name}》"
                detail = f"已听 {new_count} 次" if new_count > 0 else ""
                if first_seen_time:
                    try:
                        dt_first = datetime.fromisoformat(first_seen_time)
                        timestamp = int(dt_first.timestamp() * 1000)
                        time_str = first_seen_readable
                    except (ValueError, TypeError):
                        pass

            elif change_type == "new_first":
                time_suffix = "首次采集"
                summary = f"[{pname}] {period_label}在听《{song_name}》"
                detail = f"已听 {new_count} 次（首次采集，无法推断开始时间）"

            else:
                time_suffix = "时间未知"
                summary = f"[{pname}] {period_label}在听《{song_name}》"
                detail = f"已听 {new_count} 次" if new_count > 0 else ""

        if artist:
            summary += f" - {artist}"

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
            uid=uid,
            platform_name=pname,
            event_type="听歌记录",
            summary=summary,
            detail=detail,
            time_str=time_str,
            time_suffix=time_suffix,
            time_range=time_range or {},
            raw={"type": "record_change", "data": change},
        )

    @classmethod
    def _build_follow_entry(
        cls, platform: str, uid: str, pname: str, change: dict
    ) -> TimelineEntry:
        """根据关注变化构建时间线条目"""
        nickname = change.get("nickname", "")
        change_type = change.get("change_type", "new_follow")
        time_range = change.get("time_range")

        since_str = time_range.get("since", "") if time_range else ""
        until_str = time_range.get("until", "") if time_range else ""

        since_readable = cls._iso_to_readable(since_str)
        until_readable = cls._iso_to_readable(until_str)

        try:
            dt_until = datetime.fromisoformat(until_str) if until_str else None
            timestamp = int(dt_until.timestamp() * 1000) if dt_until else 0
            time_str = until_readable
        except (ValueError, TypeError):
            timestamp = 0
            time_str = ""

        time_suffix = f"{since_readable} ~ {until_readable}" if since_readable and until_readable else ""

        if change_type == "new_follow":
            summary = f"[{pname}] 关注了 {nickname}"
            detail = ""
        elif change_type == "unfollow":
            summary = f"[{pname}] 取关了 {nickname}"
            detail = ""
        else:
            summary = f"[{pname}] 关注变化: {nickname}"
            detail = ""

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
            uid=uid,
            platform_name=pname,
            event_type="关注变化",
            summary=summary,
            detail=detail,
            time_str=time_str,
            time_suffix=time_suffix,
            time_range=time_range or {},
            raw={"type": "follow_change", "data": change},
        )

    @classmethod
    def _build_follower_entry(
        cls, platform: str, uid: str, pname: str, change: dict
    ) -> TimelineEntry:
        """根据粉丝变化构建时间线条目"""
        nickname = change.get("nickname", "")
        change_type = change.get("change_type", "new_follower")
        time_range = change.get("time_range")

        since_str = time_range.get("since", "") if time_range else ""
        until_str = time_range.get("until", "") if time_range else ""

        since_readable = cls._iso_to_readable(since_str)
        until_readable = cls._iso_to_readable(until_str)

        try:
            dt_until = datetime.fromisoformat(until_str) if until_str else None
            timestamp = int(dt_until.timestamp() * 1000) if dt_until else 0
            time_str = until_readable
        except (ValueError, TypeError):
            timestamp = 0
            time_str = ""

        time_suffix = f"{since_readable} ~ {until_readable}" if since_readable and until_readable else ""

        if change_type == "new_follower":
            summary = f"[{pname}] 被 {nickname} 关注"
            detail = ""
        elif change_type == "lost_follower":
            summary = f"[{pname}] {nickname} 取消了关注"
            detail = ""
        else:
            summary = f"[{pname}] 粉丝变化: {nickname}"
            detail = ""

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
            uid=uid,
            platform_name=pname,
            event_type="粉丝变化",
            summary=summary,
            detail=detail,
            time_str=time_str,
            time_suffix=time_suffix,
            time_range=time_range or {},
            raw={"type": "follower_change", "data": change},
        )

    @classmethod
    def _build_playlist_entry(
        cls, platform: str, uid: str, pname: str, change: dict
    ) -> TimelineEntry:
        """根据歌单/内容列表变化构建时间线条目"""
        title = change.get("title", "")
        change_type = change.get("change_type", "new_playlist")
        time_range = change.get("time_range")
        is_owner = change.get("is_owner", True)

        since_str = time_range.get("since", "") if time_range else ""
        until_str = time_range.get("until", "") if time_range else ""

        since_readable = cls._iso_to_readable(since_str)
        until_readable = cls._iso_to_readable(until_str)

        try:
            dt_until = datetime.fromisoformat(until_str) if until_str else None
            timestamp = int(dt_until.timestamp() * 1000) if dt_until else 0
            time_str = until_readable
        except (ValueError, TypeError):
            timestamp = 0
            time_str = ""

        time_suffix = f"{since_readable} ~ {until_readable}" if since_readable and until_readable else ""

        # 按平台定制动作描述
        if change_type == "removed_playlist":
            if platform == "netease":
                action = "移除了歌单"
            elif platform == "bilibili":
                action = "删除了视频"
            elif platform == "douyin":
                action = "删除了作品"
            else:
                action = "删除了"
        else:
            if platform == "netease":
                action = "创建了歌单" if is_owner else "收藏了歌单"
            elif platform == "bilibili":
                action = "发布了视频" if is_owner else "收藏了视频"
            elif platform == "douyin":
                action = "发布了作品" if is_owner else "收藏了作品"
            else:
                action = "新增了"

        summary = f"[{pname}] {action}《{title}》"
        detail = ""

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
            uid=uid,
            platform_name=pname,
            event_type="内容变化",
            summary=summary,
            detail=detail,
            time_str=time_str,
            time_suffix=time_suffix,
            time_range=time_range or {},
            raw={"type": "playlist_change", "data": change},
        )

    @classmethod
    def _build_song_change_entry(
        cls, platform: str, uid: str, pname: str, change: dict
    ) -> TimelineEntry:
        """根据歌单内歌曲变化构建时间线条目"""
        playlist_title = change.get("playlist_title", "")
        song_title = change.get("song_title", "")
        artist = change.get("artist", "")
        change_type = change.get("change_type", "song_added")
        time_range = change.get("time_range")

        since_str = time_range.get("since", "") if time_range else ""
        until_str = time_range.get("until", "") if time_range else ""

        since_readable = cls._iso_to_readable(since_str)
        until_readable = cls._iso_to_readable(until_str)

        try:
            dt_until = datetime.fromisoformat(until_str) if until_str else None
            timestamp = int(dt_until.timestamp() * 1000) if dt_until else 0
            time_str = until_readable
        except (ValueError, TypeError):
            timestamp = 0
            time_str = ""

        time_suffix = f"{since_readable} ~ {until_readable}" if since_readable and until_readable else ""

        # 歌单歌曲变化目前只有网易云，用"歌单"为标签
        song_change_label = "歌单"

        if change_type == "song_added":
            summary = f"[{pname}] 在{song_change_label}《{playlist_title}》中加入《{song_title}》"
        elif change_type == "song_removed":
            summary = f"[{pname}] 从{song_change_label}《{playlist_title}》中移除《{song_title}》"
        else:
            summary = f"[{pname}] {song_change_label}《{playlist_title}》变化: {song_title}"

        if artist:
            summary += f" - {artist}"

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
            uid=uid,
            platform_name=pname,
            event_type="歌单歌曲变化",
            summary=summary,
            detail="",
            time_str=time_str,
            time_suffix=time_suffix,
            time_range=time_range or {},
            raw={"type": "song_change", "data": change},
        )

    @classmethod
    def _iso_to_readable(cls, iso_str: str) -> str:
        """ISO 时间 → 可读格式（年.月.日 时:分）"""
        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CST)
            else:
                dt = dt.astimezone(CST)
            return dt.strftime("%Y.%m.%d %H:%M")
        except (ValueError, TypeError):
            return ""

    # ==================== 日志生成 ====================

    @classmethod
    def build_log_text(cls, entries: list[TimelineEntry]) -> str:
        """将时间线转为纯文本日志"""
        lines = []
        for entry in entries:
            if entry.time_str:
                time_part = entry.time_str
            elif entry.time_suffix and entry.time_suffix.startswith("⏳"):
                time_part = entry.time_suffix.replace("⏳ 至少从 ", "").replace(" 开始", "")
            elif entry.time_suffix == "首次采集":
                time_part = "----.--.-- --:--"
            else:
                time_part = entry.time_suffix or "----.--.--"

            line = f"{time_part}  {entry.summary}"
            if entry.detail:
                line += f"（{entry.detail}）"
            if entry.time_suffix and entry.time_suffix not in ("时间未知", ""):
                line += f"  [{entry.time_suffix}]"
            lines.append(line)
        return "\n".join(lines)

    @classmethod
    def build_log_markdown(cls, entries: list[TimelineEntry]) -> str:
        """将时间线转为 Markdown 格式"""
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        lines = ["# 📊 多平台活动时间线", "", f"生成时间: {now}", ""]
        for entry in entries:
            icon = {"netease": "🎵", "bilibili": "📺", "douyin": "🎶"}.get(entry.platform, "📌")
            if entry.time_str:
                time_part = f"**{entry.time_str}**"
            elif entry.time_suffix and entry.time_suffix.startswith("⏳"):
                since = entry.time_suffix.replace("⏳ 至少从 ", "").replace(" 开始", "")
                time_part = f"**{since}**"
            elif entry.time_suffix == "首次采集":
                time_part = "**首次采集**"
            else:
                time_part = f"**{entry.time_suffix or '时间未知'}**"

            line = f"- {time_part} {icon} {entry.summary}"
            if entry.detail:
                line += f"（{entry.detail}）"
            if entry.time_suffix and entry.time_suffix not in ("时间未知", ""):
                line += f" _{entry.time_suffix}_"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _summarize_snapshot_event(platform_name: str, data: dict) -> str:
        """从快照数据生成活动摘要"""
        prefix = f"[{platform_name}]"
        action = data.get("event_type", "动态")
        content_preview = (data.get("content", "") or "")[:100]
        media_title = data.get("media_title", "")
        media_artist = data.get("media_artist", "")

        if media_title and content_preview:
            return f"{prefix} {action}：{content_preview}（《{media_title}》）"
        elif content_preview:
            return f"{prefix} {action}：{content_preview}"
        elif media_title:
            artist_str = f" - {media_artist}" if media_artist else ""
            return f"{prefix} {action}了《{media_title}》{artist_str}"
        else:
            return f"{prefix} {action}"

    @staticmethod
    def _summarize_event(platform_name: str, event) -> str:
        """生成活动摘要"""
        prefix = f"[{platform_name}]"
        action = event.event_type or "动态"
        content_preview = (event.content or "")[:100]

        if event.media_title and event.content:
            return f"{prefix} {action}：{content_preview}（《{event.media_title}》）"
        elif event.content:
            return f"{prefix} {action}：{content_preview}"
        elif event.media_title:
            return f"{prefix} {action}了《{event.media_title}》"
        else:
            return f"{prefix} {action}"


def _to_dict(obj) -> dict:
    """dataclass → dict"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for key in obj.__dataclass_fields__:
            val = getattr(obj, key)
            if hasattr(val, "__dataclass_fields__"):
                result[key] = _to_dict(val)
            elif isinstance(val, list):
                result[key] = [
                    _to_dict(v) if hasattr(v, "__dataclass_fields__") else v
                    for v in val
                ]
            elif isinstance(val, dict):
                result[key] = {
                    k: _to_dict(v) if hasattr(v, "__dataclass_fields__") else v
                    for k, v in val.items()
                }
            else:
                result[key] = val
        return result
    return obj
