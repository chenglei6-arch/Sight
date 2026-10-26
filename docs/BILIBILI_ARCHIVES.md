# Aicu / Danmakus 调研与接入

核查日期：2026-10-26。结论：可以把两站当前能访问的查询接口接入 Sight；不能据此获得其完整历史数据库，也不能保证第三方接口长期稳定。

## 开源情况

| 对象 | 核查结果 | 对 Sight 的意义 |
| --- | --- | --- |
| [Aicu](https://www.aicu.cc/) | 本次未找到能够确认属于该站的官方完整源码及开源许可证。不能把搜索到的其他同名 AICU 项目当成它的源码。 | 独立实现 HTTP 客户端，使用当前可访问的查询接口。 |
| [Danmakus 网站仓库](https://github.com/81f9db2ec2/danmakus.com) | 仓库只有反馈说明，不是网站服务端和历史数据库。 | 无法从这个仓库自建完整历史查询站。 |
| [danmakus-client](https://github.com/81f9db2ec2/danmakus-client) | 桌面客户端、采集内核源码公开，采用 Vue / TypeScript / Tauri；采集内核使用 B 站直播连接。 | 可以研究实时采集架构，和历史查询服务是两回事。 |
| [danmakus-core/package.json](https://github.com/81f9db2ec2/danmakus-client/blob/main/danmakus-core/package.json) | 声明 `license: MIT`；本次下载核查的整个仓库未发现独立 LICENSE 文件。 | 应把“源码公开”“内核包声明 MIT”和“整个站点已获开源授权”分别描述。本次接入未复制其实现。 |

[内核 README](https://github.com/81f9db2ec2/danmakus-client/blob/main/danmakus-core/README.md)说明了直播间连接、消息上传、账号同步，以及作为库或 CLI 运行的方法。它不是独立的历史数据库服务，且现有 CLI 使用账号 Token。自行实时采集只能积累启动后的数据，无法补回此前历史。

## 实际接口验证

使用小样本单页请求验证，未导入真实用户内容到仓库或本地数据库：

| 数据 | 上游请求 | 实测响应及映射 |
| --- | --- | --- |
| Aicu 评论 | `GET https://api.aicu.cc/api/v3/search/getreply?uid=1&pn=1&ps=1&mode=0` | `code=0`；`data.cursor`、`data.replies`；`rpid / message / time / dyn` 映射成统一事件。 |
| Aicu 视频弹幕 | `GET https://api.aicu.cc/api/v3/search/getvideodm?uid=1&pn=1&ps=1` | `code=0`；`data.videodmlist`；`id / content / ctime / oid / cid / progress`。 |
| Danmakus 直播弹幕及互动 | `GET https://api.danmakus.com/api/v2/user?uId=1&pageNum=0&pageSize=1&target=-1&useEmoji=true` | `code=200`；`data.data.records[]` 中的 `channel / live / danmakus`；分页元数据在外层 `data`。上游页码从 0 开始，已转换为 Sight 的 1 起始页码。 |

Danmakus 的 `api.danmakus.com` 域名可在其[官方客户端后端配置](https://github.com/81f9db2ec2/danmakus-client/blob/main/danmakus-core/src/core/BackendApiFallback.ts)中确认。这些查询路由是网站接口，不是已确认有稳定性承诺的开放 API；本次验证成功不代表所有 UID、所有历史或所有网络环境均能查询。

无效的 `uid=0` 在 Aicu 返回业务错误 `code=-403`，在 Danmakus v2 返回 `code=400`，所以接入前先校验正整数 UID。首页 HTML 可访问，但前端 JS 资源在本次环境返回 HTTP 403；没有绕过挑战或复制网站脚本。实际客户端以查询接口的 JSON 响应为依据。

## 已加入 Sight 的功能

进入哔哩哔哩页面并设置目标 UID，在页面下方的“评论与弹幕存档”选择来源，点击“查询存档”。即使 B 站资料模块失败，设置了 UID 后仍可独立查询第三方存档。

- Aicu 评论、Aicu 视频弹幕、Danmakus 直播弹幕及互动三种查询。
- 一次请求一页；默认 20、最大 50 条分页单位。Danmakus 上游按直播场次分页，一场可能包含多条消息；展示数量与上游总场次分别标明。
- Danmakus 的 `pageNum` 从 0 开始；客户端继续使用 `page=1`，服务端转换为 `pageNum=page-1`。否则会漏掉首页，记录不足一页时还会报“无效的页码”。
- 统一为 `EventItem`：毫秒时间戳、来源、原站链接、稳定 ID 和页内去重。非文本互动保留上游类型编号，不推断为观看、发言或其他具体行为。
- 同源串行、至少 2 秒请求间隔，5 分钟内存缓存、最多 128 个查询页；并发相同查询只请求一次上游。
- HTTP 429 / 已知业务限流进入同源冷却；不自动重试、换 IP 或切换域名绕过限制。
- HTTP、业务错误、非 JSON、结构变化明确报错，不伪装成“没有记录”。
- 每页最多展示最新 500 个事件，超限明确提示前往原站；原始视频评论有可验证的视频 ID 时链接到视频，其余链接到来源站。

第三方请求使用独立 Session，不读取或发送 `credentials/accounts.json` 的 B 站 Cookie。目前这些存档在独立面板按需展示，未接入自动监控、图谱扩展、跨平台身份合并或持久化时间线。这样无需改变现有 B 站 `/all` 的资料、动态和快照契约。

后端：`app/services/bilibili_archives.py`；REST 入口：`app/routes/api.py`；前端：`frontend/src/components/BilibiliArchives.tsx`。本次实现没有新增 Python / npm 依赖。

## 本地接口

```text
GET /api/bilibili/archives?uid=123&source=aicu_reply&page=1&page_size=20
GET /api/bilibili/archives?uid=123&source=aicu_danmaku&page=1&page_size=20
GET /api/bilibili/archives?uid=123&source=danmakus&page=1&page_size=20
```

参数错误返回 HTTP 400；上游失败返回 HTTP 502。成功响应沿用 `{"code":200,"data":...}`，包含 `events / source_name / source_url / uid / page / page_size / total / total_unit / has_more / truncated / fetched_at / cached / notice`。`total=-1` 表示上游未提供总数。页码范围 1~1000；内存缓存不提供强制绕过参数，重启服务后清空。

## 验证

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run test
npm run build
npx playwright test tests/e2e/archives.spec.ts
```

自动化测试使用合成记录和模拟上游，覆盖字段转换、秒/毫秒时间、分页单位、错误状态、限流冷却、缓存并发、UID 校验、来源切换和过期响应取消。真实联网验证仅是小样本烟雾测试，不是全量覆盖或完整性保证。

复测结果：14 项后端测试、28 项前端单元测试、14 项浏览器测试全部通过；TypeScript 检查和生产构建通过。已检查桌面和 390px 手机宽度截图，新增面板无横向溢出。

2026-10-26 扩大真实联网测试范围后，发现并修复 Danmakus 从 0 起始的页码转换问题：之前的小样本请求能成功，但实际跳过了第一页，默认每页 20 的查询在记录不足一页时会失败。新增回归测试锁定首页及第二页的转换关系。

修复后，每种来源分别验证 `uid=1` 的首页/第二页（每页 2 条）、`uid=2` 的首页（每页 1 条），以及页面默认的每页 20 条查询，共 12 组真实请求全部返回 HTTP 200；逐组复查缓存、字段映射、排序及 ID 去重，并确认前后两页没有重复事件。4 组非法参数校验及首页、图标、构建后的 JS/CSS 资源检查也全部通过，共 20 组检查。没有为这些测试导入或提交用户内容。另用无存档的极大 UID 验证边界行为：Danmakus 返回成功空结果（未提供总数，映射为 -1），Aicu 的评论/视频弹幕请求分别出现连接失败和超时，均作为明确的上游错误返回，不能把这种失败当作“没有活动”。合成数据测试另行覆盖成功空结果与结构异常的区别。

若之后需要独立于第三方站点，另行接入实时采集内核与自己的存储；历史数据仍需要站方提供导出或数据服务。公开可访问和 `robots.txt` 的抓取规则也不等于取得数据库复制或再分发许可。
