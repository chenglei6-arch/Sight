# 小红书平台说明

> 移植自 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)（PC 签名栈），
> 上游同步约定见 [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md)。

## Cookie 配置（必需）

小红书所有用户数据 API 都需要登录 Cookie，不登录不可用。

### 方式一：面板内粘贴（推荐）

顶栏「账号」→ 选择「小红书」→ 粘贴 Cookie → 保存为主账号。

### 方式二：直接写文件

1. 浏览器登录 https://www.xiaohongshu.com
2. `F12` → Application → Cookies → `xiaohongshu.com`
3. 复制完整 Cookie 字符串，保存到 `credentials/xhs_cookie.txt`：

```
a1=18abcdef...; webId=abc123; web_session=040069b...; ...
```

### 方式三：环境变量

根目录 `.env` 中配置 `XHS_COOKIES="a1=xxx; web_session=xxx; ..."`。

### 验证

访问 `/api/platforms`，确认小红书 `has_credential: true` 且 `is_alive: true`。

## 功能支持

| 功能 | 支持情况 | 说明 |
|------|:---:|------|
| 用户搜索 | ✅ | 按昵称/小红书号搜索 |
| 用户资料 | ✅ | 昵称、粉丝数、IP 属地等 |
| 笔记列表 | ✅ | 含互动数、xsec_token |
| 笔记详情 | ✅ | 面板内点卡片查看 |
| 关注/粉丝 | ❌ | 平台接口需特殊权限，暂不支持 |
| 动态 | ✅ | 基于笔记列表构建 |

对应 REST 接口：`GET /api/xhs/search`、`GET /api/xhs/all?uid=...`、
`GET /api/xhs/playlist/<note_id>`（聚合入口统一走 `/all`）。

## 获取用户 UID

- 面板搜索后从结果复制；
- 或从主页 URL 提取：`https://www.xiaohongshu.com/user/profile/<user_id>`，
  `user_id` 为 24 位十六进制字符串。

## 已知限制与常见问题

- **Cookie 有效期 1~7 天**，报错时会明确提示登录失效（错误直接透传到前端，不伪装空数据）。
- 请求经适配器串行限速（≥1.5s/请求），批量展开时请控制规模。
- 签名算法随上游更新，若搜索/资料突然失败，先检查
  [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md) 是否有新算法需要同步。
- 历史版本曾支持 Creator 模式，本项目从未启用，相关代码已移除。
