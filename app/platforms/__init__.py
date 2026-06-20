"""
平台适配器注册中心

用法:
    from app.platforms import get_adapter, list_platforms
    adapter = get_adapter("netease")
    profile = adapter.get_profile("5012722824")
"""
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.platforms.base import BasePlatformAdapter

# 平台注册表
_registry: dict[str, "BasePlatformAdapter"] = {}


def register(platform_id: str, adapter: "BasePlatformAdapter"):
    """注册平台适配器"""
    _registry[platform_id] = adapter


def get_adapter(platform_id: str) -> Optional["BasePlatformAdapter"]:
    """获取已注册的平台适配器（延迟初始化）"""
    adapter = _registry.get(platform_id)
    if adapter:
        return adapter

    # 延迟加载
    if platform_id == "netease":
        from app.platforms.netease.adapter import NeteaseAdapter
        adapter = NeteaseAdapter()
        _registry[platform_id] = adapter
        return adapter

    if platform_id == "bilibili":
        from app.platforms.bilibili.adapter import BilibiliAdapter
        adapter = BilibiliAdapter()
        _registry[platform_id] = adapter
        return adapter

    return None


def list_platforms() -> list[dict]:
    """列出所有可用平台"""
    from app.credentials import CredentialManager
    available = CredentialManager.get_available_platforms()

    result = []
    for p in available:
        pid = p["id"]
        alive = False
        login_user = None
        try:
            adapter = get_adapter(pid)
            if adapter:
                alive = adapter.check_alive()
                login_user = adapter.get_login_user()
        except Exception:
            pass

        result.append({
            "id": pid,
            "name": p["name"],
            "has_credential": p["has_credential"],
            "is_alive": alive,
            "login_user": login_user,
        })
    return result
