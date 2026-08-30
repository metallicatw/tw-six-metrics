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

    assert page.count('role="tab"') == 10
    assert page.count('class="panel"') == 10
    # Exactly one panel open on arrival, and it is the first.
    assert page.count('role="tabpanel" aria-labelledby="tab-summary">') == 1
    assert page.count("hidden>") >= 9
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
