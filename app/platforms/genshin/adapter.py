"""
原神（Genshin Impact）平台适配器

基于 Enka.Network API 的数据采集实现。

设计思路（仿 QQMusicApi）:
  - 不需要手动输入 UID：配置 Cookie 后自动从绑定 API 获取登录用户的信息
  - 核心依赖 Enka.Network 公开 API，无需额外鉴权
  - 米游社游戏记录 API 已全面风控（1034），不作为数据源

API 说明:
  - enka.network/api/uid/{uid}      [公开] 玩家展柜数据（资料 + 角色）
  - api-takumi.mihoyo.com/binding   [需Cookie] 获取绑定游戏账号（仅 `getUserGameRolesByCookie` 仍有效）

数据映射:
  - get_profile(uid)      → Enka 玩家资料（昵称/等级/签名/成就/深渊）
  - search_user(keyword)  → 空keyword时自动用Cookie身份；数字UID直接查Enka
  - get_content_lists()   → Enka 角色展柜
  - get_login_user()      → 从绑定API查出Cookie对应的游戏账号

限制:
  - 原神没有公开在线状态 API
  - 角色展柜需对方在游戏中设为"公开"
  - 昵称搜索不可用（米游社搜索接口已关停），需通过 UID 查询
"""
import time
import urllib3
from typing import Optional

import requests

from app.platforms.base import (
    BasePlatformAdapter,
    PlatformProfile,
    ContentItem,
    EventItem,
)
from app.credentials import CredentialManager
from app.config import MAX_RETRIES

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


GENSHIN_SERVERS = {
    "cn_gf01": "天空岛",
    "cn_qd01": "世界树",
    "os_usa": "America",
    "os_euro": "Europe",
    "os_asia": "Asia",
    "os_cht": "TW/HK/MO",
}


def detect_server(uid: str) -> str:
    """根据 UID 首位数推断服务器"""
    first = str(uid)[0] if uid else "1"
    return {"6": "os_usa", "7": "os_euro", "8": "os_asia", "9": "os_cht"}.get(first, "cn_gf01")


