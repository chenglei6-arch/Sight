"""
社交关系展开核心逻辑

从 /graph/social 路由抽取的无框架依赖实现，供两处复用：
  1. REST 路由（单次同步展开）
  2. 展开队列 worker（后台批量展开，见 expand_queue.py）

多账号分配: 所有平台请求均通过 AdapterPool.lease() 轮询租借账号，
关注/粉丝两路并行时各租一个账号，邻居互查按并发线程数各租各的，
N 个账号 = N 条互不阻塞的请求流水线（各适配器限速状态按实例隔离）。
"""
from concurrent.futures import ThreadPoolExecutor

from app.platforms import get_pool


def clamp_int(v, lo, hi, default):
    try:
        return max(lo, min(int(v), hi))
    except (TypeError, ValueError):
        return default


def graph_user_node(pid: str, u: dict):
    """把平台返回的用户 dict 转成关系图节点；缺 uid/昵称的丢弃"""
    uid = str(u.get("uid", "")).strip()
    nickname = str(u.get("nickname", "")).strip()
    if not uid or not nickname:
        return None
    node = {
        "id": f"{pid}:{uid}",
        "platform": pid,
        "uid": uid,
        "nickname": nickname,
        "avatarUrl": u.get("avatarUrl", "") or "",
        "fans": u.get("fans") or 0,
        "signature": u.get("signature", "") or "",
    }
    # 官方认证/达人标记透传（微博 verified、B站 official、抖音 custom_verify 等）
    if u.get("is_verified") is not None:
        node["verified"] = bool(u.get("is_verified"))
    if u.get("sec_uid"):
        node["sec_uid"] = u["sec_uid"]
    return node


