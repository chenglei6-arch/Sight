"""
微博平台适配器

基于 m.weibo.cn 移动端 API 的数据采集实现。

API 说明:
  - m.weibo.cn/api/container/getIndex  移动端容器 API（主要数据源）
  - s.weibo.com/user                   微博网页搜索
  - weibo.com/u/{uid}                   PC 端用户主页（SSR 兜底）

认证方式:
  - 需要 Cookie（SUB, SUBP 等字段）
  - 部分公开数据无需登录即可访问
  - 关注/粉丝列表需要登录态

已知限制:
  - 搜索功能对未登录用户限制严格
  - 关注/粉丝列表需要有效登录态
  - 移动端 API 有频率限制（约 100 次/分钟）
"""
import json
import re
import time
from typing import Optional

import requests

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    EventItem,
)
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class WeiboAdapter(BasePlatformAdapter):
    """微博平台适配器"""

    platform_id = "weibo"
    platform_name = "微博"

    # API 基础地址
    MOBILE_API = "https://m.weibo.cn/api/container/getIndex"
    WEB_BASE = "https://weibo.com"
    SEARCH_BASE = "https://s.weibo.com"

    def __init__(self, credentials: dict = None, account_id: str = None):
        super().__init__(credentials, account_id)
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self.last_api_error: str | None = None  # 最近一次业务错误，供上层透传真实原因

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        """构建请求会话（带 Cookie 和 UA）"""
        s = requests.Session()
        cookies = self._load_cookies()
        for key, value in cookies.items():
            s.cookies.set(key, value)
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://m.weibo.cn/",
            "Origin": "https://m.weibo.cn",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "X-Requested-With": "XMLHttpRequest",
        })
        return s

    def _rate_limit(self):
        """请求间隔控制"""
        now = time.time()
        min_interval = 1.5  # 微博请求间隔（秒）
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.time()

    def _mobile_get(self, params: dict) -> dict:
        """调用移动端 API"""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(
                    self.MOBILE_API,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok") == 1:
                        self.last_api_error = None
                        return data.get("data", {})
                    # ok=-100 且带 passport 链接 = 被重定向到登录页，登录态失效
                    if data.get("ok") == -100 or data.get("url"):
                        self.last_api_error = "登录态已失效，请更新 Cookie"
                        print(f"[微博] 登录态失效，API 重定向到 passport，params={params}")
                        return {}
                    # ok=0 通常表示登录态失效或参数错误
                    msg = data.get("msg", "")
                    self.last_api_error = msg or f"接口返回异常 (ok={data.get('ok')})"
                    print(f"[微博] API 返回异常: {self.last_api_error}, params={params}")
                    return {}
                else:
                    print(f"[微博] HTTP {resp.status_code} (attempt {attempt+1}), params={params}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1.5 + attempt * 0.5)

            except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
                print(f"[微博] 请求失败 (attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt)

        return {}

    def _web_get(self, url: str, params: dict = None, headers: dict = None) -> Optional[str]:
        """获取网页内容（SSR 兜底）"""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    return resp.text
                print(f"[微博] 网页 HTTP {resp.status_code} (attempt {attempt+1}), url={url}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt * 0.5)
            except requests.RequestException as e:
                print(f"[微博] 网页请求失败 (attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt)
        return None

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查 Cookie 是否有效（通过访问移动端首页）"""
        cookies = self._load_cookies()
        if not cookies:
            return False
        try:
            # 移动端配置接口可达且未报登录失效，才视为凭证有效
            data = self._mobile_get({"type": "uid", "value": "0"})
            return bool(data)
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户"""
        cookies = self._load_cookies()
        # 从 Cookie 中提取 uid
        # 微博 Cookie 中的 SUB 字段包含用户信息
        uid = ""
        for key in ("uid", "XSRF_TOKEN", "SUB"):
            if key in cookies and cookies[key]:
                # SUB 格式: xxx%1234567890 其中数字部分是 uid
                if key == "SUB":
                    match = re.search(r'(\d{6,})', cookies[key])
                    if match:
                        uid = match.group(1)
                break

        # 尝试通过 API 获取完整信息
        if not uid:
            return None

        # 尝试获取昵称
        profile = self._get_profile_via_mobile(uid)
        if profile:
            return {
                "uid": profile.uid,
                "nickname": profile.nickname,
                "avatarUrl": profile.avatar_url,
            }
        return {"uid": uid, "nickname": "", "avatarUrl": ""}

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """按昵称搜索用户（s.weibo.com 用户搜索页，需有效登录 Cookie）

        错误直接抛 RuntimeError，由 API 层透传给前端展示真实原因。
        """
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        return self._search_via_web(keyword, limit)

    # 用户卡片块（s.weibo.com SSR 页面）：<div class="card card-user-b ...">
    _USER_CARD_SPLIT = '<div class="card card-user-b'
    _USER_LINK_RE = re.compile(
        r'href="//weibo\.com/u/(\d+)"[^>]*?class="name"[^>]*?>(.*?)</a>', re.S
    )
    _USER_AVATAR_RE = re.compile(r'<img\s+src="(https://\w+\.sinaimg\.cn/[^"]+)"')
    _USER_FANS_RE = re.compile(r'粉丝[：:]\s*([\d.]+)(万)?')
    _ISLOGIN_RE = re.compile(r"\$CONFIG\['islogin'\]\s*=\s*'(\d)'")

    def _search_via_web(self, keyword: str, limit: int = 20) -> list[dict]:
        """通过 s.weibo.com 网页搜索用户"""
        html = self._web_get(
            f"{self.SEARCH_BASE}/user",
            params={"q": keyword, "page": 1, "Refer": "weibo_user"},
            # s.weibo.com 对 XHR 请求会返回"404错误"页，必须去掉会话里全局的
            # X-Requested-With 头
            headers={"X-Requested-With": None},
        )
        if not html:
            raise RuntimeError("微博搜索失败：搜索页请求无响应，请稍后重试")

        # 被 302 到 passport 访客页 / islogin=0 = 登录态失效
        if "passport.weibo.com" in html or (
            (m := self._ISLOGIN_RE.search(html)) and m.group(1) != "1"
        ):
            raise RuntimeError("微博搜索失败：登录态已失效，请更新 Cookie")

        # 过期/无效 Cookie 下 s.weibo.com 返回整页"404错误"
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        if title and "404" in title.group(1):
            raise RuntimeError(
                "微博搜索失败：搜索页返回 404，Cookie 可能已失效，请更新 Cookie 后重试"
            )

        users = []
        for block in html.split(self._USER_CARD_SPLIT)[1:]:
            link = self._USER_LINK_RE.search(block)
            if not link:
                continue
            uid, nickname = link.group(1), re.sub(r"<[^>]+>", "", link.group(2)).strip()
            if not uid or not nickname:
                continue

            fans = 0
            fans_m = self._USER_FANS_RE.search(block)
            if fans_m:
                fans = float(fans_m.group(1))
                if fans_m.group(2):
                    fans *= 10000
                fans = int(fans)

            avatar_m = self._USER_AVATAR_RE.search(block)
            users.append({
                "uid": uid,
                "nickname": nickname,
                "avatarUrl": avatar_m.group(1) if avatar_m else "",
                "signature": "",
                "fans": fans,
            })
            if len(users) >= limit:
                break

        return users

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """获取用户资料"""
        uid = str(uid).strip()
        if not uid:
            return None

        # 策略 1: 移动端 API
        profile = self._get_profile_via_mobile(uid)
        if profile:
            return profile

        # 策略 2: PC 端 SSR 兜底
        return self._get_profile_via_ssr(uid)

    def _get_profile_via_mobile(self, uid: str) -> Optional[PlatformProfile]:
        """通过移动端 API 获取用户资料"""
        data = self._mobile_get({"type": "uid", "value": uid})
        if not data:
            return None

        user_info = data.get("userInfo", {})
        if not user_info:
            return None

        tab_info = data.get("tabs", {})

        # 解析性别
        gender = 0
        if user_info.get("gender") == "m":
            gender = 1
        elif user_info.get("gender") == "f":
            gender = 2

        # 提取关注/粉丝/微博数
        follows = tab_info.get("follow", {})
        fans = tab_info.get("fans", {})

        return PlatformProfile(
            platform="weibo",
            uid=str(user_info.get("id", uid)),
            nickname=user_info.get("screen_name", ""),
            avatar_url=user_info.get("profile_image_url", ""),
            background_url=user_info.get("cover_image_phone", ""),
            signature=user_info.get("description", ""),
            gender=gender,
            birthday="",
            location=user_info.get("location", ""),
            join_time="",
            level=0,
            is_vip=user_info.get("verified", False),
            vip_label=user_info.get("verified_reason", ""),
            extra={
                "follow_count": follows.get("count", 0),
                "fans_count": fans.get("count", 0),
                "weibo_count": user_info.get("statuses_count", 0),
                "favourite_count": user_info.get("favourites_count", 0),
                "verified_reason": user_info.get("verified_reason", ""),
                "verified_type": user_info.get("verified_type", -1),
                "mbtype": user_info.get("mbtype", 0),
                "mbrank": user_info.get("mbrank", 0),
                "follow_status": user_info.get("follow_me", False),
                "containerid": data.get("tabsInfo", {}).get("containerid", ""),
            },
        )

    def _get_profile_via_ssr(self, uid: str) -> Optional[PlatformProfile]:
        """通过网页 SSR 兜底获取用户资料"""
        html = self._web_get(f"{self.WEB_BASE}/u/{uid}")
        if not html:
            return None

        try:
            # 从页面中提取 JSON 数据（微博在 window.$WB 或 script 中嵌入数据）
            json_match = re.search(r'window\.\$WB\s*=\s*(\{[^;]+\});', html)
            if not json_match:
                json_match = re.search(
                    r'<script>window\.__INITIAL_STATE__\s*=\s*({.*?});</script>',
                    html,
                )

            if json_match:
                state = json.loads(json_match.group(1))
                # 尝试从不同路径提取用户信息
                user_data = (
                    state.get("userInfo", {})
                    or state.get("users", {})
                )
                if not user_data:
                    return None

                # 如果 users 是 dict，提取第一个
                if isinstance(user_data, dict) and "id" not in user_data:
                    for k, v in user_data.items():
                        if isinstance(v, dict) and v.get("id"):
                            user_data = v
                            break

                if not user_data or not user_data.get("id"):
                    return None

                gender = 0
                if user_data.get("gender") == "m":
                    gender = 1
                elif user_data.get("gender") == "f":
                    gender = 2

                return PlatformProfile(
                    platform="weibo",
                    uid=str(user_data.get("id", uid)),
                    nickname=user_data.get("screen_name", ""),
                    avatar_url=user_data.get("avatar_hd", "") or user_data.get("profile_image_url", ""),
                    background_url=user_data.get("cover_image", ""),
                    signature=user_data.get("description", ""),
                    gender=gender,
                    birthday="",
                    location=user_data.get("location", ""),
                    join_time="",
                    level=0,
                    is_vip=user_data.get("verified", False),
                    vip_label=user_data.get("verified_reason", ""),
                    extra={
                        "follow_count": user_data.get("friends_count", 0),
                        "fans_count": user_data.get("followers_count", 0),
                        "weibo_count": user_data.get("statuses_count", 0),
                    },
                )

        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            print(f"[微博] SSR 解析失败: {e}")

        return None

    # ==================== 内容列表（微博列表） ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户的微博列表"""
        uid = str(uid).strip()
        if not uid:
            return []

        items = []

        # 先获取 containerid（微博列表容器的 ID）
        data = self._mobile_get({"type": "uid", "value": uid})
        if not data:
            return []

        tabs_info = data.get("tabsInfo", {})
        containerid = tabs_info.get("containerid", "")

        if not containerid:
            # 默认构造：107603 + uid 是微博列表的 containerid
            containerid = f"107603{uid}"

        # 翻页获取微博列表
        for page in range(1, 4):  # 最多取 3 页
            posts_data = self._mobile_get({
                "type": "uid",
                "value": uid,
                "containerid": containerid,
                "page": page,
            })
            if not posts_data:
                break

            cards = posts_data.get("cards", [])
            if not cards:
                break

            for card in cards:
                # 微博卡片格式：card_group 或 card_type 9
                mblog = None
                card_type = card.get("card_type", 0)

                if card_type == 9:
                    mblog = card.get("mblog", {})
                elif card_type == 11 and card.get("card_group"):
                    # 分组卡片
                    for sub in card["card_group"]:
                        if sub.get("card_type") == 9:
                            mblog = sub.get("mblog", {})
                            break

                if not mblog:
                    continue

                # 解析微博时间
                created_at = self._parse_weibo_time(mblog.get("created_at", ""))

                # 提取文字内容（最多 200 字作为标题）
                text_raw = mblog.get("text", "")
                text_plain = re.sub(r'<[^>]+>', '', text_raw).strip()
                title = text_plain[:200]

                item_id = mblog.get("id", "") or mblog.get("mid", "")

                items.append(ContentItem(
                    item_id=str(item_id),
                    title=title,
                    cover_url="",
                    count=1,
                    view_count=0,  # 旧版 API 可能不返回阅读数
                    creator=mblog.get("user", {}).get("screen_name", ""),
                    description=text_plain[:500],
                    is_owner=True,
                    create_time=str(created_at),
                    extra={
                        "reposts_count": mblog.get("reposts_count", 0),
                        "comments_count": mblog.get("comments_count", 0),
                        "attitudes_count": mblog.get("attitudes_count", 0),  # 点赞
                        "text": text_raw,
                        "pic_num": len(mblog.get("pics", [])),
                        "is_retweet": bool(mblog.get("retweeted_status")),
                        "source": mblog.get("source", ""),
                    },
                ))

            # 没有更多页
            if not cards or len(cards) < 10:
                break

        return items

    def _parse_weibo_time(self, time_str: str) -> int:
        """解析微博时间字符串为 Unix 时间戳（毫秒）

        微博时间格式: "Tue May 19 12:00:00 +0800 2020"
        """
        if not time_str:
            return 0
        try:
            # 标准微博格式
            dt = time.strptime(time_str, "%a %b %d %H:%M:%S %z %Y")
            return int(time.mktime(dt) * 1000) if dt else 0
        except (ValueError, TypeError):
            try:
                # 尝试 ISO 格式
                from datetime import datetime
                dt = datetime.fromisoformat(time_str)
                return int(dt.timestamp() * 1000)
            except (ValueError, TypeError):
                return 0

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态（微博发布）"""
        uid = str(uid).strip()
        if not uid:
            return []

        events = []

        # 获取 containerid
        data = self._mobile_get({"type": "uid", "value": uid})
        containerid = data.get("tabsInfo", {}).get("containerid", f"107603{uid}") if data else f"107603{uid}"

        max_pages = min(3, max(1, limit // 10 + 1))

        for page in range(1, max_pages + 1):
            posts_data = self._mobile_get({
                "type": "uid",
                "value": uid,
                "containerid": containerid,
                "page": page,
            })
            if not posts_data:
                break

            cards = posts_data.get("cards", [])
            if not cards:
                break

            for card in cards:
                if len(events) >= limit:
                    break

                mblog = None
                if card.get("card_type") == 9:
                    mblog = card.get("mblog", {})
                elif card.get("card_type") == 11 and card.get("card_group"):
                    for sub in card["card_group"]:
                        if sub.get("card_type") == 9:
                            mblog = sub.get("mblog", {})
                            break
                if not mblog:
                    continue

                # 判断动态类型
                event_type = "发布微博"
                if mblog.get("retweeted_status"):
                    event_type = "转发微博"

                text_raw = mblog.get("text", "")
                text_plain = re.sub(r'<[^>]+>', '', text_raw).strip()

                created_at = self._parse_weibo_time(mblog.get("created_at", ""))

                # 图片/视频媒体标题
                media_title = ""
                if mblog.get("page_info"):
                    page_info = mblog["page_info"]
                    media_title = page_info.get("page_title", "") or page_info.get("content2", "")

                if not media_title and mblog.get("retweeted_status"):
                    orig = mblog["retweeted_status"]
                    orig_text = re.sub(r'<[^>]+>', '', orig.get("text", "")).strip()
                    media_title = orig_text[:100]

                events.append(EventItem(
                    event_id=str(mblog.get("id", "")),
                    event_type=event_type,
                    content=text_plain[:500],
                    timestamp=created_at,
                    media_title=media_title[:200],
                    media_artist=mblog.get("user", {}).get("screen_name", ""),
                    extra={
                        "reposts_count": mblog.get("reposts_count", 0),
                        "comments_count": mblog.get("comments_count", 0),
                        "attitudes_count": mblog.get("attitudes_count", 0),
                        "pic_count": len(mblog.get("pics", [])),
                        "is_retweet": bool(mblog.get("retweeted_status")),
                    },
                ))

        return events

    # ==================== 关注/粉丝 ====================

    def _pc_ajax_get(self, path: str, params: dict) -> dict:
        """
        weibo.com PC 端 ajax 接口（需有效登录 Cookie）。
        实现参考 nghuyong/WeiboSpider：m.weibo.cn 的 containerid 方案对 weibo.com
        Cookie 做 wapsso 跨域校验会被拦（ok=-100 跳 passport），PC ajax 无此问题。
        """
        headers = {"Referer": "https://weibo.com/", "X-Requested-With": "XMLHttpRequest"}
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(
                    f"https://weibo.com{path}",
                    params=params,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        # 非 JSON（多为 302 跟到 passport 登录页的 HTML）
                        self.last_api_error = "登录态已失效，请更新 Cookie"
                        print(f"[微博] PC 接口返回非 JSON（疑似登录页），path={path}")
                        return {}
                    if isinstance(data, dict) and data.get("ok") == 1:
                        self.last_api_error = None
                        return data
                    msg = (data or {}).get("message") or ""
                    self.last_api_error = msg or f"接口返回异常 (ok={(data or {}).get('ok')})"
                    print(f"[微博] PC 接口返回异常: {self.last_api_error}, path={path}")
                    return {}
                print(f"[微博] HTTP {resp.status_code} (attempt {attempt+1}), path={path}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt * 0.5)
            except (requests.RequestException, ValueError) as e:
                print(f"[微博] 请求失败 (attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 + attempt)
        return {}

    def _social_page(
        self, uid: str, relate: str, limit: int, skip: int
    ) -> tuple[list[dict], bool, int]:
        """
        增量拉取一页关注/粉丝。relate: "" 关注列表 | "fans" 粉丝列表（WeiboSpider 同款参数）。
        单页 20 条。返回 (条目, 还有更多, 真实总数或 -1)。
        """
        per_page = 20
        first_page = skip // per_page + 1
        items: list[dict] = []
        total = -1
        page = first_page
        skip_in_page = skip % per_page
        while len(items) < limit:
            params = {"page": page, "uid": uid}
            if relate:
                params["relate"] = relate
                params["type"] = relate
            data = self._pc_ajax_get("/ajax/friendships/friends", params)
            if not data:
                # 第一页就取不到任何响应 = 接口失败（登录态失效/被风控/参数错误）；
                # 真正的空列表会返回 ok=1 且 users=[]。不吞错，让上层把真实原因展示给用户。
                if page == first_page:
                    detail = f"，平台返回：{self.last_api_error}" if self.last_api_error else ""
                    raise RuntimeError(
                        f"[微博] 获取关注/粉丝列表失败：接口无响应（Cookie 可能失效，或触发风控）{detail}"
                    )
                break
            if total < 0:
                try:
                    total = int(data.get("total_number", -1))
                except (TypeError, ValueError):
                    total = -1
            users = data.get("users") or []
            if not users:
                break
            for user in users:
                if skip_in_page:
                    skip_in_page -= 1  # 首页跳掉已拉取的条目
                    continue
                items.append({
                    "uid": str(user.get("id", "")),
                    "nickname": user.get("screen_name", ""),
                    "avatarUrl": user.get("profile_image_url", "") or user.get("avatar_hd", ""),
                    "signature": user.get("description", ""),
                    "gender": {"m": 1, "f": 2}.get(user.get("gender", ""), 0),
                    "is_vip": bool(user.get("verified", False)),
                    "is_verified": bool(user.get("verified", False)),
                    "fans": user.get("followers_count", 0) or 0,
                })
                if len(items) >= limit:
                    break
            if len(items) >= limit or len(users) < per_page:
                break
            page += 1
        if total >= 0:
            more = skip + len(items) < total
        else:
            more = len(items) >= limit  # 无总数时按取满推断还有更多
        return items, more, total

    def get_follows(self, uid: str, limit: int = 200, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取关注列表（增量：skip 已拉条数；返回 条目/还有更多/总数或-1）"""
        uid = str(uid).strip()
        if not uid:
            return [], False, -1
        return self._social_page(uid, "", limit, skip)

    def get_followers(self, uid: str, limit: int = 200, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取粉丝列表（增量：skip 已拉条数；返回 条目/还有更多/总数或-1）"""
        uid = str(uid).strip()
        if not uid:
            return [], False, -1
        return self._social_page(uid, "fans", limit, skip)

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """重新拉取用户最新粉丝数/认证（图谱"重新标记"用）"""
        profile = self.get_profile(uid)
        if not profile:
            return None
        # 微博 get_profile 把 verified 存在 is_vip 上（vip_label=认证原因）
        return {
            "nickname": profile.nickname,
            "fans": profile.extra.get("fans_count") or 0,
            "is_verified": bool(profile.is_vip),
        }
