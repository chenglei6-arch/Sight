"""
多平台凭证管理器

管理各平台的登录凭证（Cookie / Token），
支持从 credentials/ 目录加载，也支持通过 API 更新。
"""
import os
from pathlib import Path
from typing import Optional

# credentials 目录（项目根目录下）
CREDENTIALS_DIR = Path(__file__).parent.parent.parent / "credentials"


class CredentialManager:
    """多平台凭证管理器"""

    PLATFORM_FILES = {
        "netease": "netease_cookie.txt",
        "bilibili": "bilibili_cookie.txt",
        "douyin": "douyin_cookie.txt",
        "qqmusic": "qqmusic_cookie.txt",
        # 未来扩展:
        # "weibo": "weibo_cookie.txt",
    }

    # 文件名别名（兼容不同拼写）
    PLATFORM_ALIASES = {
        "bilibili": ["billbill_cookie.txt", "bilibili_cookie.txt"],
        "qqmusic": ["y.qq_cookie.txt"],
    }

    @classmethod
    def get_credential_path(cls, platform: str) -> Optional[Path]:
        """获取平台凭证文件路径（支持别名）"""
        # 先检查标准文件名
        filename = cls.PLATFORM_FILES.get(platform)
        if filename:
            path = CREDENTIALS_DIR / filename
            if path.exists():
                return path

        # 再检查别名
        aliases = cls.PLATFORM_ALIASES.get(platform, [])
        for alias in aliases:
            path = CREDENTIALS_DIR / alias
            if path.exists():
                return path

        # 返回标准路径（即使不存在）
        if filename:
            return CREDENTIALS_DIR / filename
        return None

    @classmethod
    def load_cookies(cls, platform: str) -> dict:
        """
        从凭证文件加载 Cookie 字典

        Args:
            platform: 平台标识 (netease / bilibili / ...)

        Returns:
            cookie 字典 {key: value}
        """
        path = cls.get_credential_path(platform)
        if not path or not path.exists():
            return {}

        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()

        cookies = {}
        for item in raw.split("; "):
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key] = value
        return cookies

    @classmethod
    def save_cookies(cls, platform: str, cookie_str: str):
        """保存 Cookie 到凭证文件"""
        filename = cls.PLATFORM_FILES.get(platform)
        if not filename:
            raise ValueError(f"未知平台: {platform}")

        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        path = CREDENTIALS_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            f.write(cookie_str.strip())

    @classmethod
    def get_available_platforms(cls) -> list[dict]:
        """获取所有已配置凭证的平台列表（含别名检测）"""
        result = []
        for platform, filename in cls.PLATFORM_FILES.items():
            path = cls.get_credential_path(platform)
            result.append({
                "id": platform,
                "name": cls._get_platform_name(platform),
                "has_credential": path is not None and path.exists(),
                "credential_file": str(path or CREDENTIALS_DIR / filename),
            })
        return result

    @classmethod
    def _get_platform_name(cls, platform: str) -> str:
        """平台标识 → 中文名"""
        names = {
            "netease": "网易云音乐",
            "bilibili": "哔哩哔哩",
            "douyin": "抖音",
            "qqmusic": "QQ音乐",
            "weibo": "微博",
        }
        return names.get(platform, platform)


# 迁移旧 cookie.txt → credentials/netease_cookie.txt
def _migrate_legacy_cookie():
    """将根目录的旧 cookie.txt 迁移到新位置"""
    old_path = CREDENTIALS_DIR.parent / "cookie.txt"
    new_path = CREDENTIALS_DIR / "netease_cookie.txt"

    if old_path.exists() and not new_path.exists():
        print(f"[migrate] 迁移 cookie: {old_path} → {new_path}")
        with open(old_path, "r", encoding="utf-8") as f:
            content = f.read()
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        with open(new_path, "w", encoding="utf-8") as f:
            f.write(content)
