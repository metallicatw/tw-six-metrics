"""全市場資料的期別，以及為什麼它必須出現在檔名裡。

在這之前，每一季抓回來的財報都寫進同一個 `data/twse_income.csv`，下一季直接
覆蓋。於是六大指標需要的九期，永遠只有不斷被換掉的那一期——〔評等清單〕停在
一年前的活頁簿快照，原因不是官方端點給不出資料，是我們把它丟掉了。

一個檔名的問題，擋住了整個全市場評等。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from twsix.cli import UNDATED, MixedPeriods, market_path, period_of
from twsix.store.snapshots import Store


def test_the_period_comes_from_the_data_not_the_clock():
    """8/17 抓回來的是 7 月的營收；8/28 抓回來的是第 2 季的財報。

    用抓取日期命名，等於把「什麼時候拿到」寫在應該寫「這是哪一期」的地方，
    而且每年會有幾天剛好落在跨月跨季的邊界上算錯。
    """
    # 證交所：中文欄名
    assert period_of([{"公司代號": "1101", "年度": "115", "季別": "2"}]) == "115Q2"
    assert period_of([{"公司代號": "1101", "資料年月": "11507"}]) == "11507"
    # 櫃買的損益表：同一件事換成英文欄名
    assert period_of([{"SecuritiesCompanyCode": "1240", "Year": "115", "Season": "2"}]) == "115Q2"


def test_a_batch_with_two_periods_is_an_error_not_a_guess():
    """挑第一列的期別當檔名，會安靜地把兩期混進同一個檔案。

    那代表端點的行為變了（例如某天開始一次回好幾期），而這裡最不該發生的事，
    就是在那種時候若無其事地寫下去。
    """
    rows = [
        {"公司代號": "1101", "年度": "115", "季別": "2"},
        {"公司代號": "1102", "年度": "115", "季別": "1"},
    ]
    try:
        period_of(rows)
    except MixedPeriods as exc:
        assert "115Q1" in str(exc) and "115Q2" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("兩個期別混在一起卻沒有報錯")


def test_no_period_at_all_is_reported_as_empty_not_invented():
    assert period_of([{"公司代號": "1101"}]) == ""
    assert period_of([]) == ""


def test_company_master_data_has_no_period_and_should_not_get_one():
    """公司基本資料是「現在的樣子」，不是某一期的紀錄。

    改名、換產業別的時候我們要的是最新那一份，不是一份一份存下來的歷史。
    """
    assert "twse_companies" in UNDATED and "tpex_companies" in UNDATED
    assert market_path("twse_companies", "") == "twse_companies"


def test_two_quarters_land_in_two_files_instead_of_overwriting():
    """這就是整件事的重點。"""
    root = Path(tempfile.mkdtemp())
    store = Store(root)
    cols = ["公司代號", "年度", "季別", "營業收入"]

    q1 = [{"公司代號": "1101", "年度": "115", "季別": "1", "營業收入": "100"}]
    q2 = [{"公司代號": "1101", "年度": "115", "季別": "2", "營業收入": "220"}]
    for rows in (q1, q2):
        store.write(market_path("twse_income", period_of(rows)), rows, cols)

    assert (root / "market/twse_income/115Q1.csv").is_file()
    assert (root / "market/twse_income/115Q2.csv").is_file()
    # 第一季沒有被第二季蓋掉——在這個改動之前，這一行會失敗。
    assert store.read("market/twse_income/115Q1")[0]["營業收入"] == "100"
    assert store.read("market/twse_income/115Q2")[0]["營業收入"] == "220"


def test_the_files_we_already_had_were_moved_into_the_new_layout():
    """既有的 115Q2 與 11507 是我們手上唯一的資料點，搬進來而不是重抓。"""
    data = Path(__file__).resolve().parents[1] / "data"
    if not (data / "market").is_dir():  # pragma: no cover - 資料目錄可能沒帶下來
        return
    for name in ("twse_income", "twse_balance", "tpex_income", "tpex_balance"):
        assert (data / "market" / name / "115Q2.csv").is_file(), name
    for name in ("twse_revenue", "tpex_revenue"):
        assert (data / "market" / name / "11507.csv").is_file(), name
    # 舊的扁平檔案不該還在——留著它只會讓人不確定該讀哪一個。
    for name in ("twse_income", "twse_revenue"):
        assert not (data / f"{name}.csv").exists(), f"{name}.csv 還在"


def test_there_is_a_schedule_that_actually_accumulates():
    """把期別放進檔名，不會自己讓歷史長出來——要有人每天去問。

    在這個改動之前，`twsix fetch` 沒有任何排程在跑：repo 裡那份 115Q2 是手動跑
    一次留下的。所以檔名改對了，第二個資料點還是不會出現。

    每天跑一次而不是照申報截止日排：期別沒變的時候寫出來的位元組一模一樣，
    workflow 自己會判定沒有差異而結束；照日子排則要算五條規則，而算錯的代價是
    整整一期永遠拿不到——官方端點只給最新一期，沒有日期參數。
    """
    wf = Path(__file__).resolve().parents[1] / ".github/workflows/market.yml"
    text = wf.read_text("utf-8")
    assert "twsix fetch --all" in text
    assert "cron:" in text and "* * *" in text, "不是每天跑"
    # 白名單式的 git add 漏檔案的症狀，是下一行 pull 失敗而且不提檔名。踩過兩次。
    add = text[text.index("git add ") : text.index("if git diff --cached --quiet")]
    assert "data/market" in add
    assert "git diff --name-only" in text, "漏了「還有什麼沒被 commit」的自白"


def test_a_half_sized_fetch_does_not_overwrite_a_complete_one():
    """抓取很少乾脆地失敗，它比較常「成功地拿到半份」。

    這是同一個教訓的第三次：回補的快取判斷只看「新」，於是跑到一半被擋之後那些
    洞永遠補不回來；`_store_rating` 沒有比較期別，於是一份退化的抓取會蓋掉完整
    的舊評等。半份資料和完整資料在程式裡長得一模一樣。

    這裡尤其要擋，因為排程每天跑、每天寫同一個期別的檔案。端點只要有一天回了一
    份截斷的 JSON，完整的那一份就被換掉了，而且要等到季度評等算出奇怪的結果才會
    有人發現。
    """
    from twsix.cli import _shrank

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    cols = ["公司代號", "營業收入"]
    store.write(
        "market/twse_income/115Q2",
        [{"公司代號": str(1000 + i), "營業收入": "1"} for i in range(1000)],
        cols,
    )

    # 往上長是正常的：同一季裡公司陸續申報，1,017 → 1,048 就是這樣來的。
    assert _shrank(store, "market/twse_income/115Q2", 1048) == ""
    # 掉一點點也還好——偶爾有公司下市。
    assert _shrank(store, "market/twse_income/115Q2", 950) == ""
    # 掉一大截就是半份。
    assert "半份" in _shrank(store, "market/twse_income/115Q2", 400)
    # 還沒有這個期別的時候，什麼都不擋。
    assert _shrank(store, "market/twse_income/115Q3", 3) == ""


def test_the_manifest_does_not_churn_when_nothing_changed():
    """這個檔案每天被排程寫一次。

    每次都蓋上「現在幾點」的話，即使整批資料一個位元組都沒變，manifest 自己也會
    製造出一個 commit——一年 365 個只有時間戳在動的雜訊，而且會讓「這次抓取有沒
    有拿到新東西」從 git 歷史上再也讀不出來。
    """
    from twsix.store.snapshots import Manifest

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    m = Manifest(counts={"market/twse_income/115Q2": 1048})
    store.save_manifest(m)
    first = (root / "manifest.json").read_text("utf-8")
    assert '"generated_at"' in first and Manifest(**store.read_json("manifest")).generated_at

    # 同樣的內容再存一次：檔案一個位元組都不該動。
    store.save_manifest(Manifest(counts={"market/twse_income/115Q2": 1048}))
    assert (root / "manifest.json").read_text("utf-8") == first

    # 內容變了才換時間戳。
    store.save_manifest(Manifest(counts={"market/twse_income/115Q2": 1050}))
    assert (root / "manifest.json").read_text("utf-8") != first


def test_the_manifest_does_not_churn_when_only_the_fetch_order_changed():
    """第一次排程就踩到的那個洞。

    `sources` 是一個「每張表一筆」的集合，但它存成 list，而呼叫端是逐張表抓、
    抓到就把那一筆移到尾巴——所以清單的順序會跟著**抓取順序**跑。內容一個字都
    沒變，八筆的順序從字母序變成抓取序，diff 就有 20 行進 20 行出，照樣 commit
    了一次。哪一張表這次失敗了也會讓順序不一樣。
    """
    from twsix.store.snapshots import Manifest

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    a = {"name": "twse_income", "period": "115Q2", "rows": 1048}
    b = {"name": "tpex_income", "period": "115Q2", "rows": 883}
    c = {"name": "twse_revenue", "period": "11507", "rows": 1085}

    store.save_manifest(Manifest(sources=[a, b, c]))
    first = (root / "manifest.json").read_text("utf-8")

    # 同樣三筆，抓取順序不同——這不是內容的差異。
    store.save_manifest(Manifest(sources=[c, a, b]))
    assert (root / "manifest.json").read_text("utf-8") == first

    # 少了一筆才是差異。
    store.save_manifest(Manifest(sources=[a, b]))
    assert (root / "manifest.json").read_text("utf-8") != first


def test_one_dead_endpoint_does_not_throw_away_the_seven_tables_that_worked():
    """第一次排程真的跑起來的那天發生的事。

    `tpex_companies` 回了一份截斷的 JSON，另外七張表全部抓好、寫進 `data/market/`
    了，然後 `twsix fetch --all` 以 exit 1 結束，workflow 在 Commit 那一步之前就
    死掉——七張抓好的資料，連同那一期的歷史，一起被丟掉。

    丟掉的代價不對稱：官方端點只給最新一期，沒有日期參數，今天沒存下來的那一期
    是永遠拿不到；缺一張表則只是明天再補。所以退出碼問的是「有沒有存下任何
    東西」，不是「有沒有任何一張失敗」。
    """
    from twsix.cli import EXIT_FAIL, EXIT_OK, _fetch_status

    assert _fetch_status(7, ["tpex_companies：IncompleteRead"]) == EXIT_OK
    assert _fetch_status(8, []) == EXIT_OK
    # 一張都沒存下來就沒有什麼可留的了，那才是失敗。
    assert _fetch_status(0, ["tpex_companies：IncompleteRead"]) == EXIT_FAIL


def test_a_truncated_response_is_retried_instead_of_being_fatal():
    """`IncompleteRead` 不是 OSError 的子類別，於是它整個漏過了重試迴圈。

    伺服器宣告了 Content-Length 卻在送完之前關掉連線——所有失敗裡最該重試的一
    種，而我們一次都沒有重試過：tpex_companies 在四次排程裡失敗了三次。
    """
    import http.client
    import inspect

    from twsix.ingest.base import HttpClient

    src = inspect.getsource(HttpClient.get)
    assert "http.client.HTTPException" in src, "重試迴圈還是接不住截斷的回應"
    assert not issubclass(http.client.IncompleteRead, OSError), (
        "如果哪天 IncompleteRead 變成 OSError 的子類別，這個 except 就多餘了"
    )
