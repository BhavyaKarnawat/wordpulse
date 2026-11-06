"""Pin a window into the Windows desktop wallpaper layer (behind the desktop icons).

This is the same trick live-wallpaper apps use: ask Explorer's Progman window
to spawn a WorkerW behind the icon view, then re-parent our window into it.

Two desktop layouts exist:
  * Windows 10 / 11 before 24H2: a top-level WorkerW holds SHELLDLL_DefView
    (the icons) and a *separate* top-level WorkerW sits behind it. We parent
    into that second WorkerW.
  * Windows 11 24H2 and later: SHELLDLL_DefView and the wallpaper WorkerW are
    both children of Progman. We parent into Progman and slot our window
    between the icons (above) and the wallpaper WorkerW (below).
"""
import base64
import ctypes
import os
import io
import sys
from ctypes import wintypes
from typing import Optional

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                           wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    user32.SetParent.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_EX_LAYERED = 0x00080000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
LWA_ALPHA = 0x2
SMTO_NORMAL = 0x0
SPI_GETDESKWALLPAPER = 0x0073
SPI_SETDESKWALLPAPER = 0x0014
SPIF_SENDCHANGE = 0x2
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXSCREEN, SM_CYSCREEN = 0, 1
SW_SHOW = 5
DPI_PER_MONITOR_V2 = ctypes.c_void_p(-4)


class _PhysicalPixels:
    """Measure and place windows in real screen pixels, regardless of display scaling."""
    def __enter__(self):
        self._old = user32.SetThreadDpiAwarenessContext(DPI_PER_MONITOR_V2) if IS_WINDOWS else None
    def __exit__(self, *exc):
        if self._old:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(self._old))


def primary_screen_size() -> tuple:
    if not IS_WINDOWS:
        return 1920, 1080
    return user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)


def _find_wallpaper_host() -> tuple:
    """Returns (parent_hwnd, insert_after_hwnd, wallpaper_workerw_or_None)."""
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return None, None, None

    # Ask Progman to create the WorkerW behind the desktop icons.
    result = ctypes.c_size_t()
    user32.SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, SMTO_NORMAL, 1000, ctypes.byref(result))
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, SMTO_NORMAL, 1000, ctypes.byref(result))

    # Windows 11 24H2+: icons and wallpaper WorkerW are children of Progman.
    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
    child_worker = user32.FindWindowExW(progman, None, "WorkerW", None)
    if defview and child_worker:
        return progman, defview, child_worker

    # Older layout: find the top-level window holding the icons, take the WorkerW after it.
    found = {"worker": None}

    def _enum(hwnd, _lparam):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            found["worker"] = user32.FindWindowExW(None, hwnd, "WorkerW", None)
        return True

    user32.EnumWindows(WNDENUMPROC(_enum), 0)
    if found["worker"]:
        return found["worker"], None, None

    # Last resort: Progman itself (icons may cover us, but we still sit on the desktop).
    return progman, defview, None


class DesktopPinner:
    """Moves one window into / out of the wallpaper layer."""

    def __init__(self):
        self.hwnd: Optional[int] = None
        self._saved_style = None
        self._saved_exstyle = None
        self._progman = None
        self.rect = None
        self.attached = False

    def attach(self, hwnd: int, rect=None) -> bool:
        """rect = (x, y, w, h) of the monitor in physical screen pixels; default the primary one."""
        if not IS_WINDOWS or not hwnd:
            return False
        self.rect = rect
        with _PhysicalPixels():
            return self._attach(hwnd)

    def is_healthy(self) -> bool:
        """False after Explorer restarts (our parent window is gone or no longer the desktop)."""
        if not IS_WINDOWS or not self.attached or not self.hwnd:
            return True
        parent = user32.GetParent(self.hwnd)
        progman = user32.FindWindowW("Progman", None)
        if not parent or not user32.IsWindow(parent):
            return False
        # our host was Progman itself (24H2+) or a WorkerW that Progman owns; either way Progman must be the same
        return progman == self._progman

    def reattach(self) -> bool:
        if not self.hwnd:
            return False
        self.attached = False
        return self.attach(self.hwnd, getattr(self, "rect", None))

    def _attach(self, hwnd: int) -> bool:
        parent, insert_after, wallpaper_worker = _find_wallpaper_host()
        if not parent:
            return False
        self._progman = user32.FindWindowW("Progman", None)

        self.hwnd = hwnd
        if self._saved_style is None:
            self._saved_style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            self._saved_exstyle = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)

        style = self._saved_style
        style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        style |= WS_CHILD | WS_VISIBLE
        exstyle = (self._saved_exstyle & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if insert_after:  # 24H2 layout: composed as a layered child of Progman
            exstyle |= WS_EX_LAYERED
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, exstyle)
        if exstyle & WS_EX_LAYERED:
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)

        user32.SetParent(hwnd, parent)

        # The host spans the whole virtual screen, whose top-left is (vx, vy) on screen.
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        if self.rect:
            mx, my, w, h = self.rect
        else:
            mx, my = 0, 0
            w, h = primary_screen_size()
        x, y = mx - vx, my - vy
        user32.SetWindowPos(hwnd, insert_after or 0, x, y, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED)
        if wallpaper_worker:
            # keep Explorer's wallpaper below us
            user32.SetWindowPos(wallpaper_worker, hwnd, 0, 0, 0, 0, SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE)
        user32.ShowWindow(hwnd, SW_SHOW)
        self.attached = True
        return True

    def detach(self) -> None:
        if not IS_WINDOWS or not self.hwnd or not self.attached:
            return
        user32.SetParent(self.hwnd, None)
        if self._saved_style is not None:
            user32.SetWindowLongPtrW(self.hwnd, GWL_STYLE, self._saved_style)
            user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, self._saved_exstyle)
        user32.SetWindowPos(self.hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        self.attached = False
        refresh_wallpaper()


def cover_monitor(hwnd: int, rect, topmost: bool = True) -> bool:
    """Makes a window cover a whole monitor, taskbar included (real fullscreen)."""
    if not IS_WINDOWS or not hwnd or not rect:
        return False
    HWND_TOPMOST, HWND_TOP = -1, 0
    x, y, w, h = rect
    with _PhysicalPixels():
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~(WS_CAPTION | WS_THICKFRAME)) | WS_VISIBLE)
        ok = user32.SetWindowPos(hwnd, HWND_TOPMOST if topmost else HWND_TOP, x, y, w, h,
                                 SWP_SHOWWINDOW | SWP_FRAMECHANGED)
    return bool(ok)


def wallpaper_path() -> str:
    if not IS_WINDOWS:
        return ""
    buf = ctypes.create_unicode_buffer(520)
    user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, len(buf), buf, 0)
    return buf.value


def refresh_wallpaper() -> None:
    """Makes Explorer repaint the wallpaper (clears anything we left behind)."""
    path = wallpaper_path()
    if path:
        user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, ctypes.c_wchar_p(path), SPIF_SENDCHANGE)


def wallpaper_data_url(max_width: int = 2560) -> str:
    """The current wallpaper as a JPEG data URL, so the page can sit on top of it."""
    path = wallpaper_path()
    if not path:
        return ""
    try:
        from PIL import Image
        with Image.open(path) as img:
            img = img.convert("RGB")
            if img.width > max_width:
                img = img.resize((max_width, round(img.height * max_width / img.width)), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=88)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        return ""
