# 多平台用户数据监控面板

实时采集网易云音乐、哔哩哔哩等多平台用户公开数据，**通过历史快照对比推断操作时间**，生成统一活动时间线。

目前已支持：网易云音乐、哔哩哔哩。后续计划扩展抖音、QQ、微信等平台。

## 快速启动

```bash
pip install -r requirements.txt
python run.py
# 访问 http://127.0.0.1:5000
```

## 目录结构

```
workshop13-sight/
│
├── run.py                          # 🚀 启动入口
├── requirements.txt                # Python 依赖
├── README.md                       # 本文档
├── .gitignore                      # 根级忽略（/data/ 只忽略根级数据库目录）
│
├── cookie.txt                      # [旧] 原始 Cookie（可删除，已迁移到 credentials/）
│
├── credentials/                    # 🔐 多平台凭证目录
│   ├── netease_cookie.txt          #   网易云 Cookie
│   └── bilibili_cookie.txt         #   B站 Cookie
│
├── data/                           # 💾 SQLite 数据库（gitignore）
│   └── snapshots.db                #   历史快照数据库
│
├── logs/                           # 📝 自动生成（gitignore）
│   ├── timeline_20260620_223000.txt
│   └── timeline_20260620_223000.json
│
└── app/                            # 📦 应用主包
    ├── __init__.py                 # Flask 应用工厂
    ├── config.py                   # 全局配置
    ├── .gitignore                  # App 级忽略
    │
    ├── platforms/                  # 🔌 平台适配器层
    │   ├── __init__.py             #   适配器注册中心
    │   ├── base.py                 #   抽象基类 + 统一数据模型
    │   ├── netease/                #   网易云音乐适配器
    │   │   ├── adapter.py          #     业务逻辑
    │   │   ├── client.py           #     HTTP 客户端 + 请求控制
    │   │   └── crypto.py           #     weapi AES+RSA 加密
    │   └── bilibili/               #   哔哩哔哩适配器
    │       └── adapter.py          #     业务逻辑 + HTTP 客户端
    │
    ├── credentials/                # 🔑 凭证管理器
    │   └── __init__.py             #   加载 / 保存 / 迁移 Cookie
    │
    ├── data/                       # 💾 数据持久化（源码，由 git 跟踪）
    │   ├── __init__.py
    │   └── store.py                #   SQLite 快照存储 + 全历史变化检测
    │
    ├── report/                     # 📈 报告生成
    │   └── generator.py            #   用户概览 / 趋势 / 跨平台报告
    │
    ├── services/                   # ⚙ 服务层
    │   ├── __init__.py
    │   ├── timeline.py             #   多平台统一时间线构建器
    │   ├── scheduler.py            #   定时自动采集器
    │   └── playlist_fetcher.py     #   歌单歌曲异步后台拉取
    │
    ├── routes/                     # 🌐 HTTP 路由
    │   ├── api.py                  #   REST API（含异步拉取路由）
    │   └── views.py                #   页面路由
    │
    ├── static/                     # 🎨 静态资源
    │   ├── css/style.css           #   暗色主题样式
    │   └── js/app.js               #   前端逻辑（搜索/视图/异步拉取/轮询）
    │
    └── templates/                  # 📄 模板
        └── index.html              #   主面板页面
```

## 核心架构

### 1. 时间推断系统（核心功能）

本项目的核心能力：**不依赖平台提供精确时间戳，而是通过对比不同时间点的数据快照，反向推断操作发生的时间窗口。**

```
T1 (10:00) 采集快照          T2 (10:30) 采集快照
┌─────────────────┐          ┌─────────────────────┐
│ 听歌排行:        │          │ 听歌排行:             │
│  老歌  50次     │   对比   │  老歌  55次 (+5)     │ → 10:00~10:30 又听了
│                 │   →     │  新歌  10次 (NEW)     │ → 10:00~10:30 开始听
│ 关注: [A]       │          │ 关注: [A, B]          │ → 10:00~10:30 关注了B
│ 歌单《X》: 3首  │          │ 歌单《X》: 4首        │ → 10:00~10:30 加入了1首
└─────────────────┘          └─────────────────────┘
```

**5 种可检测的变化类型：**

