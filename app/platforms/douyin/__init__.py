"""
抖音平台适配器

基于 cv-cat/DouYin_Spider 的 DouyinAPI 纯 API 实现。
参考项目: https://github.com/cv-cat/DouYin_Spider

架构:
  - ref_builder/*  — 请求构建（auth、header、params、proto）
  - ref_dy_apis/*  — DouyinAPI 全部接口封装（douyin_api.py）
  - ref_utils/*    — 工具函数（签名、cookie、数据处理）
  - adapter.py     — 封装为 BasePlatformAdapter 统一接口

数据流:
  DouyinAPI (ref_dy_apis/douyin_api.py) static methods
    → 原生 JSON 响应
    → adapter.py 提取字段，转化为 PlatformProfile / ContentItem / EventItem

用法:
    from app.platforms.douyin.adapter import DouyinAdapter
    adapter = DouyinAdapter()
    profile = adapter.get_profile("sec_uid")
    works = adapter.get_content_lists("sec_uid")
    videos = adapter.search_content("关键词")
    comments = adapter.get_all_comments("aweme_id")
    feed = adapter.get_feed()
"""

from app.platforms.douyin.adapter import DouyinAdapter

__all__ = ["DouyinAdapter"]
