"""
多平台凭证管理器

管理各平台的登录凭证（Cookie / Token），
支持从 credentials/ 目录加载，也支持通过 API 更新。

多账号模型:
- 主账号: credentials/<platform>_cookie.txt（与旧行为完全一致，不可删除）
- 附加账号: credentials/accounts.json（用于多账号并发查询，通过 /api/accounts 管理）
"""
import json
import time
import uuid
from pathlib import Path
from typing import Optional

# credentials 目录（项目根目录下）
CREDENTIALS_DIR = Path(__file__).parent.parent.parent / "credentials"

# 附加账号存储文件
ACCOUNTS_FILE = CREDENTIALS_DIR / "accounts.json"


class CredentialManager:
    """多平台凭证管理器"""

    PLATFORM_FILES = {
        "netease": "netease_cookie.txt",
        "bilibili": "bilibili_cookie.txt",
        "douyin": "douyin_cookie.txt",
        "qqmusic": "qqmusic_cookie.txt",
        "weibo": "weibo_cookie.txt",
        "genshin": "genshin_cookie.txt",
        "xhs": "xhs_cookie.txt",
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
    def load_cookies(cls, platform: str, account_id: str = None) -> dict:
        """
        加载 Cookie 字典

        Args:
            platform: 平台标识 (netease / bilibili / ...)
            account_id: 账号 ID。None 或 "primary" = 主账号（旧 *_cookie.txt），
                        其他值 = accounts.json 中的附加账号

        Returns:
            cookie 字典 {key: value}
        """
        if account_id and account_id != "primary":
            account = cls.get_account(platform, account_id)
            if not account:
                return {}
            return cls.parse_cookie_str(account.get("cookie", ""))

        path = cls.get_credential_path(platform)
        if not path or not path.exists():
            return {}

        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()

        return cls.parse_cookie_str(raw)

    @staticmethod
    def parse_cookie_str(raw: str) -> dict:
        """解析 "k=v; k2=v2" 格式的 Cookie 字符串"""
        cookies = {}
        for item in (raw or "").strip().split("; "):
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
            "genshin": "原神",
            "xhs": "小红书",
        }
        return names.get(platform, platform)

    # ==================== 附加账号管理（多账号并发查询用） ====================

    @classmethod
    def _read_accounts_file(cls) -> dict:
        """读取 accounts.json，结构 {platform: [account, ...]}；损坏时返回空"""
        if not ACCOUNTS_FILE.exists():
            return {}
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            print(f"[credentials] accounts.json 读取失败，忽略: {e}")
            return {}

    @classmethod
    def _write_accounts_file(cls, data: dict):
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def get_accounts(cls, platform: str) -> list[dict]:
        """列出平台的所有附加账号（不含主账号），返回 [{id, name, cookie, enabled}]"""
        accounts = cls._read_accounts_file().get(platform, [])
        return [a for a in accounts if isinstance(a, dict) and a.get("id")]

    @classmethod
    def get_account(cls, platform: str, account_id: str) -> Optional[dict]:
        for a in cls.get_accounts(platform):
            if a.get("id") == account_id:
                return a
        return None

    @classmethod
    def add_account(cls, platform: str, cookie_str: str, name: str = "") -> dict:
        """新增附加账号，返回新账号记录"""
        cookie_str = (cookie_str or "").strip()
        if not cookie_str:
            raise ValueError("cookie 内容为空")
        data = cls._read_accounts_file()
        accounts = data.setdefault(platform, [])
        account = {
            "id": f"acc_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
            "name": (name or "").strip() or f"账号{len(accounts) + 2}",
            "cookie": cookie_str,
            "enabled": True,
        }
        accounts.append(account)
        cls._write_accounts_file(data)
        return account

    @classmethod
    def update_account(cls, platform: str, account_id: str,
                       name: str = None, cookie: str = None, enabled: bool = None) -> Optional[dict]:
        """更新附加账号的字段（None 表示不修改），返回更新后的记录"""
        data = cls._read_accounts_file()
        for a in data.get(platform, []):
            if a.get("id") == account_id:
                if name is not None:
                    a["name"] = name.strip() or a["name"]
                if cookie is not None and cookie.strip():
                    a["cookie"] = cookie.strip()
                if enabled is not None:
                    a["enabled"] = bool(enabled)
                cls._write_accounts_file(data)
                return a
        return None

    @classmethod
    def remove_account(cls, platform: str, account_id: str) -> bool:
        """删除附加账号（主账号不在此列表，天然不可删）"""
        data = cls._read_accounts_file()
        accounts = data.get(platform, [])
        remaining = [a for a in accounts if a.get("id") != account_id]
        if len(remaining) == len(accounts):
            return False
        data[platform] = remaining
        cls._write_accounts_file(data)
        return True


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
