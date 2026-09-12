# 平台实现说明

> 各适配器的完整代码说明见各 `app/platforms/<id>/adapter.py` 模块头部注释；
> 上游仓库与同步约定见 [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md)。
> 本文记录每个平台的实现方式与已知的坑。

## 平台矩阵

| 平台 | 标识 | 资料搜索 | 内容列表 | 历史排行 | 动态 | 关注/粉丝 | 实现方式 |
|------|------|:---:|:---:|:---:|:---:|:---:|------|
| 网易云音乐 | `netease` | ✅ | 歌单 | ✅ | ✅ | ✅ | weapi 自写（`crypto.py` AES 加密） |
| 哔哩哔哩 | `bilibili` | ✅ | 投稿 | ❌ | ✅ | ✅ | web 接口自写 |
| 抖音 | `douyin` | ✅ | 作品 | ❌ | ✅(作品) | ✅ | DouYin_Spider fork 移植（纯 API） |
| QQ音乐 | `qqmusic` | ✅ | 歌单 | ❌ | ✅(歌单) | ✅ | 自写（SSR + fcg 网关） |
| 微博 | `weibo` | ✅ | 微博 | ❌ | ✅(微博) | ✅ | m.weibo.cn API + weibo.com PC ajax |
| 原神 | `genshin` | ✅ | 角色展柜 | ❌ | ❌ | ❌ | enka.network + 米游社绑定接口 |
| 小红书 | `xhs` | ✅ | 笔记 | ❌ | ✅(笔记) | ❌ | Spider_XHS PC 签名栈移植 |

所有平台统一走 `app/platforms/base.py` 的抽象接口：
`get_profile / search_user / get_content_lists / get_content_detail / get_history /
get_events / get_follows / get_followers / refresh_user_info / check_alive / get_login_user`。

## 错误处理约定

**适配器与服务层一律 raise**（`RuntimeError` 带平台前缀与真实原因，如账号标签/风控 code），
不返回空值伪装成功。唯一例外：

- `get_profile` 对"用户不存在"返回 `None`（404 语义）；
- `check_alive` 失败返回 `False`。

REST 层（`app/routes/api.py`）是唯一把异常转成 JSON 错误响应的地方；
`/all` 聚合接口把各子模块错误收进 `_errors` 数组原样展示给前端。

## 各平台要点与坑

### 网易云音乐（netease）

- 请求走 `weapi` 加密（`crypto.py`，pycryptodome AES）。
- 历史排行（听歌周榜/总榜）是本项目"快照对比推断时间"的数据源之一。
- 关注/粉丝列表接口返回 (条目, has_more, 真实总数)，是社交展开的正确实现范式。

### 哔哩哔哩（bilibili）

- `-799` 是频率限制：适配器带**连续风控惩罚计数**（每次触发加大等待间隔）。
- 业务 code 错误（如 -404 用户不存在）直接 `raise RuntimeError` 带 code/msg，不重试。
- `last_api_error` 实例属性保存最近一次业务错误，供上层拼装完整原因。

### 抖音（douyin）

- **上游是 fork 仓库** `chenglei6-arch/DouYin_Spider`（原仓库 `cv-cat/DouYin_Spider` 的
  following 列表 `max_time` 有 bug，fork 已修复——同步时务必从 fork 取，详见
  [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md)）。
- 签名：`douyin_sign.js`（自包含 SM3，PyExecJS 加载）生成 `a_bogus`；
  新签名栈（msToken/dtrait/bd_ticket）在 `ref_builder/`、`ref_utils/`。
- **数字 UID 解析**：参考项目只接受 sec_uid，本项目的 `_resolve_user_info` 对数字 UID
  做双策略解析（先直接查、失败后与登录用户比对），这是面板能从登录态起步的关键。
- Web 端查看他人关注/粉丝列表普遍受限（status_code 2096 / mix_count 有值但列表为空），
  适配器会把这些情况转成明确的 RuntimeError，而不是当成"没有关注任何人"。
- 请求限速 2s/次且持锁串行化（图谱接口会并发调用适配器）。

### QQ音乐（qqmusic）

- `i.y.qq.com` / `i2.y.qq.com` 在 Windows + requests 下有 SSL 握手问题（SSLEOFError），
  `_fetch_html` 遇 SSL 错误自动降级为 curl 子进程（详见 [qqmusic_research.md](qqmusic_research.md)）。
- 用户标识有两种：真实 QQ 号与 `encrypt_uin`（以 `**` 结尾）。加密 uin **无法查询
  关注/粉丝列表**（平台限制，返回空并注明），但总数可从 fcg 接口取得并存入
  `profile.extra.follow_count / fan_count`。
- SSR 数据藏在 `__ssrFirstPageData__` 双重编码 JSON 里，统一由 `_decode_ssr_payload` 解码。
- 扫码登录（`app/services/qqmusic_qr_login.py`）依赖可选的 Playwright，
  未安装时该功能明确报错，其余功能不受影响。

### 微博（weibo）

- 主力是 `m.weibo.cn` 移动端 API；关注/粉丝列表走 `weibo.com` PC ajax
  （m 端 containerid 方案对 PC Cookie 做 wapsso 跨域校验会被拦，参考 WeiboSpider）。
- 登录失效（ok=-100 + passport 重定向）会直接 `raise`，**不会**静默降级 SSR——
  历史上的 SSR 兜底是投机性实现（`window.$WB` 正则），已删除。
- Cookie 中 `SUB` 字段含 uid（正则提取数字部分），用于 get_login_user。

### 原神（genshin）

- 资料来自 enka.network 公开 API；绑定账号通过米游社
  `getUserGameRolesByCookie`（目前仍可用的少数米游社接口之一）。
- **仅支持数字 UID 搜索**，昵称搜索会明确报错（米游社不开放）。
- Enka 404 = 用户不存在（返回 None）；424 = 维护中（上抛）；其余错误上抛。

### 小红书（xhs）

- PC 签名栈移植自 Spider_XHS，含 `ref_xhs_core/`（签名 JS）与 `ref_xhs_pc/`（PC 请求栈）。
- 签名算法随上游演进，突然全线失败时优先检查上游是否有算法更新
  （同步范围与步骤见 [UPSTREAM_SYNC.md](UPSTREAM_SYNC.md)）。
- 关注/粉丝接口需特殊权限，未实现。
- Cookie 配置与已知问题见 [XHS.md](XHS.md)。
