"""Generated cover art for the original demo songs (abstract gradients; nothing copied)."""
import base64
import hashlib
import io
from functools import lru_cache

PALETTES = [
    ((255, 61, 127), (64, 22, 120)),    # magenta -> violet
    ((44, 205, 214), (18, 40, 110)),    # teal -> navy
    ((255, 170, 60), (180, 40, 70)),    # amber -> crimson
    ((120, 230, 140), (20, 80, 90)),    # mint -> deep teal
]


@lru_cache(maxsize=16)
def demo_cover(title: str, size: int = 600) -> str:
    """A data URL with a soft two-colour gradient and a few glowing circles, unique per title."""
    from PIL import Image, ImageDraw, ImageFilter
    h = hashlib.sha1(title.encode("utf-8")).digest()
    top, bottom = PALETTES[h[0] % len(PALETTES)]
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        row = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(size):
            px[x, y] = row
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    for i in range(4):
        cx, cy = h[1 + i] / 255 * size, h[5 + i] / 255 * size
        r = size * (0.12 + h[9 + i] / 255 * 0.22)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 40 + h[13 + i] % 50))
    glow = glow.filter(ImageFilter.GaussianBlur(size / 30))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
