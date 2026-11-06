"""Start WordPulse when you sign in to Windows (per-user, no admin needed).

Uses the standard HKCU ...\\CurrentVersion\\Run key, the same place Spotify,
Discord etc. register themselves. The registry is the source of truth, so the
tray checkbox always reflects what Windows will actually do.
"""
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WordPulse"

try:
    import winreg
except ImportError:  # not Windows
    winreg = None


def launch_command() -> str:
    """The command Windows should run at sign-in."""
    if getattr(sys, "frozen", False):  # packaged WordPulse.exe
        return f'"{sys.executable}"'
    # running from source: use pythonw so no console window appears
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    script = Path(__file__).resolve().parents[2] / "run_wordpulse.py"
    return f'"{interpreter}" "{script}"'


def is_enabled(key_path: str = RUN_KEY) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except OSError:
        return False


def set_enabled(enable: bool, key_path: str = RUN_KEY) -> bool:
    """Turns start-at-sign-in on or off. Returns the resulting state."""
    if winreg is None:
        return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if enable:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    return is_enabled(key_path)
