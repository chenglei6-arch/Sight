"""
QQ音乐平台适配器

基于 y.qq.com / c.y.qq.com 公开 API 的数据采集实现。

API 说明:
  - 大部分接口位于 c.y.qq.com 域名下
  - 需要 Referer: https://y.qq.com 防盗链
  - 返回 JSONP 格式 (需提取 callback)
  - g_tk 参数用于鉴权 (未登录=5381)

数据结构:
  - 用户标识: uin (QQ 号) 或 encrypt_uin (加密标识, 带 ** 后缀)
  - 歌单 (Playlist) 是 QQ 音乐的核心内容组织形式
  - 用户可创建和收藏歌单

核心策略 (精简版):
  搜索: musicu.fcg search_type=8 (唯一方式，需 Cookie)
  资料: 手机版 SSR 页面 i.y.qq.com (唯一方式，支持 uin 和 encrypt_uin)
  歌单: 手机版 SSR 页面 DissList 提取
"""
import json
import random
import re
import subprocess
import time
from typing import Optional
from urllib.parse import quote

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
        # 用户搜索缓存: encrypt_uin → {nickname, avatar_url, encrypt_uin}
        # 用于搜索结果直接返回资料，避免二次请求
        self._user_cache: dict[str, dict] = {}
        # SSR 页面缓存: uid → (html, timestamp)
        # 避免 profile、歌单、events 重复请求同一页面
        self._ssr_page_cache: dict[str, tuple[str, float]] = {}

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

    def _curl_get(self, url: str, timeout: int = 15) -> str:
        """
        使用 curl 发起 HTTP GET 请求（带当前会话 Cookie）。

        Python requests 对某些 QQ 音乐域名 (i.y.qq.com, i2.y.qq.com)
        存在 SSL 握手问题 (SSLEOFError)，curl 可正常访问。
        """
        try:
            cmd = [
                "curl", "-s", "--max-time", str(timeout),
                "-L",  # 跟随重定向
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "-H", "Referer: https://y.qq.com/",
                "-H", "Accept-Language: zh-CN,zh;q=0.9",
            ]
            # 传递当前会话的 Cookie
            cookie_str = self._get_curl_cookie_str()
            if cookie_str:
                cmd.extend(["-H", f"Cookie: {cookie_str}"])
            cmd.append(url)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
            return ""
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[QQ音乐] curl 请求异常: {e}")
            return ""

    def _get_curl_cookie_str(self) -> str:
        """从当前会话提取 Cookie 字符串传给 curl"""
        try:
            parts = []
            for c in self.session.cookies:
                if c.value:
                    parts.append(f"{c.name}={c.value}")
            return "; ".join(parts)
        except Exception:
            return ""

    def _fetch_html(self, url: str) -> str:
        """
        请求页面 HTML。

        优先使用 Python requests，SSL 失败时降级为 curl。
        """
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    return resp.text
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
            except requests.RequestException as e:
                err_str = str(e)
                # SSL 错误降级到 curl
                if "SSLError" in err_str or "EOF occurred" in err_str:
                    print(f"[QQ音乐] SSL 错误，降级为 curl: {url[:60]}...")
                    curl_result = self._curl_get(url, timeout=REQUEST_TIMEOUT)
                    if curl_result:
                        return curl_result
                    print(f"[QQ音乐] curl 也失败")
                else:
                    print(f"[QQ音乐] 页面请求异常: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)
        return ""

    def _fetch_ssr_page(self, uid: str) -> str:
        """
        获取并缓存 SSR 页面内容。

        缓存 30 秒，避免 profile、歌单、events 多次请求同一页面。
        """
        now = time.time()
        cached = self._ssr_page_cache.get(uid)
        if cached and (now - cached[1]) < 30:
            return cached[0]

        html = self._fetch_html(
            f"https://i.y.qq.com/n2/m/share/profile_v2/index.html?userid={quote(uid)}"
        )
        if html:
            self._ssr_page_cache[uid] = (html, now)
        return html

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
        uin = ""
        for key in ("uin", "qqmusic_uin", "loginUin"):
            val = cookies.get(key, "")
            if val:
                uin = val
                break

        if uin:
            return {"uid": uin, "nickname": "", "avatarUrl": ""}
        return None

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        搜索用户

        唯一方式: musicu.fcg search_type=8 (需 Cookie 登录态)
        """
        users = self._search_via_musicu_fcg(keyword, limit)
        return users[:limit] if users else []

    def _search_via_musicu_fcg(self, keyword: str, limit: int = 20) -> list[dict]:
        """musicu.fcg 网关搜索 (需 Cookie 登录态)"""
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
            print(f"[QQ音乐] musicu.fcg 搜索失败: {e}")
            return []

        if not raw:
            return []

        svc = raw.get("music.search.SearchCgiService", {})
        svc_body = svc.get("data", {}).get("body", {})

        users = []
        seen = set()
        for field in ("user", "zhida", "singer"):
            raw_data = svc_body.get(field, {})
            entries = raw_data.get("list", []) if isinstance(raw_data, dict) else (
                raw_data if isinstance(raw_data, list) else []
            )
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                raw_uin = str(entry.get("uin") or "")
                encrypt_uin = str(entry.get("encrypt_uin", "") or "")
                # 优先用真实 QQ 号，否则用 encrypt_uin
                display_uid = raw_uin if raw_uin.isdigit() else (encrypt_uin if encrypt_uin else raw_uin)
                if not display_uid or display_uid in seen:
                    continue
                seen.add(display_uid)
                nick = entry.get("nick") or entry.get("name") or entry.get("title", "")
                avatar = entry.get("avatar") or entry.get("headurl") or entry.get("pic", "")
                sign = entry.get("sign") or entry.get("signature") or entry.get("desc", "")
                users.append({
                    "uid": display_uid,
                    "nickname": nick,
                    "avatarUrl": avatar,
                    "signature": sign,
                    "gender": entry.get("gender", 0),
                    "type": field,
                    "extra": {"uin": raw_uin, "encrypt_uin": encrypt_uin},
                })
                # 缓存用户信息，供 get_profile 和 get_follows/get_followers 查询
                cache_key = encrypt_uin if encrypt_uin else raw_uin
                if cache_key:
                    self._user_cache[cache_key] = {
                        "nickname": nick,
                        "avatar_url": avatar,
                        "signature": sign,
                        "encrypt_uin": encrypt_uin,
                        "uin": raw_uin,  # 保存原始 uin（可能是空字符串）
                        "type": field,
                    }
                    # 也缓存不带 ** 的版本
                    if encrypt_uin:
                        clean = encrypt_uin.rstrip("*")
                        if clean and clean != encrypt_uin:
                            self._user_cache[clean] = self._user_cache[encrypt_uin]

        if users:
            print(f"[QQ音乐] musicu.fcg 搜索 → {len(users)} 个用户")
        return users

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """
        获取用户资料

        唯一方式: 手机版 SSR 页面 (支持 uin 和 encrypt_uin)
        优先返回搜索缓存结果。
        """
        uid = str(uid).strip()
        if not uid:
            return None

        # 检查搜索缓存（如果搜索结果缓存了用户信息，直接返回）
        cached = self._user_cache.get(uid) or self._user_cache.get(uid + "**")
        if cached:
            avatar = cached.get("avatar_url", "") or ""
            return PlatformProfile(
                platform="qqmusic",
                uid=uid,
                nickname=cached.get("nickname", uid),
                avatar_url=avatar,
                signature=cached.get("signature", ""),
                gender=0,
                extra={"uin": uid, "source": "user_cache", "encrypt_uin": cached.get("encrypt_uin", "")},
            )

        # 手机版 SSR 页面
        return self._get_profile_via_mobile_ssr(uid)

    @staticmethod
    def _extract_js_string(html: str, var_name: str) -> str:
        """
        从 HTML 中提取 JS 字符串变量的值（正确处理转义引号）。

        JS 中 var="value" 格式，正确处理 \\" 转义。
        """
        idx = html.find(f'{var_name}=')
        if idx < 0:
            return ""

        rest = html[idx + len(var_name) + 1:]
        if not rest or rest[0] != '"':
            return ""

        rest = rest[1:]
        result = []
        i = 0
        while i < len(rest):
            ch = rest[i]
            if ch == '\\':
                if i + 1 < len(rest):
                    result.append(rest[i:i+2])
                    i += 2
                else:
                    result.append(ch)
                    i += 1
            elif ch == '"':
                return ''.join(result)
            else:
                result.append(ch)
                i += 1
        return ''.join(result)

    def _get_profile_via_mobile_ssr(self, uid: str) -> Optional[PlatformProfile]:
        """
        通过 QQ 音乐手机版 SSR 页面获取用户资料。

        使用 i.y.qq.com/n2/m/share/profile_v2/index.html?userid={uid}
        的 SSR 内嵌数据，支持真实 QQ 号和 encrypt_uin 两种标识。

        注: i.y.qq.com / i2.y.qq.com 有 SSL 问题，Python requests 无法连接，
        内部自动降级为 curl 获取。
        """
        uid = str(uid).strip()
        if not uid:
            return None

        try:
            html = self._fetch_ssr_page(uid)
            if not html:
                return None

            raw = self._extract_js_string(html, "__ssrFirstPageData__")
            if not raw:
                return None

            # 解析双编码 JSON
            try:
                inner = json.loads('"' + raw + '"')
                data = json.loads(inner)
            except json.JSONDecodeError:
                s = raw.replace('\\"', '"').replace('\\u002F', '/').replace('\\n', '')
                try:
                    data = json.loads(s)
                except json.JSONDecodeError:
                    return None

            home_data = data.get("homeData", {})
            page_data = home_data.get("data", {}) if isinstance(home_data, dict) else {}
            info = page_data.get("Info", {})
            base = info.get("BaseInfo", {}) if isinstance(info, dict) else {}

            nickname = base.get("Name", "") or base.get("name", "")
            encrypt_uin = base.get("EncryptedUin", "") or ""
            avatar = base.get("Avatar", "") or ""
            big_avatar = base.get("BigAvatar", "") or ""

            if not nickname:
                return None

            # 性别
            gender = 0
            if isinstance(info, dict):
                gender_info = info.get("Gender", {})
                if isinstance(gender_info, dict):
                    gs = gender_info.get("Gender", "")
                    if gs == "男":
                        gender = 1
                    elif gs == "女":
                        gender = 2

            extra = {"uin": uid, "source": "mobile_ssr", "encrypt_uin": encrypt_uin}
            # 访客/粉丝/关注/朋友数 (SSR 页面统计信息)
            if isinstance(info, dict):
                for k in ("VisitorNum", "FansNum", "FriendsNum", "FollowNum"):
                    v = info.get(k, {})
                    if isinstance(v, dict) and v.get("Num"):
                        extra[f"m{k}"] = v.get("Num")

            # 缓存
            if encrypt_uin:
                self._user_cache[encrypt_uin] = {
                    "nickname": nickname, "avatar_url": avatar or big_avatar,
                    "signature": "", "encrypt_uin": encrypt_uin, "type": "user",
                }
                clean = encrypt_uin.rstrip("*")
                if clean and clean != encrypt_uin:
                    self._user_cache[clean] = self._user_cache[encrypt_uin]

            return PlatformProfile(
                platform="qqmusic", uid=uid, nickname=nickname,
                avatar_url=avatar or big_avatar,
                signature=base.get("signature", "") or base.get("desc", "") or "",
                gender=gender, extra=extra,
            )

        except Exception as e:
            print(f"[QQ音乐] 手机版 SSR 获取失败 ({uid}): {e}")
            return None

    # ==================== 歌单 ====================

    def _get_playlists_via_mobile_ssr(self, uid: str) -> list[ContentItem]:
        """
        通过手机版 SSR 页面提取用户的歌单列表。

        手机版资料页面的 IntroductionTab DissList 包含公开歌单。
        使用 _fetch_ssr_page 避免重复请求（与 profile 共享 SSR 缓存）。
        """
        uid = str(uid).strip()
        if not uid:
            return []

        items = []
        seen = set()

        try:
            html = self._fetch_ssr_page(uid)
            if not html:
                return []

            raw = self._extract_js_string(html, "__ssrFirstPageData__")
            if not raw:
                return []

            try:
                inner = json.loads('"' + raw + '"')
                data = json.loads(inner)
            except json.JSONDecodeError:
                s = raw.replace('\\"', '"').replace('\\u002F', '/').replace('\\n', '')
                try:
                    data = json.loads(s)
                except json.JSONDecodeError:
                    return []

            home_data = data.get("homeData", {})
            page_data = home_data.get("data", {}) if isinstance(home_data, dict) else {}
            tab_detail = page_data.get("TabDetail", {}) if isinstance(page_data, dict) else {}
            intro_tab = tab_detail.get("IntroductionTab", {}) if isinstance(tab_detail, dict) else {}
            intro_list = intro_tab.get("List", []) if isinstance(intro_tab, dict) else []

            for section in intro_list:
                if not isinstance(section, dict):
                    continue
                if section.get("ItemType") == 10:
                    diss_data = section.get("DissList")
                    if not diss_data:
                        continue
                    # DissList 可能是 [{"list": [...], "title": "..."}] 或 {"list": [...]}
                    if isinstance(diss_data, list):
                        for group in diss_data:
                            if not isinstance(group, dict):
                                continue
                            diss_items = group.get("list", [])
                            if not isinstance(diss_items, list):
                                continue
                            for diss in diss_items:
                                item = self._diss_to_content_item(diss, seen)
                                if item:
                                    items.append(item)
                    elif isinstance(diss_data, dict):
                        diss_items = diss_data.get("list", [])
                        if isinstance(diss_items, list):
                            for diss in diss_items:
                                item = self._diss_to_content_item(diss, seen)
                                if item:
                                    items.append(item)

            if items:
                print(f"[QQ音乐] 手机版 SSR 获取到 {len(items)} 个歌单")
            return items

        except Exception as e:
            print(f"[QQ音乐] 手机版 SSR 歌单提取失败: {e}")
            return []

    def _diss_to_content_item(self, diss: dict, seen: set) -> Optional[ContentItem]:
        """从 DissList 中的单个歌单条目构建 ContentItem"""
        if not isinstance(diss, dict):
            return None
        did = str(diss.get("dissid", "") or "")
        if not did or did in seen:
            return None
        seen.add(did)
        title = diss.get("title", "") or "未命名歌单"
        pic = diss.get("picurl", "") or diss.get("pic", "") or ""
        subtitle = diss.get("subtitle", "") or ""
        song_count = 0
        play_count = 0
        sc = re.search(r'(\d+)首', subtitle)
        if sc:
            song_count = int(sc.group(1))
        pc = re.search(r'(\d+)次播放', subtitle)
        if pc:
            play_count = int(pc.group(1))
        return ContentItem(
            item_id=did, title=title[:200], cover_url=pic,
            count=song_count, view_count=play_count,
            description="", is_owner=True,
            extra={"type": "create", "source": "mobile_ssr"},
        )

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """
        获取用户的歌单列表

        唯一方式: 手机版 SSR 页面提取 DissList
        """
        try:
            items = self._get_playlists_via_mobile_ssr(uid)
            if items:
                return items
        except Exception as e:
            print(f"[QQ音乐] 手机版 SSR 歌单获取失败: {e}")

        return []

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        """
        获取内容详情 (含歌曲列表)

        Args:
            item_id: 歌单 ID (dissid)

        Returns:
            包含信息和歌曲列表的字典
        """
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

        QQ 音乐无公开的听歌排行 API，返回空。
        """
        return []

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

    # ==================== 社交 (关注/粉丝) ====================

    # 关注/粉丝列表 API 路径
    FOLLOW_API_PATH = "/splcloud/fcgi-bin/friend_follow_or_listen_list.fcg"

    @staticmethod
    def _parse_jsonp_loose(text: str) -> dict:
        """
        解析 QQ 音乐的松散 JSONP 响应。

        格式: JSONCallBack({"code":0, retcode:0, total:2, list:[{uin:123, nick_name:"xx"}]})
        特点: JSONP 包裹 + 属性名可能未加引号
        """
        if not text:
            return {}

        # 去掉 JSONP 包裹
        m = re.search(r'^\w+\((.+)\);?\s*$', text.strip(), re.DOTALL)
        if m:
            inner = m.group(1)
        else:
            inner = text.strip()

        # 尝试标准 JSON 解析
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass

        # 松散解析: 给未引号的属性名加上引号
        # 匹配 {key: 或 ,key: 模式 (key 为字母/数字/下划线)
        fixed = re.sub(
            r'([{,]\s*)([a-zA-Z_]\w*)(\s*:)',
            r'\1"\2"\3',
            inner
        )
        # 单引号转双引号
        fixed = fixed.replace("'", '"')
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {}

    def _fetch_follow_list(self, uin: str, start: int, num: int, is_listen: int = 0) -> Optional[dict]:
        """
        获取关注/粉丝列表单页数据。

        Args:
            uin: QQ 号
            start: 起始位置
            num: 每页数量
            is_listen: 0=关注列表, 1=粉丝列表

        Returns:
            解析后的响应 dict, 包含 total, list 等字段
        """
        # 粉丝 API (is_listen=1) 在大 V 账号上经常超时，减少重试次数
        max_attempts = 1 if is_listen else MAX_RETRIES
        for attempt in range(max_attempts):
            try:
                self._rate_limit()
                params = {
                    "utf8": 1,
                    "start": start,
                    "num": num,
                    "uin": uin,
                    "format": "json",
                    "g_tk": self._g_tk,  # 使用 session 的真实 g_tk
                }
                if is_listen:
                    params["is_listen"] = 1

                # 粉丝列表可能很慢（大 V 用户），使用更长 timeout
                # 但只等一次，超时就放弃
                follow_timeout = 30 if is_listen else REQUEST_TIMEOUT

                resp = self.session.get(
                    f"{self.API_BASE}{self.FOLLOW_API_PATH}",
                    params=params,
                    timeout=follow_timeout,
                )
                if resp.status_code == 200:
                    data = self._parse_jsonp_loose(resp.text)
                    if data and data.get("code") == 0:
                        return data
                    if data and data.get("code") == 1101:
                        # 参数错误（可能是 encrypt_uin 无法查询）
                        return None
                elif resp.status_code == 500 and is_listen:
                    # 粉丝 API 服务端错误，无需重试
                    return None
                if attempt < max_attempts - 1:
                    time.sleep(1)
            except requests.RequestException as e:
                print(f"[QQ音乐] 关注/粉丝请求异常: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(1)
        return None

    def _resolve_real_uin(self, uid: str) -> Optional[str]:
        """
        尝试将 uid (可能是 encrypt_uin) 转为真实 QQ 号。

        从缓存中查找搜索时保存的真实 uin。
        """
        # 如果已经是纯数字，直接返回
        if uid.isdigit():
            return uid

        # 检查缓存: 搜索时保存的真实 uin
        for key in (uid, uid.rstrip("*"), uid + "**"):
            cached = self._user_cache.get(key)
            if cached:
                cached_uin = cached.get("uin", "")
                if cached_uin.isdigit():
                    return cached_uin
                # 有加密 uin 但没有真实 uin
                return None

        return None

    def _parse_follow_item(self, item: dict) -> dict:
        """解析关注/粉丝条目为标准格式，并缓存发现的真实 QQ 号"""
        nick = item.get("nick_name", "") or item.get("nick", "") or item.get("name", "")
        logo = item.get("logo", "") or item.get("headurl", "") or item.get("avatar", "")
        uin = str(item.get("uin", ""))
        encrypt_uin = str(item.get("encrypt_uin", "") or "")
        uid = encrypt_uin if encrypt_uin else uin

        # 缓存发现的真实 QQ 号，供后续查询
        if uin.isdigit() and encrypt_uin:
            self._user_cache[encrypt_uin] = {
                "nickname": nick,
                "avatar_url": logo,
                "signature": item.get("desc", "")[:200] if item.get("desc") else "",
                "encrypt_uin": encrypt_uin,
                "uin": uin,
                "type": "user",
            }
            clean = encrypt_uin.rstrip("*")
            if clean and clean != encrypt_uin:
                self._user_cache[clean] = self._user_cache[encrypt_uin]

        return {
            "uid": uid,
            "uin": uin,
            "encrypt_uin": encrypt_uin,
            "nickname": nick,
            "avatarUrl": logo if logo.startswith("http") else "",
            "avatar": logo,
            "signature": item.get("desc", "")[:200] if item.get("desc") else "",
            "is_follow": item.get("is_follow", 0),
            "follow_time": item.get("follow_time", 0),
            "listen_num": item.get("listen_num", 0),
            "songlist_num": item.get("songlist_num", 0),
            "follow_num": item.get("follow_num", 0),
        }

    def _try_get_ssr_count(self, uid: str, field: str) -> Optional[int]:
        """
        尝试从 SSR 缓存中获取关注/粉丝等统计数字。

        Args:
            uid: 用户 ID
            field: Info 中的字段名 (FollowNum/FansNum)

        Returns:
            数字或 None
        """
        try:
            html = self._fetch_ssr_page(uid)
            if not html:
                return None
            raw = self._extract_js_string(html, "__ssrFirstPageData__")
            if not raw:
                return None
            inner = json.loads('"' + raw + '"')
            data = json.loads(inner)
            home_data = data.get("homeData", {})
            page_data = home_data.get("data", {}) if isinstance(home_data, dict) else {}
            info = page_data.get("Info", {}) if isinstance(page_data, dict) else {}
            v = info.get(field, {})
            if isinstance(v, dict):
                return v.get("Num")
        except Exception:
            pass
        return None

    def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
        """
        获取用户的关注列表 (他关注了谁)。

        支持分页查询。
        对于 encrypt_uin 用户，API 无法返回关注列表（需要真实 QQ 号），
        但 SSR 页面有 FollowNum（关注总数），会以特殊标记返回。
        """
        uid = str(uid).strip()
        if not uid:
            return []

        # 解析真实 QQ 号
        real_uin = self._resolve_real_uin(uid)
        if not real_uin:
            if uid.isdigit():
                real_uin = uid
            else:
                print(f"[QQ音乐] 关注列表: {uid} 是加密用户，尝试从 SSR 获取关注数")
                # SSR 页面的 FollowNum
                ssr_count = self._try_get_ssr_count(uid, "FollowNum")
                if ssr_count is not None:
                    print(f"[QQ音乐] SSR 关注数: {ssr_count}")
                    return [{
                        "_count_only": True,
                        "count": ssr_count,
                        "uid": uid,
                        "nickname": f"关注了 {ssr_count} 人",
                        "avatarUrl": "",
                        "note": "QQ音乐隐藏了此用户的QQ号，无法获取详细关注列表",
                    }]
                return []

        # 分页获取所有关注
        all_items = []
        page_size = min(limit, 40)
        start = 0

        while len(all_items) < limit:
            data = self._fetch_follow_list(real_uin, start, page_size, is_listen=0)
            if not data:
                break

            total = data.get("total", 0)
            items = data.get("list", [])
            if not items:
                break

            for item in items:
                if len(all_items) >= limit:
                    break
                all_items.append(self._parse_follow_item(item))

            start += page_size
            if start >= total or len(items) < page_size:
                break

        if all_items:
            print(f"[QQ音乐] 关注列表: {len(all_items)} 人")
        return all_items

    def get_followers(self, uid: str, limit: int = 100) -> list[dict]:
        """
        获取用户的粉丝列表 (谁关注了他)。

        支持分页查询。
        对于 encrypt_uin 用户，API 无法返回粉丝列表（需要真实 QQ 号），
        但 SSR 页面有 FansNum（粉丝总数），会以特殊标记返回。

        注意: QQ 音乐的粉丝 API (is_listen=1) 服务端不稳定，大 V 用户会超时，
        此时返回空列表，但粉丝数可从 SSR 页面获取。
        """
        uid = str(uid).strip()
        if not uid:
            return []

        # 解析真实 QQ 号
        real_uin = self._resolve_real_uin(uid)
        if not real_uin:
            if uid.isdigit():
                real_uin = uid
            else:
                print(f"[QQ音乐] 粉丝列表: {uid} 是加密用户，尝试从 SSR 获取粉丝数")
                ssr_count = self._try_get_ssr_count(uid, "FansNum")
                if ssr_count is not None:
                    print(f"[QQ音乐] SSR 粉丝数: {ssr_count}")
                    return [{
                        "_count_only": True,
                        "count": ssr_count,
                        "uid": uid,
                        "nickname": f"{ssr_count} 位粉丝",
                        "avatarUrl": "",
                        "note": "QQ音乐隐藏了此用户的QQ号，无法获取详细粉丝列表",
                    }]
                return []

        # 分页获取所有粉丝
        all_items = []
        page_size = min(limit, 40)
        start = 0

        while len(all_items) < limit:
            data = self._fetch_follow_list(real_uin, start, page_size, is_listen=1)
            if not data:
                break

            total = data.get("total", 0)
            items = data.get("list", [])
            if not items:
                break

            for item in items:
                if len(all_items) >= limit:
                    break
                all_items.append(self._parse_follow_item(item))

            start += page_size
            if start >= total or len(items) < page_size:
                break

        if all_items:
            print(f"[QQ音乐] 粉丝列表: {len(all_items)} 人")
        return all_items
