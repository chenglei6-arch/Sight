"""小红书 PC 模块。"""

# Keep the package-level imports used by the API modules stable while the
# implementation remains in ``auth.py`` and the shared core package.
from ref_xhs_core.auth import XHSAuth

from .auth import PC_PARAMETER_SOURCES, XHSPcAuth

__all__ = ["PC_PARAMETER_SOURCES", "XHSAuth", "XHSPcAuth"]
