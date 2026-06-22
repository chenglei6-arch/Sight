# 视奸任何人

实时采集网易云音乐、哔哩哔哩、抖音、QQ音乐等多平台用户公开数据，生成统一活动时间线和数据报告。
目前支持四个平台：网易云音乐、哔哩哔哩、抖音、QQ音乐。
你可以通过这个项目，获取某人在所有你知道他在各平台的账号的实时动态来达到视奸效果。

## 详细文档

各平台适配器的详细说明、配置方法、API参考和常见问题请参见: [docs/platforms.md](docs/platforms.md)

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
├── .gitignore                      # 根级忽略
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
├── docs/                           # 📖 文档
│   └── platforms.md                #   平台适配器说明
│
├── reference/                      # 📚 参考源码/外部项目（gitignore）
│   └── DouYin_Spider/              #   cv-cat/DouYin_Spider（本地参考副本）
│
└── app/                            # 📦 应用主包
    ├── __init__.py                 # Flask 应用工厂
    ├── config.py                   # 全局配置
    │
    ├── platforms/                  # 🔌 平台适配器层
    │   ├── __init__.py             #   适配器注册中心
    │   ├── base.py                 #   抽象基类 + 统一数据模型
    │   ├── netease/                #   网易云音乐适配器
    │   │   ├── adapter.py          #     业务逻辑
    │   │   ├── client.py           #     HTTP 客户端 + 请求控制
    │   │   └── crypto.py           #     weapi AES+RSA 加密
    │   ├── bilibili/               #   哔哩哔哩适配器
    │   │   └── adapter.py          #     业务逻辑 + HTTP 客户端
    │   ├── douyin/                 #   抖音适配器
    │   │   ├── adapter.py          #     业务逻辑 + 凭证管理
    │   │   └── ref_dy_apis/        #     参考 cv-cat/DouYin_Spider 实现
    │   │       └── douyin_api.py   #       抖音 API 底层封装
    │   └── qqmusic/                #   QQ音乐适配器
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
│ 粉丝: [C]       │          │ 粉丝: [C, D]          │ → 10:00~10:30 被D关注
│ 歌单《X》: 3首  │          │ 歌单《X》: 4首        │ → 10:00~10:30 加入了1首
└─────────────────┘          └─────────────────────┘
```

**可检测的变化类型：**

| 数据类型 | data_type | 检测内容 | 方法 |
|---------|-----------|---------|------|
| 听歌排行 | `records` | 新歌出现(`new`)、播放次数增长(`increased`) | `detect_record_changes()` |
| 关注列表 | `follows` | 新关注(`new_follow`)、取关(`unfollow`) | `detect_follow_changes()` |
| 粉丝列表 | `followers` | 新粉丝(`new_follower`)、掉粉(`lost_follower`) | `detect_follower_changes()` |
| 歌单列表 | `playlists` | 新建/收藏/删除歌单 | `detect_playlist_changes()` |
| 歌单歌曲 | `playlist_songs` | 歌单内歌曲新增/移除 | `detect_playlist_song_changes()` |
| 用户资料 | `profile` | 昵称/粉丝数等字段变化 | `compare_snapshots()` |

**核心对比策略：**

- **逐对累积**：不只看"第一个变化"，而是比较今天所有连续真实快照，累积每一次变化（如同一人关注→取关→再关注，三条事件全部捕获）
- **时间窗口**：只对比「今天 00:00 至今」的快照（自然限制性能），若今天真实快照不足则向前追溯到最近一条
- **听歌记录**：逐对比较连续快照中的每首歌，play_count 增长即产生 `increased` 事件，新出现的歌产生 `new` 事件。无法推断时间的数据（播放次数未变）不加入时间线

### 2. 平台适配器模式 (`app/platforms/`)

每个平台实现 `BasePlatformAdapter` 抽象基类：

| 方法 | 说明 |
|------|------|
| `get_profile(uid)` | 获取用户资料 → `PlatformProfile` |
| `search_user(keyword)` | 搜索用户 |
| `get_content_lists(uid)` | 内容列表（歌单/投稿/作品）→ `list[ContentItem]` |
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
   │                            │  detect_follower_changes()   │
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
    platform    TEXT NOT NULL,      -- netease / bilibili / douyin / qqmusic
    uid         TEXT NOT NULL,      -- 用户 ID
    data_type   TEXT NOT NULL,      -- profile / playlists / records / events / follows / followers / playlist_songs
    data_json   TEXT NOT NULL,      -- JSON 数据；标记快照格式 {"_marker": true, "_hash": "..."}
    created_at  TEXT NOT NULL       -- ISO 时间戳 (北京时间)
);
CREATE INDEX idx_snapshot_lookup ON snapshots(platform, uid, data_type, created_at DESC);
```

**哈希去重优化：**

`save_snapshot()` 保存前自动对数据内容计算 SHA256（排除 `_` 开头的元数据字段）。若与上一条同类型真实快照哈希相同 → 只存标记 `{"_marker": true}` 不存完整数据。变化检测方法通过 `_load_today_real_snapshots()` 自动跳过标记，只对比真实快照。

```
采集数据 → compute_hash(data)
  ├─ hash == 上次 hash → INSERT {"_marker": true, "_hash": "abc..."}
  └─ hash != 上次 hash → INSERT 完整 data + "_hash" 字段
```

关键方法：

