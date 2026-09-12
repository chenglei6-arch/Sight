# Sight 多平台用户数据监控

Sight 用统一界面采集和对比网易云音乐、哔哩哔哩、抖音、QQ 音乐、微博、原神和小红书的公开用户数据，生成历史快照、变化事件和时间线。

## 快速开始

环境要求：Python 3.10+（当前代码已验证 Python 3.14），Node.js 20+（前端构建及部分签名逻辑）。

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

打开 <http://127.0.0.1:5000>。

## Cookie 配置

所有凭证统一存储在 `credentials/accounts.json`（已被 Git 忽略，切勿提交）。
推荐在面板中配置：图谱页平台状态条 →「配置 Cookie」粘贴即可，主账号与多账号（并发加速）在同一弹窗管理。

也可以手动编辑 `credentials/accounts.json`，每个平台是一个账号数组：

```json
{
  "netease": [
    { "id": "primary", "name": "主账号", "cookie": "k=v; k2=v2", "enabled": true },
    { "id": "acc_xxx", "name": "账号2", "cookie": "k=v", "enabled": true }
  ]
}
```

- `id` 为 `primary` 的是主账号（历史记录等私有数据接口固定使用，不可删除），其余为附加账号
- `enabled: false` 可把账号移出多账号轮询（不删除凭证）
- Cookie 内容在下次请求时生效；增删账号建议走面板（会同步重建账号池）

未配置 Cookie 也能启动，但对应平台功能会受限。小红书 Cookie 可能过期，需要重新获取。

## 常用 API

```text
GET  /api/platforms
GET  /api/{platform}/search?keyword=xxx
GET  /api/{platform}/all?uid=xxx                加 refresh=1 绕过 30 分钟快照强制实时拉取
GET  /api/{platform}/playlist/<item_id>
POST /api/{platform}/cache/clear                清空平台内存缓存（适配器缓存/搜索缓存）
POST /api/{platform}/accounts/<id>/test         测试账号 Cookie 可用性（id=primary 或附加账号 id）
GET  /api/timeline?uids=p1:uid1,p2:uid2
GET  /api/logs/recent                            内存日志缓冲尾部（SSE 降级轮询）
GET  /api/logs/stream                            SSE 实时日志流

# 关系图谱
GET  /api/graph/search?keyword=xxx           跨平台搜索生成关系图
POST /api/graph/expand/enqueue               展开任务批量入队（按平台隔离的后台队列）
GET  /api/graph/expand/results               增量轮询某图谱的展开结果
POST /api/graph/expand/stop                  停止某图谱的排队任务
POST /api/graph/expand/resume                恢复熔断暂停的平台队列
GET  /api/graph/expand/status                各平台队列状态
POST /api/graph/refresh_nodes                批量重新拉取节点信息（重新标记大V）
POST /api/graph/save                         按名称保存当前图谱（同名覆盖）
GET  /api/graph/saved                        已保存图谱列表
GET  /api/graph/saved/<id>                   图谱完整数据（免重新搜索直接渲染）
DELETE /api/graph/saved/<id>                 删除已保存图谱

# 运行日志（前端"终端"面板数据源）
GET  /api/logs/recent?after=seq&limit=n      内存日志缓冲尾部（增量轮询）
GET  /api/logs/stream?after=seq              SSE 实时日志流（stdout/stderr + 数据拉取记录）
GET  /api/graph/expand/status                各平台展开队列状态（排队/执行/熔断/账号数）
```

完整接口和平台限制见 [`docs/`](docs/)；小红书说明见 [`docs/XHS.md`](docs/XHS.md)。

## 前端开发

```bash
cd frontend
npm install
npm run dev       # Vite 开发服务器，默认 5173
npm run build     # 构建到 app/web/，由 Flask 托管
```

## 项目结构

```text
app/platforms/    平台适配器和数据模型
app/routes/       Flask API 路由
app/data/         快照存储和变化检测
app/services/     时间线、社交展开队列、日志中枢等服务
frontend/         Vue 3 + Vite 源码
credentials/      本地 Cookie（忽略）
data/             SQLite 数据库（忽略）
logs/             运行日志（忽略）
docs/             详细说明
```

## 相关文档

- [`docs/project_overview.md`](docs/project_overview.md)：项目架构总览
- [`docs/platforms.md`](docs/platforms.md)：各平台实现方式与坑
- [`docs/workflow.md`](docs/workflow.md)：接入新平台的完整清单
- [`docs/UPSTREAM_SYNC.md`](docs/UPSTREAM_SYNC.md)：移植模块上游仓库与同步约定
- [`docs/XHS.md`](docs/XHS.md)：小红书 Cookie 配置与限制
- [`docs/qqmusic_research.md`](docs/qqmusic_research.md)：QQ音乐 API 研究笔记
