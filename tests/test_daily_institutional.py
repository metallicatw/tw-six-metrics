
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from twsix.report.sections import INST_DAYS, institutional
from twsix.store import sheets as sheet_store
from twsix.store.daily import InstDay, institutional_history

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _back_to(date: str) -> int:
    folder = DATA / "market" / "daily" / "institutional"
    return sum(1 for p in folder.glob("*.csv.gz") if p.name[:10] >= date)


def _num(text: Any) -> float | None:
    text = str(text).replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def test_the_open_data_agrees_with_the_mirror_across_the_whole_repo():
    from collections import Counter  # noqa: PLC0415

    history = institutional_history(DATA)
    assert history, "repo 裡沒有每日三大法人的資料，這條測試就沒有意義"

    per_day: Counter[str] = Counter()
    per_day_bad: Counter[str] = Counter()
    ok = mismatched = 0
    for folder in sorted((DATA / "sheets").iterdir()):
        days = history.get(folder.name)
        if not folder.is_dir() or not days:
            continue
        grid = sheet_store.read_grid(folder, "三大法人")
        if not grid:
            continue
        by_date = {row[0]: row for row in grid if row and "/" in str(row[0])}
        for day in days:
            row = by_date.get(day.roc_label)
            if row is None:
                continue
            mirror = [_num(row[i]) for i in (1, 2, 3, 4)]
            if None in mirror:
                continue
            per_day[day.roc_label] += 1
            if [day.foreign, day.trust, day.dealer, day.total] == mirror:
                ok += 1
            else:
                mismatched += 1
                per_day_bad[day.roc_label] += 1
    total = ok + mismatched
    assert ok > 500, f"只對到 {ok} 筆，重疊的日期太少，這條測試沒有力氣"

    rate = mismatched / total
    assert rate < 0.0005, (
        f"{total:,} 筆裡有 {mismatched:,} 筆對不上（{rate:.3%}）。"
        "事後更正是萬分之幾；到這個量級要先看是不是單位或欄序變了"
    )

    broken = sorted(
        (d, per_day_bad[d], per_day[d])
        for d in per_day_bad
        if per_day[d] >= 20 and per_day_bad[d] / per_day[d] >= 0.05
    )
    assert not broken, "這幾天整天都對不上，來源的版面可能變了：" + "、".join(
        f"{d} {bad}/{n}" for d, bad, n in broken
    )


def test_the_daily_total_is_the_sum_of_the_rounded_columns():
    day = next(
        d for d in institutional_history(DATA, lookback=_back_to("2026-09-03"), days=10_000)["5439"] if d.date == "2026-09-03"
    )
    assert (day.foreign, day.trust, day.dealer) == (93, 0, -44)
    assert day.total == 49, "把原始的合計直接換算會得到 50"


def test_the_rounding_goes_away_from_zero_not_to_the_even_number():
    day = next(
        d for d in institutional_history(DATA, lookback=_back_to("2026-09-03"), days=10_000)["6423"] if d.date == "2026-09-03"
    )
    assert day.foreign == -7, "用了銀行家捨入"


def test_the_roc_label_matches_the_sheets_own_date_format():
    assert InstDay("2026-09-02", 1, 2, 3, 6).roc_label == "115/09/02"


def test_a_day_the_sheet_does_not_have_is_added_with_only_the_net():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    newest = base.days[0]["date"]

    fake = InstDay("2099-12-31", 100.0, 5.0, -3.0, 102.0)
    merged = institutional(grid, [fake])
    assert merged is not None
    assert merged.from_daily == 1
    top = merged.days[0]
    assert top["date"] == "188/12/31" and top["date"] > newest
    assert top["net"]["外資"] == 100.0
    prev = merged.days[1]
    for k, n in (("外資", 100.0), ("投信", 5.0), ("自營商", -3.0)):
        assert top["holding"][k] == prev["holding"][k] + n, k
    assert top["share"]["外資"] is None
    assert len(merged.days) == min(len(base.days) + 1, INST_DAYS)


