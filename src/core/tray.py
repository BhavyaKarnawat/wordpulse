"""System tray integration for WordPulse using pystray."""
import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item, Menu
from src.core import autostart
from src.models.settings import DisplayMode, DisplayStyle


def create_tray_image(width: int = 64, height: int = 64) -> Image.Image:
    """Generates a stylish dark modern audio-wave icon for the Windows system tray."""
    img = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Black rounded tile with a pink highlight slab and white bars (matches the lyric slab)
    s = width / 64
    draw.rounded_rectangle([2 * s, 2 * s, width - 2 * s, height - 2 * s], radius=14 * s, fill=(0, 0, 0, 255))
    draw.polygon([(10 * s, 24 * s), (54 * s, 20 * s), (53 * s, 46 * s), (11 * s, 44 * s)], fill=(255, 45, 111, 255))
    for x0, y0, y1 in [(18, 30, 38), (27, 26, 41), (36, 28, 40), (45, 31, 37)]:
        draw.rounded_rectangle([x0 * s, y0 * s, (x0 + 4) * s, y1 * s], radius=2 * s, fill=(255, 255, 255, 255))

    return img


class TrayApp:
    """Manages the Windows taskbar notification area icon and context menu."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def _on_style_selected(self, style: DisplayStyle):
        def _handler(icon, item):
            self.coordinator.set_display_style(style)
        return _handler

    def _on_mode_selected(self, mode: DisplayMode):
        def _handler(icon, item):
            self.coordinator.set_display_mode(mode)
        return _handler

    def _toggle_demo(self, icon, item):
        self.coordinator.toggle_mock_mode(not self.coordinator.settings.mock_mode)

    def _toggle(self, name):
        def _handler(icon, item):
            self.coordinator.set_setting(name, not getattr(self.coordinator.settings, name))
        return _handler

    def _toggle_autostart(self, icon, item):
        self.coordinator.set_setting("start_with_windows", not autostart.is_enabled())

    def _on_quit(self, icon, item):
        if self.icon:
            self.icon.stop()
        self.coordinator.quit()

    def _style_item(self, style: DisplayStyle):
        from src.core.app import STYLE_LABELS
        return item(STYLE_LABELS.get(style.value, style.value.title()), self._on_style_selected(style),
                    checked=lambda i, st=style: self.coordinator.settings.display_style == st, radio=True)

    def build_menu(self) -> Menu:
        c = self.coordinator
        style_menu = Menu(*[self._style_item(st) for st in DisplayStyle])

        mode_menu = Menu(
            item("On the Desktop (behind icons)", self._on_mode_selected(DisplayMode.DESKTOP_WALLPAPER),
                 checked=lambda i: c.settings.display_mode == DisplayMode.DESKTOP_WALLPAPER, radio=True),
            item("Fullscreen", self._on_mode_selected(DisplayMode.FULLSCREEN_AMBIENT),
                 checked=lambda i: c.settings.display_mode == DisplayMode.FULLSCREEN_AMBIENT, radio=True),
            item("Floating Window", self._on_mode_selected(DisplayMode.DESKTOP_OVERLAY),
                 checked=lambda i: c.settings.display_mode == DisplayMode.DESKTOP_OVERLAY, radio=True),
        )

        offset_menu = Menu(
            item(lambda i: f"This song: {c.runtime.get('song_offset_ms', 0):+d} ms", None, enabled=False),
            item("Earlier 100 ms  (Ctrl+Alt+←)", lambda icon, it: c.adjust_song_offset(-100)),
            item("Later 100 ms  (Ctrl+Alt+→)", lambda icon, it: c.adjust_song_offset(100)),
            item("Earlier 500 ms", lambda icon, it: c.adjust_song_offset(-500)),
            item("Later 500 ms", lambda icon, it: c.adjust_song_offset(500)),
            item("Reset this song", lambda icon, it: c.reset_song_offset()),
        )

        return Menu(
            item("Settings…", lambda icon, it: c.open_settings_window(), default=True),
            Menu.SEPARATOR,
            item("Display Style", style_menu),
            item("Display Mode", mode_menu),
            item("Timing", offset_menu),
            item("Sync Words for This Song…", lambda icon, it: c.open_sync_window(),
                 enabled=lambda i: c.current_track is not None),
            Menu.SEPARATOR,
            item("Hide Lyrics  (Ctrl+Alt+L)", lambda icon, it: c.toggle_dnd(), checked=lambda i: c.dnd),
            item("Keep Display Awake", self._toggle("keep_awake"), checked=lambda i: c.settings.keep_awake),
            item("Start with Windows", self._toggle_autostart, checked=lambda i: autostart.is_enabled()),
            item("Demo Songs", self._toggle_demo, checked=lambda i: c.settings.mock_mode),
            Menu.SEPARATOR,
            item("Open Logs Folder", lambda icon, it: c.open_logs()),
            item("Check for Updates", lambda icon, it: threading.Thread(target=c.check_updates, args=(True,), daemon=True).start()),
            item(f"Quit WordPulse", self._on_quit),
        )

    def set_status(self, text: str):
        if self.icon:
            try:
                self.icon.title = text[:127]   # Windows tooltips stop at 128 characters
            except Exception:
                pass

    def notify(self, title: str, message: str):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def start(self):
        """Starts system tray icon in a dedicated daemon thread."""
        img = create_tray_image()
        self.icon = pystray.Icon("WordPulse", img, "WordPulse", menu=self.build_menu())
        self.coordinator.on_status = self.set_status
        self.coordinator.on_notify = self.notify
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()

    def stop(self):
        if self.icon:
            self.icon.stop()
