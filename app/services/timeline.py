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
from app.platforms.base import dataclass_to_dict

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
        "qqmusic": "QQ音乐",
        "weibo": "微博",
        "genshin": "原神",
    }

    # 各平台内容类型标签
    CONTENT_TYPE_MAP = {
        "netease": "歌单",
        "bilibili": "视频",
        "douyin": "作品",
        "qqmusic": "歌单",
        "weibo": "微博",
        "genshin": "角色",
    }

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
                                raw={"type": "event", "data": dataclass_to_dict(ev)},
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

                        inferred.sort(key=lambda e: e.timestamp, reverse=True)
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

            print(f"[Timeline] {platform_id}:{uid} 本平台共加入 {platform_count} 条")

        print(f"[Timeline] 合计 {len(entries)} 条，来自 {list(platform_uids.keys())}")

        # 按时间戳倒序排列
        entries.sort(key=lambda e: e.timestamp, reverse=True)
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

    # 关注/粉丝/内容列表变化的通用构建配置
    _SET_ENTRY_SPECS = {
        "follow": {
            "event_type": "关注变化", "raw_type": "follow_change", "field": "nickname",
            "summaries": {"new_follow": "关注了 {x}", "unfollow": "取关了 {x}"},
            "fallback": "关注变化: {x}",
        },
        "follower": {
            "event_type": "粉丝变化", "raw_type": "follower_change", "field": "nickname",
            "summaries": {"new_follower": "被 {x} 关注", "lost_follower": "{x} 取消了关注"},
            "fallback": "粉丝变化: {x}",
        },
        "playlist": {
            "event_type": "内容变化", "raw_type": "playlist_change", "field": "title",
        },
    }

    @classmethod
    def _playlist_action(cls, platform: str, change_type: str, is_owner: bool) -> str:
        """按平台定制内容变化的动作描述"""
        verbs = {"netease": "歌单", "bilibili": "视频", "douyin": "作品"}
        noun = verbs.get(platform, "")
        if change_type == "removed_playlist":
            return ("移除了歌单" if platform == "netease" else
                    f"删除了{noun}" if noun else "删除了")
        return (f"{'创建了' if is_owner else '收藏了'}歌单" if platform == "netease"
                else f"{'发布了' if is_owner else '收藏了'}{noun}" if noun else "新增了")

    @classmethod
    def _build_set_entry(
        cls, kind: str, platform: str, uid: str, pname: str, change: dict
    ) -> TimelineEntry:
        """通用集合类变化条目构建：取 until 时间为事件时间，拼装动作摘要"""
        spec = cls._SET_ENTRY_SPECS[kind]
        change_type = change.get("change_type", "")
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

        x = change.get(spec["field"], "")
        if kind == "playlist":
            action = cls._playlist_action(platform, change_type or "new_playlist", change.get("is_owner", True))
            summary = f"[{pname}] {action}《{x}》"
        else:
            template = spec["summaries"].get(change_type, spec["fallback"])
            summary = f"[{pname}] " + template.format(x=x)

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
            uid=uid,
            platform_name=pname,
            event_type=spec["event_type"],
            summary=summary,
            detail="",
            time_str=time_str,
            time_suffix=time_suffix,
            time_range=time_range or {},
            raw={"type": spec["raw_type"], "data": change},
        )

    @classmethod
    def _build_follow_entry(cls, platform, uid, pname, change):
        """根据关注变化构建时间线条目"""
        return cls._build_set_entry("follow", platform, uid, pname, change)

    @classmethod
    def _build_follower_entry(cls, platform, uid, pname, change):
        """根据粉丝变化构建时间线条目"""
        return cls._build_set_entry("follower", platform, uid, pname, change)

    @classmethod
    def _build_playlist_entry(cls, platform, uid, pname, change):
        """根据歌单/内容列表变化构建时间线条目"""
        return cls._build_set_entry("playlist", platform, uid, pname, change)

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
            icon = {"netease": "🎵", "bilibili": "📺", "douyin": "🎶", "qqmusic": "🎵", "weibo": "💬", "genshin": "⚔️"}.get(entry.platform, "📌")
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