def test_the_sheet_wins_for_a_day_both_sides_have():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    same = base.days[0]["date"]
    year, month, day = same.split("/")
    overlap = InstDay(f"{int(year) + 1911}-{month}-{day}", -99999.0, 0.0, 0.0, -99999.0)

    merged = institutional(grid, [overlap])
    assert merged is not None
    assert merged.from_daily == 0, "同一天不該被當成新的一天補進來"
    assert merged.days[0]["net"]["外資"] == base.days[0]["net"]["外資"]
    assert merged.days[0]["share"]["外資"] == base.days[0]["share"]["外資"]


def test_the_totals_are_only_recomputed_when_the_window_actually_moved():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    assert institutional(grid, []).totals == base.totals
    assert institutional(grid, None).totals == base.totals

    moved = institutional(grid, [InstDay("2099-12-31", 100.0, 0.0, 0.0, 100.0)])
    assert moved is not None
    assert moved.totals["外資"] == sum(
        v for d in moved.days if (v := d["net"]["外資"]) is not None
    )


def test_the_share_card_points_at_a_day_that_has_a_share():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    merged = institutional(grid, [InstDay("2099-12-31", 1.0, 0.0, 0.0, 1.0)])
    assert merged is not None
    assert merged.latest["share"]["外資"] is None
    assert merged.latest_share is not None
    assert merged.latest_share["share"]["外資"] is not None


def test_a_stock_with_no_sheet_still_gets_nothing_rather_than_half_a_table():
    assert institutional([], [InstDay("2026-09-02", 1.0, 0.0, 0.0, 1.0)]) is None


def test_the_history_reader_is_missing_data_tolerant():
    empty = Path(tempfile.mkdtemp())
    assert institutional_history(empty) == {}


def test_the_newest_institutional_day_is_part_of_the_content_signature():
    from twsix.report.build import stock_signature

    base = Path(tempfile.mkdtemp()) / "5439"
    base.mkdir(parents=True)
    (base / "ISQ.json.gz").write_bytes(b"x")
    rows = [{"stock_id": "5439"}]
    one = [InstDay("2026-09-02", 1.0, 0.0, 0.0, 1.0)]
    two = [InstDay("2026-09-03", 2.0, 0.0, 0.0, 2.0)] + one
    assert stock_signature(rows, base, None, False, one) != (
        stock_signature(rows, base, None, False, two)
    )
    assert stock_signature(rows, base, None, False, one) == (
        stock_signature(rows, base, None, False, list(one))
    )



SAMPLES = ROOT / "reference/samples"


def _raw_sample(name: str):
    import gzip
    import json as _json

    with gzip.open(SAMPLES / f"{name}.raw.gz", "rb") as fh:
        return _json.loads(fh.read().decode("utf-8-sig"))


def test_the_dated_endpoints_give_both_exchanges_for_one_past_day():
    from twsix.ingest.daily import (
        parse_tpex_institutional_dated,
        parse_twse_institutional,
    )

    listed = parse_twse_institutional(_raw_sample("twse_t86_rwd_dated"))
    otc = parse_tpex_institutional_dated(_raw_sample("tpex_insti_rwd_dated"))
    assert listed and otc, "有一邊解不出資料"
    assert {r["market"] for r in listed} == {"上市"}
    assert {r["market"] for r in otc} == {"上櫃"}
    days = {r["date"] for r in listed} | {r["date"] for r in otc}
    assert days == {"2026-09-01"}, f"兩邊的日期兜不起來：{days}"
    assert len(listed) + len(otc) > 1_500, \
        f"兩市合計只有 {len(listed) + len(otc)} 列，正常一天約 1,900 列"


