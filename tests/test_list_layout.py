import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src/twsix/report/templates"
CSS = (TPL / "site.css").read_text(encoding="utf-8")
JS = (TPL / "site.js").read_text(encoding="utf-8")
MACROS = (TPL / "_macros.html.j2").read_text(encoding="utf-8")


def _decl(selector, css=CSS):
    found = re.findall(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, f"找不到規則 {selector}"
    assert len(found) == 1, f"{selector} 出現 {len(found)} 次，測到哪一條說不準"
    return re.sub(r"\s+", " ", found[0]).strip()


def _macro(name):
    i = MACROS.index("{% macro " + name)
    j = MACROS.index("{%- endmacro %}", i)
    return MACROS[i:j]




def test_報酬風險比不跟建議徽章共用類別名():
    assert 'class="rrv' in MACROS, "報酬風險比還在用 .rr"
    assert 'class="rr ' not in MACROS and 'class="rr"' not in MACROS
    for cls in ("rrv-best", "rrv-ok", "rrv-weak", "rrv-bad"):
        assert f".{cls}" in CSS, f"site.css 少了 .{cls}"
    assert ".rr-可買進" in CSS
    for old_cls in (".rr-best", ".rr-ok", ".rr-weak", ".rr-bad"):
        assert old_cls not in CSS, f"{old_cls} 還在——那是會被徽章那條蓋掉的舊名字"


def test_無風險和價格高估都寫成字():
    macro = MACROS[MACROS.index("{% macro reward(r) -%}"):]
    macro = macro[:macro.index("{%- endmacro %}")]
    macro = re.sub(r"\{#.*?#\}", "", macro, flags=re.DOTALL)
    assert "無風險" in macro, "沒有風險的那一種還沒改成「無風險」"
    assert "價格高估" in macro, "預期報酬為負的那一種還在印 0.00"
    assert "空頭" not in macro.replace("不是走勢的空頭", "")
    assert "∞" not in macro, f"還留著 ∞：{macro}"
    assert "r.risk_free" in macro
    assert "r.reward_risk is none" in macro
    assert "r.reward_risk <= 0" in macro, (
        "「預期報酬為負」沒有自己的分支，會掉進一般數字那一支印成 0.00"
    )


def test_排序鍵和畫面上的字是分開的():
    key = MACROS[MACROS.index("{% macro reward_key(r) -%}"):]
    key = key[:key.index("{%- endmacro %}")]
    assert "999999" in key, "無風險沒有排在最前面"
    assert "-999" in key, "算不出來的沒有沉到底"




def test_hidden_要壓得過那條_display():
    assert ".star-cell .mv[hidden]" in CSS, (
        "少了 .star-cell .mv[hidden]——hidden 屬性壓不過上面那條 display"
    )
    base = CSS.index(".star-cell .mv{")
    guard = CSS.index(".star-cell .mv[hidden]")
    assert guard > base, "[hidden] 那一條寫在 display 前面，權重一樣所以輸了"
    assert "display:none" in CSS[guard:guard + 60]


def test_只有觀察清單才裝那幾顆鈕():
    assert "table.getAttribute('data-watchlist') === '1'" in JS
    paint = JS[JS.index("function paintMoves()"):]
    paint = paint[:paint.index("\n  }") + 4]
    assert "if(!watchOrder) return;" in paint, "paintMoves 沒有先看 watchOrder"




def test_有一顆置頂鈕():
    assert 'class="mv-top"' in MACROS
    assert 'data-delta="top"' in MACROS
    assert "function top(code)" in JS, "TWSIXWatch 沒有 top()"
    assert re.search(r"move: move, top: top", JS), "top() 沒有掛出來"


def test_置頂的字不是罕見符號():
    btn = MACROS[MACROS.index('class="mv-top"'):]
    btn = btn[:btn.index("</button>")]
    assert ">頂" in btn, f"置頂鈕的字不是「頂」：{btn[-40:]}"


def test_置頂和上移走同一個處理器():
    h = JS[JS.index("var btn = e.target.closest('button[data-move]');"):]
    h = h[:h.index("\n    });") + 7]
    assert "TWSIXWatch.top(code)" in h
    assert "TWSIXWatch.move(code, +delta)" in h
    assert h.count("applyCustomOrder();") >= 2, "動完沒有重排"


def test_第一列的置頂要變灰():
    paint = JS[JS.index("function paintMoves()"):]
    paint = paint[:paint.index("\n  }") + 4]
    assert "button.mv-top" in paint
    assert "tp.disabled = i === 0" in paint




def test_清單那張表左右切齊標題下方的分隔線():
    assert 'class="scroll wide"' in (TPL / "list.html.j2").read_text(encoding="utf-8")
    assert 'class="scroll wide"' in (TPL / "watchlist.html.j2").read_text(encoding="utf-8")
    box = _decl(".scroll.wide")
    assert "width:auto" in box and "transform:none" in box and "margin-left:0" in box, box
    assert "fit-content" not in box and "translateX" not in box, box
    assert "width:100%" in _decl("#t")


def test_格子有收緊():
    d = _decl("#t th,#t td")
    m = re.search(r"padding:(\d+)px (\d+)px", d)
    assert m, d
    base = _decl("th,td")
    bm = re.search(r"padding:(\d+)px (\d+)px", base)
    assert bm, base
    assert int(m.group(2)) < int(bm.group(2)), (
        f"清單那張表沒有比一般表格緊：{m.group(0)} vs {bm.group(0)}"
    )


def test_標題和數值站在同一條軸上():
    d = _decl("#t th.mid,#t td.mid")
    assert "text-align:center" in d, d
    rows = _macro("row(r,")
    assert rows.count('class="mid"') + rows.count('mid"') >= 6, rows.count('mid"')
    head = _macro("table_head(")
    n_mid = head.count('class="mid"') + head.count('class="num mid"')
    assert n_mid == 14, (
        f"標題只有 {n_mid} 欄置中，應該是 14 欄"
        "（六個等第＋市場＋具投資價值＋綜合評分＋評分變化＋報酬風險比"
        "＋日漲跌、5 日、20 日漲跌）"
    )


def test_左讀的那幾欄不置中():
    rows = _macro("row(r,")
    for cell in ('class="when-cell"', 'data-s="{{ r.name }}"',
                 'data-s="{{ r.industry }}"'):
        assert cell in rows, f"找不到 {cell}，欄位是不是改名了？"
        i = rows.index(cell)
        start = rows.rindex("<td", 0, i)
        opening = rows[start:rows.index(">", i)]
        assert "mid" not in opening, f"這一欄被置中了：{opening[:90]}"


def test_燈泡和標題並排():
    assert '<span class="hdtip">' in MACROS
    d = _decl("thead th .hdtip")
    assert "inline-flex" in d, d
    assert "align-items:center" in d, f"沒有對齊兩行標題的中線：{d}"
    spacer = _decl("thead th .hdtip::before")
    assert "width:var(--bulb)" in spacer, f"配重不是照燈泡的寬度算的：{spacer}"
    assert "--bulb:" in d, f"`--bulb` 不在同一條規則上，兩邊會各改各的：{d}"
    bulb = _decl("thead th .hdtip .bulb")
    assert "min-width:var(--bulb)" in bulb, (
        f"燈泡自己沒有被釘在那個寬度上，配重就配不準：{bulb}"
    )


def test_說明出界會被推回來():
    show = JS[JS.index("function show(tip)"):]
    show = show[:show.index("\n  }") + 4]
    assert "classList.add('flip')" in show
    assert "translateX(" in show, f"沒有把出界的說明推回來：{show}"
    assert "marginLeft" not in show, "又改回 margin-left 了——那個推不動 right:0 的盒子"
    close_at = JS.rindex("function close(){", 0, JS.index("function show(tip)"))
    close = JS[close_at:]
    close = close[:close.index("\n  }") + 4]
    assert "transform = ''" in close, f"關掉的時候沒有把位移清掉：{close}"


def test_窄版的嵌入報告要夠高():
    rules = re.findall(r"(?m)^\s*iframe\.embed(?:,iframe\.embed\.tall)?\s*\{([^}]*)\}", CSS)
    assert len(rules) == 2, f"iframe.embed 有 {len(rules)} 條規則，預期基準一條＋窄版一條"
    base, narrow = (re.sub(r"\s+", " ", r) for r in rules)
    assert "78vh" in base, base
    narrow_vh = int(re.search(r"height:(\d+)vh", narrow).group(1))
    assert narrow_vh > 78, f"窄版的高度 {narrow_vh}vh 沒有比桌機的 78vh 高"
    block = CSS[CSS.index("@container page (max-width:760px)"):]
    block = block[:block.index("\n}")]
    assert "iframe.embed" in block, "窄版那一條不在 @container page 裡"
