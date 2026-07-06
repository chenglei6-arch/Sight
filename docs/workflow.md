# 接入新平台工作流程

> 本文档指导开发者如何将一个新平台接入本监控系统。
> 以接入「微博」(weibo) 为示例贯穿全文。

---

## 目录

1. [整体流程](#1-整体流程)
2. [前置调研](#2-前置调研)
3. [创建适配器文件](#3-创建适配器文件)
4. [实现适配器方法](#4-实现适配器方法)
5. [注册适配器](#5-注册适配器)
6. [配置凭证](#6-配置凭证)
7. [添加前端侧边栏](#7-添加前端侧边栏)
8. [注册时间线](#8-注册时间线)
9. [验证测试](#9-验证测试)
10. [完整检查清单](#10-完整检查清单)
11. [参考资源](#11-参考资源)

---

## 1. 整体流程

接入一个新平台需要修改 **6 处代码** + **1 个新目录**：

```
① app/platforms/weibo/          ← 新建适配器目录 + adapter.py
② app/platforms/__init__.py     ← 注册 get_adapter()
③ app/credentials/__init__.py   ← 添加凭证文件映射
④ app/templates/index.html      ← 添加侧边栏 nav-card
⑤ app/services/timeline.py      ← 添加平台名/内容类型映射
⑥ app/static/js/app.js          ← （可选）前端渲染适配
```

预期耗时：**2-4 小时**（调研 API 另计）

---

## 2. 前置调研

在写代码之前，先搞清楚目标平台的 API 情况：

### 2.1 API 清单

| 问题 | 说明 |
|------|------|
| 官方 API 文档？ | 大多数平台没有公开 API，需抓包 |
| 需要什么认证？ | Cookie / Token / OAuth 2.0 / API Key |
| 有无 SSRF/CSRF 问题？ | 后端直接调用需考虑 IP 白名单 |
| 频率限制？ | 每秒/每分钟多少请求 |
| SSL 兼容性？ | Python requests 是否能正常 TLS 握手 |
| 数据格式？ | JSON / JSONP / XML / RSS / SSR HTML |
| 是否要签名？ | 如抖音 a_bogus、网易云 weapi |

### 2.2 必测 API

以下 API 必须至少找到一种方案实现：

```python
# 必须实现（BasePlatformAdapter 抽象方法）
get_profile(uid)          # 用户资料 — 最基本
search_user(keyword)      # 用户搜索 — 前端需要

# 强烈建议实现
get_content_lists(uid)    # 内容列表（歌单/投稿/作品）
get_events(uid)           # 用户动态
get_follows(uid)          # 关注列表
get_followers(uid)        # 粉丝列表

# 可选实现
get_content_detail(id)    # 内容详情（含子项列表）
get_history(uid, period)  # 播放/观看排行
```

### 2.3 查找参考项目

```bash
# 搜索 GitHub 上该平台的第三方 API 实现
# 下载到 reference/ 目录作为参考
git clone https://github.com/xxx/xxx-api reference/xxx-api
```

---

## 3. 创建适配器文件

### 3.1 目录结构

```
app/platforms/weibo/
├── __init__.py     # 导出 WeiboAdapter
└── adapter.py      # 主适配器
```

### 3.2 `__init__.py`

```python
from .adapter import WeiboAdapter

__all__ = ["WeiboAdapter"]
```

### 3.3 `adapter.py` 框架

```python
"""
微博平台适配器

基于 weibo.com 公开 API 的数据采集实现。

API 说明:
  - api.weibo.com/2/...  微博开放平台 API
  - 需要 Cookie (SUB, SUBP 等字段)
  - 频率限制: 100 次/小时（未认证）

已知限制:
  - 搜索功能对未登录用户限制严格
  - ...
"""
import json
import os
import time
import re
from typing import Optional

import requests

from app.platforms.base import (
    BasePlatformAdapter, PlatformProfile,
    ContentItem, MediaEntry, EventItem,
)
from app.credentials import CredentialManager
from app.config import REQUEST_TIMEOUT, MAX_RETRIES


class WeiboAdapter(BasePlatformAdapter):
    """微博平台适配器"""

    platform_id = "weibo"
    platform_name = "微博"

    # API 基础地址
    API_BASE = "https://api.weibo.com/2"
    WEB_BASE = "https://weibo.com"

    def __init__(self, credentials: dict = None):
        super().__init__(credentials)
        self._session: requests.Session | None = None

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        """构建请求会话（带 Cookie 和 UA）"""
        s = requests.Session()
        cookies = CredentialManager.load_cookies("weibo")
        if cookies:
            for key, value in cookies.items():
                s.cookies.set(key, value)
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
            "Referer": "https://weibo.com/",
        })
        return s

    # ========== 必须实现 ==========

    def get_profile(self, uid: str) -> Optional[PlatformProfile]:
        ...
        # TODO: 实现用户资料获取

    def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
        ...
        # TODO: 实现用户搜索

    # ========== 内容相关 ==========

    def get_content_lists(self, uid: str) -> list[ContentItem]:
        return []  # TODO: 实现

    def get_events(self, uid: str, limit: int = 30) -> list[EventItem]:
        return []  # TODO: 实现

    def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
        return []  # TODO: 实现

    def get_followers(self, uid: str, limit: int = 100) -> list[dict]:
        return []  # TODO: 实现

    def check_alive(self) -> bool:
        """检查 Cookie 是否有效"""
        try:
            cookies = CredentialManager.load_cookies("weibo")
            return bool(cookies)
        except Exception:
            return False

    def get_login_user(self) -> Optional[dict]:
        """获取当前登录用户"""
        cookies = CredentialManager.load_cookies("weibo")
        # 从 Cookie 中提取 uid（不同平台提取方式不同）
        uid = cookies.get("uid", "") or cookies.get("SUBP", "")
        if uid:
            return {"uid": uid, "nickname": "", "avatarUrl": ""}
        return None
```

---

## 4. 实现适配器方法

### 4.1 通用实现原则

| 原则 | 说明 |
|------|------|
| **SSR 优先** | 优先从 HTML 页面提取数据（避免签名/鉴权） |
| **API 兜底** | SSR 不足时再调 API |
| **多策略瀑布** | 一个方法尝试多种策略，命中即返回 |
| **缓存优化** | 重复请求缓存 SSR 页面、搜索结果 |
| **降级** | SSL 失败降级 curl，API 超时降级其他策略 |
| **错误容忍** | 单个模块失败不影响整体，打印错误继续 |

### 4.2 `get_profile()` 实现模式

```python
def get_profile(self, uid: str) -> Optional[PlatformProfile]:
    uid = str(uid).strip()
    if not uid:
        return None

    # 策略 1: 优先从 API 获取
    profile = self._get_profile_via_api(uid)
    if profile:
        return profile

    # 策略 2: SSR 页面兜底
    return self._get_profile_via_ssr(uid)
```

### 4.3 `search_user()` 多策略模式

```python
def search_user(self, keyword: str, limit: int = 20) -> list[dict]:
    # 策略 1: 如果纯数字，可能是 UID，直接查资料
    if keyword.isdigit():
        profile = self.get_profile(keyword)
        if profile:
            return [{"uid": profile.uid, "nickname": profile.nickname, ...}]

    # 策略 2: API 搜索
    users = self._search_via_api(keyword, limit)
    if users:
        return users

    # 策略 3: 网页搜索兜底
    return self._search_via_web(keyword, limit)
```

### 4.4 `get_follows()` encrypt_uin 处理

某些平台（如 QQ Music）会隐藏用户 ID。适配器需处理：

```python
def get_follows(self, uid: str, limit: int = 100) -> list[dict]:
    # 对加密用户：返回空列表（关注数已存 profile.extra）
    # 不返回 _count_only 标记，避免破坏快照持久化
    if self._is_encrypted_uid(uid):
        return []

    # 正常流程：分页获取
    ...
```

---

## 5. 注册适配器

### 5.1 `app/platforms/__init__.py`

在 `get_adapter()` 函数中添加新平台的延迟加载分支：

```python
def get_adapter(platform_id: str) -> Optional["BasePlatformAdapter"]:
    adapter = _registry.get(platform_id)
    if adapter:
        return adapter

    # ... 已有平台 ...

    if platform_id == "weibo":                          # ← 新增
        from app.platforms.weibo.adapter import WeiboAdapter
        adapter = WeiboAdapter()
        _registry[platform_id] = adapter
        return adapter

    return None
```

---

## 6. 配置凭证

### 6.1 `app/credentials/__init__.py`

在 `PLATFORM_FILES` 字典中添加凭证文件映射：

```python
class CredentialManager:
    PLATFORM_FILES = {
        "netease": "netease_cookie.txt",
        "bilibili": "bilibili_cookie.txt",
        "douyin": "douyin_cookie.txt",
        "qqmusic": "qqmusic_cookie.txt",
        "weibo": "weibo_cookie.txt",        # ← 新增
    }

    # 文件名别名（可选，兼容旧文件名）
    PLATFORM_ALIASES = {
        "bilibili": ["billbill_cookie.txt", "bilibili_cookie.txt"],
        "qqmusic": ["y.qq_cookie.txt"],
        # "weibo": ["sina_cookie.txt"],      # ← 可按需添加别名
    }
```

### 6.2 凭证文件

在 `credentials/` 目录下创建 Cookie 文件：

```
credentials/weibo_cookie.txt
```

格式：从浏览器复制的完整 Cookie 字符串（`key1=value1; key2=value2; ...`）

### 6.3 测试凭证加载

```python
from app.credentials import CredentialManager

cookies = CredentialManager.load_cookies("weibo")
print(f"Cookie 字段: {list(cookies.keys())}")
```

---

## 7. 添加前端侧边栏

### 7.1 `app/templates/index.html`

在侧边栏找到其他平台的 `nav-card`，按同样的结构添加：

```html
<!-- 微博 -->
<div class="nav-card" id="nav-weibo" data-view="weibo">
  <div class="nav-card-header" onclick="switchView('weibo')">
    <span class="pc-icon">💬</span>
    <span>微博</span>
    <span class="pc-status" id="weibo-status">●</span>
  </div>
  <div class="nav-card-body">
    <div class="pc-input-row">
      <input type="text" id="weibo-uid" placeholder="输入 UID 或昵称..." value=""
             onchange="onUidChange('weibo')"
             onkeydown="if(event.key==='Enter') searchAndSet('weibo')">
      <button onclick="searchAndSet('weibo')">🔍</button>
    </div>
    <div class="pc-search-results" id="weibo-results"></div>
    <div class="pc-profile-mini" id="weibo-mini"></div>
  </div>
</div>
```

关键点：

| 属性 | 规则 | 示例 |
|------|------|------|
| `id="nav-xxx"` | 平台标识 | `nav-weibo` |
| `data-view="xxx"` | 与平台 ID 一致 | `weibo` |
| `onclick="switchView('xxx')"` | 同上 | `switchView('weibo')` |
| `id="xxx-uid"` | `{平台ID}-uid` | `weibo-uid` |
| `onchange="onUidChange('xxx')"` | 同上 | `onUidChange('weibo')` |
| `searchAndSet('xxx')` | 同上 | `searchAndSet('weibo')` |
| `id="xxx-results"` | 搜索结果容器 | `weibo-results` |
| `id="xxx-mini"` | 迷你资料容器 | `weibo-mini` |
| `id="xxx-status"` | 状态指示器 | `weibo-status` |

### 7.2 前端自动渲染

前端 `app.js` 的 `switchView()` 和 `loadPlatformData()` 是通用函数，自动处理所有平台：

```javascript
function switchView(platform) {
    // 不需要针对每个平台写 switch case
    // 只需要保障:
    //   1. DOM 中存在 id 为 nav-{platform} 的卡片
    //   2. DOM 中存在 id 为 {platform}-uid 的输入框
    //   3. DOM 中存在 id 为 {platform}-results 的结果容器
    //   4. DOM 中存在 id 为 {platform}-mini 的迷你资料容器
    //   5. DOM 中存在 id 为 {platform}-status 的状态指示器
    // 渲染逻辑自动适配
}
```

**注意**：前端默认通过 `GET /api/{platform}/all?uid=xxx` 加载数据。
如果新平台的某个数据模块（如 records、follows）返回空结构但希望前端仍能显示，需在前端做防御性渲染（`app.js` 已有处理）。

---

## 8. 注册时间线

### 8.1 `app/services/timeline.py`

将新平台添加到名称映射表：

```python
class TimelineBuilder:
    PLATFORM_NAME_MAP = {
        "netease": "网易云音乐",
        "bilibili": "哔哩哔哩",
        "douyin": "抖音",
        "qqmusic": "QQ音乐",
        "weibo": "微博",              # ← 新增
    }

    CONTENT_TYPE_MAP = {
        "netease": "歌单",
        "bilibili": "视频",
        "douyin": "作品",
        "qqmusic": "歌单",
        "weibo": "微博",              # ← 新增（根据平台内容类型填）
    }
```

`PLATFORM_NAME_MAP` 用于时间线条目的 `[平台名]` 前缀显示。
`CONTENT_TYPE_MAP` 用于时间线条目描述中的"发布了{内容类型}《标题》"。

### 8.2 时间线自动适配

时间线构建器 `TimelineBuilder.build()` 对**所有平台**自动运行以下检测：

| 检测 | 数据来源 | 自动生效？ |
|------|----------|-----------|
| 动态事件 | `get_events()` + events 快照 | ✅ 自动 |
| 内容发布 | `get_content_lists()` + playlists 快照 | ✅ 自动 |
| 关注变化 | follows 快照对比 | ✅ 自动 |
| 粉丝变化 | followers 快照对比 | ✅ 自动 |
| 歌单歌曲变化 | playlist_songs 快照对比 | ✅ 自动 |
| 听歌记录 | records 快照对比 | ⚠️ 仅 netease |
| 内容变化 | playlists 快照对比 | ✅ 自动 |

**无需为时间线写任何平台特定代码**，只要适配器返回正确的数据类型，时间线自动工作。

---

## 9. 验证测试

### 9.1 单元测试

```python
# 创建临时测试脚本或 pytest 用例

from app.platforms.weibo.adapter import WeiboAdapter

ada = WeiboAdapter()

# 测试 1: 连接状态
print("check_alive:", ada.check_alive())

# 测试 2: 搜索
users = ada.search_user("测试用户")
print(f"搜索到 {len(users)} 个用户")
for u in users[:3]:
    print(f"  - {u['nickname']} ({u['uid']})")

# 测试 3: 用户资料
profile = ada.get_profile("123456789")
if profile:
    print(f"昵称: {profile.nickname}")
    print(f"签名: {profile.signature}")

# 测试 4: 内容列表
items = ada.get_content_lists("123456789")
print(f"内容: {len(items)} 项")

# 测试 5: 关注/粉丝
follows = ada.get_follows("123456789")
print(f"关注: {len(follows)} 人")
```

### 9.2 数据持久化测试

```python
from app.data.store import DataStore

store = DataStore()
uid = "123456789"

# 模拟数据保存
profile = ada.get_profile(uid)
if profile:
    store.save_snapshot("weibo", uid, "profile", {
        "platform": "weibo", "uid": uid,
        "nickname": profile.nickname, ...
    })

# 验证读取
snap = store.get_latest_snapshot("weibo", uid, "profile")
print(f"快照时间: {snap.get('_snapshot_time')}")
```

### 9.3 前端验证

1. 启动服务: `python run.py`
2. 浏览器访问 `http://127.0.0.1:5000`
3. 侧边栏应出现新平台卡片
4. 搜索用户 → 选择 → 资料/内容/关注 正确显示
5. 自动采集器正常工作
6. 时间线正确生成事件

### 9.4 测试检查清单

```
□ 搜索 -> 选择 -> 加载资料
□ 关注列表（有数据/空/加密用户三种情况）
□ 粉丝列表
□ 内容列表（有/无数据）
□ 动态列表
□ 自动采集器加入后正常运行
□ 时间线中新平台事件正常显示
□ 多次采集快照去重正常
□ 变化检测正常（需模拟数据变化）
□ Cookie 过期时优雅降级
```

---

## 10. 完整检查清单

### 10.1 代码文件

| # | 文件 | 操作 | 完成 |
|---|------|------|------|
| 1 | `app/platforms/{new}/__init__.py` | 新建，导出 Adapter | □ |
| 2 | `app/platforms/{new}/adapter.py` | 新建，实现所有方法 | □ |
| 3 | `app/platforms/__init__.py` | 修改，注册 `get_adapter()` | □ |
| 4 | `app/credentials/__init__.py` | 修改，添加 `PLATFORM_FILES` | □ |
| 5 | `app/templates/index.html` | 修改，添加 nav-card | □ |
| 6 | `app/services/timeline.py` | 修改，添加名称映射 | □ |
| 7 | `credentials/{platform}_cookie.txt` | 新建，粘贴 Cookie | □ |

### 10.2 适配器方法实现状态

| 方法 | 优先级 | 状态 | 说明 |
|------|--------|------|------|
| `check_alive()` | P0 必须 | □ | 检查凭证有效性 |
| `get_login_user()` | P0 必须 | □ | 获取当前登录用户 |
| `get_profile(uid)` | P0 必须 | □ | 用户资料 |
| `search_user(keyword)` | P0 必须 | □ | 搜索用户（多策略） |
| `get_content_lists(uid)` | P1 推荐 | □ | 内容列表 |
| `get_events(uid)` | P1 推荐 | □ | 用户动态 |
| `get_follows(uid)` | P1 推荐 | □ | 关注列表 |
| `get_followers(uid)` | P1 推荐 | □ | 粉丝列表 |
| `get_content_detail(id)` | P2 可选 | □ | 内容详情 |
| `get_history(uid, period)` | P2 可选 | □ | 排行历史 |

### 10.3 数据流验证

```
访问 /api/{platform}/profile?uid=xxx     ✅ 返回正确 JSON
访问 /api/{platform}/search?keyword=xxx   ✅ 返回用户列表
访问 /api/{platform}/all?uid=xxx          ✅ 返回全量数据并保存快照
访问 /api/timeline?uids={platform}:xxx    ✅ 时间线包含新平台事件
自动采集器启动                             ✅ 快照正常保存，日志生成
```

---

## 11. 参考资源

### 参考实现

| 平台 | 文件 | 特点 |
|------|------|------|
| 网易云 | `netease/adapter.py` | weapi AES+RSA 加密，多策略 Profile 获取 |
| B站 | `bilibili/adapter.py` | 频率限制退避，快照优先策略 |
| 抖音 | `douyin/adapter.py` | SSR 优先 + a_bogus 签名兜底 |
| QQ音乐 | `qqmusic/adapter.py` | encrypt_uin 处理，curl SSL 降级 |

### 文档参考

- [平台适配器详解](platforms.md) — 各平台实现细节
- [项目总览](project_overview.md) — 数据库、时间线、API 设计
- [QQ音乐 API研究](qqmusic_research.md) — encrypt_uin 等特殊机制

### 代码速查

```python
# 数据模型（app/platforms/base.py）
PlatformProfile  # 用户资料
ContentItem      # 内容列表项
MediaEntry       # 媒体条目（歌曲/视频）
EventItem        # 动态事件

# 数据存储（app/data/store.py）
DataStore.save_snapshot(platform, uid, data_type, data)
DataStore.get_latest_snapshot(platform, uid, data_type)

# 请求工具
from app.config import REQUEST_TIMEOUT, MAX_RETRIES
from app.credentials import CredentialManager
```
