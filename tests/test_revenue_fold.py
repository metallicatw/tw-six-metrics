
from __future__ import annotations

from twsix.ingest.merge_sheets import period_key
from twsix.ingest.revenue_fold import HEADER, folded, month_label, to_row

OFFICIAL_5439 = {
    "公司代號": "5439",
    "資料年月": "11508",
    "營業收入-當月營收": "1108099",
    "營業收入-上月比較增減(%)": "5.500784044527255",
    "營業收入-去年當月營收": "1052950",
    "營業收入-去年同月增減(%)": "5.237570634882948",
    "累計營業收入-當月累計營收": "7749508",
    "累計營業收入-前期比較增減(%)": "34.29374766595645",
}

MIRROR_5439 = ["115/08", "1,108,099", "5.50%", "1,052,950", "5.24%", "7,749,508", "34.29%", ""]


def test_the_official_feed_reproduces_the_mirror_cell_for_cell():
    assert to_row(OFFICIAL_5439) == MIRROR_5439


def test_a_month_the_mirror_never_had_is_added():
    old = [
        list(HEADER),
        ["115/07", "1,050,323", "-4.78%", "1,005,270", "4.48%", "6,641,409", "40.78%", ""],
        ["115/06", "1,103,029", "10.28%", "903,156", "22.13%", "5,591,086", "50.61%", ""],
    ]
    out = folded(old, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    data = [r for r in out if r and period_key(r[0])]
    assert [r[0] for r in data] == ["115/08", "115/07", "115/06"]
    assert data[0] == MIRROR_5439
    assert out[0] == list(HEADER)


def test_the_official_number_wins_when_both_sides_have_the_month():
    stale = [
        list(HEADER),
        ["115/08", "999,999", "0.00%", "1", "0.00%", "1", "0.00%", ""],
    ]
    out = folded(stale, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    data = [r for r in out if r and period_key(r[0])]
    assert len(data) == 1, "同一個月不可以留下兩列"
    assert data[0] == MIRROR_5439


def test_nothing_to_add_reports_nothing_rather_than_rewriting():
    old = [list(HEADER), MIRROR_5439]
    assert folded(old, {"115/08": to_row(OFFICIAL_5439)}) is None


def test_a_stock_with_no_sheet_yet_gets_a_usable_one():
    out = folded(None, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    assert out[0] == list(HEADER)
    assert len(out[1]) == len(HEADER)


def test_the_month_label_is_the_one_the_sheet_uses():
    assert month_label("11508") == "115/08"
    assert month_label("11412") == "114/12"
    assert month_label("") == ""
    assert month_label("亂寫") == ""


def test_a_blank_cell_stays_blank_instead_of_becoming_zero():
    row = to_row({"資料年月": "11508", "營業收入-當月營收": "1000",
                  "營業收入-去年同月增減(%)": ""})
    assert row[1] == "1,000"
    assert row[4] == ""


def test_a_big_percentage_keeps_its_thousands_separator():
    row = to_row({"資料年月": "11507", "營業收入-去年同月增減(%)": "4533.333"})
    assert row[4] == "4,533.33%"



def _seeded(root, *, month="114/08", quarter="2025.2Q"):
    from twsix.store import sheets as sheet_store
    from twsix.store.snapshots import RATING_COLUMNS, Store

    blank = {c: "" for c in RATING_COLUMNS}
    rows = []
    for code, name, industry in (("1101", "台泥", "水泥工業"),
                                 ("5439", "高技", "電子零組件業")):
        row = dict(blank)
        row.update(stock_id=code, name=name, market="上市", industry=industry,
                   period_index="1", fiscal_quarter=quarter, revenue_month=month,
                   composite="1")
        rows.append(row)
    Store(root).write("ratings", rows, RATING_COLUMNS,
                      sort_by=("stock_id", "period_index"))
    sheet_store.write_grid(root / "sheets" / "5439", "營收",
                           [list(HEADER), MIRROR_5439])
    return root


def test_a_listing_row_older_than_its_own_sheet_is_found():
    import tempfile
    from pathlib import Path

    root = _seeded(Path(tempfile.mkdtemp()))
    from twsix.ingest.revenue_fold import behind

    assert behind(root) == ["5439"], "分頁比清單新的那一檔沒有被找出來"


def test_a_listing_row_that_matches_its_sheet_is_left_alone():
    import tempfile
    from pathlib import Path

    root = _seeded(Path(tempfile.mkdtemp()), month="115/08", quarter="2026.2Q")
    from twsix.ingest.revenue_fold import behind

    assert behind(root) == []


def test_a_sheet_with_no_revenue_page_is_not_called_behind():
    import tempfile
    from pathlib import Path

    root = _seeded(Path(tempfile.mkdtemp()))
    (root / "sheets" / "5439" / "營收.json.gz").unlink()
    from twsix.ingest.revenue_fold import behind

    assert behind(root) == []


def test_the_fold_reports_which_codes_it_touched_not_just_how_many():
    import tempfile
    from pathlib import Path

    from twsix.ingest.revenue_fold import fold_all

    root = Path(tempfile.mkdtemp())
    (root / "sheets" / "5439").mkdir(parents=True)
    (root / "market" / "tpex_revenue").mkdir(parents=True)
    import csv as _csv

    with (root / "market" / "tpex_revenue" / "11508.csv").open(
        "w", encoding="utf-8", newline=""
    ) as fh:
        writer = _csv.DictWriter(fh, fieldnames=list(OFFICIAL_5439))
        writer.writeheader()
        writer.writerow(OFFICIAL_5439)

    codes, same, absent = fold_all(root)
    assert codes == ["5439"]
    assert (same, absent) == (0, 0)
    assert fold_all(root)[0] == []


def _real_root(code="5439"):
    import shutil
    import tempfile
    from pathlib import Path

    from twsix.store.snapshots import RATING_COLUMNS, Store

    src = Path(__file__).resolve().parents[1] / "data" / "sheets" / code
    root = Path(tempfile.mkdtemp())
    shutil.copytree(src, root / "sheets" / code)
    blank = {c: "" for c in RATING_COLUMNS}
    row = dict(blank)
    row.update(stock_id=code, name="高技", market="上市", industry="電子零組件業",
               period_index="1", fiscal_quarter="2025.2Q", revenue_month="114/08",
               composite="1")
    Store(root).write("ratings", [row], RATING_COLUMNS,
                      sort_by=("stock_id", "period_index"))
    return root, code


def test_rerating_brings_the_listing_row_up_to_the_sheet():
    from twsix.ingest.revenue_fold import rerate
    from twsix.store.snapshots import Store

    root, code = _real_root()
    updated, kept = rerate(root, [code])
    assert (updated, kept) == (1, 0)
    rows = [r for r in Store(root).read("ratings") if r["stock_id"] == code]
    newest = next(r for r in rows if r["period_index"] == "1")
    assert newest["revenue_month"] > "114/08"
    assert newest["fiscal_quarter"] > "2025.2Q"
    assert len(rows) > 1
    assert newest["name"] == "高技"
    assert newest["market"] == "上市"
    assert newest["industry"] == "電子零組件業"


def test_rerating_never_adds_a_stock_the_listing_did_not_have():
    from twsix.ingest.revenue_fold import rerate
    from twsix.store.snapshots import Store

    root, code = _real_root()
    before = len(Store(root).read("ratings"))
    updated, _ = rerate(root, ["9999"])
    assert updated == 0
    assert len(Store(root).read("ratings")) == before


def test_rerating_keeps_the_old_row_when_the_new_one_is_older():
    from twsix.ingest.revenue_fold import rerate
    from twsix.store.snapshots import RATING_COLUMNS, Store

    root, code = _real_root()
    rows = Store(root).read("ratings")
    for r in rows:
        r["fiscal_quarter"] = "2099.4Q"
        r["revenue_month"] = "188/12"
    Store(root).write("ratings", rows, RATING_COLUMNS,
                      sort_by=("stock_id", "period_index"))

    updated, kept = rerate(root, [code])
    assert (updated, kept) == (0, 1)
    newest = next(r for r in Store(root).read("ratings")
                  if r["period_index"] == "1")
    assert newest["fiscal_quarter"] == "2099.4Q", "比較舊的那一份不該蓋過去"