def test_the_otc_columns_are_checked_against_the_tables_own_identity():
    from twsix.ingest.daily import parse_tpex_institutional_dated

    rows = parse_tpex_institutional_dated(_raw_sample("tpex_insti_rwd_dated"))
    bad = [
        r for r in rows
        if r["total"] != (r["foreign"] or 0) + (r["trust"] or 0) + (r["dealer"] or 0)
    ]
    assert not bad, f"{len(bad)} 列對不上恆等式，例：{bad[:2]}"


def test_a_shuffled_otc_payload_is_refused_rather_than_silently_wrong():
    import contextlib
    import io as _io

    from twsix.ingest.daily import parse_tpex_institutional_dated

    payload = _raw_sample("tpex_insti_rwd_dated")
    table = payload["tables"][0]
    for row in table["data"]:
        if len(row) > 22:
            row[22] = "999999999"
    noise = _io.StringIO()
    with contextlib.redirect_stdout(noise):
        got = parse_tpex_institutional_dated(payload)
    assert got == [], "欄序看起來位移了，parser 卻還是回了資料"
    assert "對不上" in noise.getvalue(), "拒收了卻沒有說為什麼——正式執行時那一行是警報"


def test_a_non_trading_day_is_empty_not_an_error():
    from twsix.ingest.daily import parse_tpex_institutional_dated

    assert parse_tpex_institutional_dated({"tables": [{"date": "115/08/15", "data": []}]}) == []
    assert parse_tpex_institutional_dated({}) == []




def test_qfii_parsers_read_the_real_responses():
    from twsix.ingest.daily import parse_tpex_qfii, parse_twse_qfii

    twse = parse_twse_qfii(_raw_sample("twse_qfii_dated"))
    tpex = parse_tpex_qfii(_raw_sample("tpex_qfii_dated"))
    assert len(twse) > 1000 and len(tpex) > 800
    tsmc = next(r for r in twse if r["code"] == "2330")
    assert tsmc["date"] == "2026-10-02" and tsmc["market"] == "上市"
    assert 60 < tsmc["pct"] < 80
    assert abs(tsmc["held"] / tsmc["issued"] * 100 - tsmc["pct"]) < 0.05
    assert all(r["code"].isdigit() and len(r["code"]) in (4, 6) for r in twse)
    assert any(r["code"] == "912000" for r in twse)
    top = next(r for r in tpex if r["code"] == "8455")
    assert top["date"] == "2026-09-03" and top["pct"] == 87.85


def test_qfii_holiday_is_empty_not_an_error():
    from twsix.ingest.daily import parse_tpex_qfii, parse_twse_qfii

    assert parse_tpex_qfii(_raw_sample("tpex_qfii_dated_holiday")) == []
    assert parse_twse_qfii({"stat": "很抱歉，沒有符合條件的資料!"}) == []


def test_qfii_with_shifted_columns_is_rejected_whole():
    from twsix.ingest.daily import parse_twse_qfii

    payload = _raw_sample("twse_qfii_dated")
    fields = payload["fields"]
    a, b = fields.index("全體外資及陸資持股比率"), fields.index("外資及陸資尚可投資比率")
    fields[a], fields[b] = fields[b], fields[a]
    assert parse_twse_qfii(payload) == []


def test_official_foreign_share_fills_the_days_the_sheet_left_blank():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    fake = InstDay("2099-12-31", 100.0, 5.0, -3.0, 102.0, foreign_held=1234.0, foreign_pct=0.1234)
    merged = institutional(grid, [fake])
    assert merged is not None
    top = merged.days[0]
    assert top["share"]["外資"] == 0.1234 and top["holding"]["外資"] == 1234.0
    assert top["holding"]["投信"] == merged.days[1]["holding"]["投信"] + 5.0
    assert merged.latest_share is top


