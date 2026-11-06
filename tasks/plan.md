# Implementation Plan: WordPulse

## Overview
WordPulse is a high-performance Windows desktop application that shows real-time, word-by-word synchronized lyrics across several visual styles, with automatic media session detection from Spotify, Apple Music, and other Windows media players via GSMTC, dynamic album artwork color extraction, display awake management (`SetThreadExecutionState`), a desktop (behind the icons) mode, a fullscreen / screensaver mode and a floating overlay.

## Architecture Decisions
1. **Media Capture (GSMTC WinRT API)**:
   - Use `winsdk.windows.media.control.GlobalSystemMediaTransportControlsSessionManager` to natively track current media playback, title, artist, album art thumbnail, playback state (Playing/Paused/Stopped), and timeline position across Spotify, Apple Music, Tidal, YouTube, Chrome, Edge, and other Windows media players.
   - Include a robust Mock/Demo Media Controller for offline testing, demos, and instant automated verification without requiring third-party players running.
2. **Lyrics Pipeline**:
   - Primary provider: LRCLIB API (`https://lrclib.net`) for rich synced LRC lyrics.
   - Local disk cache (`~/.wordpulse/lyrics_cache/`) to avoid repeated network requests.
   - Enhanced LRC Parser: Parses word-level timestamps (`[mm:ss.xx] <mm:ss.xx> word <mm:ss.xx> word ...`).
   - Syllable & Tempo Interpolator: When a song only has line-level timestamps, intelligently interpolates word-level timings using phonetic syllable counts and punctuation weights so that word-by-word animation is smooth and natural.
   - Word-to-Symbol/Emoji Semantic Mapper: Maps over 800 common lyrical words to emojis and modern vector icons with punctuation stripping and lemmatization.
3. **Dynamic Color & Palette Engine**:
   - Uses Pillow / ColorThief-style quantization to extract the dominant background color, primary highlight color, and secondary accent from the album art thumbnail.
   - Generates ambient mesh gradients and contrasting readable typography with dark-glass aesthetics.
4. **Rendering & Frontend Architecture**:
   - Modern WebGL & CSS3 3D engine running in a GPU-accelerated WebView2 window (`pywebview`) with transparent background, frameless styling, and click-through overlay capabilities.
   - Shaders and visual styles:
     - *Ship*: 3D stacked word wall drifting in virtual space with perspective camera, focal depth, and luminous glow on the active word.
     - *Fisheye*: Convex lens barrel-distortion shader where the active sung word sits closest to the glass while neighboring text curves away.
     - *Visual*: Dynamic typography with bouncy spring-animated icons popping in beside recognized lyrics.
     - *Fisheye Visual*: The combination of the convex lens shader and the contextual lyric icons.
5. **System Integration & Power**:
   - System Tray icon (`pystray`) for background menu controls (style switching, mode switching, palette choices, timing offset, toggle sleep inhibitor, exit).
   - Sleep prevention via `kernel32.SetThreadExecutionState` while music is actively playing.

---

## Task Breakdown

### Phase 1: Core Foundation & Testing Framework
- **Task 1: Project Setup, Models, & Testing Framework**
  - Create project structure (`src/`, `tests/`, `assets/`).
  - Define data models (`TrackInfo`, `LyricWord`, `LyricLine`, `LyricsDocument`, `PaletteTheme`, `AppSettings`).
  - Set up `pytest` test runner and base test harness.
- **Task 2: Enhanced LRC & Word-Level Timing Engine**
  - Implement parser for standard LRC, Enhanced LRC (syllable timestamps), and plain text.
  - Implement the Syllable / Word Timing Interpolator for line-level lyrics.
  - Implement Lyric Synchronizer providing active line index, active word index, and progress percentage for any given timestamp.
  - Unit tests covering all parsing variants, timing calculations, and edge cases.
- **Task 3: Semantic Lyric Icon & Emoji Mapper**
  - Implement comprehensive mapping dictionary (>800 words) for *Visual* and *Fisheye Visual* modes.
  - Handle contractions, punctuation, plurals, and case insensitivity.
  - Unit tests for emoji mapping.

### Checkpoint: Foundation
- All unit tests for models, LRC parsing, timing calculation, and icon mapping pass.

---

### Phase 2: Media Integration & Color Pipeline
- **Task 4: Media Session Provider (GSMTC + Mock Provider)**
  - Implement `GSMTCMediaProvider` using `winsdk` to read current playing media, playback status, track metadata, and timeline position.
  - Implement `MockMediaProvider` with bundled original demo songs for testing and headless validation.
  - Implement smooth position extrapolation between polling intervals.
- **Task 5: Lyrics Service & Caching**
  - Implement `LyricsService` querying LRCLIB with song title, artist, and duration.
  - Implement local SQLite or JSON file cache.
  - Fallback mechanisms for instrumental songs or missing lyrics.
- **Task 6: Album Artwork Palette Extractor & Power Manager**
  - Implement `PaletteExtractor` extracting dominant and accent colors from album art image buffers.
  - Implement Windows `PowerManager` utilizing `ctypes.windll.kernel32.SetThreadExecutionState`.

### Checkpoint: Media & Lyrics Services
- Media provider tracks sessions cleanly, lyrics fetch and cache reliably, and palette extraction succeeds.

---

### Phase 3: Visual Interface & Display Modes (Ship, Fisheye, Visual)
- **Task 7: Modern Web UI & Visual Engines**
  - Build the HTML/CSS/JavaScript interface:
    - *Ship Mode*: CSS 3D perspective wall with camera drift, depth of field, and glowing active word.
    - *Fisheye Mode*: Convex optical lens shader / WebGL distortion with magnified focal word.
    - *Visual Mode*: Fluid typography with spring-animated symbol / emoji pops.
    - *Fisheye Visual Mode*: Combined lens curvature and icon animations.
  - Fullscreen Ambient Mode (clock, track details, album art, lyrics) + Floating Transparent Desktop Overlay.
- **Task 8: Bridge, Tray Application & Controls**
  - Implement bidirectional Python <-> WebView2 bridge (`pywebview.api`).
  - Implement System Tray icon (`pystray`) with full context menu for style switching, timing offsets (±0.5s), theme toggles, and quit.
  - Support keyboard shortcuts: `F11` (toggle fullscreen/overlay), `1-4` (switch styles), `Space` (play/pause toggle), `Esc` (minimize).

---

### Phase 4: Integration, Verification & Polish
- **Task 9: End-to-End Automated Testing & Validation**
  - Write and run comprehensive automated integration test suite (`pytest tests/`).
  - Verify smooth UI rendering, media timeline sync, style transitions, and sleep prevention.
- **Task 10: CLI Runner, Documentation & Packaging**
  - Create entry point `run_wordpulse.py` and batch/powershell launcher `wordpulse.bat`.
  - Write detailed `README.md` with usage instructions, keyboard shortcuts, and architecture guide.

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| User doesn't have an active media player during testing | High | Provide a robust built-in Mock / Demo player with real songs and word-by-word lyrics so app can be tested immediately anytime. |
| Media timeline desync in GSMTC | Med | Implement high-precision local clock extrapolation between GSMTC timeline updates, with automatic resync on seek/pause. |
| WebView2 transparent window click-through | Low | Provide clean toggle for "Interactive Mode" vs "Click-Through Overlay Mode" via hotkey and tray. |

