
from __future__ import annotations

import csv
import json
from pathlib import Path

from test_stock_page import _full_grids
from twsix.report.build import build_site

ROOT = Path(__file__).resolve().parent


def _records() -> list[dict[str, str]]:
    path = ROOT.parent / "data" / "ratings.csv"
    wanted = {"5439", "2330"}
    with path.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["stock_id"] in wanted]


def _sheets(tmp: Path) -> Path:
    base = tmp / "sheets" / "5439"
    base.mkdir(parents=True)
    for name, grid in _full_grids().items():
        (base / f"{name}.json").write_text(
            json.dumps(grid, ensure_ascii=False), encoding="utf-8"
        )
    return tmp / "sheets"


def served(out: Path, name: str) -> str:
    page = (out / name).read_text(encoding="utf-8")
    parts = [page]
    for asset in ("site.css", "site.js"):
        if asset in page:
            parts.append((out / "assets" / asset).read_text(encoding="utf-8"))
    return "\n".join(parts)



def test_a_fetched_stock_gets_the_full_page_in_the_site(tmp_path=None):
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
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    plain = (out / "stock" / "2330.html").read_text(encoding="utf-8")
    assert plain, "沒有抓過資料的股票應該還是有頁面"
    assert 'id="river"' not in plain
    assert len(plain) < 60_000


def test_the_list_marks_which_codes_lead_to_a_full_page(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    listing = (out / "index.html").read_text(encoding="utf-8")
    full = listing.split('<tr data-code="5439"')[1].split("</tr>")[0]
    plain = listing.split('<tr data-code="2330"')[1].split("</tr>")[0]
    assert "已抓取完整資料" in full
    assert "已抓取完整資料" not in plain


def test_the_mark_follows_the_render_not_the_directory(tmp_path=None):
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
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=None)
    assert written["stock/*.html"] == 2
    assert "  其中完整版" not in written


def _tmp() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="twsix-site-"))




def test_the_search_index_lists_every_stock_not_only_the_fetched_ones(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    index = json.loads((out / "search.json").read_text(encoding="utf-8"))
    codes = {row[0] for row in index}
    assert codes == {"5439", "2330"}
    by_code = {row[0]: row for row in index}
    assert by_code["5439"][4] == 1
    assert by_code["2330"][4] == 0


def test_the_index_row_is_the_shape_the_script_reads():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    row = next(
        r
        for r in json.loads((out / "search.json").read_text(encoding="utf-8"))
        if r[0] == "5439"
    )
    assert len(row) == 7
    assert row[1] == "高技"
    assert row[2] and not row[2][0].isdigit()
    assert row[3].count(".") == 1 and len(row[3].split(".")[1]) == 2
    assert row[4] in (0, 1)
    assert row[5] == "" or ("T" in row[5] and len(row[5]) >= 19)
    assert row[6] == 0


def test_the_score_is_rounded_in_the_file_not_in_the_browser():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    text = (out / "search.json").read_text(encoding="utf-8")
    assert "3333333" not in text
    assert "6666666" not in text




def test_the_stock_page_search_box_resolves_paths_from_its_own_depth():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    assert 'window.TWSIX={rel:"../"' in page
    assert 'href="../assets/site.css' in page and 'src="../assets/site.js' in page
    assert "base=TWSIX.rel" in served(out, "stock/5439.html")




def test_the_three_stale_pages_are_unlinked_but_still_built():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    import re

    nav = re.search(r"<nav>(.*?)</nav>", (out / "index.html").read_text("utf-8"), re.S)
    labels = re.findall(r">([^<>]+)</a>", nav.group(1))
    assert labels == ["台股評等清單", "台股觀察清單", "選股功能", "AI 選股", "籌碼雷達"]
    for name in ("picks.html", "stats.html", "about.html"):
        assert (out / name).is_file(), f"{name} 不該被刪掉，只是不連過去"
    old = (out / "list.html").read_text("utf-8")
    assert "index.html" in old and "refresh" in old


def test_the_stock_page_is_tabs_rather_than_one_long_scroll():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")

    tabs = page.count('role="tab" id="tab-')
    assert tabs == page.count('class="panel"')
    assert tabs == 12
    assert 'id="tab-ai"' in page
    assert 'id="tab-statements"' not in page
    assert page.count('role="tabpanel" aria-labelledby="tab-summary">') == 1
    assert page.count("hidden>") >= tabs - 1
    assert 'class="ident sticky"' in page


def test_the_build_stamp_is_taipei_time():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    text = (out / "index.html").read_text("utf-8")
    assert "台北時間" in text
    assert "UTC" not in text


def test_the_dropped_section_is_gone_from_the_page_and_the_code():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")
    assert "財務指標評等預估" not in page
    assert 'id="tab-scenarios"' not in page




def test_the_published_site_can_ask_github_to_fetch_a_stock():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "index.html")

    assert '"owner/repo"' in page
    assert "/dispatches" in page
    assert "api.github.com" in page
    assert "issues/new" not in page


def test_the_page_watches_for_its_own_result_rather_than_telling_you_to_wait():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "index.html")

    assert "search.json?t=" in page
    assert "no-store" in page


def test_no_repo_configured_means_no_offer():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="")
    page = served(out, "index.html")

    assert "metallicatw" not in page
    assert 'repo:""' in page or "repo:''" in page


def test_the_unfetched_stock_page_offers_both_paths_from_one_implementation():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "stock/2330.html")

    assert "twsixLive" in page and "twsixCanAsk" in page
    assert "twsixFetch" in page and "twsixAskGithub" in page


def test_the_wait_survives_navigating_away():
    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    page = served(out, "stock/2330.html")

    assert "sessionStorage" in page
    assert "twsix.pending" in page
    assert "location.reload" in page



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
    import re

    tmp = _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")

    for name in ("index.html", "stock/2330.html", "stock/5439.html"):
        js = _script_bodies(served(out, name))
        called = {
            m.group(1)
            for m in re.finditer(r"(?<![.\w$])([a-zA-Z_$][\w$]*)\s*\(", js)
        }
        defined = set(re.findall(r"function\s+([a-zA-Z_$][\w$]*)\s*\(", js))
        defined |= set(re.findall(r"(?:var|let|const)\s+([a-zA-Z_$][\w$]*)\s*=", js))
        missing = sorted(called - defined - _JS_GLOBALS)
        assert not missing, f"{name} 呼叫了沒有定義的函式：{missing}"



