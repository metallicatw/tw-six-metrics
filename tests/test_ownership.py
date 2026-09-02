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


# ---------------------------------------------------------------------------
# 單檔回補：公開資訊觀測站的董監月線
# ---------------------------------------------------------------------------


def test_the_monthly_page_gives_the_official_totals_not_a_sum_we_computed():
    """查詢頁底部直接印著「全體董監持股合計」。

    開放資料只有逐人明細，所以那條路要自己判斷誰算董監、法人代表人要不要扣
    （見 is_director）。這條路不必——官方自己加好了。那條規則因此從「必須正確」
    降級成「拿來對帳」，而這裡正好對上：5439 的 115/03 是 7,059,687 股，
    Goodinfo 那一頁的 2026/03 寫 7,060 張。
    """
    from twsix.ingest.mops_insiders import parse

    page = (MARKET / "mops_stapap1_5439_11503.html").read_text("utf-8")
    t = parse(page, "5439")
    assert t.month == "2026/03"
    assert t.held == 7_059_687
    assert t.pledged == 0
    assert t.independent_held == 0

    gi = parse_directors(_goodinfo("董監持股"))
    row = next(r for r in gi.rows if r[0] == "2026/03")
    assert row[gi.columns.index("全體董監持股-持股張數")] == "7,060"


def test_the_label_must_match_the_whole_cell_not_be_contained_in_it():
    """「全體董監持股合計」「非獨立董監持股合計」「獨立董監持股合計」互相包含。

    用 `in` 去找「獨立董監持股合計」，第一個命中的是「非獨立」那一列——整份數字
    會安靜地錯成另一個群組的值。5439 這一期剛好可以抓到這個錯：全體是 7,059,687，
    獨立董監是 0，兩者差很遠。
    """
    from twsix.ingest.mops_insiders import parse

    page = (MARKET / "mops_stapap1_5439_11503.html").read_text("utf-8")
    t = parse(page, "5439")
    assert t.independent_held == 0            # 不是 7,059,687
    assert t.held == 7_059_687


def test_the_month_is_read_from_the_page_not_from_the_request():
    """問了 115/03 卻拿到 115/02 的話，抄請求參數會讓錯位的資料看起來正常。"""
    from twsix.ingest.mops_insiders import NoMonth, parse

    page = (MARKET / "mops_stapap1_5439_11503.html").read_text("utf-8")
    assert "資料年月:11503" in page.replace(" ", "")
    assert parse(page, "5439").month == "2026/03"
    for bad in ("", "<html>查無資料</html>"):
        try:
            parse(bad, "5439")
        except NoMonth:
            continue
        raise AssertionError(bad)


def test_counting_back_months_crosses_the_year():
    from twsix.ingest.mops_insiders import roc_months

    assert roc_months("11502", 4) == [
        ("115", "02"), ("115", "01"), ("114", "12"), ("114", "11"),
    ]
    assert len(roc_months("11507", 36)) == 36


def test_backfilled_months_and_monthly_snapshots_land_in_one_series():
    from twsix.ingest.mops_insiders import Totals

    root = _archive(_tmp())
    own.save_director_history(
        root,
        "5439",
        [
            Totals("5439", "2026/03", 7_059_687, 0, 0, 0),
            Totals("5439", "2026/02", 7_300_687, 0, 0, 0),
        ],
    )
    months = own.director_months(root, "5439")
    assert set(months) == {"2026/02", "2026/03", "2026/07"}  # 快照那一個月也在

    grid = own.directors_grid(root, "5439")
    assert [r[0] for r in grid[1:]] == ["2026/07", "2026/03", "2026/02"]   # 新到舊
    at = grid[0].index("全體董監持股-持股張數")
    assert [r[at] for r in grid[1:]] == ["10,015", "7,060", "7,301"]
    # 持股增減是相鄰兩列的差，只有在兩列都在手上時才算得出來
    delta = grid[0].index("全體董監持股-持股增減")
    assert grid[2][delta] == "-241"       # 7,060 - 7,301
    assert grid[-1][delta] == ""          # 最舊那一列沒有更早的可以比


def test_latest_custody_friday_is_the_newest_already_published_data_day():
    """回補之前要先判斷「有沒有可能有新的一週」，而且不能連網去問。

    偏差的方向要對：算晚了最多多跑一趟查詢頁，算早了會在真的有新資料時跳過
    回補。所以取的是「今天為止最近的那個週五」——不可能有比它更新的一期。
    """
    from twsix.cli import _latest_custody_friday

    assert _latest_custody_friday(date(2026, 8, 28)) == date(2026, 8, 28)  # 週五
    assert _latest_custody_friday(date(2026, 8, 29)) == date(2026, 8, 28)  # 週六
    assert _latest_custody_friday(date(2026, 8, 30)) == date(2026, 8, 28)  # 週日
    assert _latest_custody_friday(date(2026, 8, 31)) == date(2026, 8, 28)  # 週一
    assert _latest_custody_friday(date(2026, 9, 3)) == date(2026, 8, 28)   # 週四
    assert _latest_custody_friday(date(2026, 9, 4)) == date(2026, 9, 4)    # 下一個週五


