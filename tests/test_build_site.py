"""`twsix build` — and specifically, whether the site gets the good page.

This file exists because of a gap that survived a month and every test in the
suite.  Ten sections were built, tested, screenshotted and committed, and none
of them ever reached the deployed site: ``twsix page`` rendered them and
``twsix build`` did not call it, so ``stock/5439.html`` on GitHub Pages stayed
a 21 KB grade table while the real page — 116 KB — existed only on whichever
machine had run the fetch.

Nothing caught it because every test asked "does the page render correctly",
which it did.  Nobody asked "does the site contain it".  So that is what this
file asks.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from test_stock_page import _full_grids
from twsix.report.build import build_site

ROOT = Path(__file__).resolve().parent


def _records() -> list[dict[str, str]]:
    """Two stocks' worth of the stored rating table, straight off data/."""
    path = ROOT.parent / "data" / "ratings.csv"
    wanted = {"5439", "2330"}
    with path.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["stock_id"] in wanted]


def _sheets(tmp: Path) -> Path:
    """A sheets directory holding 5439 and nothing else."""
    base = tmp / "sheets" / "5439"
    base.mkdir(parents=True)
    for name, grid in _full_grids().items():
        (base / f"{name}.json").write_text(
            json.dumps(grid, ensure_ascii=False), encoding="utf-8"
        )
    return tmp / "sheets"


def served(out: Path, name: str) -> str:
    """一張頁面 **加上它連進來的共用檔案**——瀏覽器實際看到的全部。

    樣式與腳本從每一張頁面裡抽出來變成 assets/site.css、assets/site.js 之後，
    「這段腳本在不在頁面上」就不能只讀那張 HTML 了。這個 helper 把連結的檔案接
    回去，於是斷言問的還是同一件事：讀者的瀏覽器拿不拿得到這段程式。
    """
    page = (out / name).read_text(encoding="utf-8")
    parts = [page]
    for asset in ("site.css", "site.js"):
        if asset in page:
            parts.append((out / "assets" / asset).read_text(encoding="utf-8"))
    return "\n".join(parts)



def test_a_fetched_stock_gets_the_full_page_in_the_site(tmp_path=None):
    """The whole point: 河流圖 and 個股新聞 must be *in the built site*."""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    assert 'id="river"' in page, "河流圖不在網站上"
    assert 'id="news"' in page, "個股新聞不在網站上"
    assert "river-fig" in page, "河流圖有區塊但沒有圖"
    assert 'ol class="news"' in page
    assert written.get("  其中完整版") == 1


def test_a_stock_without_sheets_still_gets_the_plain_page(tmp_path=None):
    """1,740 of 1,741 have no cache; they must not 404 or crash the build."""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    plain = (out / "stock" / "2330.html").read_text(encoding="utf-8")
    assert plain, "沒有抓過資料的股票應該還是有頁面"
    assert 'id="river"' not in plain
    assert len(plain) < 60_000  # the grade table, not the ten sections


def test_the_list_marks_which_codes_lead_to_a_full_page(tmp_path=None):
    """Otherwise the one good page is findable only by clicking 1,741 codes."""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="tag full"' in listing
    # The mark is a word, so it survives greyscale and forced colours.
    assert "完整" in listing


def test_the_mark_follows_the_render_not_the_directory(tmp_path=None):
    """A stock whose cache is unusable falls back — and must not be marked.

    Promising a full page and serving the grade table is worse than serving
    the grade table, so the marked set is the set of renders that succeeded.
    """
    tmp = tmp_path or _tmp()
    sheets = tmp / "sheets"
    (sheets / "2330").mkdir(parents=True)
    (sheets / "2330" / "ISQ.json").write_text("[[]]", encoding="utf-8")

    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=sheets)

    assert written.get("  其中完整版") is None
    assert 'class="tag full"' not in (out / "index.html").read_text(encoding="utf-8")
    assert (out / "stock" / "2330.html").is_file()


def test_no_sheets_directory_at_all_builds_the_old_way(tmp_path=None):
    """The site must not require a cache — it is a market-wide screener first."""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=None)
    assert written["stock/*.html"] == 2
    assert "  其中完整版" not in written


def _tmp() -> Path:
    """The suite runs without pytest, so no fixtures — a temp dir of our own."""
    import tempfile

    return Path(tempfile.mkdtemp(prefix="twsix-site-"))


# -- 全站個股搜尋 ----------------------------------------------------------


