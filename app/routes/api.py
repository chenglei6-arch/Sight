"""
多平台 REST API 路由

URL 模式:
  /api/<platform>/profile?uid=xxx      用户资料
  /api/<platform>/search?keyword=xxx   搜索用户
  /api/<platform>/playlists?uid=xxx    内容列表
  /api/<platform>/playlist/<id>        内容详情
  /api/<platform>/records?uid=xxx      历史排行
  /api/<platform>/events?uid=xxx       用户动态
  /api/<platform>/follows?uid=xxx      关注
  /api/<platform>/followers?uid=xxx    粉丝

历史 & 报告:
  /api/history/snap?platform=..&uid=..&type=..  获取快照
  /api/history/save                            手动保存快照
  /api/report/overview?platform=..&uid=..       用户概览
  /api/report/trend?platform=..&uid=..&type=..  趋势报告
  /api/report/cross-platform?uids=..            跨平台汇总

关系图谱:
  /api/graph/search?keyword=..&platforms=..     跨平台搜索生成关系图
  /api/graph/social (POST)                      展开节点社交关系
  /api/graph/save (POST)                        按名称保存当前图谱（同名覆盖）
  /api/graph/saved                              已保存图谱列表
  /api/graph/saved/<id>                         图谱完整数据（GET）/ 删除（DELETE）

管理:
  /api/platforms                   列出所有平台
  /api/credentials                 查看/更新凭证
"""
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, jsonify, request

from app.platforms import get_adapter, list_platforms, reset_adapter
from app.config import DEFAULT_TARGET_UID, DEFAULT_PLATFORM
from app.data.store import DataStore
from app.report.generator import ReportGenerator
from app.credentials import CredentialManager

bp = Blueprint("api", __name__, url_prefix="/api")

_store = None
_report = None

# 请求日志目录
LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CST = timezone(timedelta(hours=8))


def _log_fetch(method: str, platform: str, uid: str, success: bool, elapsed_ms: float, detail: str = ""):
    """记录每次数据拉取请求到日志文件"""
    try:
        import logging
        now = datetime.now(CST)
        log_file = LOG_DIR / f"fetch_{now.strftime('%Y%m%d')}.log"

        status = "OK" if success else "FAIL"
        line = (
            f"{now.strftime('%Y-%m-%d %H:%M:%S')} | {method:6s} | {platform:8s} | "
            f"uid={uid:15s} | {status:4s} | {elapsed_ms:7.1f}ms"
        )
        if detail:
            line += f" | {detail}"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # 日志写入失败不影响主流程


def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store


def get_report() -> ReportGenerator:
    global _report
    if _report is None:
        _report = ReportGenerator(get_store())
    return _report


# ==================== 辅助函数 ====================

def _get_platform() -> str:
    """获取请求中的平台参数，默认 netease"""
    return request.args.get("platform", DEFAULT_PLATFORM).strip()


def _get_uid(platform: str = None) -> str:
    """
    获取目标 UID。
    优先级: 请求参数 > 配置默认 > 登录用户
    """
    uid = request.args.get("uid", "").strip()
    if uid:
        return uid
    if DEFAULT_TARGET_UID and (platform is None or platform == DEFAULT_PLATFORM):
        return DEFAULT_TARGET_UID
    # 尝试从登录用户获取
    adapter = get_adapter(platform or _get_platform())
    if adapter:
        login_user = adapter.get_login_user()
        if login_user:
            return str(login_user.get("uid", ""))
    return ""


def _result(data, code=200):
    """统一响应格式"""
    return jsonify({"code": code, "data": data})


def _error(msg, code=-1, http_status=500):
    return jsonify({"code": code, "message": msg}), http_status


# ==================== 平台管理 ====================

@bp.route("/platforms")
def list_platforms_api():
    """列出所有可用平台及其状态"""
    try:
        platforms = list_platforms()
        return jsonify({"code": 200, "data": platforms})
    except Exception as e:
        return _error(str(e))


@bp.route("/credentials/<platform>")
def get_credentials(platform):
    """查看平台凭证状态"""
    try:
        cookies = CredentialManager.load_cookies(platform)
        # 掩码显示，不暴露完整 cookie
        masked = {k: (v[:10] + "..." if len(v) > 10 else v) for k, v in cookies.items()}
        return jsonify({
            "code": 200,
            "data": {
                "platform": platform,
                "has_credential": bool(cookies),
                "cookie_keys": list(cookies.keys()),
                "cookie_preview": masked,
            }
        })
    except Exception as e:
        return _error(str(e))


@bp.route("/credentials/<platform>", methods=["POST"])
def update_credentials(platform):
    """更新平台 Cookie（body: {cookie: "k=v; k2=v2"}），保存后立即生效"""
    body = request.get_json(silent=True) or {}
    cookie_str = str(body.get("cookie", "")).strip()
    if not cookie_str:
        return _error("cookie 内容为空", http_status=400)
    if platform not in CredentialManager.PLATFORM_FILES:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        CredentialManager.save_cookies(platform, cookie_str)
        # 适配器实例内缓存了 Cookie/登录态（如抖音 _auth），重建以便新 Cookie 立即生效
        reset_adapter(platform)
        cookies = CredentialManager.load_cookies(platform)
        return _result({
            "platform": platform,
            "has_credential": bool(cookies),
            "cookie_keys": list(cookies.keys()),
        })
    except Exception as e:
        return _error(str(e))


# ==================== 用户搜索（跨平台） ====================

