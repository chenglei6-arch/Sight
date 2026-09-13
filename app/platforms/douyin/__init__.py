"""
抖音平台适配器

基于 chenglei6-arch/DouYin_Spider（cv-cat/DouYin_Spider 的 fork）的纯 API 实现。
上游与同步约定见 docs/MANUAL.md（上游同步节）。原仓库 cv-cat/DouYin_Spider 有 bug，勿从原仓库同步。

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
"""

from app.platforms.douyin.adapter import DouyinAdapter

__all__ = ["DouyinAdapter"]
