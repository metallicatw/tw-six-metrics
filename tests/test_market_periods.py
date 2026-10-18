
from __future__ import annotations

import tempfile
from pathlib import Path

from twsix.cli import UNDATED, MixedPeriods, market_path, period_of
from twsix.store.snapshots import Store


def test_the_period_comes_from_the_data_not_the_clock():
    assert period_of([{"公司代號": "1101", "年度": "115", "季別": "2"}]) == "115Q2"
    assert period_of([{"公司代號": "1101", "資料年月": "11507"}]) == "11507"
    assert period_of([{"SecuritiesCompanyCode": "1240", "Year": "115", "Season": "2"}]) == "115Q2"


def test_a_batch_with_two_periods_is_an_error_not_a_guess():
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
    assert "twse_companies" in UNDATED and "tpex_companies" in UNDATED
    assert market_path("twse_companies", "") == "twse_companies"


def test_two_quarters_land_in_two_files_instead_of_overwriting():
    root = Path(tempfile.mkdtemp())
    store = Store(root)
    cols = ["公司代號", "年度", "季別", "營業收入"]

    q1 = [{"公司代號": "1101", "年度": "115", "季別": "1", "營業收入": "100"}]
    q2 = [{"公司代號": "1101", "年度": "115", "季別": "2", "營業收入": "220"}]
    for rows in (q1, q2):
        store.write(market_path("twse_income", period_of(rows)), rows, cols)

    assert (root / "market/twse_income/115Q1.csv").is_file()
    assert (root / "market/twse_income/115Q2.csv").is_file()
    assert store.read("market/twse_income/115Q1")[0]["營業收入"] == "100"
    assert store.read("market/twse_income/115Q2")[0]["營業收入"] == "220"


def test_the_files_we_already_had_were_moved_into_the_new_layout():
    data = Path(__file__).resolve().parents[1] / "data"
    if not (data / "market").is_dir():  # pragma: no cover - 資料目錄可能沒帶下來
        return
    for name in ("twse_income", "twse_balance", "tpex_income", "tpex_balance"):
        assert (data / "market" / name / "115Q2.csv").is_file(), name
    for name in ("twse_revenue", "tpex_revenue"):
        assert (data / "market" / name / "11507.csv").is_file(), name
    for name in ("twse_income", "twse_revenue"):
        assert not (data / f"{name}.csv").exists(), f"{name}.csv 還在"


def test_there_is_a_schedule_that_actually_accumulates():
    import re

    wf = Path(__file__).resolve().parents[1] / ".github/workflows/market.yml"
    text = wf.read_text("utf-8")
    assert "twsix fetch --all" in text
    crons = re.findall(r'cron:\s*"([^"]+)"', text)
    assert crons, "沒有排程"

    def runs_on(month, day):
        for c in crons:
            _m, _h, dom, mon, dow = c.split()
            if dow != "*":
                continue
            months = range(1, 13) if mon == "*" else [int(x) for x in mon.split(",")]
            if month not in months:
                continue
            for part in dom.split(","):
                lo, _, hi = part.partition("-")
                if part == "*" or int(lo) <= day <= int(hi or lo):
                    return True
        return False

    for month, day, what in ((9, 10, "月營收"), (5, 15, "Q1"), (8, 14, "Q2"),
                             (11, 14, "Q3"), (3, 31, "年報"), (3, 20, "年報前")):
        assert runs_on(month, day), f"{month}/{day}（{what}截止前後）沒有排到"
    assert runs_on(7, 18) and runs_on(7, 25), "下半月的保險那兩天不見了"
    add = text[text.index("git add ") : text.index("if git diff --cached --quiet")]
    assert "data/market" in add
    assert "git diff --name-only" in text, "漏了「還有什麼沒被 commit」的自白"


def test_a_half_sized_fetch_does_not_overwrite_a_complete_one():
    from twsix.cli import _shrank

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    cols = ["公司代號", "營業收入"]
    store.write(
        "market/twse_income/115Q2",
        [{"公司代號": str(1000 + i), "營業收入": "1"} for i in range(1000)],
        cols,
    )

    assert _shrank(store, "market/twse_income/115Q2", 1048) == ""
    assert _shrank(store, "market/twse_income/115Q2", 950) == ""
    assert "半份" in _shrank(store, "market/twse_income/115Q2", 400)
    assert _shrank(store, "market/twse_income/115Q3", 3) == ""


def test_the_manifest_does_not_churn_when_nothing_changed():
    from twsix.store.snapshots import Manifest

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    m = Manifest(counts={"market/twse_income/115Q2": 1048})
    store.save_manifest(m)
    first = (root / "manifest.json").read_text("utf-8")
    assert '"generated_at"' in first and Manifest(**store.read_json("manifest")).generated_at

    store.save_manifest(Manifest(counts={"market/twse_income/115Q2": 1048}))
    assert (root / "manifest.json").read_text("utf-8") == first

    store.save_manifest(Manifest(counts={"market/twse_income/115Q2": 1050}))
    assert (root / "manifest.json").read_text("utf-8") != first


def test_the_manifest_does_not_churn_when_only_the_fetch_order_changed():
    from twsix.store.snapshots import Manifest

    root = Path(tempfile.mkdtemp())
    store = Store(root)
    a = {"name": "twse_income", "period": "115Q2", "rows": 1048}
    b = {"name": "tpex_income", "period": "115Q2", "rows": 883}
    c = {"name": "twse_revenue", "period": "11507", "rows": 1085}

    store.save_manifest(Manifest(sources=[a, b, c]))
    first = (root / "manifest.json").read_text("utf-8")

    store.save_manifest(Manifest(sources=[c, a, b]))
    assert (root / "manifest.json").read_text("utf-8") == first

    store.save_manifest(Manifest(sources=[a, b]))
    assert (root / "manifest.json").read_text("utf-8") != first


def test_one_dead_endpoint_does_not_throw_away_the_seven_tables_that_worked():
    from twsix.cli import EXIT_FAIL, EXIT_OK, _fetch_status

    assert _fetch_status(7, ["tpex_companies：IncompleteRead"]) == EXIT_OK
    assert _fetch_status(8, []) == EXIT_OK
    assert _fetch_status(0, ["tpex_companies：IncompleteRead"]) == EXIT_FAIL


def test_a_truncated_response_is_retried_instead_of_being_fatal():
    import http.client
    import inspect

    from twsix.ingest.base import HttpClient

    src = inspect.getsource(HttpClient.get)
    assert "http.client.HTTPException" in src, "重試迴圈還是接不住截斷的回應"
    assert not issubclass(http.client.IncompleteRead, OSError), (
        "如果哪天 IncompleteRead 變成 OSError 的子類別，這個 except 就多餘了"
    )
