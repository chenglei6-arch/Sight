# 视奸任何人

实时采集网易云音乐、哔哩哔哩等多平台用户公开数据，生成统一活动时间线和数据报告。
目前只支持这两个平台，以后会逐渐推广到其他平台上，比如抖音，qq，微信。
你可以通过这个项目，获取某人的在所有你知道他在各平台的账号的实时动态来达到视奸效果。

## 快速启动

```bash
pip install -r requirements.txt
python run.py
# 访问 http://127.0.0.1:5000
```

## 目录结构

```
workshop13-test/
│
├── run.py                          # 🚀 启动入口
├── requirements.txt                # Python 依赖
├── README.md                       # 本文档
│
├── cookie.txt                      # [旧] 原始 Cookie（可删除，已迁移到 credentials/）
│
├── credentials/                    # 🔐 多平台凭证目录
│   ├── netease_cookie.txt          #   网易云 Cookie
│   └── billbill_cookie.txt         #   B站 Cookie（兼容 bilibili_cookie.txt）
│
├── data/                           # 💾 自动生成
│   └── snapshots.db                #   SQLite 历史快照数据库
│
├── logs/                           # 📝 自动生成
│   ├── timeline_20260619_223000.txt   # 时间线纯文本日志
│   └── timeline_20260619_223000.json  # 时间线结构化数据
│
└── app/                            # 📦 应用主包
    ├── __init__.py                 # Flask 应用工厂
    ├── config.py                   # 全局配置
    │
    ├── platforms/                  # 🔌 平台适配器层
    │   ├── __init__.py             #   适配器注册中心
    │   ├── base.py                 #   抽象基类 + 统一数据模型
    │   ├── netease/                #   网易云音乐适配器
    │   │   ├── __init__.py
    │   │   ├── adapter.py          #     业务逻辑适配器
    │   │   ├── client.py           #     HTTP 客户端 + Cookie + 请求控制
    │   │   └── crypto.py           #     weapi AES+RSA 加密
    │   └── bilibili/               #   哔哩哔哩适配器
    │       ├── __init__.py
    │       └── adapter.py          #     业务逻辑 + HTTP 客户端
    │
    ├── credentials/                # 🔑 凭证管理器
    │   └── __init__.py             #   加载 / 保存 / 迁移 Cookie
    │
    ├── data/                       # 💾 数据持久化
    │   ├── __init__.py
    │   └── store.py                #   SQLite 快照存储 + 变化检测 + 对比
    │
    ├── report/                     # 📈 报告生成
    │   ├── __init__.py
    │   └── generator.py            #   用户概览 / 趋势 / 跨平台报告
    │
    ├── services/                   # ⚙ 服务层
    │   ├── __init__.py
    │   ├── timeline.py             #   多平台统一时间线构建
    │   └── scheduler.py            #   定时自动采集器
    │
    ├── routes/                     # 🌐 HTTP 路由
    │   ├── __init__.py
    │   ├── api.py                  #   REST API 路由
    │   └── views.py                #   页面路由
    │
    ├── static/                     # 🎨 静态资源
    │   ├── css/style.css           #   暗色主题样式
    │   └── js/app.js               #   前端逻辑（侧边栏导航）
    │
    └── templates/                  # 📄 模板
        └── index.html              #   主面板页面
```

## 核心架构

### 1. 平台适配器模式 (`app/platforms/`)

每个平台实现 `BasePlatformAdapter` 抽象基类，统一接口：

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

### 2. 数据流

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
   │  POST /api/collector/collect                               │
   ├──────────────────────────►│                              │
   │                            │  遍历所有平台                │
   │                            │  adapter.get_profile() ─────►│
   │                            │  adapter.get_events() ──────►│
   │                            │  adapter.get_content_lists()─►│
   │                            │  保存快照 + 生成时间线日志   │
   │◄───────────────────────────┤                              │
```

### 3. 数据持久化 (`app/data/store.py`)

SQLite 表结构：

```sql
CREATE TABLE snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,      -- netease / bilibili
    uid         TEXT NOT NULL,      -- 用户 ID
    data_type   TEXT NOT NULL,      -- profile / playlists / records / events
    data_json   TEXT NOT NULL,      -- JSON 数据
    created_at  TEXT NOT NULL       -- ISO 时间戳
);
```

关键方法：

| 方法 | 说明 |
|------|------|
| `save_snapshot(p, uid, type, data)` | 保存一份快照 |
| `get_latest_snapshot(p, uid, type)` | 取最新快照 |
| `get_snapshots(p, uid, type, since, limit)` | 取历史快照列表 |
| `detect_record_changes(p, uid)` | 对比最近两次 records 快照，检测新增/变化的歌曲 |
| `compare_snapshots(p, uid, type)` | 对比最新两次快照，生成变化报告 |

### 4. 时间线系统 (`app/services/timeline.py`)

`TimelineBuilder.build(platform_uids)` 合并多平台数据：

1. **动态**：从 events 快照读取（有精确时间戳）
2. **内容发布**：从 playlists 快照读取（B站投稿等，有创建时间）
3. **听歌记录**：通过 `detect_record_changes` 对比快照
   - 有变化的 → 显示推断时间范围（如 `06.19 10:00~10:30`）
   - 无变化的 → 显示「时间未知」（仅展示 Top 10）

时间线 API 支持三种输出格式：
- `?format=json`（默认）：结构化数据，前端渲染
- `?format=text`：纯文本日志
- `?format=markdown`：Markdown 格式

### 5. 自动采集器 (`app/services/scheduler.py`)

`AutoCollector` 后台定时任务：

- 可配置间隔（默认 30 分钟）
- 遍历所有已配置 UID 的平台
- 采集 profile / events / playlists / records
- 自动保存快照到 SQLite
- 自动生成时间线日志到 `logs/` 目录

## API 参考

### 聚合数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/all?uid=xxx` | 获取平台全部数据（单次请求，避免频率限制） |

