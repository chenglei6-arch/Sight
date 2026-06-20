"""
HTTP 客户端 + Session 管理

负责：
- Cookie 加载与维护
- 请求频率控制（反爬）
- 自动重试
- 浏览器指纹伪装
"""
import time

import requests

from app.config import (
    REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
)
from app.credentials import CredentialManager


class NeteaseClient:
    """网易云音乐 HTTP 客户端"""

    def __init__(self, credentials: dict = None):
        self._session: requests.Session | None = None
        self._last_request_at = 0.0
        self._csrf = ""
        self._custom_credentials = credentials  # 允许注入自定义凭证

    # ==================== Session ====================

    @property
    def session(self) -> requests.Session:
        """延迟初始化 session"""
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def _build_session(self) -> requests.Session:
        """创建带 Cookie 和伪装头的 Session"""
        s = requests.Session()

        # 加载 Cookie
        cookies = self._load_cookies()
        for key, value in cookies.items():
            s.cookies.set(key, value)
            if key == "__csrf":
                self._csrf = value

        # 浏览器伪装头
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://music.163.com/",
            "Origin": "https://music.163.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        return s

    @staticmethod
    def _load_cookies() -> dict:
        """从凭证管理器加载 Cookie"""
        return CredentialManager.load_cookies("netease")

    # ==================== 请求控制 ====================

    def _rate_limit(self):
        """请求频率控制"""
        now = time.time()
        elapsed = now - self._last_request_at
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        self._last_request_at = time.time()

    def _post(self, url: str, data: dict, extra_headers: dict = None) -> dict:
        """带重试的 POST 请求"""
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.post(
                    url, data=data, timeout=REQUEST_TIMEOUT, headers=headers
                )
                result = resp.json()
                if result.get("code") == 200:
                    return result
                # 非 200 也返回，让上层处理
                return result
            except requests.RequestException as e:
                print(f"[HTTP] 请求失败 (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5)
        return {"code": -1, "message": "网络请求失败"}

    def _get(self, url: str, params: dict = None) -> dict:
        """带重试的 GET 请求"""
        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                resp = self.session.get(
                    url, params=params, timeout=REQUEST_TIMEOUT
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"code": resp.status_code, "message": resp.text[:200]}
            except requests.RequestException as e:
                print(f"[HTTP] GET 失败 (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5)
        return {"code": -1, "message": "网络请求失败"}

    # ==================== 公开方法 ====================

    def weapi_post(self, endpoint: str, data: dict) -> dict:
        """
        发送 weapi POST 请求（自动加密）

        Args:
            endpoint: API 路径，如 /weapi/v1/user/detail/xxx
            data: 请求体数据（明文，自动加密）

        Returns:
            API 响应 JSON
        """
        from app.platforms.netease.crypto import encrypt_request

        encrypted = encrypt_request(data)
        return self._post(
            f"https://music.163.com{endpoint}",
            {
                "params": encrypted["params"],
                "encSecKey": encrypted["encSecKey"],
                "csrf_token": self._csrf,
            },
        )

    def api_get(self, endpoint: str, params: dict = None) -> dict:
        """发送普通 GET 请求"""
        return self._get(f"https://music.163.com{endpoint}", params)

    def get_csrf(self) -> str:
        """获取当前 CSRF token"""
        return self._csrf

    def get_cookie_value(self, name: str) -> str:
        """获取指定 Cookie 值"""
        for cookie in self.session.cookies:
            if cookie.name == name:
                return cookie.value
        return ""