class GenshinAdapter(BasePlatformAdapter):
    """原神平台适配器"""

    platform_id = "genshin"
    platform_name = "原神"

    ENKA_API = "https://enka.network/api/uid"
    TAKUMI_BINDING = "https://api-takumi.mihoyo.com/binding/api"

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self._session: requests.Session | None = None
        self._bind_session: requests.Session | None = None
        self._last_request_at = 0.0
        # 缓存从 Cookie 发现的游戏账号
        self._my_game_uid: str | None = None

    # ── Session ──

    @property
    def session(self) -> requests.Session:
        """Enka API session（无需认证）"""
        if self._session is None:
            self._session = requests.Session()
            self._session.verify = False
            self._session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            })
        return self._session

    def _bind_api_session(self) -> requests.Session | None:
        """绑定 API 用的 session（只需 Cookie，不需要 DS 签名）"""
        cookies = CredentialManager.load_cookies("genshin")
        if not cookies:
            return None
        if self._bind_session is None:
            s = requests.Session()
            s.verify = False
            for k, v in cookies.items():
                s.cookies.set(k, v, domain=".mihoyo.com")
            s.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Referer": "https://webstatic.mihoyo.com/",
            })
            self._bind_session = s
        return self._bind_session

    def _rate_limit(self, base: float = 1.0):
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < base:
            time.sleep(base - elapsed)
        self._last_request_at = time.time()

    # ── 获取 Cookie 对应的游戏账号 ──

    def _get_my_game_account(self) -> dict | None:
        """
        调用 getUserGameRolesByCookie 获取绑定账号。
        这是目前唯一还能正常工作的米游社 API。
        """
        sess = self._bind_api_session()
        if not sess:
            return None
        if self._my_game_uid:
            return {"uid": self._my_game_uid}

        try:
            self._rate_limit(1.0)
            resp = sess.get(
                f"{self.TAKUMI_BINDING}/getUserGameRolesByCookie",
                params={},
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("retcode") != 0:
                return None
            roles = data.get("data", {}).get("list", [])
            # 找原神 (hk4e_cn) 账号
            for role in roles:
                if role.get("game_biz") in ("hk4e_cn", "hk4e_global"):
                    self._my_game_uid = str(role.get("game_uid", ""))
                    return {
                        "uid": self._my_game_uid,
                        "nickname": role.get("nickname", ""),
                        "level": role.get("level", 0),
                        "region": role.get("region", ""),
                        "server": GENSHIN_SERVERS.get(role.get("region", ""), role.get("region", "")),
                    }
        except Exception:
            return None

    # ── Enka API ──

    def _enka_get(self, uid: str) -> dict:
        uid = str(uid).strip()
        for attempt in range(min(MAX_RETRIES, 2)):
            try:
                self._rate_limit(0.5)
                resp = self.session.get(
                    f"{self.ENKA_API}/{uid}",
                    timeout=(10, 15),
                )
                if resp.status_code == 424:
                    print(f"[原神] Enka 维护 (424) uid={uid}")
                    return {}
                if resp.status_code == 404:
                    print(f"[原神] Enka 无此用户 (404) uid={uid}")
                    return {}
                if resp.status_code != 200:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(2 + attempt)
                    continue
                data = resp.json()
                return data if isinstance(data, dict) else {}
            except (requests.RequestException, ValueError) as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 + attempt)
        return {}

    # ── 状态检查 ──

    def check_alive(self) -> bool:
        return self._bind_api_session() is not None

    def get_login_user(self) -> Optional[dict]:
        """
        获取 Cookie 对应的登录用户（自动从绑定 API 查出游戏 UID）。
        这就是"不需要uid"的关键——Cookie 自动识别身份。
        """
        account = self._get_my_game_account()
        if account:
            return {
                "uid": account["uid"],
                "nickname": account.get("nickname", ""),
                "avatarUrl": "",
                "level": account.get("level", 0),
                "region": account.get("region", ""),
                "server": account.get("server", ""),
            }
        return None

    # ── 搜索（自动发现或数字UID）──

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        搜索用户。
        - 空keyword / "me" → 自动从Cookie查出自己的身份
        - 数字 → 直接查 Enka
        """
        kw = keyword.strip()

        # 空 / me → 自动发现
        if not kw or kw.lower() == "me":
            account = self._get_my_game_account()
            if account:
                return [account]
            return []

        # 数字 UID → Enka
        if kw.isdigit():
            profile = self.get_profile(kw)
            if profile:
                return [{
                    "uid": profile.uid,
                    "nickname": profile.nickname,
                    "avatarUrl": profile.avatar_url,
                    "signature": profile.signature,
                    "level": profile.level,
                }]
        return []

    # ── 资料 ──

    def get_profile(self, uid: str | None = None) -> Optional[PlatformProfile]:
        """
        获取玩家资料。
        - uid=None/空 → 用 Cookie 自动发现
        - 其他 → 按指定 UID 查 Enka
        """
        # 没传 UID → 自动发现
        if not uid or not str(uid).strip():
            account = self._get_my_game_account()
            if account:
                uid = account["uid"]
            else:
                return None

        uid = str(uid).strip()
        if not uid.isdigit():
            return None

        enka_data = self._enka_get(uid)
        if not enka_data:
            return None

        player_info = enka_data.get("playerInfo") or {}
        server = detect_server(uid)

        # 头像
        profile_pic = player_info.get("profilePicture") or {}
        pic_id = profile_pic.get("id", 0)
        avatar_url = (
            f"https://enka.network/ui/UI_AvatarIcon_{profile_pic.get('avatarId', '')}.png"
            if pic_id and profile_pic.get("avatarId") else ""
        )

        extra = {
            "server": server,
            "server_name": GENSHIN_SERVERS.get(server, ""),
            "world_level": player_info.get("worldLevel", 0),
            "achievements": player_info.get("finishAchievementNum", 0),
            "abyss_floor": player_info.get("towerFloorIndex", 0),
            "abyss_room": player_info.get("towerLevelIndex", 0),
            "name_card_id": player_info.get("nameCardId", 0),
            "characters_count": len(enka_data.get("avatarInfoList") or []),
            "last_login_time": player_info.get("lastLoginTime", 0),
        }

        return PlatformProfile(
            platform="genshin",
            uid=uid,
            nickname=player_info.get("nickname", f"旅行者{uid[-4:]}"),
            avatar_url=avatar_url,
            signature=player_info.get("signature", ""),
            level=player_info.get("level", 0),
            extra=extra,
        )

    # ── 角色展柜 ──

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        if not uid or not str(uid).isdigit():
            return []

        enka_data = self._enka_get(uid)
        if not enka_data:
            return []

        avatar_list = enka_data.get("avatarInfoList") or []
        result = []
        for i, avatar in enumerate(avatar_list):
            if not isinstance(avatar, dict):
                continue
            info = avatar.get("avatarInfo", avatar)
            name = info.get("name", f"角色{i+1}")
            avatar_id = avatar.get("avatarId", 0)
            level = info.get("level", 0)
            element = info.get("element", "")
            constellation = info.get("constellationNum", 0)
            weapon = info.get("weapon") or {}
            weapon_name = weapon.get("name", "")
            weapon_level = weapon.get("level", 0)

            result.append(ContentItem(
                item_id=str(avatar_id or i),
                title=f"{name} Lv.{level}",
                cover_url=(
                    f"https://enka.network/ui/UI_AvatarIcon_{name}.png"
                    if name else ""
                ),
                count=1,
                view_count=level,
                description=f"{element} · {constellation}命" if element else f"Lv.{level}",
                is_owner=True,
                extra={
                    "avatar_id": avatar_id,
                    "element": element,
                    "level": level,
                    "constellation": constellation,
                    "friendship": info.get("fetterLevel", 0),
                    "weapon_name": weapon_name,
                    "weapon_level": weapon_level,
                },
            ))
        return result

    # ── 不支持 ──

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """深渊数据因米游社风控不可用"""
        return []

    def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
        return []

    def get_followers(self, uid: str, limit: int = 100) -> list[dict]:
        return []

    def get_history(self, uid: str, period: str = "all") -> list:
        return []