| 数据类型 | data_type | 检测内容 | 方法 |
|---------|-----------|---------|------|
| 听歌排行 | `records` | 新歌出现、播放次数增长 | `detect_record_changes()` |
| 关注列表 | `follows` | 新关注、取关 | `detect_follow_changes()` |
| 歌单列表 | `playlists` | 新建/收藏歌单、B站新投稿 | `detect_playlist_changes()` |
| 歌单歌曲 | `playlist_songs` | 歌单内新增/移除歌曲 | `detect_playlist_song_changes()` |
| 用户资料 | `profile` | 昵称/粉丝数等字段变化 | `compare_snapshots()` |

**跨全历史追踪：** `detect_record_changes()` 不只对比最近 2 次快照，而是遍历全部历史快照（最多 500 条），追踪每首歌从首次出现到每次播放增长的全轨迹。

| change_type | 含义 | 时间信息 | 示例 |
|------------|------|---------|------|
| `new` | 最近两次快照间新出现 | 精确时间窗口 | `06.20 10:00 ~ 10:30` |
| `increased` | 播放次数增长 | 精确时间窗口 | `06.20 10:00 ~ 10:30` |
| `first_seen` | 在更早快照中首次出现 | 首次出现窗口 | `06.18 08:00 ~ 06.18 08:30` |
| `ongoing` | 最早快照就已存在 | "至少从 XX 开始" | `⏳ 至少从 06.15 14:30 开始` |
| `new_first` | 仅有一次快照 | "首次采集" | — |

### 2. 平台适配器模式 (`app/platforms/`)

每个平台实现 `BasePlatformAdapter` 抽象基类：

| 方法 | 说明 |
|------|------|
| `get_profile(uid)` | 获取用户资料 → `PlatformProfile` |
| `search_user(keyword)` | 搜索用户 |
| `get_content_lists(uid)` | 内容列表（歌单/投稿）→ `list[ContentItem]` |
| `get_content_detail(id)` | 内容详情（含歌曲/视频列表） |
| `get_history(uid, period)` | 播放/观看历史 → `list[MediaEntry]` |
| `get_events(uid)` | 用户动态 → `list[EventItem]` |
| `get_follows(uid)` | 关注列表 |
| `get_followers(uid)` | 粉丝列表 |
| `check_alive()` | 检查凭证是否有效 |
| `get_login_user()` | 获取凭证对应的登录用户 |

**接入新平台**只需：
1. 在 `app/platforms/` 下新建目录
2. 实现 `BasePlatformAdapter` 所有方法
3. 在 `app/platforms/__init__.py` 的 `get_adapter()` 中注册
4. 在 `app/credentials/__init__.py` 的 `PLATFORM_FILES` 中添加凭证文件名
5. 在前端侧边栏添加 `nav-card`

### 3. 数据流

```
用户浏览器                     Flask 后端                     外部平台
   │                            │                              │
   │  GET /api/{p}/all          │                              │
   ├──────────────────────────►│                              │
   │                            │  优先读 DataStore 快照       │
   │                            │  快照不存在 → 调 adapter     │
   │                            ├─────────────────────────────►│
   │                            │◄─────────────────────────────┤
   │                            │  保存快照到 SQLite           │
   │◄───────────────────────────┤                              │
   │                            │                              │
   │  GET /api/timeline         │                              │
   ├──────────────────────────►│                              │
   │                            │  读取全部历史快照            │
   │                            │  detect_record_changes()     │
   │                            │  detect_follow_changes()     │
   │                            │  detect_playlist_changes()   │
   │                            │  detect_playlist_song_changes()
   │                            │  构建 TimelineEntry[]        │
   │                            │  按时间戳降序排列            │
   │◄───────────────────────────┤                              │
   │                            │                              │
   │  POST /api/{p}/fetch-songs/start                           │
   ├──────────────────────────►│                              │
   │                            │  启动后台线程                │
   │                            │  逐歌单拉取详情（0.8s间隔）  │
   │  GET .../fetch-songs/status│  每完成一个写 DB             │
   ├──────────────────────────►│                              │
   │◄──── {total, fetched, ...} │                              │
   │  (每 2 秒轮询)             │                              │
```

### 4. 数据持久化 (`app/data/store.py`)

SQLite 表结构：

```sql
CREATE TABLE snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,      -- netease / bilibili
    uid         TEXT NOT NULL,      -- 用户 ID
    data_type   TEXT NOT NULL,      -- profile / playlists / records / events / follows / playlist_songs
    data_json   TEXT NOT NULL,      -- JSON 数据
    created_at  TEXT NOT NULL       -- ISO 时间戳 (北京时间)
);
CREATE INDEX idx_snapshot_lookup ON snapshots(platform, uid, data_type, created_at DESC);
```