def test_the_search_index_lists_every_stock_not_only_the_fetched_ones(tmp_path=None):
    """Typing 2330 must say what the site knows, even with no full page.

    「找不到」 for a stock that is plainly in 評等清單 reads as a broken search
    rather than as missing data, so the index is the whole market and the
    fifth field is what separates the two.
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    index = json.loads((out / "search.json").read_text(encoding="utf-8"))
    codes = {row[0] for row in index}
    assert codes == {"5439", "2330"}
    by_code = {row[0]: row for row in index}
    assert by_code["5439"][4] == 1  # has the full page
    assert by_code["2330"][4] == 0  # listed, but only the grade table


def test_the_index_row_is_the_shape_the_script_reads():
    """[代號, 名稱, 產業, 綜合評分, 有無完整頁] — the order is a contract.

    It is read back in exactly one place, an inline script in base.html.j2,
    which cannot import anything.  Pinning it here is the only thing standing
    between a reordered field and a search box that shows industries where
    names should be.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    row = next(
        r
        for r in json.loads((out / "search.json").read_text(encoding="utf-8"))
        if r[0] == "5439"
    )
    assert len(row) == 5
    assert row[1] == "高技"
    assert row[2] and not row[2][0].isdigit()  # 產業, not a number
    assert row[3].count(".") == 1 and len(row[3].split(".")[1]) == 2  # 兩位小數
    assert row[4] in (0, 1)


def test_the_score_is_rounded_in_the_file_not_in_the_browser():
    """Ten digits shipped to be formatted away on arrival wastes them twice."""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    text = (out / "search.json").read_text(encoding="utf-8")
    assert "3333333" not in text
    assert "6666666" not in text


def test_every_page_carries_the_search_box(tmp_path=None):
    """Including the stock pages — that is the point of putting it in base."""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    for name in ("index.html", "picks.html", "stats.html", "about.html"):
        page = served(out, name)
        assert 'id="find"' in page, f"{name} 沒有搜尋框"
        assert "search.json" in page, f"{name} 沒有載入索引"
    for code in ("5439", "2330"):
        page = served(out, f"stock/{code}.html")
        assert 'id="find"' in page, f"{code} 的頁面沒有搜尋框"


def test_the_search_box_still_goes_somewhere_without_javascript():
    """A form wrapping the input, pointing at a page that lists everything.

    The combobox is an enhancement; with scripting off, submitting must still
    reach 評等清單, which has its own filter and every stock in it.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "index.html").read_text(encoding="utf-8")
    assert 'action="index.html"' in page
    assert 'name="q"' in page


def test_the_stock_page_search_box_resolves_paths_from_its_own_depth():
    """stock/5439.html is one level down; its links must not 404."""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    # rel 現在由每頁一行的 window.TWSIX 帶進來，腳本本身是全站共用的靜態檔。
    assert 'window.TWSIX={rel:"../"' in page
    assert 'action="../index.html"' in page
    assert 'href="../assets/site.css' in page and 'src="../assets/site.js' in page
    assert "base=TWSIX.rel" in served(out, "stock/5439.html")


# -- 這一輪的版面決定 ------------------------------------------------------


def test_the_three_stale_pages_are_unlinked_but_still_built():
    """〔具投資價值〕〔評等統計〕〔評分規則〕 all read a year-old snapshot.

    A ranked pick list computed from stale data is not merely out of date, it
    is confidently out of date, and no nav label says 「這是去年的」 loudly
    enough.  So the links go.  The files stay: hiding is a link-level
    decision, and someone holding one of these URLs should get the page — with
    the site's own staleness banner on it — rather than a 404.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    import re

    nav = re.search(r"<nav>(.*?)</nav>", (out / "index.html").read_text("utf-8"), re.S)
    labels = re.findall(r">([^<>]+)</a>", nav.group(1))
    assert labels == ["評等清單", "觀察清單"]
    for name in ("picks.html", "stats.html", "about.html"):
        assert (out / name).is_file(), f"{name} 不該被刪掉，只是不連過去"
    # 評等清單 is the front door now; the old URL still resolves.
    old = (out / "list.html").read_text("utf-8")
    assert "index.html" in old and "refresh" in old


def test_the_stock_page_is_tabs_rather_than_one_long_scroll():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")

    # 分頁數和面板數必須相等——多一個按鈕就是一個點了沒反應的分頁，多一個面板
    # 就是一段永遠打不開的內容。
    tabs = page.count('role="tab"')
    assert tabs == page.count('class="panel"')
    # 〔財報圖表〕併進〔六大財務指標評等〕之後少一個。
    assert tabs == 9
    assert 'id="tab-statements"' not in page
    # Exactly one panel open on arrival, and it is the first.
    assert page.count('role="tabpanel" aria-labelledby="tab-summary">') == 1
    assert page.count("hidden>") >= tabs - 1
    # The three rows a reader needs on every tab stay put.
    assert 'class="ident sticky"' in page


def test_the_build_stamp_is_taipei_time():
    """民國 quarters and 月營收 read against a UTC clock made the reader do
    arithmetic to answer 「這是多久以前的」."""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    text = (out / "index.html").read_text("utf-8")
    assert "台北時間" in text
    assert "UTC" not in text


