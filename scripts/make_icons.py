"""由 icons/logo-source.png 轉出網站圖示（PNG／ICO／SVG）。只在換了站徽時手動跑一次。

    pip install pillow
    python scripts/make_icons.py

2026-10-05 起站徽是金股道（GoldenWay）的金色禾穗、緞帶與上揚箭頭——使用者提供的點陣圖，
已經裁成圓形、外面透明。favicon.svg 是一張內嵌 128px PNG 的 SVG：頁首、登入卡片、
manifest 都引用 favicon.svg，所以換站徽不必改任何一個引用的地方。
PNG 一律量化成 256 色：原圖是金色漸層，256 色看不出差別，檔案小五倍。
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

ICONS = Path(__file__).resolve().parents[1] / "src/twsix/report/templates/icons"


def _q(im: Image.Image) -> Image.Image:
    return im.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)


def main() -> None:
    src = Image.open(ICONS / "logo-source.png").convert("RGBA")

    def sz(n: int) -> Image.Image:
        return src.resize((n, n), Image.LANCZOS)

    for n, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        _q(sz(n)).save(ICONS / name, optimize=True)
    bg = Image.new("RGBA", (512, 512), (12, 12, 14, 255))   # maskable：四周留安全區
    bg.alpha_composite(sz(410), (51, 51))
    _q(bg).save(ICONS / "icon-maskable-512.png", optimize=True)
    frames = [sz(16), sz(32), sz(48)]
    frames[2].save(ICONS / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=frames[:2])
    buf = io.BytesIO()
    _q(sz(128)).save(buf, "PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    (ICONS / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 64 64">\n'
        "<!-- 金股道 GoldenWay 站徽：由 scripts/make_icons.py 從 logo-source.png 產生 -->\n"
        f'<image width="64" height="64" href="data:image/png;base64,{b64}" xlink:href="data:image/png;base64,{b64}"/>\n'
        "</svg>\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