关键方法：

| 方法 | 说明 |
|------|------|
| `save_snapshot(p, uid, type, data)` | 保存一份快照 |
| `get_latest_snapshot(p, uid, type)` | 取最新快照 |
| `get_snapshots(p, uid, type, since, limit)` | 取历史快照列表 |
| `detect_record_changes(p, uid)` | 全历史听歌记录变化检测 |
| `detect_follow_changes(p, uid)` | 关注/取关检测 |
| `detect_playlist_changes(p, uid)` | 歌单/内容新增检测 |
| `detect_playlist_song_changes(p, uid)` | 歌单内歌曲增减检测 |
| `compare_snapshots(p, uid, type)` | 通用两快照对比 |
| `clean_old_snapshots(days)` | 清理过期快照 |
| `get_all_tracked_users()` | 所有追踪过的用户 |

### 5. 时间线系统 (`app/services/timeline.py`)

`TimelineBuilder.build(platform_uids)` 合并多平台全部事件：

1. **动态**（events）：从快照读取，有精确时间戳
2. **内容发布**（playlists）：B站投稿等，有创建时间（自动识别毫秒/秒格式）
3. **听歌记录**（records）：快照对比推断，5 种 change_type，按时间窗口排序
4. **关注变化**（follows）：快照对比，检测新关注和取关
5. **歌单变化**（playlists 对比）：检测新建/收藏的歌单
6. **歌单歌曲变化**（playlist_songs 对比）：检测歌单内新增/移除的歌曲

排序规则：`timestamp DESC`（最新在前），timestamp=0 的未知时间条目自然排到最后。

时间线 API 支持三种输出格式：
- `?format=json`（默认）：结构化数据，前端渲染
- `?format=text`：纯文本日志
- `?format=markdown`：Markdown 格式

时间格式：`YYYY.MM.DD HH:MM`（包含年份，支持跨年数据正确排序）。

### 6. 自动采集器 (`app/services/scheduler.py`)

`AutoCollector` 后台定时任务：

- 可配置间隔（默认 30 分钟）
- 遍历所有已配置 UID 的平台
- 采集：profile → events → playlists → records → **follows**
- 每次采集保存快照到 SQLite
- 自动生成时间线日志（.txt + .json）到 `logs/` 目录

### 7. 歌单歌曲异步拉取 (`app/services/playlist_fetcher.py`)

`PlaylistSongFetcher` 后台线程服务：

- 前端点击「🎵 拉取歌单详情」触发
- 后台线程逐个调用 `get_content_detail()` 拉取每个歌单的歌曲列表
- 保持 0.8s 请求间隔（与全局配置一致）
- 每完成一个歌单立即写入 DataStore（`data_type='playlist_songs'`）
- 前端每 2 秒轮询 `/api/{p}/fetch-songs/status` 获取进度
- 已完成的歌单立即可见，未完成的显示加载中
- 全部完成后自动刷新时间线

## API 参考

### 聚合数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/all?uid=xxx` | 获取平台全部数据（含 follows 快照保存） |

### 单数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/profile?uid=xxx` | 用户资料 |
| GET | `/api/{platform}/search?keyword=xxx` | 搜索用户 |
| GET | `/api/{platform}/playlists?uid=xxx` | 内容列表（歌单/投稿） |
| GET | `/api/{platform}/playlist/{id}` | 内容详情（歌曲列表） |
| GET | `/api/{platform}/records?uid=xxx` | 听歌排行 |
| GET | `/api/{platform}/events?uid=xxx` | 用户动态 |
| GET | `/api/{platform}/follows?uid=xxx` | 关注列表 |
| GET | `/api/{platform}/followers?uid=xxx` | 粉丝列表 |
| GET | `/api/{platform}/status` | 平台连接状态 |