def test_the_dropped_section_is_gone_from_the_page_and_the_code():
    """〔財務指標評等預估〕 showed four scenarios and no numbers."""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")
    assert "財務指標評等預估" not in page
    assert 'id="tab-scenarios"' not in page


# -- 線上版的抓取路徑 ------------------------------------------------------


def test_the_published_site_can_ask_github_to_fetch_a_stock():
    """The one thing GitHub Pages can do that a static page normally cannot.

    It cannot fetch the mirrors — the browser refuses the cross-origin request
    and the engine is Python — but it can *ask the repository to*, with a
    workflow_dispatch POST to the REST API, which is CORS-enabled.  One press,
    no navigation; the panel then polls the run and the site.

    The issue detour this replaced is gone rather than kept as a fallback: it
    turned one press into a page full of other buttons and an editable stock
    code, and it never closed itself.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "index.html")

    assert '"owner/repo"' in page
    assert "/dispatches" in page
    assert "api.github.com" in page
    assert "issues/new" not in page


def test_the_page_watches_for_its_own_result_rather_than_telling_you_to_wait():
    """search.json is same-origin, so no API, no CORS, no rate limit.

    The flag in field 5 flips when the stock gets a full page, which is exactly
    the signal 「好了沒」 needs.  Cache-busted because the Pages CDN would
    otherwise hand back the same file for minutes.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "index.html")

    assert "search.json?t=" in page
    assert "no-store" in page


def test_no_repo_configured_means_no_offer():
    """A fork, or a site published elsewhere, must not point back here."""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="")
    page = served(out, "index.html")

    assert "metallicatw" not in page
    assert 'repo:""' in page or "repo:''" in page


def test_the_unfetched_stock_page_offers_both_paths_from_one_implementation():
    """`twsix serve` fetches on the spot; GitHub Pages asks the repo.

    Same button, same built HTML — which of the two it does is decided at load
    time by whether /api/ping answers.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "stock/2330.html")

    assert "twsixLive" in page and "twsixCanAsk" in page
    assert "twsixFetch" in page and "twsixAskGithub" in page


def test_the_wait_survives_navigating_away():
    """3711's failure mode: press the button, follow the issue link, lose it.

    The timer lives in one page's JavaScript, and the reader does not stay
    put — the bot's comment links straight to the stock page, so the very
    action the flow invites is the one that killed the wait.  sessionStorage
    carries it across, and landing on the stock's own page means a reload
    rather than a navigation to where you already are.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "stock/2330.html")

    assert "sessionStorage" in page
    assert "twsix.pending" in page
    assert "location.reload" in page


# ---------------------------------------------------------------------------
# 這一段測的不是排版，是「按了沒反應」。
#
# 那個 bug 只有一行：清單裡的小按鈕呼叫 askGithub()，而函式當時叫 grabOnline。
# 瀏覽器丟一個 ReferenceError 就安靜地不做事——沒有錯誤訊息、沒有面板、沒有任何
# 跡象，看起來就是按鈕壞了。Python 測試看不見這種錯，因為它不執行 JavaScript。
#
# 所以退一步用靜態的方式問同一件事：頁面裡每一個被呼叫的名字，都有被定義嗎？

_JS_GLOBALS = frozenset(
    ["if", "for", "while", "switch", "catch", "return", "typeof", "function", "new", "delete", "void", "fetch", "setTimeout", "setInterval", "clearInterval", "clearTimeout", "encodeURIComponent", "decodeURIComponent", "parseInt", "parseFloat", "isNaN", "String", "Number", "Boolean", "Object", "Array", "JSON", "Date", "Math", "Promise", "Error", "RegExp", "Set", "Map", "alert", "confirm", "require"]
)


def _script_bodies(page: str) -> str:
    out = []
    rest = page
    while "<script>" in rest:
        _, rest = rest.split("<script>", 1)
        body, rest = rest.split("</script>", 1)
        out.append(body)
    return "\n".join(out)


def test_every_function_the_page_calls_is_a_function_the_page_defines():
    """按了沒反應的那個 bug：呼叫 askGithub()，定義的卻叫 grabOnline。

    ReferenceError 在瀏覽器裡是靜默的——事件處理器直接不執行，畫面上什麼都不會
    發生。這個測試不執行 JavaScript，只問一個保守的問題：script 裡每個 `名字(`
    形式的呼叫，都找得到對應的定義嗎？找不到就是那一類的錯字。
    """
    import re

    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")

    for name in ("index.html", "stock/2330.html", "stock/5439.html"):
        js = _script_bodies(served(out, name))
        # 前面接著 `.` 的是方法呼叫，屬於某個物件，不在這裡的判斷範圍。
        called = {
            m.group(1)
            for m in re.finditer(r"(?<![.\w$])([a-zA-Z_$][\w$]*)\s*\(", js)
        }
        defined = set(re.findall(r"function\s+([a-zA-Z_$][\w$]*)\s*\(", js))
        defined |= set(re.findall(r"(?:var|let|const)\s+([a-zA-Z_$][\w$]*)\s*=", js))
        missing = sorted(called - defined - _JS_GLOBALS)
        assert not missing, f"{name} 呼叫了沒有定義的函式：{missing}"


