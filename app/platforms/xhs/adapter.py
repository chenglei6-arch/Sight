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
import threading
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
        # /graph 接口会从多个线程并发调用本适配器，限流必须串行化
        self._rl_lock = threading.Lock()

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
                # 修复导入路径：需要从 app.platforms.xhs 导入
                import sys
                from pathlib import Path
                xhs_path = Path(__file__).parent
                if str(xhs_path) not in sys.path:
                    sys.path.insert(0, str(xhs_path))

                from ref_xhs_pc.auth import XHSPcAuth
                cookie_str = self._load_cookie_str()
                if not cookie_str:
                    print("[小红书] PC Auth: Cookie 为空，部分功能受限")
                    return None
                self._auth_pc = XHSPcAuth.from_cookie(cookie_str)
                print(f"[小红书] PC Auth 已加载")
            except Exception as e:
                import traceback
                print(f"[小红书] PC Auth 初始化失败: {e}")
                traceback.print_exc()
                return None
        return self._auth_pc

    @property
    def auth_creator(self):
        """获取 Creator Auth 实例（延迟初始化）"""
        if self._auth_creator is None:
            try:
                import sys
                from pathlib import Path
                xhs_path = Path(__file__).parent
                if str(xhs_path) not in sys.path:
                    sys.path.insert(0, str(xhs_path))

                from ref_xhs_creator.auth import XHSCreatorAuth
                cookie_str = self._load_cookie_str()
                if not cookie_str:
                    print("[小红书] Creator Auth: Cookie 为空，部分功能受限")
                    return None
                self._auth_creator = XHSCreatorAuth.from_cookie(cookie_str)
                print(f"[小红书] Creator Auth 已加载")
            except Exception as e:
                import traceback
                print(f"[小红书] Creator Auth 初始化失败: {e}")
                traceback.print_exc()
                return None
        return self._auth_creator

    @property
    def api_pc(self):
        """获取 PC API 实例"""
        if self._api_pc is None and self.auth_pc:
            try:
                import sys
                from pathlib import Path
                xhs_path = Path(__file__).parent
                if str(xhs_path) not in sys.path:
                    sys.path.insert(0, str(xhs_path))

                from ref_apis.xhs_pc_apis import XHS_Apis
                self._api_pc = XHS_Apis(self.auth_pc).bootstrap()
                print(f"[小红书] PC API 已初始化")
            except Exception as e:
                import traceback
                print(f"[小红书] PC API 初始化失败: {e}")
                traceback.print_exc()
                return None
        return self._api_pc

    @property
    def api_creator(self):
        """获取 Creator API 实例"""
        if self._api_creator is None and self.auth_creator:
            try:
                import sys
                from pathlib import Path
                xhs_path = Path(__file__).parent
                if str(xhs_path) not in sys.path:
                    sys.path.insert(0, str(xhs_path))

                from ref_apis.xhs_creator_apis import XHS_Creator_Apis
                self._api_creator = XHS_Creator_Apis(self.auth_creator).bootstrap()
                print(f"[小红书] Creator API 已初始化")
            except Exception as e:
                import traceback
                print(f"[小红书] Creator API 初始化失败: {e}")
                traceback.print_exc()
                return None
        return self._api_creator

    # ==================== 限速 ====================

    def _rate_limit(self):
        """请求间隔，防止触发反爬。持锁 sleep：并发线程排队通过，保证请求间隔成立"""
        with self._rl_lock:
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
                    basic = data.get("basic_info") or data
                    return {
                        "uid": basic.get("user_id", ""),
                        "nickname": basic.get("nickname", ""),
                        "avatarUrl": basic.get("images") or basic.get("image", ""),
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
        """搜索用户（失败时抛出带原因的异常，由调用方展示）"""
        try:
            if not self.api_pc:
                raise RuntimeError("小红书客户端未初始化（请检查 Cookie 是否已配置/有效）")
            self._rate_limit()
            success, msg, res = self.api_pc.search_some_user(keyword, limit)
            if not success:
                raise RuntimeError(f"小红书搜索失败: {msg}")
            if not res:
                return []

            results = []
            # XHS_Apis.search_some_user returns the accumulated list directly.
            # Keep support for the raw response shape for compatibility.
            items = res if isinstance(res, list) else res.get("items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                user = item.get("user") or item
                results.append({
                    "uid": user.get("user_id") or user.get("id", ""),
                    "nickname": user.get("nickname") or user.get("nick_name") or user.get("name", ""),
                    "avatarUrl": user.get("avatar") or user.get("images") or user.get("image", ""),
                    "signature": user.get("desc") or user.get("description") or user.get("sub_title", ""),
                })
            return results
        except Exception as e:
            print(f"[小红书] search_user 失败: {e}")
            raise

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
            basic = data.get("basic_info") or data
            interactions = data.get("interactions") or []
            interaction_counts = {}
            for index, interaction in enumerate(interactions):
                if not isinstance(interaction, dict):
                    continue
                key = interaction.get("type") or interaction.get("name")
                count = interaction.get("count", 0)
                if key:
                    interaction_counts[str(key)] = count
                # Older responses do not include a type; preserve their order.
                if index == 0:
                    interaction_counts.setdefault("follows", count)
                elif index == 1:
                    interaction_counts.setdefault("fans", count)
                elif index == 2:
                    interaction_counts.setdefault("interaction", count)

            # XHS 编码 0=男 1=女；字段缺失（未公开）时用 -1 兜底，归为未知而非男
            gender_value = basic.get("gender", -1)
            if isinstance(gender_value, str):
                gender_key = gender_value.lower()
                gender = 1 if gender_key in {"male", "man", "男"} else 2 if gender_key in {"female", "woman", "女"} else 0
            elif gender_value == 0:
                gender = 1
            elif gender_value == 1:
                gender = 2
            else:
                gender = 0
            return PlatformProfile(
                platform="xhs",
                uid=uid,
                nickname=basic.get("nickname", ""),
                avatar_url=basic.get("images") or basic.get("image", ""),
                background_url=basic.get("imageb", ""),
                signature=basic.get("desc", ""),
                gender=gender,
                location=basic.get("location") or basic.get("ip_location", ""),
                extra={
                    "red_id": basic.get("red_id", ""),
                    "follows": interaction_counts.get("follows", basic.get("follows", 0)),
                    "fans": interaction_counts.get("fans", basic.get("fans", 0)),
                    "interaction": interaction_counts.get("interaction", basic.get("interaction", 0)),
                    "notes_count": basic.get("notes_count", 0),
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
                if not isinstance(note, dict):
                    continue
                interact = note.get("interact_info") or {}
                cover = note.get("cover") or {}
                note_id = note.get("note_id") or note.get("id", "")
                title = note.get("display_title") or note.get("title") or "无标题"
                create_time = note.get("time", note.get("create_time", ""))
                user = note.get("user") or {}
                items.append(ContentItem(
                    item_id=note_id,
                    title=str(title)[:200],
                    cover_url=cover.get("url_default", "") if isinstance(cover, dict) else "",
                    view_count=note.get("view_count", 0),
                    description=note.get("desc", "")[:200],
                    is_owner=True,
                    creator=user.get("nickname", "") if isinstance(user, dict) else "",
                    create_time=str(create_time) if create_time is not None else "",
                    url=f"https://www.xiaohongshu.com/explore/{note_id}" if note_id else "",
                    extra={
                        "liked_count": interact.get("liked_count", note.get("liked_count", 0)),
                        "collected_count": interact.get("collected_count", note.get("collected_count", 0)),
                        "comment_count": interact.get("comment_count", note.get("comment_count", 0)),
                        "share_count": interact.get("share_count", note.get("share_count", 0)),
                        "type": note.get("type", ""),
                        "xsec_token": note.get("xsec_token", ""),
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
            timestamp = 0
            if item.create_time:
                try:
                    timestamp = int(item.create_time)
                    if timestamp < 1000000000000:
                        timestamp *= 1000
                except (TypeError, ValueError):
                    timestamp = 0
            events.append(EventItem(
                event_id=item.item_id,
                event_type="发布笔记",
                content=item.title,
                timestamp=timestamp,
                media_title=item.title,
                url=item.url,
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
