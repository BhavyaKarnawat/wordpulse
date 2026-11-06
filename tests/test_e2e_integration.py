import pytest
import os
import asyncio
from pathlib import Path
from src.core.app import AppCoordinator
from src.core.tray import TrayApp, create_tray_image
from src.models.settings import AppSettings, DisplayStyle, DisplayMode
from src.models.track import PlaybackStatus

def test_ui_assets_integrity():
    ui_dir = Path("src/ui")
    assert (ui_dir / "index.html").exists()
    assert (ui_dir / "style.css").exists()
    assert (ui_dir / "app.js").exists()

    html = (ui_dir / "index.html").read_text(encoding="utf-8")
    assert 'id="stack"' in html
    assert 'id="gooFilter"' in html and 'lensFilter' not in html   # fisheye is real text now, no pixel filter
    assert 'id="styleSelect"' in html            # styles are offered in a dropdown filled by app.js
    assert 'id="player"' in html and 'id="fsArt"' in html

    css = (ui_dir / "style.css").read_text(encoding="utf-8")
    assert ".style-ship" in css
    assert ".style-fisheye" in css
    assert ".style-fisheye-visual" in css
    assert ".style-visual" in css
    assert ".mode-floating" in css
    assert ".w.active" in css

    js = (ui_dir / "app.js").read_text(encoding="utf-8")
    assert "pywebview" in js
    assert "get_state" in js
    assert "applyPalette" in js

def test_tray_icon_and_menu_generation():
    coordinator = AppCoordinator(settings=AppSettings(mock_mode=True))
    tray = TrayApp(coordinator)
    
    # Verify image generation
    img = create_tray_image()
    assert img.size == (64, 64)
    
    # Verify menu construction
    menu = tray.build_menu()
    assert menu is not None
    # Check that menu items are structured
    menu_items = list(menu.items)
    assert len(menu_items) >= 8

def test_e2e_full_lifecycle():
    async def _test():
        settings = AppSettings(mock_mode=True, display_style=DisplayStyle.SHIP)
        coordinator = AppCoordinator(settings=settings)
        
        # 1. First tick: load first demo track
        track1 = await coordinator.tick_media_update()
        assert track1.title == "Neon Tide"
        assert coordinator.current_doc is not None
        assert coordinator.current_doc.is_synced is True
        assert coordinator.current_palette is not None
        
        # 2. Switch visual style to FISHEYE_VISUAL
        coordinator.set_display_style(DisplayStyle.FISHEYE_VISUAL)
        assert coordinator.settings.display_style == DisplayStyle.FISHEYE_VISUAL
        
        # 3. Switch mode to DESKTOP_OVERLAY
        coordinator.set_display_mode(DisplayMode.DESKTOP_OVERLAY)
        assert coordinator.settings.display_mode == DisplayMode.DESKTOP_OVERLAY
        
        # 4. Advance track to The Quiet Arcade
        coordinator.next_track()
        track2 = await coordinator.tick_media_update()
        assert track2.title == "Paper Satellites"
        assert coordinator.current_doc.track_title == "Paper Satellites"
        
        # 5. Verify timing offset adjustment
        coordinator.adjust_timing_offset(250)
        assert coordinator.settings.timing_offset_ms == 250
        
        # 6. Verify sleep prevention toggle
        coordinator.power_manager.prevent_sleep(True)
        assert coordinator.power_manager.is_inhibited is True
        coordinator.power_manager.prevent_sleep(False)
        assert coordinator.power_manager.is_inhibited is False

    asyncio.run(_test())