### 单数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/profile?uid=xxx` | 用户资料 |
| GET | `/api/{platform}/search?keyword=xxx` | 搜索用户 |
| GET | `/api/{platform}/playlists?uid=xxx` | 内容列表（歌单/投稿） |
| GET | `/api/{platform}/playlist/{id}` | 内容详情 |
| GET | `/api/{platform}/records?uid=xxx` | 听歌排行 |
| GET | `/api/{platform}/events?uid=xxx` | 用户动态 |
| GET | `/api/{platform}/follows?uid=xxx` | 关注列表 |
| GET | `/api/{platform}/followers?uid=xxx` | 粉丝列表 |
| GET | `/api/{platform}/status` | 平台连接状态 |

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
| POST | `/api/collector/start` | 启动采集器（body: `{targets, interval_minutes}`） |
| POST | `/api/collector/stop` | 停止采集器 |
| POST | `/api/collector/collect` | 手动触发一次采集 |
| GET | `/api/collector/logs` | 采集器日志 |

### 兼容路由（旧版，默认 netease）

| 方法 | 路径 |
|------|------|
| GET | `/api/user/profile?uid=xxx` |
| GET | `/api/user/search?keyword=xxx` |
| GET | `/api/user/playlists?uid=xxx` |
| GET | `/api/user/record?uid=xxx` |
| GET | `/api/user/events?uid=xxx` |
| GET | `/api/user/follows?uid=xxx` |
| GET | `/api/user/followeds?uid=xxx` |

## 凭证管理

### 添加新 Cookie

1. 浏览器登录目标平台
2. 用开发者工具复制完整 Cookie 字符串
3. 粘贴到 `credentials/{platform}_cookie.txt`

**网易云 Cookie 关键字段**：`MUSIC_U`、`__csrf`

**B站 Cookie 关键字段**：`SESSDATA`、`bili_jct`、`DedeUserID`

### 文件名兼容

`CredentialManager` 支持别名匹配。例如 B站 同时识别 `billbill_cookie.txt` 和 `bilibili_cookie.txt`。

在 `PLATFORM_ALIASES` 字典中添加更多别名：

```python
PLATFORM_ALIASES = {
    "bilibili": ["billbill_cookie.txt", "bilibili_cookie.txt"],
}
```

## 配置说明 (`app/config.py`)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEFAULT_PLATFORM` | `"netease"` | 默认平台 |
| `DEFAULT_TARGET_UID` | `"5012722824"` | 默认监控用户（Felipy） |
| `REQUEST_INTERVAL` | `0.8` | 请求间隔（秒），网易云 |
| `REQUEST_TIMEOUT` | `15` | 请求超时（秒） |
| `MAX_RETRIES` | `3` | 失败重试次数 |
| `FLASK_HOST` | `"127.0.0.1"` | 服务器地址 |
| `FLASK_PORT` | `5000` | 服务器端口 |
| `FLASK_DEBUG` | `True` | 调试模式（自动重载模板） |

## 反爬措施

### 网易云
- weapi 双层 AES-128-CBC 加密 + RSA 密钥加密
- 完整浏览器请求头伪装
- 请求间隔控制（默认 0.8s）
- CSRF token 自动携带

### B站
- 请求间隔控制（3s，B站限制较严）
- 频率限制 -799 自动等待重试
- **快照优先策略**：面板和 API 优先从本地 SQLite 读取，减少对 B站 API 的调用
- 采集器只在定时任务时才调用 B站 API

## 常见问题

### Q: B站数据显示"暂无投稿"
**A**: 可能是频率限制。等待几分钟后刷新，或手动触发一次采集：点击侧边栏「▶ 启动」采集器，再点「📸 采集」。

### Q: Cookie 过期了怎么办
**A**: 重新登录对应平台，复制新 Cookie 替换 `credentials/` 下的文件，重启服务。

### Q: 如何监控其他用户
**A**: 在侧边栏输入框中输入用户 UID，点击 🔍 搜索，从结果中选择目标用户。

### Q: 如何添加新平台
**A**: 
1. 在 `app/platforms/` 下创建新目录
2. 实现 `BasePlatformAdapter`（参考 `netease/adapter.py`）
3. 在 `app/platforms/__init__.py` 注册
4. 在 `app/credentials/__init__.py` 添加凭证文件映射
5. 在 `app/templates/index.html` 侧边栏添加 `nav-card`

### Q: 时间线中听歌记录显示"时间未知"
**A**: 首次采集时所有记录都是"时间未知"。随着采集器持续运行，新的快照对比会检测到变化，届时显示时间范围。
