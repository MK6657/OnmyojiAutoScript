"""Device package bootstrap.

``adbutils==0.11.0`` still imports the removed ``pkg_resources`` module.
Load the project's small compatibility shim before any device submodule can
import adbutils or uiautomator2.  This keeps fresh Python environments (where
modern setuptools no longer ships pkg_resources) usable without a global
site-package monkey patch.
"""

from module.device.pkg_resources import get_distribution as _get_distribution

__all__ = []

# Keep the import observable to static analysers and avoid an eager package
# lookup on every submodule import.
_ = _get_distribution
