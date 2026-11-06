# PyInstaller spec for WordPulse -> dist/WordPulse.exe (single file, no console window)
# Build with:  powershell -ExecutionPolicy Bypass -File build.ps1
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("src/ui", "src/ui")]
binaries = []
hiddenimports = [
    "pystray._win32",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr",
    # only the WinRT namespaces WordPulse actually uses (winsdk is huge)
    "winsdk.windows.media.control",
    "winsdk.windows.storage.streams",
    "winsdk.windows.foundation",
    "winsdk.windows.foundation.collections",
]

for pkg in ("webview", "clr_loader", "pythonnet", "pyaudiowpatch"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("syncedlyrics")

a = Analysis(
    ["run_wordpulse.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WordPulse",
    icon="assets/wordpulse.ico",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
