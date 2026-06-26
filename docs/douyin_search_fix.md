# 抖音搜索功能修复记录

## 根因分析

### 参考项目为什么能查？

参考项目（`reference/DouYin_Spider-master`）的工作流程：

```
main.py:
  user_url = 'https://www.douyin.com/user/MS4wLjABAAAA...'   ← 用户提供 sec_uid URL
  DouyinAPI.get_user_info(auth, user_url)
    → user_id = user_url.split("/")[-1] = "MS4wLjABAAAA..."  ← 得到 sec_uid
    → params.add_param("sec_user_id", user_id)                ← API 认得这个格式
    → API 返回用户数据 ✅
```

**参考项目从不处理数字 UID**。它的入口是用户手动粘贴的完整主页链接（含 `sec_uid`），直接传给 API，API 一查就中。

### 本项目为什么查不到？

本项目的工作流程：

```
app.py（自动初始化）:
  get_login_user()
    → get_my_uid() 返回数字 UID: "3402315065201417"
  get_profile("3402315065201417")
    → _resolve_user_info("3402315065201417")
      → get_user_info(auth, "https://www.douyin.com/user/3402315065201417")
        → user_id = "3402315065201417"                         ← 数字 UID
        → params.add_param("sec_user_id", "3402315065201417")   ← API 不认得！
        → API 返回空 ❌
```

**关键差异**：
- 参考项目**只传 sec_uid**（`MS4wLjABAAAA...` 格式），API 用 `sec_user_id` 参数接收
- 本项目**有时传数字 UID**（来自 `get_login_user`），但 API 的 `sec_user_id` 参数只接受 sec_uid 格式
- API 同时支持 `user_id` 参数接受数字 UID，但原代码没有用到

### 修复方案

#### 修复一：get_user_info 参数路由

只改了一处核心代码——`get_user_info` 中根据 UID 类型选择正确的 API 参数：

```python
# 改前：一律用 sec_user_id（数字 UID 时查不到）
params.add_param("sec_user_id", user_id)

# 改后：数字 UID 用 user_id，sec_uid 用 sec_user_id
if user_id.isdigit():
    params.add_param("user_id", user_id)
else:
    params.add_param("sec_user_id", user_id)
```

配合适配器 `_resolve_user_info` 放宽了校验条件（有 uid + 昵称就算查到，不再强求 `sec_uid` 字段）。

#### 修复二：所有 requests 调用添加 timeout

`douyin_api.py` 中所有 `requests.get()` 和 `requests.post()` 调用均缺少 `timeout` 参数。当抖音 API 响应慢时，请求会无限等待，导致整个 `/api/<platform>/all` 端点卡死（前端表现为"搜不到用户"）。

**改动**：给全部 32 处 `requests` 调用添加 `timeout=15`，15 秒无响应则抛出超时异常。

```python
# 改前：
resp = requests.get(url, headers=headers.get(), cookies=auth.cookie, params=params.get(), verify=False)

# 改后：
resp = requests.get(url, headers=headers.get(), cookies=auth.cookie, params=params.get(), verify=False, timeout=15)
```

#### 修复三：减少关注/粉丝默认拉取量

`get_follows` 和 `get_followers` 默认 `limit=500`，每次翻页 20 条，最多 25 次 API 调用。加上每次 2 秒限速，仅关注/粉丝数据就需要 50 秒以上，导致 `/all` 端点极慢。

**改动**：将默认 limit 从 500 降低到 50（最多 3 次 API 调用），大幅缩短首次加载时间。

```python
# 改前：
def get_follows(self, uid: str, limit: int = 500) -> list[dict]:
def get_followers(self, uid: str, limit: int = 500) -> list[dict]:

# 改后：
def get_follows(self, uid: str, limit: int = 50) -> list[dict]:
def get_followers(self, uid: str, limit: int = 50) -> list[dict]:
```

---

## 改动文件

### `app/platforms/douyin/ref_dy_apis/douyin_api.py`

1. **`get_user_info`**（第 377-381 行）— 数字 UID 改用 `user_id` 参数（唯一的核心修复）
2. **所有请求** — 添加 `timeout=15`，防止 API 慢时无限阻塞

### `app/platforms/douyin/adapter.py`

1. **`_resolve_user_info`**（第 178-186 行）— 放宽查询成功判定条件
2. **`get_follows`**（第 645 行）— 默认 limit 从 500 改为 50
3. **`get_followers`**（第 672 行）— 默认 limit 从 500 改为 50

### `app/static/js/app.js`

1. **`onUidChange`** — 抖音输入框拦截明显的搜索关键词（中文、非数字非sec_uid格式的内容），不设为 UID。防止用户打字时把搜索关键词存为 `targetUids['douyin']`，导致后续请求报错。

---

## 验证结果

| 路径 | 修改前 | 修改后 |
|------|--------|--------|
| `search_user('音乐')` | ✅ 正常 | ✅ 正常（20条结果，< 3秒） |
| `get_profile(sec_uid)` | ✅ 正常 | ✅ 正常 |
| `get_profile(数字UID)` | ❌ 返回 None | ✅ 返回正确 Profile |
| `_resolve_user_info(数字UID)` | ❌ 解析失败 | ✅ API 查询成功 |
| `/api/douyin/all?uid=xxx` | ❌ 无限卡死 | ✅ 15 秒超时返回部分数据 |
| 前端搜索用户→点击加载 | ❌ 浏览器转圈无响应 | ✅ 正常加载（慢但不卡死） |

---

## 如果未来又搜不到人

通常是因为 Cookie 过期或 API 超时：

1. **Cookie 过期**：浏览器打开 https://www.douyin.com 并登录 → F12 → Application → Cookies → 筛选 `douyin.com` → 全选复制所有 Cookie → 粘贴覆盖 `credentials/douyin_cookie.txt`
2. **API 超时**：抖音接口偶尔会慢（15 秒超时）。刷新重试即可。
3. **网络问题**：确认电脑能正常访问 douyin.com。
