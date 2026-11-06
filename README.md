# WordPulse: word-by-word lyrics on your Windows desktop


> Live, word-by-word lyrics for whatever you're playing, right on your Windows desktop.
> Lights lyrics word-by-word at the exact moment each syllable is sung, synchronized to your active media player.

![WordPulse Architecture](https://img.shields.io/badge/Windows-GSMTC%20%7C%20WinRT-0078D4?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![WebView2](https://img.shields.io/badge/Engine-Microsoft%20Edge%20WebView2-0078D7?logo=microsoftedge&logoColor=white)


---

## ✨ Features

- **Lyrics on your desktop:** By default WordPulse draws behind your desktop icons, on top of your wallpaper, like a live wallpaper. The desktop looks normal until music plays, then the words appear. There's no window or taskbar button; everything lives in the tray.
- **Word-by-word timing:** Each word lights up as it's sung. Songs with word-level timing are exact; line-timed songs get an estimate that learns each song's singing pace. You can also tap along to sync any song yourself (see below).
- **Works with what you already play:** Uses Windows' built-in media controls (GSMTC) to follow Spotify, Apple Music, Tidal, YouTube Music, and browsers. No login.
- **11 display styles.** The sung word always sits in the middle of the screen:
  1. **Ship:** a typographic wall drifting in 3D.
  2. **Fisheye:** a convex lens stack with the sung word closest to the glass.
  3. **Fisheye Visual:** the lens plus icons.
  4. **Visual:** icons pop in beside the words (about 800 mapped words).
  5. **Pop:** one big word at a time, springing in.
  6. **Stamp:** each word slams onto the centre, and earlier words of the line stay scattered around it.
  7. **Line:** the whole line shows, and the highlight wipes across each word as it's sung.
  8. **Orbit:** the line rides a 3D carousel that turns to bring the sung word to the front.
  9. **Inkblot:** the old word melts into the new one like ink, slab and all, then snaps back to crisp text.
  10. **Squeeze:** the new word pushes in from the right and squashes the old one flat against its left edge.
  11. **Remold:** the old word's letters rearrange into the new word. Shared letters slide to their new spots, extra letters melt away, and new ones sprout from their neighbours while the slab stretches to fit.
- **Mood that follows the music:** WordPulse listens to the beat (on your PC only; audio is never saved or sent) and reads each song's lyric speed and genre. It then picks one of five moods: **Neon** for rap, drill and EDM, **Bright** for upbeat pop, **Heavy** for rock and metal, **Smooth** for R&B and soul, and **Soft** for ballads and acoustic songs. Each mood sets the style and the colours, and adds on-beat pulses and drop shakes. You can override the mood per song, and choose which style each mood uses.
- **Auto Sync colours:** The highlight colour comes from the album art, and each mood re-tunes it.
- **Works offline:** Every lyric download is saved, so songs you've played before work without internet. When you're offline the app says so, and retries until you're back online.
- **Keeps the screen awake** while music plays.
- **Other modes:** fullscreen, a floating window you can pin on top, a screensaver, and **All displays**, which puts lyrics on every monitor.
- **Settings window and tray:** saved settings, placement, fonts, highlight shape, wallpaper dim and blur, per-song timing, and system-wide hotkeys. The lyrics hide themselves during games or fullscreen video.
- **Start with Windows** and a **daily update check**, both optional.
- **Offline demo:** three original songs written for the demo, with word timing.

### Tap to sync

For songs without word timing, right-click the tray icon and choose **Sync Words for This Song…**. While the song plays, tap <kbd>Space</kbd> (or click) each time a word is sung:

| Key | Action |
|-----|--------|
| <kbd>Space</kbd> / click | Mark the highlighted word as sung now |
| <kbd>Backspace</kbd> | Undo the last tap |
| <kbd>↓</kbd> / <kbd>Enter</kbd> | Skip the rest of this line |
| <kbd>Home</kbd> | Jump to the line playing now |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save |

You can start mid-song and save at any point. Untapped words keep their estimated timing. The **Reaction** slider shifts taps earlier to cancel out reaction time (default 120 ms). Saved timings are stored per song in `%USERPROFILE%\.wordpulse\lyrics_cache` and win over downloaded lyrics. **Reset to source** removes them.

---

## 🚀 Quick Start

### Install
Download `WordPulse-Setup-<version>.exe` from [Releases](../../releases) and run it. It installs just for you, with no admin rights needed, and offers a Start menu shortcut, start-with-Windows and the screensaver. You can also run the standalone `WordPulse.exe`. Either way it needs the Microsoft Edge WebView2 Runtime, which comes with Windows 10 and 11.

On first launch a short welcome explains the tray icon and shortcuts. After that, click the tray icon for **Settings**.

### Build it yourself
```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
# -> dist\WordPulse.exe, dist\WordPulse.scr and, if Inno Setup 6 is installed, dist\WordPulse-Setup-<version>.exe
```
To sign the builds, set `WORDPULSE_SIGN_PFX` (and `WORDPULSE_SIGN_PASSWORD`) to your code-signing certificate before running the script.

### Run from source
```powershell
python run_wordpulse.py                 # on the desktop (default)
python run_wordpulse.py --demo          # demo songs
python run_wordpulse.py --mode overlay  # floating window
```

Command-line options:
```text
  --demo                Offline demo mode with the built-in songs
  --style {ship,fisheye,fisheye_visual,visual,pop,stamp,line,orbit,inkblot,squeeze,remold}
  --mode {wallpaper,fullscreen,overlay,desktop,lockscreen}   (default: wallpaper)
  --desktop             Floating window mode
  --pin                 Keep the floating window on top
  --offset OFFSET       Timing offset in milliseconds
  --no-tray             No tray icon
  --no-keep-awake       Let the display sleep while music plays
```
Developer switches:
- `WORDPULSE_DEBUG=1` logs frame timing and layout checks every 10 seconds.
- `WORDPULSE_DEMO=1` plays the demo songs, including in screensaver mode.
- `WORDPULSE_FAKE_BPM=128` fakes a beat, to try the beat effects without audio.

### Where things are stored
| What | Where |
|------|-------|
| Settings, per-song timing and mood, genre tags | `%APPDATA%\WordPulse\` |
| Logs | `%APPDATA%\WordPulse\logs\` |
| Saved lyrics and your tapped timings | `%USERPROFILE%\.wordpulse\lyrics_cache\` (up to 4,000 songs; taps and imported lyrics are never removed) |

---

## ⌨️ Controls

The tray menu has everything: style, display mode, timing offset, tap to sync, start with Windows, demo mode, and quit. In fullscreen and floating modes you can also use:

| Key | Action |
|-----|--------|
| <kbd>1</kbd>–<kbd>8</kbd> | Ship, Fisheye, Fisheye Visual, Visual, Pop, Stamp, Line, Orbit |
| <kbd>9</kbd> / <kbd>0</kbd> / <kbd>-</kbd> | Inkblot, Squeeze, Remold |
| <kbd>F11</kbd> / <kbd>Tab</kbd> | Cycle display mode |
| <kbd>T</kbd> | Pin on top |
| <kbd>Space</kbd> | Play / pause (demo) |
| <kbd>N</kbd> / <kbd>P</kbd> | Next / previous (demo) |
| <kbd>D</kbd> | Toggle demo mode |

---

## 🧪 Testing & Verification

WordPulse includes an automated test suite:

```powershell
python -m pytest tests/
```

Test coverage includes:
- Enhanced LRC syllable parsing & timestamp calculations
- Heuristic syllable & timing interpolation for line-synced lyrics
- Semantic icon/emoji mapping across 800+ words
- GSMTC media session tracking & clock extrapolation
- Album art color quantization & high-contrast WCAG palette generation
- Windows sleep prevention (`SetThreadExecutionState`)
- Full end-to-end integration flows and UI asset validation

