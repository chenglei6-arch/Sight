"""
抖音平台适配器 — 基于 chenglei6-arch/DouYin_Spider（cv-cat/DouYin_Spider 的 fork）的纯 API 实现

上游与同步约定见 docs/UPSTREAM_SYNC.md（含 following 列表 max_time 修复说明）。

架构说明:
  - 本适配器直接复用上游的 DouyinAPI 静态方法，不做 SSR 兜底
  - ref_builder/*, ref_dy_apis/*, ref_utils/* 是上游的移植模块
  - adapter.py 将这些基础 API 封装为 BasePlatformAdapter 的统一接口

用法:
    from app.platforms.douyin.adapter import DouyinAdapter
    adapter = DouyinAdapter()
    profile = adapter.get_profile("sec_uid_or_uid")
    works = adapter.get_content_lists("sec_uid")

数据流:
    DouyinAPI (ref_dy_apis/douyin_api.py)
      → 直接调用静态方法，返回原始 JSON
      → adapter.py 提取字段，转化为 PlatformProfile / ContentItem / EventItem
      → BasePlatformAdapter 接口（app/platforms/base.py）
"""
import json
import random
import re
import threading
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
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


def _douyin_verified(u: dict) -> bool:
    """抖音认证判定：user_verified 布尔或 custom_verify 有内容（个人/机构认证）"""
    return bool(u.get("user_verified")) or bool(u.get("custom_verify"))


