"""Small Windows helpers: monitors, fullscreen detection, battery, hotkeys, logging."""
import ctypes
import logging
import logging.handlers
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"
log = logging.getLogger("wordpulse")


# ---------------- logging ----------------
def setup_logging(directory: Path) -> Path:
    """Rotating log file; also catches crashes. The exe has no console, so this is where errors go."""
    log_dir = Path(directory) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:                       # settings folder not writable: log to the temp folder instead
        import tempfile
        log_dir = Path(tempfile.gettempdir()) / "WordPulse" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "wordpulse.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=512_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)

    def _excepthook(exc_type, exc, tb):
        log.critical("Unhandled error", exc_info=(exc_type, exc, tb))
    sys.excepthook = _excepthook
    threading.excepthook = lambda a: log.critical("Unhandled error in thread %s", a.thread, exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return log_dir


# ---------------- messages, WebView2, single instance ----------------
MB_OK, MB_YESNO, MB_ICONINFO, MB_ICONWARN, MB_ICONERROR, IDYES = 0x0, 0x4, 0x40, 0x30, 0x10, 6
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def message_box(text: str, title: str = "WordPulse", flags: int = MB_ICONINFO) -> int:
    """A plain Windows message box (the exe has no console to print to)."""
    if not IS_WINDOWS:
        print(f"{title}: {text}")
        return 0
    try:
        return ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x10000)  # MB_SETFOREGROUND
    except Exception:
        return 0


def webview2_installed() -> bool:
    """The Microsoft Edge WebView2 Runtime draws the lyrics; it ships with Windows 11 and most Windows 10 PCs."""
    if not IS_WINDOWS:
        return True
    import winreg
    guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    places = [
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\" + guid),
        (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + guid),
        (winreg.HKEY_CURRENT_USER, "Software\\Microsoft\\EdgeUpdate\\Clients\\" + guid),
    ]
    for hive, key in places:
        try:
            with winreg.OpenKey(hive, key) as k:
                version, _ = winreg.QueryValueEx(k, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


SHOW_SETTINGS_EVENT = r"Local\WordPulseShowSettings"


def signal_running_instance() -> bool:
    """A second launch asks the running copy to open its settings window instead of doing nothing."""
    if not IS_WINDOWS:
        return False
    k32 = ctypes.windll.kernel32
    k32.OpenEventW.restype = wintypes.HANDLE
    handle = k32.OpenEventW(0x0002, False, SHOW_SETTINGS_EVENT)   # EVENT_MODIFY_STATE
    if not handle:
        return False
    k32.SetEvent(handle)
    k32.CloseHandle(handle)
    return True


def listen_for_second_launch(callback: Callable[[], None]) -> None:
    if not IS_WINDOWS:
        return
    k32 = ctypes.windll.kernel32
    k32.CreateEventW.restype = wintypes.HANDLE
    handle = k32.CreateEventW(None, False, False, SHOW_SETTINGS_EVENT)   # auto-reset

    def _wait():
        while True:
            if k32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
                try:
                    callback()
                except Exception:
                    log.exception("Opening settings for a second launch failed")
    threading.Thread(target=_wait, daemon=True, name="second-launch").start()


def next_backoff(previous: float, floor: float = 2.0, ceiling: float = 30.0) -> float:
    """Retry delays that grow 2, 4, 8 ... up to 30 s, so a missing device doesn't spin."""
    return min(ceiling, max(floor, previous * 2))


# ---------------- monitors ----------------
class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT), ("rcWork", _RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def list_monitors() -> List[Dict]:
    """Monitors in physical pixels, primary first: [{name, x, y, w, h, work:(x,y,w,h), primary}]."""
    if not IS_WINDOWS:
        return [{"name": "Primary", "x": 0, "y": 0, "w": 1920, "h": 1080, "work": (0, 0, 1920, 1040), "primary": True}]
    user32 = ctypes.windll.user32
    old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    found = []
    PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(_RECT), wintypes.LPARAM)

    def cb(hmon, hdc, rect, lparam):
        info = _MONITORINFOEX()
        info.cbSize = ctypes.sizeof(_MONITORINFOEX)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            m, wk = info.rcMonitor, info.rcWork
            found.append({
                "name": info.szDevice.replace("\\\\.\\", ""),
                "x": m.left, "y": m.top, "w": m.right - m.left, "h": m.bottom - m.top,
                "work": (wk.left, wk.top, wk.right - wk.left, wk.bottom - wk.top),
                "primary": bool(info.dwFlags & 1),
            })
        return True

    user32.EnumDisplayMonitors(None, None, PROC(cb), 0)
    if old:
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
    found.sort(key=lambda m: (not m["primary"], m["x"], m["y"]))
    for i, m in enumerate(found):
        m["label"] = f"{'Main display' if m['primary'] else 'Display ' + str(i + 1)} ({m['w']}×{m['h']})"
    return found


