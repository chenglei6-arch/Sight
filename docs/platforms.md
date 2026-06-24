# 抖音 & QQ音乐平台适配器文档

## 目录
1. [概述](#概述)
2. [抖音平台适配器](#抖音平台适配器)
3. [QQ音乐平台适配器](#qq音乐平台适配器)
4. [配置指南](#配置指南)
5. [API参考](#api参考)
6. [常见问题](#常见问题)

---

## 概述

本项目 `workshop13-sight` 是一个多平台用户数据监控面板，支持以下平台：

| 平台 | 标识 | 核心功能 | 状态 |
|------|------|----------|------|
| 网易云音乐 | `netease` | 资料/歌单/排行/动态/关注 | ✅ 稳定 |
| 哔哩哔哩 | `bilibili` | 资料/投稿/动态/关注/粉丝 | ✅ 稳定 |
| **抖音** | `douyin` | 资料/作品/关注/粉丝/动态 | ✅ 已完善 |
| **QQ音乐** | `qqmusic` | 资料/歌单/动态/排行 | ✅ 新增 |

---

## 抖音平台适配器

### 文件结构

```
app/platforms/douyin/
├── __init__.py          # 模块初始化, 导出 DouyinAdapter
├── adapter.py           # 主适配器 (SSR + API 双策略)
├── abogus.py            # a_bogus 签名生成 (JS 方案 + 纯 Python 降级)
├── abogus_pure.py       # 纯 Python a_bogus (实验性)
├── douyin_sign.js       # a_bogus 签名 JS 源码
└── data/
    ├── FIXED_keystream.json    # RC4 密钥流
    └── time_mapping_sample.json # 时间戳映射表 (100 样本)
```

### 核心策略

适配器采用 **SSR优先 + API兜底** 的双策略架构：

1. **SSR RENDER_DATA** (优先)
   - 从抖音页面 HTML 的 `<script id="RENDER_DATA">` 提取内嵌 JSON 数据
   - **无需 a_bogus 签名**, 成功率较高
   - 适用于: 用户资料, 作品列表, 登录用户信息

2. **API + a_bogus** (兜底)
   - 通过 Node.js 执行 `douyin_sign.js` 生成 a_bogus 签名
   - 需要有效 Cookie (sessionid)
   - 适用于: 搜索, 关注/粉丝列表, 作品详情

### a_bogus 签名机制

a_bogus 是抖音 Web API 的反爬签名参数，生成流程：

1. 对 URL 查询参数做两次 SM3 哈希
2. 对 User-Agent 做 RC4 加密 → Base64 变种编码 → SM3 哈希
3. 组装 29 字节数组 (含时间戳,哈希片段,XOR校验)
4. 字节重排 → RC4 再加密 → Base64 变种编码

**实现方式**: 通过 PyExecJS 调用 Node.js 执行 `douyin_sign.js`，若 Node.js 不可用则降级到纯 Python 方案。

### 依赖项

- Node.js (v14+, 用于 a_bogus 签名)
- PyExecJS (`pip install pyexecjs`)

### 主要方法

| 方法 | 功能 | 数据来源 |
|------|------|----------|
| `check_alive()` | 检查 Cookie 有效性 | 首页 HTML |
| `get_login_user()` | 获取当前登录用户 | SSR + self API |
| `get_profile(uid)` | 获取用户资料 | SSR + /profile/other/ API |
| `search_user(keyword)` | 搜索用户 | API + SSR + 直接查询 |
| `get_content_lists(uid)` | 获取作品列表 | SSR + /aweme/post/ API |
| `get_content_detail(item_id)` | 获取作品详情 | /aweme/detail/ API |
| `get_follows(uid)` | 获取关注列表 | /following/list/ API |
| `get_followers(uid)` | 获取粉丝列表 | /follower/list/ API |
| `get_events(uid)` | 获取用户动态 | 基于作品列表 |

### 已知限制

1. **搜索功能受限**: 抖音 Web 搜索对未登录/新登录用户有严格限制，API 搜索可能返回空结果
2. **作品数量**: SSR 初始加载约 30 个作品，API 翻页最多 100 个
3. **Cookie 有效期**: sessionid 约 7 天过期，需定期更新
4. **反爬机制**: 频繁请求可能触发风控 (HTTP 429/403)

### 使用示例

```python
from app.platforms.douyin.adapter import DouyinAdapter

adapter = DouyinAdapter()
profile = adapter.get_profile("MS4wLjABAAAA...")  # sec_uid 或数字 UID
print(f"用户: {profile.nickname}")
print(f"粉丝: {profile.extra.get('follower_count')}")
```

---

## QQ音乐平台适配器

### 文件结构

```
app/platforms/qqmusic/
├── __init__.py     # 模块初始化, 导出 QQMusicAdapter
└── adapter.py      # 主适配器
```

### API 概述

QQ 音乐的 API 主要集中在 `c.y.qq.com` 域名下：

| API 端点 | 功能 | 是否需要登录 |
|----------|------|-------------|
| `u.y.qq.com/cgi-bin/musicu.fcg` | **用户搜索** (search_type=8) | 否 |
| `rsc/fcgi-bin/fcg_get_profile_homepage.fcg` | 用户主页/歌单 | 否(基础) |
| `qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg` | 歌单详情(含歌曲) | 否 |
| `soso/fcgi-bin/client_search_cp` | 歌曲/歌手搜索 | 否 |
| `musichall/fcgi-bin/fcg_yqqhomepagerecommend.fcg` | 首页推荐 | 否 |

### 关键机制

1. **g_tk 鉴权**: 从 Cookie 的 `skey` / `p_skey` 计算，新版本使用 `qqmusic_key` / `qm_keyst` 代替，未登录默认 `5381`
2. **防盗链**: 需要 `Referer: https://y.qq.com` 请求头
3. **JSONP 处理**: 自动检测并解析 JSONP 格式响应
4. **用户标识**: 使用 QQ 号 (`uin`) 作为用户 ID
5. **通用网关**: `u.y.qq.com/cgi-bin/musicu.fcg` 统一 POST 网关，`comm` 块自动注入 `g_tk`、`uin`、`format` 等公共参数

### 主要方法

| 方法 | 功能 | 备注 |
|------|------|------|
| `check_alive()` | 检查 Cookie 有效性 | 检测 cookie 字段 (qqmusic_key + uin) |
| `get_login_user()` | 获取登录用户 | 从 Cookie 读取 uin |
| `get_profile(uid)` | 获取用户资料 | 多策略: API → 歌单 → 页面 |
| `search_user(keyword)` | 搜索用户 | 通用网关 user search (search_type=8, 需 Cookie 登录态) + UIN 兜底 |
| `get_content_lists(uid)` | 获取歌单列表 | 创建 + 收藏 |
| `get_content_detail(item_id)` | 获取歌单详情 | 含完整歌曲列表 |
| `get_history(uid)` | 听歌排行 | 累计统计 |
| `get_events(uid)` | 用户动态 | 基于歌单创建/收藏 |

### 使用示例

```python
from app.platforms.qqmusic.adapter import QQMusicAdapter

adapter = QQMusicAdapter()
playlists = adapter.get_content_lists("123456789")  # QQ 号 (uin)
for pl in playlists:
    print(f"歌单: {pl.title} ({pl.count} 首)")
```

### 已知限制

1. **社交功能**: 关注/粉丝列表无公开 API
2. **Cookie 依赖**: 获取私人歌单/听歌排行需要登录 Cookie
3. **用户搜索需要登录态**: `musicu.fcg` 网关搜索用户 (`search_type=8`) 需要有效 Cookie + 正确的 `g_tk`，匿名请求返回空
4. **g_tk 计算**: Cookie 中 `qqmusic_key` / `qm_keyst` 是新版鉴权字段（替代 `skey`），适配器已支持自动检测
5. **check_alive**: 使用 cookie 字段检测代替已废弃的首页推荐接口（原接口返回 HTTP 500）
6. **接口变动**: QQ 音乐可能更新 API 参数，需持续适配

---

## 配置指南

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖包括: `flask`, `requests`, `pycryptodome`, `PyExecJS`

### 2. 配置 Cookie

在项目根目录的 `credentials/` 文件夹中创建 Cookie 文件：

```
credentials/
├── netease_cookie.txt    # 网易云音乐
├── bilibili_cookie.txt   # 哔哩哔哩
├── douyin_cookie.txt     # 抖音
└── qqmusic_cookie.txt    # QQ音乐 (可选)
```

#### 获取 Cookie 的方法

**抖音**:
1. 浏览器打开 `https://www.douyin.com/` 并登录
2. F12 → Application → Cookies → `www.douyin.com`
3. 复制所有 Cookie 字符串
4. 保存为 `credentials/douyin_cookie.txt`

**QQ音乐**:
1. 浏览器打开 `https://y.qq.com/` 并登录
2. F12 → Application → Cookies → `y.qq.com`
3. 复制所有 Cookie 字符串
4. 保存为 `credentials/qqmusic_cookie.txt` 或 `credentials/y.qq_cookie.txt`（别名自动识别）

### 3. 启动服务

```bash
python run.py
```

访问 `http://127.0.0.1:5000` 查看面板。

### 4. 启动自动采集

启动后，点击左侧栏的 "▶ 启动" 按钮或通过 API:

```bash
curl -X POST http://127.0.0.1:5000/api/collector/start
```

采集器默认每 30 分钟自动采集所有平台数据。

---

## API 参考

### 平台状态

```http
GET /api/{platform}/status
```

示例: `GET /api/douyin/status`

```json
{
  "code": 200,
  "data": {
    "platform": "douyin",
    "alive": true,
    "login_user": {
      "uid": "3402315065201417",
      "nickname": "用户xxx",
      "avatarUrl": "https://..."
    }
  }
}
```

### 用户资料

```http
GET /api/{platform}/profile?uid={uid}
```

### 用户搜索

```http
GET /api/{platform}/search?keyword={keyword}&limit=20
```

### 内容列表

```http
GET /api/{platform}/playlists?uid={uid}
```

### 全量数据

```http
GET /api/{platform}/all?uid={uid}
```

返回 profile, playlists, records, events, follows, followers 的聚合数据。

### 采集器控制

```http
GET  /api/collector/status      # 查看状态
POST /api/collector/start       # 启动采集
POST /api/collector/stop        # 停止采集
POST /api/collector/collect     # 立即采集一次
```

---

## 常见问题

### Q: 抖音搜索返回空结果怎么办？

抖音 Web 搜索有严格的反爬限制，这是已知问题。您可以通过以下方式缓解：

1. 使用新 Cookie 登录
2. 直接使用数字 UID 搜索（而非关键词）
3. 降低请求频率

### Q: QQ音乐提示 "未配置凭证"？

QQ音乐的大部分公开 API 不需要登录即可使用（资料、歌单搜索等）。
Cookie 文件不存在时，适配器会降级为未登录模式运行，部分功能受限。
如需完整功能，请按上述指南配置 Cookie。

### Q: a_bogus 签名失败？

确保已安装 Node.js (v14+) 和 PyExecJS：

```bash
node --version
pip install pyexecjs
```

如果 Node.js 不可用，适配器会自动尝试纯 Python 降级方案（有效性有限）。

### Q: 访问频率限制？

各平台适配器已内置请求间隔控制：
- 抖音: 2 秒 + 随机延迟
- QQ音乐: 1 秒 + 随机延迟

如遇 429/403 错误，适配器会自动指数退避重试。
