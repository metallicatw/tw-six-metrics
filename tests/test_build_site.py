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
        page = (out / name).read_text(encoding="utf-8")
        assert 'id="find"' in page, f"{name} 沒有搜尋框"
        assert "search.json" in page, f"{name} 沒有載入索引"
    for code in ("5439", "2330"):
        page = (out / "stock" / f"{code}.html").read_text(encoding="utf-8")
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
    assert "'../'+'search.json'" in page or "base='../'" in page.replace(" ", "")
    assert 'action="../index.html"' in page


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
    assert labels == ["評等清單"]
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
    page = (out / "index.html").read_text("utf-8")

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
    page = (out / "index.html").read_text("utf-8")

    assert "search.json?t=" in page
    assert "no-store" in page


def test_no_repo_configured_means_no_offer():
    """A fork, or a site published elsewhere, must not point back here."""
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="")
    page = (out / "index.html").read_text("utf-8")

    assert "metallicatw" not in page
    assert 'var repo = ""' in page or "var repo = ''" in page


def test_the_unfetched_stock_page_offers_both_paths_from_one_implementation():
    """`twsix serve` fetches on the spot; GitHub Pages asks the repo.

    Same button, same built HTML — which of the two it does is decided at load
    time by whether /api/ping answers.
    """
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = (out / "stock" / "2330.html").read_text("utf-8")

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
    page = (out / "stock" / "2330.html").read_text("utf-8")

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
    """
    if for while switch catch return typeof function new delete void
    fetch setTimeout setInterval clearInterval clearTimeout encodeURIComponent
    decodeURIComponent parseInt parseFloat isNaN String Number Boolean Object
    Array JSON Date Math Promise Error RegExp Set Map alert confirm require
    """.split()
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
        page = (out / name).read_text("utf-8")
        js = _script_bodies(page)
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
    full = (out / "stock" / "5439.html").read_text("utf-8")
    assert 'data-grab="5439"' in full
    assert 'data-full="1"' in full
    assert "重新抓取" in full
