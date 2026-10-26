"""On-demand public Aicu / Danmakus archives, with isolated HTTP sessions."""
import copy
import hashlib
import json
import re
import threading
import time
from collections import OrderedDict

import requests

from app.config import REQUEST_TIMEOUT
from app.platforms.base import EventItem, dataclass_to_dict


SOURCES = {
    "aicu_reply": ("Aicu · 评论", "aicu", "/api/v3/search/getreply"),
    "aicu_danmaku": ("Aicu · 视频弹幕", "aicu", "/api/v3/search/getvideodm"),
    "danmakus": ("Danmakus · 直播弹幕与互动", "danmakus", "/api/v2/user"),
}
ORIGINS = {"aicu": "https://api.aicu.cc", "danmakus": "https://api.danmakus.com"}
NOTICE = "第三方存档可能延迟、缺失或已失效；查询不到不代表没有相关活动。"
CACHE_TTL = 5 * 60
MIN_INTERVAL = 2.0
MAX_EVENTS = 500


def _object(value, label):
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} 响应结构已变化：预期对象")
    return value


def _rows(value, label):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RuntimeError(f"{label} 响应结构已变化：预期记录列表")
    return value


def _number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _timestamp(value):
    stamp = _number(value)
    return stamp * 1000 if 0 < stamp < 100_000_000_000 else max(0, stamp)


def _identity(source, row, context=""):
    raw = json.dumps([source, context, row], ensure_ascii=False, sort_keys=True)
    return f"{source}:{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _aicu_page(source, uid, data):
    label = SOURCES[source][0]
    cursor = _object(data.get("cursor"), label)
    if not isinstance(cursor.get("is_end"), bool):
        raise RuntimeError(f"{label} 响应结构已变化：缺少分页游标")
    is_reply = source == "aicu_reply"
    rows = _rows(data.get("replies" if is_reply else "videodmlist"), label)
    source_url = f"https://www.aicu.cc/{'reply' if is_reply else 'videodanmu'}?uid={uid}"
    events = []
    for row in rows:
        dyn = row.get("dyn") or {}
        if not isinstance(dyn, dict):
            raise RuntimeError(f"{label} 响应结构已变化：dyn")
        oid = str(dyn.get("oid", "") if is_reply else row.get("oid", ""))
        record_id = str(row.get("rpid" if is_reply else "id") or "")
        url = source_url
        if oid.isascii() and oid.isdigit() and (not is_reply or dyn.get("type") == 1):
            url = f"https://www.bilibili.com/video/av{oid}"
            if is_reply and record_id.isascii() and record_id.isdigit():
                url += f"#reply{record_id}"
        events.append(EventItem(
            event_id=f"{source}:{record_id}" if record_id else _identity(source, row, uid),
            event_type="评论" if is_reply else "视频弹幕",
            content=str(row.get("message" if is_reply else "content") or ""),
            timestamp=_timestamp(row.get("time" if is_reply else "ctime")),
            url=url,
            extra={"source": "aicu", "source_url": source_url, "archived": True,
                   "oid": oid, "progress": row.get("progress")},
        ))
    return events, not cursor["is_end"], _number(cursor.get("all_count"), -1), source_url


def _danmakus_page(uid, data):
    label = SOURCES["danmakus"][0]
    if not isinstance(data.get("hasMore"), bool):
        raise RuntimeError(f"{label} 响应结构已变化：缺少分页游标")
    nested = data.get("data")
    # An empty result can omit `data`; require explicit empty-page metadata.
    if nested is None and data.get("total") == 0 and not data["hasMore"]:
        records = []
    else:
        records = _rows(_object(nested, label).get("records"), label)
    source_url = f"https://danmakus.com/user/{uid}"
    events = []
    for record in records:
        channel = _object(record.get("channel"), label)
        live = _object(record.get("live"), label)
        for message in _rows(record.get("danmakus"), label):
            if str(message.get("uId")) != uid:
                raise RuntimeError(f"{label} 返回了不匹配的用户 ID")
            text = str(message.get("message") or "")
            events.append(EventItem(
                event_id=_identity("danmakus", message, str(live.get("liveId", ""))),
                event_type="直播弹幕" if text else "直播互动",
                content=text or f"直播互动（上游类型 {message.get('type', '未知')}）",
                timestamp=_timestamp(message.get("sendDate")),
                media_title=str(live.get("title") or ""),
                media_artist=str(channel.get("uName") or ""),
                url=source_url,
                extra={"source": "danmakus", "source_url": source_url, "archived": True,
                       "room_id": channel.get("roomId"), "live_id": live.get("liveId"),
                       "message_type": message.get("type")},
            ))
    return events, data["hasMore"], _number(data.get("total"), -1), source_url


