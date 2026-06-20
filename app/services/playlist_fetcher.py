"""
歌单歌曲异步拉取服务

后台线程逐歌单拉取详情（每次请求间隔 REQUEST_INTERVAL 秒），
已拉取的立即写入 DataStore，前端轮询进度即可实时看到结果。
"""
import threading
import time
from datetime import datetime, timezone, timedelta

from app.platforms import get_adapter
from app.data.store import DataStore

CST = timezone(timedelta(hours=8))


class PlaylistSongFetcher:
    """歌单歌曲异步拉取器 — 每个 platform+uid 一个实例"""

    def __init__(self):
        self._store = DataStore()
        # 进度状态: key = f"{platform}:{uid}" → dict
        self._status: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start_fetch(self, platform: str, uid: str):
        """启动后台拉取（非阻塞）"""
        key = f"{platform}:{uid}"
        with self._lock:
            if key in self._status and self._status[key].get("running"):
                return self._status[key]  # 已在运行
            self._status[key] = {
                "running": True,
                "total": 0,
                "fetched": 0,
                "current": "",
                "error": None,
                "complete": False,
            }

        thread = threading.Thread(
            target=self._fetch_loop,
            args=(platform, uid),
            daemon=True,
        )
        thread.start()
        return self._status[key]

    def get_status(self, platform: str, uid: str) -> dict:
        """查询进度"""
        key = f"{platform}:{uid}"
        with self._lock:
            s = self._status.get(key)
            if s:
                return dict(s)
        # 从未启动 → 检查 DB 里是否有已保存的数据
        existing = self._store.get_latest_snapshot(platform, uid, "playlist_songs")
        if existing:
            fetched = existing.get("fetched", 0)
            total = existing.get("total", 0)
            return {
                "running": False,
                "total": total,
                "fetched": fetched,
                "current": "",
                "error": None,
                "complete": fetched >= total > 0,
            }
        return {
            "running": False,
            "total": 0,
            "fetched": 0,
            "current": "",
            "error": None,
            "complete": False,
        }

    def _fetch_loop(self, platform: str, uid: str):
        """后台逐个拉取歌单详情"""
        key = f"{platform}:{uid}"
        adapter = get_adapter(platform)
        if not adapter:
            self._set_error(key, f"未知平台: {platform}")
            return

        try:
            # 获取歌单列表
            playlists = adapter.get_content_lists(uid)
            if not playlists:
                self._set_error(key, "未获取到歌单列表")
                return

            total = len(playlists)
            with self._lock:
                self._status[key]["total"] = total

            # 收集结果
            result = {}
            fetched = 0

            for i, pl in enumerate(playlists):
                pl_id = getattr(pl, "item_id", "") or str(pl.get("item_id", pl.get("id", "")))
                pl_title = getattr(pl, "title", "") or pl.get("title", pl.get("name", ""))
                if not pl_id:
                    continue

                with self._lock:
                    self._status[key]["current"] = pl_title
                    self._status[key]["fetched"] = fetched

                # 保存中间进度到 DB（每完成一个就写一次）
                self._save_progress(platform, uid, result, total, fetched)

                # 拉取歌单详情
                try:
                    detail = adapter.get_content_detail(pl_id)
                except Exception as e:
                    print(f"[PlaylistFetcher] {pl_title} 详情获取失败: {e}")
                    detail = None

                if detail and detail.get("items"):
                    songs = []
                    for s in detail["items"]:
                        songs.append({
                            "id": str(s.get("id", "")),
                            "title": s.get("title", ""),
                            "artist": s.get("artist", ""),
                            "album": s.get("album", ""),
                            "coverUrl": s.get("coverUrl", ""),
                        })
                    result[pl_id] = {
                        "title": pl_title,
                        "songs": songs,
                        "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
                    }
                else:
                    # 空歌单或获取失败
                    result[pl_id] = {
                        "title": pl_title,
                        "songs": [],
                        "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
                    }

                fetched += 1

                # 请求间隔（保持和全局一致）
                from app.config import REQUEST_INTERVAL
                if i < total - 1:
                    time.sleep(REQUEST_INTERVAL)

            # 全部完成，写最终快照
            self._save_progress(platform, uid, result, total, fetched, final=True)

            with self._lock:
                self._status[key]["fetched"] = fetched
                self._status[key]["current"] = ""
                self._status[key]["complete"] = True
                self._status[key]["running"] = False

            print(f"[PlaylistFetcher] {platform}:{uid} 歌单歌曲拉取完成 ({fetched}/{total})")

        except Exception as e:
            self._set_error(key, str(e))

    def _save_progress(self, platform: str, uid: str, result: dict,
                       total: int, fetched: int, final: bool = False):
        """将当前进度写入 DataStore"""
        try:
            self._store.save_snapshot(platform, uid, "playlist_songs", {
                "playlists": result,
                "total": total,
                "fetched": fetched,
                "fetching": not final,
            })
        except Exception as e:
            print(f"[PlaylistFetcher] 进度保存失败: {e}")

    def _set_error(self, key: str, error: str):
        with self._lock:
            if key in self._status:
                self._status[key]["error"] = error
                self._status[key]["running"] = False
        print(f"[PlaylistFetcher] 错误: {error}")


# 全局单例
_fetcher: PlaylistSongFetcher | None = None


def get_playlist_fetcher() -> PlaylistSongFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = PlaylistSongFetcher()
    return _fetcher