def test_the_fetch_button_sits_next_to_the_search_box():
    """一顆按鈕，一個對象：搜尋框裡的那一檔。

    上一版把它放在個股頁最底下，離「要抓哪一檔」最遠的地方，而搜尋結果旁邊那顆
    小標籤又壞著——所以正常的路徑（打代號、按抓取）是死的，只有捲到頁尾才找得到
    活的入口。現在只剩頁首那一顆。
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")

    index = (out / "index.html").read_text("utf-8")
    assert 'id="grabnow"' in index
    # 在搜尋表單裡面，不是頁面某處
    form = index.split('class="find"', 1)[1].split("</form>", 1)[0]
    assert 'id="grabnow"' in form

    thin = (out / "stock" / "2330.html").read_text("utf-8")
    assert 'data-grab="2330"' in thin  # 停在這一頁時按鈕預設指這一檔
    assert 'data-full="1"' not in thin  # 還沒有完整報告（腳本裡的 getAttribute 不算）
    assert 'id="grab-btn"' not in thin  # 底部那顆已經沒了
    assert "GitHub issue" not in thin  # 連同那句說明

    # 已經完整的那一檔也要能重抓：資料會過期，而且後來新增的區塊（大戶持股、
    # 董監持股）只能靠重抓補上。上一版把它當成「沒有對象」，按鈕就消失了——
    # 於是成功抓過一次的股票反而是唯一補不到新東西的。
    #
    # 字是「立即更新」不是「重新抓取」：按鈕上該寫的是按下去會發生什麼事。
    full = (out / "stock" / "5439.html").read_text("utf-8")
    assert 'data-grab="5439"' in full
    assert 'data-full="1"' in full
    assert "立即更新" in served(out, "stock/5439.html")


def test_the_mark_is_the_update_date_when_the_fetch_left_one(tmp_path=None):
    """「完整」只說了有沒有，沒說什麼時候——而讀者要判斷的是後者。

    一份三個月前抓的完整報告和昨天抓的，在舊版清單上是同一個字。日期同時回答
    兩件事：有這個標記就代表有完整頁，標記的內容就是它多舊。
    """
    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text("2026-08-30\n", encoding="utf-8")

    out = tmp / "site"
    build_site(_records(), out, sheets_dir=sheets)

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="tag when"' in listing
    assert ">08/30<" in listing
    assert "報表更新於 2026-08-30" in listing
    assert 'class="tag full"' not in listing      # 有日期就不再退回「完整」

    # search.json 的第五欄跟著換成日期。真假值沒變，所以讀它的 JS 照舊。
    row = next(
        r
        for r in json.loads((out / "search.json").read_text(encoding="utf-8"))
        if r[0] == "5439"
    )
    assert row[4] == "2026-08-30"


def test_a_stock_fetched_before_the_stamp_existed_still_says_完整(tmp_path=None):
    """沒有日期就不要編一個出來——退回原本的字，不要留空或猜一個。"""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))   # 沒有 _fetched.txt

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="tag full"' in listing and "完整" in listing
    assert 'class="tag when"' not in listing


def test_a_corrupt_stamp_is_ignored_rather_than_printed(tmp_path=None):
    """壞掉的內容不該原樣印到頁面上。"""
    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text("昨天啦\n", encoding="utf-8")

    out = tmp / "site"
    build_site(_records(), out, sheets_dir=sheets)
    listing = (out / "index.html").read_text(encoding="utf-8")
    assert "昨天啦" not in listing
    assert 'class="tag full"' in listing


def test_the_stamp_is_not_mistaken_for_a_fourteenth_sheet(tmp_path=None):
    """建站是用 glob("*.json") 把資料夾讀成表格的，記號不能長得像一張表。"""
    from twsix.cli import FETCHED_STAMP

    assert not FETCHED_STAMP.endswith(".json")

    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / FETCHED_STAMP).write_text("2026-08-30\n", encoding="utf-8")
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=sheets)
    assert written.get("  其中完整版") == 1      # 還是照常算得出完整報告


def test_the_name_links_to_the_same_page_as_the_code(tmp_path=None):
    """掃清單時眼睛落在名稱上，卻要把游標移回四位數字才點得到。

    每一列都要付一次的小摩擦，而兩個連結指向同一頁，沒有任何歧義。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert '<a href="stock/5439.html">高技</a>' in listing
    assert '<a href="stock/2330.html">台積電</a>' in listing
    # 代號那一格也還是連結——兩個都指同一頁。
    assert '<a href="stock/5439.html">5439</a>' in listing


