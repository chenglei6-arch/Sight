"""
页面路由

前端为 frontend/ 下的 Vite + Vue 3 工程，构建产物输出到 app/web/，
由 Flask 直接托管（无需 Node 即可运行后端）。
"""
from flask import Blueprint, current_app, send_from_directory

bp = Blueprint("views", __name__)


@bp.route("/")
def index():
    """主面板页面（app/web/index.html）"""
    return send_from_directory(current_app.static_folder, "index.html")