class _Provider:
    def __init__(self):
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Sight/1.0 (public archive reader)",
                                     "Accept": "application/json"})
        self.last_request = None
        self.cooldown_until = 0.0


class BilibiliArchives:
    def __init__(self):
        self._providers = {name: _Provider() for name in ORIGINS}
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()

    def fetch(self, source, uid, page=1, page_size=20):
        if source not in SOURCES:
            raise ValueError("未知存档来源")
        if not isinstance(uid, str) or not re.fullmatch(r"[0-9]{1,20}", uid) or int(uid) <= 0:
            raise ValueError("请提供有效的 B 站数字 UID")
        uid = str(int(uid))
        if type(page) is not int or not 1 <= page <= 1000:
            raise ValueError("page 必须在 1~1000 之间")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise ValueError("page_size 必须在 1~50 之间")
        key = (source, uid, page, page_size)
        label, provider_name, path = SOURCES[source]
        provider = self._providers[provider_name]
        # One lock per upstream coalesces concurrent misses and shares the
        # rate limit across Aicu endpoints and all local Bilibili accounts.
        with provider.lock:
            with self._cache_lock:
                cached = self._cache.get(key)
                if cached and time.monotonic() - cached[0] < CACHE_TTL:
                    self._cache.move_to_end(key)
                    return {**copy.deepcopy(cached[1]), "cached": True}
            if provider.cooldown_until > time.monotonic():
                raise RuntimeError(f"[{label}] 上游限流冷却中，请稍后重试")
            if provider.last_request is not None:
                time.sleep(max(0, MIN_INTERVAL - (time.monotonic() - provider.last_request)))
            params = ({"uid": uid, "pn": page, "ps": page_size} if provider_name == "aicu"
                      # Danmakus pages start at zero; Sight / Aicu start at one.
                      else {"uId": uid, "pageNum": page - 1, "pageSize": page_size,
                            "target": -1, "useEmoji": "true"})
            if source == "aicu_reply":
                params["mode"] = 0
            provider.last_request = time.monotonic()
            try:
                response = provider.session.get(ORIGINS[provider_name] + path, params=params,
                                                timeout=REQUEST_TIMEOUT, allow_redirects=False)
                if response.status_code == 429:
                    delay = min(300, max(30, _number(response.headers.get("Retry-After"), 60)))
                    provider.cooldown_until = time.monotonic() + delay
                    raise RuntimeError(f"[{label}] HTTP 429，上游限流，请 {delay} 秒后重试")
                if response.status_code != 200:
                    raise RuntimeError(f"[{label}] HTTP {response.status_code}，上游请求失败")
                payload = _object(response.json(), f"[{label}]")
            except ValueError as exc:
                raise RuntimeError(f"[{label}] 上游未返回 JSON，可能需要登录或验证") from exc
            except requests.RequestException as exc:
                raise RuntimeError(f"[{label}] 网络请求失败（{type(exc).__name__}）") from exc
            expected_code = 0 if provider_name == "aicu" else 200
            if type(payload.get("code")) is not int or payload["code"] != expected_code:
                code = payload.get("code")
                if code in (429, -799):
                    provider.cooldown_until = time.monotonic() + 60
                message = str(payload.get("message") or payload.get("msg") or "请求失败")[:200]
                raise RuntimeError(f"[{label}] {message} (code={code})")
            data = _object(payload.get("data"), f"[{label}]")
            events, has_more, total, source_url = (
                _aicu_page(source, uid, data) if provider_name == "aicu"
                else _danmakus_page(uid, data)
            )
            unique = {event.event_id: event for event in events}
            ordered = sorted(unique.values(), key=lambda event: event.timestamp, reverse=True)
            result = {
                "source": source, "source_name": label, "source_url": source_url,
                "uid": uid, "page": page, "page_size": page_size,
                "total": total, "total_unit": "直播场次" if source == "danmakus" else "条",
                "has_more": has_more and page < 1000, "truncated": len(ordered) > MAX_EVENTS,
                "events": [dataclass_to_dict(event) for event in ordered[:MAX_EVENTS]],
                "fetched_at": int(time.time() * 1000), "cached": False, "notice": NOTICE,
            }
            with self._cache_lock:
                self._cache[key] = (time.monotonic(), copy.deepcopy(result))
                self._cache.move_to_end(key)
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
            return result


archives = BilibiliArchives()
