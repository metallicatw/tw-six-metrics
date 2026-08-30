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

    listing = (out / "list.html").read_text(encoding="utf-8")
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
    assert 'class="tag full"' not in (out / "list.html").read_text(encoding="utf-8")
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
