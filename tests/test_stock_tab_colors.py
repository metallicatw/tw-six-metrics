
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
    assert len(ids) == 14, ids
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
    assert _colours(":root:not([data-theme=light]) .tabs ") == \
        _colours(":root[data-theme=dark] .tabs ")


def test_選中的那一顆是實心():
    css = (TPL / "site.css").read_text("utf-8")
    rule = re.search(r"^\.tab\[aria-selected=true\]\{([^}]*)\}", css, re.M).group(1)
    assert "background:var(--tk)" in rule, rule
    assert "color:#fff" in rule, rule
    assert ":root[data-theme=dark] .tab[aria-selected=true]{color:var(--ground)}" in css, (
        "深底上的按鈕色是調亮過的，白字壓不住"
    )


def test_頁內分頁比頁首大分頁小一號_而且降彩度():
    css = (TPL / "site.css").read_text("utf-8")
    nav = re.search(r"^nav\{[^}]*font-size:(\d+(?:\.\d+)?)px", css, re.M | re.S)
    assert nav and float(nav.group(1)) == 15
    rules = {
        ".tab{": css, ".ai-tab{": css, ".wg-tab{": css, ".subtab{": css,
        ".sc-tab{": (TPL / "screener.html.j2").read_text("utf-8"),
        ".cf-tab{": (TPL / "radar.html.j2").read_text("utf-8"),
    }
    for sel, src in rules.items():
        body = src.split("\n" + sel, 1)[1].split("}", 1)[0]
        size = float(re.search(r"font-size:(\d+(?:\.\d+)?)px", body).group(1))
        assert size < 15, (sel, size)
        assert "--tk:color-mix(in srgb,var(--tc) 60%" in body, sel
        assert "color:var(--tc)" not in body, sel
    assert ".subtab{" in css and "font-size:12.5px" in css.split(".subtab{", 1)[1].split("}", 1)[0]


def test_可以左右滑的分頁列不吸附_滑到哪停在哪():
    for p in TPL.rglob("*"):
        if p.suffix in {".css", ".j2", ".html", ".js"}:
            src = p.read_text("utf-8")
            for bad in ("scroll-snap-type", "scroll-snap-align", "scrollSnap"):
                assert bad not in src, (p.name, bad)


def test_全站頁內分頁同一種樣式_照個股頁那一排():
    css = (TPL / "site.css").read_text("utf-8")
    block = css.split("html :is(.tab,.subtab,.sc-tab,.cf-tab,.ai-tab,.wg-tab){", 1)[1].split("}", 1)[0]
    assert "border-radius:7px" in block and "45%" in block and "font-size:13px" in block
