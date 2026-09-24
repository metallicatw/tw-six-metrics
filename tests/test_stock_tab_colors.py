"""個股頁的分頁列是按鈕，一顆一個顏色（2026-09-23）。

守三件事：模板上的每一個分頁都有自己的顏色（淺色、深色各一份）、同一個主題裡
沒有兩顆撞色、選中的那一顆是實心的。少了其中一份的症狀都是「那一顆變回預設
色」——畫面不會壞，只是那一顆和旁邊的分不開，而那正是這次改動要解決的事。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src/twsix/report/templates"


def _tab_ids():
    page = (TPL / "stockpage.html.j2").read_text("utf-8")
    bar = page[page.index('<div class="tabs"'):]
    bar = bar[:bar.index("</div>")]
    return re.findall(r'role="tab" id="tab-([a-z]+)"', bar)


def _colours(prefix):
    css = (TPL / "site.css").read_text("utf-8")
    pat = re.escape(prefix) + r"#tab-([a-z]+)\{--tc:(#[0-9a-f]{6})\}"
    return dict(re.findall(pat, css))


def test_十三顆分頁都在():
    ids = _tab_ids()
    assert len(ids) == 14, ids                     # 十三個內容分頁（含〔AI 選股〕）＋〔尚未建置〕
    assert ids[:5] == ["summary", "six", "eps", "health", "pxhealth"], ids


def test_每一顆都有自己的顏色而且不撞色():
    ids = _tab_ids()
    for prefix in (".tabs ", ":root:not([data-theme=light]) .tabs ",
                   ":root[data-theme=dark] .tabs "):
        got = _colours(prefix)
        missing = [i for i in ids if i not in got]
        assert not missing, f"{prefix!r} 少了 {missing} 的顏色"
        content = [got[i] for i in ids if i != "unbuilt"]
        assert len(set(content)) == len(content), f"{prefix!r} 有兩顆同色：{got}"


def test_深色的兩份一模一樣():
    """深色有兩個入口（跟系統、手動切換），兩份不一樣時切換前後顏色會跳。"""
    assert _colours(":root:not([data-theme=light]) .tabs ") == \
        _colours(":root[data-theme=dark] .tabs ")


def test_選中的那一顆是實心():
    css = (TPL / "site.css").read_text("utf-8")
    rule = re.search(r"^\.tab\[aria-selected=true\]\{([^}]*)\}", css, re.M).group(1)
    assert "background:var(--tc)" in rule, rule
    assert "color:#fff" in rule, rule
    assert ":root[data-theme=dark] .tab[aria-selected=true]{color:var(--ground)}" in css, (
        "深底上的按鈕色是調亮過的，白字壓不住"
    )
