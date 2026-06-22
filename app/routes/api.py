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

管理:
  /api/platforms                   列出所有平台
  /api/credentials                 查看/更新凭证
"""
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, request

from app.platforms import get_adapter, list_platforms
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

        # 用户资料：优先快照，失败时实时获取
        result["profile"] = None
        try:
            snap_profile = get_store().get_latest_snapshot(platform, uid, "profile")
            if snap_profile:
                result["profile"] = snap_profile
            else:
                profile = adapter.get_profile(uid)
                if profile:
                    profile_dict = _dataclass_to_dict(profile)
                    result["profile"] = profile_dict
                    get_store().save_snapshot(platform, uid, "profile", profile_dict)
        except Exception as e:
            errors.append(f"profile: {e}")

        # 内容列表：优先快照，失败时实时获取 + 写入快照
        result["playlists"] = []
        try:
            all_pl_snaps = get_store().get_snapshots(platform, uid, "playlists", limit=3)
            snap_pl = None
            for s in all_pl_snaps:
                if s.get("items"):
                    snap_pl = s
                    break
            if snap_pl and snap_pl.get("items"):
                result["playlists"] = snap_pl["items"]
                print(f"[{platform}] /all playlists 命中快照: {len(result['playlists'])} 项")
            else:
                items = adapter.get_content_lists(uid)
                item_dicts = [_dataclass_to_dict(i) for i in items]
                result["playlists"] = item_dicts
                if item_dicts:
                    get_store().save_snapshot(platform, uid, "playlists", {
                        "count": len(item_dicts), "items": item_dicts,
                    })
                    print(f"[{platform}] /all playlists 实时拉取并保存: {len(item_dicts)} 项")
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
            all_ev_snaps = get_store().get_snapshots(platform, uid, "events", limit=3)
            snap_ev = None
            for s in all_ev_snaps:
                if s.get("items"):
                    snap_ev = s
                    break
            if snap_ev and snap_ev.get("items"):
                result["events"] = snap_ev["items"]
                print(f"[{platform}] /all events 命中快照: {len(result['events'])} 条")
            else:
                events = adapter.get_events(uid)
                event_dicts = [_dataclass_to_dict(e) for e in events]
                result["events"] = event_dicts
                if event_dicts:
                    get_store().save_snapshot(platform, uid, "events", {
                        "count": len(event_dicts), "items": event_dicts,
                    })
                    print(f"[{platform}] /all events 实时拉取并保存: {len(event_dicts)} 条")
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

        # profile 完全为空且无快照兜底时返回错误
        if result["profile"] is None and not result["playlists"] and not result["events"]:
            detail = "all_failed: " + "; ".join(errors)
            _log_fetch("GET /all", platform, uid, False, elapsed_ms, detail)
            return _error("所有数据模块均加载失败: " + "; ".join(errors))

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
                    icon = {"netease": "🎵", "bilibili": "📺"}.get(r.get("platform", ""), "📌")
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