def test_a_news_headline_opens_in_a_new_tab(tmp_path=None):
    """點一則新聞是「順便看一下」，不是「離開這一頁」。

    原本會把整份報告換掉，回來還得重新選分頁、重新捲回原來的位置。
    target 一定要配 rel="noopener noreferrer"：少了它，被開的那一頁可以透過
    window.opener 改寫這一頁的網址。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    heads = [ln for ln in page.splitlines() if 'class="head" href=' in ln]
    assert heads, "新聞標題連結不見了"
    for ln in heads:
        assert 'target="_blank"' in ln
        assert 'rel="noopener noreferrer"' in ln


def test_the_intraday_price_ticks_are_gone_from_the_page(tmp_path=None):
    """盤中速報不再出現在頁面上——標籤、灰底列、說明文字都不留。"""
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    assert "盤中速報" not in page
    assert "roundup" not in page


def test_the_header_stamp_says_when_and_reminds_to_update(tmp_path=None):
    """頁首那一行原本擠了四件事，其中三件在別的地方各自說過一次。

    檔數與季別在〔評等清單〕的第一句，落後多久在下面那條 ⚠ 橫幅。留在頁首只是
    把最上面那一行讀成一串參數。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    for name in ("index.html", "stock/5439.html"):
        page = (out / name).read_text(encoding="utf-8")
        assert "網站最後更新：" in page, name
        assert "個股資料請記得更新" in page, name
        assert "網站產生：" not in page, name
        assert "資料截止：" not in page, name


def test_the_shared_css_and_js_are_downloaded_once_not_baked_into_every_page(tmp_path=None):
    """1,741 張頁面夾帶同一份 22 KB 樣式 + 16 KB 腳本 = 96 MB 的網站。

    那 96 MB 每次「立即更新」都要打包、上傳、再解開一次，就為了其中一張變了。
    抽成 assets/ 之後網站約剩四分之一，而讀者翻第二頁起是快取命中。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    css = out / "assets" / "site.css"
    js = out / "assets" / "site.js"
    assert css.is_file() and js.is_file()
    assert len(css.read_text("utf-8")) > 5_000
    assert len(js.read_text("utf-8")) > 5_000

    for name, rel in (("index.html", ""), ("stock/2330.html", "../")):
        page = (out / name).read_text("utf-8")
        assert f'href="{rel}assets/site.css?v=' in page, name
        assert f'src="{rel}assets/site.js?v=' in page, name
        # 內嵌的只剩那一行 bootstrap，不是整份腳本。
        assert "<style>" not in page, name
        assert len(_script_bodies(page)) < 500, name


def test_the_asset_url_carries_a_content_fingerprint(tmp_path=None):
    """沒有指紋，改過樣式的網站對回訪的讀者是舊的。

    瀏覽器手上那份 site.css 沒有過期的理由——它上次拿到的網址一模一樣。
    """
    from twsix.report.build import asset_version

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    v = asset_version()
    assert len(v) == 8
    assert f"assets/site.css?v={v}" in (out / "index.html").read_text("utf-8")


def test_a_standalone_page_still_carries_everything_it_needs(tmp_path=None):
    """`twsix page` 產出的那一張要能單獨用瀏覽器開起來。

    它旁邊沒有 assets/ 可以連——所以單頁版內嵌，網站版連外部檔案。同一份樣板，
    兩種輸出。
    """
    from test_stock_page import _page  # noqa: PLC0415
    from twsix.report.build import build_stock_page  # noqa: PLC0415

    tmp = tmp_path or _tmp()
    page, _ = _page()
    out = build_stock_page(page, tmp / "5439.html")
    text = out.read_text("utf-8")
    assert "<style>" in text
    assert "assets/site.css" not in text
    assert len(_script_bodies(text)) > 5_000


def test_the_watcher_waits_for_the_mark_to_change_not_merely_to_exist(tmp_path=None):
    """對一檔已經有完整報告的股票按「立即更新」，「有沒有完整頁」從頭到尾都是真。

    舊的判斷是「第五欄有值就算完成」，所以輪詢第一次就以為好了，把還沒發布的
    舊頁面重新載入一次——看起來像什麼都沒發生，於是要自己再重整一次。第五欄改成
    更新日期之後，它會變；判斷改成「跟按之前不一樣」才算完成。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    js = (out / "assets" / "site.js").read_text("utf-8")

    assert "function currentMark(code)" in js
    assert "now !== was" in js, "還在用『有值就算完成』的判斷"
    # 同一天更新同一檔，日期不會變——那時沒有站內訊號可等，要有保底。
    assert "SETTLE_MS" in js


