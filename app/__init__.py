"""
多平台用户数据监控面板
Flask 应用工厂
"""
import os
import sys
import io

# 修复 Windows 终端 GBK 编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from flask import Flask


def create_app() -> Flask:
    """创建并配置 Flask 应用"""
    # 迁移旧 cookie → 新 credentials 目录
    from app.credentials import _migrate_legacy_cookie
    _migrate_legacy_cookie()

    app = Flask(
        __name__,
        static_folder="web",      # Vite 构建产物目录（frontend/ 执行 npm run build 生成）
        static_url_path="",       # 静态资源挂根路径：/assets/...、/favicon.svg
    )
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

    # 镜像 stdout/stderr 到内存日志中枢（前端终端面板的数据源）
    from app.services.log_hub import install_tee
    install_tee()

    # 注册路由
    from app.routes.api import bp as api_bp
    from app.routes.views import bp as views_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)

    return app