### 歌单歌曲异步拉取

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/{platform}/fetch-songs/start?uid=xxx` | 启动后台异步拉取 |
| GET | `/api/{platform}/fetch-songs/status?uid=xxx` | 查询拉取进度 `{total, fetched, current, complete}` |

### 时间线 & 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/timeline?uids=netease:xxx,bilibili:yyy&limit=30&format=json` | 多平台统一时间线 |
| GET | `/api/report/overview?platform=..&uid=..` | 用户概览报告 |
| GET | `/api/report/trend?platform=..&uid=..&type=profile` | 趋势报告 |
| GET | `/api/report/cross-platform?uids=netease:xxx,bilibili:yyy` | 跨平台汇总 |
| GET | `/api/history/snapshots?platform=..&uid=..&type=..` | 历史快照 |
| GET | `/api/history/tracked-users` | 所有追踪过的用户 |

### 采集器控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/collector/status` | 采集器状态 |
| POST | `/api/collector/start` | 启动（body: `{targets, interval_minutes}`） |
| POST | `/api/collector/stop` | 停止 |
| POST | `/api/collector/collect` | 手动触发一次采集 |
| GET | `/api/collector/logs` | 采集器日志 |

## 凭证管理

### 添加新 Cookie

1. 浏览器登录目标平台
2. 开发者工具 → Application → Cookies → 复制完整 Cookie 字符串
3. 粘贴到 `credentials/{platform}_cookie.txt`

| 平台 | 关键 Cookie 字段 |
|------|-----------------|
| 网易云 | `MUSIC_U`、`__csrf` |
| B站 | `SESSDATA`、`bili_jct`、`DedeUserID` |

## 配置说明 (`app/config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEFAULT_PLATFORM` | `"netease"` | 默认平台 |
| `DEFAULT_TARGET_UID` | `""` | 默认监控用户（空=使用登录用户） |
| `REQUEST_INTERVAL` | `0.8` | 请求间隔（秒） |
| `REQUEST_TIMEOUT` | `15` | 请求超时（秒） |
| `MAX_RETRIES` | `3` | 失败重试次数 |
| `FLASK_HOST` | `"127.0.0.1"` | 服务器地址 |
| `FLASK_PORT` | `5000` | 服务器端口 |
| `FLASK_DEBUG` | `True` | 调试模式 |

## 反爬措施

### 网易云
- weapi 双层 AES-128-CBC 加密 + RSA 密钥加密（`crypto.py`）
- 完整浏览器请求头伪装（UA / Referer / Origin）
- 请求间隔控制（默认 0.8s）
- CSRF token 自动携带

### B站
- 请求间隔控制（基础 3s，风控时递增等待）
- HTTP 412/429 风控自动退避重试
- 频率限制 -799 自动等待
- 空响应 / null 响应防御性重试
- **快照优先策略**：面板和 API 优先从本地 SQLite 读取，减少对 API 的调用

## 常见问题

### Q: B站数据显示"暂无投稿"
**A**: 可能触发了频率限制。等待几分钟后刷新，或手动触发采集（侧边栏 → ▶ 启动 → 📸 采集）。

### Q: Cookie 过期了怎么办
**A**: 重新登录对应平台，复制新 Cookie 替换 `credentials/` 下的文件，重启服务。

### Q: 如何监控其他用户
**A**: 在侧边栏输入框中输入用户 UID 或昵称，点击 🔍 搜索，从结果中选择目标用户。

### Q: 时间线中听歌记录大量显示"时间未知"或"持续在听"
**A**: 正常现象。需要**至少 2 次采集**才能开始推断时间窗口：
- 第 1 次采集：建立基线，所有记录标记为"首次采集"
- 第 2 次采集开始：对比发现新增歌曲 → 显示精确时间窗口
- 一直存在的歌：显示"⏳ 至少从 XX 开始"

建议启动自动采集器，间隔设为 5-10 分钟以获得更精确的时间推断。

### Q: 如何检测关注变化
**A**: 自动的。采集器每次运行都会保存 follows 快照，时间线自动对比并显示新关注/取关。

### Q: 如何检测歌单里新增了哪些歌
**A**: 点击顶部「🎵 拉取歌单详情」按钮。后台会逐个拉取每个歌单的歌曲列表（保持 0.8s 间隔），进度实时可见。拉取 2 轮后，时间线会显示歌单内新增/移除的歌曲。

### Q: 如何添加新平台
**A**:
1. 在 `app/platforms/` 下创建新目录
2. 实现 `BasePlatformAdapter`（参考 `netease/adapter.py`）
3. 在 `app/platforms/__init__.py` 注册
4. 在 `app/credentials/__init__.py` 添加凭证文件映射
5. 在 `app/templates/index.html` 侧边栏添加 `nav-card`
