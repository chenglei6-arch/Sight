# 📊 多平台用户数据监控

实时采集 **网易云音乐、哔哩哔哩、抖音、QQ音乐、微博、原神** 多平台用户公开数据，通过快照对比推断活动时间线，生成统一数据报告。

> 项目代号：**workshop13-sight**

---

## 快速开始

```bash
pip install -r requirements.txt
python run.py
# → http://127.0.0.1:5000
```

### 配置 Cookie（可选）

登录目标平台后，从浏览器复制完整 Cookie 字符串，粘贴到对应的凭证文件：

| 平台 | 凭证文件 | 关键 Cookie 字段 |
|------|---------|-----------------|
| 网易云音乐 | `credentials/netease_cookie.txt` | `MUSIC_U`、`__csrf` |
| 哔哩哔哩 | `credentials/bilibili_cookie.txt` | `SESSDATA`、`bili_jct` |
| 抖音 | `credentials/douyin_cookie.txt` | `sessionid`、`sid_tt` |
| QQ音乐 | `credentials/y.qq_cookie.txt` | `uin`、`qqmusic_key` |
| 微博 | `credentials/weibo_cookie.txt` | `SUB`、`SUBP` |
| 原神 | `credentials/genshin_cookie.txt` | 米游社 `ltuid_v2`、`ltoken_v2` |

> 不配置 Cookie 也能启动，部分平台功能受限。

---

## 支持的平台

| 平台 | 适配器 | 资料 | 内容 | 动态 | 关注 | 粉丝 |
|------|--------|:----:|:----:|:----:|:----:|:----:|
| 🎵 网易云音乐 | `netease/` | ✅ | 歌单 | ✅ | ✅ | ✅ |
| 📺 哔哩哔哩 | `bilibili/` | ✅ | 视频 | ✅ | ✅ | ✅ |
| 🎶 抖音 | `douyin/` | ✅ | 作品 | ✅ | ✅ | ✅ |
| 🎵 QQ音乐 | `qqmusic/` | ✅ | 歌单 | ❌ | ✅ | ✅ |
| 💬 微博 | `weibo/` | ✅ | 微博 | ✅ | ✅ | ✅ |
| ⚔️ 原神 | `genshin/` | ✅ | 角色 | ❌¹ | ❌² | ❌² |

> ¹ 原神深渊数据因米游社风控不可用
> ² 游戏内没有关注/粉丝系统

### 原神特殊说明

- **无需 UID**：配置 Cookie 后自动从绑定 API 获取你的游戏账号（QQMusicApi 模式）
- 查询他人需提供目标 UID（如 `271273454`）
- 数据来源：Enka.Network 公开 API（无需额外鉴权）
- 角色展柜需对方在游戏中设为「公开」

---

## 核心架构

### 数据流

```
用户浏览器                     Flask 后端                     外部平台
   │                            │                              │
   │  GET /api/{p}/all?uid=xxx  │                              │
   ├──────────────────────────► │                              │
   │                            │  adapter.get_profile()       │
   │                            │  ├── Enka API (原神)         │
   │                            │  ├── B站 API                 │
   │                            │  ├── weapi 加密 (网易云)     │
   │                            │  └── ...                     │
   │                            │  保存快照到 SQLite            │
   │◄───────────────────────────┤                              │
   │                            │                              │
   │  GET /api/timeline         │                              │
   ├──────────────────────────► │                              │
   │                            │  对比历史快照 → 推断事件      │
   │◄───────────────────────────┤                              │
```

### 快照对比（核心能力）

不依赖平台提供精确时间戳，通过对比不同时间点的数据快照反向推断操作发生的时间窗口：

```
T1 (10:00) 采集               T2 (10:30) 采集
┌─────────────────┐          ┌─────────────────────┐
│ 关注: [A]       │   对比   │ 关注: [A, B]         │ → 10:00~10:30 关注了B
│ 粉丝: [C]       │   →     │ 粉丝: [C, D]         │ → 10:00~10:30 被D关注
│ 歌单《X》: 3首  │          │ 歌单《X》: 4首       │ → 10:00~10:30 加入了1首
└─────────────────┘          └─────────────────────┘
```

可检测的变化：听歌记录增长、新关注/取关、新粉丝/掉粉、内容发布/删除、歌单歌曲增减、资料变更。

### 平台适配器模式

所有平台实现 `BasePlatformAdapter` 抽象基类，接入新平台只需：

1. 创建 `app/platforms/{name}/adapter.py`
2. 实现 `get_profile()` / `search_user()` 等接口
3. 在 `app/platforms/__init__.py` 注册
4. 添加凭证映射 + 前端 nav-card

