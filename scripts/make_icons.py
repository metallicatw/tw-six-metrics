"""由 icons/favicon.svg 轉出網站圖示（PNG／ICO）。只在改了站徽時手動跑一次。

    pip install cairosvg pillow
    python scripts/make_icons.py

16px 用簡化版（拿掉星芒、反光與浪頭細線、折線加粗），不然在分頁上只剩一團。
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import cairosvg
from PIL import Image

ICONS = Path(__file__).resolve().parents[1] / "src/twsix/report/templates/icons"


def _png(svg: str, size: int) -> Image.Image:
    data = cairosvg.svg2png(bytestring=svg.encode(), output_width=size, output_height=size)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def _small(svg: str) -> str:
    svg = re.sub(r"<!-- 靈光一閃 -->\s*<path[^>]*/>", "", svg)
    svg = re.sub(r'<path d="M12 44\.2[^>]*/>', "", svg)
    svg = re.sub(r'<path d="M18\.4 26\.6[^>]*/>', "", svg)
    svg = svg.replace('stroke-width="3.3"', 'stroke-width="4.4"')
    return svg.replace('viewBox="0 0 64 64"', 'viewBox="3 1 60 60"')


def main() -> None:
    svg = (ICONS / "favicon.svg").read_text(encoding="utf-8")
    small = _small(svg)
    for size, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        _png(svg, size).save(ICONS / name, optimize=True)
    bg = Image.new("RGBA", (512, 512), (8, 26, 34, 255))   # maskable：四周留安全區
    bg.alpha_composite(_png(svg, 410), (51, 51))
    bg.save(ICONS / "icon-maskable-512.png", optimize=True)
    frames = [_png(small, 16), _png(small, 32), _png(svg, 48)]
    frames[2].save(ICONS / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=frames[:2])


if __name__ == "__main__":
    main()
