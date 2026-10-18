
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
    bg = Image.new("RGBA", (512, 512), (12, 12, 14, 255))
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
