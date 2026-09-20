"""〔台股評等清單〕：十七欄要看得完，而且每一欄說的是它自己的話。

## 量到的（2026-09-20 那一份，無頭瀏覽器）

改之前：

    表格 1,315px，內容欄 1,200px
    → 最右邊兩欄（具投資價值、報酬風險比）**在 1920 的螢幕上也看不到**
    ▲▼（自訂順序）出現在〔評等清單〕上，每一列多佔 24px——而那一頁的順序
      是綜合評分，移動它沒有任何意義
    報酬風險比的數值和背景同色，看不到
    「無風險」顯示成 ∞、「預期報酬為負」顯示成 0.00

改之後：

    1280 / 1400 / 1440 / 1920 四個寬度，十七欄全部看得到，不必橫向捲
    ▲▼ 0/1940 列（只在〔觀察清單〕出現）
    數值顏色 rgb(240,83,63)，背景透明
    非數字的值：無風險 127 檔、空頭 88 檔、— 55 檔

## 三個各自獨立的 bug

1. **`.rr` 撞名。** `site.css` 裡有兩個 `.rr`：這一欄的數值，和個股頁〔建議〕
   那顆徽章。徽章那一條在後面、權重一樣，所以它的 `color:var(--badge-ink)`
   （給有底色的徽章用的墨色）把數值的顏色整個蓋掉——落在沒有底色的表格上就是
   「看不到」。

2. **`[hidden]` 沒有作用。** `.star-cell .mv{display:inline-flex}` 的權重
   (0,2,0) 大於瀏覽器預設的 `[hidden]{display:none}` (0,1,0)，所以 site.js
   那句 `el.hidden` 從來沒有生效過。同一類的錯在 market-monitor 的
   `.mode-toggle-btn[hidden]` 上也犯過一次。

3. **夾住表格的不是視窗，是 `max-width:1240px`。** 所以「換一台大螢幕」不會
   讓那兩欄跑出來，而橫向捲軸在表格下方一整頁的位置，不捲到底根本不知道右邊
   還有東西。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src/twsix/report/templates"
CSS = (TPL / "site.css").read_text(encoding="utf-8")
JS = (TPL / "site.js").read_text(encoding="utf-8")
MACROS = (TPL / "_macros.html.j2").read_text(encoding="utf-8")


def _decl(selector, css=CSS):
    """挑出某一條規則的宣告。選擇器要從行首開始配，免得撈到別人的後代選擇器。"""
    found = re.findall(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, f"找不到規則 {selector}"
    assert len(found) == 1, f"{selector} 出現 {len(found)} 次，測到哪一條說不準"
    return re.sub(r"\s+", " ", found[0]).strip()


# ---------------------------------------------------------------------------
# 1. 數值看得到


def test_報酬風險比不跟建議徽章共用類別名():
    """`.rr` 底下那個是別人——個股頁〔建議〕那顆徽章。

    兩條權重一樣，而徽章那條在後面，所以它贏：數值拿到 `--badge-ink`（給有
    底色的徽章用的墨色），落在沒有底色的表格上就是和背景同一個顏色。

    改名而不是加權重：兩個不相干的東西共用一個名字，遲早會再撞一次。
    """
    assert 'class="rrv' in MACROS, "報酬風險比還在用 .rr"
    assert 'class="rr ' not in MACROS and 'class="rr"' not in MACROS
    for cls in ("rrv-best", "rrv-ok", "rrv-weak", "rrv-bad"):
        assert f".{cls}" in CSS, f"site.css 少了 .{cls}"
    # 徽章那一套還在，而且還是叫 .rr——這條測試守的是「兩者分開」，
    # 不是「把徽章改名」。
    assert ".rr-可買進" in CSS
    # 舊名字要整個消失。留著的話，哪天有人把 macro 改回去，畫面又會變成
    # 「看不到」，而 CSS 那邊看起來一切正常（規則都在）。
    for old_cls in (".rr-best", ".rr-ok", ".rr-weak", ".rr-bad"):
        assert old_cls not in CSS, f"{old_cls} 還在——那是會被徽章那條蓋掉的舊名字"


def test_無風險和空頭都寫成字():
    """∞ 要先知道它代表什麼才看得懂，而 0.00 看起來像「算出來剛好是零」。

    清單上最常被問的就是「∞ 是好還是壞」。兩個都直接寫成中文。
    """
    macro = MACROS[MACROS.index("{% macro reward(r) -%}"):]
    macro = macro[:macro.index("{%- endmacro %}")]
    # 註解要先拿掉：底下那句「以前印 ∞」本身就含有 ∞，而它是說明不是輸出。
    macro = re.sub(r"\{#.*?#\}", "", macro, flags=re.DOTALL)
    assert "無風險" in macro, "沒有風險的那一種還沒改成「無風險」"
    assert "空頭" in macro, "預期報酬為負的那一種還在印 0.00"
    assert "∞" not in macro, f"還留著 ∞：{macro}"
    # 三種說不通的值要分得開，混在一起是這個欄位最容易犯的錯。
    assert "r.risk_free" in macro
    assert "r.reward_risk is none" in macro
    assert "r.reward_risk <= 0" in macro, (
        "「預期報酬為負」沒有自己的分支，會掉進一般數字那一支印成 0.00"
    )


def test_排序鍵和畫面上的字是分開的():
    """畫面改成中文，排序**不可以**跟著改成照字串排。

    「無風險」要排在最前面、「—」要沉到底，而這兩件事在資料裡長得一模一樣
    （`reward_risk` 都是 None）。
    """
    key = MACROS[MACROS.index("{% macro reward_key(r) -%}"):]
    key = key[:key.index("{%- endmacro %}")]
    assert "999999" in key, "無風險沒有排在最前面"
    assert "-999" in key, "算不出來的沒有沉到底"


# ---------------------------------------------------------------------------
# 2. ▲▼ 只在觀察清單


def test_hidden_要壓得過那條_display():
    """`.star-cell .mv{display:inline-flex}` 的權重 (0,2,0) 大於瀏覽器預設的

    `[hidden]{display:none}` (0,1,0)。少了這一條，site.js 那句 `el.hidden`
    從頭到尾沒有作用過，而症狀是 ▲▼ 在〔評等清單〕上也照樣出現。
    """
    assert ".star-cell .mv[hidden]" in CSS, (
        "少了 .star-cell .mv[hidden]——hidden 屬性壓不過上面那條 display"
    )
    base = CSS.index(".star-cell .mv{")
    guard = CSS.index(".star-cell .mv[hidden]")
    assert guard > base, "[hidden] 那一條寫在 display 前面，權重一樣所以輸了"
    assert "display:none" in CSS[guard:guard + 60]


def test_只有觀察清單才裝那幾顆鈕():
    """JS 那一邊的守門。`watchOrder` 是唯一的開關，三個地方都要看它。"""
    assert "table.getAttribute('data-watchlist') === '1'" in JS
    paint = JS[JS.index("function paintMoves()"):]
    paint = paint[:paint.index("\n  }") + 4]
    assert "if(!watchOrder) return;" in paint, "paintMoves 沒有先看 watchOrder"


# ---------------------------------------------------------------------------
# 3. 置頂


def test_有一顆置頂鈕():
    """一份觀察清單十幾檔，「把這一檔提到最上面」用上移要按到第十幾次。"""
    assert 'class="mv-top"' in MACROS
    assert 'data-delta="top"' in MACROS
    assert "function top(code)" in JS, "TWSIXWatch 沒有 top()"
    assert re.search(r"move: move, top: top", JS), "top() 沒有掛出來"


def test_置頂的字不是罕見符號():
    """⤒ 之類的箭頭在部分系統字型裡是空格或方框。這一頁本來就是中文的。"""
    btn = MACROS[MACROS.index('class="mv-top"'):]
    btn = btn[:btn.index("</button>")]
    assert ">頂" in btn, f"置頂鈕的字不是「頂」：{btn[-40:]}"


def test_置頂和上移走同一個處理器():
    """「先切回自訂順序、動完重排、焦點跟著走」三步兩者完全一樣。

    分開寫的話改了一邊就會有一邊沒改到，而那沒有任何症狀——直到有人發現
    按〔置頂〕之後排序指示器沒有清掉。
    """
    h = JS[JS.index("var btn = e.target.closest('button[data-move]');"):]
    h = h[:h.index("\n    });") + 7]
    assert "TWSIXWatch.top(code)" in h
    assert "TWSIXWatch.move(code, +delta)" in h
    assert h.count("applyCustomOrder();") >= 2, "動完沒有重排"


def test_第一列的置頂要變灰():
    """按了不會有事的按鈕不該看起來可以按——和〔上移〕同一條規則。"""
    paint = JS[JS.index("function paintMoves()"):]
    paint = paint[:paint.index("\n  }") + 4]
    assert "button.mv-top" in paint
    assert "tp.disabled = i === 0" in paint


# ---------------------------------------------------------------------------
# 4. 十七欄看得完


def test_清單那張表在寬螢幕上突出內容欄():
    """夾住它的不是視窗，是 `.wrap` 的 `max-width:1240px`——所以「換一台大螢幕」

    不會讓最右邊那兩欄跑出來。
    """
    assert 'class="scroll wide"' in (TPL / "list.html.j2").read_text(encoding="utf-8")
    assert 'class="scroll wide"' in (TPL / "watchlist.html.j2").read_text(encoding="utf-8")
    d = _decl(".scroll.wide")
    assert "width:min(" in d and "100vw" in d, f"沒有跟著視窗放寬：{d}"
    assert "margin-left:calc(" in d, f"沒有往兩側撐開，只會被 .wrap 夾住：{d}"
    # 上限。再寬下去每一列會長到眼睛追不回行首。
    assert "1600px" in d, d


def test_格子有收緊():
    """十七欄各省 8px 就是 136px。字級沒有動，收的是留白。"""
    d = _decl("#t th,#t td")
    m = re.search(r"padding:(\d+)px (\d+)px", d)
    assert m, d
    base = _decl("th,td")
    bm = re.search(r"padding:(\d+)px (\d+)px", base)
    assert bm, base
    assert int(m.group(2)) < int(bm.group(2)), (
        f"清單那張表沒有比一般表格緊：{m.group(0)} vs {bm.group(0)}"
    )


def test_燈泡和標題並排():
    """不包在同一個 inline-flex 裡的話，燈泡接在 `報酬<br>風險比` 後面會自己

    掉到第三行去——整列標題被撐高一截，而那顆燈泡看起來像是下一欄的東西。
    """
    assert '<span class="hdtip">' in MACROS
    d = _decl("thead th .hdtip")
    assert "inline-flex" in d, d
    assert "align-items:center" in d, f"沒有對齊兩行標題的中線：{d}"


def test_說明出界會被推回來():
    """〔報酬風險比〕是最右邊那一欄，而它在一個**橫向捲動**的表格裡。

    `.flip`（改成 right:0）只是換一個出界的方向——那一欄本身可能已經被捲到
    畫面外了。所以翻面之後還要量一次，出界就推回來。

    推的方式是 `transform`，不是 `margin-left`：翻面之後這個盒子是
    `left:auto;right:0`，絕對定位在那個組合下解的是 left，margin 被吃進那條
    方程式裡推不動它（實測 -145px 下去，量到的位置一個像素都沒變）。
    """
    show = JS[JS.index("function show(tip)"):]
    show = show[:show.index("\n  }") + 4]
    assert "classList.add('flip')" in show
    assert "translateX(" in show, f"沒有把出界的說明推回來：{show}"
    assert "marginLeft" not in show, "又改回 margin-left 了——那個推不動 right:0 的盒子"
    # 推完要清掉，不然下一次打開會帶著上一次的位移。
    #
    # `function close(){` 在這份 JS 裡有好幾個（搜尋框也有一個），所以從
    # `show()` 往**回**找最近的那一個——它們是同一段裡的一對。
    close_at = JS.rindex("function close(){", 0, JS.index("function show(tip)"))
    close = JS[close_at:]
    close = close[:close.index("\n  }") + 4]
    assert "transform = ''" in close, f"關掉的時候沒有把位移清掉：{close}"
