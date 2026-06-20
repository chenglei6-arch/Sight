"""
多平台用户数据监控面板 - 启动入口

支持平台: 网易云音乐, 哔哩哔哩 (更多平台持续接入中)

用法:
    python run.py
    然后访问 http://127.0.0.1:5000
"""
from app import create_app
from app.config import (
    FLASK_HOST,
    FLASK_PORT,
    FLASK_DEBUG,
    DEFAULT_PLATFORM,
    DEFAULT_TARGET_UID,
)
from app.platforms import get_adapter, list_platforms
from app.credentials import CredentialManager


def main():
    """启动前检查 + 启动服务器"""
    print("=" * 58)
    print("  📊  多平台用户数据监控面板")
    print("=" * 58)

    # ---- 检查各平台连接 ----
    platforms = CredentialManager.get_available_platforms()
    for p in platforms:
        pid = p["id"]
        if p["has_credential"]:
            try:
                adapter = get_adapter(pid)
                if adapter and adapter.check_alive():
                    login = adapter.get_login_user()
                    if login:
                        print(f"  ✓ {p['name']}: {login.get('nickname', login.get('uid', '?'))} (UID: {login.get('uid', '?')})")
                    else:
                        print(f"  ✓ {p['name']}: 已连接")
                else:
                    print(f"  ⚠ {p['name']}: 凭证已配置但未通过验证")
            except Exception as e:
                print(f"  ⚠ {p['name']}: {e}")
        else:
            print(f"  ○ {p['name']}: 未配置凭证（将 {p['credential_file']} 放入 Cookie 即可启用）")

    # 默认监控用户
    if DEFAULT_TARGET_UID:
        try:
            adapter = get_adapter(DEFAULT_PLATFORM)
            if adapter:
                profile = adapter.get_profile(DEFAULT_TARGET_UID)
                if profile:
                    print(f"  ✓ 默认监控: {profile.nickname} ({DEFAULT_PLATFORM}, UID: {DEFAULT_TARGET_UID})")
        except Exception:
            pass

    print(f"  ✓ 面板地址: http://{FLASK_HOST}:{FLASK_PORT}")
    print("=" * 58)

    app = create_app()
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)


if __name__ == "__main__":
    main()
