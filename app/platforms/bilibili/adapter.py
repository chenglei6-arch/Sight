"""
哔哩哔哩平台适配器（完整实现）

B站 API 参考:
- 用户搜索: /x/web-interface/search/type
- 用户资料: /x/space/acc/info
- 投稿列表: /x/space/arc/search
- 用户动态: /x/polymer/web-dynamic/v1/feed/space
- 关注/粉丝: /x/relation/*
"""
import time
from typing import Optional

import requests

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    MediaEntry,
    EventItem,
)
from app.credentials import CredentialManager
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class BilibiliAdapter(BasePlatformAdapter):
    """哔哩哔哩平台适配器"""

    platform_id = "bilibili"
    platform_name = "哔哩哔哩"

    BASE_API = "https://api.bilibili.com"

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self._consecutive_rate_limits = 0

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        cookies = CredentialManager.load_cookies("bilibili")
        if not cookies.get("SESSDATA"):
            print("[B站] 警告: 未检测到 SESSDATA，部分接口可能受限")
        for key, value in cookies.items():
            s.cookies.set(key, value)
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://space.bilibili.com/",
            "Origin": "https://space.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        return s

    def _rate_limit(self, extra_wait: float = 0):
        """请求间隔控制，支持额外等待（用于频率限制后）"""
        now = time.time()
        base_wait = 3.0  # B站基础间隔
        # 连续触发频率限制时额外增加等待
        penalty = min(self._consecutive_rate_limits * 2.0, 30.0)
        required_wait = base_wait + penalty + extra_wait
        elapsed = now - self._last_request_at
        if elapsed < required_wait:
            time.sleep(required_wait - elapsed)
        self._last_request_at = time.time()

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """带重试的 GET 请求（防御空响应/非字典/HTTP错误）"""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(
                    f"{self.BASE_API}{endpoint}",
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                # HTTP 429/412 是风控，直接退避重试
                if resp.status_code in (412, 429):
                    self._consecutive_rate_limits += 1
                    wait_time = min(5 + (self._consecutive_rate_limits * 2), 25)
                    print(f"[B站] HTTP {resp.status_code}，等待 {wait_time}s 重试... endpoint={endpoint}")
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    print(f"[B站] HTTP {resp.status_code}，等待重试... endpoint={endpoint}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1.5 + attempt)
                    continue

                # 防御：B站可能返回空响应或 JSON null（反爬虫特征）
                raw_text = resp.text.strip() if resp.text else ""
                if not raw_text or raw_text == "null":
                    self._consecutive_rate_limits += 1
                    if attempt >= 1:
                        # 已重试过一次仍为空，疑似反爬虫，快速放弃
                        print(f"[B站] 空响应持续，疑似反爬虫拦截，放弃 endpoint={endpoint}")
                        return {}
                    print(f"[B站] 空响应 (attempt {attempt+1})，短暂等待后重试... endpoint={endpoint}")
                    time.sleep(min(2 + self._consecutive_rate_limits * 1.5, 10))
                    continue

                data = resp.json()
                # 防御：json() 可能返回 None（body 为 "null"）
                if data is None or not isinstance(data, dict):
                    if attempt >= 1:
                        print(f"[B站] 非字典响应持续 type={type(data).__name__}，放弃 endpoint={endpoint}")
                        return {}
                    print(f"[B站] 非字典响应 type={type(data).__name__} (attempt {attempt+1})，等待重试... endpoint={endpoint}")
                    time.sleep(1.5)
                    continue

                code = data.get("code")
                if code == 0:
                    self._consecutive_rate_limits = 0
                    return data.get("data", {})

                if code == -799:
                    self._consecutive_rate_limits += 1
                    wait_time = min(3 + (self._consecutive_rate_limits * 2), 20)
                    print(f"[B站] 频率限制 (-799)，等待 {wait_time}s 重试... endpoint={endpoint}")
                    time.sleep(wait_time)
                    continue

                if code in (-404,):
                    return {}

                print(f"[B站] API 返回异常: code={code}, msg={data.get('message', '')}, endpoint={endpoint}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5)
                return data.get("data", {})

            except (requests.RequestException, ValueError, AttributeError) as e:
                print(f"[B站] 请求失败 (attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt)

        return {}

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        cookies = CredentialManager.load_cookies("bilibili")
        if not cookies.get("SESSDATA"):
            return False
        try:
            data = self._get("/x/web-interface/nav")
            return bool(data.get("mid"))
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        cookies = CredentialManager.load_cookies("bilibili")
        uid = cookies.get("DedeUserID", "")
        # 尝试通过 nav 接口获取完整信息
        try:
            data = self._get("/x/web-interface/nav")
            if data.get("mid"):
                return {
                    "uid": str(data["mid"]),
                    "nickname": data.get("uname", ""),
                    "avatarUrl": data.get("face", ""),
                }
        except Exception:
            pass
        if uid:
            return {"uid": uid, "nickname": "", "avatarUrl": ""}
        return None

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        result = self._get("/x/web-interface/search/type", {
            "search_type": "bili_user",
            "keyword": keyword,
            "page": 1,
        })
        users = result.get("result") or []
        return [
            {
                "uid": str(u.get("mid", "")),
                "nickname": u.get("uname", ""),
                "avatarUrl": "https:" + u.get("upic", "") if u.get("upic") else "",
                "signature": u.get("usign", ""),
                "gender": {"男": 1, "女": 2}.get(u.get("gender", ""), 0),
                "is_vip": u.get("vip", {}).get("status", 0) == 1,
                "fans": u.get("fans", 0),
                "videos": u.get("videos", 0),
            }
            for u in users[:limit]
        ]

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        info = self._get("/x/space/acc/info", {"mid": uid})
        if not info:
            return None

        # 获取UP主统计数据
        stat = self._get("/x/space/upstat", {"mid": uid})

        return PlatformProfile(
            platform="bilibili",
            uid=uid,
            nickname=info.get("name", ""),
            avatar_url=info.get("face", ""),
            background_url=info.get("top_photo", ""),
            signature=info.get("sign", ""),
            gender={"男": 1, "女": 2, "保密": 0}.get(info.get("sex", ""), 0),
            birthday=info.get("birthday", ""),
            join_time="",
            level=info.get("level", 0),
            is_vip=info.get("vip", {}).get("status", 0) == 1,
            vip_label="B站大会员" if info.get("vip", {}).get("status") == 1 else "",
            extra={
                "follower_count": info.get("follower", 0),
                "following_count": info.get("following", 0),
                "video_count": stat.get("archive", {}).get("view", 0) if stat else 0,
                "article_count": stat.get("article", {}).get("view", 0) if stat else 0,
                "likes": stat.get("likes", 0) if stat else 0,
                "total_views": stat.get("archive", {}).get("view", 0) if stat else 0,
                "official": info.get("official", {}).get("title", ""),
                "live_status": info.get("live_room", {}).get("liveStatus", 0),
            },
        )

    # ==================== 投稿/收藏夹 ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户投稿列表（翻页直到没有更多）"""
        items = []
        pn = 1
        ps = 50
        while True:
            result = self._get("/x/space/arc/search", {
                "mid": uid, "ps": ps, "pn": pn, "order": "pubdate",
            })
            videos = result.get("list", {}).get("vlist") or []
            if not videos:
                break
            for v in videos:
                items.append(ContentItem(
                    item_id=str(v.get("aid", "")),
                    title=v.get("title", ""),
                    cover_url=v.get("pic", ""),
                    count=1,
                    view_count=v.get("play", 0),
                    creator=v.get("author", ""),
                    description=v.get("description", "")[:200],
                    is_owner=True,
                    create_time=str(v.get("created", "")),
                    extra={
                        "bvid": v.get("bvid", ""),
                        "length": v.get("length", ""),
                        "comment_count": v.get("comment", 0),
                        "danmaku_count": v.get("video_review", 0),
                    },
                ))
            if len(videos) < ps:
                break
            pn += 1
        return items

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        """获取视频详情"""
        result = self._get("/x/web-interface/view", {"aid": item_id})
        if not result:
            return None
        return {
            "title": result.get("title", ""),
            "coverUrl": result.get("pic", ""),
            "count": 1,
            "viewCount": result.get("stat", {}).get("view", 0),
            "description": result.get("desc", "")[:500],
            "creator": result.get("owner", {}).get("name", ""),
            "createTime": str(result.get("pubdate", "")),
            "subscribedCount": result.get("stat", {}).get("favorite", 0),
            "items": [],
        }

    # ==================== 观看/播放历史 ====================

    def get_history(self, uid: str, period: str = "all") -> list[MediaEntry]:
        """B站没有公开的观看历史，返回投稿作为内容列表"""
        return []

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态（游标翻页直到取够 limit 或没有更多）"""
        events = []
        offset = ""
        max_pages = 10  # 安全上限，防止无限翻页

        type_map = {
            "DYNAMIC_TYPE_AV": "投稿视频",
            "DYNAMIC_TYPE_FORWARD": "转发动态",
            "DYNAMIC_TYPE_DRAW": "发布图文",
            "DYNAMIC_TYPE_WORD": "文字动态",
            "DYNAMIC_TYPE_LIVE_RCMD": "直播",
            "DYNAMIC_TYPE_ARTICLE": "发布专栏",
            "DYNAMIC_TYPE_PGC": "追番/追剧",
        }

        for _ in range(max_pages):
            result = self._get("/x/polymer/web-dynamic/v1/feed/space", {
                "host_mid": uid,
                "offset": offset,
            })

            items = result.get("items") or []
            if not items:
                break

            for item in items:
                if len(events) >= limit:
                    break
                mod = item.get("modules", {})
                desc = mod.get("module_dynamic", {}).get("desc") or {}
                stat = mod.get("module_stat", {})
                author = mod.get("module_author", {})

                # 提取文字内容
                text_parts = desc.get("text", "") if isinstance(desc, dict) and isinstance(desc.get("text"), str) else ""
                if not text_parts and isinstance(desc, dict) and isinstance(desc.get("rich_text_nodes"), list):
                    text_parts = "".join(
                        n.get("orig_text", n.get("text", ""))
                        for n in (desc.get("rich_text_nodes") or [])
                    )

                # 提取关联内容
                major = mod.get("module_dynamic", {}).get("major", {})
                media_title = ""
                if major.get("archive"):
                    media_title = major["archive"].get("title", "")
                elif major.get("article"):
                    media_title = major["article"].get("title", "")

                type_str = type_map.get(item.get("type", ""), item.get("type", "动态"))

                pub_ts = author.get("pub_ts", 0)
                try:
                    ts = int(pub_ts) * 1000 if pub_ts else 0
                except (ValueError, TypeError):
                    ts = 0

                events.append(EventItem(
                    event_id=item.get("id_str", str(item.get("id", ""))),
                    event_type=type_str,
                    content=text_parts[:500],
                    timestamp=ts,
                    media_title=media_title,
                    media_artist=author.get("name", ""),
                    extra={
                        "likes": stat.get("like", {}).get("count", 0),
                        "comments": stat.get("comment", {}).get("count", 0),
                        "forwards": stat.get("forward", {}).get("count", 0),
                    },
                ))

            if len(events) >= limit:
                break

            # 取下一页游标
            next_offset = result.get("offset")
            if not next_offset or next_offset == offset:
                break
            offset = next_offset

        return events

    # ==================== 关注/粉丝 ====================

    def get_follows(self, uid: str, limit: int = 500) -> list[dict]:
        """获取关注列表（翻页直到取够 limit 或没有更多，B站上限500）"""
        all_follows = []
        pn = 1
        ps = 50  # B站单页最大 50
        while len(all_follows) < limit:
            result = self._get("/x/relation/followings", {
                "vmid": uid, "ps": ps, "pn": pn,
            })
            follow_list = result.get("list") or []
            if not follow_list:
                break
            for f in follow_list:
                all_follows.append({
                    "uid": str(f.get("mid", "")),
                    "nickname": f.get("uname", ""),
                    "avatarUrl": f.get("face", ""),
                    "signature": f.get("sign", ""),
                    "gender": {"男": 1, "女": 2}.get(f.get("gender", ""), 0),
                })
            if len(follow_list) < ps:
                break
            pn += 1
        return all_follows[:limit]

    def get_followers(self, uid: str, limit: int = 500) -> list[dict]:
        """获取粉丝列表（翻页直到取够 limit 或没有更多，B站上限500）"""
        all_followers = []
        pn = 1
        ps = 50
        while len(all_followers) < limit:
            result = self._get("/x/relation/followers", {
                "vmid": uid, "ps": ps, "pn": pn,
            })
            follower_list = result.get("list") or []
            if not follower_list:
                break
            for f in follower_list:
                all_followers.append({
                    "uid": str(f.get("mid", "")),
                    "nickname": f.get("uname", ""),
                    "avatarUrl": f.get("face", ""),
                    "signature": f.get("sign", ""),
                    "gender": {"男": 1, "女": 2}.get(f.get("gender", ""), 0),
                })
            if len(follower_list) < ps:
                break
            pn += 1
        return all_followers[:limit]
