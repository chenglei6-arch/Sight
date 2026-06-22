"""
定时自动采集服务

后台定时抓取所有配置平台的用户数据，
自动保存快照 + 生成时间线日志。
"""
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.platforms import get_adapter
from app.data.store import DataStore
from app.services.timeline import TimelineBuilder

CST = timezone(timedelta(hours=8))

# 日志目录
LOG_DIR = Path(__file__).parent.parent.parent / "logs"


class AutoCollector:
    """
    自动采集器

    用法:
        collector = AutoCollector(interval_minutes=30)
        collector.set_targets({"netease": "5012722824", "bilibili": "3493284789881676"})
        collector.start()
    """

    def __init__(self, interval_minutes: int = 30):
        self.interval = interval_minutes * 60  # 转为秒
        self.targets: dict[str, str] = {}      # {platform: uid}
        self._store = DataStore()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_run: dict[str, str] = {}     # {platform: ISO time}
        self._log_entries: list[dict] = []      # 最近生成的日志条目
        self._status = "stopped"

    def set_targets(self, targets: dict[str, str]):
        """设置采集目标 {platform_id: uid}"""
        self.targets = targets

    def start(self):
        """启动定时采集"""
        if self._running:
            return
        self._running = True
        self._status = "running"
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Collector] 已启动，间隔 {self.interval // 60} 分钟")

    def stop(self):
        """停止采集"""
        self._running = False
        self._status = "stopped"
        print("[Collector] 已停止")

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "status": self._status,
            "interval_minutes": self.interval // 60,
            "targets": self.targets,
            "last_run": self._last_run,
            "recent_entries_count": len(self._log_entries),
        }

    def get_recent_logs(self, limit: int = 100) -> list[dict]:
        """获取最近的采集日志"""
        return self._log_entries[-limit:]

    def collect_once(self) -> list[dict]:
        """手动执行一次采集，返回新发现的条目"""
        new_entries = []
        now = datetime.now(CST)
        now_iso = now.isoformat(timespec="seconds")

        for platform_id, uid in self.targets.items():
            if not uid:
                continue

            adapter = get_adapter(platform_id)
            if not adapter:
                continue

            try:
                # 采集用户资料
                profile = adapter.get_profile(uid)
                if profile:
                    data = _to_dict(profile)
                    self._store.save_snapshot(platform_id, uid, "profile", data)

                # 采集动态
                events = adapter.get_events(uid, limit=20)
                if events and len(events) > 0:
                    events_data = {
                        "count": len(events),
                        "items": [_to_dict(e) for e in events],
                    }
                    self._store.save_snapshot(platform_id, uid, "events", events_data)

                # 采集内容列表
                items = adapter.get_content_lists(uid)
                if items and len(items) > 0:
                    items_data = {
                        "count": len(items),
                        "items": [_to_dict(i) for i in items],
                    }
                    self._store.save_snapshot(platform_id, uid, "playlists", items_data)

                # 采集历史
                history = adapter.get_history(uid, "all")
                weekly = adapter.get_history(uid, "week")
                if history or weekly:
                    records_data = {
                        "allTime": [_to_dict(h) for h in history],
                        "weekly": [_to_dict(w) for w in weekly],
                    }
                    self._store.save_snapshot(platform_id, uid, "records", records_data)

                # 采集关注列表
                follows = []
                try:
                    follows = adapter.get_follows(uid)
                    if follows:
                        follows_data = {
                            "count": len(follows),
                            "items": follows,
                        }
                        self._store.save_snapshot(platform_id, uid, "follows", follows_data)
                except Exception as e:
                    print(f"[Collector] {platform_id}:{uid} 关注采集失败: {e}")

                # 采集粉丝列表
                followers = []
                try:
                    followers = adapter.get_followers(uid)
                    if followers:
                        followers_data = {
                            "count": len(followers),
                            "items": followers,
                        }
                        self._store.save_snapshot(platform_id, uid, "followers", followers_data)
                except Exception as e:
                    print(f"[Collector] {platform_id}:{uid} 粉丝采集失败: {e}")

                self._last_run[platform_id] = now_iso

                entry = {
                    "time": now_iso,
                    "platform": platform_id,
                    "uid": uid,
                    "events_count": len(events) if events else 0,
                    "items_count": len(items) if items else 0,
                    "follows_count": len(follows) if follows else 0,
                    "followers_count": len(followers) if followers else 0,
                    "success": True,
                }
                new_entries.append(entry)
                self._log_entries.append(entry)

                print(f"[Collector] {platform_id}:{uid} 采集完成 "
                      f"(动态{len(events) if events else 0}, 内容{len(items) if items else 0}, "
                      f"关注{len(follows) if follows else 0}, 粉丝{len(followers) if followers else 0})")

            except Exception as e:
                print(f"[Collector] {platform_id}:{uid} 采集失败: {e}")
                entry = {
                    "time": now_iso, "platform": platform_id,
                    "uid": uid, "success": False, "error": str(e),
                }
                new_entries.append(entry)
                self._log_entries.append(entry)

        # 生成时间线
        if self.targets:
            try:
                timeline = TimelineBuilder.build(self.targets, limit_per_platform=15)

                # 持久化到数据库（自动去重）
                try:
                    inserted = self._store.insert_timeline_entries(timeline)
                    print(f"[Collector] 时间线持久化: {inserted} 条新增")
                except Exception as e:
                    print(f"[Collector] 时间线持久化失败: {e}")

                log_text = TimelineBuilder.build_log_text(timeline)

                # 保存日志到文件
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                log_file = LOG_DIR / f"timeline_{now.strftime('%Y%m%d_%H%M%S')}.txt"
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(log_text)

                # 同时保存 JSON
                json_file = LOG_DIR / f"timeline_{now.strftime('%Y%m%d_%H%M%S')}.json"
                import json
                with open(json_file, "w", encoding="utf-8") as f:
                    json.dump([_to_dict(e) for e in timeline], f, ensure_ascii=False, indent=2, default=str)

                print(f"[Collector] 时间线已保存: {log_file}")
            except Exception as e:
                print(f"[Collector] 时间线生成失败: {e}")

        return new_entries

    def _loop(self):
        """后台循环"""
        # 首次立即执行
        self.collect_once()

        while self._running:
            time.sleep(self.interval)
            if self._running:
                self.collect_once()


# 全局采集器实例
collector = AutoCollector(interval_minutes=30)


def get_collector() -> AutoCollector:
    return collector


def _to_dict(obj) -> dict:
    """dataclass → dict"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for key in obj.__dataclass_fields__:
            val = getattr(obj, key)
            if hasattr(val, "__dataclass_fields__"):
                result[key] = _to_dict(val)
            elif isinstance(val, list):
                result[key] = [_to_dict(v) if hasattr(v, "__dataclass_fields__") else v for v in val]
            elif isinstance(val, dict):
                result[key] = {k: _to_dict(v) if hasattr(v, "__dataclass_fields__") else v for k, v in val.items()}
            else:
                result[key] = val
        return result
    return obj