class DouyinAdapter(BasePlatformAdapter):
    """抖音平台适配器 — 纯 API 实现，参考 DouYin_Spider 的 main.py 使用模式"""

    platform_id = "douyin"
    platform_name = "抖音"

    BASE_URL = "https://www.douyin.com"

    def __init__(self, credentials: dict = None, account_id: str = None):
        super().__init__(credentials, account_id)
        self._auth: DouyinAuth | None = None
        self._last_request_at = 0.0
        # /graph 接口会从多个线程并发调用本适配器，限流必须串行化
        self._rl_lock = threading.Lock()
        self._session: requests.Session | None = None
        # 缓存: uid -> {"nickname": ..., "sec_uid": ..., "uid": ..., "_cached_at": ts}
        self._user_cache: dict[str, dict] = {}

    # ==================== 用户信息缓存（TTL 30 分钟） ====================

    USER_CACHE_TTL = 30 * 60  # 粉丝数/作品数等随 raw_user 一起缓存，过期必须重拉

    def _cache_get_user(self, uid: str) -> Optional[dict]:
        info = self._user_cache.get(uid)
        if info and time.time() - info.get("_cached_at", 0) < self.USER_CACHE_TTL:
            return info
        return None

    def _cache_set_user(self, uid: str, info: dict) -> dict:
        info["_cached_at"] = time.time()
        self._user_cache[uid] = info
        return info

    def clear_cache(self) -> dict:
        """清空内存缓存：uid→用户信息缓存 + 模块级 msToken 缓存（实例其余缓存随实例丢弃）"""
        # msToken 缓存在 ref_utils.mstoken 模块级，适配器实例丢弃清不掉，必须显式清
        from app.platforms.douyin.ref_utils.mstoken import clear_cache as clear_mstoken
        clear_mstoken()
        return {"用户信息缓存": len(self._user_cache)}

    def test_account(self) -> dict:
        """抖音凭证深探测：get_my_uid 对过期旧 session 也能通过（账号弹窗曾据此误判可用），
        社交列表接口的登录校验更严，这里补一步列表探测抓住这种"假 alive"。"""
        result = super().test_account()
        if not result.get("ok"):
            return result
        try:
            uid = str((result.get("login_user") or {}).get("uid") or "")
            if uid:
                self.get_follows(uid, limit=1)
        except Exception as e:
            msg = str(e)
            if "未登录" in msg:
                result["ok"] = False
                result["error"] = msg
            else:
                # 其余错误（如 2096 平台限制列表可见性）不代表凭证失效，降级为警告
                result["warning"] = msg
        return result

    # ==================== 认证 ====================

    def _load_cookie_str(self) -> str:
        """加载抖音 Cookie 字符串（统一存于 accounts.json，按账号池绑定的账号加载）"""
        cookies = self._load_cookies()
        if cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            sid = cookies.get("sessionid", "")
            print(f"[抖音] 加载 Cookie: {len(cookies)} 个字段（account_id={self.account_id or 'primary'}）"
                  + (f", session={sid[:10]}..." if sid else ""))
            return cookie_str

        print("[抖音] 警告: 未配置 Cookie")
        return ""

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
        """请求间隔，防止触发反爬。持锁 sleep：并发线程排队通过，保证请求间隔成立"""
        with self._rl_lock:
            now = time.time()
            elapsed = now - self._last_request_at
            if elapsed < 2.0:
                time.sleep(2.0 - elapsed + random.uniform(0, 0.5))
            self._last_request_at = time.time()

    # ==================== 工具方法 ====================

    def _get_cookie_value(self, key: str) -> str:
        cookies = self._load_cookies()
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
        # 检查缓存（USER_CACHE_TTL 内有效，过期重新拉取保证数据新鲜）
        cached = self._cache_get_user(uid)
        if cached:
            return cached

        # 策略1: 通过 get_user_info API 查询
        # get_user_info 已增强：对数字 UID 会自动添加 user_id 参数
        try:
            user_url = f"{self.BASE_URL}/user/{uid}"
            self._rate_limit()
            user_data = DouyinAPI.get_user_info(self.auth, user_url)
            user = user_data.get("user", {})
            api_uid = user.get("uid")
            if api_uid and user.get("nickname"):  # 有 uid 和昵称说明查询成功
                info = {
                    "uid": str(api_uid),
                    "sec_uid": user.get("sec_uid") or uid,  # 可能没有 sec_uid，用原值兜底
                    "nickname": user.get("nickname", ""),
                    "avatar_url": self._extract_avatar_url(user),
                    "raw_user": user,
                }
                return self._cache_set_user(uid, info)
        except Exception as e:
            print(f"[抖音] _resolve_user_info({uid}) get_user_info 请求失败: {e}")

        # 策略2: uid 是数字，检查是否是自己
        if uid.isdigit():
            try:
                my_uid = str(DouyinAPI.get_my_uid(self.auth))
                if my_uid == uid:
                    sec_uid = DouyinAPI.get_my_sec_uid(self.auth)
                    info = {"uid": uid, "sec_uid": sec_uid, "nickname": "", "avatar_url": ""}
                    return self._cache_set_user(uid, info)
            except Exception:
                pass

        print(f"[抖音] _resolve_user_info({uid}) 解析失败")
        return None

    # ==================== Status ====================

    def check_alive(self) -> bool:
        """检查凭证是否有效 — 调用 get_my_uid 验证"""
        cookies = self._load_cookies()
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
            cookies = self._load_cookies()
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
        如返回空结果，请在面板中更新主账号 Cookie（accounts.json 的 primary 条目）。
        获取方法: 浏览器登录抖音 → F12 → Application → Cookies → 复制全部 douyin.com 的 Cookie。
        """
        try:
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
                    # 搜索/资料接口带粉丝数；关注/粉丝列表接口无该字段
                    "fans": info.get("follower_count") or 0,
                    "is_verified": _douyin_verified(info),
                })
            print(f"[抖音] search_user '{keyword}': 找到 {len(results)} 个用户")
            return results
        except Exception as e:
            print(f"[抖音] search_user 失败: {e}")
            raise  # 带真实原因上抛（Cookie 失效/风控等），由调用方决定如何展示

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
                self._cache_set_user(uid, user_info)

            raw_user = user_info.get("raw_user", {})
            if not raw_user:
                # 如果缓存中没有 raw_user，重新获取
                user_url = f"{self.BASE_URL}/user/{user_info['sec_uid']}"
                self._rate_limit()
                user_data = DouyinAPI.get_user_info(self.auth, user_url)
                raw_user = user_data.get("user", {})

            return self._build_profile(raw_user, user_info["uid"])
        except RuntimeError:
            raise
        except (requests.RequestException, ValueError, KeyError, AttributeError) as e:
            raise RuntimeError(f"[抖音] 获取资料失败 ({uid}): {e}") from e

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
        except RuntimeError:
            raise
        except (requests.RequestException, ValueError, KeyError, AttributeError) as e:
            raise RuntimeError(f"[抖音] 获取作品列表失败: {e}") from e

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
        except RuntimeError:
            raise
        except (requests.RequestException, ValueError, KeyError, AttributeError) as e:
            raise RuntimeError(f"[抖音] 获取作品详情失败 ({item_id}): {e}") from e

    # ==================== 关注/粉丝 ====================

    def _social_page(
        self, uid: str, kind: str, limit: int, skip: int
    ) -> tuple[list[dict], bool, int]:
        """
        增量拉取一页关注/粉丝（抖音分页游标：max_time）。
        kind: 'follows' | 'followers'
        返回 (条目, 还有更多, 总数或 -1)；抖音不返回真实总数。
        """
        try:
            user_info = self._resolve_user_info(uid)
            if not user_info:
                raise RuntimeError(
                    f"[抖音] 无法解析用户 {uid} 的资料（Cookie 可能失效/过期，或被风控）"
                )
            user_id = user_info["uid"]
            sec_uid = user_info["sec_uid"]
            max_time = "0"
            remaining_skip = max(0, skip)
            items: list[dict] = []
            has_more = False
            PAGE = 20
            while len(items) < limit:
                self._rate_limit()
                if kind == "follows":
                    res = DouyinAPI.get_user_following_list(self.auth, user_id, sec_uid, max_time, PAGE)
                    key = "followings"
                else:
                    res = DouyinAPI.get_user_follower_list(self.auth, user_id, sec_uid, max_time, PAGE)
                    key = "followers"
                # 抖音响应里 mix_count 是关注/粉丝的声明总数（即使列表被限制不返回，该字段仍存在）
                # 抖音 API 用 status_code 表达业务错误（如 2096=列表不可见），
                # 必须把真实原因带给上层/前端，不能当成"空列表"吞掉
                status_code = res.get("status_code", 0)
                status_msg = res.get("status_msg") or ""
                if status_code == 2096:
                    # 抖音网页端自改版后普遍不开放查看他人关注/粉丝列表，返回 2096；
                    # 多数情况并非对方主动设置隐私，而是平台 web 端限制（App 内可查看）
                    raise RuntimeError(
                        "[抖音] 网页端无法获取该用户的关注/粉丝列表（抖音 Web 端已限制查看他人列表，"
                        "App 内可能可见；或对方设置了列表隐私）"
                    )
                if status_code:
                    raise RuntimeError(f"[抖音] {status_msg or f'接口错误 {status_code}'}（{kind} 列表）")
                batch = res.get(key) or []
                has_more = res.get("has_more") == 1
                # status=0 但接口承认有数据却不给列表（mix_count>0 而列表为空）：
                # 说明同样被平台限制，不能误报成"对方没有关注任何人"
                if not batch and skip == 0 and "mix_count" in res:
                    try:
                        declared = int(res.get("mix_count") or 0)
                    except (TypeError, ValueError):
                        declared = 0
                    if declared > 0:
                        raise RuntimeError(
                            "[抖音] 网页端无法获取该用户的关注/粉丝列表（接口未返回数据，"
                            "抖音 Web 端已限制查看他人列表，App 内可能可见）"
                        )
                if remaining_skip >= len(batch):
                    remaining_skip -= len(batch)
                else:
                    for f in batch[remaining_skip:]:
                        items.append({
                            "uid": str(f.get("uid", "")),
                            "nickname": f.get("nickname", ""),
                            "avatarUrl": self._extract_avatar_url(f),
                            "signature": f.get("signature", ""),
                            "gender": f.get("gender", 0),
                            "sec_uid": f.get("sec_uid", ""),
                            # 列表条目可能不带 follower_count（缺省 0），认证标记是大V判定兜底信号
                            "fans": f.get("follower_count") or 0,
                            "is_verified": _douyin_verified(f),
                        })
                        if len(items) >= limit:
                            break
                    remaining_skip = 0
                if not has_more or not batch:
                    break
                max_time = str(res.get("min_time", max_time))
            more = len(items) >= limit and has_more  # 抖音无总数：取满且 has_more 才算还有更多
            return items, more, -1
        except RuntimeError:
            # 业务错误（隐私不可见/风控等）已带明确消息，直接透传
            raise
        except json.JSONDecodeError as e:
            # 接口返回了 HTML 而非 JSON：典型为风控/人机验证拦截，需与"列表为空"区分开
            print(f"[抖音] {kind} 接口返回非 JSON（疑似风控/验证码拦截）")
            raise RuntimeError(
                f"[抖音] 拉取{kind}失败：接口返回非 JSON（疑似被风控/人机验证拦截，"
                "请到 douyin.com 完成一次验证后重试，或更新 Cookie）"
            ) from e
        except Exception as e:
            # 其它拉取失败要让上层知道（graph_social 会把真实原因展示给前端），不能静默吞掉伪装成"没有列表"
            print(f"[抖音] {kind} 拉取失败: {e}")
            raise RuntimeError(f"[抖音] 拉取{kind}失败: {e}") from e

    def get_follows(self, uid: str, limit: int = 50, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取关注列表（增量：skip 已拉条数；返回 条目/还有更多/总数(-1)）"""
        return self._social_page(uid, "follows", limit, skip)

    def get_followers(self, uid: str, limit: int = 50, skip: int = 0) -> tuple[list[dict], bool, int]:
        """获取粉丝列表（增量：skip 已拉条数；返回 条目/还有更多/总数(-1)）"""
        return self._social_page(uid, "followers", limit, skip)

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """重新拉取用户最新粉丝数/认证（图谱"重新标记"用）；绕过缓存保证拿到新数据"""
        try:
            user_url = f"{self.BASE_URL}/user/{uid}"
            self._rate_limit()
            user = DouyinAPI.get_user_info(self.auth, user_url).get("user", {})
            if not user.get("uid"):
                return None
            return {
                "nickname": user.get("nickname", ""),
                "fans": user.get("follower_count") or 0,
                "is_verified": _douyin_verified(user),
            }
        except RuntimeError:
            raise
        except (requests.RequestException, ValueError, KeyError, AttributeError) as e:
            raise RuntimeError(f"[抖音] refresh_user_info({uid}) 失败: {e}") from e

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