def test_the_site_publishes_a_stamp_that_changes_on_every_build(tmp_path=None):
    """「deploy 完成了沒」要有一個精確的答案，不是從資料反推。

    以前問的是 search.json 的第五欄——那一欄只在資料變了才動，所以同一天對同一檔
    按第二次「立即更新」，日期一模一樣，頁面沒有任何訊號可以等，只能空等計時器。
    build.json 每建一次站就換一次，六十個位元組。
    """
    import json
    import time

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    build_site(_records(), out, sheets_dir=sheets)
    first = json.loads((out / "build.json").read_text("utf-8"))
    assert first["built"] and first["assets"]

    # 頁面知道自己是哪一次建的，才比得出來。
    # 薄頁和完整頁走的是兩條不同的 render 路徑，兩條都要帶到——漏掉完整頁的話，
    # 「立即更新」停在的那一頁正好就是不會自己更新的那一頁。
    for name in ("index.html", "stock/2330.html", "stock/5439.html"):
        assert f'built:"{first["built"]}"' in (out / name).read_text("utf-8"), name

    time.sleep(1.1)
    build_site(_records(), out, sheets_dir=sheets)
    second = json.loads((out / "build.json").read_text("utf-8"))
    assert second["built"] != first["built"], "重建之後號碼沒變，等待就永遠不會結束"


def test_the_watcher_polls_the_build_stamp_first(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    js = (out / "assets" / "site.js").read_text("utf-8")

    assert "build.json?t=" in js
    assert "TWSIX.built" in js
    # search.json 那條路留著，但只是 build.json 拿不到時的退路。
    assert "function fallback(" in js
    assert js.index("build.json?t=") < js.index("function fallback(")


def test_every_progress_line_says_how_long_it_took(tmp_path=None):
    """「總共兩分鐘」沒辦法告訴任何人該修哪一段。

    整段等待橫跨三件事：GitHub 派 runner 的排隊、workflow 本身、Pages 的 CDN
    換檔。前後兩段都不在 Actions 顯示的 Total duration 裡，所以只看那個數字會
    一直修錯地方。每一行掛上秒數，一張截圖就分得出來。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    js = (out / "assets" / "site.js").read_text("utf-8")

    assert "var line = elapsed() + " in js, "進度行沒有時間戳"
    assert "這一段是排隊，不算在 workflow 的執行時間裡" in js
    assert "剩下的是 Pages CDN 換檔" in js


def test_every_column_can_be_sorted_and_sorts_by_a_key_not_by_the_printed_text(tmp_path=None):
    """「+0.50」「—」「AA」照字串排會排出胡說。

    型別是在產生 HTML 的時候就知道的——那時候寫進 data-s，比在瀏覽器裡一欄一欄
    猜可靠。沒有值一律是 -999：排序時沉到底，而不是插在中間。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    listing = (out / "index.html").read_text("utf-8")

    # 每一欄都可以點——只有幾欄能點，而且看不出是哪幾欄，比全部都能點難用。
    import re

    cols = re.findall(r'class="sortable" data-col="(\d+)"', listing)
    assert [int(c) for c in cols] == list(range(14))

    row = listing.split('<tr data-code="5439"')[1].split("</tr>")[0]
    assert re.search(r'class="num" data-s="[-0-9.]+"', row)   # 綜合評分排的是數字
    assert 'data-s="4"' in row                                # AA -> 4
    assert 'data-s="高技"' in row                              # 名稱排的是名稱
    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "data-s" in js and "sortBy" in js


def test_the_update_date_is_its_own_column_with_a_header(tmp_path=None):
    """原本那個日期是塞在代號那一格裡的徽章——有值，但沒有欄名。

    一欄資料沒有標題，讀者只能猜它是什麼；而它旁邊那 1,712 檔沒有日期的，看起來
    就像資料壞了，而不是「那是另一種資料」。
    """
    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text("2026-08-30\n", encoding="utf-8")
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=sheets)
    listing = (out / "index.html").read_text("utf-8")

    assert "最後<br>更新日" in listing
    row = listing.split('<tr data-code="5439"')[1].split("</tr>")[0]
    assert '<td class="when-cell" data-s="2026-08-30">' in row
    # 沒有完整報告的那一檔，這一格是破折號，不是空白——空白讀起來像漏掉了。
    plain = listing.split('<tr data-code="2330"')[1].split("</tr>")[0]
    assert '<td class="when-cell" data-s="">' in plain and "—" in plain


