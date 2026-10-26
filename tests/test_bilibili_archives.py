"""Contract / failure tests use synthetic records and never access upstreams."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import requests
from flask import Flask

from app.services.bilibili_archives import BilibiliArchives, SOURCES


def reply_payload():
    return {"code": 0, "data": {
        "cursor": {"is_end": False, "all_count": 2},
        "replies": [{"rpid": "12", "message": "测试评论", "time": 1700000000,
                     "dyn": {"oid": "123", "type": 1}}],
    }}


def live_payload():
    return {"code": 200, "data": {
        "total": 1, "hasMore": False,
        "data": {"records": [{
            "channel": {"roomId": 42, "uName": "示例主播"},
            "live": {"liveId": "sample", "title": "示例直播"},
            "danmakus": [
                {"uId": 123, "type": 0, "sendDate": 1700000000000, "message": "测试弹幕"},
                {"uId": 123, "type": 9, "sendDate": 1700000001000},
            ],
        }]},
    }}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.service = BilibiliArchives()
        self.interval = patch("app.services.bilibili_archives.MIN_INTERVAL", 0)
        self.interval.start()
        self.addCleanup(self.interval.stop)
        self.gets = {}
        for name, provider in self.service._providers.items():
            self.addCleanup(provider.session.close)
            self.gets[name] = Mock(return_value=Mock(status_code=200, headers={}, json=Mock(return_value=reply_payload())))
            provider.session.get = self.gets[name]

    def respond(self, provider, payload, status=200, headers=None):
        self.gets[provider].return_value = Mock(status_code=status, headers=headers or {},
                                               json=Mock(return_value=payload))

    def test_aicu_mapping_cache_and_isolated_cookies(self):
        result = self.service.fetch("aicu_reply", "00123")
        event = result["events"][0]
        self.assertEqual(result["uid"], "123")
        self.assertEqual(event["timestamp"], 1700000000000)
        self.assertEqual(event["url"], "https://www.bilibili.com/video/av123#reply12")
        self.assertTrue(result["has_more"])
        self.assertFalse(result["cached"])
        result["events"].clear()
        again = self.service.fetch("aicu_reply", "123")
        self.assertTrue(again["cached"])
        self.assertEqual(len(again["events"]), 1)
        self.assertEqual(self.gets["aicu"].call_count, 1)
        self.assertEqual(dict(self.service._providers["aicu"].session.cookies), {})
        kwargs = self.gets["aicu"].call_args.kwargs
        self.assertEqual(kwargs["params"]["mode"], 0)
        self.assertEqual(kwargs["params"]["pn"], 1)
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn("cookies", kwargs)

    def test_video_danmaku_mapping_and_nonvideo_comment_link(self):
        self.respond("aicu", {"code": 0, "data": {
            "cursor": {"is_end": True, "all_count": 1},
            "videodmlist": [{"id": "dm1", "content": "视频弹幕", "ctime": 1700000000,
                              "oid": "789", "cid": "100", "progress": 5000}],
        }})
        event = self.service.fetch("aicu_danmaku", "123")["events"][0]
        self.assertEqual(event["event_id"], "aicu_danmaku:dm1")
        self.assertEqual(event["extra"]["progress"], 5000)
        self.assertEqual(event["url"], "https://www.bilibili.com/video/av789")
        payload = reply_payload()
        payload["data"]["replies"][0]["dyn"]["type"] = 11
        self.respond("aicu", payload)
        event = self.service.fetch("aicu_reply", "123")["events"][0]
        self.assertTrue(event["url"].startswith("https://www.aicu.cc/reply"))

    def test_danmakus_pagination_units_and_unknown_interaction(self):
        payload = live_payload()
        payload["data"]["data"]["records"][0]["danmakus"].append(
            payload["data"]["data"]["records"][0]["danmakus"][0].copy())
        self.respond("danmakus", payload)
        result = self.service.fetch("danmakus", "123", page=2, page_size=5)
        self.assertEqual(result["total_unit"], "直播场次")
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["events"][0]["event_type"], "直播互动")
        self.assertIn("上游类型 9", result["events"][0]["content"])
        self.assertEqual(result["events"][0]["timestamp"], 1700000001000)
        self.assertEqual(self.gets["danmakus"].call_args.kwargs["params"]["pageNum"], 1)

    def test_danmakus_default_first_page_maps_to_upstream_zero(self):
        self.respond("danmakus", live_payload())
        result = self.service.fetch("danmakus", "123")
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 20)
        params = self.gets["danmakus"].call_args.kwargs["params"]
        self.assertEqual(params["pageNum"], 0)
        self.assertEqual(params["pageSize"], 20)

    def test_danmakus_rejects_other_senders(self):
        payload = live_payload()
        payload["data"]["data"]["records"][0]["danmakus"][0]["uId"] = 456
        self.respond("danmakus", payload)
        with self.assertRaisesRegex(RuntimeError, "不匹配"):
            self.service.fetch("danmakus", "123")

    def test_empty_and_changed_schema_are_distinct(self):
        self.respond("danmakus", {"code": 200, "data": {"total": 0, "hasMore": False}})
        self.assertEqual(self.service.fetch("danmakus", "123")["events"], [])
        for data in [None, {}, {"cursor": {"is_end": True}}]:
            with self.subTest(data=data):
                self.respond("aicu", {"code": 0, "data": data})
                with self.assertRaisesRegex(RuntimeError, "结构已变化"):
                    self.service.fetch("aicu_reply", "123")

    def test_business_errors_are_not_cached_or_empty_successes(self):
        self.respond("aicu", {"code": -403, "data": None, "message": "需要验证"})
        with self.assertRaisesRegex(RuntimeError, "code=-403"):
            self.service.fetch("aicu_reply", "123")
        self.respond("aicu", reply_payload())
        self.assertEqual(len(self.service.fetch("aicu_reply", "123")["events"]), 1)
        self.assertEqual(self.gets["aicu"].call_count, 2)

    def test_http_rate_limit_stops_requests_for_both_aicu_sources(self):
        self.respond("aicu", {}, status=429, headers={"Retry-After": "90"})
        with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
            self.service.fetch("aicu_reply", "123")
        with self.assertRaisesRegex(RuntimeError, "冷却"):
            self.service.fetch("aicu_danmaku", "123")
        self.assertEqual(self.gets["aicu"].call_count, 1)

    def test_non_json_and_network_errors_are_explicit(self):
        self.gets["aicu"].return_value.json.side_effect = ValueError("html")
        with self.assertRaisesRegex(RuntimeError, "未返回 JSON"):
            self.service.fetch("aicu_reply", "123")
        self.gets["aicu"].side_effect = requests.Timeout("timeout")
        with self.assertRaisesRegex(RuntimeError, "网络请求失败"):
            self.service.fetch("aicu_reply", "123")

    def test_invalid_requests_never_reach_upstream(self):
        for uid in ["0", "-1", "abc", "１", "1/../2", "1" * 21]:
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                self.service.fetch("aicu_reply", uid)
        for kwargs in [{"page": 0}, {"page": 1001}, {"page_size": 51}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.service.fetch("aicu_reply", "123", **kwargs)
        with self.assertRaises(ValueError):
            self.service.fetch("https://example.com", "123")
        self.gets["aicu"].assert_not_called()

    def test_simultaneous_cache_misses_share_one_request(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.service.fetch("aicu_reply", "123"), range(4)))
        self.assertEqual(self.gets["aicu"].call_count, 1)
        self.assertEqual(sum(result["cached"] for result in results), 3)

    def test_large_live_page_is_explicitly_truncated(self):
        self.respond("danmakus", live_payload())
        with patch("app.services.bilibili_archives.MAX_EVENTS", 1):
            result = self.service.fetch("danmakus", "123")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["events"]), 1)


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.routes.api import bp
        app = Flask(__name__)
        app.register_blueprint(bp)
        cls.client = app.test_client()

    def test_validation_and_upstream_failure_http_status(self):
        response = self.client.get("/api/bilibili/archives?uid=123&page=abc")
        self.assertEqual(response.status_code, 400)
        response = self.client.get("/api/bilibili/archives?uid=0")
        self.assertEqual(response.status_code, 400)
        with patch("app.services.bilibili_archives.archives.fetch", side_effect=RuntimeError("上游故障")):
            response = self.client.get("/api/bilibili/archives?uid=123")
        self.assertEqual(response.status_code, 502)
        self.assertIn("上游故障", response.json["message"])

    def test_all_sources_route_to_the_archive_service(self):
        for source in SOURCES:
            with self.subTest(source=source), patch("app.services.bilibili_archives.archives.fetch", return_value={"events": []}) as fetch:
                response = self.client.get(f"/api/bilibili/archives?uid=123&source={source}&page=2&page_size=5")
                self.assertEqual(response.json["code"], 200)
                fetch.assert_called_once_with(source, "123", 2, 5)


if __name__ == "__main__":
    unittest.main()
