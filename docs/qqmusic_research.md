# QQ 音乐 API 研究成果

> 研究日期: 2026-06-26
> 研究目标: 实现 QQ 音乐用户数据采集，重点关注用户关注列表获取

---

## 1. API 架构总览

QQ 音乐存在多套 API 子系统，域名不同、功能不同、认证方式不同：

| 域名 | 用途 | SSL | 认证 |
|------|------|-----|------|
| `c.y.qq.com` | 传统 API（歌单、搜索） | ✅ 正常 | Cookie + g_tk |
| `c6.y.qq.com` | 新版 API（主页、关系） | ✅ 正常 | Cookie + g_tk |
| `u.y.qq.com` | 统一网关（musicu.fcg） | ✅ 正常 | POST JSON + Cookie |
| `u6.y.qq.com` | 签名网关（musics.fcg） | ✅ 正常 | sign 参数 |
| `y.qq.com` | 新版 SPA WebApp | ✅ 正常 | Cookie |
| `i.y.qq.com` | SSR 手机版页面 | ❌ SSLEOFError | 需代理/curl |
| `i2.y.qq.com` | 静态资源/CDN | ❌ SSLEOFError | 需代理/curl |

**重要**: `i.y.qq.com` 和 `i2.y.qq.com` 在 Windows + Python requests 下存在 SSL 握手问题 (`SSLEOFError`)，需通过代理或 curl 访问。

---

## 2. 核心 API 端点

### 2.1 用户主页资料

```
GET https://c6.y.qq.com/rsc/fcgi-bin/fcg_get_profile_homepage.fcg
  ?cid=205360838
  &userid={uid}
  &g_tk=5381
  &format=json
```

| 参数 | 说明 |
|------|------|
| `userid` | 支持 QQ 号和 encrypt_uin |
| `reqfrom=1` | **encrypt_uin 用户不可用此参数**（返回 code 1000） |
| `g_tk=5381` | 未登录默认值 |

响应包含:
- `creator`（昵称 base64、头像、uin=0 表示隐藏、encrypt_uin）
- `tabs.relation`（`follownum`、`fannum` 统计）
- `tabs.orders`（`songnum` 收藏数）
- `tabs.diss`（歌单摘要，title 字段 base64 编码）

**注意**: 昵称字段 `creator.nick` 是 **base64** 编码（UTF-8），非明文。

### 2.2 关注/粉丝列表

```
GET https://c.y.qq.com/splcloud/fcgi-bin/friend_follow_or_listen_list.fcg
  ?utf8=1
  &start=0
  &num=20
  &uin={real_qq_number}
  &format=json
  &g_tk=5381
```

| 参数 | 说明 |
|------|------|
| `uin` | **必须使用真实 QQ 号**，encrypt_uin 无效（超时或 code 1200） |
| `is_listen=1` | 粉丝列表，不加则返回关注列表 |

**已知限制**:
- ❌ 不支持 encrypt_uin（必须真实 QQ 号）
- ❌ 粉丝 API 在大 V 账号上经常超时
- ✅ 非加密用户可正常获取

### 2.3 用户搜索

```
POST https://u.y.qq.com/cgi-bin/musicu.fcg
  {"music.search.SearchCgiService": {
    "module": "music.search.SearchCgiService",
    "method": "DoSearchForQQMusicDesktop",
    "param": {
      "query": "keyword",
      "search_type": 8,   // 8=用户, 3=歌单, 0=综合
      "page_num": 1,
      "num_per_page": 40,
      "grp": 1,
      "remoteplace": "sizer.newclient.user"
    }
  }}
```

**用户搜索 (search_type=8) 限制**:
- 结果极不完整，大多数用户搜索不到
- "Felipy" 搜索结果 = 0
- 歌手搜索 (field=singer) 正常工作
- 需要有效 Cookie 登录态

### 2.4 用户歌单

```
GET https://c.y.qq.com/rsc/fcgi-bin/fcg_user_created_diss
  ?hostUin=0
  &hostuin={uid}
  &sin=0&size=200
  &g_tk=5381&format=json
```

- 支持 encrypt_uin
- 返回用户创建的所有歌单（含私密）
- `hostuin` 字段对于 encrypt_uin 用户返回空

### 2.5 歌单详情

```
GET https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg
  ?type=1
  &disstid={dissid}
  &onlysong=0
  &utf8=1
```

- 返回歌单歌曲列表
- `uin` 字段返回 encrypt_uin（非真实 QQ 号）
- 创建者 `nickname` 为明文

### 2.6 收藏/资产

```
GET https://c.y.qq.com/fav/fcgi-bin/fcg_get_profile_order_asset.fcg
  ?ct=20&cid=205360956
  &userid={uid}
  &reqtype=3
  &sin=0&ein=10
```

- 加密用户返回 code 4000 `"privacy"`（隐私保护）

### 2.7 关注歌手

```
GET https://c.y.qq.com/rsc/fcgi-bin/fcg_order_singer_getlist.fcg
  ?utf8=1&page=1&perpage=20
  &uin={uid}
  &g_tk=5381&format=json
```

- encrypt_uin 用户返回 code 1000 `"not login"`
- 需要较强登录态

### 2.8 手机版 SSR 页面

```
GET https://i.y.qq.com/n2/m/share/profile_v2/index.html?userid={uid}
```

