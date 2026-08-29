"""
小红书平台适配器 — 基于 cv-cat/Spider_XHS

参考项目: https://github.com/cv-cat/Spider_XHS
参考文档: reference/Spider_XHS-main/README.md

架构说明:
  - 本适配器支持 PC 和 Creator 两种模式
  - ref_xhs_core/*, ref_xhs_pc/*, ref_xhs_creator/* 是 Spider_XHS 的移植模块
  - adapter.py 将这些基础 API 封装为 BasePlatformAdapter 的统一接口

用法:
    from app.platforms.xhs.adapter import XhsAdapter
    adapter = XhsAdapter(mode="pc")  # 或 mode="creator"
    profile = adapter.get_profile("user_id")
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional

# 添加 ref 模块到 sys.path
_xhs_ref_root = Path(__file__).parent
if str(_xhs_ref_root) not in sys.path:
    sys.path.insert(0, str(_xhs_ref_root))

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    EventItem,
)
from app.credentials import CredentialManager
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class XhsAdapter(BasePlatformAdapter):
    """小红书平台适配器 — 支持 PC 和 Creator 模式"""

    platform_id = "xhs"
    platform_name = "小红书"

    def __init__(self, credentials: dict = None, mode: str = "pc"):
        """
        Args:
            credentials: 凭证字典
            mode: "pc" 或 "creator"
        """
        super().__init__(credentials)
        self.mode = mode
        self._auth_pc = None
        self._auth_creator = None
        self._api_pc = None
        self._api_creator = None
        self._last_request_at = 0.0

    # ==================== 凭证加载 ====================

    def _load_cookie_str(self) -> str:
        """
        加载小红书 Cookie 字符串
        优先级: credentials/xhs_cookie.txt → .env XHS_COOKIES
        """
        cookies = CredentialManager.load_cookies("xhs")
        if cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            print(f"[小红书] 从 credentials/xhs_cookie.txt 加载: {len(cookies)} 个字段")
            return cookie_str

        # 从 .env 加载
        from dotenv import load_dotenv
        root_env = Path(__file__).parent.parent.parent.parent / ".env"
        if root_env.exists():
            load_dotenv(dotenv_path=root_env, override=True)
            xhs_cookies = os.environ.get("XHS_COOKIES", "")
            if xhs_cookies:
                print(f"[小红书] 从根目录 .env 加载")
                return xhs_cookies.strip().strip("'").strip('"')

        print(f"[小红书] 警告: 未找到任何 Cookie 来源")
        return ""

    # ==================== Auth 初始化 ====================

    @property
    def auth_pc(self):
        """获取 PC Auth 实例（延迟初始化）"""
        if self._auth_pc is None:
            try:
                from ref_xhs_pc.auth import XHSPcAuth
                cookie_str = self._load_cookie_str()
                if not cookie_str:
                    print("[小红书] PC Auth: Cookie 为空，部分功能受限")
                    return None
                self._auth_pc = XHSPcAuth.from_cookie(cookie_str)
                print(f"[小红书] PC Auth 已加载")
            except Exception as e:
                print(f"[小红书] PC Auth 初始化失败: {e}")
                return None
        return self._auth_pc

    @property
    def auth_creator(self):
        """获取 Creator Auth 实例（延迟初始化）"""
        if self._auth_creator is None:
            try:
                from ref_xhs_creator.auth import XHSCreatorAuth
                cookie_str = self._load_cookie_str()
                if not cookie_str:
                    print("[小红书] Creator Auth: Cookie 为空，部分功能受限")
                    return None
                self._auth_creator = XHSCreatorAuth.from_cookie(cookie_str)
                print(f"[小红书] Creator Auth 已加载")
            except Exception as e:
                print(f"[小红书] Creator Auth 初始化失败: {e}")
                return None
        return self._auth_creator

    @property
    def api_pc(self):
        """获取 PC API 实例"""
        if self._api_pc is None and self.auth_pc:
            try:
                from ref_apis.xhs_pc_apis import XHS_Apis
                self._api_pc = XHS_Apis(self.auth_pc).bootstrap()
                print(f"[小红书] PC API 已初始化")
            except Exception as e:
                print(f"[小红书] PC API 初始化失败: {e}")
                return None
        return self._api_pc

    @property
    def api_creator(self):
        """获取 Creator API 实例"""
        if self._api_creator is None and self.auth_creator:
            try:
                from ref_apis.xhs_creator_apis import XHS_Creator_Apis
                self._api_creator = XHS_Creator_Apis(self.auth_creator).bootstrap()
                print(f"[小红书] Creator API 已初始化")
            except Exception as e:
                print(f"[小红书] Creator API 初始化失败: {e}")
                return None
        return self._api_creator

    # ==================== 限速 ====================

    def _rate_limit(self):
        """请求间隔，防止触发反爬"""
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < 1.5:
            time.sleep(1.5 - elapsed)
        self._last_request_at = time.time()

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查凭证是否有效"""
        cookies = CredentialManager.load_cookies("xhs")
        if not cookies:
            return False
        try:
            if self.mode == "pc" and self.api_pc:
                success, msg, res = self.api_pc.get_user_me()
                return success
            elif self.mode == "creator" and self.api_creator:
                success, msg, res = self.api_creator.get_user_me()
                return success
            return False
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户信息"""
        try:
            if self.mode == "pc" and self.api_pc:
                self._rate_limit()
                success, msg, res = self.api_pc.get_user_me()
                if success and res:
                    data = res.get("data", {})
                    return {
                        "uid": data.get("user_id", ""),
                        "nickname": data.get("nickname", ""),
                        "avatarUrl": data.get("image", ""),
                    }
            elif self.mode == "creator" and self.api_creator:
                self._rate_limit()
                success, msg, res = self.api_creator.get_user_me()
                if success and res:
                    data = res.get("data", {})
                    return {
                        "uid": data.get("user_id", ""),
                        "nickname": data.get("nickname", ""),
                        "avatarUrl": data.get("avatar", ""),
                    }
            return None
        except Exception as e:
            print(f"[小红书] get_login_user 失败: {e}")
            return None

    # ==================== 用户搜索 ====================

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜索用户"""
        try:
            if not self.api_pc:
                return []
            self._rate_limit()
            success, msg, res = self.api_pc.search_some_user(keyword, limit)
            if not success or not res:
                return []

            results = []
            items = res.get("items", [])
            for item in items:
                user = item.get("user", {})
                results.append({
                    "uid": user.get("user_id", ""),
                    "nickname": user.get("nickname", ""),
                    "avatarUrl": user.get("avatar", ""),
                    "signature": user.get("desc", ""),
                })
            return results
        except Exception as e:
            print(f"[小红书] search_user 失败: {e}")
            return []

    # ==================== 用户资料 ====================

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """获取用户资料"""
        try:
            if not self.api_pc:
                return None
            self._rate_limit()
            success, msg, res = self.api_pc.get_user_info(uid)
            if not success or not res:
                return None

            data = res.get("data", {})
            return PlatformProfile(
                platform="xhs",
                uid=uid,
                nickname=data.get("nickname", ""),
                avatar_url=data.get("image", ""),
                background_url=data.get("imageb", ""),
                signature=data.get("desc", ""),
                gender=1 if data.get("gender") == "male" else (2 if data.get("gender") == "female" else 0),
                location=data.get("location", ""),
                extra={
                    "red_id": data.get("red_id", ""),
                    "follows": data.get("follows", 0),
                    "fans": data.get("fans", 0),
                    "interaction": data.get("interaction", 0),
                    "notes_count": data.get("notes_count", 0),
                },
            )
        except Exception as e:
            print(f"[小红书] get_profile 失败: {e}")
            return None

    # ==================== 内容列表 ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户的笔记列表"""
        try:
            if not self.api_pc:
                return []

            # 构建用户主页 URL
            user_url = f"https://www.xiaohongshu.com/user/profile/{uid}"
            self._rate_limit()
            success, msg, res = self.api_pc.get_user_all_notes(user_url)
            if not success or not res:
                return []

            items = []
            notes = res.get("notes", []) if isinstance(res, dict) else res
            for note in notes:
                items.append(ContentItem(
                    item_id=note.get("note_id", ""),
                    title=note.get("title", "无标题")[:200],
                    cover_url=note.get("cover", {}).get("url_default", "") if isinstance(note.get("cover"), dict) else "",
                    view_count=note.get("view_count", 0),
                    description=note.get("desc", "")[:200],
                    is_owner=True,
                    extra={
                        "liked_count": note.get("liked_count", 0),
                        "collected_count": note.get("collected_count", 0),
                        "comment_count": note.get("comment_count", 0),
                        "share_count": note.get("share_count", 0),
                        "type": note.get("type", ""),
                    },
                ))
            return items
        except Exception as e:
            print(f"[小红书] get_content_lists 失败: {e}")
            return []

    # ==================== 动态 ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态 — 基于笔记列表"""
        items = self.get_content_lists(uid)
        events = []
        for item in items[:limit]:
            events.append(EventItem(
                event_id=item.item_id,
                event_type="发布笔记",
                content=item.title,
                timestamp=0,  # 需要从笔记详情获取
                media_title=item.title,
                extra=item.extra,
            ))
        return events

    # ==================== 社交 ====================

    def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
        """获取关注列表 — 暂不支持"""
        return []

    def get_followers(self, uid: str, limit: int = 100) -> list[dict]:
        """获取粉丝列表 — 暂不支持"""
        return []

