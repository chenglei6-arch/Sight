# 小红书模块集成文档

## 概述

本项目已集成小红书（XHS）平台用户数据查询功能，基于 [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) 项目。

## 功能支持

### ✅ 已实现功能

| 功能 | PC模式 | Creator模式 | 说明 |
|------|:------:|:-----------:|------|
| 用户资料 | ✅ | ✅ | 昵称、头像、签名、粉丝数等 |
| 用户搜索 | ✅ | ❌ | 通过昵称或小红书号搜索用户 |
| 用户笔记 | ✅ | ✅ | 获取用户发布的所有笔记 |
| 用户动态 | ✅ | ✅ | 基于笔记列表构建 |
| 笔记详情 | ✅ | ❌ | 单条笔记的详细信息 |
| 笔记评论 | ✅ | ❌ | 笔记的评论列表 |
| 笔记搜索 | ✅ | ❌ | 按关键词搜索笔记 |

### ❌ 暂未支持

- 关注列表（API需要特殊权限）
- 粉丝列表（API需要特殊权限）
- 实时推荐流

## 配置方法

### 1. Cookie 获取

小红书需要登录 Cookie 才能访问大部分 API。

#### 方法一：浏览器复制（推荐）

1. 浏览器打开 https://www.xiaohongshu.com 并登录
2. 打开开发者工具（F12）→ Application → Cookies → xiaohongshu.com
3. 复制整个 Cookie 字符串（格式：`a1=xxx; webId=xxx; web_session=xxx; ...`）
4. 粘贴到 `credentials/xhs_cookie.txt`

#### 方法二：.env 配置

在项目根目录创建或编辑 `.env` 文件：

```bash
XHS_COOKIES="a1=xxx; webId=xxx; web_session=xxx; ..."
```

### 2. 验证配置

启动项目后访问 http://127.0.0.1:5000/api/platforms，检查小红书平台状态：

```json
{
  "id": "xhs",
  "name": "小红书",
  "has_credential": true,
  "is_alive": true,
  "login_user": {
    "uid": "5d8c000000000000xxxx",
    "nickname": "你的昵称",
    "avatarUrl": "https://..."
  }
}
```

## API 使用示例

### 搜索用户

```bash
GET /api/xhs/search?keyword=美食
```

响应：
```json
{
  "code": 200,
  "data": [
    {
      "uid": "5d8c...",
      "nickname": "美食博主",
      "avatarUrl": "https://...",
      "signature": "分享美食日常"
    }
  ]
}
```

### 获取用户资料

```bash
GET /api/xhs/profile?uid=5d8c000000000000xxxx
```

响应：
```json
{
  "code": 200,
  "data": {
    "platform": "xhs",
    "uid": "5d8c...",
    "nickname": "用户昵称",
    "avatar_url": "https://...",
    "signature": "个性签名",
    "extra": {
      "red_id": "小红书号",
      "follows": 123,
      "fans": 45678,
      "interaction": 98765,
      "notes_count": 234
    }
  }
}
```

### 获取用户笔记列表

```bash
GET /api/xhs/playlists?uid=5d8c000000000000xxxx
```

响应：
```json
{
  "code": 200,
  "data": [
    {
      "item_id": "6a3b5a0b000000002103ee67",
      "title": "笔记标题",
      "cover_url": "https://...",
      "view_count": 12345,
      "description": "笔记描述",
      "extra": {
        "liked_count": 123,
        "collected_count": 45,
        "comment_count": 67,
        "type": "normal"
      }
    }
  ]
}
```

### 获取全量数据（资料+笔记+动态）

```bash
GET /api/xhs/all?uid=5d8c000000000000xxxx
```

## 前端集成

小红书已添加到前端平台列表，访问 http://127.0.0.1:5000 即可在 Dashboard 中看到。

**平台配置：**
- 颜色：`#ff2442`（小红书品牌红）
- 内容类型：笔记（note）
- UID 格式：24位十六进制字符串

## 架构说明

```
app/platforms/xhs/
├── adapter.py              # 平台适配器（实现 BasePlatformAdapter）
├── ref_xhs_core/          # 核心签名模块（移植自 Spider_XHS）
│   ├── auth.py            # 认证基类
│   ├── cookies.py         # Cookie 管理
│   ├── dsl.py             # DS anchor 获取
│   ├── http.py            # HTTP 客户端
│   ├── params.py          # 请求参数生成
│   ├── runtime.py         # Node.js 运行时桥接
│   └── js/                # JS 签名算法（b1, mns, sign, websectiga）
├── ref_xhs_pc/            # PC 网页版模块
│   ├── auth.py            # PC Auth 工厂
│   ├── http.py            # PC HTTP 客户端
│   ├── params.py          # PC 请求参数
│   └── ...
├── ref_xhs_creator/       # 创作者中心模块
│   ├── auth.py            # Creator Auth 工厂
│   ├── http.py            # Creator HTTP 客户端
│   └── ...
├── ref_apis/              # API 封装
│   ├── xhs_pc_apis.py     # PC 模式 API（用户、笔记、搜索、评论）
│   └── xhs_creator_apis.py # Creator 模式 API（创作者功能）
└── ref_utils/             # 工具模块
    ├── data_util.py       # 数据处理
    └── cookie_util.py     # Cookie 工具
```

## 注意事项

### Cookie 有效期

- 小红书 Cookie 通常在 **1-7天** 后过期
- 出现 `401` / `403` 错误时需要重新获取
- 建议定期（每周）更新 Cookie

### 反爬限制

- 内置了 **1.5秒** 请求间隔防止触发反爬
- 短时间内大量请求可能导致账号被风控
- 建议：
  - 单用户查询间隔 ≥ 2 秒
  - 批量查询使用队列控制并发
  - 避免在高峰期（晚 8-10 点）密集请求

### 数据完整性

- 部分字段（如笔记发布时间）需要额外请求笔记详情
- 关注/粉丝列表因 API 限制暂不可用
- 推荐使用 PC 模式（更稳定）

## 依赖项

本模块新增的依赖（已添加到 `requirements.txt`）：

```txt
curl_cffi==0.15.0    # 模拟 Chrome 浏览器指纹
loguru>=0.7.0        # 日志库
retry>=0.9.2         # 重试机制
```

## 故障排查

### 问题：`No module named 'curl_cffi'`

```bash
pip install curl_cffi==0.15.0
```

### 问题：`401 Unauthorized` / `403 Forbidden`

- Cookie 已过期，需要重新获取
- Cookie 格式错误，确保包含 `a1` 和 `web_session` 字段

### 问题：搜索/API 返回空

- 检查 Cookie 是否有效
- 查看日志中是否有反爬验证码提示
- 尝试降低请求频率

### 问题：`ImportError: cannot import name 'XHSPcAuth'`

- 检查 `ref_xhs_pc/__init__.py` 是否存在
- 尝试重新安装依赖：`pip install -r requirements.txt --force-reinstall`

## 参考资料

- 上游项目：https://github.com/cv-cat/Spider_XHS
- 小红书开发者文档：https://www.xiaohongshu.com/developer
- API 逆向分析参考：`reference/Spider_XHS-main/README.md`

## 更新日志

### 2026-08-30
- ✅ 初始集成小红书平台
- ✅ 实现 PC 和 Creator 双模式支持
- ✅ 用户资料、笔记、搜索功能
- ✅ 前端 Dashboard 集成
