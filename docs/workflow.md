# 接入新平台工作流程

> 以「微博」为例的完整接入清单。当前 7 个平台的接入方式可作为参照实现
> （建议从结构最简单的 `genshin/adapter.py` 或最标准的 `netease/adapter.py` 起步抄骨架）。

## 1. 需要改动的位置（共 6 处）

```
① app/platforms/<id>/adapter.py    新建适配器（实现 base.py 抽象接口）
② app/platforms/__init__.py        _factory_for() 加分支 + known_platform_ids() 加 id
③ app/credentials/__init__.py      PLATFORM_FILES 加凭证文件名映射
④ frontend/src/platforms.js        PLATFORMS 数组加平台配置（前端渲染契约）
⑤ app/services/timeline.py         PLATFORM_NAME_MAP / CONTENT_TYPE_MAP 加映射
⑥ docs/platforms.md                补平台矩阵一行与要点（如有坑）
```

可选：`app/services/expand_queue.py` 的 `PLATFORM_MIN_INTERVALS` 为该平台加队列级
最小间隔（默认 0.3s，重平台如抖音 2.0s）。

## 2. 实现适配器

新建 `app/platforms/<id>/adapter.py`，继承 `BasePlatformAdapter`：

```python
from app.platforms.base import BasePlatformAdapter, PlatformProfile, ContentItem, EventItem

class XxxAdapter(BasePlatformAdapter):
    platform_id = "xxx"
    platform_name = "XX平台"

    def get_profile(self, uid): ...        # 必须实现；用户不存在返回 None
    def search_user(self, keyword, limit=20): ...  # 必须实现；返回 [{uid, nickname, avatarUrl, ...}]
```

其余方法（`get_content_lists / get_content_detail / get_history / get_events /
get_follows / get_followers / refresh_user_info / check_alive / get_login_user`）
按平台能力选实现，**不支持的不要覆盖**——base 默认返回空数据。

### 必须遵守的约定

- **错误一律 raise**：`raise RuntimeError("[XX平台] <真实原因>")`，带账号标签
  （多账号时用 `self._load_cookies()` 区分）。禁止 `except Exception: return []/None/{}`
  把失败伪装成空数据。允许的例外：`get_profile` 对"用户不存在"返回 `None`；
  `check_alive` 失败返回 `False`。
- **get_follows / get_followers 返回三元组** `(条目, has_more, 真实总数或 -1)`，
  支持 `skip` 参数做增量续拉（社交展开队列依赖）。
- **限速**：适配器内实现 `_rate_limit()`；图谱/展开会多线程并发调用适配器，
  限速要持锁串行化（参考 `douyin/adapter.py` 的 `_rl_lock` 做法）。
- **返回字段契约**：列表条目用 `uid / nickname / avatarUrl / signature / fans /
  is_verified / sec_uid(可选)`（社交展开和前端都按这套字段消费）；
  内容项用 `ContentItem`，资料用 `PlatformProfile`。

## 3. 注册与凭证

```python
# app/platforms/__init__.py
elif platform_id == "xxx":
    from app.platforms.xxx.adapter import XxxAdapter
    factory = lambda account_id=None: XxxAdapter(account_id=account_id)

def known_platform_ids():
    return [..., "xxx"]
```

```python
# app/credentials/__init__.py
PLATFORM_FILES = {..., "xxx": "xxx_cookie.txt"}
```

凭证文件放 `credentials/xxx_cookie.txt`（git 忽略），或让用户在面板「账号」弹窗里粘贴。

## 4. 前端配置（frontend/src/platforms.js）

在 `PLATFORMS` 数组加一项（字段见文件头注释）：

```js
{
  id: 'xxx', name: 'XX平台', color: '#xxxxxx',
  searchPlaceholder: '...', uidHint: '...',
  contentLabel: '内容', contentKind: 'playlist' /*现支持: playlist|video|work|post|character*/,
  hasDetail: false, hasRecords: false, hasEvents: true, hasSocial: true,
  looksLikeUid: (s) => /^\d+$/.test(s),
  resultUid: (u) => String(u.uid ?? ''),
  itemLink: (it) => it.item_id ? `https://.../${it.item_id}` : '',
  vipLabel: (p) => p.is_vip ? 'xxx' : '',   // 无会员体系可省略
  metaLine: (p) => [...], stats: (p, out) => {...},
}
```

侧边栏按钮、状态点、平台视图全部由该配置驱动，无需再改组件。

## 5. 时间线映射

```python
# app/services/timeline.py
PLATFORM_NAME_MAP = {..., "xxx": "XX平台"}
CONTENT_TYPE_MAP = {..., "xxx": "内容"}   # "发布了<内容>《标题》" 用
```

若希望该平台的听歌/观看记录参与时间推断，需在适配器实现 `get_history`
并在 `/all`（`app/routes/api.py`）的 records 分支加入平台判断。

## 6. 验证清单

```bash
# 启动 + 冒烟
python run.py
# 逐项确认（浏览器或 curl）
curl "http://127.0.0.1:5000/api/xxx/search?keyword=test"
curl "http://127.0.0.1:5000/api/xxx/all?uid=<某真实uid>"
# 图谱搜索该平台 → 展开一个节点 → 保存/调出图谱
# 终端面板观察日志：失败应有红色错误而非静默空结果
```

- [ ] 搜索返回结果且头像/昵称正确
- [ ] /all 各模块正常，故意断 Cookie 时 `_errors` 有明确原因
- [ ] 关注/粉丝展开正常，skip 增量续拉正确
- [ ] 时间线出现该平台条目，中文文案正确
- [ ] 前端卡片/详情弹窗/外链正确

## 7. 若实现来自开源项目

把上游仓库、本地参考副本位置、同步范围与已知本地修复写进
[UPSTREAM_SYNC.md](UPSTREAM_SYNC.md)——下次上游更新时按它同步，避免把修复覆盖丢。
