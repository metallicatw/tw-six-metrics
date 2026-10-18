
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




def test_tdcc_reproduces_every_tier_goodinfo_shows():
    snap = _tdcc()["5439"]
    page = parse_holders(_goodinfo("大戶持股"))
    latest = page.rows[0]
    assert latest[0] == "26W35"

    mine = snap.percents
    for name, _ in tdcc.TIERS:
        theirs = float(latest[page.columns.index(tdcc.PREFIX + name)])
        assert abs(mine[name] - theirs) <= 0.06, name


def test_the_week_label_matches_goodinfos_own_numbering_for_every_row():
    page = parse_holders(_goodinfo("大戶持股"))
    for row in page.rows:
        label, md = row[0], row[1]
        year = 2000 + int(label[:2])
        month, day = (int(x) for x in md.split("/"))
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
    odd = _tdcc()["00403A"]
    assert odd.adjust == 2_000
    assert sum(odd.tiers.values()) - odd.adjust == odd.shares
    assert 100.0 < sum(odd.percents.values()) < 100.001

    plain = _tdcc()["5439"]
    assert plain.adjust == 0
    assert sum(plain.tiers.values()) == plain.shares


def test_percentages_are_divided_once_not_summed_from_rounded_parts():
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




def test_the_director_total_matches_goodinfo_exactly():
    company = _insiders()["5439"]
    assert company.month == "2026/07"
    assert company.held == 10_014_687
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
    company = _insiders()["5439"]
    titles = {p.title for p in company.people}
    assert "總經理本人" in titles and "財務部門主管本人" in titles
    assert not ins.is_director("總經理本人")
    assert not ins.is_director("財務部門主管本人")
    assert ins.is_director("董事長本人") and ins.is_director("獨立董事本人")


def test_both_exchanges_land_in_the_same_shape():
    market = _insiders()
    assert "1101" in market and "5439" in market
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
    assert grid[1][2] == "9.298"


def test_the_directors_percentage_uses_that_months_custody_not_todays():
    root = _archive(_tmp())
    grid = own.directors_grid(root, "5439")
    row = grid[1]
    assert row[0] == "2026/07"
    assert row[grid[0].index("全體董監持股-持股張數")] == "10,015"
    assert row[grid[0].index("全體董監持股-持股(%)")] == "10.77"
    assert row[grid[0].index("發行張數(萬張)")] == "9.298"


def test_a_stock_with_no_snapshot_gets_an_empty_grid_not_a_fake_one():
    root = _archive(_tmp())
    assert own.holders_grid(root, "9999") == []
    assert own.directors_grid(root, "9999") == []


def test_the_archive_is_byte_stable_for_the_same_input():
    a, b = _tmp(), _tmp()
    p1 = own.save_holders(a / "ownership", _tdcc())
    p2 = own.save_holders(b / "ownership", _tdcc())
    assert p1.read_bytes() == p2.read_bytes()




def test_official_rows_merge_into_imported_goodinfo_history():
    imported = parse_holders(_goodinfo("大戶持股")).grid
    root = _archive(_tmp())
    merged = tdcc.merge(imported, own.holders_grid(root, "5439"))

    assert merged[0] == imported[0]
    assert len(merged) == len(imported)
    head = merged[0]
    latest = merged[1]
    assert latest[0] == "26W35"
    assert latest[head.index("當週股價-收盤")] == "264.5"
    assert latest[head.index(tdcc.PREFIX + "＞1千張")] == "26.33"


def test_merging_never_blanks_a_value_that_was_already_there():
    existing = [["月別", "甲", "乙"], ["2026/07", "有值", "也有值"]]
    fresh = [["月別", "甲", "乙"], ["2026/07", "新值", ""]]
    merged = tdcc.merge(existing, fresh)
    assert merged[1] == ["2026/07", "新值", "也有值"]


def test_periods_sort_by_number_not_by_string():
    assert tdcc.period_key("26W35") > tdcc.period_key("26W9")
    assert tdcc.period_key("2026/07") > tdcc.period_key("2025/12")
    assert tdcc.period_key("看不懂") == (0, 0)




def test_the_query_page_and_the_open_data_agree_on_the_same_week():
    from twsix.ingest.tdcc_history import parse_week

    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    snap = parse_week(page, "5439", date(2026, 8, 7))
    assert snap.holders == 34_631
    assert snap.shares == 92_976_751
    assert sum(snap.tiers.values()) == snap.shares
    assert snap.adjust == 0
    assert abs(snap.percents["＞1千張"] - 29.13) < 0.01
    assert tdcc.week_label(snap.day) == "26W32"


