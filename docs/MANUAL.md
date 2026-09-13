# Sight 开发手册

平台实现、错误约定、接入新平台清单与上游同步。
快速开始、架构图与第三方仓库声明见[根 README](../README.md)。

## 1. 平台矩阵

| 平台 | 标识 | 搜索 | 内容 | 历史 | 动态 | 关注/粉丝 | 实现方式 | 上游 |
|------|------|:---:|:---:|:---:|:---:|:---:|------|------|
| 网易云音乐 | `netease` | ✅ | 歌单 | ✅ | ✅ | ✅ | weapi 自写（`crypto.py` AES） | 无 |
| 哔哩哔哩 | `bilibili` | ✅ | 投稿 | ❌ | ✅ | ✅ | web 接口自写 | 无 |
| 抖音 | `douyin` | ✅ | 作品 | ❌ | ✅ | ✅ | fork 移植（纯 API） | 原仓库 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) **有 bug 不可用**；修复版：作者 fork [chenglei6-arch/DouYin_Spider](https://github.com/chenglei6-arch/DouYin_Spider) |
| QQ音乐 | `qqmusic` | ✅ | 歌单 | ❌ | ✅ | ✅ | 自写（SSR + fcg 网关） | [jsososo/QQMusicApi](https://github.com/jsososo/QQMusicApi)（仅接口文档） |
| 微博 | `weibo` | ✅ | 微博 | ❌ | ✅ | ✅ | m.weibo.cn + PC ajax | [nghuyong/WeiboSpider](https://github.com/nghuyong/WeiboSpider)（请求构造参考） |
| 原神 | `genshin` | ✅ | 角色展柜 | ❌ | ❌ | ❌ | enka.network + 米游社绑定 | [Womsxd/YuanShen_User_Info](https://github.com/Womsxd/YuanShen_User_Info)（设计参考） |
| 小红书 | `xhs` | ✅ | 笔记 | ❌ | ✅ | ❌ | PC 签名栈移植 | [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS) |

所有平台统一实现 `base.py` 接口：`get_profile / search_user / get_content_lists /
get_content_detail / get_history / get_events / get_follows / get_followers /
refresh_user_info / check_alive / get_login_user`。

## 2. 错误处理约定

- 适配器与服务层失败一律 `raise RuntimeError`（带平台前缀、账号标签、风控 code），
  禁止 `except: return []/None/{}` 把失败伪装成空数据。
- 例外仅两个：`get_profile` 对"用户不存在"返回 `None`；`check_alive` 失败返回 `False`。
- REST 层（`routes/api.py`）是唯一把异常转 JSON 的边界；`/all` 把子模块错误收进
  `_errors` 数组原样给前端。

## 3. 各平台要点与坑

### 网易云音乐（netease）

- weapi 加密（`crypto.py`，pycryptodome AES）。
- 听歌周榜/总榜是"快照对比推断时间"的数据源之一。
- 关注/粉丝返回 `(条目, has_more, 真实总数)`，是社交展开的正确实现范式。

### 哔哩哔哩（bilibili）

- `-799` 是频率限制：适配器带连续风控惩罚计数，每次触发加大等待间隔。
- 业务 code 错误（如 -404 用户不存在）直接 `raise`，不重试；
  `last_api_error` 实例属性保存最近一次业务错误供上层拼装原因。

### 抖音（douyin）

- **上游 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 有关键 bug，不可直接使用或同步**：
  关注列表接口 `max_time=0` 走错分支，只回 `mix_count` 不回列表，会被误判为"平台限制"。
  修复版是作者 fork [chenglei6-arch/DouYin_Spider](https://github.com/chenglei6-arch/DouYin_Spider)（见[上游同步](#5-上游同步)）。
- 签名：`douyin_sign.js`（PyExecJS）生成 `a_bogus`；新签名栈
  （msToken/dtrait/bd_ticket）在 `ref_builder/`、`ref_utils/`。
- 数字 UID 双策略解析（先直查、失败后与登录用户比对）——上游只支持 sec_uid，
  这是面板能从登录态起步的关键。
- 他人关注/粉丝普遍受限（status_code 2096 / mix_count 有值但列表空），
  转成明确 RuntimeError，不当成"没有关注任何人"。
- 限速 2s/次且持锁串行化（图谱接口会并发调用适配器）。

### QQ音乐（qqmusic）

- 域名两套行为：`c/c6/u.y.qq.com`（fcg 接口与统一网关，SSL 正常）；
  `i/i2.y.qq.com`（SSR 页面，Windows + requests 必现 SSLEOFError）
  → `_fetch_html` 遇 SSL 错误自动降级 curl 子进程。
- 用户标识两种：真实 QQ 号与 `encrypt_uin`（`**` 结尾）。加密 uin 查不了
  关注/粉丝列表（平台限制，返回空并注明），总数从 fcg 主页接口取，
  存入 `profile.extra.follow_count / fan_count`。
- SSR 数据藏在 `__ssrFirstPageData__` 双重编码 JSON，`_decode_ssr_payload` 统一解码；
  昵称字段是 base64（UTF-8）。
- g_tk 鉴权（未登录 = 5381）。扫码登录（`services/qqmusic_qr_login.py`）
  依赖可选 Playwright，未安装时明确报错，其余功能不受影响。

### 微博（weibo）

- 主力 `m.weibo.cn` 移动端 API；关注/粉丝走 `weibo.com` PC ajax
  （m 端 containerid 方案对 PC Cookie 做 wapsso 跨域校验会被拦）。
- 登录失效（ok=-100 + passport 重定向）直接 `raise`，不做 SSR 兜底（投机性实现已删）。
- Cookie 的 `SUB` 字段含 uid（正则提取数字部分），用于 `get_login_user`。

### 原神（genshin）

- 资料来自 enka.network 公开 API；绑定账号走米游社 `getUserGameRolesByCookie`。
- 仅支持数字 UID 搜索，昵称搜索明确报错（米游社不开放）。
- Enka 404 = 用户不存在（返回 None）；424 = 维护中（上抛）；其余错误上抛。

### 小红书（xhs）

- Cookie 有效期仅 1~7 天，失效直接报错不伪装；请求串行限速 ≥1.5s/次。
- 签名算法随上游演进，全线失败时先查上游是否有算法更新（见[上游同步](#5-上游同步)）。
- 关注/粉丝接口需特殊权限，未实现。
- UID 从主页 URL 提取：`https://www.xiaohongshu.com/user/profile/<24位十六进制>`。
- Cookie 配置与各平台相同（面板粘贴或 `accounts.json`），无特殊步骤。

## 4. 接入新平台

改动位置（共 6 处）：

```
① app/platforms/<id>/adapter.py    新建适配器（实现 base.py 抽象接口）
② app/platforms/__init__.py        _factory_for() 加分支 + known_platform_ids() 加 id
③ app/credentials/__init__.py      PLATFORMS 元组加平台 id
④ frontend/src/platforms.js        PLATFORMS 数组加渲染配置（侧边栏/视图全由它驱动）
⑤ app/services/timeline.py         PLATFORM_NAME_MAP / CONTENT_TYPE_MAP 加映射
⑥ docs/MANUAL.md                   平台矩阵与要点补一行
```

可选：`expand_queue.py` 的 `PLATFORM_MIN_INTERVALS` 加队列级最小间隔
（默认 0.3s，重平台如抖音 2.0s）。

适配器约定：

- 必须实现 `get_profile` 与 `search_user`；其余方法按平台能力选实现，
  **不支持的不要覆盖**——base 默认返回空数据。
- 错误一律 `raise`（见第 2 节）。
- `get_follows / get_followers` 返回三元组 `(条目, has_more, 真实总数或 -1)`，
  支持 `skip` 参数做增量续拉（社交展开队列依赖）。
- 限速持锁串行化（图谱会多线程并发调用，参考 `douyin/adapter.py` 的 `_rl_lock`）。
- 字段契约：列表条目用 `uid / nickname / avatarUrl / signature / fans /
  is_verified / sec_uid(可选)`；内容项用 `ContentItem`，资料用 `PlatformProfile`。

验证（`python run.py` 后）：

```bash
curl "http://127.0.0.1:5001/api/xxx/search?keyword=test"
curl "http://127.0.0.1:5001/api/xxx/all?uid=<真实uid>"
```

- [ ] 搜索/资料正确；故意断 Cookie 时 `_errors` 有明确原因
- [ ] 关注/粉丝展开与 skip 增量续拉正确
- [ ] 时间线条目中文文案正确；前端卡片/详情弹窗/外链正确

若实现来自开源项目：把上游仓库、本地副本位置、同步范围与本地修复写进下一节。

## 5. 上游同步

移植代码映射（`reference/` 为本地参考副本，git 忽略；逐文件 diff 手工移植，
含导入路径适配，勿整目录覆盖）：

| 平台 | 上游与本地副本 | 同步范围 |
|------|------|------|
| douyin | ⚠️ 原仓库 [cv-cat/DouYin_Spider](https://github.com/cv-cat/DouYin_Spider) 有 bug，**勿从其同步**；修复版 = 作者 fork [chenglei6-arch/DouYin_Spider](https://github.com/chenglei6-arch/DouYin_Spider)，副本 `reference/DouYin_Spider` | `builder/` → `ref_builder/`、`dy_apis/` → `ref_dy_apis/`、`utils/` → `ref_utils/`、`static/` → `ref_static/` |
| xhs | [cv-cat/Spider_XHS](https://github.com/cv-cat/Spider_XHS)，副本 `reference/Spider_XHS-main` | `xhs_utils/xhs_core/` → `ref_xhs_core/`、`xhs_utils/xhs_pc/` → `ref_xhs_pc/`、`apis/xhs_pc_apis.py` → `ref_apis/xhs_pc_apis.py`（creator 模块不同步） |

**抖音必须从 fork 同步，原仓库有问题**：cv-cat 原仓库 `get_user_following_list`
的 `max_time=0` bug 会导致关注列表恒为空；作者 fork 提交 `37ec119` 修复
（max_time 需传当前秒级时间戳，source_type=1 才返回数据）。
`reference/DouYin_Spider` 已配 remote（`origin` = 原仓库，`fork` = chenglei6-arch，
同步基准 fork/master = 37ec119 = 上游 9afaf79 + 修复）。
本项目移植版已在 `ref_dy_apis/douyin_api.py` 的 `get_user_following_list`
带上同样修复（28ae880）——同步时不得覆盖，也不要从原仓库同步。
