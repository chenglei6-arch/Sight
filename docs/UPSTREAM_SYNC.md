# 上游同步说明

各平台移植/参考模块的上游仓库与同步约定。

## 抖音（douyin）

- **上游仓库：使用 fork，不要从原仓库同步**
  - fork：<https://github.com/chenglei6-arch/DouYin_Spider>
  - 原仓库：<https://github.com/cv-cat/DouYin_Spider>
- **原因**：原仓库的 `get_user_following_list`（关注列表）存在 bug——
  `max_time=0` 时服务端走另一条分支，只回 `mix_count` 不回 `followings`，
  会被误判为"平台限制查看他人列表"。fork 提交 `37ec119` 修复：
  max_time 需传当前秒级时间戳（source_type=1）才返回数据。
- **本项目移植版**已在 `app/platforms/douyin/ref_dy_apis/douyin_api.py`
  的 `get_user_following_list` 内带上同样的修复（28ae880）。
  **未来从 fork 同步时不要把这段覆盖丢**；也不要直接从原仓库同步。
- 同步范围：`builder/` → `ref_builder/`、`dy_apis/` → `ref_dy_apis/`、
  `utils/` → `ref_utils/`、`static/` → `ref_static/`（注意本项目有导入路径与本仓库
  约定的适配改动，逐文件 diff 手工移植，不要整目录覆盖）。
- 本地参考副本 `reference/DouYin_Spider` 已配置 remote：
  `origin` = 原仓库、`fork` = chenglei6-arch fork（同步基准）。
  截至 2026-09-12：fork/master = 37ec119（= 上游 9afaf79 + max_time 修复）。

## 小红书（xhs）

- 上游：<https://github.com/cv-cat/Spider_XHS>
- 同步范围：`xhs_utils/xhs_core/` → `ref_xhs_core/`、
  `xhs_utils/xhs_pc/` → `ref_xhs_pc/`、
  `apis/xhs_pc_apis.py` → `ref_apis/xhs_pc_apis.py`。
- 本项目未启用 creator 模式，`xhs_utils/xhs_creator/` 不同步。

## 其他

- QQ音乐：参考 [jsososo/QQMusicApi](https://github.com/jsososo/QQMusicApi)
  （2022 年后未更新，仅作接口文档参考）；适配器为自写直连 y.qq.com。
- 原神：参考 YuanShen_User_Info；适配器自写直连 enka.network + 米游社 API。
- 网易云 / B站 / 微博：自写适配器，无上游。