def test_trust_and_dealer_holdings_follow_the_mirrors_own_arithmetic():
    import random

    names = sorted(p.name for p in (DATA / "sheets").iterdir() if (p / "三大法人.json.gz").exists())
    random.seed(7)
    ok = bad = 0
    for code in random.sample(names, min(120, len(names))):
        inst = institutional(sheet_store.read_grid(DATA / "sheets" / code, "三大法人"))
        if not inst:
            continue
        for older, newer in zip(inst.days[1:], inst.days[:-1], strict=True):
            h0, h1, n = older["holding"]["投信"], newer["holding"]["投信"], newer["net"]["投信"]
            if None in (h0, h1, n):
                continue
            ok, bad = (ok + 1, bad) if abs(h0 + n - h1) < 0.5 else (ok, bad + 1)
    assert ok > 500 and bad / (ok + bad) < 0.03, (ok, bad)


def test_three_institution_share_is_total_over_issued():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    fake = InstDay("2099-12-31", 0.0, 0.0, 0.0, 0.0, foreign_held=1000.0, foreign_pct=0.1, issued_lots=10000.0)
    top = institutional(grid, [fake]).days[0]
    h = top["holding"]
    assert h["合計"] == h["外資"] + h["投信"] + h["自營商"]
    assert abs(top["share"]["三大法人"] - h["合計"] / 10000.0) < 1e-12


def test_official_foreign_share_never_overrides_the_sheet():
    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    base = institutional(grid)
    assert base is not None
    day = next(d for d in base.days if d["share"]["外資"] is not None)
    y, m, dd = day["date"].split("/")
    same = InstDay(f"{int(y) + 1911}-{m}-{dd}", 0.0, 0.0, 0.0, 0.0, foreign_pct=0.999)
    merged = institutional(grid, [same])
    assert merged is not None
    again = next(d for d in merged.days if d["date"] == day["date"])
    assert again["share"]["外資"] == day["share"]["外資"]


def _older_days(grid, n: int) -> list[InstDay]:
    from datetime import date, timedelta

    base = institutional(grid)
    y, m, d = base.days[-1]["date"].split("/")
    day = date(int(y) + 1911, int(m), int(d))
    out = []
    while len(out) < n:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            out.append(InstDay(day.isoformat(), 10.0, 2.0, -1.0, 11.0))
    return out


def test_the_charts_cover_120_days_while_the_table_stays_at_20():
    from twsix.report.sections import CHART_DAYS

    grid = sheet_store.read_grid(DATA / "sheets/5439", "三大法人")
    merged = institutional(grid, _older_days(grid, 150))
    assert merged is not None
    assert merged.chart_span == CHART_DAYS == 120
    assert len(merged.days) == INST_DAYS
    assert merged.from_daily == 0, "只補了更舊的日子，表格那 20 天沒變"
    assert merged.totals == institutional(grid).totals


def test_holdings_before_the_anchor_are_walked_back_from_the_net():
    from twsix.report.sections import _carry_holdings

    days = [
        {"date": f"115/09/0{i}", "net": {"外資": None, "投信": n, "自營商": 0.0, "合計": None},
         "holding": dict.fromkeys(("外資", "投信", "自營商", "合計")),
         "share": {"外資": None, "三大法人": None}}
        for i, n in ((1, 5.0), (2, 7.0), (3, -4.0))
    ]
    days[2]["holding"]["投信"] = 100.0
    _carry_holdings(days, {})
    assert [d["holding"]["投信"] for d in days] == [97.0, 104.0, 100.0]
    assert all(d["holding"]["自營商"] is None for d in days)


def test_a_missing_net_stops_the_backward_walk():
    from twsix.report.sections import _carry_holdings

    days = [
        {"date": f"115/09/0{i}", "net": {"外資": None, "投信": n, "自營商": None, "合計": None},
         "holding": dict.fromkeys(("外資", "投信", "自營商", "合計")),
         "share": {"外資": None, "三大法人": None}}
        for i, n in ((1, 5.0), (2, None), (3, -4.0))
    ]
    days[2]["holding"]["投信"] = 100.0
    _carry_holdings(days, {})
    assert days[1]["holding"]["投信"] == 104.0
    assert days[0]["holding"]["投信"] is None
