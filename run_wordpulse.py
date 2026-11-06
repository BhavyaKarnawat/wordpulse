#!/usr/bin/env python3
"""
WordPulse: word-by-word synced lyrics for Windows.

Settings are saved between runs; command-line options override them for one run.
Also works as a Windows screensaver when renamed to .scr (/s, /c, /p arguments).
"""
import argparse
import logging
import os
import sys
from pathlib import Path

from src.core.app import AppCoordinator
from src.core.config import ConfigStore
from src.core import autostart, system
from src.core.tray import TrayApp
from src.models.settings import DisplayMode, DisplayStyle

STYLES = [s.value.lower() for s in DisplayStyle]
MODES = {
    "wallpaper": DisplayMode.DESKTOP_WALLPAPER,
    "fullscreen": DisplayMode.FULLSCREEN_AMBIENT,
    "lockscreen": DisplayMode.FULLSCREEN_AMBIENT,
    "overlay": DisplayMode.DESKTOP_OVERLAY,
    "desktop": DisplayMode.DESKTOP_OVERLAY,
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="WordPulse: word-by-word synced lyrics for Windows")
    parser.add_argument("--demo", action="store_true", help="Offline demo mode with the built-in original songs")
    parser.add_argument("--style", choices=STYLES, help="Display style for this run")
    parser.add_argument("--desktop", action="store_true", help="Floating window mode for this run")
    parser.add_argument("--pin", action="store_true", help="Keep the floating window on top")
    parser.add_argument("--mode", choices=list(MODES), help="Display mode for this run (default: saved setting)")
    parser.add_argument("--offset", type=int, help="Global timing offset in milliseconds")
    parser.add_argument("--no-tray", action="store_true", help="No tray icon")
    parser.add_argument("--no-keep-awake", action="store_true", help="Let the display sleep while music plays")
    parser.add_argument("--settings", action="store_true", help="Open the settings window on start")
    return parser.parse_args(argv)


def screensaver_command(argv):
    """Windows calls screensavers with /s (run), /c[:hwnd] (configure) or /p <hwnd> (preview)."""
    if not argv:
        return None
    a = argv[0].lower()
    if a.startswith("/s") or a.startswith("-s"):
        return "run"
    if a.startswith("/c") or a.startswith("-c"):
        return "config"
    if a.startswith("/p") or a.startswith("-p"):
        return "preview"
    return None


def _mutex(name: str) -> bool:
    """Returns True if another copy already holds this mutex."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    globals().setdefault("_mutexes", []).append(kernel32.CreateMutexW(None, False, name))
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def run_screensaver(cmd: str, store: ConfigStore) -> None:
    if cmd == "preview":
        return   # the tiny preview box in Screen Saver Settings isn't supported
    if cmd == "config":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "WordPulse's options live in its tray icon: right-click it and choose Settings.",
            "WordPulse screensaver", 0x40)
        return
    if _mutex(r"Local\WordPulseScreensaver"):
        return
    settings = store.load()
    settings.display_mode = DisplayMode.FULLSCREEN_AMBIENT
    settings.mock_mode = os.environ.get("WORDPULSE_DEMO") == "1"   # developer switch for testing
    coordinator = AppCoordinator(settings=settings, config=None, screensaver=True)   # never overwrite your settings
    coordinator.launch_window()


def main(argv=None):
    """Runs the app; any failure ends in a readable message, never a silent exit."""
    try:
        _main(argv)
    except SystemExit:
        raise
    except Exception as e:
        logging.getLogger("wordpulse").critical("WordPulse failed to start", exc_info=True)
        system.message_box(
            f"WordPulse ran into a problem and has to close.\n\n{e.__class__.__name__}: {e}\n\n"
            f"Details are in the log folder:\n{_log_dir_hint()}",
            "WordPulse", system.MB_ICONERROR)


def _log_dir_hint() -> str:
    return str(globals().get("_LOG_DIR") or "%APPDATA%\\WordPulse\\logs")


def _main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        store = ConfigStore()
    except OSError:                         # settings folder unusable: keep going with a temp one
        import tempfile
        store = ConfigStore(Path(tempfile.gettempdir()) / "WordPulse")
    log_dir = system.setup_logging(store.dir)
    globals()["_LOG_DIR"] = log_dir
    log = logging.getLogger("wordpulse")

    if not system.webview2_installed():
        answer = system.message_box(
            "WordPulse needs the Microsoft Edge WebView2 Runtime to draw the lyrics, and it isn't installed.\n\n"
            "Open the download page now? (It's free, from Microsoft, and takes a minute.)",
            "WordPulse", system.MB_YESNO | system.MB_ICONWARN)
        if answer == system.IDYES:
            os.startfile(system.WEBVIEW2_URL)
        log.error("WebView2 Runtime missing")
        return

    ss = screensaver_command(argv)
    if ss:
        run_screensaver(ss, store)
        return

    args = parse_args(argv)
    if _mutex(r"Local\WordPulseSingleInstance"):
        # already running: bring up its settings instead of silently doing nothing
        if not system.signal_running_instance():
            system.message_box("WordPulse is already running. Click its icon in the tray (by the clock).")
        return

    # If start-with-Windows is on, keep it pointing at wherever the app lives now
    try:
        if autostart.is_enabled():
            autostart.set_enabled(True)
    except OSError:
        pass

    settings = store.load()
    if args.style:
        settings.display_style = DisplayStyle[args.style.upper()]
    if args.desktop:
        settings.display_mode = DisplayMode.DESKTOP_OVERLAY
    elif args.mode:
        settings.display_mode = MODES[args.mode]
    if args.pin:
        settings.always_on_top = True
    if args.offset is not None:
        settings.timing_offset_ms = args.offset
    if args.no_keep_awake:
        settings.keep_awake = False
    settings.mock_mode = args.demo or os.environ.get("WORDPULSE_DEMO") == "1"

    log.info("Starting WordPulse (mode=%s, style=%s, demo=%s)", settings.display_mode.value,
             settings.display_style.value, settings.mock_mode)
    coordinator = AppCoordinator(settings=settings, config=store)
    coordinator.log_dir = log_dir
    system.listen_for_second_launch(coordinator.open_settings_window)

    tray = None
    if not args.no_tray:
        try:
            tray = TrayApp(coordinator)
            tray.start()
        except Exception:
            log.exception("Could not start the tray icon")
            tray = None
            system.message_box("WordPulse couldn't add its tray icon, so it'll run without one.\n\n"
                               "Press Ctrl+Alt+O any time to open Settings (you can quit from there).",
                               "WordPulse", system.MB_ICONWARN)

    if args.settings:
        coordinator.open_settings_window()
    elif not settings.welcomed:
        coordinator.open_welcome_window()
    try:
        coordinator.launch_window()
    except KeyboardInterrupt:
        coordinator.quit()
    finally:
        if tray:
            tray.stop()


if __name__ == "__main__":
    main()
