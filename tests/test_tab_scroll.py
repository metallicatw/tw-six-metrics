
from __future__ import annotations

import re
from pathlib import Path

T = Path(__file__).resolve().parents[1] / "src" / "twsix" / "report" / "templates"


def test_導覽列換頁之後照原位擺():
    base = (T / "base.html.j2").read_text(encoding="utf-8")
    nav_end = base.index("</nav>")
    script = base[nav_end:base.index("</script>", nav_end)]
    assert "<script>" in script[:1500], "記住捲動位置的那段要緊接在 nav 後面（site.js 是 defer，會閃一下）"
    assert "sessionStorage" in script and "scrollLeft" in script
    assert "aria-current" in script, "沒有記錄時要把目前這一頁那一顆捲進畫面"
    assert "try{" in script, "sessionStorage 在無痕／被封鎖時會丟例外"


def test_頁內分頁列點了不會被拉回最左邊():
    js = (T / "site.js").read_text(encoding="utf-8")
    radar = (T / "radar.html.j2").read_text(encoding="utf-8")
    assert "bar.scrollLeft = cur.offsetLeft" not in js, "AI 選股分頁列又把點到的那顆拉到最左邊了"
    assert re.search(r"reveal\(bar, cur\)", js)
    for src in (js, radar):
        assert not re.search(r"scrollLeft\s*=\s*0\b", src), "有地方把分頁列歸零"
    body = radar[radar.index("function open(tab"):radar.index("function bgShow(")]
    assert "scrollLeft +=" in body and "scrollLeft -=" in body, "籌碼雷達的分頁只該捲最少"
