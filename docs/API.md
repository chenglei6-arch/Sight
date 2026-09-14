# Sight API 参考

REST / SSE 接口一览。启动方式与 Cookie 配置见[根 README](../README.md)，
平台实现与开发约定见[开发手册](MANUAL.md)。

所有路径前缀 `/api`（默认 `http://127.0.0.1:5001`）。成功响应 `{"code": 200, "data": ...}`；
REST 层是唯一把异常转 JSON 的边界，失败返回 `{"code": -1, "message": 原因}`
（message 带平台前缀/账号标签/风控码）。`{platform}` 取值见开发手册平台矩阵。

## 平台数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/platforms` | 平台列表与凭证状态 |
| GET | `/{platform}/search?keyword=xxx` | 用户搜索 |
| GET | `/{platform}/all?uid=xxx` | 资料/内容/关系聚合，子模块错误收进 `data._errors`；`refresh=1` 绕过 30 分钟快照强制实时 |
| GET | `/{platform}/playlist/<item_id>` | 内容详情 |
| GET | `/{platform}/status` | 连接状态（`alive` + `login_user`） |
| GET | `/timeline?uids=p1:uid1,p2:uid2` | 跨平台统一时间线；`source=live\|stored`、`format=json\|text\|markdown`、`limit`（默认 30） |
| PUT / DELETE | `/timeline/<entry_id>` | 时间线条目编辑 / 删除 |
| POST | `/{platform}/cache/clear` | 清空平台运行期内存缓存（SQLite 快照不删，前端随后以 `refresh=1` 强制实时） |

## 凭证与多账号

主账号固定 id `primary`（`/credentials` 即它的更新入口，历史记录等私有数据接口固定使用）；
附加账号 id 自动生成，用于多账号并发轮询。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/credentials/<platform>` | 凭证状态（Cookie 掩码显示，不回完整值） |
| POST | `/credentials/<platform>` | 更新主账号 Cookie，body `{"cookie": "k=v; k2=v2"}`，保存后重建适配器立即生效 |
| GET | `/accounts/<platform>` | 账号列表（主账号 + 附加账号）与可用池大小 |
| POST | `/accounts/<platform>` | 添加附加账号，body `{"cookie": "...", "name"?}` |
| POST | `/accounts/<platform>/<account_id>` | 更新账号（主/附加通用），body `{"name"?, "cookie"?, "enabled"?}` 字段可选 |
| DELETE | `/accounts/<platform>/<account_id>` | 删除附加账号（主账号不可删，可停用或经 `/credentials` 覆盖） |
| POST | `/accounts/<platform>/<account_id>/test` | 测试账号 Cookie 可用性（真实调用平台接口探测），返回 `ok / warning / error + latency_ms` |

## 关系图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/graph/search?keyword=xxx` | 跨平台搜索生成关系图；`keywords`（JSON 对象）给单平台指定专属搜索词，`platforms` 限定平台，`limit`（3~20），`refresh=1` 跳过 30 分钟搜索缓存 |
| POST | `/graph/expand/enqueue` | 展开任务批量入队，body `{"graph_id"?, "items": [{platform, uid, ...}]}`；同图同 uid 自动去重，返回 `{queued, duplicates, rejected}` |
| GET | `/graph/expand/results?graph_id=xxx` | 增量轮询展开结果，`since_id` 续拉；返回 `results / cursor / pending / paused` |
| POST | `/graph/expand/stop` | 停止排队任务，body `{"graph_id", "platform"?}`（可选限单平台；执行中任务照常完成） |
| POST | `/graph/expand/resume` | 恢复熔断暂停的平台队列，body `{"platform"?}`，为空恢复全部 |
| GET | `/graph/expand/status` | 各平台队列状态（排队/执行/暂停原因/账号占用） |
| POST | `/graph/refresh_nodes` | 批量重拉节点最新资料（修正大V判定），body `{"nodes": [{platform, uid}, ...]}`，单次 ≤300 |
| POST | `/graph/save` | 按名称保存图谱（同名覆盖） |
| GET | `/graph/saved[/<id>]` | 已保存图谱列表 / 完整数据 |
| DELETE | `/graph/saved/<id>` | 删除已保存图谱 |

## QQ音乐扫码登录

依赖可选 Playwright，未安装时明确报错、其余功能不受影响（见[开发手册](MANUAL.md)第 3 节）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/qqmusic/qr-login/start` | 启动扫码会话，body 可选 `{"uid": ...}` |
| GET | `/qqmusic/qr-login/status` | 轮询登录状态 |
| POST | `/qqmusic/qr-login/stop` | 停止扫码会话 |

## 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/logs/recent?after=seq` | 内存日志缓冲尾部，`after` 增量拉取（SSE 的降级轮询） |
| GET | `/logs/stream?after=seq` | SSE 实时日志流 |
