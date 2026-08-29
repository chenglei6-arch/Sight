# 小红书模块快速开始

## 🚀 5分钟上手

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

**⚠️ Python 版本要求:** 3.10 - 3.12（Python 3.14 与 curl_cffi 存在兼容性问题）

### 2. 配置 Cookie

#### 方式一：浏览器复制（推荐）

1. 登录 https://www.xiaohongshu.com
2. 按 `F12` 打开开发者工具
3. 切换到 **Application** → **Cookies** → `xiaohongshu.com`
4. 复制整个 Cookie 字符串（右键 → Show Requests Cookies）
5. 粘贴到 `credentials/xhs_cookie.txt`

**Cookie 示例格式:**
```
a1=18abcdef1234567890abcdef; webId=abc123; web_session=040069b1234567890abcdef; ...
```

#### 方式二：环境变量

编辑项目根目录的 `.env` 文件：

```bash
XHS_COOKIES="a1=xxx; webId=xxx; web_session=xxx; ..."
```

### 3. 启动服务

```bash
python run.py
```

访问 http://127.0.0.1:5000

### 4. 验证集成

在 Dashboard 中应该能看到小红书平台（红色图标 📕），状态为"在线"。

## 📌 核心功能

| 功能 | API Endpoint | 示例 |
|------|-------------|------|
| 搜索用户 | `GET /api/xhs/search?keyword=美食` | 按昵称搜索用户 |
| 用户资料 | `GET /api/xhs/profile?uid=5d8c...` | 获取用户信息 |
| 用户笔记 | `GET /api/xhs/playlists?uid=5d8c...` | 获取笔记列表 |
| 用户动态 | `GET /api/xhs/events?uid=5d8c...` | 获取动态事件 |
| 全量数据 | `GET /api/xhs/all?uid=5d8c...` | 一次获取所有数据 |

## 🔍 获取用户 UID

### 方法一：通过搜索

1. Dashboard → 选择"小红书"平台
2. 搜索框输入昵称
3. 从结果中复制 `user_id`

### 方法二：从用户主页 URL

用户主页 URL 格式：
```
https://www.xiaohongshu.com/user/profile/5d8c000000000000xxxx
                                        └─────┬─────┘
                                           user_id (24位十六进制)
```

## 🛠️ 常见问题

### Q: Cookie 多久失效？
A: 通常 **1-7天**，出现 401/403 错误时需要重新获取。

### Q: 能否不登录使用？
A: 不行。小红书所有用户数据 API 都需要登录 Cookie。

### Q: 支持批量查询吗？
A: 支持，但请控制频率（建议间隔 ≥ 2秒），避免触发反爬。

### Q: 为什么关注/粉丝列表为空？
A: 小红书的关注/粉丝 API 需要特殊权限，当前版本暂不支持。

### Q: Python 3.14 报错 "the first argument must be callable"
A: 使用 Python 3.10-3.12。详见 [XHS_INTEGRATION.md](./XHS_INTEGRATION.md#故障排查)。

## 📚 完整文档

- [集成文档](./XHS_INTEGRATION.md) - 架构说明、API 参考、故障排查
- [主 README](../README.md) - 项目整体介绍

## 🎯 下一步

- 配置其他平台（网易云、B站、抖音等）
- 启用定时采集（数据快照 → 时间线推断）
- 查看活动时间线分析

---

**项目:** workshop13-sight | **文档版本:** 2026-08-30
