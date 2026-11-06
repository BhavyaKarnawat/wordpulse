# Contributing to WordPulse

Thanks for helping! WordPulse is a free tool, and fixes, new styles and better docs are all welcome.

## Getting set up

You need Windows 10 or 11 and Python 3.12.

```powershell
git clone https://github.com/BhavyaKarnawat/wordpulse.git
cd wordpulse
python -m pip install -r requirements-dev.txt
python -m pytest -q                      # all tests should pass
python run_wordpulse.py --demo           # run with the built-in demo songs
```

Useful switches while developing:

| Switch | What it does |
|---|---|
| `--demo` | Plays the three original demo songs, so you don't need a music app |
| `--style constellation` | Starts in a given style |
| `--mode fullscreen` / `--mode overlay` | Fullscreen or floating window instead of the desktop |
| `WORDPULSE_DEBUG=1` | Logs frame rate and layout checks every 10 s |
| `WORDPULSE_FAKE_BPM=128` | Fakes a beat, to work on beat effects without audio |

Build the exe and installer with `powershell -ExecutionPolicy Bypass -File build.ps1` (the installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)).

## How the code is laid out

| Path | What lives there |
|---|---|
| `run_wordpulse.py` | Entry point: settings, single instance, screensaver arguments |
| `src/core/app.py` | The coordinator: polling, settings, windows, mood, health checks |
| `src/core/desktop.py` | Attaching the window behind the desktop icons |
| `src/media/` | Following Spotify and other players through Windows media controls |
| `src/lyrics/` | Lyrics download, cache, tap-to-sync, cover art |
| `src/audio/` | Beat and tempo detection from what's playing |
| `src/ui/` | The lyrics page (`app.js`, `style.css`), settings, sync and welcome windows |
| `tests/` | pytest suite (runs on every push) |

## Adding a lyric style

1. Add it to `DisplayStyle` in `src/models/settings.py` and to `STYLE_LABELS` in `src/core/app.py`.
2. In `src/ui/app.js`, add a class to `STYLE_CLASS` and a layout in `layoutFor()` (return a list of slots; the motion engine animates them).
3. Keep the sung word centred (`area.centre`) and inside `safeArea()`.
4. Check it with `WORDPULSE_DEBUG=1`: the log reports `overflow_px` (should be negative) and `centre_off_px` (should be near 0).

## Ground rules

- **No copyrighted lyrics in the repo.** Tests, demos and screenshots use the original demo songs only.
- **Keep it light.** WordPulse runs all day; measure CPU before and after anything that animates.
- **Privacy first.** No telemetry, no accounts. Anything that goes online must be listed in the README's privacy section.
- Run `python -m pytest -q` before opening a pull request.