def test_the_total_row_is_found_by_its_label_not_its_number():
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
    assert snap.tiers["＞1千張"] == 27_087_435


def test_a_page_without_the_table_is_refused_rather_than_returning_zeroes():
    from twsix.ingest.tdcc_history import NoHistory, parse_week

    for bad in ("", "<html><body>請重新查詢</body></html>"):
        try:
            parse_week(bad, "5439", date(2026, 8, 7))
        except NoHistory:
            continue
        raise AssertionError(f"{bad!r} 不該解析成功")


def test_backfilled_weeks_and_market_snapshots_land_in_one_series():
    from twsix.ingest.tdcc_history import parse_week

    root = _archive(_tmp())
    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    own.save_level_history(root, "5439", [parse_week(page, "5439", date(2026, 8, 7))])

    weeks = own.weeks(root, "5439")
    assert set(weeks) == {date(2026, 8, 7), date(2026, 8, 28)}
    grid = own.holders_grid(root, "5439")
    assert [r[0] for r in grid[1:]] == ["26W35", "26W32"]


def test_backfilling_twice_does_not_duplicate_a_week():
    from twsix.ingest.tdcc_history import parse_week

    root = _tmp() / "ownership"
    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    snap = parse_week(page, "5439", date(2026, 8, 7))
    assert own.save_level_history(root, "5439", [snap]) == 1
    assert own.save_level_history(root, "5439", [snap]) == 1
    assert own.save_stock_history(root, "5439", [snap]) == 0
    assert not (root / own.STOCK_DIR / "5439.csv.gz").exists()


def test_the_backfill_also_gives_the_directors_percentage_a_denominator_per_month():
    from twsix.ingest.tdcc_history import parse_week

    root = _archive(_tmp())
    page = (MARKET / "tdcc_qrystock_20260807.html").read_text("utf-8")
    own.save_level_history(root, "5439", [parse_week(page, "5439", date(2026, 8, 7))])
    custody = own.custody_shares(root, "5439")
    assert custody["2026/08"] == 92_976_751




def test_the_monthly_page_gives_the_official_totals_not_a_sum_we_computed():
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
    from twsix.ingest.mops_insiders import parse

    page = (MARKET / "mops_stapap1_5439_11503.html").read_text("utf-8")
    t = parse(page, "5439")
    assert t.independent_held == 0
    assert t.held == 7_059_687


def test_the_month_is_read_from_the_page_not_from_the_request():
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
    assert set(months) == {"2026/02", "2026/03", "2026/07"}

    grid = own.directors_grid(root, "5439")
    assert [r[0] for r in grid[1:]] == ["2026/07", "2026/03", "2026/02"]
    at = grid[0].index("全體董監持股-持股張數")
    assert [r[at] for r in grid[1:]] == ["10,015", "7,060", "7,301"]
    delta = grid[0].index("全體董監持股-持股增減")
    assert grid[2][delta] == "-241"
    assert grid[-1][delta] == ""


def test_latest_custody_friday_is_the_newest_already_published_data_day():
    from twsix.cli import _latest_custody_friday

    assert _latest_custody_friday(date(2026, 8, 28)) == date(2026, 8, 28)
    assert _latest_custody_friday(date(2026, 8, 29)) == date(2026, 8, 28)
    assert _latest_custody_friday(date(2026, 8, 30)) == date(2026, 8, 28)
    assert _latest_custody_friday(date(2026, 8, 31)) == date(2026, 8, 28)
    assert _latest_custody_friday(date(2026, 9, 3)) == date(2026, 8, 28)
    assert _latest_custody_friday(date(2026, 9, 4)) == date(2026, 9, 4)


def test_director_floor_survives_and_stops_asking_for_months_that_never_existed():
    root = _archive(_tmp())
    assert own.director_floor(root, "6547") is None

    own.save_director_floor(root, "6547", "11203")
    assert own.director_floor(root, "6547") == "11203"

    own.save_director_floor(root, "6547", "11208")
    assert own.director_floor(root, "6547") == "11203"
    own.save_director_floor(root, "6547", "11101")
    assert own.director_floor(root, "6547") == "11101"

    assert own.director_history(root, "6547") == {}


