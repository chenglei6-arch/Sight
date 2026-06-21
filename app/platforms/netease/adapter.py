"""
网易云音乐平台适配器

实现 BasePlatformAdapter 接口，
封装 weapi 加密、HTTP 请求、数据转换。
"""
import json
from typing import Optional

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    MediaEntry,
    EventItem,
)
from app.platforms.netease.crypto import encrypt_request
from app.platforms.netease.client import NeteaseClient


class NeteaseAdapter(BasePlatformAdapter):
    """网易云音乐平台适配器"""

    platform_id = "netease"
    platform_name = "网易云音乐"

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self._client = NeteaseClient(credentials)

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        user = self._get_login_user_raw()
        return bool(user.get("userId"))

    def get_login_user(self) -> Optional[dict]:
        user = self._get_login_user_raw()
        if user.get("userId"):
            return {
                "uid": str(user["userId"]),
                "nickname": user.get("nickname", ""),
                "avatarUrl": user.get("avatarUrl", ""),
            }
        return None

    def _get_login_user_raw(self) -> dict:
        resp = self._client.api_get("/api/nuser/account/get")
        return resp.get("profile", {})

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        resp = self._client.weapi_post("/weapi/search/get", {
            "s": keyword,
            "type": 1002,
            "limit": limit,
            "offset": 0,
        })
        users = resp.get("result", {}).get("userprofiles", [])
        return [
            {
                "uid": str(u.get("userId", "")),
                "nickname": u.get("nickname", ""),
                "avatarUrl": u.get("avatarUrl", ""),
                "signature": u.get("signature", ""),
                "gender": u.get("gender", 0),
                "vipType": u.get("vipType", 0),
            }
            for u in users
        ]

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        detail = self._client.weapi_post(f"/weapi/v1/user/detail/{uid}", {})
        if detail.get("code") != 200:
            return None

        p = detail.get("profile", {})
        level_data = self._client.weapi_post("/weapi/user/level", {})
        subcount = self._client.weapi_post("/weapi/subcount", {})

        return PlatformProfile(
            platform="netease",
            uid=str(p.get("userId", "")),
            nickname=p.get("nickname", ""),
            avatar_url=p.get("avatarUrl", ""),
            background_url=p.get("backgroundUrl", ""),
            signature=p.get("signature", ""),
            gender=p.get("gender", 0),
            birthday=str(p.get("birthday", "")) if p.get("birthday") else "",
            location=f"{p.get('province', '')} {p.get('city', '')}".strip(),
            join_time=str(p.get("createTime", "")),
            level=level_data.get("data", {}).get("level", 0),
            is_vip=p.get("vipType", 0) == 11,
            vip_label="黑胶VIP" if p.get("vipType") == 11 else "",
            extra={
                "listenSongs": level_data.get("data", {}).get("listenSongs", 0),
                "followeds": p.get("followeds", 0),
                "follows": p.get("follows", 0),
                "eventCount": p.get("eventCount", 0),
                "playlistCount": p.get("playlistCount", 0),
                "artistCount": subcount.get("artistCount", 0),
                "mvCount": subcount.get("mvCount", 0),
                "djRadioCount": subcount.get("djRadioCount", 0),
                "createdPlaylistCount": subcount.get("createdPlaylistCount", 0),
                "subPlaylistCount": subcount.get("subPlaylistCount", 0),
            },
        )

    # ==================== 歌单 ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取歌单列表（翻页直到没有更多）"""
        result = []
        offset = 0
        while True:
            resp = self._client.weapi_post("/weapi/user/playlist", {
                "uid": uid,
                "limit": 100,
                "offset": offset,
                "includeVideo": True,
            })
            playlists = resp.get("playlist", [])
            if not playlists:
                break
            for pl in playlists:
                result.append(ContentItem(
                    item_id=str(pl.get("id", "")),
                    title=pl.get("name", ""),
                    cover_url=pl.get("coverImgUrl", ""),
                    count=pl.get("trackCount", 0),
                    view_count=pl.get("playCount", 0),
                    creator=pl.get("creator", {}).get("nickname", ""),
                    description=(pl.get("description") or "")[:200],
                    is_owner=not pl.get("subscribed", False),
                    create_time=str(pl.get("createTime", "")),
                    extra={
                        "subscribedCount": pl.get("subscribedCount", 0),
                        "userId": str(pl.get("userId", "")),
                    },
                ))
            if not resp.get("more"):
                break
            offset += 100
        return result

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        resp = self._client.weapi_post("/weapi/v6/playlist/detail", {
            "id": item_id,
            "n": 100000,
            "s": 8,
        })
        playlist = resp.get("playlist", {})
        if not playlist:
            return None

        tracks = playlist.get("tracks", [])
        songs = []
        for track in tracks[:100]:
            songs.append({
                "id": str(track.get("id", "")),
                "title": track.get("name", ""),
                "artist": ", ".join(a.get("name", "") for a in track.get("ar", [])),
                "album": track.get("al", {}).get("name", ""),
                "coverUrl": track.get("al", {}).get("picUrl", ""),
                "duration": track.get("dt", 0),
            })

        return {
            "title": playlist.get("name", ""),
            "coverUrl": playlist.get("coverImgUrl", ""),
            "count": playlist.get("trackCount", 0),
            "viewCount": playlist.get("playCount", 0),
            "description": (playlist.get("description") or "")[:500],
            "creator": playlist.get("creator", {}).get("nickname", ""),
            "createTime": str(playlist.get("createTime", "")),
            "subscribedCount": playlist.get("subscribedCount", 0),
            "items": songs,
        }

    # ==================== 听歌排行 ====================

    def get_history(self, uid: str, period: str = "all") -> list[MediaEntry]:
        record_type = 0 if period == "all" else 1
        resp = self._client.weapi_post("/weapi/v1/play/record", {
            "uid": uid,
            "type": record_type,
        })
        data_key = "allData" if period == "all" else "weekData"
        records = resp.get(data_key, [])

        result = []
        for item in records:
            song = item.get("song", {})
            result.append(MediaEntry(
                entry_id=str(song.get("id", "")),
                title=song.get("name", ""),
                artist_or_uploader=", ".join(
                    a.get("name", "") for a in song.get("ar", [])
                ),
                album_or_category=song.get("al", {}).get("name", ""),
                cover_url=song.get("al", {}).get("picUrl", ""),
                duration=song.get("dt", 0),
                play_count=item.get("playCount", 0),
                extra={"score": item.get("score", 0)},
            ))
        return result

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态（时间游标翻页直到取够 limit 或没有更多）"""
        result = []
        cursor_time = -1
        max_pages = 10

        type_map = {
            18: "分享", 19: "分享", 17: "分享",
            39: "视频", 35: "评论",
            13: "歌单", 22: "转发",
            24: "专栏",
        }

        for _ in range(max_pages):
            resp = self._client.weapi_post(f"/weapi/event/get/{uid}", {
                "uid": uid,
                "limit": min(limit - len(result), 50),
                "time": cursor_time,
                "getcounts": True,
            })
            events = resp.get("events", [])
            if not events:
                break

            for ev in events:
                if len(result) >= limit:
                    break
                info = ev.get("info", {})
                json_data = {}
                try:
                    json_data = json.loads(ev.get("json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    pass

                media_title = ""
                media_artist = ""
                if "song" in json_data:
                    media_title = json_data["song"].get("name", "")
                    media_artist = ", ".join(
                        a.get("name", "") for a in json_data["song"].get("artists", [])
                    )
                elif "playlist" in json_data:
                    media_title = json_data["playlist"].get("name", "")
                    media_artist = json_data["playlist"].get("creator", {}).get("nickname", "")

                result.append(EventItem(
                    event_id=str(ev.get("id", "")),
                    event_type=type_map.get(info.get("type"), "动态"),
                    content=json_data.get("msg", ""),
                    timestamp=ev.get("eventTime", 0),
                    media_title=media_title,
                    media_artist=media_artist,
                    extra={"pics": info.get("pics", []), "actName": info.get("actName", "")},
                ))

            if len(result) >= limit or not resp.get("more"):
                break
            cursor_time = resp.get("lasttime", cursor_time)

        return result

    # ==================== 关注/粉丝 ====================

    def get_follows(self, uid: str, limit: int = 500) -> list[dict]:
        """获取关注列表（翻页直到取够 limit 或没有更多）"""
        all_follows = []
        offset = 0
        while len(all_follows) < limit:
            resp = self._client.weapi_post(f"/weapi/user/getfollows/{uid}", {
                "uid": uid, "limit": 100, "offset": offset, "order": True,
            })
            follows = resp.get("follow", [])
            if not follows:
                break
            for f in follows:
                all_follows.append({
                    "uid": str(f.get("userId", "")),
                    "nickname": f.get("nickname", ""),
                    "avatarUrl": f.get("avatarUrl", ""),
                    "signature": f.get("signature", ""),
                    "gender": f.get("gender", 0),
                })
            if not resp.get("more"):
                break
            offset += 100
        return all_follows[:limit]

    def get_followers(self, uid: str, limit: int = 500) -> list[dict]:
        """获取粉丝列表（翻页直到取够 limit 或没有更多）"""
        all_followers = []
        offset = 0
        while len(all_followers) < limit:
            resp = self._client.weapi_post(f"/weapi/user/getfolloweds/{uid}", {
                "userId": uid, "limit": 100, "offset": offset,
                "time": "0", "getcounts": True,
            })
            followers = resp.get("followeds", [])
            if not followers:
                break
            for f in followers:
                all_followers.append({
                    "uid": str(f.get("userId", "")),
                    "nickname": f.get("nickname", ""),
                    "avatarUrl": f.get("avatarUrl", ""),
                    "signature": f.get("signature", ""),
                    "gender": f.get("gender", 0),
                })
            if not resp.get("more"):
                break
            offset += 100
        return all_followers[:limit]
