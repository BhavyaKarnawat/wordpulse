"""Color palette and dynamic styling models."""
from dataclasses import dataclass
from typing import Tuple


@dataclass
class PaletteTheme:
    name: str = "Default"
    background: str = "#0a0a0f"
    surface: str = "#141420"
    text_primary: str = "#ffffff"
    text_secondary: str = "rgba(255, 255, 255, 0.45)"
    highlight: str = "#38bdf8"        # Active sung word glow
    accent: str = "#818cf8"           # Accent gradient color
    is_auto: bool = True              # Extracted from album artwork

    @classmethod
    def default_theme(cls) -> "PaletteTheme":
        return cls(
            name="Cosmic Glass",
            background="#08080c",
            surface="rgba(255, 255, 255, 0.06)",
            text_primary="#ffffff",
            text_secondary="rgba(255, 255, 255, 0.40)",
            highlight="#ff2d6f",
            accent="#ffb3c7",
            is_auto=False
        )

    @classmethod
    def from_rgb_triplet(
        cls,
        bg_rgb: Tuple[int, int, int],
        highlight_rgb: Tuple[int, int, int],
        accent_rgb: Tuple[int, int, int]
    ) -> "PaletteTheme":
        return cls(
            name="Album Sync",
            background=f"rgb({bg_rgb[0]}, {bg_rgb[1]}, {bg_rgb[2]})",
            surface="rgba(255, 255, 255, 0.08)",
            text_primary="#ffffff",
            text_secondary="rgba(255, 255, 255, 0.45)",
            highlight=f"rgb({highlight_rgb[0]}, {highlight_rgb[1]}, {highlight_rgb[2]})",
            accent=f"rgb({accent_rgb[0]}, {accent_rgb[1]}, {accent_rgb[2]})",
            is_auto=True
        )