def test_the_mark_is_the_update_date_when_the_fetch_left_one(tmp_path=None):
    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text("2026-08-30\n", encoding="utf-8")

    out = tmp / "site"
    build_site(_records(), out, sheets_dir=sheets)

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert "報表更新於 2026-08-30" in listing
    assert "財報 <b>2026Q2</b>" in listing

    row = next(
        r
        for r in json.loads((out / "search.json").read_text(encoding="utf-8"))
        if r[0] == "5439"
    )
    assert row[4] == "2026-08-30"


def test_a_stock_fetched_before_the_stamp_existed_still_says_完整(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert "已抓取完整資料" in listing
    assert "報表更新於" not in listing


def test_a_corrupt_stamp_is_ignored_rather_than_printed(tmp_path=None):
    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text("昨天啦\n", encoding="utf-8")

    out = tmp / "site"
    build_site(_records(), out, sheets_dir=sheets)
    listing = (out / "index.html").read_text(encoding="utf-8")
    assert "昨天啦" not in listing
    assert "已抓取完整資料" in listing


def test_the_stamp_is_not_mistaken_for_a_fourteenth_sheet(tmp_path=None):
    from twsix.cli import FETCHED_STAMP

    assert not FETCHED_STAMP.endswith(".json")

    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / FETCHED_STAMP).write_text("2026-08-30\n", encoding="utf-8")
    out = tmp / "site"
    written = build_site(_records(), out, sheets_dir=sheets)
    assert written.get("  其中完整版") == 1


def test_the_name_links_to_greed_fear_in_a_new_tab(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    listing = (out / "index.html").read_text(encoding="utf-8")
    assert '<a href="radar.html#t1-5439-gf" target="_blank" rel="noopener"' in listing
    assert '>高技</a>' in listing
    assert '<a href="radar.html#t1-2330-gf" target="_blank"' in listing
    assert '<a href="stock/5439.html">5439</a>' in listing


def test_a_news_headline_opens_in_a_new_tab(tmp_path=None):
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
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    assert "盤中速報" not in page
    assert "roundup" not in page


def test_the_header_stamp_says_only_when_the_site_was_built(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    for name in ("index.html", "stock/5439.html"):
        page = (out / name).read_text(encoding="utf-8")
        assert 'class="built"' in page, name
        head = page[page.index("<header"):page.index("</header>")]
        assert 'class="built"' in head, f"{name}：建站時間不在頁首"
        assert "個股資料請記得更新" not in page, name
        assert "網站產生：" not in page, name
        assert "資料截止：" not in page, name


def test_the_shared_css_and_js_are_downloaded_once_not_baked_into_every_page(tmp_path=None):
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
        assert "<style>" not in page, name
        assert len(_script_bodies(page)) < 1_500, name


def test_the_asset_url_carries_a_content_fingerprint(tmp_path=None):
    from twsix.report.build import asset_version

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    v = asset_version()
    assert len(v) == 8
    assert f"assets/site.css?v={v}" in (out / "index.html").read_text("utf-8")


def test_a_standalone_page_still_carries_everything_it_needs(tmp_path=None):
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
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    js = (out / "assets" / "site.js").read_text("utf-8")

    assert "function currentMark(code)" in js
    assert "now !== was" in js, "還在用『有值就算完成』的判斷"
    assert "SETTLE_MS" in js


def test_the_site_publishes_a_stamp_that_changes_on_every_build(tmp_path=None):
    import json
    import time

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)
    build_site(_records(), out, sheets_dir=sheets)
    first = json.loads((out / "build.json").read_text("utf-8"))
    assert first["built"] and first["assets"]

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
    assert "function fallback(" in js
    assert js.index("build.json?t=") < js.index("function fallback(")


def test_every_progress_line_says_how_long_it_took(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), repo="owner/repo")
    js = (out / "assets" / "site.js").read_text("utf-8")

    assert "at: elapsed()" in js, "進度行沒有時間戳"
    assert "s.at + '　' + s.text" in js
    assert "這一段是排隊，不算在 workflow 的執行時間裡" in js
    assert "剩下的是 Pages CDN 換檔" in js


