"""Application settings and display configuration."""
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class DisplayStyle(Enum):
    SHIP = "SHIP"                     # 3D tilted drifting perspective wall
    FISHEYE = "FISHEYE"               # Convex optical lens barrel distortion
    FISHEYE_VISUAL = "FISHEYE_VISUAL" # Fisheye lens + contextual emojis/icons
    VISUAL = "VISUAL"                 # Fluid typography + contextual emojis/icons
    POP = "POP"                       # One big word at a time, springing in
    STAMP = "STAMP"                   # Sung word slams down; earlier words stay scattered
    LINE = "LINE"                     # Whole line; highlight wipes across each word
    ORBIT = "ORBIT"                   # Line rides a 3D carousel, sung word at the front
    INKBLOT = "INKBLOT"               # Old word melts into the new one like ink
    SQUEEZE = "SQUEEZE"               # New word squeezes the old one flat
    REMOLD = "REMOLD"                 # Old word's letters rearrange into the new word


class DisplayMode(Enum):
    DESKTOP_WALLPAPER = "DESKTOP_WALLPAPER"   # Lyrics live on the desktop, behind the icons
    FULLSCREEN_AMBIENT = "FULLSCREEN_AMBIENT" # Fullscreen ambient lock-screen / screensaver
    DESKTOP_OVERLAY = "DESKTOP_OVERLAY"       # Transparent floating desktop HUD


POSITIONS = ["center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right", "custom"]
SLAB_SHAPES = ["sharp", "pill", "none"]
SHUFFLE_MODES = ["off", "song", "line"]
REDUCE_MOTION = ["system", "on", "off"]
AUTO_MOOD = ["off", "beats", "full"]
FULLSCREEN_BG = ["black", "wallpaper", "album"]
DEFAULT_MOOD_STYLES = {"NEON": "SQUEEZE", "BRIGHT": "POP", "HEAVY": "STAMP", "SMOOTH": "REMOLD", "SOFT": "FISHEYE"}


@dataclass
class AppSettings:
    # what and where
    display_style: DisplayStyle = DisplayStyle.SHIP
    display_mode: DisplayMode = DisplayMode.DESKTOP_WALLPAPER
    monitor: int = 0                   # index into the monitor list (0 = primary, -1 = all displays)
    position: str = "center"           # one of POSITIONS
    custom_x: float = 0.5              # 0..1 across the screen, for position == "custom"
    custom_y: float = 0.5
    font_scale: float = 1.0            # overall word size
    max_width_pct: int = 78            # widest a word may get, % of screen width
    always_on_top: bool = False

    # look
    auto_theme: bool = True            # colours from the album art ("Auto Sync")
    lyric_color: str = "#ffb3c7"
    highlight_color: str = "#ff2d6f"
    secondary_color: str = "#9a7480"
    font_family: str = "Segoe UI Variable Display"
    uppercase: bool = False
    slab_shape: str = "sharp"          # one of SLAB_SHAPES
    wall_dim: float = 0.35             # how much the wallpaper dims while words show (0..0.8)
    wall_blur: bool = False
    album_background: bool = False     # use blurred album art behind the words
    fullscreen_bg: str = "black"       # fullscreen + screensaver background: black, wallpaper, album

    # motion
    shuffle: str = "off"               # one of SHUFFLE_MODES
    shuffle_pool: List[str] = field(default_factory=lambda: [s.value for s in DisplayStyle])
    motion: float = 1.0                # 0.3 (calm) .. 1.5 (lively)
    reduce_motion: str = "system"      # follow Windows, or force on/off
    battery_saver: bool = True         # drop the heavy effects on battery

    # mood (tempo / energy / genre)
    auto_mood: str = "full"            # off, beats (on-beat effects only), full (also style + look)
    beat_strength: float = 1.0         # 0..1.5
    mood_styles: dict = field(default_factory=lambda: dict(DEFAULT_MOOD_STYLES))

    # behaviour
    keep_awake: bool = True
    hide_on_fullscreen: bool = True    # step aside for games / fullscreen video
    hide_when_paused_s: int = 0        # 0 = never
    hotkeys_enabled: bool = True
    timing_offset_ms: int = 0          # global; per-song offsets are stored separately
    preferred_player: str = "auto"     # "auto" or part of an app id, e.g. "Spotify"
    ignore_browsers: bool = False
    check_updates: bool = False
    update_repo: str = "BhavyaKarnawat/wordpulse"   # GitHub repo whose releases are checked
    last_update_check: float = 0.0     # when we last looked (daily at most)
    welcomed: bool = False             # first-run welcome shown

    # runtime only (not saved)
    start_with_windows: bool = False
    mock_mode: bool = False            # Demo / test track player
    window_opacity: float = 0.95
