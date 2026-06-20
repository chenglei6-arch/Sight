"""
应用配置
"""
import os

# ==================== 路径 ====================
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_FILE = os.path.join(ROOT_DIR, "cookie.txt")

# ==================== 目标用户配置 ====================
# 默认监控的平台
DEFAULT_PLATFORM = "netease"

# 默认监控的用户 UID（空字符串 = 使用 cookie 对应的登录用户）
DEFAULT_TARGET_UID = ""

# ==================== 请求控制 ====================
REQUEST_INTERVAL = 0.8   # 请求间隔（秒），防反爬
REQUEST_TIMEOUT = 15      # 请求超时（秒）
MAX_RETRIES = 3           # 失败重试次数

# ==================== 服务器 ====================
FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
FLASK_DEBUG = True
