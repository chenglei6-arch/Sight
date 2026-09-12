# 项目总览

> 更新: 2026-09-12（精简重构后）
> 项目: workshop13-sight — 多平台用户数据监控面板

## 1. 项目是什么

统一采集 7 个平台（网易云、B站、抖音、QQ音乐、微博、原神、小红书）用户的公开数据，
落库为带哈希去重的快照，并在此基础上提供：

- **平台视图**：单用户资料 / 内容列表 / 历史排行 / 动态 / 关注粉丝，一次 `/all` 聚合返回；
- **统一时间线**：跨平台活动合并排序；不依赖平台时间戳的部分靠**快照对比推断时间窗口**
  （如"周榜开始听《X》"= 两次快照之间首次出现）；
- **关系图谱**：跨平台关键词搜索归并为图，支持按平台隔离的后台队列批量展开
  关注/粉丝关系、邻居互查、跨平台同人判定、命名持久化；
- **运行终端**：后端日志经内存环形缓冲实时推送到前端（SSE），含队列状态页签。

快速启动见根目录 [README](../README.md)。

## 2. 技术栈与结构

```
后端  Python 3.10+ / Flask（app/）
前端  Vue 3 + Vite + ECharts（frontend/，构建产物输出 app/web/ 由 Flask 托管）
存储  SQLite（data/snapshots.db）
签名  PyExecJS + douyin_sign.js；curl_cffi；protobuf/ecdsa（抖音新签名栈）
```

```
app/
├── routes/api.py            REST 路由（唯一把异常转 JSON 响应的地方）
├── platforms/
│   ├── base.py              适配器抽象接口 + dataclass 模型 + dataclass_to_dict
│   ├── pool.py              多账号适配器池（主账号 + accounts.json 附加账号，租借制轮询）
│   ├── __init__.py          平台工厂注册中心（延迟构造）
│   └── <platform>/          7 个平台适配器（详见 platforms.md）
├── services/
│   ├── timeline.py          统一时间线构建（快照对比推断时间窗口）
│   ├── social_expander.py   社交展开核心（供 REST 与队列复用）
│   ├── expand_queue.py      按平台隔离的展开队列（限速/熔断/断点恢复）
│   ├── log_hub.py           stdout/stderr 镜像 → 环形缓冲 → SSE
│   └── qqmusic_qr_login.py  QQ音乐扫码登录（可选 Playwright）
├── data/store.py            SQLite 快照/时间线/图谱/展开任务持久化
├── credentials/             凭证管理（accounts.json 统一存储：主账号 primary + 附加账号）
└── web/                     前端构建产物（勿手改，npm run build 生成）

frontend/src/
├── store.js                 全局状态与数据加载编排
├── platforms.js             平台元信息与渲染配置（字段与后端严格对应）
├── components/View*.vue     平台视图 / 时间线 / 关系图谱
└── components/TerminalPanel.vue  运行终端（日志 + 队列）
```

## 3. 数据流

1. **采集**：`GET /api/<platform>/all?uid=...` → 适配器实时拉取 → 写快照
   （内容哈希与上次相同则只存标记，防表膨胀；30 分钟内的新鲜快照直接复用）。
2. **推断**：`GET /api/timeline` → TimelineBuilder 读取各平台快照，
   对 records/follows/followers/playlists 做逐对集合 diff，生成带时间窗口的条目并持久化
   （`dedup_key` 幂等）。
3. **展开**：`POST /api/graph/expand/enqueue` → 按平台队列（账号池租借、间隔限速、
   连续失败 5 次熔断）→ 结果落库 → 前端增量轮询 `/api/graph/expand/results` 合并进图。
4. **观测**：所有 print 输出经 log_hub 镜像到前端终端；请求级日志另写 `logs/fetch_*.log`。

## 4. 关键约定

- **错误上抛**：适配器与服务层失败必须 raise（带平台前缀/账号标签/风控码），
  不返回空值伪装成功；唯一转 JSON 的边界在 REST 层。前端对失败如实展示。
- **上游同步**：移植模块的上游仓库、fork 使用与同步范围见
  [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md)（抖音必须用 fork）。
- **前端字段契约**：`frontend/src/platforms.js` 与后端 adapter 返回字段严格对应，改一边要同步另一边。
- **tmp/ 与 logs/ 均为运行时/调试产物**，已 gitignore，可随时清空。

## 5. 详细文档

| 文档 | 内容 |
|------|------|
| [platforms.md](platforms.md) | 各平台实现方式与坑 |
| [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md) | 移植模块上游仓库与同步约定 |
| [workflow.md](workflow.md) | 接入新平台的完整清单 |
| [qqmusic_research.md](qqmusic_research.md) | QQ音乐 API 研究笔记 |
| [XHS.md](XHS.md) | 小红书 Cookie 配置与限制 |