详细指南见 [docs/workflow.md](docs/workflow.md)。

---

## 目录结构

```
workshop13-sight/
├── run.py                     # 启动入口
├── requirements.txt           # Python 依赖
├── README.md                  # 本文档
├── .gitignore
│
├── app/
│   ├── __init__.py            # Flask 应用工厂
│   ├── config.py              # 全局配置
│   │
│   ├── platforms/             # 🔌 平台适配器
│   │   ├── base.py            #    抽象基类 + 数据模型
│   │   ├── __init__.py        #    适配器注册中心
│   │   ├── netease/           #    网易云（含 weapi 加密）
│   │   ├── bilibili/          #    B站
│   │   ├── douyin/            #    抖音（含 a_bogus 签名）
│   │   ├── qqmusic/           #    QQ音乐（含 encrypt_uin）
│   │   ├── weibo/             #    微博（m.weibo.cn API）
│   │   └── genshin/           #    原神（Enka.Network）
│   │
│   ├── credentials/           # 🔑 凭证管理器
│   ├── data/                  # 💾 SQLite 存储 + 变化检测
│   ├── report/                # 📈 报告生成
│   ├── services/              # ⚙ 时间线 / 采集器 / 歌单拉取
│   ├── routes/                # 🌐 REST API + 页面路由
│   ├── static/                # 🎨 CSS / JS
│   └── templates/             # 📄 HTML 模板
│
├── credentials/               # 🔐 凭证文件（gitignore）
├── data/                      # 💾 SQLite 数据库（gitignore）
├── logs/                      # 📝 日志（gitignore）
└── docs/                      # 📖 详细文档
```

---

## API 参考

### 数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/{p}/all?uid=xxx` | 全量数据（资料+内容+动态+关注+粉丝） |
| GET | `/api/{p}/profile?uid=xxx` | 用户资料 |
| GET | `/api/{p}/search?keyword=xxx` | 搜索用户 |
| GET | `/api/{p}/playlists?uid=xxx` | 内容列表（歌单/投稿/角色） |
| GET | `/api/{p}/playlist/{id}` | 内容详情 |
| GET | `/api/{p}/events?uid=xxx` | 用户动态 |
| GET | `/api/{p}/follows?uid=xxx` | 关注列表 |
| GET | `/api/{p}/followers?uid=xxx` | 粉丝列表 |
| GET | `/api/{p}/records?uid=xxx` | 播放排行（仅网易云） |

### 时间线 & 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/timeline?uids=p1:uid1,p2:uid2` | 多平台时间线 |
| GET | `/api/report/overview?platform=..&uid=..` | 用户概览 |
| GET | `/api/report/trend?platform=..&uid=..&type=..` | 趋势报告 |
| GET | `/api/report/cross-platform?uids=..` | 跨平台汇总 |

### 采集器

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/collector/status` | 状态 |
| POST | `/api/collector/start` | 启动 |
| POST | `/api/collector/stop` | 停止 |
| POST | `/api/collector/collect` | 手动采集一次 |

### 后台异步拉取

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/{p}/fetch-songs/start?uid=xxx` | 启动后台拉取歌单详情 |
| GET | `/api/{p}/fetch-songs/status?uid=xxx` | 拉取进度 |

### 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/platforms` | 列出所有平台 |
| GET | `/api/credentials` | 凭证状态 |
| POST | `/api/credentials/update` | 更新凭证 |
| GET | `/api/history/snapshots` | 历史快照 |
| GET | `/api/history/tracked-users` | 追踪过的用户 |

---

## 配置

参见 `app/config.py`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DEFAULT_PLATFORM` | `netease` | 默认平台 |
| `REQUEST_INTERVAL` | `0.8` | 请求间隔（秒） |
| `REQUEST_TIMEOUT` | `15` | 请求超时（秒） |
| `MAX_RETRIES` | `3` | 重试次数 |
| `FLASK_HOST` | `127.0.0.1` | 监听地址 |
| `FLASK_PORT` | `5000` | 监听端口 |

---

## 技术栈

- **后端**: Python 3, Flask, requests, PyExecJS
- **前端**: 原生 JS + CSS（暗色主题，无框架依赖）
- **存储**: SQLite（`data/snapshots.db`）
- **加密**: AES + RSA（网易云 weapi），SM3（抖音 a_bogus）
- **反爬**: 请求间隔控制、指数退避、多策略降级

---

## 致谢

- [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) — 抖音 API 底层封装参考（Apache-2.0）
- [jsososo/QQMusicApi](https://github.com/jsososo/QQMusicApi) — QQ音乐 API 参考
- [Enka.Network](https://enka.network/) — 原神玩家数据 API