- 支持 encrypt_uin 和 QQ 号
- 内嵌 `__ssrFirstPageData__` JS 变量（双编码 JSON）
- 包含: 资料、歌单列表（DissList）、统计信息
- **不包含**: 关注/粉丝列表数据
- ⚠️ SSL 异常，需代理或 curl

---

## 3. encrypt_uin 机制

### 3.1 是什么

QQ 音乐的 `encrypt_uin` 是一个 **AES 服务端加密** 的用户标识符，格式如:

```
oK6kowEAoK4z7Knioivl7evl7n**
```

特征:
- 32-40 个字符
- 以 `**` 结尾
- 无法客户端解密（密钥在 QQ 音乐服务端）
- 用于隐藏用户的真实 QQ 号

### 3.2 影响范围

| 功能 | encrypt_uin 用户 | 真实 QQ 号用户 |
|------|-----------------|----------------|
| 资料页 SSR | ✅ 正常 | ✅ 正常 |
| fcg API 主页 | ✅ 不加 reqfrom=1 | ✅ 正常 |
| 歌单列表 | ✅ 正常 | ✅ 正常 |
| 歌单详情 | ✅ 返回 encrypt_uin | ✅ 返回 uin |
| 搜索 | ❌ 搜不到 | ✅ 可搜到 |
| 关注/粉丝列表 | ❌ API 超时 | ✅ 正常 |
| 关注歌手列表 | ❌ 返回未登录 | ✅ 正常 |
| 收藏 | ❌ 隐私保护 | ✅ 正常 |
| 关注数/粉丝数 | ✅ fcg API 可查 | ✅ 正常 |

### 3.3 与真实 QQ 号的对应关系

encrypt_uin **不是**真实 QQ 号的简单编码。以下关系已被排除:
- ❌ Base64 编码
- ❌ Hex 编码
- ❌ 位运算/移位
- ❌ 简单 XOR

只能通过以下方式关联:
1. **QQ 音乐服务端** 直接映射
2. **QQ 互联 OAuth** 授权后获得
3. 从歌单详情 API 中获取（但返回的是同一 encrypt_uin）

内部存在一个 `bgmusic.jumpurl` 参数包含类似 `userid=1152921505033474474` 的内部 ID，但无法通过该 ID 获取 QQ 号。

---

## 4. 身份认证 (g_tk)

### 4.1 计算方式

```python
def _calc_g_tk(skey: str) -> int:
    h = 5381
    for c in skey:
        h += (h << 5) + ord(c)
    return h & 0x7FFFFFFF
```

### 4.2 Cookie 依赖

| Cookie 字段 | 用途 |
|-------------|------|
| `uin` | 登录用户 QQ 号 |
| `skey` | 旧版鉴权（Web 用） |
| `p_skey` | 旧版安全鉴权 |
| `qqmusic_key` | 新版 API 鉴权 |
| `qm_keyst` | 新版 API 安全鉴权 |

未登录时 `g_tk=5381` 可访问部分公开 API。

---

## 5. 参考项目

- [jsososo/QQMusicApi](https://github.com/jsososo/QQMusicApi) — Node.js 实现的 QQ 音乐 API
- 提供了 `/follow/users`、`/fans`、`/follow/singers` 等路由
- 与本研究使用相同的 API 端点
- 无特殊处理 encrypt_uin 用户的方法

---

## 6. 已知限制

1. **关注列表**: encrypt_uin 用户无法获取（需要真实 QQ 号）
2. **搜索**: 大部分用户搜不到（搜素引擎索引不完整）
3. **粉丝列表**: 服务端不稳定，大 V 用户超时
4. **SSL**: i.y.qq.com 域名 SSL 异常
5. **请求频率**: 高频请求触发 429/403 限流
6. **历史记录**: 无公开听歌排行 API

---

## 7. 适配器实现总结 (`app/platforms/qqmusic/adapter.py`)

| 方法 | 实现状态 | 数据来源 |
|------|---------|---------|
| `search_user` | ✅ | musicu.fcg search_type=8 |
| `get_profile` | ✅ | SSR 页面 + fcg 关注数 |
| `get_content_lists` | ✅ | SSR 页面 DissList |
| `get_content_detail` | ✅ | cdlist API |
| `get_events` | ✅ | 歌单创建/更新事件 |
| `get_follows` | ⚠️ 仅真实 QQ 号 | friend_follow API |
| `get_followers` | ⚠️ 仅真实 QQ 号 | friend_follow API |
| `get_history` | ❌ 无 API | 空实现 |

### 数据持久化

遵循与其他平台相同的快照机制:
- `profile` → `DataStore.save_snapshot()` → `snapshots` 表
- `playlists` → 同上
- `follows`/`followers` → 同上（encrypt_uin 用户返回空列表）
- `events` → 同上
- 变化检测 → `detect_follow_changes()` / `detect_playlist_changes()` 等
- 时间线 → `TimelineEngine` → `timeline` 表

### 关注数获取

对于 encrypt_uin 用户:
- `profile.extra.follow_count` = fcg API 获取的关注数
- `profile.extra.fan_count` = fcg API 获取的粉丝数
- `get_follows()` 返回 `[]`（不污染快照数据）
- 关注列表需通过 Playwright 登录 + 真实 QQ 号获取
