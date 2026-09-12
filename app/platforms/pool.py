"""
多账号适配器池 —— 多账号并发查询的核心。

账号模型（统一存储于 credentials/accounts.json）:
- 主账号: 固定 id "primary"，私有数据接口固定走主账号；可停用（停用后不参与轮询）
- 附加账号: 通过 /api/accounts/<platform> 管理，可停用

每个账号对应一个独立的适配器实例。各适配器的限速状态
（_last_request_at / 限速锁 / B站惩罚计数等）天然按实例隔离，
因此 N 个账号 = N 条互不阻塞的请求流水线。

调度采用"租借制": 调用方通过 lease() 借出一个适配器、用完即还，
池内轮询分配；停用的账号不参与分配。
"""
import threading
from contextlib import contextmanager
from typing import Callable, Optional

from app.credentials import CredentialManager, PRIMARY_ACCOUNT_ID


class _Slot:
    """池中的一个账号槽位（适配器懒构造）"""

    def __init__(self, platform: str, account_id: str, label: str,
                 factory: Callable, enabled: bool = True):
        self.platform = platform
        self.account_id = account_id
        self.label = label
        self.factory = factory
        self.enabled = enabled
        self.adapter = None  # 懒构造，避免启动时实例化所有平台

    def get_adapter(self):
        if self.adapter is None:
            self.adapter = self.factory(self.account_id)
        return self.adapter

    def drop_adapter(self):
        """凭证变更后丢弃适配器实例，下次使用时按新 Cookie 重建"""
        self.adapter = None


class AdapterPool:
    """单平台的多账号适配器池"""

    def __init__(self, platform: str, factory: Callable):
        self.platform = platform
        self._factory = factory
        self._lock = threading.Lock()
        self._slots: list[_Slot] = []
        self._rr = 0  # 轮询游标
        self._active: set[str] = set()  # 当前有请求在执行的账号 id（"哪个账号正在展开"展示用）
        self._reload_slots()

    # ==================== 槽位维护 ====================

    def _reload_slots(self):
        """从凭证管理器重建槽位列表（主账号固定在前，附加账号按配置顺序）"""
        slots = []
        primary = CredentialManager.get_account(self.platform, PRIMARY_ACCOUNT_ID)
        slots.append(_Slot(
            self.platform, PRIMARY_ACCOUNT_ID,
            (primary or {}).get("name") or "主账号", self._factory,
            enabled=bool((primary or {}).get("enabled", True)),
        ))
        for acc in CredentialManager.get_accounts(self.platform):
            if acc["id"] == PRIMARY_ACCOUNT_ID:
                continue
            if acc.get("enabled", True):
                slots.append(_Slot(
                    self.platform, acc["id"], acc.get("name") or acc["id"], self._factory
                ))
        with self._lock:
            self._slots = slots
            self._rr = 0

    def reload(self):
        """accounts.json 变更后调用：重建槽位列表"""
        self._reload_slots()

    def reset(self):
        """Cookie 内容更新后调用：丢弃所有适配器实例（槽位不变），强制按新凭证重建"""
        with self._lock:
            for s in self._slots:
                s.drop_adapter()

    def clear_caches(self) -> tuple[int, dict]:
        """
        清空平台运行期内存缓存（"清理缓存"按钮用）：
        先让各存活适配器清理自己持有的实例缓存/模块级缓存（如抖音 msToken），
        再丢弃全部适配器实例，下次使用按当前凭证重建。

        返回 (清掉的适配器实例数, {缓存名: 清理条数})
        """
        with self._lock:
            slots = list(self._slots)
        dropped = 0
        items: dict[str, int] = {}
        for s in slots:
            if s.adapter is not None:
                dropped += 1
                try:
                    for name, n in (s.adapter.clear_cache() or {}).items():
                        items[name] = items.get(name, 0) + int(n)
                except Exception:
                    pass  # 单实例清理失败不阻塞整体（实例随后被丢弃，缓存同样失效）
            s.drop_adapter()
        return dropped, items

    # ==================== 基本信息 ====================

    @property
    def size(self) -> int:
        """可用账号数（参与轮询的槽位数，停用账号不计入）"""
        with self._lock:
            return sum(1 for s in self._slots if s.enabled)

    @property
    def total(self) -> int:
        """账号总数（含主账号，等同 size）"""
        return self.size

    def primary(self):
        """主账号适配器（历史记录等私有数据接口固定走主账号；主账号停用仍可用）"""
        with self._lock:
            slot = self._slots[0] if self._slots else None
        return slot.get_adapter() if slot else None

    def adapter_for_account(self, account_id: str):
        """取指定账号槽位的适配器（懒构造，供单账号可用性测试用）；无此账号返回 None"""
        with self._lock:
            for s in self._slots:
                if s.account_id == account_id:
                    return s.get_adapter()
        return None

    def label_for(self, adapter) -> str:
        """查询适配器所属账号的显示名（错误信息标注用）"""
        with self._lock:
            slot = self._find_slot(adapter)
        return slot.label if slot else "未知账号"

    def active_labels(self) -> list[str]:
        """当前有请求正在执行的账号标签列表（队列面板"哪个账号正在展开"用）"""
        with self._lock:
            active = set(self._active)
        return [s.label for s in self._slots if s.account_id in active]

    # ==================== 租借 ====================

    @contextmanager
    def lease(self):
        """
        借出一个账号的适配器（轮询分配）。

        用法:
            with pool.lease() as adapter:
                adapter.get_follows(uid, limit)

        租借期间该账号计入 _active，供 active_labels() 报告"哪些账号正在执行"。
        """
        slot = self._acquire()
        if slot is None:
            yield None
            return
        with self._lock:
            self._active.add(slot.account_id)
        try:
            yield slot.get_adapter()
        finally:
            with self._lock:
                self._active.discard(slot.account_id)

    def _acquire(self) -> Optional[_Slot]:
        with self._lock:
            enabled = [s for s in self._slots if s.enabled]
            if not enabled:
                return None
            slot = enabled[self._rr % len(enabled)]
            self._rr += 1
            return slot

    def _find_slot(self, adapter) -> Optional[_Slot]:
        for s in self._slots:
            if s.adapter is adapter:
                return s
        return None