@bp.route("/<platform>/search")
def search_user(platform):
    """搜索用户"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return _error("请输入搜索关键词", http_status=400)

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        users = adapter.search_user(keyword)
        return _result(users)
    except Exception as e:
        return _error(str(e))


# ==================== 关系图（跨平台搜索归并） ====================

def _norm_nickname(name: str) -> str:
    """昵称归一化：全角转半角、去空白、转小写，用于跨平台同人判定"""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(name or ""))
    return "".join(s.split()).lower()


def _name_similarity(a: str, b: str) -> float:
    import difflib
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ==================== 搜索缓存（关系图用） ====================

SEARCH_CACHE_TTL = 30 * 60  # 缓存失效时间：30 分钟
# key: (platform, keyword, limit) -> (存入时间戳, 用户列表)
_search_cache: dict[tuple, tuple[float, list]] = {}
_search_cache_lock = threading.Lock()


def _search_user_cached(pid: str, keyword: str, limit: int, force: bool = False):
    """
    带缓存的平台用户搜索（TTL 见 SEARCH_CACHE_TTL，默认 30 分钟）。

    只缓存"成功且非空"的结果；登录失效/风控返回的空列表一律不缓存，
    这样修好 Cookie 或风控放行后的下一次搜索能立即拿到真实数据。
    进程重启即全量失效；force=True（前端 refresh=1）可跳过读缓存。

    返回 (users, from_cache: bool)
    """
    key = (pid, keyword, limit)
    now = time.time()
    if not force:
        with _search_cache_lock:
            hit = _search_cache.get(key)
            if hit and now - hit[0] < SEARCH_CACHE_TTL:
                return list(hit[1]), True

    users: list = []
    adapter = get_adapter(pid)
    if not adapter:
        return users, False
    users = adapter.search_user(keyword, limit) or []  # 失败异常直接上抛，由调用方收集展示

    if users:
        with _search_cache_lock:
            _search_cache[key] = (now, list(users))
    return users, False


def _graph_user_node(pid: str, u: dict):
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
    if u.get("sec_uid"):
        node["sec_uid"] = u["sec_uid"]
    return node


@bp.route("/graph/search")
def graph_search():
    """
    按关键词并行搜索各平台用户，聚合为关系图数据。

    节点: 关键词中心节点 + 用户节点（platform:uid）
    边:
      hit    中心 -> 用户（关键词命中）
      same   用户 <-> 用户（跨平台昵称完全一致，疑似同一人）
      alike  用户 <-> 用户（昵称相似度 >= 0.9，弱关联）
    """
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return _error("请输入搜索关键词", http_status=400)

    try:
        limit = max(3, min(int(request.args.get("limit", 10)), 20))
    except ValueError:
        limit = 10

    requested = request.args.get("platforms", "").strip()
    if requested:
        platform_ids = [p for p in requested.split(",") if p]
    else:
        platform_ids = [p["id"] for p in CredentialManager.get_available_platforms()]

    refresh = request.args.get("refresh", "").strip() in ("1", "true")

    def _search_one(pid: str):
        try:
            adapter = get_adapter(pid)
            if not adapter:
                return pid, [], None, False
            users, from_cache = _search_user_cached(pid, keyword, limit, force=refresh)
            return pid, users, None, from_cache
        except Exception as e:
            return pid, [], str(e), False

    results: dict[str, list] = {}
    errors: dict[str, str] = {}
    cached_pids: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(platform_ids)))) as pool:
        for pid, users, err, from_cache in pool.map(_search_one, platform_ids):
            results[pid] = users
            if err:
                errors[pid] = err
            if from_cache:
                cached_pids.append(pid)

    nodes = [{
        "id": "keyword",
        "platform": "keyword",
        "uid": "",
        "nickname": keyword,
        "avatarUrl": "",
        "fans": 0,
        "signature": "搜索关键词",
    }]
    edges: list[dict] = []
    norm_index: list[dict] = []  # 参与同人判定的 (节点id, 平台, 归一化昵称)

    for pid, users in results.items():
        for u in users:
            node = _graph_user_node(pid, u)
            if node is None:
                continue
            nodes.append(node)
            edges.append({"source": "keyword", "target": node["id"], "relation": "hit"})
            norm_index.append({"id": node["id"], "platform": pid, "norm": _norm_nickname(node["nickname"])})

    # 跨平台同人判定（只比较不同平台之间，避免同平台重名误连）
    for i in range(len(norm_index)):
        for j in range(i + 1, len(norm_index)):
            a, b = norm_index[i], norm_index[j]
            if a["platform"] == b["platform"]:
                continue
            if not a["norm"] or not b["norm"]:
                continue
            if a["norm"] == b["norm"]:
                edges.append({"source": a["id"], "target": b["id"], "relation": "same"})
            elif _name_similarity(a["norm"], b["norm"]) >= 0.9:
                edges.append({"source": a["id"], "target": b["id"], "relation": "alike"})

    return _result({
        "keyword": keyword,
        "searched": sorted(platform_ids),  # 本次实际请求的平台（含无结果的）
        "platforms": sorted(pid for pid, users in results.items() if users),
        "nodes": nodes,
        "edges": edges,
        "errors": errors,
        "cached": sorted(cached_pids),  # 本次结果命中了 30 分钟缓存的平台
    })


def _clamp_int(v, lo, hi, default):
    try:
        return max(lo, min(int(v), hi))
    except (TypeError, ValueError):
        return default


@bp.route("/graph/social", methods=["POST"])
def graph_social():
    """
    展开某用户的社交关系，返回可合并进关系图的 nodes/edges。

    请求体:
      platform, uid            目标用户
      follows_limit            拉取关注数（0 表示不拉，默认 100）
      followers_limit          拉取粉丝数（0 表示不拉，默认 0）
      known_ids                图中已有节点 id 列表（"platform:uid"），用于邻居互查对交集
      intercheck_skip          已互查过的 uid 列表，跳过重复查询
      intercheck_extra         图中与目标相邻、但不在本次拉取结果里的 uid，补查它们
      intercheck_limit         最多互查多少个邻居（默认 40）
      intercheck_follow_limit  每个邻居取多少条关注（默认 50）

    互查: 对目标用户的每个邻居查其关注列表，与 known 同平台节点求交集，
    得到 b→c 这类"邻居之间"的关注边。
    """
    body = request.get_json(silent=True) or {}
    platform = str(body.get("platform", "")).strip()
    uid = str(body.get("uid", "")).strip()
    if not platform or not uid:
        return _error("缺少 platform 或 uid", http_status=400)

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    follows_limit = _clamp_int(body.get("follows_limit", 100), 0, 200, 100)
    followers_limit = _clamp_int(body.get("followers_limit", 0), 0, 200, 0)
    intercheck_limit = _clamp_int(body.get("intercheck_limit", 40), 0, 60, 40)
    intercheck_follow_limit = _clamp_int(body.get("intercheck_follow_limit", 50), 10, 100, 50)

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

    def _fetch(name, fn, limit):
        if limit <= 0:
            return []
        try:
            return fn(uid, limit) or []
        except Exception as e:
            errors[name] = str(e)
            return []

    follows_list = _fetch("follows", adapter.get_follows, follows_limit)
    followers_list = _fetch("followers", adapter.get_followers, followers_limit)

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
        node = _graph_user_node(platform, u)
        if node is None or node["uid"] in seen_uids:
            continue
        seen_uids.add(node["uid"])
        nodes.append(node)
        neighbor_ids.append(node["uid"])
        _add_edge(uid, node["uid"])
    for u in followers_list:
        node = _graph_user_node(platform, u)
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
        try:
            follows = adapter.get_follows(n_uid, intercheck_follow_limit) or []
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
        with ThreadPoolExecutor(max_workers=4) as pool:
            for pairs in pool.map(_intercheck, intercheck_targets):
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

    return _result({
        "platform": platform,
        "uid": uid,
        "counts": {
            "follows": len(follows_list),
            "followers": len(followers_list),
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
    })


# ==================== 关系图谱持久化（命名保存 / 侧边栏调出） ====================

GRAPH_NAME_MAX_LEN = 60


@bp.route("/graph/save", methods=["POST"])
def graph_save():
    """
    保存当前关系图谱（body: {name, keyword, data}）。
    data 为 /graph/search（可能已并入 /graph/social 展开结果）的原始载荷，
    含 nodes/edges/searched/platforms/errors/cached。同名图谱覆盖更新。
    """
    body = request.get_json(force=True, silent=True) or {}
    name = str(body.get("name", "")).strip()[:GRAPH_NAME_MAX_LEN]
    data = body.get("data")
    if not name:
        return _error("请提供图谱名称", http_status=400)
    if not isinstance(data, dict) or not data.get("nodes"):
        return _error("图谱数据为空，无法保存", http_status=400)

    keyword = str(body.get("keyword") or data.get("keyword") or "").strip()
    try:
        graph_id = get_store().save_graph(name, keyword, data)
        return _result({"id": graph_id, "name": name})
    except Exception as e:
        return _error(str(e))


@bp.route("/graph/saved")
def graph_saved_list():
    """列出所有已保存图谱的元信息（侧边栏用，不含节点/边数据）"""
    try:
        return _result(get_store().list_graphs())
    except Exception as e:
        return _error(str(e))


@bp.route("/graph/saved/<int:graph_id>")
def graph_saved_detail(graph_id):
    """获取一张已保存图谱的完整数据（前端直接渲染，不再请求平台数据）"""
    try:
        graph = get_store().get_graph(graph_id)
        if graph is None:
            return _error("图谱不存在或已被删除", http_status=404)
        return _result(graph)
    except Exception as e:
        return _error(str(e))


@bp.route("/graph/saved/<int:graph_id>", methods=["DELETE"])
def graph_saved_delete(graph_id):
    """删除一张已保存图谱"""
    try:
        ok = get_store().delete_graph(graph_id)
        if ok:
            return _result({"message": "删除成功", "id": graph_id})
        return _error("图谱不存在或已被删除", http_status=404)
    except Exception as e:
        return _error(str(e))


# ==================== 用户资料 ====================

@bp.route("/<platform>/profile")
def user_profile(platform):
    """获取用户资料"""
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID，且无默认配置")

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        profile = adapter.get_profile(uid)
        if profile is None:
            return _error("获取资料失败")

        # 转为字典进行存储和返回
        data = _dataclass_to_dict(profile)

        # 自动保存快照
        try:
            get_store().save_snapshot(platform, uid, "profile", data)
        except Exception:
            pass

        return _result(data)
    except Exception as e:
        return _error(str(e))


# ==================== 内容列表（歌单/收藏夹） ====================

@bp.route("/<platform>/playlists")
def content_lists(platform):
    """获取用户内容列表"""
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        items = adapter.get_content_lists(uid)
        data = [_dataclass_to_dict(item) for item in items]

        get_store().save_snapshot(platform, uid, "playlists", {
            "count": len(data),
            "items": data,
        })

        return _result(data)
    except Exception as e:
        return _error(str(e))


@bp.route("/<platform>/playlist/<item_id>")
def content_detail(platform, item_id):
    """获取内容详情"""
    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        detail = adapter.get_content_detail(item_id)
        if detail is None:
            return _error("获取详情失败")
        return _result(detail)
    except Exception as e:
        return _error(str(e))


# ==================== 历史排行 ====================

@bp.route("/<platform>/records")
def history_records(platform):
    """获取历史排行（听歌/观看）"""
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        all_time = adapter.get_history(uid, "all")
        weekly = adapter.get_history(uid, "week")

        all_data = [_dataclass_to_dict(e) for e in all_time]
        week_data = [_dataclass_to_dict(e) for e in weekly]

        get_store().save_snapshot(platform, uid, "records", {
            "allTime": all_data,
            "weekly": week_data,
        })

        return _result({
            "allTime": all_data,
            "weekly": week_data,
        })
    except Exception as e:
        return _error(str(e))


# ==================== 动态 ====================

@bp.route("/<platform>/events")
def user_events(platform):
    """获取用户动态"""
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        events = adapter.get_events(uid)
        data = [_dataclass_to_dict(e) for e in events]

        get_store().save_snapshot(platform, uid, "events", {
            "count": len(data),
            "items": data,
        })

        return _result(data)
    except Exception as e:
        return _error(str(e))


# ==================== 关注/粉丝 ====================

@bp.route("/<platform>/follows")
def user_follows(platform):
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")
    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)
    try:
        return _result(adapter.get_follows(uid))
    except Exception as e:
        return _error(str(e))


@bp.route("/<platform>/followers")
def user_followers(platform):
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")
    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)
    try:
        return _result(adapter.get_followers(uid))
    except Exception as e:
        return _error(str(e))


# ==================== 聚合数据接口（一次请求取所有数据） ====================

SNAPSHOT_TTL = 30 * 60  # /all 中 profile/playlists/events 快照的有效期（秒），过期实时重拉


def _snapshot_age(snapshot: dict):
    """快照的年龄（秒）；无法解析时间返回 None"""
    ts = snapshot.get("_snapshot_time")
    if not ts:
        return None
    try:
        return max(0.0, time.time() - datetime.fromisoformat(str(ts)).timestamp())
    except (ValueError, TypeError, OSError):
        return None


def _is_marker(snapshot: dict) -> bool:
    """内容未变化的占位快照（save_snapshot 只存哈希标记，不含真实数据）"""
    return isinstance(snapshot, dict) and bool(snapshot.get("_marker"))


def _snapshot_is_usable(platform: str, data_type: str, snapshot: dict) -> bool:
    """Reject legacy XHS snapshots created before the current response mapping.

    TODO(迁移补丁): 仅用于拦截 xhs 字段映射修复前落库的乱码/缺字段快照。
    被拒的快照会在 /all 中实时重拉并覆盖保存，跑过一段时间后即可整体删除本函数
    及其三处调用；删除前 events 判定绑定了 event_type=="发布笔记"，新增事件类型时需同步。
    """
    if platform != "xhs":
        return True
    if not isinstance(snapshot, dict):
        return False

    if data_type == "profile":
        nickname = str(snapshot.get("nickname") or "")
        return bool(nickname) and "\ufffd" not in nickname

    items = snapshot.get("items")
    if not isinstance(items, list) or not items:
        return False
    first = next((item for item in items if isinstance(item, dict)), None)
    if not first:
        return False

    if data_type == "playlists":
        title = str(first.get("title") or "")
        return (
            bool(title)
            and title != "无标题"
            and "\ufffd" not in title
            and ("create_time" in first or "url" in first)
        )
    if data_type == "events":
        content = str(first.get("content") or "")
        event_type = str(first.get("event_type") or "")
        return (
            bool(content)
            and content != "无标题"
            and "\ufffd" not in content
            and event_type == "发布笔记"
            and (first.get("timestamp") or first.get("url"))
        )
    return True

@bp.route("/<platform>/all")
def platform_all(platform):
    """获取平台所有数据（单次请求，避免并行触发频率限制）"""
    uid = _get_uid(platform)
    if not uid:
        return _error("未指定用户 UID")

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    t0 = time.perf_counter()
    success = False
    detail = ""
    try:
        result = {"platform": platform, "uid": uid}
        errors = []  # 收集各子模块错误，但不中断整体返回

        # 用户资料：30 分钟内的快照直接用；过期/缺失实时拉取，实时失败回退旧快照
        result["profile"] = None
        try:
            real_snaps = [
                s for s in get_store().get_snapshots(platform, uid, "profile", limit=5)
                if not _is_marker(s)
            ]
            fresh = None
            for s in real_snaps:
                age = _snapshot_age(s)
                if (
                    age is not None
                    and age < SNAPSHOT_TTL
                    and _snapshot_is_usable(platform, "profile", s)
                ):
                    fresh = s
                    break
            if fresh:
                result["profile"] = fresh
            else:
                profile = adapter.get_profile(uid)
                if profile:
                    profile_dict = _dataclass_to_dict(profile)
                    result["profile"] = profile_dict
                    get_store().save_snapshot(platform, uid, "profile", profile_dict)
                elif real_snaps:
                    result["profile"] = real_snaps[0]
                    errors.append("profile: 实时拉取失败，已回退到历史快照")
        except Exception as e:
            errors.append(f"profile: {e}")

        # 内容列表：30 分钟内的快照直接用；过期/缺失实时拉取 + 写入快照，失败回退旧快照
        result["playlists"] = []
        try:
            real_pl = [
                s for s in get_store().get_snapshots(platform, uid, "playlists", limit=5)
                if not _is_marker(s)
            ]
            snap_pl = None
            for s in real_pl:
                age = _snapshot_age(s)
                if (
                    s.get("items")
                    and age is not None
                    and age < SNAPSHOT_TTL
                    and _snapshot_is_usable(platform, "playlists", s)
                ):
                    snap_pl = s
                    break
            if snap_pl:
                result["playlists"] = snap_pl["items"]
                print(f"[{platform}] /all playlists 命中新鲜快照({int(_snapshot_age(snap_pl) or 0)}s): {len(result['playlists'])} 项")
            else:
                items = adapter.get_content_lists(uid)
                item_dicts = [_dataclass_to_dict(i) for i in items]
                result["playlists"] = item_dicts
                if item_dicts:
                    get_store().save_snapshot(platform, uid, "playlists", {
                        "count": len(item_dicts), "items": item_dicts,
                    })
                    print(f"[{platform}] /all playlists 实时拉取并保存: {len(item_dicts)} 项")
                elif real_pl and real_pl[0].get("items"):
                    result["playlists"] = real_pl[0]["items"]
                    errors.append("playlists: 实时拉取为空，已回退到历史快照")
                    print(f"[{platform}] /all playlists 实时拉取为空，回退快照: {len(result['playlists'])} 项")
                else:
                    print(f"[{platform}] /all playlists 实时拉取为空")
        except Exception as e:
            errors.append(f"playlists: {e}")
            print(f"[{platform}] /all playlists 异常: {e}")

        # 历史/播放记录（实时拉取 + 写入快照供时间线使用）
        result["records"] = {"allTime": [], "weekly": []}
        try:
            if platform == "netease":
                all_t = adapter.get_history(uid, "all")
                weekly = adapter.get_history(uid, "week")
                all_data = [_dataclass_to_dict(e) for e in all_t]
                week_data = [_dataclass_to_dict(e) for e in weekly]
                result["records"] = {"allTime": all_data, "weekly": week_data}
                if all_data or week_data:
                    get_store().save_snapshot(platform, uid, "records", {
                        "allTime": all_data, "weekly": week_data,
                    })
        except Exception as e:
            errors.append(f"records: {e}")

        # 动态：优先快照，失败时实时获取 + 写入快照
        result["events"] = []
        try:
            real_ev = [
                s for s in get_store().get_snapshots(platform, uid, "events", limit=5)
                if not _is_marker(s)
            ]
            snap_ev = None
            for s in real_ev:
                age = _snapshot_age(s)
                if (
                    s.get("items")
                    and age is not None
                    and age < SNAPSHOT_TTL
                    and _snapshot_is_usable(platform, "events", s)
                ):
                    snap_ev = s
                    break
            if snap_ev:
                result["events"] = snap_ev["items"]
                print(f"[{platform}] /all events 命中新鲜快照({int(_snapshot_age(snap_ev) or 0)}s): {len(result['events'])} 条")
            else:
                events = adapter.get_events(uid)
                event_dicts = [_dataclass_to_dict(e) for e in events]
                result["events"] = event_dicts
                if event_dicts:
                    get_store().save_snapshot(platform, uid, "events", {
                        "count": len(event_dicts), "items": event_dicts,
                    })
                    print(f"[{platform}] /all events 实时拉取并保存: {len(event_dicts)} 条")
                elif real_ev and real_ev[0].get("items"):
                    result["events"] = real_ev[0]["items"]
                    errors.append("events: 实时拉取为空，已回退到历史快照")
                    print(f"[{platform}] /all events 实时拉取为空，回退快照: {len(result['events'])} 条")
                else:
                    print(f"[{platform}] /all events 实时拉取为空")
        except Exception as e:
            errors.append(f"events: {e}")
            print(f"[{platform}] /all events 异常: {e}")

        # 关注（同时保存快照供变化检测）
        result["follows"] = []
        try:
            follows_list = adapter.get_follows(uid)
            result["follows"] = follows_list
            if follows_list:
                get_store().save_snapshot(platform, uid, "follows", {
                    "count": len(follows_list),
                    "items": follows_list,
                })
        except Exception as e:
            errors.append(f"follows: {e}")

        # 粉丝（同时保存快照供变化检测）
        result["followers"] = []
        try:
            followers_list = adapter.get_followers(uid)
            result["followers"] = followers_list
            if followers_list:
                get_store().save_snapshot(platform, uid, "followers", {
                    "count": len(followers_list),
                    "items": followers_list,
                })
        except Exception as e:
            errors.append(f"followers: {e}")

        elapsed_ms = (time.perf_counter() - t0) * 1000

        # 检查是否有任何成功获取的数据
        has_any_data = (
            result["profile"] is not None
            or result["playlists"]
            or result["events"]
            or result["follows"]
            or result["followers"]
        )
        if not has_any_data:
            detail = "all_failed: " + "; ".join(errors)
            _log_fetch("GET /all", platform, uid, False, elapsed_ms, detail)
            return _error("所有数据模块均加载失败: " + "; ".join(errors))

        # 部分数据成功：即使 profile/playlists/events 为空，
        # 但只要 follows/followers 有数据就正常返回（如 QQ 音乐 SSR 降级场景）
        if errors:
            detail = "partial: " + "; ".join(errors)
            result["_errors"] = errors
            print(f"[{platform}] /all 部分数据加载失败: {'; '.join(errors)}")

        success = True
        _log_fetch("GET /all", platform, uid, success, elapsed_ms, detail)
        return _result(result)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _log_fetch("GET /all", platform, uid, False, elapsed_ms, str(e))
        return _error(str(e))


# ==================== QQ音乐 QR 扫码登录 ====================

@bp.route("/qqmusic/qr-login/start", methods=["POST"])
def qr_login_start():
    """启动 QQ 音乐 QR 扫码登录"""
    from app.services.qqmusic_qr_login import get_session
    body = request.get_json(force=True, silent=True) or {}
    target_uid = body.get("uid", "oK6kowEAoK4z7Knioivl7evl7n**")
    session = get_session()
    result = session.start(target_uid)
    return _result(result)


@bp.route("/qqmusic/qr-login/status")
def qr_login_status():
    """轮询 QR 登录状态"""
    from app.services.qqmusic_qr_login import get_session
    session = get_session()
    return _result(session.get_status_dict())


@bp.route("/qqmusic/qr-login/follows")
def qr_login_follows():
    """获取关注列表（登录后使用）"""
    uid = request.args.get("uid", "oK6kowEAoK4z7Knioivl7evl7n**")
    from app.services.qqmusic_qr_login import get_session
    session = get_session()
    status_data = session.get_status_dict()

    # 如果已经登录但还未抓取，返回当前状态
    if status_data["status"] == "done" and status_data.get("follow_data"):
        return _result(status_data["follow_data"])

    # 如果还在进行中，告知状态
    if status_data["status"] in ("logged_in", "fetching", "starting", "qr_ready"):
        return _result({
            "status": status_data["status"],
            "message": "请等待登录完成后自动获取",
        })

    # 未开始或已停止：启动新流程
    result = session.start(uid)
    return _result({
        "status": result["status"],
        "message": "扫码登录流程已启动",
    })


@bp.route("/qqmusic/qr-login/stop", methods=["POST"])
def qr_login_stop():
    """停止 QR 登录会话"""
    from app.services.qqmusic_qr_login import get_session
    session = get_session()
    session.stop()
    return _result({"status": "stopped"})


# ==================== 状态检查 ====================

@bp.route("/<platform>/status")
def platform_status(platform):
    """检查指定平台连接状态"""
    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)
    try:
        alive = adapter.check_alive()
        login_user = adapter.get_login_user()
        return _result({
            "platform": platform,
            "alive": alive,
            "login_user": login_user,
        })
    except Exception as e:
        return _error(str(e))


# ==================== 历史快照 ====================

@bp.route("/history/snapshots")
def get_snapshots():
    """获取历史快照"""
    platform = request.args.get("platform", "")
    uid = request.args.get("uid", "")
    data_type = request.args.get("type", "profile")
    since = request.args.get("since", None)
    limit = int(request.args.get("limit", 50))

    if not platform or not uid:
        return _error("缺少 platform 或 uid 参数", http_status=400)

    try:
        snaps = get_store().get_snapshots(platform, uid, data_type, since, limit)
        return _result(snaps)
    except Exception as e:
        return _error(str(e))


@bp.route("/history/save", methods=["POST"])
def save_snapshot():
    """手动保存当前数据快照"""
    body = request.get_json(force=True, silent=True) or {}
    platform = body.get("platform", DEFAULT_PLATFORM)
    uid = body.get("uid", _get_uid(platform))
    data_type = body.get("type", "profile")

    if not uid:
        return _error("未指定用户 UID", http_status=400)

    adapter = get_adapter(platform)
    if not adapter:
        return _error(f"未知平台: {platform}", http_status=404)

    try:
        if data_type == "profile":
            profile = adapter.get_profile(uid)
            if profile:
                get_store().save_snapshot(platform, uid, "profile", _dataclass_to_dict(profile))
                return _result({"saved": "profile"})
        elif data_type == "records":
            all_time = adapter.get_history(uid, "all")
            weekly = adapter.get_history(uid, "week")
            get_store().save_snapshot(platform, uid, "records", {
                "allTime": [_dataclass_to_dict(e) for e in all_time],
                "weekly": [_dataclass_to_dict(e) for e in weekly],
            })
            return _result({"saved": "records"})
        elif data_type == "playlists":
            items = adapter.get_content_lists(uid)
            get_store().save_snapshot(platform, uid, "playlists", {
                "count": len(items),
                "items": [_dataclass_to_dict(item) for item in items],
            })
            return _result({"saved": "playlists"})
        elif data_type == "events":
            events = adapter.get_events(uid)
            get_store().save_snapshot(platform, uid, "events", {
                "count": len(events),
                "items": [_dataclass_to_dict(e) for e in events],
            })
            return _result({"saved": "events"})

        return _error(f"未知类型: {data_type}", http_status=400)
    except Exception as e:
        return _error(str(e))


@bp.route("/history/tracked-users")
def tracked_users():
    """获取所有追踪过的用户列表"""
    try:
        users = get_store().get_all_tracked_users()
        return _result(users)
    except Exception as e:
        return _error(str(e))


# ==================== 报告 ====================

@bp.route("/report/overview")
def report_overview():
    """生成用户概览报告"""
    platform = request.args.get("platform", DEFAULT_PLATFORM)
    uid = request.args.get("uid", _get_uid(platform))
    if not uid:
        return _error("未指定用户 UID", http_status=400)

    try:
        report = get_report().user_overview(platform, uid)
        return _result(report)
    except Exception as e:
        return _error(str(e))


@bp.route("/report/trend")
def report_trend():
    """生成趋势报告"""
    platform = request.args.get("platform", DEFAULT_PLATFORM)
    uid = request.args.get("uid", _get_uid(platform))
    data_type = request.args.get("type", "profile")
    since = request.args.get("since", None)

    if not uid:
        return _error("未指定用户 UID", http_status=400)

    try:
        report = get_report().trend_report(platform, uid, data_type, since)
        return _result(report)
    except Exception as e:
        return _error(str(e))


@bp.route("/report/cross-platform")
def report_cross_platform():
    """跨平台汇总报告"""
    uids_param = request.args.get("uids", "")
    if not uids_param:
        return _error("请提供 uids 参数，格式: netease:5012722824,bilibili:123456", http_status=400)

    uid_map = {}
    for pair in uids_param.split(","):
        parts = pair.strip().split(":")
        if len(parts) == 2:
            uid_map[parts[0]] = parts[1]

    if not uid_map:
        return _error("无法解析 uids 参数", http_status=400)

    try:
        report = get_report().cross_platform_report(uid_map)
        return _result(report)
    except Exception as e:
        return _error(str(e))


# ==================== 统一时间线 ====================

@bp.route("/timeline")
def unified_timeline():
    """
    多平台统一活动时间线。

    参数:
      uids: 逗号分隔的 platform:uid 对，如 netease:5012722824,bilibili:3493284789881676
      limit: 每平台最多取多少条 (默认30)
      format: json | text | markdown (默认json)
      source: live(默认) 实时对比快照 | stored 从持久化时间线读取
    """
    uids_param = request.args.get("uids", "")
    limit = int(request.args.get("limit", 30))
    fmt = request.args.get("format", "json")
    source = request.args.get("source", "live")

    uid_map = {}
    if uids_param:
        for pair in uids_param.split(","):
            parts = pair.strip().split(":")
            if len(parts) == 2:
                uid_map[parts[0]] = parts[1]

    if not uid_map:
        return _error("请提供 uids 参数，如 netease:5012722824,bilibili:3493284789881676", http_status=400)

    t0 = time.perf_counter()
    try:
        # ---- 从持久化时间线读取 ----
        if source == "stored":
            all_rows = []
            for platform_id, uid in uid_map.items():
                rows = get_store().get_timeline_entries(
                    platform=platform_id, uid=uid, limit=limit
                )
                all_rows.extend(rows)

            # 按 created_at 倒序排列
            all_rows.sort(key=lambda r: (r.get("created_at", ""), r.get("timestamp", 0)), reverse=True)
            all_rows = all_rows[:limit]

            elapsed_ms = (time.perf_counter() - t0) * 1000
            uid_list = ",".join(f"{k}:{v}" for k, v in uid_map.items())
            _log_fetch("GET /timeline", "multi", uid_list, True, elapsed_ms,
                       f"{len(all_rows)} stored entries")

            if fmt == "text":
                lines = []
                for r in all_rows:
                    time_part = r.get("time_str", "") or r.get("time_suffix", "") or "----.--.--"
                    line = f"{time_part}  {r.get('summary', '')}"
                    if r.get("detail"):
                        line += f"（{r.get('detail')}）"
                    if r.get("time_suffix"):
                        line += f"  [{r.get('time_suffix')}]"
                    lines.append(line)
                return _result({"timeline": "\n".join(lines)})
            elif fmt == "markdown":
                now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
                lines = ["# 📊 多平台活动时间线（历史）", "", f"生成时间: {now}", ""]
                for r in all_rows:
                    icon = {"netease": "🎵", "bilibili": "📺", "weibo": "💬", "genshin": "⚔️"}.get(r.get("platform", ""), "📌")
                    time_part = r.get("time_str", "") or r.get("time_suffix", "") or "时间未知"
                    line = f"- **{time_part}** {icon} {r.get('summary', '')}"
                    if r.get("detail"):
                        line += f"（{r.get('detail')}）"
                    lines.append(line)
                return _result({"timeline": "\n".join(lines)})
            else:
                return _result(all_rows)

        # ---- 实时对比快照构建时间线（默认）----
        from app.services.timeline import TimelineBuilder
        entries = TimelineBuilder.build(uid_map, limit_per_platform=limit, store=get_store())

        # 持久化到数据库（自动去重）
        try:
            inserted = get_store().insert_timeline_entries(entries)
            print(f"[API /timeline] 时间线持久化: {inserted} 条新增")
        except Exception as e:
            print(f"[API /timeline] 时间线持久化失败: {e}")

        elapsed_ms = (time.perf_counter() - t0) * 1000
        uid_list = ",".join(f"{k}:{v}" for k, v in uid_map.items())
        _log_fetch("GET /timeline", "multi", uid_list, True, elapsed_ms, f"{len(entries)} entries")

        if fmt == "text":
            return _result({"timeline": TimelineBuilder.build_log_text(entries)})
        elif fmt == "markdown":
            return _result({"timeline": TimelineBuilder.build_log_markdown(entries)})
        else:
            data = []
            for e in entries:
                data.append({
                    "timestamp": e.timestamp,
                    "time_str": e.time_str,
                    "time_suffix": e.time_suffix,
                    "platform": e.platform,
                    "platform_name": e.platform_name,
                    "event_type": e.event_type,
                    "summary": e.summary,
                    "detail": e.detail,
                })
            return _result(data)
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        uid_list = ",".join(f"{k}:{v}" for k, v in uid_map.items())
        _log_fetch("GET /timeline", "multi", uid_list, False, elapsed_ms, str(e))
        return _error(str(e))


# ==================== 时间线条目增删改 ====================

@bp.route("/timeline/<int:entry_id>", methods=["PUT"])
def update_timeline_entry(entry_id):
    """更新时间线条目（summary / detail）"""
    body = request.get_json(force=True, silent=True) or {}
    summary = body.get("summary")
    detail = body.get("detail")
    if summary is None and detail is None:
        return _error("请提供 summary 或 detail 字段", http_status=400)

    try:
        ok = get_store().update_timeline_entry(entry_id, summary=summary, detail=detail)
        if ok:
            return _result({"message": "更新成功", "id": entry_id})
        else:
            return _error("条目不存在或未变更", http_status=404)
    except Exception as e:
        return _error(str(e))


@bp.route("/timeline/<int:entry_id>", methods=["DELETE"])
def delete_timeline_entry(entry_id):
    """删除时间线条目"""
    try:
        ok = get_store().delete_timeline_entry(entry_id)
        if ok:
            return _result({"message": "删除成功", "id": entry_id})
        else:
            return _error("条目不存在", http_status=404)
    except Exception as e:
        return _error(str(e))


# ==================== 采集器控制 ====================

@bp.route("/collector/status")
def collector_status():
    """获取自动采集器状态"""
    from app.services.scheduler import get_collector
    c = get_collector()
    return _result(c.status)


@bp.route("/collector/start", methods=["POST"])
def collector_start():
    """启动自动采集"""
    from app.services.scheduler import get_collector
    c = get_collector()
    body = request.get_json(force=True, silent=True) or {}
    targets = body.get("targets", {})
    interval = int(body.get("interval_minutes", 30))

    if targets:
        c.set_targets(targets)
    c.interval = interval * 60
    c.start()
    return _result({"message": "采集器已启动", "status": c.status})


@bp.route("/collector/stop", methods=["POST"])
def collector_stop():
    """停止自动采集"""
    from app.services.scheduler import get_collector
    c = get_collector()
    c.stop()
    return _result({"message": "采集器已停止", "status": c.status})


@bp.route("/collector/collect", methods=["POST"])
def collector_collect_once():
    """手动触发一次采集（需先启动采集器设置 targets）"""
    from app.services.scheduler import get_collector
    c = get_collector()
    try:
        entries = c.collect_once()
        return _result({"message": "采集完成", "entries": entries})
    except Exception as e:
        return _error(str(e))


@bp.route("/collector/logs")
def collector_logs():
    """获取采集器最近日志"""
    from app.services.scheduler import get_collector
    c = get_collector()
    limit = int(request.args.get("limit", 50))
    return _result(c.get_recent_logs(limit))


# ==================== 歌单歌曲异步拉取 ====================

@bp.route("/<platform>/fetch-songs/start", methods=["POST"])
def start_fetch_songs(platform):
    """启动后台异步拉取歌单歌曲详情"""
    uid = request.args.get("uid", _get_uid(platform))
    if not uid:
        return _error("未指定用户 UID", http_status=400)

    try:
        from app.services.playlist_fetcher import get_playlist_fetcher
        fetcher = get_playlist_fetcher()
        status = fetcher.start_fetch(platform, uid)
        return _result(status)
    except Exception as e:
        return _error(str(e))


@bp.route("/<platform>/fetch-songs/status")
def fetch_songs_status(platform):
    """查询歌单歌曲拉取进度"""
    uid = request.args.get("uid", _get_uid(platform))
    if not uid:
        return _error("未指定用户 UID", http_status=400)

    try:
        from app.services.playlist_fetcher import get_playlist_fetcher
        fetcher = get_playlist_fetcher()
        status = fetcher.get_status(platform, uid)
        return _result(status)
    except Exception as e:
        return _error(str(e))


# ==================== 旧路由兼容（无 platform 参数时默认 netease） ====================

@bp.route("/user/search")
def search_user_legacy():
    """[兼容] 搜索用户 - 默认网易云"""
    return search_user("netease")


@bp.route("/user/profile")
def user_profile_legacy():
    """[兼容] 用户资料 - 默认网易云"""
    return user_profile("netease")


@bp.route("/user/playlists")
def content_lists_legacy():
    """[兼容] 内容列表 - 默认网易云"""
    return content_lists("netease")


@bp.route("/user/playlist/<item_id>")
def content_detail_legacy(item_id):
    """[兼容] 内容详情 - 默认网易云"""
    return content_detail("netease", item_id)


@bp.route("/user/record")
def history_records_legacy():
    """[兼容] 历史排行 - 默认网易云"""
    return history_records("netease")


@bp.route("/user/events")
def user_events_legacy():
    """[兼容] 用户动态 - 默认网易云"""
    return user_events("netease")


@bp.route("/user/follows")
def user_follows_legacy():
    """[兼容] 关注 - 默认网易云"""
    return user_follows("netease")


@bp.route("/user/followeds")
def user_followeds_legacy():
    """[兼容] 粉丝 - 默认网易云"""
    return user_followers("netease")


# ==================== 辅助函数 ====================

def _dataclass_to_dict(obj) -> dict:
    """将 dataclass 对象转为字典"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for field_name in obj.__dataclass_fields__:
            value = getattr(obj, field_name)
            if hasattr(value, "__dataclass_fields__"):
                result[field_name] = _dataclass_to_dict(value)
            elif isinstance(value, list):
                result[field_name] = [
                    _dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__") else v
                    for v in value
                ]
            elif isinstance(value, dict):
                result[field_name] = {
                    k: _dataclass_to_dict(v) if hasattr(v, "__dataclass_fields__") else v
                    for k, v in value.items()
                }
            else:
                result[field_name] = value
        return result
    return obj