def test_director_floor_survives_and_stops_asking_for_months_that_never_existed():
    """「問過了，那個月本來就沒有」要記下來，否則每次更新都重問一遍。

    一檔近年才上市的股票，上市之前那十幾個月永遠回查無資料，一個月一個請求、
    兩秒多一個。少了地板，那半分鐘每按一次「立即更新」就重付一次。
    """
    root = _archive(_tmp())
    assert own.director_floor(root, "6547") is None

    own.save_director_floor(root, "6547", "11203")
    assert own.director_floor(root, "6547") == "11203"

    # 只往更早的方向放寬，不會被後來某次比較淺的回補推高。
    own.save_director_floor(root, "6547", "11208")
    assert own.director_floor(root, "6547") == "11203"
    own.save_director_floor(root, "6547", "11101")
    assert own.director_floor(root, "6547") == "11101"

    # 地板不能被誤認成月線檔（那個目錄用 *.csv.gz glob）。
    assert own.director_history(root, "6547") == {}


def test_stock_workflow_commits_the_directors_backfill_it_paid_for():
    """〔加一檔個股〕抓到的董監月線與地板要 commit 進來，否則下次重抓。

    這條 workflow 只 add 它自己列出來的路徑；漏掉哪一個，那一份就留在 runner 上
    隨著機器一起消失，而使用者看到的是「明明更新過了，怎麼還是一樣慢」。
    """
    text = (ROOT.parent / ".github" / "workflows" / "stock.yml").read_text("utf-8")
    assert '"data/ownership/stock/$code.csv.gz"' in text
    assert '"data/ownership/directors_stock/$code."*' in text


def test_stock_workflow_commits_the_rating_it_just_recomputed():
    """`twsix report` 會把重算的評等寫回全市場表；那個檔案也必須被 commit。

    漏掉它有兩個後果，而且都不像「漏了一個檔案」：

    1. 個股頁是新的、清單是舊的——同一個網站上兩個數字互相矛盾。
    2. 下一行 `git pull --rebase` 會因為工作區有未暫存的變更而整個失敗，
       訊息是「cannot pull with rebase: You have unstaged changes」，完全
       不提是哪一個檔案。這個坑真的踩過，而且是先看到症狀 1 才找到原因。

    白名單式的 `git add` 就是會這樣：引擎多寫一個檔案，workflow 不會知道。
    所以除了這一行斷言，workflow 裡也留了一段「還有什麼沒被 commit」的自白。
    """
    text = (ROOT.parent / ".github" / "workflows" / "stock.yml").read_text("utf-8")
    add = text[text.index("git add "):text.index("if git diff --cached --quiet")]
    assert "data/ratings.csv" in add, "commit 那一步沒有 add data/ratings.csv"
    assert "git diff --name-only" in text, "漏了「還有什麼沒被 commit」的自白"


def _assert_tracked(path: Path) -> None:
    """這個檔案有沒有真的進版控？沒有 git 就跳過（測試本身零相依）。"""
    import shutil
    import subprocess

    if shutil.which("git") is None:  # pragma: no cover
        return
    rel = path.relative_to(ROOT.parent)
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(rel)],
        cwd=ROOT.parent, capture_output=True, text=True,
    )
    assert out.returncode == 0, f"{rel} 不在版本控制裡（多半被 .gitignore 吃掉了）"


def test_no_workflow_pays_for_a_second_runner_just_to_build_the_site():
    """建站要在抓完資料的那個 job 裡做，不是 call 另一個 workflow。

    workflow_call 起的是另一台 runner：重新排隊、checkout、setup-python、
    pip install、重跑一次剛跑過的測試，全部只為了四秒的 build。使用者按下
    「立即更新」之後等的時間裡，那段開機成本比抓資料本身還長。
    """
    wf = ROOT.parent / ".github" / "workflows"
    for name in ("stock.yml", "ownership.yml"):
        text = (wf / name).read_text("utf-8")
        live = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("workflows/pages.yml" in ln for ln in live), name
        assert "uses: ./.github/actions/build-site" in text, name
        assert "deploy-pages@v4" in text, name
        # 連 deploy 都不再另起一台 runner：起一台要十幾秒，deploy-pages 本身九秒。
        # 不用 yaml 解析——這一組測試要能在沒裝任何東西的 Python 上跑。
        after = text.split("\njobs:\n", 1)[1]
        jobs = [
            ln.strip().rstrip(":")
            for ln in after.splitlines()
            if ln.startswith("  ") and not ln.startswith("   ") and ln.rstrip().endswith(":")
        ]
        assert jobs == ["fetch"], f"{name} 還有第二個 job：{jobs}"
    # 建站的定義仍然只有一份，而且**在版本控制裡**。
    #
    # 「在磁碟上存在」不等於「推得上去」：.gitignore 原本有一條沒加斜線的
    # `site/`，它會比對任何深度的 site 目錄，於是 `.github/actions/site/` 被
    # 整個忽略——git add -A 一聲不吭地跳過，本機測試全綠，runner 上才說
    # Can't find 'action.yml'。所以這裡問的是 git，不是檔案系統。
    action = wf.parent / "actions" / "build-site" / "action.yml"
    assert action.exists()
    _assert_tracked(action)