def monitor_rect(index: int) -> Tuple[int, int, int, int]:
    mons = list_monitors()
    m = mons[index] if 0 <= index < len(mons) else mons[0]
    return m["x"], m["y"], m["w"], m["h"]


# ---------------- fullscreen apps / battery ----------------
def fullscreen_app_running() -> bool:
    """True while a game, fullscreen video or presentation has the screen."""
    if not IS_WINDOWS:
        return False
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except Exception:
        return False
    # 2 = busy (fullscreen app), 3 = D3D fullscreen, 4 = presentation mode
    return state.value in (2, 3, 4)


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def on_battery() -> bool:
    if not IS_WINDOWS:
        return False
    st = _SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return False
    return st.ACLineStatus == 0


def system_reduce_motion() -> bool:
    """Windows 'Animation effects' off -> the user wants less motion."""
    if not IS_WINDOWS:
        return False
    enabled = wintypes.BOOL(True)
    SPI_GETCLIENTAREAANIMATION = 0x1042
    if ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0):
        return not enabled.value
    return False


# ---------------- global hotkeys ----------------
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK = {"L": 0x4C, "S": 0x53, "O": 0x4F, "LEFT": 0x25, "RIGHT": 0x27}
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

DEFAULT_HOTKEYS = {
    "toggle": ("Ctrl+Alt+L", MOD_CONTROL | MOD_ALT, VK["L"]),
    "next_style": ("Ctrl+Alt+S", MOD_CONTROL | MOD_ALT, VK["S"]),
    "settings": ("Ctrl+Alt+O", MOD_CONTROL | MOD_ALT, VK["O"]),
    "earlier": ("Ctrl+Alt+Left", MOD_CONTROL | MOD_ALT, VK["LEFT"]),
    "later": ("Ctrl+Alt+Right", MOD_CONTROL | MOD_ALT, VK["RIGHT"]),
}


class HotkeyListener:
    """Registers system-wide shortcuts on its own thread (they must be read from the thread that registered them)."""

    def __init__(self, handlers: Dict[str, Callable[[], None]]):
        self.handlers = handlers
        self.thread_id = 0
        self.registered: List[str] = []
        self.failed: List[str] = []
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not IS_WINDOWS or self._thread:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True, name="hotkeys")
        self._thread.start()
        ready.wait(2)

    def _run(self, ready: threading.Event) -> None:
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ids = {}
        for i, (name, (label, mods, vk)) in enumerate(DEFAULT_HOTKEYS.items(), start=1):
            if name not in self.handlers:
                continue
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = name
                self.registered.append(label)
            else:
                self.failed.append(label)   # another app already owns it
        if self.failed:
            log.warning("Hotkeys already in use by another app: %s", ", ".join(self.failed))
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                try:
                    self.handlers[ids[msg.wParam]]()
                except Exception:
                    log.exception("Hotkey handler failed")
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            self.thread_id = 0
            self._thread = None
