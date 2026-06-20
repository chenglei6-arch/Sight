"""
页面路由
"""
from flask import Blueprint, render_template

bp = Blueprint("views", __name__)


@bp.route("/")
def index():
    """主面板页面"""
    return render_template("index.html")
