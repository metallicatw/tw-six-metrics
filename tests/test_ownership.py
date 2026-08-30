"""官方來源的〔大戶持股〕〔董監持股〕，對照 Goodinfo 那兩頁驗收。

這一組測試的重點不是「程式跑得動」，是**兩條路算出來的是同一個數字**。
Goodinfo 的頁面是使用者親手存下來的，它顯示什麼是既定事實；集保與公開資訊
觀測站的開放資料是我們新走的路。兩者逐格相同，才有資格說「不用再手動下載了」。

fixture 是真實回應剪出來的五檔（5439/2330/1101/0050/00403A），欄位、編碼、
分級結構都原封不動——剪掉的只是其他 4,042 檔。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "src"))

from twsix.ingest import insiders as ins  # noqa: E402
from twsix.ingest import tdcc  # noqa: E402
from twsix.ingest.goodinfo import parse_directors, parse_holders  # noqa: E402
from twsix.store import ownership as own  # noqa: E402

MARKET = ROOT / "pages" / "market"


def _tdcc() -> dict[str, tdcc.Snapshot]:
    return tdcc.parse((MARKET / "tdcc_20260828.csv").read_text("utf-8-sig"))


def _insiders() -> dict[str, ins.Company]:
    records = []
    for name in ("insiders_twse_11507.json", "insiders_tpex_11507.json"):
        records += json.loads((MARKET / name).read_text("utf-8"))
    return ins.parse(records)


def _goodinfo(sheet: str):
    return (ROOT / "pages" / "5439" / f"5439_{sheet}.html").read_text("utf-8")


# ---------------------------------------------------------------------------
# 大戶持股：TDCC 對照 Goodinfo
# ---------------------------------------------------------------------------


def test_tdcc_reproduces_every_tier_goodinfo_shows():
    """八個級距逐格相同。這一條成立，Goodinfo 就沒有存在的必要了。

    TDCC 分 15 級（以股計），Goodinfo 分 8 級（以張計）。併法是推出來的，但
    **不是靠它成立**——靠的是併完之後和那一頁上的數字對得起來。
    """
    snap = _tdcc()["5439"]
    page = parse_holders(_goodinfo("大戶持股"))
    latest = page.rows[0]
    assert latest[0] == "26W35"

    mine = snap.percents
    for name, _ in tdcc.TIERS:
        theirs = float(latest[page.columns.index(tdcc.PREFIX + name)])
        # Goodinfo 進位到小數一位，我們留兩位；差距只該來自那一次進位。
        assert abs(mine[name] - theirs) <= 0.06, name


def test_the_week_label_matches_goodinfos_own_numbering_for_every_row():
    """「26W35」不是 ISO 週。

    Goodinfo 以「含 1/1 的那一週」為第 1 週、週日起算，所以 2022 年有第 53 週。
    用 ISO 算會在 69 列上對不起來，而且是 2022 年整年——那種錯不會爆炸，只會讓
    合併時多出一批對不齊的列。這裡拿那一頁的 257 列全部問一次。
    """
    page = parse_holders(_goodinfo("大戶持股"))
    for row in page.rows:
        label, md = row[0], row[1]
        year = 2000 + int(label[:2])
        month, day = (int(x) for x in md.split("/"))
        # 統計日期沒有年份；跨年的那一列年份要往回退一年
        for candidate in (year, year - 1):
            try:
                when = date(candidate, month, day)
            except ValueError:
                continue
            if tdcc.week_label(when) == label:
                break
        else:  # pragma: no cover - 失敗時才會走到
            raise AssertionError(f"{label} / {md} 算不出來")


def test_the_adjustment_bracket_is_a_deduction_from_the_total():
    """分級 16「差異數調整」是減項，而且合計才是權威值。

    4,047 檔裡有 70 檔的 16 非零，這 70 檔滿足 sum(1..15) - 16 == 17。
    00403A 的級距加起來比合計多 2,000 股。TDCC 沒說那 2,000 股該從哪一級扣，
    所以不猜：分母用合計，級距照抄，差額掛在 adjust 上讓它看得見。

    一般的股票 adjust 是 0，級距相加就等於合計——5439 是這一類。
    """
    odd = _tdcc()["00403A"]
    assert odd.adjust == 2_000
    assert sum(odd.tiers.values()) - odd.adjust == odd.shares
    # 比例因此超出 100 一點點，而「一點點」要小到說得出口
    assert 100.0 < sum(odd.percents.values()) < 100.001

    plain = _tdcc()["5439"]
    assert plain.adjust == 0
    assert sum(plain.tiers.values()) == plain.shares


def test_percentages_are_divided_once_not_summed_from_rounded_parts():
    """TDCC 的比例欄已經四捨五入；五級相加會把誤差疊起來。

    ≦10張 是 1+2+3 三級，＞10張≦50張 是 4..8 五級。從股數除一次，和從比例欄
    相加，在 5439 上就差 0.02 個百分點——不大，但那是我們自己製造的誤差。
    """
    snap = _tdcc()["5439"]
    assert abs(sum(snap.percents.values()) - 100.0) < 1e-6
    assert snap.tiers["≦10張"] == 2_418_069 + 18_923_760 + 6_529_361


def test_a_response_that_is_not_the_distribution_table_is_refused():
    for bad in ("", "a,b,c\n1,2,3\n", "資料日期,證券代號\n20260828,5439\n"):
        try:
            tdcc.parse(bad)
        except tdcc.NotTdccData:
            continue
        raise AssertionError(f"{bad!r} 不該解析成功")


# ---------------------------------------------------------------------------
# 董監持股：公開資訊觀測站對照 Goodinfo
# ---------------------------------------------------------------------------


def test_the_director_total_matches_goodinfo_exactly():
    """10,015 張、質押 0、獨立董監 0——三個數字全中。

    關鍵在扣掉「法人代表人」：法人董事本身已經佔一列，它指派的自然人代表另有
    自己的持股，不是董事。含進去會多 1,020 張，Goodinfo 就對不起來了。
    """
    company = _insiders()["5439"]
    assert company.month == "2026/07"
    assert company.held == 10_014_687          # -> 10,015 張
    assert company.pledged == 0
    assert company.independent_held == 0

    page = parse_directors(_goodinfo("董監持股"))
    row = next(r for r in page.rows if r[0] == "2026/07")
    assert row[page.columns.index("全體董監持股-持股張數")] == "10,015"
    assert row[page.columns.index("全體董監持股-質押張數")] == "0"


def test_a_legal_persons_representative_is_not_a_director():
    company = _insiders()["5439"]
    reps = [p for p in company.people if "法人代表人" in p.title]
    assert reps, "5439 這一期本來就有法人代表人，fixture 不該剪掉"
    assert sum(p.held for p in reps) == 1_020_502
    assert not any(ins.is_director(p.title) for p in reps)


def test_managers_are_in_the_file_but_not_in_the_total():
    """同一個人會出現在多列：李泰輝既是董事也是總經理，同一筆 850,000 股。

    整份直接加總會把他算兩次。這就是為什麼規則是「職稱含董事或監察人」，而不是
    「全部加起來」。
    """
    company = _insiders()["5439"]
    titles = {p.title for p in company.people}
    assert "總經理本人" in titles and "財務部門主管本人" in titles
    assert not ins.is_director("總經理本人")
    assert not ins.is_director("財務部門主管本人")
    assert ins.is_director("董事長本人") and ins.is_director("獨立董事本人")


def test_both_exchanges_land_in_the_same_shape():
    """上市的欄名是「選任時持股 」（尾隨空白），上櫃沒有。

    這一欄沒被用到，但它提醒：欄名照抄，不要自己整理。兩邊合起來之後，同一個
    parse() 要能一視同仁。
    """
    market = _insiders()
    assert "1101" in market and "5439" in market      # 上市、上櫃各一
    assert market["1101"].month == market["5439"].month


def test_the_roc_month_becomes_a_real_month():
    assert ins.month_label("11507") == "2026/07"
    assert ins.month_label("09912") == "2010/12"
    for bad in ("", "115", "abcde"):
        try:
            ins.month_label(bad)
        except ins.NotInsiderData:
            continue
        raise AssertionError(bad)


# ---------------------------------------------------------------------------
# 檔案庫：快照存進去，個股表折出來
# ---------------------------------------------------------------------------


def _archive(tmp: Path) -> Path:
    root = tmp / "ownership"
    own.save_holders(root, _tdcc())
    own.save_directors(root, _insiders())
    return root


def _tmp() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp(prefix="twsix-own-"))


def test_a_snapshot_round_trips_into_a_per_stock_grid():
    root = _archive(_tmp())
    grid = own.holders_grid(root, "5439")
    assert grid[0] == list(tdcc.COLUMNS)
    assert len(grid) == 2
    assert grid[1][0] == "26W35"
    assert grid[1][1] == "08/28"
    assert grid[1][2] == "9.298"      # 集保庫存(萬張)，和 Goodinfo 同一個數字


def test_the_directors_percentage_uses_that_months_custody_not_todays():
    """分母是集保庫存合計——Goodinfo 標「發行張數」，值卻正是這個。

    用「最新的股本」去除三年前的董監持股，在增資過的公司上會把整條線壓低，
    而那條線正是要看的東西。所以分母按月取。
    """
    root = _archive(_tmp())
    grid = own.directors_grid(root, "5439")
    row = grid[1]
    assert row[0] == "2026/07"
    assert row[grid[0].index("全體董監持股-持股張數")] == "10,015"
    assert row[grid[0].index("全體董監持股-持股(%)")] == "10.77"   # Goodinfo 顯示 10.8
    assert row[grid[0].index("發行張數(萬張)")] == "9.298"


def test_a_stock_with_no_snapshot_gets_an_empty_grid_not_a_fake_one():
    root = _archive(_tmp())
    assert own.holders_grid(root, "9999") == []
    assert own.directors_grid(root, "9999") == []


def test_the_archive_is_byte_stable_for_the_same_input():
    """同樣的資料要壓出同樣的位元組，否則每週的 commit 都像整檔重寫。"""
    a, b = _tmp(), _tmp()
    p1 = own.save_holders(a / "ownership", _tdcc())
    p2 = own.save_holders(b / "ownership", _tdcc())
    assert p1.read_bytes() == p2.read_bytes()


# ---------------------------------------------------------------------------
# 合併：官方往後長，Goodinfo 往前補
# ---------------------------------------------------------------------------


def test_official_rows_merge_into_imported_goodinfo_history():
    """兩條路的欄名一致，所以合併不需要任何轉換。

    匯入的 257 週留著（那是官方來源給不了的歷史），最新那一週換成官方的數字
    （比較精確），Goodinfo 才有的欄位（當週股價）原封不動。
    """
    imported = parse_holders(_goodinfo("大戶持股")).grid
    root = _archive(_tmp())
    merged = tdcc.merge(imported, own.holders_grid(root, "5439"))

    assert merged[0] == imported[0]                  # 欄名不變（Goodinfo 的較寬）
    assert len(merged) == len(imported)              # 同一週，沒有多出一列
    head = merged[0]
    latest = merged[1]
    assert latest[0] == "26W35"
    assert latest[head.index("當週股價-收盤")] == "264.5"          # Goodinfo 獨有，留著
    assert latest[head.index(tdcc.PREFIX + "＞1千張")] == "26.33"  # 官方，較精確


def test_merging_never_blanks_a_value_that_was_already_there():
    """空白是「不知道」，不是「這裡是空的」。

    官方那份算不出〔持股增減〕（要有上一個月），如果讓它覆蓋，Goodinfo 已經
    填好的那一格就被擦掉了——資料變少而且沒有人會發現。
    """
    existing = [["月別", "甲", "乙"], ["2026/07", "有值", "也有值"]]
    fresh = [["月別", "甲", "乙"], ["2026/07", "新值", ""]]
    merged = tdcc.merge(existing, fresh)
    assert merged[1] == ["2026/07", "新值", "也有值"]


def test_periods_sort_by_number_not_by_string():
    assert tdcc.period_key("26W35") > tdcc.period_key("26W9")
    assert tdcc.period_key("2026/07") > tdcc.period_key("2025/12")
    assert tdcc.period_key("看不懂") == (0, 0)


# ---------------------------------------------------------------------------
# 單檔回補：集保查詢頁的 51 週
# ---------------------------------------------------------------------------


def test_the_query_page_and_the_open_data_agree_on_the_same_week():
    """兩條路、同一週、同一組數字。

    開放資料（全市場、最新一週）和查詢頁（單檔、51 週）是集保的兩個出口。回補
    來的歷史要能和每週累積的資料接在同一條線上，前提就是這一條——否則圖上會在
    「回補結束、累積開始」的那一週出現一個接縫。

    fixture 是查詢 20260807 的真實回應；那一週不在開放資料的 fixture 裡（它只有
    20260828），所以這裡比的是**結構**：解析出來的合計、人數、級距總和自洽，
    而且級距的併法和開放資料那條路用的是同一個 TIERS。
    """
    from twsix.ingest.tdcc_history import parse_week

    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    snap = parse_week(page, "5439", date(2026, 8, 7))
    assert snap.holders == 34_631
    assert snap.shares == 92_976_751
    assert sum(snap.tiers.values()) == snap.shares
    assert snap.adjust == 0
    # 這一週的 ＞1千張 是 29.13%（查詢頁自己也印這個數字）
    assert abs(snap.percents["＞1千張"] - 29.13) < 0.01
    assert tdcc.week_label(snap.day) == "26W32"


def test_the_total_row_is_found_by_its_label_not_its_number():
    """查詢頁的第 16 列是「合計」；開放資料的 16 是「差異數調整」、17 才是合計。

    照序號抓，這條路會把最後一個級距當成合計——分母整個錯掉，比例全部爆炸，
    而且不會丟出任何例外。所以認的是標籤。
    """
    from twsix.ingest.tdcc_history import parse_week

    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    rows = [
        r
        for r in __import__(
            "twsix.ingest.tdcc_history", fromlist=["_rows"]
        )._rows(page)
        if r[0].strip().isdigit() or "合" in r[1]
    ]
    numbered = [r for r in rows if r[0].strip().isdigit()]
    assert numbered[-1][0] == "16" and "合" in numbered[-1][1], "第 16 列就是合計"
    snap = parse_week(page, "5439", date(2026, 8, 7))
    # 合計沒有被當成第 16 個級距塞進 ＞1千張
    assert snap.tiers["＞1千張"] == 27_087_435


def test_a_page_without_the_table_is_refused_rather_than_returning_zeroes():
    """token 用過就作廢，回來的頁面沒有表格也不報錯——只是安靜地沒有資料。

    那是這條路最危險的失敗模式：不接下一個 token 的話，第二週之後全部是空的，
    而空的看起來就像「這一檔那幾週沒有股東」。所以沒有表格要當成錯誤。
    """
    from twsix.ingest.tdcc_history import NoHistory, parse_week

    for bad in ("", "<html><body>請重新查詢</body></html>"):
        try:
            parse_week(bad, "5439", date(2026, 8, 7))
        except NoHistory:
            continue
        raise AssertionError(f"{bad!r} 不該解析成功")


def test_backfilled_weeks_and_market_snapshots_land_in_one_series():
    """回補的和每週累積的是同一條線。

    存法不同（一檔一個檔案 vs 一週一個檔案），但讀出來要是一串連續的週。重疊的
    那一週以全市場快照為準——兩邊實測相同，這個順序只是為了「同一週永遠只有一
    個來源說了算」。
    """
    from twsix.ingest.tdcc_history import parse_week

    root = _archive(_tmp())
    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    own.save_stock_history(root, "5439", [parse_week(page, "5439", date(2026, 8, 7))])

    weeks = own.weeks(root, "5439")
    assert set(weeks) == {date(2026, 8, 7), date(2026, 8, 28)}
    grid = own.holders_grid(root, "5439")
    assert [r[0] for r in grid[1:]] == ["26W35", "26W32"]      # 新到舊


def test_backfilling_twice_does_not_duplicate_a_week():
    from twsix.ingest.tdcc_history import parse_week

    root = _tmp() / "ownership"
    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    snap = parse_week(page, "5439", date(2026, 8, 7))
    assert own.save_stock_history(root, "5439", [snap]) == 1
    assert own.save_stock_history(root, "5439", [snap]) == 1


def test_the_backfill_also_gives_the_directors_percentage_a_denominator_per_month():
    """回補的週線同時餵給董監那張表。

    董監持股的分母是集保庫存合計。只有最新一週時，三年前的董監持股只能拿今天的
    股本去除；有了一年的週線，每個月都有自己的分母。
    """
    from twsix.ingest.tdcc_history import parse_week

    root = _archive(_tmp())
    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    own.save_stock_history(root, "5439", [parse_week(page, "5439", date(2026, 8, 7))])
    custody = own.custody_shares(root, "5439")
    assert custody["2026/08"] == 92_976_751
