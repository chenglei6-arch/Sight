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


class BasePlatformAdapter(ABC):
    """
    平台适配器抽象基类

    每个平台需实现以下方法。
    未实现的方法默认返回空数据。
    """

    platform_id: str = "__base__"    # 子类必须覆盖
    platform_name: str = "Base"      # 平台中文名

    def __init__(self, credentials: dict = None):
        self.credentials = credentials or {}

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

    def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
        """获取关注列表"""
        return []

    def get_followers(self, uid: str, limit: int = 100) -> list[dict]:
        """获取粉丝列表"""
        return []

    # ==================== 状态检查 ====================

    def check_alive(self) -> bool:
        """检查平台连接/凭证是否有效"""
        return True

    def get_login_user(self) -> Optional[dict]:
        """获取当前凭证对应的登录用户信息"""
        return None
