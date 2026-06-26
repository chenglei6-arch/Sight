"""
QR 登录工作进程（由主进程启动，独立运行）
"""
import base64, json, os, sys, time, re
import requests as req_lib
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TMP_DIR = BASE_DIR / "tmp"
STATE_FILE = BASE_DIR / "credentials" / "yqq_playwright_state.json"
STATUS_FILE = TMP_DIR / "qr_login_status.json"
TARGET_UID = "oK6kowEAoK4z7Knioivl7evl7n**"

os.makedirs(TMP_DIR, exist_ok=True)

# 写入 PID 供主进程管理
Path(str(TMP_DIR / "qr_worker.pid")).write_text(str(os.getpid()), encoding="utf-8")

def write_status(data: dict):
    data["_ts"] = time.time()
    STATUS_FILE.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")

def main():
    write_status({"status": "starting"})

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        write_status({"status": "error", "error": "Playwright 未安装"})
        return
    except NameError as e:
        write_status({"status": "error", "error": f"Python 3.14 兼容性: {e}，请升级 anyio"})
        return

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(no_viewport=True)
            ctx.clear_cookies()
            page = ctx.new_page()

            # 导航到 y.qq.com
            page.goto("https://y.qq.com/", wait_until="networkidle", timeout=30000)
            time.sleep(4)

            # 点击登录按钮
            try:
                btn = page.query_selector("a.top_login__link")
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(4)
            except Exception:
                pass

            # 等待 graph.qq.com iframe
            try:
                qq_iframe_el = page.wait_for_selector(
                    'iframe[src*="graph.qq.com"]', timeout=15000
                )
                time.sleep(2)
            except Exception:
                write_status({"status": "error", "error": "无法打开 QQ 登录页"})
                browser.close()
                return

            # 获取 ptlogin iframe
            try:
                qq_frame = qq_iframe_el.content_frame()
                if not qq_frame:
                    raise Exception("no frame")
                ptlogin_iframe_el = qq_frame.wait_for_selector(
                    "#ptlogin_iframe", timeout=15000
                )
                time.sleep(3)
                ptlogin_frame = ptlogin_iframe_el.content_frame()
                if not ptlogin_frame:
                    raise Exception("no ptlogin frame")

                # 截图 QR 码
                qr_img = ptlogin_frame.wait_for_selector(
                    'img[src*="ptqrshow"]', timeout=10000
                )
                if qr_img:
                    qr_bytes = qr_img.screenshot()
                    with open(str(TMP_DIR / "qr_raw.png"), "wb") as f:
                        f.write(qr_bytes)
                    write_status({
                        "status": "qr_ready",
                        "qr_code": base64.b64encode(qr_bytes).decode(),
                    })
                else:
                    raise Exception("no qr img")
            except Exception as e:
                write_status({"status": "error", "error": f"QR 码获取失败: {e}"})
                browser.close()
                return

            # 等待扫码登录（最多 120 秒）
            LOGIN_COOKIES = {"qqmusic_key", "qm_keyst", "psrf_qqaccess_token", "p_skey", "skey"}

            start = time.time()
            logged_in = False
            current_url = page.url

            while time.time() - start < 120:
                # 方法1: 检查 y.qq.com 域名的登录 cookie
                cookies = ctx.cookies()
                y_cookies = {c["name"]: c.get("value", "") for c in cookies
                             if "y.qq.com" in c.get("domain", "") or "qq.com" in c.get("domain", "")}

                has_login = any(
                    c["name"] in LOGIN_COOKIES and c.get("value", "")
                    for c in cookies
                )

                if has_login:
                    elapsed = int(time.time() - start)
                    write_status({"status": "logged_in", "login_seconds": elapsed,
                                  "debug_cookies": list(y_cookies.keys())})
                    logged_in = True
                    break

                # 方法2: 检查页面是否跳转回 y.qq.com（OAuth 回调）
                try:
                    new_url = page.url
                    if "y.qq.com" in new_url and "graph.qq.com" not in new_url and "ptlogin" not in new_url:
                        if time.time() - start > 10:  # 至少 10 秒后才认为是登录跳转
                            time.sleep(3)
                            cookies = ctx.cookies()
                            has_login = any(
                                c["name"] in LOGIN_COOKIES and c.get("value", "")
                                for c in cookies
                            )
                            if has_login:
                                elapsed = int(time.time() - start)
                                write_status({"status": "logged_in", "login_seconds": elapsed,
                                              "debug_note": "detected by url redirect"})
                                logged_in = True
                                break
                except Exception:
                    pass

                # 方法3: 登录成功后 ptlogin iframe 的 QR 码会消失
                if time.time() - start > 15:
                    try:
                        if qq_iframe_el:
                            qq_frame = qq_iframe_el.content_frame()
                            if qq_frame:
                                pt_frame = qq_frame.query_selector("#ptlogin_iframe")
                                if not pt_frame or not pt_frame.is_visible():
                                    time.sleep(2)
                                    cookies = ctx.cookies()
                                    has_login = any(
                                        c["name"] in LOGIN_COOKIES and c.get("value", "")
                                        for c in cookies
                                    )
                                    if has_login:
                                        elapsed = int(time.time() - start)
                                        write_status({"status": "logged_in", "login_seconds": elapsed,
                                                      "debug_note": "detected by qr disappearance"})
                                        logged_in = True
                                        break
                    except Exception:
                        pass

                time.sleep(2)

            if not logged_in:
                write_status({"status": "error", "error": "登录超时（120 秒）"})
                browser.close()
                return

            # ═══════════════════════════════════════════════
            #  获取关注列表 — 用 Cookie 直接调后端 API
            #  不用打开任何页面，requests 直连
            # ═══════════════════════════════════════════════

            write_status({"status": "fetching"})

            follows = []
            target_uin = ""

            try:
                # 1. 从 Playwright 提取 Cookie
                p_cookies = ctx.cookies()
                cookie_dict = {}
                my_uin = ""
                for c in p_cookies:
                    name, value = c["name"], c.get("value", "")
                    cookie_dict[name] = value
                    if name == "uin":
                        my_uin = value.strip()

                # 2. 计算 g_tk
                skey = (cookie_dict.get("skey") or cookie_dict.get("p_skey")
                        or cookie_dict.get("qqmusic_key") or cookie_dict.get("qm_keyst") or "")
                g_tk = 5381
                for ch in skey:
                    g_tk += (g_tk << 5) + ord(ch)
                g_tk &= 0x7FFFFFFF

                # 3. 构建 requests session
                sess = req_lib.Session()
                for name, value in cookie_dict.items():
                    sess.cookies.set(name, value)
                sess.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
                    "Referer": "https://y.qq.com/",
                    "Origin": "https://y.qq.com",
                })

                # 辅助：解析 JSONP
                def parse_jsonp(text):
                    if not text:
                        return {}
                    m = re.search(r'^\w+\((.+)\);?\s*$', text.strip(), re.DOTALL)
                    inner = m.group(1) if m else text.strip()
                    try:
                        return json.loads(inner)
                    except json.JSONDecodeError:
                        pass
                    fixed = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)(\s*:)', r'\1"\2"\3', inner)
                    fixed = fixed.replace("'", '"')
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        return {}

                # ── 步骤 A: 搜索 Felipy ──
                search_keyword = "Felipy"
                target_uin = ""

                search_body = {
                    "comm": {"g_tk": g_tk, "uin": int(my_uin) if my_uin.isdigit() else 0,
                             "format": "json", "ct": 24, "cv": 4747474},
                    "music.search.SearchCgiService": {
                        "module": "music.search.SearchCgiService",
                        "method": "DoSearchForQQMusicDesktop",
                        "param": {
                            "query": search_keyword,
                            "search_type": 8,
                            "page_num": 1,
                            "num_per_page": 10,
                            "grp": 1,
                            "remoteplace": "sizer.newclient.user",
                        },
                    },
                }

                try:
                    sr = sess.post(
                        "https://u.y.qq.com/cgi-bin/musicu.fcg",
                        json=search_body, timeout=15,
                    )
                    if sr.status_code == 200:
                        search_data = sr.json()
                        svc = search_data.get("music.search.SearchCgiService", {})
                        svc_body = svc.get("data", {}).get("body", {})
                        user_raw = svc_body.get("user", {})
                        if isinstance(user_raw, dict):
                            user_list = user_raw.get("list", [])
                        elif isinstance(user_raw, list):
                            user_list = user_raw
                        else:
                            user_list = []
                        for u in user_list:
                            raw_uin = str(u.get("uin") or "")
                            if raw_uin.isdigit():
                                target_uin = raw_uin
                                break
                            encrypt_uin = str(u.get("encrypt_uin") or "")
                            if encrypt_uin:
                                target_uin = encrypt_uin
                        if not target_uin:
                            # 没搜到，尝试直接用 TARGET_UID
                            if TARGET_UID.replace("*", "").isdigit():
                                target_uin = TARGET_UID.replace("*", "")
                except Exception as e:
                    (TMP_DIR / "qr_search_error.log").write_text(str(e), encoding="utf-8")
                    # fallback: 用 TARGET_UID 试试
                    if TARGET_UID.replace("*", "").isdigit():
                        target_uin = TARGET_UID.replace("*", "")

                # ── 步骤 B: 获取关注列表 ──
                if target_uin:
                    try:
                        params = {
                            "utf8": 1, "start": 0, "num": 40,
                            "uin": target_uin, "format": "json",
                            "g_tk": g_tk,
                        }
                        fr = sess.get(
                            "https://c.y.qq.com/splcloud/fcgi-bin/friend_follow_or_listen_list.fcg",
                            params=params, timeout=15,
                        )
                        if fr.status_code == 200:
                            flist = parse_jsonp(fr.text)
                            if flist.get("code") == 0:
                                for item in flist.get("list", []):
                                    nick = str(item.get("nick_name") or item.get("nick") or "")
                                    uin_val = str(item.get("uin") or "")
                                    avatar = str(item.get("logo") or item.get("avatarUrl") or "")
                                    if nick or uin_val:
                                        follows.append({
                                            "nickname": nick or uin_val,
                                            "avatarUrl": avatar,
                                            "signature": "",
                                        })
                    except Exception as e:
                        (TMP_DIR / "qr_follow_error.log").write_text(str(e), encoding="utf-8")
                else:
                    # 没有目标用户的 UIN
                    pass

            except Exception as e:
                import traceback
                (TMP_DIR / "qr_fetch_error.log").write_text(
                    f"{type(e).__name__}: {e}\n{traceback.format_exc()}", encoding="utf-8"
                )

            # 清理 — 关闭浏览器
            try:
                browser.close()
            except Exception:
                pass

            write_status({
                "status": "done",
                "follow_data": {
                    "uid": TARGET_UID,
                    "found_uin": target_uin,
                    "count": len(follows),
                    "follows": follows[:50],
                },
            })

    except Exception as e:
        import traceback
        write_status({"status": "error", "error": f"{type(e).__name__}: {e}"})
        try:
            (TMP_DIR / "qr_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass

if __name__ == "__main__":
    main()