| 方法 | 说明 |
|------|------|
| `save_snapshot(p, uid, type, data)` | 保存快照（自动 hash 去重） |
| `get_latest_snapshot(p, uid, type)` | 取最新快照 |
| `get_snapshots(p, uid, type, since, limit)` | 取历史快照列表 |
| `detect_record_changes(p, uid)` | 逐对比较今天 records 快照，累积所有 count 增长 |
| `detect_follow_changes(p, uid)` | 逐对比较今天 follows 快照，累积所有关注/取关 |
| `detect_follower_changes(p, uid)` | 逐对比较今天 followers 快照，累积所有粉丝增减 |
| `detect_playlist_changes(p, uid)` | 逐对比较今天 playlists 快照，累积所有歌单变化 |
| `detect_playlist_song_changes(p, uid)` | 逐对比较今天 playlist_songs 快照，累积所有歌曲增减 |
| `compare_snapshots(p, uid, type)` | 通用两快照对比 |
| `clean_old_snapshots(days)` | 清理过期快照 |
| `get_all_tracked_users()` | 所有追踪过的用户 |

### 5. 时间线系统 (`app/services/timeline.py`)

`TimelineBuilder.build(platform_uids)` 合并多平台全部事件：

1. **动态**（events）：从快照读取，有精确时间戳。抖音跳过此步（作品由内容列表代替，避免重复）
2. **内容发布**（playlists/内容列表）：各平台作品/歌单/视频，有创建时间（自动识别毫秒/秒格式）
3. **听歌记录**（records）：逐对比较今天快照，仅保留有精确时间窗口的（`new`/`increased`）
4. **关注变化**（follows）：逐对比较今天快照，新关注/取关全部捕获
5. **粉丝变化**（followers）：逐对比较今天快照，新粉丝/掉粉全部捕获
6. **歌单变化**（playlists 对比）：逐对比较，检测新建/收藏/删除
7. **歌单歌曲变化**（playlist_songs 对比）：逐对比较，检测歌单内歌曲增减

每条推断事件带时间窗口 `{since, until}`，按 `until` 降序排列。

时间线 API 支持三种输出格式：
- `?format=json`（默认）：结构化数据，前端渲染
- `?format=text`：纯文本日志
- `?format=markdown`：Markdown 格式

### 6. 自动采集器 (`app/services/scheduler.py`)

`AutoCollector` 后台定时任务：

- 可配置间隔（默认 30 分钟）
- 遍历所有已配置 UID 的平台
- 采集：profile → events → playlists → records → follows → **followers**
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
| GET | `/api/{platform}/all?uid=xxx` | 获取平台全部数据（含 follows/followers 快照保存） |

### 单数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/profile?uid=xxx` | 用户资料 |
| GET | `/api/{platform}/search?keyword=xxx` | 搜索用户 |
| GET | `/api/{platform}/playlists?uid=xxx` | 内容列表（歌单/投稿/作品） |
| GET | `/api/{platform}/playlist/{id}` | 内容详情（歌曲列表） |
| GET | `/api/{platform}/records?uid=xxx` | 听歌/观看排行 |
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
| 抖音 | `sessionid`、`sid_tt`、`uid_tt` |
| QQ音乐 | `uin`、`skey`、`p_skey` (可选) |

### 抖音凭证特殊说明

抖音适配器使用了 **sign_token** 认证模式而非标准 Cookie：
1. 参考 `credentials/README.md` 获取 sign_token
2. 将 token 填写到 `credentials/douyin.json` 中
3. 启动服务后访问面板，抖音卡片会显示连接状态

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

### 抖音
- API 接口参考 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 实现端点加密及签名
- sign_token 认证模式，定时刷新
- 请求间隔控制 + 限速保护

## 常见问题

### Q: B站数据显示"暂无投稿"
**A**: 可能触发了频率限制。等待几分钟后刷新，或手动触发采集（侧边栏 → ▶ 启动 → 📸 采集）。

### Q: Cookie 过期了怎么办
**A**: 重新登录对应平台，复制新 Cookie 替换 `credentials/` 下的文件，重启服务。

### Q: 如何监控其他用户
**A**: 在侧边栏输入框中输入用户 UID 或昵称，点击 🔍 搜索，从结果中选择目标用户。

### Q: 时间线中听歌记录为什么有些歌不显示
**A**: 只有能推断出具体时间窗口的变化才加入时间线。需要**播放次数确实增长**或在两次采集间**新出现**的歌才会显示。播放次数一直不变的老歌不再出现，这是设计如此——无法推断你何时听了它。

建议启动自动采集器，间隔设为 5-10 分钟以获得更精确的时间推断。

### Q: 如何检测关注/粉丝变化
**A**: 自动的。采集器每次运行都会保存关注列表和粉丝列表快照，时间线自动对比并显示新关注/取关/新粉丝/掉粉。

### Q: 如何检测歌单里新增了哪些歌
**A**: 点击顶部「🎵 拉取歌单详情」按钮。后台会逐个拉取每个歌单的歌曲列表（保持 0.8s 间隔），进度实时可见。拉取 2 轮后，时间线会显示歌单内新增/移除的歌曲。

### Q: 如何添加新平台
**A**:
1. 在 `app/platforms/` 下创建新目录
2. 实现 `BasePlatformAdapter`（参考 `netease/adapter.py`）
3. 在 `app/platforms/__init__.py` 注册
4. 在 `app/credentials/__init__.py` 添加凭证文件映射
5. 在 `app/templates/index.html` 侧边栏添加 `nav-card`

## 致谢

- **[cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider)** — 抖音 API 底层封装（`app/platforms/douyin/ref_dy_apis/douyin_api.py`）基本照搬自该项目。原项目采用 Apache-2.0 许可证。我们仅在兼容布尔类型 `has_more` 返回值、翻页数量控制和移除部分非必要的 protobuf 处理上做了少量修改，在此对原作者的贡献表示感谢。
