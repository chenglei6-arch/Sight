"""
平台适配器注册中心

用法:
    from app.platforms import get_adapter, get_pool, list_platforms
    adapter = get_adapter("netease")            # 主账号适配器（兼容旧用法）
    with get_pool("netease").lease() as ad:     # 多账号轮询租借（并发查询）
        ad.get_follows(uid, 100)
"""
import threading
from typing import Callable, Optional, TYPE_CHECKING

from app.platforms.pool import AdapterPool

if TYPE_CHECKING:
    from app.platforms.base import BasePlatformAdapter

# 各平台适配器的延迟构造工厂（避免启动时导入全部平台依赖）
_FACTORIES: dict[str, Callable] = {}


def _factory_for(platform_id: str) -> Optional[Callable]:
    """获取平台适配器工厂 (account_id → 适配器实例)，未知平台返回 None"""
    if platform_id in _FACTORIES:
        return _FACTORIES[platform_id]

    factory = None
    if platform_id == "netease":
        from app.platforms.netease.adapter import NeteaseAdapter
        factory = lambda account_id=None: NeteaseAdapter(account_id=account_id)
    elif platform_id == "bilibili":
        from app.platforms.bilibili.adapter import BilibiliAdapter
        factory = lambda account_id=None: BilibiliAdapter(account_id=account_id)
    elif platform_id == "douyin":
        from app.platforms.douyin.adapter import DouyinAdapter
        factory = lambda account_id=None: DouyinAdapter(account_id=account_id)
    elif platform_id == "qqmusic":
        from app.platforms.qqmusic.adapter import QQMusicAdapter
        factory = lambda account_id=None: QQMusicAdapter(account_id=account_id)
    elif platform_id == "weibo":
        from app.platforms.weibo.adapter import WeiboAdapter
        factory = lambda account_id=None: WeiboAdapter(account_id=account_id)
    elif platform_id == "genshin":
        from app.platforms.genshin.adapter import GenshinAdapter
        factory = lambda account_id=None: GenshinAdapter(account_id=account_id)
    elif platform_id == "xhs":
        from app.platforms.xhs.adapter import XhsAdapter
        factory = lambda account_id=None: XhsAdapter(account_id=account_id)

    if factory:
        _FACTORIES[platform_id] = factory
    return factory


# 平台账号池注册表
_pools: dict[str, AdapterPool] = {}
_pools_lock = threading.Lock()


def get_pool(platform_id: str) -> Optional[AdapterPool]:
    """获取平台账号池（延迟创建）"""
    factory = _factory_for(platform_id)
    if factory is None:
        return None
    with _pools_lock:
        pool = _pools.get(platform_id)
        if pool is None:
            pool = AdapterPool(platform_id, factory)
            _pools[platform_id] = pool
        return pool


def get_adapter(platform_id: str) -> Optional["BasePlatformAdapter"]:
    """获取平台主账号适配器（= 账号池主账号槽位，与旧单账号行为一致）"""
    pool = get_pool(platform_id)
    return pool.primary() if pool else None


def reset_adapter(platform_id: str):
    """主账号 Cookie 更新后调用：丢弃所有适配器实例，下次使用按新凭证重建"""
    with _pools_lock:
        pool = _pools.get(platform_id)
    if pool:
        pool.reset()


def reset_pool(platform_id: str):
    """账号配置（accounts.json）变更后调用：重建账号槽位"""
    with _pools_lock:
        pool = _pools.get(platform_id)
    if pool:
        pool.reload()


def known_platform_ids() -> list[str]:
    """所有已注册的平台 id（轻量，不做网络检查；与 _factory_for 的分支保持一致）"""
    return ["netease", "bilibili", "douyin", "qqmusic", "weibo", "genshin", "xhs"]


def list_platforms() -> list[dict]:
    """列出所有可用平台"""
    from app.credentials import CredentialManager
    available = CredentialManager.get_available_platforms()

    result = []
    for p in available:
        pid = p["id"]
        alive = False
        login_user = None
        pool = get_pool(pid)
        try:
            adapter = pool.primary() if pool else None
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
            # 账号池规模（含主账号），前端可据此展示"多账号加速"
            "account_count": pool.total if pool else 1,
        })
    return result