def test_ci_installs_only_what_the_site_actually_imports():
    """建站的相依是 jinja2，不是 ".[all]"。

    all 會拖進 matplotlib（連著 numpy、pillow、fonttools）、pytest、ruff、mypy，
    四個裡面沒有一個在執行時被 import——圖表是自己畫的 SVG，測試跑的是零相依的
    run_tests.py。幾十 MB 的解壓縮，每個 job 付一次。
    """
    action = (ROOT.parent / ".github" / "actions" / "build-site" / "action.yml").read_text("utf-8")
    assert 'pip install -e ".[report]"' in action
    assert 'pip install -e ".[all]"' not in action


def test_the_stock_workflow_runs_the_suite_alongside_the_fetch_not_before_it():
    """抓取是等網路，CPU 幾乎閒著；排成一列就是白等二十幾秒。

    而那二十幾秒是使用者按下「立即更新」之後真的在看著螢幕的時間。兩件都得做，
    但沒有理由一件做完才做另一件。
    """
    text = (ROOT.parent / ".github" / "workflows" / "stock.yml").read_text("utf-8")
    live = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(live)
    assert "run_tests.py > /tmp/tests.log 2>&1 &" in body, "測試沒有丟到背景"
    assert 'wait "$tests"' in body, "沒有等測試結束就往下走了"
    # 測試沒過就不能 commit——並行不能變成不管。
    assert '不 commit 這次抓到的資料' in body
    order = body.index("run_tests.py"), body.index("twsix report"), body.index("git commit")
    assert order[0] < order[1] < order[2]


def test_the_backfill_guard_needs_a_full_year_not_just_a_current_week():
    """只看「新」是個陷阱：回補是新到舊跑的。

    一次跑到一半被擋，存下來的正好是最新那幾週；下一次進來看到「最新的有了」
    就跳過，那些洞於是永遠補不回來——使用者看到的是「明明按了立即更新，大戶
    持股還是缺」。
    """
    import inspect

    from twsix import cli

    src = inspect.getsource(cli._backfill_holders)
    assert "len(have) >= BACKFILL_WEEKS" in src
    assert "max(have) >= newest" in src


def test_a_scattered_failure_does_not_abandon_the_rest_of_the_year():
    """五次失敗散落在 51 週裡是很正常的抖動。

    上一版數的是**總數**，五次就整批停下，後面四十幾週一次都不問。連續才算被擋。
    """
    import inspect

    from twsix import cli

    src = inspect.getsource(cli._backfill_holders)
    assert "streak" in src and "streak >= 6" in src
    # 邊跑邊存：step 被砍或 runner 逾時的時候，拿到的那幾週不能跟著消失。
    assert src.count("save_stock_history") >= 2
    # 沒拿到的再試一次，而不是留給下一次執行。
    assert "再試一次" in src


def test_a_corporate_director_holding_several_seats_is_counted_once():
    """明細是**一席一列**，而一個法人董事可以占好幾席。

    統一（1216）的高權投資占三席：董事長本人一列、董事本人兩列，三列都寫著同樣
    的 284,330,536 股。逐列相加會把那一塊算三次——1,130,457 張，實際是 561,796
    張，多了一倍；質押 240,090 正好是 80,030 的三倍。

    這個洞是使用者從 Goodinfo 匯入 1216 的十年歷史時撞出來的：兩邊差了兩倍，而
    扣掉重複的兩次之後一股不差。5439 沒撞到，因為它的董事沒有人占兩席——也就是
    說，只用一檔股票驗收的來源，驗的是那一檔，不是那個規則。

    實測全市場 1,085 家上市公司裡有 498 家有重複席次。這不是邊角案例。
    """
    company = _insiders()["1216"]

    seats = [p for p in company.people if p.name == "高權投資股份有限公司"]
    assert len(seats) == 3, "fixture 應該保留那三席"
    assert {p.held for p in seats} == {284_330_536}, "三列寫的是同一塊持股"

    assert round(company.held / 1000) == 561_796        # Goodinfo 上是 561,796 張
    assert round(company.pledged / 1000) == 80_030      # 不是 240,090
    assert company.independent_held == 0


def test_two_directors_with_different_names_both_count():
    """去重是以「持有人」為單位，不是把董事會壓成一個人。"""
    company = _insiders()["1216"]
    names = {p.name for p in company.people if ins.is_director(p.title)}
    assert "侯博裕" in names and "林蒼生" in names
    # 兩個人的持股都要在合計裡
    only = sum(
        p.held for p in company.people
        if ins.is_director(p.title) and p.name in ("侯博裕", "林蒼生")
    )
    assert only == 141_697_024 + 49_916_266
    assert company.held > only
