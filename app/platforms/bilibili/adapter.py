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
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


def _dict(x) -> dict:
    """B站 API 嵌套字段可能为显式 null，统一收敛为 dict，避免链式 .get 报错"""
    return x if isinstance(x, dict) else {}


class BilibiliAdapter(BasePlatformAdapter):
    """哔哩哔哩平台适配器"""

    platform_id = "bilibili"
    platform_name = "哔哩哔哩"

    BASE_API = "https://api.bilibili.com"

    def __init__(self, credentials: dict = None, account_id: str = None):
        super().__init__(credentials, account_id)
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self._consecutive_rate_limits = 0
        self.last_api_error: str | None = None  # 最近一次业务错误（code/msg），供上层透传真实原因

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        s = requests.Session()
        cookies = self._load_cookies()
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
        """带重试的 GET 请求；重试耗尽或业务错误时抛 RuntimeError，不返回空值伪装成功"""
        last_error = "未知错误"
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
                    last_error = f"HTTP {resp.status_code}（风控拦截）"
                    time.sleep(wait_time)
                    continue

                if resp.status_code != 200:
                    print(f"[B站] HTTP {resp.status_code}，等待重试... endpoint={endpoint}")
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1.5 + attempt)
                    continue

                # 防御：B站可能返回空响应或 JSON null（反爬虫特征）
                raw_text = resp.text.strip() if resp.text else ""
                if not raw_text or raw_text == "null":
                    self._consecutive_rate_limits += 1
                    last_error = "空响应（疑似反爬虫拦截）"
                    if attempt >= 1:
                        # 已重试过一次仍为空，疑似反爬虫，快速放弃
                        print(f"[B站] 空响应持续，疑似反爬虫拦截，放弃 endpoint={endpoint}")
                        break
                    print(f"[B站] 空响应 (attempt {attempt+1})，短暂等待后重试... endpoint={endpoint}")
                    time.sleep(min(2 + self._consecutive_rate_limits * 1.5, 10))
                    continue

                data = resp.json()
                # 防御：json() 可能返回 None（body 为 "null"）
                if data is None or not isinstance(data, dict):
                    last_error = f"非字典响应 type={type(data).__name__}"
                    if attempt >= 1:
                        print(f"[B站] 非字典响应持续 type={type(data).__name__}，放弃 endpoint={endpoint}")
                        break
                    print(f"[B站] 非字典响应 type={type(data).__name__} (attempt {attempt+1})，等待重试... endpoint={endpoint}")
                    time.sleep(1.5)
                    continue

                code = data.get("code")
                if code == 0:
                    self._consecutive_rate_limits = 0
                    self.last_api_error = None
                    return data.get("data", {})

                msg = data.get("message") or data.get("msg") or "未知错误"
                last_error = f"{msg}(code={code})"

                if code == -799:
                    self._consecutive_rate_limits += 1
                    wait_time = min(3 + (self._consecutive_rate_limits * 2), 20)
                    print(f"[B站] 频率限制 (-799)，等待 {wait_time}s 重试... endpoint={endpoint}")
                    time.sleep(wait_time)
                    continue

                print(f"[B站] API 返回异常: code={code}, msg={msg}, endpoint={endpoint}")
                self.last_api_error = last_error
                # 业务错误（目标不存在/未登录/权限不足等）重试无意义，直接上抛
                raise RuntimeError(f"[B站] {last_error}, endpoint={endpoint}")

            except (requests.RequestException, ValueError, AttributeError) as e:
                last_error = str(e)
                print(f"[B站] 请求失败 (attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt)

        self.last_api_error = last_error
        raise RuntimeError(f"[B站] 请求失败: {last_error}, endpoint={endpoint}")

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        cookies = self._load_cookies()
        if not cookies.get("SESSDATA"):
            return False
        try:
            data = self._get("/x/web-interface/nav")
            return bool(data.get("mid"))
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        cookies = self._load_cookies()
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
                "is_vip": u.get("vip", {}).get("status", 0) == 1,  # 大会员
                # 官方认证即视为"达人"：type=1 机构号、type=0 个人认证（B站知名UP主的认证都是个人认证，
                # 如"bilibili 知名科普UP主"；漏掉它则大V灰化判定对绝大多数知名UP失效）
                "is_verified": (u.get("official_verify") or {}).get("type", -1) in (0, 1),
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
        stat = _dict(self._get("/x/space/upstat", {"mid": uid}))
        archive = _dict(stat.get("archive"))
        article = _dict(stat.get("article"))
        vip = _dict(info.get("vip"))
        official = _dict(info.get("official"))
        live_room = _dict(info.get("live_room"))

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
            is_vip=vip.get("status", 0) == 1,
            vip_label="B站大会员" if vip.get("status") == 1 else "",
            extra={
                "follower_count": info.get("follower", 0),
                "following_count": info.get("following", 0),
                "video_count": archive.get("view", 0),
                "article_count": article.get("view", 0),
                "likes": stat.get("likes", 0),
                "total_views": archive.get("view", 0),
                "official": official.get("title", ""),
                "live_status": live_room.get("liveStatus", 0),
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
                mod = _dict(item.get("modules"))
                dyn = _dict(mod.get("module_dynamic"))
                desc = _dict(dyn.get("desc"))
                stat = _dict(mod.get("module_stat"))
                author = _dict(mod.get("module_author"))
                major = _dict(dyn.get("major"))

                # 提取文字内容
                text_parts = desc.get("text", "") if isinstance(desc, dict) and isinstance(desc.get("text"), str) else ""
                if not text_parts and isinstance(desc, dict) and isinstance(desc.get("rich_text_nodes"), list):
                    text_parts = "".join(
                        n.get("orig_text", n.get("text", ""))
                        for n in (desc.get("rich_text_nodes") or [])
                    )

                # 提取关联内容
                media_title = ""
                if _dict(major.get("archive")):
                    media_title = major["archive"].get("title", "")
                elif _dict(major.get("article")):
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
                        "likes": _dict(stat.get("like")).get("count", 0),
                        "comments": _dict(stat.get("comment")).get("count", 0),
                        "forwards": _dict(stat.get("forward")).get("count", 0),
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

    def _social_batch(
        self, uid: str, endpoint: str, limit: int, skip: int
    ) -> tuple[list[dict], bool, int]:
        """
        增量拉取一页关注/粉丝。
        skip>0 表示跳过前面 skip 条（已展开的人），从后续开始取，避免重复。
        返回 (条目, 是否还有更多, 真实总数或 -1)。单页 50。
        B站 relation 接口最多只返回前 100 条（第 3 页起为空），因此实际可拉上限 100；
        拉到 100 后再续拉也拿不到更多，more 固定为 False。
        """
        BILI_SOCIAL_HARD_CAP = 100
        items: list[dict] = []
        result: dict = {}
        pn = max(1, skip // 50 + 1)
        ps = 50
        need = min(limit, BILI_SOCIAL_HARD_CAP - skip)  # 拿不满 100 也如实少拉
        while len(items) < need:
            result = self._get(endpoint, {"vmid": uid, "ps": ps, "pn": pn})
            batch = result.get("list") or []
            if not batch:
                # 第一页就无响应且无 total = 接口失败（Cookie 失效/风控/参数错误）；
                # 真正的空列表会带 total 字段。不吞错，让上层把真实原因展示给用户。
                if pn == max(1, skip // 50 + 1) and "total" not in result:
                    # 平台有明确业务错误（如 22115 用户已设置隐私）时如实透传，避免误导为 Cookie 失效
                    detail = f"，平台返回：{self.last_api_error}" if self.last_api_error else ""
                    raise RuntimeError(
                        f"[B站] 获取关注/粉丝列表失败：接口无响应（Cookie 可能失效，或触发风控）{detail}"
                    )
                break
            start = (skip % 50) if pn == skip // 50 + 1 else 0  # 首页跳掉已拉取的条数
            for f in batch[start:]:
                items.append({
                    "uid": str(f.get("mid", "")),
                    "nickname": f.get("uname", ""),
                    "avatarUrl": f.get("face", ""),
                    "signature": f.get("sign", ""),
                    "gender": {"男": 1, "女": 2}.get(f.get("gender", ""), 0),
                    # 官方认证即视为"达人"（type=1 机构号 / type=0 个人认证的知名UP）
                    "is_verified": _dict(f.get("official_verify")).get("type", -1) in (0, 1),
                    # relation 列表接口不返回粉丝数字段，这里恒为 0；
                    # 大V判定靠上面的认证标记，粉丝数用图谱"重新标记"（relation/stat）补全
                    "fans": f.get("fans", 0) or 0,
                })
                if len(items) >= need:
                    break
            if start and len(batch) <= start:
                break
            if len(batch) < ps:
                break
            pn += 1
        total = -1
        if isinstance(result, dict):
            try:
                total = int(result.get("total", -1))
            except (TypeError, ValueError):
                total = -1
        # 还有更多：B站最多只能取 100 条；已到硬顶则无法再续拉
        if skip + len(items) >= BILI_SOCIAL_HARD_CAP:
            more = False
        elif total >= 0:
            more = skip + len(items) < total
        else:
            more = len(items) >= need and len(items) % 50 == 0
        return items, more, total

    def get_follows(self, uid: str, limit: int = 500, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取关注列表（增量：skip 已拉条数；返回 条目/还有更多/总数）"""
        return self._social_batch(uid, "/x/relation/followings", limit, skip)

    def get_followers(self, uid: str, limit: int = 500, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取粉丝列表（增量：skip 已拉条数；返回 条目/还有更多/总数）"""
        return self._social_batch(uid, "/x/relation/followers", limit, skip)

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """重新拉取用户最新粉丝数/认证（图谱"重新标记"用）"""
        profile = self.get_profile(uid)
        if not profile:
            return None
        fans = profile.extra.get("follower_count") or 0
        if not fans:
            # acc/info 未带 Wbi 签名时 follower 恒为 0，改用轻量的 relation/stat 补粉丝数
            try:
                stat = self._get("/x/relation/stat", {"vmid": uid})
                fans = int(stat.get("follower") or 0)
            except Exception:
                pass  # 补不到时保持 0，认证标记仍然生效
        return {
            "nickname": profile.nickname,
            "fans": fans,
            # official 为认证机构/个人标题（空串=未认证），个人认证的知名UP也算
            "is_verified": bool(profile.extra.get("official")),
        }
