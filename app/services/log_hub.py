"""
进程内日志中枢 —— 环形缓冲 + stdout/stderr 镜像。

- _Tee 接管 sys.stdout / sys.stderr：原样写回真实终端（控制台行为不变），
  同时按行写入环形缓冲，供前端 /api/logs/recent 与 /api/logs/stream(SSE) 读取。
- 安装时机在 create_app() 内，晚于 app/__init__.py 的 UTF-8 包装；
  debug 重载器派生的子进程同样会走 create_app()，无需额外处理。
- werkzeug 的访问日志在导入期就持有了原始 stderr 句柄，不会经过 Tee，
  终端里因此只保留业务日志，正好过滤掉了最嘈杂的请求行。
"""
import os
import sys
import threading
from collections import deque
from datetime import datetime

MAX_ENTRIES = 1000

# 进程标识：前端据此检测后端重启（seq 会归零，需清空重同步）
BOOT_ID = os.urandom(4).hex()

# 级别推断用的关键字（按优先级匹配）
_ERROR_KEYWORDS = ("FAIL", "失败", "错误", "异常", "Exception", "Traceback", "ERROR")
_WARN_KEYWORDS = ("熔断", "重试", "警告", "WARN", "频率限制", "未登录", "回退", "未通过验证", "过期")

# 自身轮询产生的访问日志不过进终端（会把日志流刷屏）
_NOISE_PATTERNS = (
    'GET /api/graph/expand/status',
    'GET /api/logs/recent',
    'GET /api/logs/stream',
)


def _infer_level(text: str) -> str:
    """从一行 print 文本粗略推断日志级别"""
    if any(k in text for k in _ERROR_KEYWORDS):
        return "error"
    if any(k in text for k in _WARN_KEYWORDS):
        return "warn"
    return "info"


class LogHub:
    """线程安全的日志环形缓冲，自增 seq 供增量拉取与 SSE 续传去重"""

    def __init__(self, maxlen: int = MAX_ENTRIES):
        self._buf: deque = deque(maxlen=maxlen)
        self._cond = threading.Condition()
        self._seq = 0

    def publish(self, text: str, level: str = "info", source: str = "console") -> dict:
        now = datetime.now()
        with self._cond:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": now.strftime("%m-%d %H:%M:%S"),
                "level": level,
                "source": source,
                "text": text.rstrip(),
                "boot": BOOT_ID,
            }
            self._buf.append(entry)
            self._cond.notify_all()
        return entry

    def since(self, after_seq: int) -> list:
        with self._cond:
            return [e for e in self._buf if e["seq"] > after_seq]

    def wait_since(self, after_seq: int, timeout: float = 15.0) -> list:
        """阻塞等待新日志；超时返回空列表（SSE 用它发 keepalive）"""
        with self._cond:
            if not self._cond.wait(timeout):
                return []
            return [e for e in self._buf if e["seq"] > after_seq]


class _Tee:
    """把写入同时镜像到 LogHub 的行缓冲代理（代理其余属性到原始流）"""

    def __init__(self, original, hub: LogHub, source: str):
        self._original = original
        self._hub = hub
        self._source = source
        self._lock = threading.Lock()
        self._pending = ""

    def write(self, s):
        try:
            self._original.write(s)
            self._original.flush()
        except Exception:
            pass
        with self._lock:
            self._pending += s
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                stripped = line.strip()
                if not stripped:
                    continue
                if self._source == "stderr" and any(k in stripped for k in _NOISE_PATTERNS):
                    continue
                self._hub.publish(stripped, level=_infer_level(stripped), source=self._source)
        return len(s)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._original, name)


_hub: LogHub | None = None
_hub_lock = threading.Lock()


def get_log_hub() -> LogHub:
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = LogHub()
        return _hub


def install_tee():
    """接管 sys.stdout / sys.stderr（幂等；重复调用直接返回）"""
    if getattr(sys, "_sight_log_tee_installed", False):
        return
    sys._sight_log_tee_installed = True
    hub = get_log_hub()
    sys.stdout = _Tee(sys.stdout, hub, "console")
    sys.stderr = _Tee(sys.stderr, hub, "stderr")
