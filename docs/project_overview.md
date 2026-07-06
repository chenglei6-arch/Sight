# 多平台用户数据监控系统 — 项目总览

> 生成日期: 2026-06-26
> 项目: workshop13-sight — "视奸任何人"

---

## 目录

1. [项目概述](#1-项目概述)
2. [支持的平台](#2-支持的平台)
3. [核心架构](#3-核心架构)
4. [时间推断系统](#4-时间推断系统)
5. [数据持久化](#5-数据持久化)
6. [时间线系统](#6-时间线系统)
7. [自动采集器](#7-自动采集器)
8. [凭证管理](#8-凭证管理)
9. [API 参考](#9-api-参考)
10. [反爬措施](#10-反爬措施)
11. [目录结构](#11-目录结构)
12. [快速启动](#12-快速启动)
13. [常见问题](#13-常见问题)
14. [致谢](#14-致谢)

---

## 1. 项目概述

实时采集网易云音乐、哔哩哔哩、抖音、QQ音乐等多平台用户公开数据，生成统一活动时间线和数据报告。
支持四个平台：网易云音乐、哔哩哔哩、抖音、QQ音乐。

**核心能力**: 不依赖平台提供精确时间戳，而是通过对比不同时间点的数据快照，反向推断操作发生的时间窗口。

---

## 2. 支持的平台

| 平台 | 标识 | 核心功能 | 状态 |
|------|------|----------|------|
| 网易云音乐 | `netease` | 资料/歌单/排行/动态/关注 | ✅ 稳定 |
| 哔哩哔哩 | `bilibili` | 资料/投稿/动态/关注/粉丝 | ✅ 稳定 |
| 抖音 | `douyin` | 资料/作品/关注/粉丝/动态 | ✅ 已完善 |
| QQ音乐 | `qqmusic` | 资料/歌单/动态/关注/粉丝 | ✅ 已完善 |

各平台详细说明：

- [QQ音乐研究](qqmusic_research.md)
- [抖音搜索修复](douyin_search_fix.md)
- [平台适配器详解](platforms.md)

---

## 3. 核心架构

### 3.1 平台适配器模式 (`app/platforms/`)

每个平台实现 `BasePlatformAdapter` 抽象基类：

```python
class BasePlatformAdapter(ABC):
    def get_profile(self, uid) -> Optional[PlatformProfile]   # 用户资料
    def search_user(self, keyword) -> list[dict]               # 搜索用户
    def get_content_lists(self, uid) -> list[ContentItem]      # 内容列表（歌单/投稿/作品）
    def get_content_detail(self, id) -> Optional[dict]         # 内容详情
    def get_history(self, uid, period) -> list[MediaEntry]     # 播放/观看历史
    def get_events(self, uid) -> list[EventItem]               # 用户动态
    def get_follows(self, uid) -> list[dict]                   # 关注列表
    def get_followers(self, uid) -> list[dict]                 # 粉丝列表
    def check_alive(self) -> bool                              # 凭证有效性
    def get_login_user(self) -> Optional[dict]                 # 登录用户
```

**接入新平台**只需：
1. 在 `app/platforms/` 下新建目录
2. 实现 `BasePlatformAdapter` 所有方法
3. 在 `app/platforms/__init__.py` 的 `get_adapter()` 中注册
4. 在 `app/credentials/__init__.py` 的 `PLATFORM_FILES` 中添加凭证文件名
5. 在前端侧边栏添加 `nav-card`

### 3.2 数据流

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
   │                            │  ...                         │
   │                            │  构建 TimelineEntry[]        │
   │                            │  按时间戳降序排列            │
   │◄───────────────────────────┤                              │
```

---

## 4. 时间推断系统

本项目的核心功能：通过对比不同时间点的数据快照，反向推断操作发生的时间窗口。

```
T1 (10:00) 采集快照               T2 (10:30) 采集快照
┌─────────────────┐              ┌──────────────────────┐
│ 听歌排行:        │              │ 听歌排行:              │
│  老歌  50次     │     对比     │  老歌  55次 (+5)      │ → 10:00~10:30 又听了
│                 │     →       │  新歌  10次 (NEW)      │ → 10:00~10:30 开始听
│ 关注: [A]       │              │ 关注: [A, B]           │ → 10:00~10:30 关注了B
│ 粉丝: [C]       │              │ 粉丝: [C, D]           │ → 10:00~10:30 被D关注
│ 歌单《X》: 3首  │              │ 歌单《X》: 4首         │ → 10:00~10:30 加入了1首
└─────────────────┘              └──────────────────────┘
```

### 可检测的变化类型

| 数据类型 | data_type | 检测内容 |
|---------|-----------|---------|
| 听歌排行 | `records` | 新歌出现(`new`)、播放次数增长(`increased`) |
| 关注列表 | `follows` | 新关注(`new_follow`)、取关(`unfollow`) |
| 粉丝列表 | `followers` | 新粉丝(`new_follower`)、掉粉(`lost_follower`) |
| 歌单列表 | `playlists` | 新建/收藏/删除歌单 |
| 歌单歌曲 | `playlist_songs` | 歌单内歌曲新增/移除 |
| 用户资料 | `profile` | 昵称/粉丝数等字段变化 |

### 核心对比策略

- **逐对累积**：比较今天所有连续真实快照，累积每一次变化
- **时间窗口**：只对比「今天 00:00 至今」的快照，不足则向前追溯
- **听歌记录**：play_count 增长产生 `increased` 事件，新歌产生 `new` 事件

---

## 5. 数据持久化

### SQLite 表结构

```sql
-- 快照表
CREATE TABLE snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,      -- netease / bilibili / douyin / qqmusic
    uid         TEXT NOT NULL,
    data_type   TEXT NOT NULL,      -- profile / playlists / records / events / follows / followers / playlist_songs
    data_json   TEXT NOT NULL,      -- JSON 数据
    created_at  TEXT NOT NULL       -- ISO 时间戳
);

-- 时间线表
CREATE TABLE timeline (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    platform         TEXT NOT NULL,
    uid              TEXT NOT NULL,
    event_type       TEXT NOT NULL,
    timestamp        INTEGER DEFAULT 0,
    summary          TEXT DEFAULT '',
    detail           TEXT DEFAULT '',
    dedup_key        TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL
);
```

### 哈希去重优化

`save_snapshot()` 保存前自动对数据计算 SHA256 哈希。若与上一条同类型快照相同 → 只存标记 `{"_marker": true}`，不存完整数据。

```
采集数据 → compute_hash(data)
  ├─ hash == 上次 hash → INSERT {"_marker": true, "_hash": "abc..."}
  └─ hash != 上次 hash → INSERT 完整 data + "_hash" 字段
```

### DataStore 关键方法

| 方法 | 说明 |
|------|------|
| `save_snapshot(p, uid, type, data)` | 保存快照（自动 hash 去重） |
| `get_latest_snapshot(p, uid, type)` | 取最新快照 |
| `get_snapshots(p, uid, type, since, limit)` | 取历史快照 |
| `detect_record_changes(p, uid)` | 听歌记录变化检测 |
| `detect_follow_changes(p, uid)` | 关注变化检测 |
| `detect_follower_changes(p, uid)` | 粉丝变化检测 |
| `detect_playlist_changes(p, uid)` | 歌单变化检测 |
| `detect_playlist_song_changes(p, uid)` | 歌单歌曲变化检测 |
| `insert_timeline_entries(entries)` | 时间线持久化 |
| `compare_snapshots(p, uid, type)` | 通用两快照对比 |

---

## 6. 时间线系统

`TimelineBuilder.build(platform_uids)` 合并多平台全部事件：

1. **动态**（events）：从快照读取，有精确时间戳
2. **内容发布**（playlists）：各平台作品/歌单/视频
3. **听歌记录**（records）：逐对比较快照，仅保留有精确时间窗口的
4. **关注变化**（follows）：逐对比较，新关注/取关全部捕获
5. **粉丝变化**（followers）：逐对比较，新粉丝/掉粉全部捕获
6. **歌单变化**（playlists 对比）：检测新建/收藏/删除
7. **歌单歌曲变化**（playlist_songs 对比）：检测歌单内歌曲增减

支持三种输出格式：`json`（默认）、`text`（纯文本）、`markdown`

---

## 7. 自动采集器

`AutoCollector` 后台定时任务：

- 可配置间隔（默认 30 分钟）
- 遍历所有已配置 UID 的平台
- 采集顺序：profile → events → playlists → records → follows → followers
- 每次采集保存快照到 SQLite
- 自动生成时间线日志（.txt + .json）到 `logs/` 目录

---

## 8. 凭证管理

### Cookie 文件

| 平台 | Cookie 文件 | 关键字段 |
|------|------------|---------|
| 网易云音乐 | `credentials/netease_cookie.txt` | `MUSIC_U`、`__csrf` |
| B站 | `credentials/bilibili_cookie.txt` | `SESSDATA`、`bili_jct`、`DedeUserID` |
| 抖音 | `credentials/douyin_cookie.txt` | `sessionid`、`sid_tt` |
| QQ音乐 | `credentials/y.qq_cookie.txt` | `uin`、`qqmusic_key`、`qm_keyst` |

### 添加新 Cookie

1. 浏览器登录目标平台
2. 开发者工具 → Application → Cookies → 复制完整 Cookie 字符串
3. 粘贴到 `credentials/{platform}_cookie.txt`

---

## 9. API 参考

### 聚合数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/all?uid=xxx` | 全量数据（含快照保存） |

### 单数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{platform}/profile?uid=xxx` | 用户资料 |
| GET | `/api/{platform}/search?keyword=xxx` | 搜索用户 |
| GET | `/api/{platform}/playlists?uid=xxx` | 内容列表 |
| GET | `/api/{platform}/playlist/{id}` | 内容详情 |
| GET | `/api/{platform}/records?uid=xxx` | 听歌/观看排行 |
| GET | `/api/{platform}/events?uid=xxx` | 用户动态 |
| GET | `/api/{platform}/follows?uid=xxx` | 关注列表 |
| GET | `/api/{platform}/followers?uid=xxx` | 粉丝列表 |
| GET | `/api/{platform}/status` | 平台连接状态 |

### 时间线 & 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/timeline?uids=netease:xxx,bilibili:yyy&format=json` | 统一时间线 |
| GET | `/api/report/overview?platform=..&uid=..` | 概览报告 |
| GET | `/api/report/trend?platform=..&uid=..&type=profile` | 趋势报告 |
| GET | `/api/report/cross-platform?uids=..` | 跨平台汇总 |
| GET | `/api/history/snapshots?platform=..&uid=..&type=..` | 历史快照 |

### 采集器控制

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/collector/status` | 采集器状态 |
| POST | `/api/collector/start` | 启动 |
| POST | `/api/collector/stop` | 停止 |
| POST | `/api/collector/collect` | 立即采集一次 |
| GET | `/api/collector/logs` | 采集日志 |

---

## 10. 反爬措施

### 网易云
- weapi 双层 AES-128-CBC 加密 + RSA 密钥加密
- 完整浏览器请求头伪装
- 请求间隔控制（默认 0.8s）

### B站
- 请求间隔控制（基础 3s，风控时递增）
- HTTP 412/429 风控自动退避
- 快照优先策略减少 API 调用

### 抖音
- a_bogus 签名生成（Node.js + 纯 Python 降级）
- sign_token 认证模式
- 请求间隔控制 + 限速保护

### QQ音乐
- g_tk 鉴权计算
- 防盗链 Referer 头
- SSL 降级（i.y.qq.com 需 curl/代理）
- 请求间隔控制（1s + 随机延迟）

---

## 11. 目录结构

```
workshop13-sight/
├── run.py                     # 🚀 启动入口
├── requirements.txt           # Python 依赖
├── .gitignore                 # 根级忽略
│
├── credentials/               # 🔐 凭证目录
│   ├── netease_cookie.txt
│   ├── bilibili_cookie.txt
│   ├── douyin_cookie.txt
│   └── y.qq_cookie.txt
│
├── data/                      # 💾 SQLite 数据库
│   └── snapshots.db
│
├── logs/                      # 📝 自动生成日志
│
├── docx/                      # 📖 项目文档
│   ├── project_overview.md    #   本文档 - 项目总览
│   ├── qqmusic_research.md    #   QQ音乐 API 研究
│   ├── douyin_search_fix.md   #   抖音搜索修复记录
│   └── platforms.md           #   平台适配器详解
│
├── docs/                      # 📖 旧文档目录（迁移至 docx/）
│
├── reference/                 # 📚 参考源码
│
└── app/                       # 📦 应用主包
    ├── __init__.py            # Flask 应用工厂
    ├── config.py              # 全局配置
    ├── platforms/             # 🔌 平台适配器层
    │   ├── __init__.py        #   适配器注册中心
    │   ├── base.py            #   抽象基类 + 数据模型
    │   ├── netease/           #   网易云音乐
    │   ├── bilibili/          #   哔哩哔哩
    │   ├── douyin/            #   抖音
    │   └── qqmusic/           #   QQ音乐
    ├── credentials/           # 🔑 凭证管理器
    ├── data/                  # 💾 数据持久化
    │   └── store.py           #   SQLite 快照存储
    ├── report/                # 📈 报告生成
    ├── services/              # ⚙ 服务层
    │   ├── timeline.py        #   时间线构建器
    │   ├── scheduler.py       #   定时采集器
    │   └── playlist_fetcher.py#   歌单歌曲拉取
    ├── routes/                # 🌐 HTTP 路由
    │   ├── api.py             #   REST API
    │   └── views.py           #   页面路由
    ├── static/                # 🎨 静态资源
    └── templates/             # 📄 模板
```

---

## 12. 快速启动

```bash
pip install -r requirements.txt
python run.py
# 访问 http://127.0.0.1:5000
```

### 启动自动采集

```bash
curl -X POST http://127.0.0.1:5000/api/collector/start
```

采集器默认每 30 分钟自动采集所有平台数据。

---

## 13. 常见问题

### Q: B站数据显示"暂无投稿"？
可能触发了频率限制。等待几分钟后刷新，或手动触发采集。

### Q: Cookie 过期了怎么办？
重新登录对应平台，复制新 Cookie 替换 `credentials/` 下的文件，重启服务。

### Q: 如何监控其他用户？
在侧边栏输入 UID 或昵称，点击 🔍 搜索，从结果中选择目标用户。

### Q: 时间线中听歌记录为什么有些歌不显示？
只有能推断出具体时间窗口的变化才加入时间线。需要播放次数确实增长或在两次采集间新出现的歌才会显示。

### Q: 如何检测关注/粉丝变化？
自动的。采集器每次运行都会保存关注和粉丝列表快照，时间线自动对比并显示变化。

### Q: 抖音搜索返回空结果怎么办？
抖音 Web 搜索有严格反爬限制。使用新 Cookie、直接输入数字 UID、降低请求频率可缓解。

### Q: QQ音乐 "未配置凭证"？
大部分 API 无需登录。Cookie 不存在时降级为未登录模式，部分功能受限。

---

## 14. 致谢

- **[cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider)** — 抖音 API 底层封装（Apache-2.0 许可证）
- **[jsososo/QQMusicApi](https://github.com/jsososo/QQMusicApi)** — QQ 音乐 API 参考实现
