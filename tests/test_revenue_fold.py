"""全市場月營收折回每一檔的〔營收〕分頁。

這一支修的是一個**綠燈的失敗**：〔全市場官方資料（月營收／季財報）〕跑完、
commit 了、workflow 綠燈，而 1,877 檔的個股頁上月營收還停在 115/07。原因是抓回來
的 `data/market/*_revenue/11508.csv` 是給評等清單用的，個股頁那張圖讀的是
`data/sheets/<代號>/營收.json.gz`——中間沒有人把前者攤回後者。

所以這裡守的是三件會安靜出錯的事：**欄位對應**、**格式**、以及**重疊時誰贏**。
"""

from __future__ import annotations

from twsix.ingest.merge_sheets import period_key
from twsix.ingest.revenue_fold import HEADER, folded, month_label, to_row

#: 官方開放資料上 5439 的 115/08 那一列，欄名與數值照抄
#: `data/market/tpex_revenue/11508.csv`。
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

#: 券商鏡像抓回來的同一個月，照抄 `data/sheets/5439/營收.json.gz`。
MIRROR_5439 = ["115/08", "1,108,099", "5.50%", "1,052,950", "5.24%", "7,749,508", "34.29%", ""]


def test_the_official_feed_reproduces_the_mirror_cell_for_cell():
    """折進去的不是一個近似值，是同一個數字。

    這是整支模組唯一真正需要證明的事：官方那份的七個欄位，換算成分頁的格式之後
    要和券商鏡像那一列**逐格相同**。四捨五入差一位、千分位少一個逗號，畫面上都
    看得出來是兩種來源拼起來的，而那種不一致遲早會被讀成資料本身的差異。

    全 repo 對過帳：2,018 個兩邊都有的月份，1,988 筆逐欄相同、24 筆是官方比較
    完整（鏡像那一格是空的）、6 筆真的不同（見下一條）。
    """
    assert to_row(OFFICIAL_5439) == MIRROR_5439


def test_a_month_the_mirror_never_had_is_added():
    """分頁沒有的月份要補進去，而且補在最上面——〔營收〕是新的排在前面。"""
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
    # 表頭留在原位：讀取端是按位置找它的。
    assert out[0] == list(HEADER)


def test_the_official_number_wins_when_both_sides_have_the_month():
    """同一個月兩邊都有，用官方那一份——而這不是一條偏好，是量過的。

    2,018 個重疊的月份裡有 6 筆真的不同，逐筆看過之後沒有一筆是官方錯：

      * 4804 115/07：官方累計 70,627、鏡像 1,076。官方那一列的〔備註〕寫著
        「上海地區業務清算。」——那是一個有解釋的數字。
      * 3631 115/07：官方當月 6,997、鏡像 5,065。備註「本月收入較去年同期營收
        增多肇因於錫价上漲50%多」。
      * 6283 115/07：當月與年增率兩邊一樣，只有月增率不同——因為兩邊對**上個月**
        的認知不同（官方的上月營收 121,651）。也就是說公司更正過六月。
      * 5310 115/07：-78.12% vs -78.13%，純粹是四捨五入。

    官方那一份是公司自己申報的，鏡像是第三方轉載；公司更正之後鏡像不一定跟上。
    所以重疊的時候官方贏。
    """
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
    """已經有那個月就回 None，不要把 1,958 個 gzip 每天重寫一次。

    回原樣也「正確」，但每一次排程都會產生兩千個內容相同、位元組不同的檔案
    （gzip 帶時間戳），而那會讓每一筆 commit 都看起來動了整個資料庫。
    """
    old = [list(HEADER), MIRROR_5439]
    assert folded(old, {"115/08": to_row(OFFICIAL_5439)}) is None