def test_stock_workflow_commits_the_directors_backfill_it_paid_for():
    text = (ROOT.parent / ".github" / "workflows" / "stock.yml").read_text("utf-8")
    line = next(ln for ln in text.splitlines() if "git add -A --" in ln and "data/sheets/$code" in ln)
    assert "data/ownership" in line


def test_stock_workflow_commits_the_rating_it_just_recomputed():
    text = (ROOT.parent / ".github" / "workflows" / "stock.yml").read_text("utf-8")
    add = text[text.index("git add "):text.index("if git diff --cached --quiet")]
    assert "data/ratings.csv" in add, "commit 那一步沒有 add data/ratings.csv"
    assert "git diff --name-only" in text, "漏了「還有什麼沒被 commit」的自白"


def _assert_tracked(path: Path) -> None:
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
    wf = ROOT.parent / ".github" / "workflows"
    for name in ("stock.yml", "ownership.yml"):
        text = (wf / name).read_text("utf-8")
        live = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        assert not any("workflows/pages.yml" in ln for ln in live), name
        assert "uses: ./.github/actions/build-site" in text, name
        assert "deploy-pages@v4" in text, name
        after = text.split("\njobs:\n", 1)[1]
        jobs = [
            ln.strip().rstrip(":")
            for ln in after.splitlines()
            if ln.startswith("  ") and not ln.startswith("   ") and ln.rstrip().endswith(":")
        ]
        assert jobs == ["fetch"], f"{name} 還有第二個 job：{jobs}"
    action = wf.parent / "actions" / "build-site" / "action.yml"
    assert action.exists()
    _assert_tracked(action)


def test_ci_installs_only_what_the_site_actually_imports():
    action = (ROOT.parent / ".github" / "actions" / "build-site" / "action.yml").read_text("utf-8")
    assert 'pip install -e ".[report]"' in action
    assert 'pip install -e ".[all]"' not in action


def test_the_stock_workflow_runs_the_suite_alongside_the_fetch_not_before_it():
    text = (ROOT.parent / ".github" / "workflows" / "stock.yml").read_text("utf-8")
    live = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(live)
    assert "run_tests.py > /tmp/tests.log 2>&1 &" in body, "測試沒有丟到背景"
    assert 'wait "$tests"' in body, "沒有等測試結束就往下走了"
    assert '不 commit 這次抓到的資料' in body
    order = body.index("run_tests.py"), body.index("twsix report"), body.index("git commit")
    assert order[0] < order[1] < order[2]


def test_the_backfill_guard_needs_a_full_year_not_just_a_current_week():
    import inspect

    from twsix import cli

    src = inspect.getsource(cli._backfill_holders)
    assert "len(have) >= BACKFILL_WEEKS" in src
    assert "max(have) >= newest" in src


def test_a_scattered_failure_does_not_abandon_the_rest_of_the_year():
    import inspect

    from twsix import cli

    src = inspect.getsource(cli._backfill_holders)
    assert "streak" in src and "streak >= 6" in src
    assert src.count("_save_weeks") >= 2
    assert "再試一次" in src


def test_a_corporate_director_holding_several_seats_is_counted_once():
    company = _insiders()["1216"]

    seats = [p for p in company.people if p.name == "高權投資股份有限公司"]
    assert len(seats) == 3, "fixture 應該保留那三席"
    assert {p.held for p in seats} == {284_330_536}, "三列寫的是同一塊持股"

    assert round(company.held / 1000) == 561_796
    assert round(company.pledged / 1000) == 80_030
    assert company.independent_held == 0


def test_two_directors_with_different_names_both_count():
    company = _insiders()["1216"]
    names = {p.name for p in company.people if ins.is_director(p.title)}
    assert "侯博裕" in names and "林蒼生" in names
    only = sum(
        p.held for p in company.people
        if ins.is_director(p.title) and p.name in ("侯博裕", "林蒼生")
    )
    assert only == 141_697_024 + 49_916_266
    assert company.held > only


def test_a_half_market_directors_fetch_does_not_shrink_the_month():
    root = _tmp() / "ownership"
    full = _insiders()
    path = own.save_directors(root, full)
    before = own._read(path)
    half = dict(list(sorted(full.items()))[: len(full) // 2])
    own.save_directors(root, half)
    after = own._read(path)
    assert len(after) == len(before) == len(full)
    assert after == before
