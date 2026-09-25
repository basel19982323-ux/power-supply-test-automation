"""Path resolution that works both from source and from a PyInstaller bundle.

app_base()      -> where writable app data goes (output/, saved configs).
                   Frozen: the folder that contains the .exe. Source: the app root.
resource_base() -> where bundled read-only resources live (shipped default
                   configs, templates). Frozen: the PyInstaller extract dir
                   (_MEIPASS). Source: the app root.

From source these are the same directory, so behaviour is unchanged during
development; the split only matters in a packaged build.
"""
import os
import sys

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return _APP_ROOT


def resource_base():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return _APP_ROOT