def test_the_watchlist_page_is_the_same_table_filtered_in_the_browser(tmp_path=None):
    """清單存在讀者的 localStorage 裡，建站的時候我們不知道他標了哪幾檔。

    ——也不該知道。這是一份靜態網站，沒有可以放私人清單的地方。所以整張表都送
    過去，由瀏覽器自己篩。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "watchlist.html").read_text("utf-8")
    assert '<table id="t" data-watchlist="1">' in page
    assert '<tr data-code="5439"' in page and '<tr data-code="2330"' in page
    assert 'id="watch-empty"' in page          # 一檔都沒加時要說話
    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "twsix.watchlist" in js and "localStorage" in js
    # 導覽列指得過去
    assert 'href="watchlist.html"' in (out / "index.html").read_text("utf-8")


def test_the_target_price_calculator_is_seeded_from_the_stocks_own_numbers(tmp_path=None):
    """一個試算盤最容易變成的東西，是一組看起來很精確、其實憑空填的參數。

    所以每個預設值都要說得出出處，而且要對得起來：5439 的年營收 9,644 百萬、
    股數 0.93 億股、淨利率 14.5% ± 1.7%、營收成長率 4.5%（最近月）到 43.6%
    （近六月均）——這幾個數字和坊間工具上的一模一樣，是各自算出來的，不是抄的。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")

    assert 'id="calc"' in page and "data-seed=" in page
    import json
    import re

    seed = json.loads(re.search(r"data-seed='([^']+)'", page).group(1))
    assert round(seed["revenue"]) == 9644            # 百萬元
    assert round(seed["shares"], 2) == 0.93          # 億股
    assert round(seed["margin"]["avg"] * 100, 1) == 14.5
    assert round(seed["margin"]["sigma"] * 100, 1) == 1.7
    assert round(seed["growth"]["latest"] * 100, 1) == 4.5
    assert round(seed["growth"]["recent6"] * 100, 1) == 43.6
    assert [y["year"] for y in seed["years"]] == [2025, 2024, 2023, 2022]
    assert round(seed["years"][0]["eps"], 2) == 13.74

    # 算不出來、對不上來源的東西不放：累計年增率我試過幾種視窗都對不上參考工具，
    # 所以它不在種子裡——一個來路不明的預設值會被當成事實填進去。
    assert "ytd" not in seed["growth"]

    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "預估目標價" in js and "上檔空間" in js


def test_every_forecast_field_on_the_page_says_where_its_formula_came_from(tmp_path=None):
    """一個沒有出處的估值和一個猜出來的估值，在畫面上長得一模一樣。

    〔EPS預估與估價〕的每一格都是活頁簿的公式搬過來的，但公式原本只活在程式的
    docstring 裡——讀者看到的只有數字。這個測試釘住的是：畫面上出現的每一個欄位，
    說明欄裡都找得到它的公式與活頁簿出處。

    釘住「每一個」而不是「有這個區塊」，是因為之後新增欄位很容易只加畫面不加說明，
    而那正是這個區塊存在的理由被悄悄抽掉的方式。
    """
    from twsix.report.stock_page import FORECAST_BASIS, FORECAST_BASIS_NOTES

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")

    assert "各欄的計算依據" in page
    for field, formula, source in FORECAST_BASIS:
        assert field and formula and source, f"{field} 少了公式或出處"
        assert field in page, f"說明欄漏了 {field}"
        assert source in page, f"{field} 的出處沒有印出來"
    for note in FORECAST_BASIS_NOTES:
        assert note in page

    # 畫面上實際印出來的每一個欄位，說明欄都要涵蓋。
    labelled = {f for f, _, _ in FORECAST_BASIS}
    for shown in ("預估成長率", "預估營收", "稅後淨利率", "預估淨利",
                  "加權平均股數", "預估 EPS", "近四季 EPS", "目標價",
                  "下檔價", "預期報酬", "預期風險", "報酬風險比",
                  "預估本益比", "EPS 成長率", "PEG"):
        assert shown in labelled, f"{shown} 印在頁面上，卻沒有計算依據"

    # 對帳的強弱要說出來：本益比基準和活頁簿存檔時的設定不同，這件事必須寫明。
    assert "pe_basis" in page and "排除極端值" in page


