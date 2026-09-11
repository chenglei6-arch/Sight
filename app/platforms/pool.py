"""
多账号适配器池 —— 多账号并发查询的核心。

账号模型:
- 主账号: credentials/<platform>_cookie.txt，账号 ID 固定为 "primary"（与旧行为一致）
- 附加账号: credentials/accounts.json（通过 /api/accounts/<platform> 管理）

每个账号对应一个独立的适配器实例。各适配器的限速状态
（_last_request_at / 限速锁 / B站惩罚计数等）天然按实例隔离，
因此 N 个账号 = N 条互不阻塞的请求流水线。

调度采用"租借制": 调用方通过 lease() 借出一个适配器、用完即还，
池内轮询分配；停用的账号不参与分配。
"""
import threading
from contextlib import contextmanager
from typing import Callable, Optional

from app.credentials import CredentialManager

PRIMARY_ACCOUNT_ID = "primary"


class _Slot:
    """池中的一个账号槽位（适配器懒构造）"""

    def __init__(self, platform: str, account_id: str, label: str,
                 factory: Callable):
        self.platform = platform
        self.account_id = account_id
        self.label = label
        self.factory = factory
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
        self._reload_slots()

    # ==================== 槽位维护 ====================

    def _reload_slots(self):
        """从凭证管理器重建槽位列表（主账号固定在前，附加账号按配置顺序）"""
        slots = [_Slot(self.platform, PRIMARY_ACCOUNT_ID, "主账号", self._factory)]
        for acc in CredentialManager.get_accounts(self.platform):
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

    # ==================== 基本信息 ====================

    @property
    def size(self) -> int:
        """可用账号数（参与轮询的槽位数）"""
        with self._lock:
            return len(self._slots)

    @property
    def total(self) -> int:
        """账号总数（含主账号，等同 size）"""
        return self.size

    def primary(self):
        """主账号适配器（历史记录等私有数据接口固定走主账号）"""
        with self._lock:
            slot = self._slots[0] if self._slots else None
        return slot.get_adapter() if slot else None

    def label_for(self, adapter) -> str:
        """查询适配器所属账号的显示名（错误信息标注用）"""
        with self._lock:
            slot = self._find_slot(adapter)
        return slot.label if slot else "未知账号"

    # ==================== 租借 ====================

    @contextmanager
    def lease(self):
        """
        借出一个账号的适配器（轮询分配）。

        用法:
            with pool.lease() as adapter:
                adapter.get_follows(uid, limit)
        """
        slot = self._acquire()
        try:
            yield slot.get_adapter() if slot else None
        finally:
            pass  # 适配器长期归槽位所有，租借只是"约定本次由它出请求"

    def _acquire(self) -> Optional[_Slot]:
        with self._lock:
            if not self._slots:
                return None
            slot = self._slots[self._rr % len(self._slots)]
            self._rr += 1
            return slot

    def _find_slot(self, adapter) -> Optional[_Slot]:
        for s in self._slots:
            if s.adapter is adapter:
                return s
        return None
