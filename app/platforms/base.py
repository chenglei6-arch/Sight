"""
平台适配器抽象基类

所有平台（网易云、B站等）必须实现此接口。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PlatformProfile:
    """统一用户资料模型"""
    platform: str                    # 平台标识: netease / bilibili / ...
    uid: str                         # 用户 ID
    nickname: str                    # 昵称
    avatar_url: str = ""             # 头像 URL
    background_url: str = ""         # 背景图 URL
    signature: str = ""              # 个性签名
    gender: int = 0                  # 0=未设 1=男 2=女
    birthday: str = ""               # 生日
    location: str = ""               # 所在地
    join_time: str = ""              # 注册时间
    level: int = 0                   # 等级
    is_vip: bool = False             # 是否为会员
    vip_label: str = ""              # 会员标签
    extra: dict = field(default_factory=dict)  # 平台特有字段


@dataclass
class ContentItem:
    """统一内容项模型（歌单/收藏夹/投稿等）"""
    item_id: str                     # 内容 ID
    title: str                       # 标题
    cover_url: str = ""              # 封面 URL
    count: int = 0                    # 内容数量（歌曲数/视频数等）
    view_count: int = 0              # 播放/浏览数
    creator: str = ""                # 创建者
    description: str = ""            # 描述
    is_owner: bool = True            # 是否自创（False=收藏）
    create_time: str = ""            # 创建时间
    url: str = ""                    # 原始链接
    extra: dict = field(default_factory=dict)


@dataclass
class MediaEntry:
    """统一媒体条目模型（歌曲/视频等）"""
    entry_id: str
    title: str
    artist_or_uploader: str = ""     # 艺人/UP主
    album_or_category: str = ""      # 专辑/分区
    cover_url: str = ""
    duration: int = 0                # 时长(ms)
    play_count: int = 0              # 播放次数
    extra: dict = field(default_factory=dict)


@dataclass
class EventItem:
    """统一动态模型"""
    event_id: str
    event_type: str                  # 动态类型标签
    content: str = ""                # 文字内容
    timestamp: int = 0               # 时间戳(ms)
    media_title: str = ""            # 关联内容标题
    media_artist: str = ""           # 关联内容作者
    url: str = ""                    # 原始链接
    extra: dict = field(default_factory=dict)


def dataclass_to_dict(obj):
    """递归把 dataclass（含嵌套 dataclass/list/dict）转为纯 dict"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for key in obj.__dataclass_fields__:
            val = getattr(obj, key)
            if hasattr(val, "__dataclass_fields__"):
                result[key] = dataclass_to_dict(val)
            elif isinstance(val, list):
                result[key] = [dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__") else v for v in val]
            elif isinstance(val, dict):
                result[key] = {
                    k: dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__") else v
                    for k, v in val.items()
                }
            else:
                result[key] = val
        return result
    return obj


class BasePlatformAdapter(ABC):
    """
    平台适配器抽象基类

    每个平台需实现以下方法。
    未实现的方法默认返回空数据。
    """

    platform_id: str = "__base__"    # 子类必须覆盖
    platform_name: str = "Base"      # 平台中文名

    def __init__(self, credentials: dict = None, account_id: str = None):
        self.credentials = credentials or {}
        # 多账号池绑定的账号 ID；None = 主账号（credentials/<platform>_cookie.txt），
        # 其他值 = accounts.json 中的附加账号。子类加载 Cookie 时应使用 _load_cookies()。
        self.account_id = account_id

    def _load_cookies(self) -> dict:
        """加载本实例绑定账号的 Cookie（子类的 Cookie 读取统一走这里）"""
        from app.credentials import CredentialManager
        return CredentialManager.load_cookies(self.platform_id, getattr(self, "account_id", None))

    # ==================== 必须实现 ====================

    @abstractmethod
    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        """获取用户资料"""
        ...

    @abstractmethod
    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜索用户，返回 [{uid, nickname, avatarUrl, ...}]"""
        ...

    # ==================== 内容相关（可选实现） ====================

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        """获取用户的内容列表（歌单/收藏夹）"""
        return []

    def get_content_detail(self, item_id: str) -> Optional[dict]:
        """获取内容详情（含条目列表）"""
        return None

    # ==================== 历史/排行（可选实现） ====================

    def get_history(self, uid: str, period: str = "all") -> list[MediaEntry]:
        """
        获取用户收听/观看历史排行
        period: "all" | "week"
        """
        return []

    # ==================== 动态（可选实现） ====================

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        """获取用户动态"""
        return []

    # ==================== 社交（可选实现） ====================

    def get_follows(self, uid: str, limit: int = 100, skip: int = 0) -> tuple:
        """
        获取关注列表。
        统一返回 (条目列表, 是否还有更多, 真实总数或 -1)；
        skip>0 表示跳过前面 skip 条（已拉取的人），用于增量续拉。
        """
        return [], False, -1

    def get_followers(self, uid: str, limit: int = 100, skip: int = 0) -> tuple:
        """
        获取粉丝列表。
        统一返回 (条目列表, 是否还有更多, 真实总数或 -1)；
        skip>0 表示跳过前面 skip 条（已拉取的人），用于增量续拉。
        """
        return [], False, -1

    def refresh_user_info(self, uid: str) -> Optional[dict]:
        """
        重新拉取单个用户的最新信息（图谱"重新标记"用）。
        返回 {"nickname": str, "fans": int, "is_verified": bool 缺省则不更新}，
        平台不支持时返回 None。
        """
        return None

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查平台连接/凭证是否有效"""
        return True

    def get_login_user(self) -> Optional[dict]:
        """获取当前凭证对应的登录用户信息"""
        return None

    # ==================== 缓存清理 ====================

    def clear_cache(self) -> dict:
        """清空适配器内存缓存，返回 {缓存名: 清理条数} 供界面反馈。

        实例级缓存（用户缓存/session 等）随适配器实例丢弃自动清空，
        由 AdapterPool.clear_caches() 统一处理；子类只需在此额外清理
        模块级缓存（如抖音 msToken），并报告实例级缓存的条数。
        """
        return {}

    # ==================== 账号可用性测试 ====================

    def test_account(self) -> dict:
        """测试当前账号凭证可用性（账号弹窗"测试"按钮用），返回 {ok, login_user?, error?, warning?}。

        默认走 check_alive + get_login_user（各平台探测深度不一）；
        平台存在"轻接口能过但私有接口已失效"的凭证时（如抖音）应覆写加深探测。
        """
        try:
            if not self.check_alive():
                return {"ok": False, "error": "凭证无效或已过期"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        result: dict = {"ok": True}
        try:
            result["login_user"] = self.get_login_user()
        except Exception as e:
            result["warning"] = f"登录用户识别失败: {e}"
        return result