def test_the_matrix_says_which_axis_is_which_and_the_three_bands_read_apart(tmp_path=None):
    """「淨利率＼成長率」印成一行，讀者得自己猜哪個是橫的——猜錯就整張表看反。

    改成把左上角切成兩塊三角，中間留一道縫（寬度和九宮格之間的縫一樣，所以它
    看起來是格線的一部分，不是一條特別粗的斜線），軸名各站一邊。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    js = (out / "assets" / "site.js").read_text("utf-8")
    css = (out / "assets" / "site.css").read_text("utf-8")

    # 兩個軸名是分開的元素，不是一個字串裡的斜線。
    assert 'class="ax-col"' in js and 'class="ax-row"' in js
    assert "<th>淨利率" not in js          # 兩個軸名擠在一格裡的舊寫法

    # 三角形是背景畫出來的，中間那道縫必須透得出底色——所以底色要透明，
    # 不能是 surface-2，否則縫會被填滿又變回一條線。
    corner = css[css.index("table.matrix th.corner{"):][:400]
    assert "background-color:transparent" in corner
    assert corner.count("linear-gradient(to top right") == 2

    # 九個格子之間要有縫，不然色塊糊成一片。
    assert "border-spacing" in css


def test_the_matrix_colours_by_size_not_by_distance_from_the_price(tmp_path=None):
    """顏色改塗「這一格有多大」，離現價多遠讓給每一格的第二行。

    兩件事各用一個管道講，比兩件事搶同一個管道好：顏色一旦讓出來，就能拿去做
    另一件顏色擅長的事——讓三張本益比矩陣一眼分得出來。
    """
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    js = (out / "assets" / "site.js").read_text("utf-8")
    css = (out / "assets" / "site.css").read_text("utf-8")

    # 階數是相對這張表自己的極值算的，不是絕對門檻。
    assert "function stepper(" in js and "(v - lo) / span * 4" in js
    # 第二行：正的是預期報酬，負的是預期風險。
    assert "預期報酬 " in js and "預期風險 " in js
    assert 'class="d"' in js and 'class="v"' in js
    # 預估 EPS 那張不比現價——EPS 不是價格。
    assert "'n', 0, false" in js
    # 三張目標價矩陣三個色相。
    assert "['a', 'b', 'c']" in js

    # 四組色階 × 五階，每一階都自帶前景色（深底不能配深字）。
    for fam in "nabc":
        for i in range(5):
            assert f"--m{fam}{i}:linear-gradient" in css
            assert f"table.matrix td.m{fam}{i}{{background:var(--m{fam}{i});" in css
            assert f"color:var(--m{fam}{i}-fg)}}" in css
    # 深色主題自己一組——淺色的最淺階在深底上是一塊發光的白，不是「小」。
    assert css.count("--mn0:linear-gradient") == 2

    # 格子置中：這裡不是拿來縱向掃一欄數字比大小的，顏色已經在做那件事。
    assert "table.matrix td{background:var(--surface-2);font-variant-numeric:tabular-nums;" in css
    assert "text-align:center" in css


def test_every_matrix_step_keeps_its_text_readable():
    """深底配深字是這種色階最容易犯的錯，而且只有在最深的那一兩階才看得出來。

    四組 × 五階 × 兩個主題 = 40 個組合，全部要 >= 4.5:1。這是算的，不是看的。
    """
    import re

    css = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css").read_text("utf-8")

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(hexcode: str) -> float:
        r, g, b = (int(hexcode[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def ratio(a: str, b: str) -> float:
        la, lb = lum(a), lum(b)
        hi, lo = max(la, lb), min(la, lb)
        return (hi + 0.05) / (lo + 0.05)

    INK = "#0b1220"  # --badge-ink，兩個主題共用
    pattern = re.compile(
        r"--m([nabc])(\d):linear-gradient\(150deg,(#[0-9a-f]{6}),(#[0-9a-f]{6})\); "
        r"--m\1\2-fg:(#fff|var\(--badge-ink\));"
    )
    found = pattern.findall(css)
    assert len(found) == 40, f"色階數不對：{len(found)}"
    for fam, step, c1, c2, fg in found:
        ink = INK if fg.startswith("var") else "#ffffff"
        # 漸層的兩端都要過，不是只有中間那個平均值。
        for stop in (c1, c2):
            r = ratio(stop, ink)
            assert r >= 4.5, f"--m{fam}{step} 的 {stop} 配 {fg} 只有 {r:.2f}:1"


def test_the_stylesheet_has_no_orphan_declaration_blocks():
    """少了選擇器的宣告區塊，瀏覽器會直接跳過——不會壞掉，只會靜靜地什麼都不做。

    這是真的發生過的：`.scenarios` 那兩條規則的選擇器在某次編輯裡被刪掉了，
    兩行宣告留在原地當孤兒，撐了好幾個 commit 都沒人發現，因為畫面上「少了一個
    本來就沒人在看的區塊」和「一切正常」長得一樣。

    大括號配平抓得到這一類：孤兒宣告會多出一個 `}`。
    """
    css = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css"
    ).read_text("utf-8")
    depth = 0
    for n, line in enumerate(css.split("\n"), 1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"第 {n} 行多了一個 }}：{line.strip()[:70]}"
    assert depth == 0, f"少了 {depth} 個 }}"


def test_the_narrow_layout_is_written_once_and_the_toggle_reuses_it():
    """「切換手機版」不是第二份版面，是把 .wrap 釘窄讓同一組規則生效。

    維護兩套版面的專案，壞掉的永遠是沒人在看的那一套——所以窄版規則只能寫一次，
    而要讓一顆按鈕觸發它，規則就必須掛在容器寬度上，不是視窗寬度上。
    """
    css = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css"
    ).read_text("utf-8")
    js = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js"
    ).read_text("utf-8")

    assert "container-type:inline-size" in css and "container-name:page" in css
    assert "@container page (max-width:760px)" in css
    assert ":root[data-view=mobile] .wrap" in css
    # 按鈕只改屬性，不改版面——版面的話在 CSS 裡。
    assert "data-view" in js and "twsix.viewmode" in js
    # 回到最上方：捲下去才出現，而且尊重「減少動態效果」。
    assert "#totop{position:fixed" in css
    assert "prefers-reduced-motion" in js
