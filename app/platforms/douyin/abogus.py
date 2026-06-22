"""
抖音 a_bogus 签名 — 基于 PyExecJS + douyin_sign.js

参考 cv-cat/DouYin_Spider 的实现接口:
  generate_a_bogus(query_str, data_str="")
    - query_str: URL 查询参数字符串 (已 URL 编码)
    - data_str: POST body 字符串 (GET 请求为空)

注意:
  - 默认使用 douyin_sign.js (自包含 SM3, 无需 npm)
  - 备选: 若存在 dy_ab.js (需 jsrsasign), 优先使用
"""
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

subprocess.Popen = partial(subprocess.Popen, encoding="utf-8")
import execjs

_JS_DIR = Path(__file__).parent
_CTX = None
_CTX_AB = None  # dy_ab.js 上下文


def _get_ctx():
    """加载 douyin_sign.js (自包含, 无需 npm)"""
    global _CTX
    if _CTX is None:
        js_file = _JS_DIR / "douyin_sign.js"
        if js_file.exists():
            _CTX = execjs.compile(js_file.read_text("utf-8"))
    return _CTX


def _get_ab_ctx():
    """加载 dy_ab.js (优先, 需 jsrsasign)"""
    global _CTX_AB
    if _CTX_AB is None:
        js_file = _JS_DIR / "dy_ab.js"
        if js_file.exists():
            try:
                _CTX_AB = execjs.compile(js_file.read_text("utf-8"))
            except Exception as e:
                print(f"[a_bogus] dy_ab.js 加载失败: {e}")
    return _CTX_AB


def generate_a_bogus(query_str: str, data_str: str = "", user_agent: str = "") -> str:
    """
    生成 a_bogus 签名

    接口匹配 cv-cat/DouYin_Spider:
      generate_a_bogus(query, data)

    Args:
        query_str: URL 查询参数字符串 (如 "keyword=test&count=10")
        data_str: POST body (GET 请求为空字符串)
        user_agent: User-Agent (douyin_sign.js 需要)

    Returns:
        a_bogus 签名字符串, 失败返回 ""
    """
    # 优先使用 dy_ab.js (参考项目)
    ctx_ab = _get_ab_ctx()
    if ctx_ab:
        try:
            result = ctx_ab.call("get_ab", query_str, data_str)
            return result or ""
        except Exception as e:
            print(f"[a_bogus] dy_ab.js 调用失败: {e}")

    # 兜底: douyin_sign.js
    ctx = _get_ctx()
    if ctx:
        try:
            result = ctx.call("sign_datail", query_str, user_agent or _DEFAULT_UA)
            return result or ""
        except Exception as e:
            print(f"[a_bogus] douyin_sign.js 调用失败: {e}")

    return ""


def generate_a_bogus_url(full_url: str, user_agent: str = "") -> str:
    """从完整 URL 生成 a_bogus (兼容旧接口)"""
    query_str = full_url.split("?", 1)[1] if "?" in full_url else ""
    return generate_a_bogus(query_str, "", user_agent)


_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
    "Gecko/20100101 Firefox/117.0"
)
