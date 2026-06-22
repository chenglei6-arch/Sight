"""
抖音平台适配器 — 基于 cv-cat/DouYin_Spider 的 DouyinAPI 纯 API 实现

参考项目: https://github.com/cv-cat/DouYin_Spider
参考文档: reference/DouYin_Spider-master/README.md
使用模式: reference/DouYin_Spider-master/main.py

架构说明:
  - 本适配器直接复用 reference 的 DouyinAPI 静态方法，不做 SSR 兜底
  - ref_builder/*, ref_dy_apis/*, ref_utils/* 是 DouYin_Spider 的移植模块
  - adapter.py 将这些基础 API 封装为 BasePlatformAdapter 的统一接口

用法:
    from app.platforms.douyin.adapter import DouyinAdapter
    adapter = DouyinAdapter()
    profile = adapter.get_profile("sec_uid_or_uid")
    works = adapter.get_content_lists("sec_uid")
    videos = adapter.search_content("关键词")
    comments = adapter.get_all_comments("aweme_id")

数据流:
    DouyinAPI (ref_dy_apis/douyin_api.py)
      → 直接调用静态方法，返回原始 JSON
      → adapter.py 提取字段，转化为 PlatformProfile / ContentItem / EventItem
      → BasePlatformAdapter 接口（app/platforms/base.py）
"""
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from dotenv import load_dotenv

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    EventItem,
)
from app.platforms.douyin.ref_builder.auth import DouyinAuth
from app.platforms.douyin.ref_dy_apis.douyin_api import DouyinAPI
from app.credentials import CredentialManager
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class DouyinAdapter(BasePlatformAdapter):
    """抖音平台适配器 — 纯 API 实现，参考 DouYin_Spider 的 main.py 使用模式"""

    platform_id = "douyin"
    platform_name = "抖音"

    BASE_URL = "https://www.douyin.com"

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self._auth: DouyinAuth | None = None
        self._last_request_at = 0.0
        self._session: requests.Session | None = None
        # 缓存: uid -> {"nickname": ..., "sec_uid": ..., "uid": ...}
        self._user_cache: dict[str, dict] = {}

    # ==================== 认证 ====================

    def _load_cookie_str(self) -> str:
        """加载抖音 Cookie 字符串

        优先级（用户更新 Cookie 请修改 credentials/douyin_cookie.txt）：
          1. credentials/douyin_cookie.txt — 用户自行维护的 Cookie 文件
          2. 项目根目录 .env 中的 DY_COOKIES
          3. reference/DouYin_Spider-master/.env 中的 DY_COOKIES（参考项目）
        """
        # 1. credentials/douyin_cookie.txt — 最高优先级，用户手动维护
        cookies = CredentialManager.load_cookies("douyin")
        if cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            sid = cookies.get("sessionid", "")
            print(f"[抖音] 从 credentials/douyin_cookie.txt 加载: {len(cookies)} 个字段"
                  + (f", session={sid[:10]}..." if sid else ""))
            return cookie_str

        # 2. 项目根目录 .env
        root_env = Path(__file__).parent.parent.parent.parent / ".env"
        if root_env.exists():
            load_dotenv(dotenv_path=root_env, override=True)
            dy_cookies = os.environ.get("DY_COOKIES", "")
            if dy_cookies:
                return self._parse_dy_cookie_env(dy_cookies, "根目录 .env")

        # 3. 参考项目的 .env
        ref_env = Path(__file__).parent.parent.parent.parent / "reference" / "DouYin_Spider-master" / ".env"
        if ref_env.exists():
            load_dotenv(dotenv_path=ref_env, override=True)
            dy_cookies = os.environ.get("DY_COOKIES", "")
            if dy_cookies:
                return self._parse_dy_cookie_env(dy_cookies, "参考项目 .env")

        print(f"[抖音] 警告: 未找到任何 Cookie 来源")
        return ""

    def _parse_dy_cookie_env(self, raw: str, source: str) -> str:
        """解析 .env 中的 DY_COOKIES 值"""
        raw = raw.strip().strip("'").strip('"')
        cookies = {}
        for item in raw.split("; "):
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key.strip()] = value.strip()
        if cookies.get("sessionid"):
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            print(f"[抖音] 从 {source} 加载: {len(cookies)} 个字段, session={cookies.get('sessionid','')[:10]}...")
            return cookie_str
        else:
            # 没有 sessionid 也返回，可能有部分可用
            print(f"[抖音] 从 {source} 加载: {len(cookies)} 个字段, 无sessionid")
            return "; ".join([f"{k}={v}" for k, v in cookies.items()])

    @property
    def auth(self) -> DouyinAuth:
        """获取 DouyinAuth 实例"""
        if self._auth is None:
            cookie_str = self._load_cookie_str()
            self._auth = DouyinAuth()
            self._auth.perepare_auth(cookie_str)
            has_session = "sessionid" in self._auth.cookie if self._auth.cookie else False
            print(f"[抖音] Auth 已加载: {len(self._auth.cookie or {})} 个字段, 有session={has_session}")
        return self._auth

    # ==================== 限速 ====================

    def _rate_limit(self):
        """请求间隔，防止触发反爬"""
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed + random.uniform(0, 0.5))
        self._last_request_at = time.time()

    # ==================== 工具方法 ====================

    def _get_cookie_value(self, key: str) -> str:
        cookies = CredentialManager.load_cookies("douyin")
        return cookies.get(key, "")

    @staticmethod
    def _extract_avatar_url(user: dict) -> str:
        """从用户 dict 中提取头像 URL（按优先级尝试多个字段）"""
        for key in ("avatar_thumb", "avatar_168x168", "avatar_300x300", "avatar_larger"):
            avatar = user.get(key) or {}
            if isinstance(avatar, dict):
                urls = avatar.get("url_list", [])
                if urls:
                    return urls[0]
        return ""

    def _resolve_user_info(self, uid: str) -> Optional[dict]:
        """
        将 uid（可能是数字 uid 或 sec_uid）解析为用户信息。
        参考 DouYin_Spider: DouyinAPI.get_user_info

        返回: {uid, sec_uid, nickname, ...} 或 None
        """
        # 检查缓存
        if uid in self._user_cache:
            return self._user_cache[uid]

        try:
            # 策略1: 尝试作为 sec_uid 直接请求
            user_url = f"{self.BASE_URL}/user/{uid}"
            self._rate_limit()
            user_data = DouyinAPI.get_user_info(self.auth, user_url)
            user = user_data.get("user", {})
            if user and user.get("uid"):
                info = {
                    "uid": str(user.get("uid", "")),
                    "sec_uid": user.get("sec_uid", uid),
                    "nickname": user.get("nickname", ""),
                    "avatar_url": self._extract_avatar_url(user),
                    "raw_user": user,
                }
                self._user_cache[uid] = info
                return info
        except Exception as e:
            print(f"[抖音] _resolve_user_info({uid}) API 失败: {e}")

        # 策略2: uid 是数字，检查是否是自己
        if uid.isdigit():
            try:
                my_uid = str(DouyinAPI.get_my_uid(self.auth))
                if my_uid == uid:
                    sec_uid = DouyinAPI.get_my_sec_uid(self.auth)
                    info = {"uid": uid, "sec_uid": sec_uid, "nickname": "", "avatar_url": ""}
                    self._user_cache[uid] = info
                    return info
            except Exception:
                pass

        return None

    # ==================== Status ====================

    def check_alive(self) -> bool:
        """检查凭证是否有效 — 调用 get_my_uid 验证"""
        cookies = CredentialManager.load_cookies("douyin")
        if not cookies:
            return False
        try:
            uid = DouyinAPI.get_my_uid(self.auth)
            return bool(uid)
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户信息 — 参考 DouYin_Spider main.py 的 auth 初始化"""
        try:
            uid = str(DouyinAPI.get_my_uid(self.auth))
            # get_my_sec_uid 可能失败（HTML格式变化），兜底
            sec_uid = ""
            try:
                sec_uid = DouyinAPI.get_my_sec_uid(self.auth)
            except Exception:
                pass
            # 获取用户信息
            profile = None
            if sec_uid:
                profile = self.get_profile(sec_uid)
            elif uid:
                profile = self.get_profile(uid)
            nickname = profile.nickname if profile else ""
            avatar_url = profile.avatar_url if profile else ""
            result = {
                "uid": uid,
                "sec_uid": sec_uid,
                "nickname": nickname or f"用户{uid}",
                "avatarUrl": avatar_url,
            }
            print(f"[抖音] get_login_user: {result['nickname']} (uid={uid})")
            return result
        except Exception as e:
            print(f"[抖音] get_login_user 失败: {e}")
            # 兜底：从 Cookie 获取基础信息
            cookies = CredentialManager.load_cookies("douyin")
            uid_tt = cookies.get("uid_tt", "")
            if uid_tt:
                return {"uid": uid_tt, "sec_uid": "", "nickname": "", "avatarUrl": ""}
            sessionid = cookies.get("sessionid", "")
            if sessionid:
                return {"uid": f"session_{sessionid[:8]}", "sec_uid": "", "nickname": "", "avatarUrl": ""}
            return None

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        搜索用户 — 参考 DouYin_Spider: DouyinAPI.search_some_user

        注意: 抖音搜索 API 需要新鲜的 Cookie，否则会触发 verify_check 验证码。
        如返回空结果，请更新 credentials/douyin_cookie.txt。
        获取方法: 浏览器登录抖音 → F12 → Application → Cookies → 复制全部 douyin.com 的 Cookie。
        """
        try:
            # 先检查搜索可用性（直接调用一次，检查是否有 verify_check）
            check = DouyinAPI.search_user(self.auth, keyword, "0", "5")
            nil_info = check.get("search_nil_info", {})
            if nil_info.get("search_nil_type") == "verify_check":
                print(f"[抖音] 搜索被抖音验证码拦截 (verify_check)")
                print(f"[抖音] 请更新 credentials/douyin_cookie.txt（浏览器重新登录后复制全部 Cookie）")
                return []

            users = DouyinAPI.search_some_user(self.auth, keyword, limit)
            results = []
            for u in users:
                info = u.get("user_info", {})
                results.append({
                    "uid": str(info.get("uid", "")),
                    "nickname": info.get("nickname", ""),
                    "avatarUrl": self._extract_avatar_url(info),
                    "signature": info.get("signature", ""),
                    "gender": info.get("gender", 0),
                    "sec_uid": info.get("sec_uid", ""),
                })
            print(f"[抖音] search_user '{keyword}': 找到 {len(results)} 个用户")
            return results
        except Exception as e:
            print(f"[抖音] search_user 失败: {e}")
            return []

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """
        获取用户资料 — 参考 DouYin_Spider: DouyinAPI.get_user_info

        参考 main.py:
            user_info = self.douyin_apis.get_user_info(auth, user_url)
            user_info['user'] 包含所有用户信息

        支持 sec_uid 或数字 uid 输入。
        """
        try:
            # 尝试解析用户信息
            user_info = self._resolve_user_info(uid)
            if not user_info:
                # 直接作为 sec_uid 尝试
                user_url = f"{self.BASE_URL}/user/{uid}"
                self._rate_limit()
                user_data = DouyinAPI.get_user_info(self.auth, user_url)
                raw_user = user_data.get("user", {})
                if not raw_user or not raw_user.get("uid"):
                    print(f"[抖音] get_profile: 用户不存在或接口返回空")
                    return None
                user_info = {
                    "uid": str(raw_user.get("uid", uid)),
                    "sec_uid": raw_user.get("sec_uid", uid),
                    "nickname": raw_user.get("nickname", ""),
                    "avatar_url": self._extract_avatar_url(raw_user),
                    "raw_user": raw_user,
                }
                self._user_cache[uid] = user_info

            raw_user = user_info.get("raw_user", {})
            if not raw_user:
                # 如果缓存中没有 raw_user，重新获取
                user_url = f"{self.BASE_URL}/user/{user_info['sec_uid']}"
                self._rate_limit()
                user_data = DouyinAPI.get_user_info(self.auth, user_url)
                raw_user = user_data.get("user", {})

            return self._build_profile(raw_user, user_info["uid"])
        except Exception as e:
            print(f"[抖音] get_profile 失败: {e}")
            return None

    def _build_profile(self, user: dict, uid: str) -> PlatformProfile:
        """从用户数据构建 PlatformProfile"""
        def _get(ks, kc="", d=None):
            v = user.get(ks)
            if v is not None:
                return v
            if kc:
                v = user.get(kc)
                if v is not None:
                    return v
            return d

        avatar_url = self._extract_avatar_url(user)
        cover = user.get("cover_url") or user.get("cover_thumb") or {}
        cover_url = ""
        if isinstance(cover, dict):
            covers = cover.get("url_list", [])
            cover_url = covers[0] if covers else ""

        return PlatformProfile(
            platform="douyin",
            uid=str(_get("uid", "", uid)),
            nickname=_get("nickname", "", ""),
            avatar_url=avatar_url,
            background_url=cover_url,
            signature=_get("signature", "", ""),
            gender=_get("gender", "", 0),
            birthday=_get("birthday", "", ""),
            location=" ".join(filter(None, [
                _get("country", "", ""), _get("province", "", ""), _get("city", "", ""),
            ])),
            join_time="", level=0,
            is_vip=_get("is_star", "isStar", False),
            vip_label="",
            extra={
                "follower_count": _get("follower_count", "followerCount", 0),
                "following_count": _get("following_count", "followingCount", 0),
                "aweme_count": _get("aweme_count", "awemeCount", 0),
                "total_favorited": _get("total_favorited", "totalFavorited", 0),
                "sec_uid": _get("sec_uid", "secUid", ""),
                "short_id": _get("short_id", "shortId", ""),
                "unique_id": _get("unique_id", "uniqueId", ""),
                "custom_verify": _get("custom_verify", "customVerify", ""),
            },
        )

    # ==================== 作品列表 ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """
        获取用户作品列表 — 参考 DouYin_Spider: DouyinAPI.get_user_all_work_info

        参考 main.py:
            work_list = self.douyin_apis.get_user_all_work_info(auth, user_url)
            for work_info in work_list:
                handle_work_info(work_info)
        """
        try:
            user_info = self._resolve_user_info(uid)
            if not user_info:
                return []
            sec_uid = user_info["sec_uid"]

            user_url = f"{self.BASE_URL}/user/{sec_uid}"
            self._rate_limit()
            aweme_list = DouyinAPI.get_user_all_work_info(self.auth, user_url)

            items = []
            seen_ids = set()
            for aweme in aweme_list:
                item = self._build_content_item(aweme)
                if item and item.item_id not in seen_ids:
                    seen_ids.add(item.item_id)
                    items.append(item)
            return items
        except Exception as e:
            print(f"[抖音] get_content_lists 失败: {e}")
            return []

    def _build_content_item(self, aweme: dict) -> Optional[ContentItem]:
        """从作品 JSON 构建 ContentItem"""
        if not aweme.get("aweme_id"):
            return None
        video = aweme.get("video", {})
        cover = video.get("cover", {}) or {}
        cover_urls = cover.get("url_list", []) if isinstance(cover, dict) else []
        stats = aweme.get("statistics", {})
        return ContentItem(
            item_id=str(aweme.get("aweme_id", "")),
            title=(aweme.get("desc") or "无标题")[:200],
            cover_url=cover_urls[0] if cover_urls else "",
            count=1,
            view_count=stats.get("play_count", 0),
            creator=aweme.get("author", {}).get("nickname", ""),
            description=(aweme.get("desc") or "")[:200],
            is_owner=True,
            create_time=str(aweme.get("create_time", "")),
            extra={
                "duration": video.get("duration", 0),
                "comment_count": stats.get("comment_count", 0),
                "digg_count": stats.get("digg_count", 0),
                "share_count": stats.get("share_count", 0),
            },
        )

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        """
        获取作品详情 — 参考 DouYin_Spider: DouyinAPI.get_work_info

        参考 main.py:
            res_json = self.douyin_apis.get_work_info(auth, work_url)
            data = res_json['aweme_detail']
            work_info = handle_work_info(data)
        """
        try:
            url = f"{self.BASE_URL}/video/{item_id}"
            self._rate_limit()
            resp = DouyinAPI.get_work_info(self.auth, url)
            aweme = resp.get("aweme_detail", {})
            if not aweme:
                return None
            video = aweme.get("video", {})
            cover = video.get("cover", {}) or {}
            cover_urls = cover.get("url_list", []) if isinstance(cover, dict) else []
            stats = aweme.get("statistics", {})
            return {
                "title": (aweme.get("desc") or "无标题")[:200],
                "coverUrl": cover_urls[0] if cover_urls else "",
                "count": 1,
                "viewCount": stats.get("play_count", 0),
                "description": (aweme.get("desc") or "")[:500],
                "creator": aweme.get("author", {}).get("nickname", ""),
                "createTime": str(aweme.get("create_time", "")),
                "subscribedCount": stats.get("collect_count", 0),
                "items": [],
            }
        except Exception as e:
            print(f"[抖音] get_content_detail 失败: {e}")
            return None

    # ==================== 内容搜索 ====================

    def search_content(self, keyword: str, limit: int = 25, sort_type: str = "0",
                       publish_time: str = "0", offset: str = "0",
                       filter_duration: str = "", search_range: str = "",
                       content_type: str = "") -> list[dict]:
        """
        综合搜索作品 — 参考 DouYin_Spider: DouyinAPI.search_some_general_work

        注意: 抖音搜索 API 需要新鲜的 Cookie，否则会触发 verify_check 验证码。
        """
        try:
            # 先检查搜索可用性
            check = DouyinAPI.search_general_work(
                self.auth, keyword, sort_type, publish_time, "0",
                filter_duration, search_range, content_type
            )
            nil_info = check.get("search_nil_info", {})
            if nil_info.get("search_nil_type") == "verify_check":
                print(f"[抖音] 内容搜索被验证码拦截 (verify_check)")
                print(f"[抖音] 请更新 credentials/douyin_cookie.txt（浏览器重新登录后复制全部 Cookie）")
                return []

            self._rate_limit()
            works = DouyinAPI.search_some_general_work(
                self.auth, keyword, limit, sort_type, publish_time,
                filter_duration, search_range, content_type
            )
            return [self._build_search_result(w) for w in works]
        except Exception as e:
            print(f"[抖音] search_content 失败: {e}")
            return []

    def search_video(self, keyword: str, limit: int = 25, offset: str = "0",
                     sort_type: str = "0", publish_time: str = "0",
                     filter_duration: str = "", search_range: str = "0") -> list[dict]:
        """
        视频搜索 — 参考 DouYin_Spider: DouyinAPI.search_some_video_work
        """
        try:
            self._rate_limit()
            works, _ = DouyinAPI.search_some_video_work(
                self.auth, keyword, limit, sort_type, publish_time,
                filter_duration, search_range
            )
            return [self._build_search_result(w) for w in works]
        except Exception as e:
            print(f"[抖音] search_video 失败: {e}")
            return []

    def search_live(self, keyword: str, limit: int = 25) -> list[dict]:
        """
        搜索直播 — 参考 DouYin_Spider: DouyinAPI.search_some_live
        """
        try:
            self._rate_limit()
            lives = DouyinAPI.search_some_live(self.auth, keyword, limit)
            results = []
            for live in lives:
                author = live.get("author", {})
                results.append({
                    "id": live.get("id_str", ""),
                    "title": live.get("title", ""),
                    "cover_url": self._extract_avatar_url(live),
                    "nickname": author.get("nickname", ""),
                    "user_count": live.get("user_count_str", "0"),
                    "status": live.get("status", 0),
                })
            return results
        except Exception as e:
            print(f"[抖音] search_live 失败: {e}")
            return []

    def _build_search_result(self, item: dict) -> dict:
        """统一搜索结果构建"""
        aweme = item.get("aweme_info", {})
        if not aweme:
            return item
        video = aweme.get("video", {})
        cover = video.get("cover", {}) or {}
        cover_urls = cover.get("url_list", []) if isinstance(cover, dict) else []
        stats = aweme.get("statistics", {})
        author = aweme.get("author", {})
        return {
            "aweme_id": str(aweme.get("aweme_id", "")),
            "desc": (aweme.get("desc") or "")[:200],
            "create_time": str(aweme.get("create_time", "")),
            "cover_url": cover_urls[0] if cover_urls else "",
            "duration": video.get("duration", 0),
            "play_count": stats.get("play_count", 0),
            "digg_count": stats.get("digg_count", 0),
            "comment_count": stats.get("comment_count", 0),
            "share_count": stats.get("share_count", 0),
            "author": {
                "uid": str(author.get("uid", "")),
                "nickname": author.get("nickname", ""),
                "sec_uid": author.get("sec_uid", ""),
                "avatar_url": self._extract_avatar_url(author),
            },
        }

    # ==================== 评论 ====================

    def get_comments(self, item_id: str, cursor: str = "0", count: int = 20) -> dict:
        """
        获取评论 — 参考 DouYin_Spider: DouyinAPI.get_work_out_comment

        参考 main.py:
            res_json = DouyinAPI.get_work_out_comment(auth, url, cursor)
        """
        try:
            url = f"{self.BASE_URL}/video/{item_id}"
            self._rate_limit()
            resp = DouyinAPI.get_work_out_comment(self.auth, url, cursor)
            if not resp:
                return {"comments": [], "cursor": "0", "has_more": 0}
            comments = [self._build_comment(c) for c in resp.get("comments", [])]
            return {
                "comments": comments,
                "cursor": str(resp.get("cursor", "0")),
                "has_more": resp.get("has_more", 0),
                "total": resp.get("total", 0),
            }
        except Exception as e:
            print(f"[抖音] get_comments 失败: {e}")
            return {"comments": [], "cursor": "0", "has_more": 0}

    def get_all_comments(self, item_id: str, limit: int = 200) -> list[dict]:
        """
        获取全部一级评论 — 参考 DouYin_Spider: DouyinAPI.get_work_all_out_comment
        """
        try:
            url = f"{self.BASE_URL}/video/{item_id}"
            self._rate_limit()
            comments = DouyinAPI.get_work_all_out_comment(self.auth, url)
            return [self._build_comment(c) for c in comments[:limit]]
        except Exception as e:
            print(f"[抖音] get_all_comments 失败: {e}")
            return []

    def get_reply_comments(self, item_id: str, comment_id: str, cursor: str = "0",
                           count: int = 5) -> dict:
        """
        获取评论的二级回复 — 参考 DouYin_Spider: DouyinAPI.get_work_inner_comment
        """
        try:
            comment = {"aweme_id": item_id, "cid": comment_id}
            self._rate_limit()
            resp = DouyinAPI.get_work_inner_comment(self.auth, comment, cursor, str(count))
            if not resp:
                return {"comments": [], "cursor": "0", "has_more": 0}
            comments = [self._build_comment(c) for c in resp.get("comments", [])]
            return {
                "comments": comments,
                "cursor": str(resp.get("cursor", "0")),
                "has_more": resp.get("has_more", 0),
            }
        except Exception as e:
            print(f"[抖音] get_reply_comments 失败: {e}")
            return {"comments": [], "cursor": "0", "has_more": 0}

    def _build_comment(self, c: dict) -> dict:
        """统一评论构建"""
        user = c.get("user", {})
        return {
            "cid": str(c.get("cid", "")),
            "text": c.get("text", "")[:500],
            "create_time": str(c.get("create_time", 0)),
            "digg_count": c.get("digg_count", 0),
            "reply_comment_total": c.get("reply_comment_total", 0),
            "user": {
                "uid": str(user.get("uid", "")),
                "nickname": user.get("nickname", ""),
                "avatar_url": self._extract_avatar_url(user),
                "sec_uid": user.get("sec_uid", ""),
            },
            "has_more_reply": c.get("reply_comment_total", 0) > 0,
        }

    # ==================== 关注/粉丝 ====================

    def get_follows(self, uid: str, limit: int = 500) -> list[dict]:
        """
        获取关注列表 — 参考 DouYin_Spider: DouyinAPI.get_some_user_following_list

        参考 douyin_api.py:
            DouyinAPI.get_some_user_following_list(auth, user_id, sec_id, num)
        """
        try:
            user_info = self._resolve_user_info(uid)
            if not user_info:
                return []
            user_id = user_info["uid"]
            sec_uid = user_info["sec_uid"]
            self._rate_limit()
            follows = DouyinAPI.get_some_user_following_list(self.auth, user_id, sec_uid, limit)
            return [{
                "uid": str(f.get("uid", "")),
                "nickname": f.get("nickname", ""),
                "avatarUrl": self._extract_avatar_url(f),
                "signature": f.get("signature", ""),
                "gender": f.get("gender", 0),
                "sec_uid": f.get("sec_uid", ""),
            } for f in follows]
        except Exception as e:
            print(f"[抖音] get_follows 失败: {e}")
            return []

    def get_followers(self, uid: str, limit: int = 500) -> list[dict]:
        """
        获取粉丝列表 — 参考 DouYin_Spider: DouyinAPI.get_some_user_follower_list
        """
        try:
            user_info = self._resolve_user_info(uid)
            if not user_info:
                return []
            user_id = user_info["uid"]
            sec_uid = user_info["sec_uid"]
            self._rate_limit()
            followers = DouyinAPI.get_some_user_follower_list(self.auth, user_id, sec_uid, limit)
            return [{
                "uid": str(f.get("uid", "")),
                "nickname": f.get("nickname", ""),
                "avatarUrl": self._extract_avatar_url(f),
                "signature": f.get("signature", ""),
                "gender": f.get("gender", 0),
                "sec_uid": f.get("sec_uid", ""),
            } for f in followers]
        except Exception as e:
            print(f"[抖音] get_followers 失败: {e}")
            return []

    # ==================== 推荐 Feed ====================

    def get_feed(self, count: int = 20, refresh_index: str = "2") -> list[dict]:
        """
        获取首页推荐视频 — 参考 DouYin_Spider: DouyinAPI.get_feed

        注意: 当前 feed 接口返回空内容（抖音 API 变更），暂不可用。
        """
        try:
            self._rate_limit()
            resp = DouyinAPI.get_feed(self.auth, str(count), refresh_index)
            aweme_list = resp.get("aweme_list", [])
            if not aweme_list:
                print(f"[抖音] get_feed 返回空（接口可能已被抖音变更）")
                return []

            results = []
            seen_ids = set()
            for aweme in aweme_list:
                aweme_id = str(aweme.get("aweme_id", ""))
                if aweme_id and aweme_id not in seen_ids:
                    seen_ids.add(aweme_id)
                    video = aweme.get("video", {})
                    cover = video.get("cover", {}) or {}
                    cover_urls = cover.get("url_list", []) if isinstance(cover, dict) else []
                    stats = aweme.get("statistics", {})
                    author = aweme.get("author", {})
                    results.append({
                        "aweme_id": aweme_id,
                        "desc": (aweme.get("desc") or "")[:200],
                        "create_time": str(aweme.get("create_time", "")),
                        "cover_url": cover_urls[0] if cover_urls else "",
                        "duration": video.get("duration", 0),
                        "play_count": stats.get("play_count", 0),
                        "digg_count": stats.get("digg_count", 0),
                        "comment_count": stats.get("comment_count", 0),
                        "share_count": stats.get("share_count", 0),
                        "author": {
                            "uid": str(author.get("uid", "")),
                            "nickname": author.get("nickname", ""),
                            "sec_uid": author.get("sec_uid", ""),
                            "avatar_url": self._extract_avatar_url(author),
                        },
                    })
            return results[:count]
        except requests.exceptions.JSONDecodeError:
            print(f"[抖音] get_feed 响应为空（抖音 API 变更，接口可能已失效）")
            return []
        except Exception as e:
            print(f"[抖音] get_feed 失败: {e}")
            return []

    # ==================== 互动操作 ====================

    def digg_aweme(self, aweme_id: str, digg_type: str = "1") -> bool:
        """
        点赞/取消点赞视频 — 参考 DouYin_Spider: DouyinAPI.digg

        参考 douyin_api.py:
            DouyinAPI.digg(auth, aweme_id, digg_type)
            digg_type: "1" 点赞, "0" 取消点赞
        """
        try:
            self._rate_limit()
            result = DouyinAPI.digg(self.auth, aweme_id, digg_type)
            return result
        except Exception as e:
            print(f"[抖音] digg_aweme 失败: {e}")
            return False

    def publish_comment(self, aweme_id: str, content: str, reply_id: str = "") -> Optional[dict]:
        """
        发布评论 — 参考 DouYin_Spider: DouyinAPI.publish_comment

        参考 douyin_api.py:
            DouyinAPI.publish_comment(auth, aweme_id, content, reply_id)
        """
        try:
            self._rate_limit()
            result = DouyinAPI.publish_comment(self.auth, aweme_id, content, reply_id)
            return result
        except Exception as e:
            print(f"[抖音] publish_comment 失败: {e}")
            return None

    def collect_aweme(self, aweme_id: str, action: str = "1") -> Optional[dict]:
        """
        收藏/取消收藏视频 — 参考 DouYin_Spider: DouyinAPI.collect_aweme

        参考 douyin_api.py:
            DouyinAPI.collect_aweme(auth, aweme_id, action)
            action: "1" 收藏, "0" 取消收藏
        """
        try:
            self._rate_limit()
            result = DouyinAPI.collect_aweme(self.auth, aweme_id, action)
            return result
        except Exception as e:
            print(f"[抖音] collect_aweme 失败: {e}")
            return None

    def get_notice_list(self, limit: int = 20, notice_group: str = "700") -> list[dict]:
        """
        获取消息通知 — 参考 DouYin_Spider: DouyinAPI.get_some_notice_list

        参考 douyin_api.py:
            DouyinAPI.get_some_notice_list(auth, num, notice_group)
            notice_group: 700 全部消息, 401 粉丝, 601 @我的, 2 评论, 3 点赞, 520 弹幕
        """
        try:
            self._rate_limit()
            notices = DouyinAPI.get_some_notice_list(self.auth, limit, notice_group)
            return notices
        except Exception as e:
            print(f"[抖音] get_notice_list 失败: {e}")
            return []

    # ==================== Events ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """
        获取用户动态 — 基于作品列表构建

        参考 DouYin_Spider main.py:
            work_list = self.douyin_apis.get_user_all_work_info(auth, user_url)
            # 每个作品视为一个动态事件
        """
        items = self.get_content_lists(uid)
        events = []
        for item in items[:limit]:
            ts = 0
            if item.create_time and item.create_time.isdigit():
                raw_ts = int(item.create_time)
                if raw_ts > 1000000000000:  # 毫秒级
                    ts = raw_ts
                else:  # 秒级 → 转毫秒
                    ts = raw_ts * 1000
            events.append(EventItem(
                event_id=item.item_id,
                event_type="发布作品",
                content=item.title,
                timestamp=ts,
                media_title=item.title,
                media_artist=item.creator,
                extra=item.extra,
            ))
        return events

    def get_history(self, uid: str, period: str = "all") -> list:
        """抖音暂无听歌历史"""
        return []
