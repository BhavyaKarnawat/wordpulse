"""Extracts dynamic color palettes from album artwork images."""
import base64
import colorsys
import io
from typing import List, Optional, Tuple
from PIL import Image
from src.models.theme import PaletteTheme


class PaletteExtractor:
    """Extracts harmonious background, highlight, and accent colors from album covers."""

    @staticmethod
    def _rgb_to_hsl(r: int, g: int, b: int) -> Tuple[float, float, float]:
        return colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)

    @staticmethod
    def _hsl_to_rgb(h: float, l: float, s: float) -> Tuple[int, int, int]:
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        return int(r * 255), int(g * 255), int(b * 255)

    def extract_from_base64(self, b64_str: str) -> PaletteTheme:
        """Extracts palette from a data:image/...;base64 string."""
        if not b64_str or "," not in b64_str:
            return PaletteTheme.default_theme()

        try:
            header, encoded = b64_str.split(",", 1)
            raw_bytes = base64.b64decode(encoded)
            return self.extract_from_bytes(raw_bytes)
        except Exception:
            return PaletteTheme.default_theme()

    def extract_from_bytes(self, image_bytes: bytes) -> PaletteTheme:
        """Analyzes image bytes and produces an accessible, vibrant theme."""
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                img = img.convert("RGB")
                # Downsample for rapid extraction
                img = img.resize((48, 48), Image.Resampling.LANCZOS)
                
                # Quantize down to 12 dominant color clusters
                quantized = img.quantize(colors=12)
                palette = quantized.getpalette()[: 12 * 3]
                
                colors: List[Tuple[int, int, int]] = []
                for i in range(0, len(palette), 3):
                    colors.append((palette[i], palette[i + 1], palette[i + 2]))

                if not colors:
                    return PaletteTheme.default_theme()

                # Score colors based on saturation and balanced lightness
                scored_highlights = []
                for rgb in colors:
                    h, l, s = self._rgb_to_hsl(*rgb)
                    # Prefer high saturation and medium-high lightness
                    score = (s * 2.5) + (1.0 - abs(l - 0.65))
                    scored_highlights.append((score, rgb, (h, l, s)))

                scored_highlights.sort(key=lambda x: x[0], reverse=True)
                
                best_highlight = scored_highlights[0][1]
                h_h, h_l, h_s = scored_highlights[0][2]
                
                # Ensure highlight is sufficiently light and vivid for reading on dark backdrop
                target_l = max(0.55, min(0.80, h_l))
                target_s = max(0.60, h_s)
                final_highlight = self._hsl_to_rgb(h_h, target_l, target_s)

                # Find secondary accent with distinct hue
                best_accent = final_highlight
                for _, rgb, (a_h, a_l, a_s) in scored_highlights[1:]:
                    hue_diff = abs(a_h - h_h)
                    if hue_diff > 0.5:
                        hue_diff = 1.0 - hue_diff
                    if hue_diff > 0.15:  # At least ~50 degrees difference on color wheel
                        acc_l = max(0.50, min(0.78, a_l))
                        acc_s = max(0.50, a_s)
                        best_accent = self._hsl_to_rgb(a_h, acc_l, acc_s)
                        break

                # Create deep, rich ambient background by tinting near-black with dominant hue
                bg_l = 0.05  # 5% lightness ensures high contrast
                bg_s = min(0.40, h_s)
                final_bg = self._hsl_to_rgb(h_h, bg_l, bg_s)

                return PaletteTheme.from_rgb_triplet(
                    bg_rgb=final_bg,
                    highlight_rgb=final_highlight,
                    accent_rgb=best_accent
                )
        except Exception:
            return PaletteTheme.default_theme()

