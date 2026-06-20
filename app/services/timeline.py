"""
统一活动时间线服务

将多个平台的数据合并为按时间排序的统一活动日志。
- 动态使用精确时间戳
- 听歌/观看记录通过快照对比推断时间范围
- 无变化的记录标注为"时间未知"
"""
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
    platform_name: str = ""         # 平台中文名
    event_type: str = ""            # 活动类型
    summary: str = ""               # 一句话摘要
    detail: str = ""                # 详细信息
    time_str: str = ""              # 人类可读时间
    time_suffix: str = ""           # 时间标注（如 "约10:30"、"时间未知"、"10:00~10:30"）
    time_range: dict = field(default_factory=dict)  # {since, until} 或 None
    raw: dict = field(default_factory=dict)          # 原始数据


class TimelineBuilder:
    """多平台活动时间线构建器"""

    PLATFORM_NAME_MAP = {
        "netease": "网易云音乐",
        "bilibili": "哔哩哔哩",
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
            platform_count = 0  # 该平台添加到时间线的条目数

            # ---- 动态：优先从快照读取，避免频繁调用API触发频率限制 ----
            try:
                # 获取最近的2个快照，用第一个有数据的
                all_event_snaps = store.get_snapshots(platform_id, uid, "events", limit=2)
                print(f"[Timeline] {platform_id}:{uid} events 快照数={len(all_event_snaps)}")
                events_snap = None
                for snap in all_event_snaps:
                    if snap.get("items"):
                        events_snap = snap
                        break

                if events_snap and events_snap.get("items"):
                    # 从快照读取
                    event_count = 0
                    for ev_data in events_snap["items"]:
                        ts = ev_data.get("timestamp", 0) or 0
                        time_str = ""
                        if ts and ts > 0:
                            try:
                                dt = datetime.fromtimestamp(ts / 1000, CST)
                                time_str = dt.strftime("%Y.%m.%d %H:%M")
                            except (OSError, OverflowError, ValueError):
                                time_str = ""  # 无效时间戳
                        entries.append(TimelineEntry(
                            timestamp=ts if ts > 0 else 0,
                            platform=platform_id,
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
                    # 快照不存在，实时获取
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

            # ---- 内容发布：从快照读取（B站投稿等）----
            try:
                all_content_snaps = store.get_snapshots(platform_id, uid, "playlists", limit=2)
                print(f"[Timeline] {platform_id}:{uid} playlists 快照数={len(all_content_snaps)}")
                content_snap = None
                for snap in all_content_snaps:
                    if snap.get("items"):
                        content_snap = snap
                        break

                if content_snap and content_snap.get("items"):
                    added = 0
                    for item in content_snap["items"][:10]:
                        ts = 0
                        create_time = item.get("create_time", "")
                        if create_time and create_time.isdigit():
                            ts = int(create_time) * 1000
                        time_str = ""
                        if ts and ts > 0:
                            try:
                                dt = datetime.fromtimestamp(ts / 1000, CST)
                                time_str = dt.strftime("%Y.%m.%d %H:%M")
                            except (OSError, OverflowError, ValueError):
                                time_str = ""

                        title = item.get("title", item.get("name", ""))
                        view_count = item.get("view_count", item.get("playCount", 0))
                        summary = f"[{pname}] 发布了《{title}》"
                        detail = f"播放 {view_count} 次" if view_count else ""

                        entries.append(TimelineEntry(
                            timestamp=ts,
                            platform=platform_id,
                            platform_name=pname,
                            event_type="发布内容",
                            summary=summary,
                            detail=detail,
                            time_str=time_str,
                            time_suffix="",
                            raw={"type": "content", "data": item},
                        ))
                        added += 1
                    platform_count += added
                    print(f"[Timeline] {platform_id}:{uid} 内容加入 {added} 条")
                else:
                    print(f"[Timeline] {platform_id}:{uid} 内容快照无数据")
            except Exception as e:
                print(f"[Timeline] {platform_id} 内容获取失败: {e}")

            # ---- 听歌/观看记录（快照对比推断时间）----
            if platform_id == "netease":  # 目前只有网易云有听歌记录
                try:
                    record_changes = store.detect_record_changes(platform_id, uid)

                    if record_changes.get("has_data"):
                        inferred = []
                        unknown = []
                        for ch in record_changes["changes"]:
                            entry = cls._build_record_entry(platform_id, pname, ch)
                            if entry.time_suffix == "时间未知":
                                unknown.append(entry)
                            else:
                                inferred.append(entry)

                        cls._quicksort(unknown, key=lambda e: e.raw.get("data", {}).get("new_count", 0), reverse=True)
                        entries.extend(inferred)
                        entries.extend(unknown[:10])
                        platform_count += len(inferred) + min(len(unknown), 10)
                        print(f"[Timeline] {platform_id}:{uid} 听歌记录加入 {len(inferred)} 条推断 + {min(len(unknown), 10)} 条未知")
                except Exception as e:
                    print(f"[Timeline] {platform_id} 记录对比失败: {e}")

            print(f"[Timeline] {platform_id}:{uid} 本平台共加入 {platform_count} 条")

        print(f"[Timeline] 合计 {len(entries)} 条，来自 {list(platform_uids.keys())}")

        # 快排：按时间倒序排列（时间未知的排最后）
        cls._quicksort(entries, key=lambda e: (0 if e.timestamp else 1, -e.timestamp))
        return entries

    @classmethod
    def _build_record_entry(
        cls, platform: str, pname: str, change: dict
    ) -> TimelineEntry:
        """根据一条记录变化构建时间线条目"""
        song_name = change.get("song_name", "")
        artist = change.get("artist", "")
        change_type = change.get("change_type", "unchanged")
        delta = change.get("delta", 0)
        new_count = change.get("new_count", 0)
        time_range = change.get("time_range")
        period = change.get("period", "all")

        period_label = "周榜" if period == "week" else ""

        if change_type == "unchanged" or time_range is None:
            # 时间未知
            timestamp = 0
            time_str = ""
            time_suffix = "时间未知"

            if change_type == "unchanged" and new_count > 0:
                detail = f"已听 {new_count} 次"
            elif change_type == "unchanged":
                detail = ""
            else:
                detail = ""

            summary = f"[{pname}] {period_label}在听《{song_name}》"
            if artist:
                summary += f" - {artist}"

        else:
            # 可推断时间范围
            since_str = time_range.get("since", "")
            until_str = time_range.get("until", "")

            # 格式化为可读时间
            since_readable = cls._iso_to_readable(since_str)
            until_readable = cls._iso_to_readable(until_str)

            # 取 until 作为排序时间戳
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
            elif change_type == "new_first":
                summary = f"[{pname}] {period_label}在听《{song_name}》"
                detail = f"已听 {new_count} 次（首次采集，无法推断开始时间）"
            elif change_type == "increased":
                summary = f"[{pname}] {period_label}又在听《{song_name}》"
                detail = f"播放 +{delta} 次（共 {new_count} 次）"
            else:
                summary = f"[{pname}] {period_label}在听《{song_name}》"
                detail = f"已听 {new_count} 次"

            if artist:
                summary += f" - {artist}"

        return TimelineEntry(
            timestamp=timestamp,
            platform=platform,
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
    def _iso_to_readable(cls, iso_str: str) -> str:
        """ISO 时间 → 可读格式（月.日 时:分）"""
        if not iso_str:
            return ""
        try:
            dt = datetime.fromisoformat(iso_str)
            # 转为北京时间
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=CST)
            else:
                dt = dt.astimezone(CST)
            return dt.strftime("%m.%d %H:%M")
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
            elif entry.time_suffix == "时间未知":
                time_part = "----.--.--"
            else:
                time_part = entry.time_suffix

            line = f"{time_part}  {entry.summary}"
            if entry.detail:
                line += f"（{entry.detail}）"
            if entry.time_suffix and entry.time_suffix not in ("时间未知",):
                line += f"  [{entry.time_suffix}]"
            elif entry.time_suffix == "时间未知":
                line += "  [时间未知]"
            lines.append(line)
        return "\n".join(lines)

    @classmethod
    def build_log_markdown(cls, entries: list[TimelineEntry]) -> str:
        """将时间线转为 Markdown 格式"""
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        lines = ["# 📊 多平台活动时间线", "", f"生成时间: {now}", ""]
        for entry in entries:
            icon = {"netease": "🎵", "bilibili": "📺"}.get(entry.platform, "📌")
            if entry.time_str:
                time_part = f"**{entry.time_str}**"
            elif entry.time_suffix == "时间未知":
                time_part = "**时间未知**"
            else:
                time_part = f"**{entry.time_suffix}**"

            line = f"- {time_part} {icon} {entry.summary}"
            if entry.detail:
                line += f"（{entry.detail}）"
            if entry.time_suffix and entry.time_suffix not in ("时间未知", ""):
                line += f" _{entry.time_suffix}_"
            elif entry.time_suffix == "时间未知":
                line += " _时间未知_"
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