def test_a_stock_with_no_sheet_yet_gets_a_usable_one():
    """還沒有分頁的那一檔，自己造一張最小的——欄數要和鏡像那張一致。"""
    out = folded(None, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    assert out[0] == list(HEADER)
    assert len(out[1]) == len(HEADER)


def test_the_month_label_is_the_one_the_sheet_uses():
    """`11508` 是官方的寫法，`115/08` 是分頁的。認錯的話合併會當成兩個不同的月。"""
    assert month_label("11508") == "115/08"
    assert month_label("11412") == "114/12"
    assert month_label("") == ""
    assert month_label("亂寫") == ""


def test_a_blank_cell_stays_blank_instead_of_becoming_zero():
    """官方那一格是空的就留空。塞 0 進去的話，畫面上會出現一條假的零成長。"""
    row = to_row({"資料年月": "11508", "營業收入-當月營收": "1000",
                  "營業收入-去年同月增減(%)": ""})
    assert row[1] == "1,000"
    assert row[4] == ""


def test_a_big_percentage_keeps_its_thousands_separator():
    """基期小的時候年增率會是四位數，而鏡像那張表寫的是 `4,533.33%`。

    少了逗號的話，同一張分頁上哪一列是官方折進來的、哪一列是鏡像抓的，光看格式
    就分得出來——而那種差異遲早會被誤讀成資料本身的差異。
    """
    row = to_row({"資料年月": "11507", "營業收入-去年同月增減(%)": "4533.333"})
    assert row[4] == "4,533.33%"


# ── 第二層：分頁補好了，清單也要跟著動 ──────────────────────────────────

def _seeded(root, *, month="114/08", quarter="2025.2Q"):
    """一份最小的 data/：清單兩檔，分頁一檔（5439）帶著比清單新的月份。"""
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
    """個股頁寫 115/08、清單那一列還是 114/08——那是同一個網站上兩個矛盾的數字。"""
    import tempfile
    from pathlib import Path

    root = _seeded(Path(tempfile.mkdtemp()))
    from twsix.ingest.revenue_fold import behind

    assert behind(root) == ["5439"], "分頁比清單新的那一檔沒有被找出來"


def test_a_listing_row_that_matches_its_sheet_is_left_alone():
    """一樣新就不要重算——1,958 檔每天重算一次只是讓每筆 commit 都看起來動了整個庫。"""
    import tempfile
    from pathlib import Path

    root = _seeded(Path(tempfile.mkdtemp()), month="115/08", quarter="2026.2Q")
    from twsix.ingest.revenue_fold import behind

    assert behind(root) == []


def test_a_sheet_with_no_revenue_page_is_not_called_behind():
    """沒有分頁不等於分頁比較新。沒有東西可比的時候不要猜。"""
    import tempfile
    from pathlib import Path

    root = _seeded(Path(tempfile.mkdtemp()))
    (root / "sheets" / "5439" / "營收.json.gz").unlink()
    from twsix.ingest.revenue_fold import behind

    assert behind(root) == []


def test_the_fold_reports_which_codes_it_touched_not_just_how_many():
    """呼叫端還有第二件事要做（重算那幾檔的評等），所以要知道是哪幾檔。"""
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
    # 再折一次就沒東西可補了——而「沒東西可補」要回空的串列，不是回 None。
    assert fold_all(root)[0] == []


def _real_root(code="5439"):
    """把 repo 裡真的一檔分頁複製進暫存目錄，配一份落後的清單。

    用真的分頁而不是合成的，是因為這條測試要證明的正是「重算」——合成一份剛好
    算得出評等的分頁，等於把評分引擎重寫一次在測試裡。
    """
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
    """重算的是**評等**，不是只把 revenue_month 那一格改掉。

    多一個月的營收會讓〔營收年增率〕的評分跟著變。只改月份的話，留下的是一列
    「月份是新的、等第是舊的」的資料——而它看起來完全正常。
    """
    from twsix.ingest.revenue_fold import rerate
    from twsix.store.snapshots import Store

    root, code = _real_root()
    updated, kept = rerate(root, [code])
    assert (updated, kept) == (1, 0)
    rows = [r for r in Store(root).read("ratings") if r["stock_id"] == code]
    newest = next(r for r in rows if r["period_index"] == "1")
    assert newest["revenue_month"] > "114/08"
    assert newest["fiscal_quarter"] > "2025.2Q"
    # 九期都要重算，不是只有第一期。
    assert len(rows) > 1
    # 個股報表上沒有這三欄，要從舊的那一列帶過來——不然更新一檔的代價是弄丟它
    # 的產業，然後它從清單的產業篩選和搜尋索引裡消失。
    assert newest["name"] == "高技"
    assert newest["market"] == "上市"
    assert newest["industry"] == "電子零組件業"


def test_rerating_never_adds_a_stock_the_listing_did_not_have():
    """這張表的成員名單是全市場快照決定的，不該被「某一檔的分頁動了」改變。"""
    from twsix.ingest.revenue_fold import rerate
    from twsix.store.snapshots import Store

    root, code = _real_root()
    before = len(Store(root).read("ratings"))
    updated, _ = rerate(root, ["9999"])
    assert updated == 0
    assert len(Store(root).read("ratings")) == before


def test_rerating_keeps_the_old_row_when_the_new_one_is_older():
    """抓取可能退化成一份比較短的資料。過期但正確的評等，仍然是一個評等。"""
    from twsix.ingest.revenue_fold import rerate
    from twsix.store.snapshots import RATING_COLUMNS, Store

    root, code = _real_root()
    rows = Store(root).read("ratings")
    for r in rows:
        r["fiscal_quarter"] = "2099.4Q"     # 清單假裝自己來自未來
        r["revenue_month"] = "188/12"
    Store(root).write("ratings", rows, RATING_COLUMNS,
                      sort_by=("stock_id", "period_index"))

    updated, kept = rerate(root, [code])
    assert (updated, kept) == (0, 1)
    newest = next(r for r in Store(root).read("ratings")
                  if r["period_index"] == "1")
    assert newest["fiscal_quarter"] == "2099.4Q", "比較舊的那一份不該蓋過去"
