import pytest
import io
import base64
from PIL import Image
from src.core.palette import PaletteExtractor
from src.core.power import PowerManager
from src.models.theme import PaletteTheme

def create_test_image_b64(color_rgb=(30, 144, 255)) -> str:
    img = Image.new("RGB", (64, 64), color=color_rgb)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64_str}"

def test_palette_extractor_default():
    extractor = PaletteExtractor()
    theme = extractor.extract_from_base64("")
    assert isinstance(theme, PaletteTheme)
    assert theme.background.startswith("#") or theme.background.startswith("rgb")

def test_palette_extractor_from_image():
    extractor = PaletteExtractor()
    # Deep blue/cyan image
    b64_img = create_test_image_b64((20, 100, 220))
    theme = extractor.extract_from_base64(b64_img)
    
    assert theme.is_auto is True
    assert "rgb" in theme.highlight
    assert "rgb" in theme.background

def test_power_manager_state():
    power = PowerManager()
    # Should not raise exception
    power.prevent_sleep(True)
    assert power.is_inhibited is True
    
    power.prevent_sleep(False)
    assert power.is_inhibited is False

