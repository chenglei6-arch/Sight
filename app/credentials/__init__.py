"""
多平台凭证管理器

管理各平台的登录凭证（Cookie / Token），统一存储于 credentials/accounts.json，
支持通过 API 更新，保存后立即生效。

多账号模型（accounts.json 单一事实源，结构 {platform: [account, ...]}）:
- 主账号: 固定 id "primary"，列表首位；私有数据接口固定使用；不可删除，可停用
- 附加账号: 自动生成 id，用于多账号并发查询，通过 /api/accounts 管理
"""
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

# credentials 目录（项目根目录下）
CREDENTIALS_DIR = Path(__file__).parent.parent.parent / "credentials"

# 凭证存储文件（唯一事实源）
ACCOUNTS_FILE = CREDENTIALS_DIR / "accounts.json"

# 主账号的固定 ID
PRIMARY_ACCOUNT_ID = "primary"

# 支持的平台
PLATFORMS = ("netease", "bilibili", "douyin", "qqmusic", "weibo", "genshin", "xhs")

_PLATFORM_NAMES = {
    "netease": "网易云音乐",
    "bilibili": "哔哩哔哩",
    "douyin": "抖音",
    "qqmusic": "QQ音乐",
    "weibo": "微博",
    "genshin": "原神",
    "xhs": "小红书",
}

# accounts.json 的进程内读写锁（可重入：读-改-写整体串行，避免并发写坏文件；
# 写入本身走临时文件 + os.replace 原子替换）
_ACCOUNTS_LOCK = threading.RLock()


class CredentialManager:
    """多平台凭证管理器"""

    PLATFORMS = PLATFORMS

    # ==================== 存储层 ====================

    @classmethod
    def _read_accounts_file(cls) -> dict:
        """读取 accounts.json，结构 {platform: [account, ...]}；不存在/损坏时返回空"""
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
        """原子写入 accounts.json：先写临时文件再 os.replace，进程中断也不会写坏凭证"""
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = ACCOUNTS_FILE.with_name(ACCOUNTS_FILE.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ACCOUNTS_FILE)

    @classmethod
    def _mutate_accounts(cls, mutator):
        """锁内完成 accounts.json 的读-改-写；mutator(data) 原地修改，返回值透传"""
        with _ACCOUNTS_LOCK:
            data = cls._read_accounts_file()
            result = mutator(data)
            cls._write_accounts_file(data)
            return result

    # ==================== Cookie 读写 ====================

    @classmethod
    def load_cookies(cls, platform: str, account_id: str = None) -> dict:
        """
        加载 Cookie 字典

        Args:
            platform: 平台标识 (netease / bilibili / ...)
            account_id: 账号 ID。None 或 "primary" = 主账号，其他值 = 附加账号

        Returns:
            cookie 字典 {key: value}
        """
        account = cls.get_account(platform, account_id or PRIMARY_ACCOUNT_ID)
        return cls.parse_cookie_str(account.get("cookie", "")) if account else {}

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
        """保存/覆盖主账号 Cookie（= 更新 accounts.json 中 id 为 primary 的条目）"""
        if platform not in PLATFORMS:
            raise ValueError(f"未知平台: {platform}")
        cookie_str = (cookie_str or "").strip()
        if not cookie_str:
            raise ValueError("cookie 内容为空")

        def _mut(data):
            accounts = data.setdefault(platform, [])
            for a in accounts:
                if a.get("id") == PRIMARY_ACCOUNT_ID:
                    a["cookie"] = cookie_str
                    return
            accounts.insert(0, {
                "id": PRIMARY_ACCOUNT_ID,
                "name": "主账号",
                "cookie": cookie_str,
                "enabled": True,
            })

        cls._mutate_accounts(_mut)

    @classmethod
    def get_available_platforms(cls) -> list[dict]:
        """获取所有平台及主账号凭证配置状态"""
        return [{
            "id": platform,
            "name": _PLATFORM_NAMES.get(platform, platform),
            "has_credential": bool(cls.load_cookies(platform)),
        } for platform in PLATFORMS]

    @classmethod
    def _get_platform_name(cls, platform: str) -> str:
        """平台标识 → 中文名"""
        return _PLATFORM_NAMES.get(platform, platform)

    # ==================== 账号管理（主账号与附加账号统一存取） ====================

    @classmethod
    def get_accounts(cls, platform: str) -> list[dict]:
        """列出平台的所有账号（含主账号），返回 [{id, name, cookie, enabled}]"""
        with _ACCOUNTS_LOCK:
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

        record = {}

        def _mut(data):
            accounts = data.setdefault(platform, [])
            record.update({
                "id": f"acc_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
                "name": (name or "").strip() or f"账号{len(accounts) + 1}",
                "cookie": cookie_str,
                "enabled": True,
            })
            accounts.append(record)

        cls._mutate_accounts(_mut)
        return record

    @classmethod
    def update_account(cls, platform: str, account_id: str,
                       name: str = None, cookie: str = None, enabled: bool = None) -> Optional[dict]:
        """更新账号字段（None 表示不修改），返回更新后的记录；主账号同样适用"""
        found = {}

        def _mut(data):
            for a in data.get(platform, []):
                if a.get("id") == account_id:
                    if name is not None:
                        a["name"] = name.strip() or a["name"]
                    if cookie is not None and cookie.strip():
                        a["cookie"] = cookie.strip()
                    if enabled is not None:
                        a["enabled"] = bool(enabled)
                    found.update(a)
                    return

        cls._mutate_accounts(_mut)
        return found or None

    @classmethod
    def remove_account(cls, platform: str, account_id: str) -> bool:
        """删除附加账号；主账号不可删（返回 False）"""
        if account_id == PRIMARY_ACCOUNT_ID:
            return False

        removed = {"ok": False}

        def _mut(data):
            accounts = data.get(platform, [])
            remaining = [a for a in accounts if a.get("id") != account_id]
            if len(remaining) != len(accounts):
                data[platform] = remaining
                removed["ok"] = True

        cls._mutate_accounts(_mut)
        return removed["ok"]