def test_every_column_can_be_sorted_and_sorts_by_a_key_not_by_the_printed_text(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    listing = (out / "index.html").read_text("utf-8")

    import re

    cols = re.findall(r'class="sortable" data-col="(\d+)"', listing)
    assert [int(c) for c in cols] == list(range(1, 24))

    head = listing.split("<thead>")[1].split("</thead>")[0]
    ths = re.findall(r"<th\b.*?</th>", head, re.S)
    for i, th in enumerate(ths):
        m = re.search(r'data-col="(\d+)"', th)
        assert m is None or int(m.group(1)) == i, (
            f"第 {i} 欄的表頭寫著 data-col={m.group(1)}"
            f"（{re.sub(r'<[^>]+>', '', th).strip()[:16]}）"
        )
    first = listing.split('<tr data-code="')[1].split("</tr>")[0]
    body_cols = len(re.findall(r"<td\b", first))
    assert body_cols == len(ths), (
        f"表頭 {len(ths)} 欄、資料列 {body_cols} 欄——對不起來排序會整排錯開"
    )

    row = listing.split('<tr data-code="5439"')[1].split("</tr>")[0]
    assert re.search(r'class="num mid" data-s="[-0-9.]+"', row)
    assert 'data-s="4"' in row
    assert 'data-s="高技"' in row
    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "data-s" in js and "sortBy" in js


def test_the_update_date_is_its_own_column_with_a_header(tmp_path=None):
    tmp = tmp_path or _tmp()
    sheets = _sheets(tmp)
    (sheets / "5439" / "_fetched.txt").write_text("2026-08-30\n", encoding="utf-8")
    out = tmp / "site"
    records = _records()
    for r in records:
        if r["stock_id"] == "5439":
            r["fiscal_quarter"] = "2026.2Q"
            r["revenue_month"] = "115/08"
    build_site(records, out, sheets_dir=sheets)
    listing = (out / "index.html").read_text("utf-8")

    assert ">財報基準</button>" in listing
    row = listing.split('<tr data-code="5439"')[1].split("</tr>")[0]
    assert '<td class="when-cell" data-s="2026.2Q|115/08"' in row
    assert "財報 <b>2026Q2</b>" in row and "營收 <b>2026/08</b>" in row
    plain = listing.split('<tr data-code="2330"')[1].split("</tr>")[0]
    assert 'class="when-cell"' in plain


def test_the_watchlist_page_is_the_same_table_filtered_in_the_browser(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "watchlist.html").read_text("utf-8")
    assert '<table id="t" class="compact" data-watchlist="1">' in page
    assert '<tr hidden data-code="5439"' in page and '<tr hidden data-code="2330"' in page
    assert '<tr data-code="5439"' in (out / "index.html").read_text("utf-8")
    assert 'id="watch-empty"' in page
    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "twsix.watchlist" in js and "localStorage" in js
    assert 'href="watchlist.html"' in (out / "index.html").read_text("utf-8")


def test_the_target_price_calculator_is_seeded_from_the_stocks_own_numbers(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")

    assert 'id="calc"' in page and "data-seed=" in page
    import json
    import re

    seed = json.loads(re.search(r"data-seed='([^']+)'", page).group(1))
    assert round(seed["revenue"]) == 9644
    assert round(seed["shares"], 2) == 0.93
    assert round(seed["margin"]["avg"] * 100, 1) == 14.5
    assert round(seed["margin"]["sigma"] * 100, 1) == 1.7
    assert round(seed["growth"]["latest"] * 100, 1) == 4.5
    assert round(seed["growth"]["recent6"] * 100, 1) == 43.6
    assert [y["year"] for y in seed["years"]] == [2025, 2024, 2023, 2022]
    assert round(seed["years"][0]["eps"], 2) == 13.74

    assert "ytd" not in seed["growth"]

    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "預估目標價" in js


def test_every_forecast_field_on_the_page_says_where_its_formula_came_from(tmp_path=None):
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

    labelled = {f for f, _, _ in FORECAST_BASIS}
    for shown in ("預估成長率", "預估營收", "稅後淨利率", "預估淨利",
                  "加權平均股數", "預估 EPS", "近四季 EPS", "目標價",
                  "下檔價", "預期報酬", "預期風險", "報酬風險比",
                  "預估本益比", "EPS 成長率", "PEG"):
        assert shown in labelled, f"{shown} 印在頁面上，卻沒有計算依據"

    assert "pe_basis" in page and "排除極端值" in page


def test_the_matrix_says_which_axis_is_which_and_the_three_bands_read_apart(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    js = (out / "assets" / "site.js").read_text("utf-8")
    css = (out / "assets" / "site.css").read_text("utf-8")

    assert 'class="ax-col"' in js and 'class="ax-row"' in js
    assert "<th>淨利率" not in js

    corner = css[css.index("table.matrix th.corner{"):][:400]
    assert "background-color:transparent" in corner
    assert corner.count("linear-gradient(to top right") == 2

    assert "border-spacing" in css


def test_the_matrix_colours_by_size_not_by_distance_from_the_price(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    js = (out / "assets" / "site.js").read_text("utf-8")
    css = (out / "assets" / "site.css").read_text("utf-8")

    assert "function stepper(" in js and "(v - lo) / span * 4" in js
    assert "預期報酬 " in js and "預期風險 " in js
    assert 'class="d"' in js and 'class="v"' in js
    assert "'n', 0, false" in js
    assert "['a', 'b', 'c']" in js

    for fam in "nabc":
        for i in range(5):
            assert f"--m{fam}{i}:linear-gradient" in css
            assert f"table.matrix td.m{fam}{i}{{background:var(--m{fam}{i});" in css
            assert f"color:var(--m{fam}{i}-fg)}}" in css
    assert css.count("--mn0:linear-gradient") == 2

    assert "table.matrix td{background:var(--surface-2);font-variant-numeric:tabular-nums;" in css
    assert "text-align:center" in css


def test_every_matrix_step_keeps_its_text_readable():
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

    INK = "#0b1220"
    pattern = re.compile(
        r"--m([nabc])(\d):linear-gradient\(150deg,(#[0-9a-f]{6}),(#[0-9a-f]{6})\); "
        r"--m\1\2-fg:(#fff|var\(--badge-ink\));"
    )
    found = pattern.findall(css)
    assert len(found) == 40, f"色階數不對：{len(found)}"
    for fam, step, c1, c2, fg in found:
        ink = INK if fg.startswith("var") else "#ffffff"
        for stop in (c1, c2):
            r = ratio(stop, ink)
            assert r >= 4.5, f"--m{fam}{step} 的 {stop} 配 {fg} 只有 {r:.2f}:1"


def test_the_stylesheet_has_no_orphan_declaration_blocks():
    css = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css"
    ).read_text("utf-8")
    depth = 0
    for n, line in enumerate(css.split("\n"), 1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"第 {n} 行多了一個 }}：{line.strip()[:70]}"
    assert depth == 0, f"少了 {depth} 個 }}"


def test_the_narrow_layout_is_written_once_and_the_toggle_reuses_it():
    css = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css"
    ).read_text("utf-8")
    js = (
        Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js"
    ).read_text("utf-8")

    assert "container-type:inline-size" in css and "container-name:page" in css
    assert "@container page (max-width:760px)" in css
    assert "data-view=mobile" not in css and "button.viewmode" not in css
    assert "localStorage.removeItem('twsix.viewmode')" in js
    assert "#totop{position:fixed" in css
    assert "prefers-reduced-motion" in js



def test_the_chart_windows_match_the_tables_below_them():
    from twsix.ingest.weekly_prices import DEFAULT_YEARS
    from twsix.report.sections import DIRECTOR_MONTHS, HOLDER_WEEKS

    assert HOLDER_WEEKS == 52
    assert DIRECTOR_MONTHS == 36
    assert DEFAULT_YEARS == 5

    tpl = (ROOT.parent / "src/twsix/report/templates/stockpage.html.j2").read_text("utf-8")
    assert "h.weeks[:52]" in tpl and "dr.months[:36]" in tpl, "表和圖要一樣長"


def test_the_monitor_tab_appears_only_when_the_page_is_really_there(tmp_path=None):
    from twsix.report.build import MONITOR_PAGE, MONITOR_REPORT

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)

    build_site(_records(), out, sheets_dir=sheets)
    assert "全球市場監控" not in (out / "index.html").read_text("utf-8")
    assert not (out / MONITOR_PAGE).exists(), "沒有報告就不該畫一個空的框"

    out.mkdir(parents=True, exist_ok=True)
    (out / MONITOR_REPORT).write_text("<html>報告</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=sheets)
    listing = (out / "index.html").read_text("utf-8")
    assert '>全球市場監控＋日股觀察</a>' in listing and "monitor.html" in listing
    assert '"../monitor.html"' in (out / "stock" / "5439.html").read_text("utf-8")


def test_the_report_is_embedded_so_the_reader_can_get_back(tmp_path=None):
    from twsix.report.build import MONITOR_PAGE, MONITOR_REPORT

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / MONITOR_REPORT).write_text("<html>報告</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / MONITOR_PAGE).read_text("utf-8")
    assert 'src="monitor-report.html"' in page, "沒有把報告嵌進來"
    assert "台股評等清單" in page, "導覽列不在，等於還是出不來"
    assert 'aria-current="page"' in page
    assert 'target="_blank"' in page

    assert (out / MONITOR_REPORT).read_text("utf-8") == "<html>報告</html>"

    js = (ROOT.parent / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "iframe.embed" in js and "getBoundingClientRect" in js


def test_the_report_is_copied_in_before_the_build_and_a_failure_is_not_fatal():
    repo = ROOT.parent
    action = (repo / ".github/actions/build-site/action.yml").read_text("utf-8")
    assert "market-monitor" in action
    assert "site/monitor-report.html" in action, "複製成外殼那一頁的檔名會被建站蓋掉"
    assert action.index("帶進〔市場監控〕") < action.index("建立網站")
    assert "::warning::" in action

    step = action.split("帶進〔市場監控〕")[1].split("帶進〔趨勢選股〕")[0]
    assert "--branch report" in step, "上游報告住在 report 分支"
    assert "github.io" not in step, "上游不再獨立建站"
    pages = (repo / ".github/workflows/pages.yml").read_text("utf-8")
    assert 'cron: "37 23 * * 1-5"' in pages



def test_the_trend_tab_appears_only_when_the_report_is_really_there(tmp_path=None):
    from twsix.report.build import TREND_PAGE, TREND_REPORT

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    sheets = _sheets(tmp)

    build_site(_records(), out, sheets_dir=sheets)
    assert "趨勢×六大×報酬" not in (out / "index.html").read_text("utf-8")
    assert not (out / TREND_PAGE).exists(), "沒有報告就不該畫一個空的框"

    out.mkdir(parents=True, exist_ok=True)
    (out / TREND_REPORT).write_text("<html>線圖</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=sheets)
    listing = (out / "index.html").read_text("utf-8")
    assert ">趨勢×六大×報酬</a>" in listing and "trend.html" in listing
    assert '"../trend.html"' in (out / "stock" / "5439.html").read_text("utf-8")


def test_the_trend_report_is_embedded_not_linked(tmp_path=None):
    from twsix.report.build import TREND_PAGE, TREND_REPORT

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / TREND_REPORT).write_text("<html>線圖</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / TREND_PAGE).read_text("utf-8")
    assert 'src="trend-report.html#cross"' in page, "沒有把報告嵌進來"
    assert "台股評等清單" in page, "導覽列不在，等於還是出不來"
    assert 'target="_blank"' in page, "想全螢幕看的人要有一條路"
    assert (out / TREND_REPORT).read_text("utf-8") == "<html>線圖</html>"


NAV_EXPECTED = [
    ("nav-list",   "台股評等清單"),
    ("nav-watch",  "台股觀察清單"),
    ("nav-trend",  "趨勢×六大×報酬"),
    ("nav-screen", "選股功能"),
    ("nav-ai",     "AI 選股"),
    ("nav-radar",  "籌碼雷達"),
    ("nav-mon",    "全球市場監控＋日股觀察"),
]


def test_the_nav_is_ordered_named_and_coloured(tmp_path=None):
    from twsix.report.build import MONITOR_REPORT, TREND_REPORT

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / TREND_REPORT).write_text("<html>線圖</html>", encoding="utf-8")
    (out / MONITOR_REPORT).write_text("<html>報告</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    import re

    html = (out / "index.html").read_text("utf-8")
    nav = html[html.index("<nav>"):html.index("</nav>")]
    got = re.findall(r'<a class="(nav-[a-z-]+)"[^>]*>([^<>]+)</a>', nav)
    assert got == NAV_EXPECTED, got

    css = (ROOT.parent / "src/twsix/report/templates/site.css").read_text("utf-8")
    colours = {}
    for cls, _label in NAV_EXPECTED:
        m = re.search(rf"nav a\.{cls}\s*{{--nav-c:(#[0-9a-fA-F]{{3,8}})}}", css)
        assert m, f"{cls} 在 site.css 裡沒有顏色"
        colours[cls] = m.group(1).lower()
    assert len(set(colours.values())) == len(colours), colours

    for cls, _label in NAV_EXPECTED:
        assert f"[data-theme=dark] nav a.{cls}" in css, f"{cls} 少了深色底的顏色"

    assert re.search(r"^nav{[^}]*font-size:1[5-9]px", css, re.M), "導覽列字級沒有加大"
    assert re.search(r"^nav a{[^}]*border-radius:999px", css, re.M), "分頁不是按鈕列"
    assert re.search(r"^nav{[^}]*flex-wrap:nowrap", css, re.M), "分頁會折行而不是橫滑"
    assert re.search(r"^nav{[^}]*overflow-x:auto", css, re.M), "分頁滑不動"
    assert re.search(r"header\.top h1{[^}]*font-size:2[0-9]px", css), "大標題沒有加大"


def test_the_trend_report_is_copied_in_before_the_build():
    repo = ROOT.parent
    action = (repo / ".github/actions/build-site/action.yml").read_text("utf-8")
    assert "tw-trend-filter" in action
    assert "site/trend-report.html" in action, "複製成外殼那一頁的檔名會被建站蓋掉"
    assert action.index("帶進〔趨勢選股〕") < action.index("建立網站")
    assert "::warning::" in action
    assert "for ref in report main" in action

    daily = (repo / ".github/workflows/daily.yml").read_text("utf-8")
    assert 'cron: "53 8 * * 1-5"' in daily and "scripts/wait_upstream.py" in daily


def test_the_trend_report_links_back_to_this_site():
    repo = ROOT.parent
    action = (repo / ".github/actions/build-site/action.yml").read_text("utf-8")
    assert (repo / "src/twsix/report/build.py").read_text("utf-8").count(
        'out_dir / "stock" / f"{stock_id}.html"'
    ) >= 1, "個股頁的路徑變了，上游的 --link-base 會全部指到 404"
    assert "tw-trend-filter" in action



def test_附註收在燈泡裡而不是攤在頁面上(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    listing = (out / "index.html").read_text("utf-8")

    assert 'class="tipbox"' in listing, "附註沒有被收進燈泡"
    assert 'class="bulb"' in listing
    assert "上一期要算得出綜合評分" in listing
    assert 'aria-expanded="false"' in listing


def test_燈泡是按鈕不是可點的_span():
    macros = (
        ROOT.parent / "src/twsix/report/templates/_macros.html.j2"
    ).read_text("utf-8")
    tip = macros[macros.index("{% macro tip()"):]
    assert "<button" in tip and 'type="button"' in tip
    assert "aria-expanded" in tip
    assert 'aria-hidden="true"' in tip and 'class="sr"' in tip


def test_沒有_javascript_的時候說明直接攤開():
    css = (
        ROOT.parent / "src/twsix/report/templates/site.css"
    ).read_text("utf-8")
    assert "html:not(.js) .tipbox{display:block" in css
    assert "html:not(.js) button.bulb{display:none}" in css
    js = (ROOT.parent / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "documentElement.classList.add('js')" in js


def test_燈泡的三種關法都在():
    js = (ROOT.parent / "src/twsix/report/templates/site.js").read_text("utf-8")
    seg = js[js.index("function show(tip){") - 2000:]
    assert "Escape" in seg, "按 Esc 關不掉"
    assert "if(tip === open) close();" in seg, "再按一次同一顆關不掉"
    assert "closest('.tipbox')" in seg
    assert "function show(tip){\n    close();" in seg



def test_股價和籌碼畫在同一張圖上_用右邊那條軸():
    from twsix.report import charts

    labels = ["09/01", "09/02", "09/03", "09/04"]
    plain = charts.bars(labels, [10, -20, 30, -5], title="外資買賣超",
                        unit=" 張", digits=0, newest_first=False)
    with_px = charts.bars(labels, [10, -20, 30, -5], title="外資買賣超",
                          unit=" 張", digits=0, newest_first=False,
                          price=[100.0, 101.5, 99.0, 103.0])

    import re
    h_plain = float(re.search(r'viewBox="0 0 \d+ ([\d.]+)"', plain).group(1))
    h_price = float(re.search(r'viewBox="0 0 \d+ ([\d.]+)"', with_px).group(1))
    assert h_price == h_plain, "疊在同一張圖上，高度不該變"

    assert 'class="chart-legend"' in with_px, "沒有圖例"
    assert "收盤價（右軸 元）" in with_px, "圖例沒說那是右軸"
    assert with_px.count('fill="var(--price)"') >= 2, "右軸刻度沒有跟著同色"
    assert 'stroke="var(--price)"' in with_px, "股價線沒畫"

    assert 'fill="url(#pg' in with_px, "沒有畫成面積"
    assert "<linearGradient" in with_px, "面積沒有由上往下淡出"

    assert '<th class="num">收盤價</th>' in with_px
    assert "101.50" in with_px, "股價的小數位被買賣超那一欄的 0 位蓋掉了"


def test_股價畫在主序列之前_才不會蓋住資料():
    from twsix.report import charts

    labels = ["09/01", "09/02", "09/03", "09/04"]
    svg = charts.bars(labels, [10, -20, 30, -5], title="外資買賣超", unit=" 張",
                      digits=0, newest_first=False,
                      price=[100.0, 101.5, 99.0, 103.0])
    area_at = svg.index('fill="url(#pg')
    bar_at = svg.index("<rect x=")
    assert area_at < bar_at, "股價面積畫在長條後面，會蓋住資料"


def test_時間軸只畫一次():
    from twsix.report import charts

    labels = ["09/01", "09/02", "09/03", "09/04"]
    svg = charts.line(labels, [1.0, 2.0, 3.0, 4.0], title="外資持股比重",
                      unit="%", digits=2, label_every=1, newest_first=False,
                      price=[100.0, 101.5, 99.0, 103.0])
    chart = svg[svg.index("<svg"):svg.index("</svg>")]
    assert chart.count(">09/02<") == 1, "日期標籤畫了兩排"


def test_股價缺哪一天就斷在哪一天():
    from twsix.report import charts

    labels = ["09/01", "09/02", "09/03", "09/04"]
    svg = charts.line(labels, [1.0, 2.0, 3.0, 4.0], title="外資持股比重",
                      unit="%", digits=2, newest_first=False,
                      price=[100.0, None, None, 103.0])
    assert 'fill="url(#pg' not in svg


def test_一個點畫不出趨勢就整格不畫():
    from twsix.report import charts

    labels = ["09/01", "09/02"]
    svg = charts.line(labels, [1.0, 2.0], title="外資持股比重", unit="%",
                      newest_first=False, price=[None, 103.0])
    assert "收盤價" not in svg


def test_民國日期對得上西元的每日快照():
    from twsix.report.sections import _ad

    assert _ad("115/09/02") == "2026-09-02"
    assert _ad("115/9/2") == "2026-09-02", "個位數的月日要補零"
    assert _ad("2026-09-02") == "2026-09-02"
    assert _ad("") == ""


def test_大戶持股的週收盤來自股價週分頁而不是那張表本身():
    from twsix.report.sections import holders

    grid = [
        ["週別", "統計日期", "各持股等級股東之持有比例(%)-≦10張",
         "各持股等級股東之持有比例(%)-＞400張≦800張"],
        ["26W35", "08/28", "12.5", "30.1"],
        ["26W34", "08/21", "12.7", "29.8"],
        ["26W33", "08/14", "12.9", "29.4"],
    ]
    weekly = [("2026/08/10", 24.25), ("2026/08/17", 24.85), ("2026/08/24", 24.30)]

    plain = holders(grid)
    assert [w["close"] for w in plain.weeks] == [None, None, None]
    assert "收盤價" not in plain.figures["big"], "沒有價就不該畫那一格"

    with_px = holders(grid, weekly)
    assert [w["close"] for w in with_px.weeks] == [24.30, 24.85, 24.25]
    assert "收盤價" in with_px.figures["big"]
    assert "收盤價" in with_px.figures["small"]


def test_週別的前兩碼決定年份():
    from twsix.report.sections import _week_year, _weekly_close_at

    assert _week_year("26W35") == 2026
    assert _week_year("25W52") == 2025
    assert _week_year("") == 0

    weekly = [("2025/12/29", 10.0), ("2026/01/05", 11.0)]
    assert _weekly_close_at(weekly, 2026, "01/02") == 10.0
    assert _weekly_close_at(weekly, 2026, "01/09") == 11.0
    assert _weekly_close_at(weekly, 2025, "01/02") is None


def test_同一頁多張圖的漸層_id_不能撞():
    from twsix.report import charts

    labels = ["09/01", "09/02", "09/03"]
    px = [100.0, 101.0, 102.0]
    a = charts.line(labels, [1.0, 2.0, 3.0], title="甲", newest_first=False, price=px)
    b = charts.line(labels, [1.0, 2.0, 3.0], title="乙", newest_first=False, price=px)
    import re
    ida = re.search(r'id="(pg\d+)"', a).group(1)
    idb = re.search(r'id="(pg\d+)"', b).group(1)
    assert ida != idb, (ida, idb)
    assert f'url(#{ida})' in a and f'url(#{idb})' in b


def test_頁首那兩件事各自貼著它有關的東西(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "index.html").read_text(encoding="utf-8")

    h1 = page[page.index("<h1"):page.index("</h1>")]
    assert 'class="built"' in h1, "建站時間沒有跟在站名那一行"

    assert 'class="findrow"' not in page and "抓取權杖" not in page


def test_線上抓取已退役_網站不再要權杖():
    js = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "var repo = '';" in js
    assert "localStorage.removeItem('twsix.token')" in js


def test_評等清單的燈泡接在那句話後面(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "index.html").read_text(encoding="utf-8")

    para = page[page.index("全市場評等，共"):]
    para = para[: para.index("</p>")]
    assert 'class="bulb"' in para, "燈泡跑到那一段外面了"


def test_市場監控的說明也收進燈泡(tmp_path=None):
    from twsix.report.build import MONITOR_PAGE, MONITOR_REPORT

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / MONITOR_REPORT).write_text("<html>報告</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / MONITOR_PAGE).read_text(encoding="utf-8")
    assert '<h2 class="sr">全球市場監控＋日股觀察</h2>' in page
    cap = page[page.index('class="muted note-s embed-cap'):page.index("<iframe")]
    assert 'class="bulb"' in cap, "燈泡不在說明那一行"
    assert "村田" in page, "說明內容不見了"
    assert "台股加權" in cap.split('class="tipbox"', 1)[1]


def test_the_eight_periods_are_real_table_columns(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    assert 'class="pv"' in page, "八期不是表格欄了"
    assert 'class="cells"' not in page, "grid 版回來了，列與列之間會對不齊"
    assert 'colspan="8"' in page


def test_the_three_margin_rows_sit_together_on_the_built_page(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    order = [page.find(x) for x in ("營業利益率", "淨利率（歸母）", "業外佔比")]
    assert all(i >= 0 for i in order), f"有一列不在頁面上：{order}"
    assert order == sorted(order), "三列的順序被打亂了"


def test_the_revenue_table_is_collapsed_and_not_duplicated(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))

    page = (out / "stock" / "5439.html").read_text(encoding="utf-8")
    assert 'class="rev"' in page, "月營收明細不見了"
    head = page[: page.find('class="rev"')]
    opened = head.rfind("<details")
    assert opened >= 0 and "</details>" not in head[opened:], "月營收明細沒有收起來"
    assert page.count('<th class="num">累計年增率</th>') == 1, (
        "月營收表在這一頁上出現了兩次"
    )
    assert page.count("<th>月營收</th>") == 0, "圖自己那張數值表回來了"




def _valuations(**by_stock) -> list[dict[str, str]]:
    from twsix.store.snapshots import VALUATION_COLUMNS

    out = []
    for code, values in by_stock.items():
        row = dict.fromkeys(VALUATION_COLUMNS, "")
        row["stock_id"] = code
        row.update(values)
        out.append(row)
    return out


def test_清單上看得到上市或上櫃(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    listing = (out / "index.html").read_text("utf-8")
    assert ">市場<" in listing, "表頭沒有〔市場〕這一欄"
    row = listing.split('<tr data-code="2330"')[1].split("</tr>")[0]
    assert 'data-s="上市"' in row, f"2330 那一列看不到「上市」：{row[:400]}"


def test_清單最右邊是報酬風險比(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(
        _records(), out, sheets_dir=_sheets(tmp),
        valuations=_valuations(
            **{"5439": {"reward_risk": "2.5", "risk_free": "0"},
               "2330": {"reward_risk": "", "risk_free": "1",
                        "target_price": "100", "market_price": "50",
                        "downside_price": "60"}},
        ),
    )
    listing = (out / "index.html").read_text("utf-8")
    assert ">報酬<br>風險比<" in listing.replace("\n", ""), "表頭沒有〔報酬風險比〕"

    good = listing.split('<tr data-code="5439"')[1].split("</tr>")[0]
    assert "2.50" in good and "rrv-ok" in good, good[-400:]

    free = listing.split('<tr data-code="2330"')[1].split("</tr>")[0]
    assert "無風險" in free, "『股價已低於下檔價』沒有畫成「無風險」"
    assert "∞" not in free, "還留著 ∞"
    assert 'data-s="999999"' in free, (
        "「無風險」的排序鍵不是一個大數——照〔報酬風險比〕排的時候它會沉到底，"
        "而它其實是最好的那一種"
    )


def test_算不出報酬風險比的顯示破折號而不是零(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp), valuations=[])
    row = (out / "index.html").read_text("utf-8") \
        .split('<tr data-code="5439"')[1].split("</tr>")[0]
    last = row.rsplit("<td", 4)[1]
    assert "—" in last and "0.00" not in last, last
    assert 'data-s="-999"' in last, "算不出來的排序鍵要沉到底"


def test_燈泡裡有那張勝率對照表(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    listing = served(out, "index.html")
    for must in ("損益兩平", "33.3%", "25%", "rrguide"):
        assert must in listing, f"燈泡裡少了「{must}」"
    assert "沒有下檔風險" in listing, "燈泡沒有說 ∞ 是什麼"




def test_網站發布了_cross_json(tmp_path=None):
    import json

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(
        _records(), out, sheets_dir=_sheets(tmp),
        valuations=_valuations(**{"5439": {
            "target_price": "395.6582", "downside_price": "155.2678",
            "reward_risk": "1.62", "as_of": "2026-09-18"}}),
    )
    feed = json.loads((out / "cross.json").read_text("utf-8"))
    assert feed["columns"] == ["six", "target", "downside"], feed["columns"]
    assert feed["quarter"], "沒有寫是哪一季的六大——接收端沒辦法在畫面上標日期"
    assert feed["as_of"] == "2026-09-18", feed["as_of"]

    six, target, floor = feed["rows"]["5439"]
    assert abs(target - 395.6582) < 1e-6 and abs(floor - 155.2678) < 1e-6
    assert six is not None and 0 <= six <= 6

    assert feed["rows"]["2330"][1] is None, feed["rows"]["2330"]
    assert feed["rows"]["2330"][0] is not None, "連六大都沒有帶過去"


def test_cross_json_不發算好的報酬風險比(tmp_path=None):
    import json

    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    feed = json.loads((out / "cross.json").read_text("utf-8"))
    assert "reward_risk" not in feed["columns"], (
        "cross.json 開始發算好的報酬風險比了。那個數字綁在**這邊**的收盤價上，"
        "而接收端跑在這條排程前面 34 分鐘——它拿到的會是昨天的價格算出來的。"
    )
    assert "market_price" not in feed["columns"], (
        "發了股價就等於發了報酬風險比——接收端會拿它去算，而它是昨天的"
    )




def _with_trend(tmp: Path) -> Path:
    out = tmp / "site"
    out.mkdir(parents=True, exist_ok=True)
    (out / "trend-report.html").write_text("<html>上游那份報告</html>", "utf-8")
    return out


def test_那一頁預設就帶_cross(tmp_path=None):
    import re

    tmp = tmp_path or _tmp()
    out = _with_trend(tmp)
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "trend.html").read_text("utf-8")
    src = re.search(r'<iframe[^>]*src="([^"]*)"', page).group(1)
    assert src.endswith("trend-report.html#cross"), (
        f"嵌的是 {src}——少了 #cross 的話這一頁只剩技術面四關"
    )
    assert "六大 &gt; 3" in page, "燈泡沒有說清楚常用的那一組門檻是什麼"
    assert "沒有下檔風險" in page, "燈泡沒有說「無風險」是什麼"
    title = page.split("<title>")[1].split("</title>")[0]
    assert title.startswith("趨勢×六大×報酬"), f"分頁標題還是舊的：{title}"
    assert '<h2 class="sr">趨勢×六大×報酬</h2>' in page, "頁面上的標題沒改"
    assert "只顯示、不篩" in page, "燈泡沒有說那兩個數字預設不拿來篩"
    assert "預設都是 <b>0</b>" in page, "燈泡沒有說預設值是 0"


def test_舊的交集網址是一頁轉址(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = _with_trend(tmp)
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "cross.html").read_text("utf-8")
    assert 'http-equiv="refresh"' in page, "轉址靠 JS 的話，JS 沒跑就卡在這一頁"
    assert 'url=trend.html' in page, page[:400]
    assert 'rel="canonical"' in page and 'href="trend.html"' in page
    assert '<a href="trend.html">' in page, "沒有可以按的連結"
    nav = (out / "index.html").read_text("utf-8").split("<nav>")[1].split("</nav>")[0]
    assert "cross.html" not in nav, "轉址頁還掛在導覽列上"


def test_每一種頁面的導覽列都有那一項(tmp_path=None):
    import re

    tmp = tmp_path or _tmp()
    out = _with_trend(tmp)
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    WANT = {"nav-list": "index.html", "nav-watch": "watchlist.html",
            "nav-trend": "trend.html"}
    seen = {}
    for name in ("index.html", "trend.html", "watchlist.html",
                 "stock/5439.html"):
        html = (out / name).read_text("utf-8")
        nav = html.split("<nav>")[1].split("</nav>")[0]
        items = re.findall(
            r'class="(nav-[\w-]+)" href="([^"]*)"[^>]*>([^<]+)<', nav)
        seen[name] = [t for _, _, t in items]
        for cls, href, label in items:
            want = WANT.get(cls)
            if want is None:
                continue
            assert href.endswith(want), (
                f"{name} 的〔{label}〕指到 {href!r}，應該以 {want} 結尾"
                "——多半是某個 context 漏了帶那個參數"
            )
    first = seen["index.html"]
    assert "趨勢×六大×報酬" in first, first
    for name, items in seen.items():
        assert items == first, (
            f"{name} 的導覽列和〔評等清單〕不一樣：\n  {items}\n  {first}"
        )


def test_沒有趨勢報告就整項不出現(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    assert not (out / "trend.html").exists(), "沒有上游報告卻畫了那一頁"
    assert not (out / "cross.html").exists(), "沒有上游報告卻畫了轉址頁"
    nav = (out / "index.html").read_text("utf-8").split("<nav>")[1].split("</nav>")[0]
    assert "趨勢×六大×報酬" not in nav


def test_觀察清單那一頁才有上移下移(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    watch = (out / "watchlist.html").read_text("utf-8")
    assert 'data-watchlist="1"' in watch
    assert 'data-move="5439"' in watch and 'data-delta="-1"' in watch
    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "data-watchlist" in js and "button[data-move]" in js, (
        "site.js 沒有把那兩顆鈕接上去，或是沒有只在觀察清單那一頁接"
    )
    assert '<span class="mv" hidden>' in watch


def test_排序和自訂順序不會打架(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    js = (out / "assets" / "site.js").read_text("utf-8")
    block = js.split("button[data-move]", 1)[1].split("\n  }", 1)[0]
    before = block.index("applyCustomOrder()")
    moved = block.index("TWSIXWatch.move(")
    assert before < moved, (
        "按上移的時候沒有先切回自訂順序——在別的排序下按，存起來的順序會和"
        "畫面上看到的對不起來"
    )


def test_隱藏的抓取按鈕真的看不見():
    css = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.css").read_text("utf-8")
    assert ".btn-grab[hidden]{display:none}" in css


def test_觀察清單不再有文字篩選框(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "watchlist.html").read_text(encoding="utf-8")
    assert "在觀察清單裡篩選" not in page and 'id="find"' not in page


def test_頁首搜尋框與抓取已全站拿掉(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    for name in ("index.html", "watchlist.html", "stock/5439.html", "stock/2330.html"):
        page = served(out, name)
        assert 'id="find"' not in page and 'id="grabnow"' not in page, name
        assert "台股評等清單" in page, f"{name} 沒有導覽列"


def test_網站圖示與加到主畫面的名稱(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    for name in ("favicon.ico", "favicon.svg", "apple-touch-icon.png", "icon-192.png",
                 "icon-512.png", "icon-maskable-512.png", "site.webmanifest"):
        assert (out / name).is_file() and (out / name).stat().st_size > 0, name
    manifest = json.loads((out / "site.webmanifest").read_text("utf-8"))
    assert manifest["name"] == "金股道" and manifest["short_name"] == "金股道"
    index = (out / "index.html").read_text("utf-8")
    assert "<title>金股道 | 禾熟之時，金股自到</title>" in index, "首頁標題＝書籤預設名稱"
    assert 'href="favicon.ico"' in index and 'content="金股道"' in index
    assert '<img class="brand" src="favicon.svg"' in index
    assert ">GoldenWay<" in index and "禾熟之時，金股自到" in index, "英文站名與副標"
    stock = (out / "stock" / "5439.html").read_text("utf-8")
    assert 'href="../favicon.ico"' in stock and 'href="../site.webmanifest"' in stock
    assert "台股與全球市場觀測站" not in index + stock


def test_大分頁不再顯示和導覽列重複的標題(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    for name, title in (("index.html", "台股評等清單"), ("watchlist.html", "台股觀察清單")):
        page = (out / name).read_text("utf-8")
        assert f'<h2 class="sr">{title}</h2>' in page and f"<h2>{title}</h2>" not in page, name
    watch = (out / "watchlist.html").read_text("utf-8")
    assert "跟著帳號存在雲端" in watch.split('class="tipbox"', 1)[1]
    index = (out / "index.html").read_text("utf-8")
    q = index[index.index('<span class="q-wrap">'):index.index('<div class="qf"')]
    assert 'id="q"' in q and 'class="bulb"' in q
    end = index[index.index('class="qf-end"'):]
    assert 'class="bulb"' not in end[:end.index("</span>")]


def test_嵌入頁的燈泡在_div_裡_單獨開啟收進燈泡(tmp_path=None):
    from twsix.report.build import MONITOR_PAGE, MONITOR_REPORT

    tmp = tmp_path or _tmp()
    out = _with_trend(tmp)
    (out / MONITOR_REPORT).write_text("<html>報告</html>", encoding="utf-8")
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    for name in ("trend.html", MONITOR_PAGE):
        page = (out / name).read_text("utf-8")
        assert '<div class="muted note-s embed-cap' in page, name
        assert '<p class="muted note-s embed-cap">' not in page, name
        cap = page[page.index('embed-cap'):page.index("<iframe")]
        before, inside = cap.split('class="tipbox"', 1)
        assert "單獨開啟" not in before and "單獨開啟這份報告" in inside, name


def test_各頁都有匯入觀察清單的按鈕():
    root = Path(__file__).resolve().parents[1] / "src/twsix/report/templates"
    read = lambda name: (root / name).read_text("utf-8")  # noqa: E731
    assert 'data-wg-src="trend" data-wg-name="趨勢×六大×報酬"' in read("trend.html.j2")
    sc = read("screener.html.j2")
    for src, name in (("sc-fin", "財務選股"), ("sc-trend", "趨勢選股"),
                      ("sc-strong", "近期強勢股"), ("sc-high", "創新高選股")):
        assert f'["{src}", "{name}"]' in sc, name
    ai = read("ai.html.j2")
    for src, name in (("ai-a", "AI營收驚喜"), ("ai-b", "AI供應鏈連動"), ("ai-d", "AI籌碼共振")):
        assert f"wg_imp('{src}', '{name}'" in ai, name
    for f, src, name in (("radar_bg/t4.html", "cf-t4", "籌碼篩選"), ("radar_bg/t5.html", "cf-t5", "基本面篩選"),
                         ("radar_bg/t6.html", "cf-t6", "籌碼×基本面")):
        assert f'data-wg-src="{src}" data-wg-name="{name}"' in read(f), name
        assert f"['{src}'] = function()" in read("radar_bg/mods.js"), src
    assert '["cf-picks", "精選漏斗"]' in read("radar.html.j2")
    assert '["cf-l1", "籌碼共振（L1）"]' in read("radar.html.j2"), "籌碼共振（L1）也要能一鍵匯入"
    assert 'id="wg"' in read("watchlist.html.j2")


def test_星號不會每一顆都掃一次整份頁面():
    import re

    js = (Path(__file__).resolve().parents[1] / "src/twsix/report/templates/site.js").read_text("utf-8")
    body = js.split("function paint(btn){", 1)[1].split("\n  }\n", 1)[0]
    assert "document.querySelector" not in body, "paint() 裡又直接查 DOM 了"
    assert len(re.findall(r"document\.querySelector\('table\[data-watchlist", js)) == 1


def test_河流圖有週期切換_其他區間按了才下載(tmp_path=None):
    tmp = tmp_path or _tmp()
    out = tmp / "site"
    build_site(_records(), out, sheets_dir=_sheets(tmp))
    page = (out / "stock" / "5439.html").read_text("utf-8")
    assert 'data-rng="river"' in page and 'data-r="1Y"' in page and 'data-r="ALL" class="on"' in page
    assert '<div class="rng-fig" data-rng-fig="river">' in page
    data = json.loads((out / "stock" / "5439.r.json").read_text("utf-8"))
    assert set(data["river"]) == {"1Y", "3Y"}
    assert data["river"]["1Y"].count("<svg") == 1
    js = (out / "assets" / "site.js").read_text("utf-8")
    assert "code + '.r.json'" in js and "window.TWSIXHover = function(root)" in js
    assert not (out / "stock" / "2330.r.json").exists()


def test_匯入觀察清單時打的名字和現有群組同名_可以直接覆蓋那個群組(tmp_path=None):
    js = (ROOT.parent / "src" / "twsix" / "report" / "templates" / "site.js").read_text("utf-8")
    imp = js[js.index("function importGroup(src, name, codes, asName){"):js.index("function sourceGroup(src){")]
    assert "x.name === asName" in imp and "replaced: true" in imp, "同名就覆蓋那個群組，不另外 push 一個"
    dlg = js[js.index("function ask(old, n, cb){"):]
    assert "改一下名字" not in dlg
    assert "bc.textContent = taken && !self ? '覆蓋〔' + v + '〕' : '另存新群組'" in dlg
    assert "bc.hidden = self" in dlg and "dlg.close(bc.hidden ? 'over' : 'copy')" in dlg
