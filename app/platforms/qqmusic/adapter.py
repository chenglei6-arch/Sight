"""
QQ音乐平台适配器

基于 y.qq.com / c.y.qq.com 公开 API 的数据采集实现。

API 说明:
  - 大部分接口位于 c.y.qq.com 域名下
  - 需要 Referer: https://y.qq.com 防盗链
  - 返回 JSONP 格式 (需提取 callback)
  - g_tk 参数用于鉴权 (未登录=5381)
  - QQ 音乐没有公开的按昵称搜索用户的 API

数据结构:
  - 用户标识: uin (QQ 号)
  - 歌单 (Playlist) 是 QQ 音乐的核心内容组织形式
  - 用户可创建和收藏歌单
"""
import json
import random
import re
import time
from typing import Optional
from urllib.parse import urlencode

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


class QQMusicAdapter(BasePlatformAdapter):
    """QQ音乐平台适配器"""

    platform_id = "qqmusic"
    platform_name = "QQ音乐"

    # API 基础域名
    API_BASE = "https://c.y.qq.com"
    WEB_BASE = "https://y.qq.com"

    # 公共请求参数
    COMMON_PARAMS = {
        "format": "json",
        "inCharset": "utf-8",
        "outCharset": "utf-8",
        "notice": 0,
        "platform": "yqq",
        "needNewCode": 0,
    }

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self._g_tk = 5381  # 未登录默认值

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        """构建请求会话 (带 Cookie 和防盗链)"""
        s = requests.Session()
        cookies = CredentialManager.load_cookies("qqmusic")
        if cookies:
            for key, value in cookies.items():
                s.cookies.set(key, value)
            # 从 Cookie 中计算 g_tk (新版本用 qqmusic_key/qm_keyst 代替了 skey)
            skey = (
                cookies.get("skey")
                or cookies.get("p_skey")
                or cookies.get("qqmusic_key")
                or cookies.get("qm_keyst")
                or ""
            )
            self._g_tk = self._calc_g_tk(skey) if skey else 5381

        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Referer": "https://y.qq.com/",
            "Origin": "https://y.qq.com",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        return s

    @staticmethod
    def _calc_g_tk(skey: str) -> int:
        """计算 g_tk 鉴权参数 (与 QQ 音乐前端算法一致)"""
        h = 5381
        for c in skey:
            h += (h << 5) + ord(c)
        return h & 0x7FFFFFFF

    def _rate_limit(self):
        """请求间隔控制 (1s)"""
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed + random.uniform(0, 0.5))
        self._last_request_at = time.time()

    def _api_get_json(self, path: str, params: dict = None) -> dict:
        """
        调用 QQ音乐 API 并返回 JSON

        Args:
            path: API 路径 (如 /splcloud/fcgi-bin/fcg_get_diss_by_tag.fcg)
            params: 查询参数

        Returns:
            解析后的 JSON 字典, 失败返回 {}
        """
        url = f"{self.API_BASE}{path}"
        if params is None:
            params = {}

        # 合并公共参数
        all_params = {}
        all_params.update(self.COMMON_PARAMS)
        all_params.update(params)
        all_params.setdefault("g_tk", self._g_tk)

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(
                    url,
                    params=all_params,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
                if resp.status_code == 200:
                    return self._parse_response(resp.text)
                if resp.status_code in (429, 403):
                    wait = 3 + attempt * 2
                    print(f"[QQ音乐] HTTP {resp.status_code}, 等待 {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"[QQ音乐] HTTP {resp.status_code} path={path}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
            except requests.RequestException as e:
                print(f"[QQ音乐] 请求异常: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
        return {}

    def _api_post_json(self, path: str, json_body: dict = None) -> dict:
        """
        调用 QQ音乐 POST API (musicu.fcg 通用网关) 并返回 JSON

        Args:
            path: API 路径 (如 /cgi-bin/musicu.fcg)
            json_body: POST JSON 请求体

        Returns:
            解析后的 JSON 字典, 失败返回 {}
        """
        url = f"https://u.y.qq.com{path}"
        if json_body is None:
            json_body = {}

        # 注入公共参数
        json_body.setdefault("comm", {})
        json_body["comm"].setdefault("g_tk", self._g_tk)
        # 从 session cookie 获取实际 uin (有登录就用真实 uin)
        uin = 0
        for c in self.session.cookies:
            if c.name in ("uin", "qqmusic_uin"):
                uin = int(c.value) if c.value.isdigit() else 0
                break
        json_body["comm"].setdefault("uin", uin)
        json_body["comm"].setdefault("format", "json")
        json_body["comm"].setdefault("ct", 24)
        json_body["comm"].setdefault("cv", 0)

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.post(
                    url,
                    json=json_body,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 200:
                    return self._parse_response(resp.text)
                if resp.status_code in (429, 403):
                    wait = 3 + attempt * 2
                    print(f"[QQ音乐] HTTP {resp.status_code}, 等待 {wait}s...")
                    time.sleep(wait)
                    continue
                print(f"[QQ音乐] HTTP {resp.status_code} path={path}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
            except requests.RequestException as e:
                print(f"[QQ音乐] POST 请求异常: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
        return {}

    @staticmethod
    def _parse_response(text: str) -> dict:
        """
        解析 QQ音乐 API 响应

        QQ 音乐返回 JSONP (如 callback({...}))
        此函数提取 JSON 部分并解析。
        """
        if not text:
            return {}
        text = text.strip()
        # 如果是 JSONP, 提取括号中的 JSON
        # 格式: MusicJsonCallback({...}) 或 jsonCallback({...})
        match = re.search(r'^\w+\((.+)\)$', text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            json_str = text

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试去掉末尾的分号
            try:
                return json.loads(json_str.rstrip(";"))
            except json.JSONDecodeError:
                return {}

    def _fetch_html(self, url: str) -> str:
        """请求页面 HTML"""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    return resp.text
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
            except requests.RequestException as e:
                print(f"[QQ音乐] 页面请求异常: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
        return ""

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查 Cookie/连接是否有效"""
        try:
            cookies = CredentialManager.load_cookies("qqmusic")
        except FileNotFoundError:
            return False
        if not cookies:
            return False
        # 检查是否有认证必需的字段
        has_auth = bool(cookies.get("qqmusic_key") or cookies.get("qm_keyst") or cookies.get("skey") or cookies.get("p_skey"))
        has_uin = bool(cookies.get("uin"))
        return has_auth and has_uin

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户信息"""
        cookies = CredentialManager.load_cookies("qqmusic")
        # 从 Cookie 获取 uin
        uin = ""
        for key in ("uin", "qqmusic_uin", "loginUin"):
            val = cookies.get(key, "")
            if val:
                uin = val
                break

        if not uin:
            # 尝试从首页推荐 API 获取
            resp = self._api_get_json("/musichall/fcgi-bin/fcg_yqqhomepagerecommend.fcg")
            if resp:
                data = resp.get("data", {})
                uin = str(data.get("loginUin", ""))

        if uin:
            return {"uid": uin, "nickname": "", "avatarUrl": ""}
        return None

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        搜索用户

        通过 QQ音乐通用 API 网关 (musicu.fcg) 的 search_type=8 搜索普通用户。
        需要有效 Cookie 才能返回结果。
        """
        # ---------- 策略1: musicu.fcg search_type=8 ----------
        body = {
            "music.search.SearchCgiService": {
                "module": "music.search.SearchCgiService",
                "method": "DoSearchForQQMusicDesktop",
                "param": {
                    "query": keyword,
                    "search_type": 8,
                    "page_num": 1,
                    "num_per_page": min(limit, 40),
                    "grp": 1,
                    "remoteplace": "sizer.newclient.user",
                },
            }
        }
        try:
            raw = self._api_post_json("/cgi-bin/musicu.fcg", body)
        except Exception as e:
            print(f"[QQ音乐] user search POST 失败: {e}")
            raw = {}

        if raw:
            # 打印响应摘要便于调试
            top_code = raw.get("code")
            svc = raw.get("music.search.SearchCgiService", {})
            svc_code = svc.get("code")
            svc_data = svc.get("data", {})
            svc_body = svc_data.get("body", {})
            print(f"[QQ音乐] search resp: code={top_code} svc_code={svc_code} body_keys={list(svc_body.keys())}")
            # 打印各分类的数量
            for k in ("song", "singer", "album", "mv", "user", "zhida", "songlist"):
                items = svc_body.get(k, {})
                lst = items.get("list") if isinstance(items, dict) else (items if isinstance(items, list) else [])
                print(f"  {k}: {len(lst)}")

            # 从所有可能的字段提取用户
            users = []
            seen = set()
            for field in ("user", "zhida", "singer"):
                raw_data = svc_body.get(field, {})
                entries = raw_data.get("list", []) if isinstance(raw_data, dict) else (raw_data if isinstance(raw_data, list) else [])
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    uid = str(entry.get("uin") or entry.get("id") or entry.get("uid", ""))
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    nick = entry.get("nick") or entry.get("name") or entry.get("title", "")
                    avatar = entry.get("avatar") or entry.get("headurl") or entry.get("pic", "")
                    sign = entry.get("sign") or entry.get("signature") or entry.get("desc", "")
                    users.append({
                        "uid": uid,
                        "nickname": nick,
                        "avatarUrl": avatar,
                        "signature": sign,
                        "gender": entry.get("gender", 0),
                        "extra": {"uin": uid},
                    })

            if users:
                print(f"[QQ音乐] user search → {len(users)} users")
                return users[:limit]

        # ---------- 策略2: 纯数字 → 直接查 ----------
        if keyword.isdigit():
            try:
                profile = self.get_profile(keyword)
                if profile:
                    return [{
                        "uid": profile.uid,
                        "nickname": profile.nickname,
                        "avatarUrl": profile.avatar_url,
                        "signature": profile.signature,
                        "gender": profile.gender,
                    }]
            except Exception as e:
                print(f"[QQ音乐] 直接查资料失败: {e}")

        return []

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """
        获取用户资料

        通过用户主页 API 获取歌单信息, 并从中提取用户信息。
        """
        # 方式1: 尝试从 profile homepage API 获取用户信息
        resp = self._api_get_json("/rsc/fcgi-bin/fcg_get_profile_homepage.fcg", {
            "uin": uid,
            "loginUin": uid,
            "hostUin": uid,
        })

        if resp and resp.get("code") == 0:
            data = resp.get("data", {})
            # 提取用户信息
            creator = data.get("creator", {})
            if creator:
                return self._build_profile(creator, uid)

        # 方式2: 通过用户创建的公开歌单获取信息
        playlists = self._get_user_playlists_raw(uid)
        if playlists:
            # 从歌单数据中提取用户信息
            disslist = playlists.get("mydiss", []) if isinstance(playlists, dict) else playlists
            if disslist and isinstance(disslist, list) and len(disslist) > 0:
                first = disslist[0]
                creator_info = first.get("creator", {}) or {}
                if creator_info:
                    return self._build_profile(creator_info, uid)

            # 从歌单数据提取访问者信息
            visitor = playlists.get("visitor", {}) if isinstance(playlists, dict) else {}
            if visitor:
                return self._build_profile(visitor, uid)

        # 方式3: 从网页端抓取用户信息
        try:
            html = self._fetch_html(f"{self.WEB_BASE}/n/ryqq/profile/{uid}")
            if html:
                # 提取用户信息
                nickname = ""
                match = re.search(r'"nickname"\s*:\s*"([^"]+)"', html)
                if match:
                    nickname = match.group(1)
                if nickname:
                    return PlatformProfile(
                        platform="qqmusic",
                        uid=uid,
                        nickname=nickname,
                        extra={"uin": uid},
                    )
        except Exception as e:
            print(f"[QQ音乐] 网页抓取失败: {e}")

        return None

    def _get_user_playlists_raw(self, uin: str) -> dict:
        """获取用户的原始歌单数据"""
        resp = self._api_get_json("/rsc/fcgi-bin/fcg_get_profile_homepage.fcg", {
            "uin": uin,
            "loginUin": uin,
            "hostUin": uin,
        })
        if resp and resp.get("code") == 0:
            return resp.get("data", {})
        return {}

    def _build_profile(self, data: dict, uid: str) -> PlatformProfile:
        """从 API 数据构建用户资料"""
        nickname = data.get("nick") or data.get("nickname") or data.get("name", "")
        avatar_url = data.get("avatar") or data.get("headpic", "")

        # 头像 URL 补全
        if avatar_url and avatar_url.startswith("http://"):
            avatar_url = avatar_url.replace("http://", "https://")
        if avatar_url and not avatar_url.startswith("http"):
            avatar_url = f"https://y.gtimg.cn/music/photo_new/T001R300x300M000{avatar_url}.jpg"

        # QQ 音乐等级
        _level = 0
        if isinstance(data.get("level"), int):
            _level = data["level"]
        elif isinstance(data.get("lv"), int):
            _level = data["lv"]
        elif isinstance(data.get("score"), int):
            _level = min(data["score"] // 100, 100)

        return PlatformProfile(
            platform="qqmusic",
            uid=str(data.get("uin", uid)),
            nickname=nickname,
            avatar_url=avatar_url,
            signature=data.get("desc", ""),
            gender=data.get("gender", 0),
            is_vip=bool(data.get("vip") or data.get("is_vip")),
            vip_label=data.get("vip_type", ""),
            level=_level,
            extra={
                "uin": str(data.get("uin", uid)),
                "create_time": data.get("create_time", ""),
                "listen_num": data.get("listen_num", 0),
            },
        )

    # ==================== 歌单列表 ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """
        获取用户的歌单列表 (创建 + 收藏)

        返回用户创建的歌单 (mydiss) 和收藏的歌单 (otherdiss)。
        对歌手 ID 兜底返回 "热门歌曲" 列表。
        """
        items = []
        seen_ids = set()

        data = self._get_user_playlists_raw(uid)
        if data:
            # 用户创建的歌单
            mydiss = data.get("mydiss", []) if isinstance(data, dict) else data
            if isinstance(mydiss, list):
                for diss in mydiss:
                    item = self._build_content_item(diss, is_owner=True)
                    if item and item.item_id not in seen_ids:
                        seen_ids.add(item.item_id)
                        items.append(item)

            # 用户收藏的歌单
            otherdiss = data.get("otherdiss", []) if isinstance(data, dict) else []
            if isinstance(otherdiss, list):
                for diss in otherdiss:
                    item = self._build_content_item(diss, is_owner=False)
                    if item and item.item_id not in seen_ids:
                        seen_ids.add(item.item_id)
                        items.append(item)

            if items:
                return items

        return items

    @staticmethod
    def _build_content_item(diss: dict, is_owner: bool = True) -> Optional[ContentItem]:
        """从歌单数据构建统一内容项"""
        diss_id = str(diss.get("dissid", "") or diss.get("id", ""))
        if not diss_id or diss_id == "0":
            return None

        # 封面处理
        cover_url = ""
        for key in ("cover_url", "cover", "pic", "picurl", "logo", "headurl"):
            val = diss.get(key, "")
            if val:
                cover_url = val
                break

        # 数量 (歌曲数)
        count = diss.get("song_count", 0) or diss.get("cnt", 0) or diss.get("total_song_num", 0)

        # 播放量
        listen_count = diss.get("listen_count", 0) or diss.get("access_num", 0)

        return ContentItem(
            item_id=diss_id,
            title=diss.get("diss_name", diss.get("title", diss.get("name", "未命名歌单")))[:200],
            cover_url=cover_url,
            count=int(count),
            view_count=int(listen_count),
            creator=diss.get("nickname", diss.get("creator", {}).get("nick", "")) if not is_owner else "",
            description=diss.get("desc", "")[:200],
            is_owner=is_owner,
            create_time=str(diss.get("create_time", "")),
            extra={
                "type": "create" if is_owner else "collect",
                "song_ids": diss.get("song_ids", []),
                "tag": diss.get("tag", ""),
            },
        )

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        """
        获取内容详情 (含歌曲列表)

        Args:
            item_id: 歌单 ID (dissid)

        Returns:
            包含信息和歌曲列表的字典
        """
        # 普通歌单
        resp = self._api_get_json("/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg", {
            "type": 1,
            "disstid": item_id,
            "onlysong": 0,
            "utf8": 1,
        })

        if not resp or resp.get("code") != 0:
            return None

        data = resp.get("data", {}) if resp.get("data") else resp.get("cdlist", [None])[0]
        if not data:
            return None

        # 兼容两种响应格式
        if isinstance(data, list):
            data = data[0] if data else {}

        # 封面
        cover_url = ""
        for key in ("cover_url", "cover", "picurl", "logo"):
            val = data.get(key, "")
            if val:
                cover_url = val
                break

        # 歌曲列表
        songlist = data.get("songlist", [])
        items = []
        for song in songlist:
            items.append({
                "id": str(song.get("id", "") or song.get("songid", "")),
                "mid": song.get("mid", "") or song.get("songmid", ""),
                "title": song.get("title", song.get("name", "")),
                "singer": song.get("singer", song.get("singerName", "")),
                "album": song.get("album", song.get("albumname", "")),
                "duration": song.get("interval", 0),
            })

        return {
            "title": data.get("diss_name", data.get("title", "未命名"))[:200],
            "coverUrl": cover_url,
            "count": len(items),
            "viewCount": data.get("listen_count", 0),
            "description": data.get("desc", "")[:500],
            "creator": data.get("nickname", ""),
            "createTime": str(data.get("create_time", "")),
            "subscribedCount": data.get("subscriber_count", data.get("favor_count", 0)),
            "items": items,
        }

    # ==================== 收听历史 (排行) ====================

    def get_history(self, uid: str, period: str = "all") -> list[MediaEntry]:
        """
        获取用户的听歌排行

        注意: 仅登录用户可查看自己的排行。
        period: "all" = 总排行, "week" = 周排行

        实现: 通过 QQ 音乐用户主页信息获取听歌数据。
        """
        # 获取用户主页数据中的听歌信息
        data = self._get_user_playlists_raw(uid)
        if not data:
            return []

        entries = []

        # 听歌总量
        listen_num = data.get("listen_num", 0)
        if listen_num:
            entries.append(MediaEntry(
                entry_id=f"listen_total_{uid}",
                title=f"累计听歌 {listen_num} 首",
                artist_or_uploader="",
                play_count=int(listen_num),
            ))

        # 如果有详细听歌排行数据 (需要进一步 API)
        # QQ 音乐的听歌排行可能需要额外的 API 调用
        # 这里作为扩展点

        return entries

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """
        获取用户动态

        QQ 音乐的"动态"主要通过歌单创建/更新体现。
        此处将最近的歌单更新作为动态事件。
        """
        events = []
        playlists = self.get_content_lists(uid)

        for pl in playlists[:limit]:
            ts = 0
            if pl.create_time and pl.create_time.isdigit():
                ts = int(pl.create_time) * 1000

            event_type = "创建歌单" if pl.is_owner else "收藏歌单"
            events.append(EventItem(
                event_id=f"playlist_{pl.item_id}",
                event_type=event_type,
                content=f"{pl.title} ({pl.count} 首)",
                timestamp=ts,
                media_title=pl.title,
                media_artist=pl.creator,
                extra=pl.extra,
            ))

        return events

    # ==================== 社交 ====================

    def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
        """
        获取关注列表

        QQ 音乐无公开的关注列表 API，返回空。
        """
        return []

    def get_followers(self, uid: str, limit: int = 100) -> list[dict]:
        """
        获取粉丝列表

        QQ 音乐无公开的粉丝列表 API，返回空。
        """
        return []