def expand_social(body: dict) -> dict:
    """
    展开某用户的社交关系，返回可合并进关系图的 nodes/edges。

    body 字段（与 /graph/social 请求体一致）:
      platform, uid            目标用户
      follows_limit            拉取关注数（0 表示不拉，默认 100）
      followers_limit          拉取粉丝数（0 表示不拉，默认 0）
      follows_skip             已拉取过的关注条数（增量续拉时跳过，默认 0）
      followers_skip           已拉取过的粉丝条数（增量续拉时跳过，默认 0）
      known_ids                图中已有节点 id 列表（"platform:uid"），用于邻居互查对交集
      intercheck_skip          已互查过的 uid 列表，跳过重复查询
      intercheck_extra         图中与目标相邻、但不在本次拉取结果里的 uid，补查它们
      intercheck_limit         最多互查多少个邻居（默认 40）
      intercheck_follow_limit  每个邻居取多少条关注（默认 50）

    返回 counts 附带 more（该方向是否还有更多）与 total（真实总数，平台支持时），
    供前端判断"还剩多少未展开"。平台未知时抛 ValueError。
    """
    platform = str(body.get("platform", "")).strip()
    uid = str(body.get("uid", "")).strip()
    if not platform or not uid:
        raise ValueError("缺少 platform 或 uid")

    pool = get_pool(platform)
    if not pool:
        raise ValueError(f"未知平台: {platform}")

    # 上限与前端工具栏可配置范围一致（10~500），避免前端设置被后端静默截断
    follows_limit = clamp_int(body.get("follows_limit", 100), 0, 500, 100)
    followers_limit = clamp_int(body.get("followers_limit", 0), 0, 500, 0)
    follows_skip = clamp_int(body.get("follows_skip", 0), 0, 5000, 0)
    followers_skip = clamp_int(body.get("followers_skip", 0), 0, 5000, 0)
    # 抖音单页 20 条且每请求限速 ~2s：单批超过 100 会非常慢，单独压低
    if platform == "douyin":
        follows_limit = min(follows_limit, 100)
        followers_limit = min(followers_limit, 100)
    intercheck_limit = clamp_int(body.get("intercheck_limit", 40), 0, 60, 40)
    intercheck_follow_limit = clamp_int(body.get("intercheck_follow_limit", 50), 10, 100, 50)

    known_uids = set()
    for item in body.get("known_ids", []) or []:
        pid, _, uid_part = str(item).partition(":")
        if pid == platform and uid_part:
            known_uids.add(uid_part)
    known_uids.add(uid)
    skip = {str(s) for s in body.get("intercheck_skip", []) or []}

    errors: dict[str, str] = {}
    follows_list: list = []
    followers_list: list = []

    def _fetch_via_pool(name, fn_name, limit, offset):
        """通过账号池租借适配器拉取数据；失败记录真实原因，由前端展示，不吞错"""
        if limit <= 0:
            return [], False, -1
        with pool.lease() as ad:
            if ad is None:
                errors[name] = "无可用账号"
                return [], False, -1
            try:
                # 各平台 get_follows/get_followers 已统一为 (条目, 还有更多, 总数)
                items, more, total = getattr(ad, fn_name)(uid, limit, offset)
                try:
                    total = int(total)
                except (TypeError, ValueError):
                    total = -1
                return items or [], bool(more), total
            except Exception as e:
                # 拉取失败（Cookie 失效/风控/接口异常）：记录真实原因并标注是哪个账号，由前端展示，不吞错
                errors[name] = f"[账号：{pool.label_for(ad)}] {e}"
                return [], False, -1

    # 关注/粉丝两路并行拉取：池内有多个账号时各租一个账号，互不排队
    if pool.size >= 2:
        with ThreadPoolExecutor(max_workers=2) as fetch_ex:
            f_follows = fetch_ex.submit(_fetch_via_pool, "follows", "get_follows", follows_limit, follows_skip)
            f_followers = fetch_ex.submit(_fetch_via_pool, "followers", "get_followers", followers_limit, followers_skip)
            follows_list, follows_more, follows_total = f_follows.result()
            followers_list, followers_more, followers_total = f_followers.result()
    else:
        follows_list, follows_more, follows_total = _fetch_via_pool(
            "follows", "get_follows", follows_limit, follows_skip
        )
        followers_list, followers_more, followers_total = _fetch_via_pool(
            "followers", "get_followers", followers_limit, followers_skip
        )

    nodes: list[dict] = []
    edges: list[dict] = []
    edge_keys: set[tuple] = set()
    neighbor_ids: list[str] = []  # 互查候选，关注在前粉丝在后，去重保序

    def _add_edge(src_uid: str, dst_uid: str):
        key = (src_uid, dst_uid)
        if key in edge_keys or src_uid == dst_uid:
            return
        edge_keys.add(key)
        edges.append({
            "source": f"{platform}:{src_uid}",
            "target": f"{platform}:{dst_uid}",
            "relation": "follows",
        })

    seen_uids = {uid}
    for u in follows_list:
        node = graph_user_node(platform, u)
        if node is None or node["uid"] in seen_uids:
            continue
        seen_uids.add(node["uid"])
        nodes.append(node)
        neighbor_ids.append(node["uid"])
        _add_edge(uid, node["uid"])
    for u in followers_list:
        node = graph_user_node(platform, u)
        if node is None or node["uid"] in seen_uids:
            continue
        seen_uids.add(node["uid"])
        nodes.append(node)
        neighbor_ids.append(node["uid"])
        _add_edge(node["uid"], uid)

    # ---- 邻居互查: 查邻居的关注列表，命中图中已有节点则建 b→c 边 ----
    extra = [str(x) for x in body.get("intercheck_extra", []) or []]
    ordered_targets = []
    seen_targets = set()
    for n in neighbor_ids + extra:
        if n == uid or n in skip or n in seen_targets:
            continue
        seen_targets.add(n)
        ordered_targets.append(n)
    intercheck_targets = ordered_targets[:intercheck_limit]

    def _intercheck(n_uid: str):
        with pool.lease() as ad:
            if ad is None:
                return []
            try:
                follows, _more, _total = ad.get_follows(n_uid, intercheck_follow_limit)
            except Exception:
                return []
        out = []
        for f in follows:
            t = str(f.get("uid", "")).strip()
            if t and t in known_uids and t != n_uid:
                out.append((n_uid, t))
        return out

    intercheck_edges: list[dict] = []
    if intercheck_targets:
        # 线程数随可用账号数扩展（下限 4 兼容旧行为，上限 8）；
        # 每个线程租借不同账号，各账号限速独立，真正并行
        with ThreadPoolExecutor(max_workers=min(8, max(4, pool.size))) as executor:
            for pairs in executor.map(_intercheck, intercheck_targets):
                for src, dst in pairs:
                    key = (src, dst)
                    if key in edge_keys:
                        continue
                    edge_keys.add(key)
                    intercheck_edges.append({
                        "source": f"{platform}:{src}",
                        "target": f"{platform}:{dst}",
                        "relation": "follows",
                    })

    return {
        "platform": platform,
        "uid": uid,
        "counts": {
            "follows": len(follows_list),
            "followers": len(followers_list),
            # 该方向是否还有更多（"剩余未展开"判断依据）
            "follows_more": bool(follows_more),
            "followers_more": bool(followers_more),
            # 真实总数（仅平台支持时提供，-1 表示未知）
            "follows_total": follows_total if follows_total >= 0 else None,
            "followers_total": followers_total if followers_total >= 0 else None,
            # 本次请求前已拉取的数量（增量续拉时前端累计用）
            "follows_offset": follows_skip,
            "followers_offset": followers_skip,
        },
        "nodes": nodes,
        "edges": edges,
        "intercheck": {
            "checked": len(intercheck_targets),
            "total": len(ordered_targets),
            "targets": intercheck_targets,
            "edges": intercheck_edges,
        },
        "errors": errors,
    }
