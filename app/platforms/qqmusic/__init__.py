"""
QQ音乐平台适配器

基于 y.qq.com / c.y.qq.com 公开 API 的数据采集实现。

功能:
  - 用户资料查询 (API + 页面)
  - 用户搜索 (歌手搜索 + 直接查资料)
  - 歌单列表 (创建 + 收藏)
  - 歌单详情 (含歌曲列表)
  - 用户听歌排行

API 特点:
  - 需要 Referer: https://y.qq.com 防盗链
  - 返回 JSONP 格式
  - g_tk 参数用于鉴权 (未登录=5381)

使用:
    from app.platforms.qqmusic.adapter import QQMusicAdapter
    adapter = QQMusicAdapter()
    profile = adapter.get_profile("123456789")
"""

from app.platforms.qqmusic.adapter import QQMusicAdapter

__all__ = ["QQMusicAdapter"]
