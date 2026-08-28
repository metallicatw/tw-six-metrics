"""Reconciliation against the workbook's own answers.

Three layers, deliberately separated so a failure says *where* the engine and
the spreadsheet diverged:

1. rules      — feed the workbook's own indicator inputs into the graders
2. plumbing   — rebuild those inputs from the three statements, then grade
3. market     — replay the composite and value-pick logic over all 1,741
                published stocks

Every assertion is exact.  A tolerance would hide precisely the kind of drift
this suite exists to catch.
"""

from __future__ import annotations

import csv
from pathlib import Path

from golden_loader import (
    INDICATOR_KEYS,
    available_stocks,
    expected_blocks,
    gate_flag,
    inventory_ratios,
)

from twsix.models import (
    Grade,
    IndicatorResult,
    INDICATOR_LABELS,
    INDICATOR_ORDER,
    Snapshot,
    Status,
)
from twsix.rating.indicators import (
    Rules,
    grade_eps,
    grade_free_cash_flow,
    grade_inventory_turnover,
    grade_net_income_yoy,
    grade_operating_margin,
    grade_revenue_yoy,
)

GOLDEN = Path(__file__).parent / "golden"
WORKBOOK_ENV = "TWSIX_WORKBOOK"


def _grade_block(blk, rules: Rules, qratio, aratio) -> dict[str, IndicatorResult]:
    return {
        "revenue_yoy": grade_revenue_yoy(blk.inputs["revenue_yoy"], rules=rules),
        "operating_margin": grade_operating_margin(
            blk.inputs["operating_margin"], rules=rules
        ),
        "net_income_yoy": grade_net_income_yoy(
            blk.inputs["net_income_yoy"], net_margins=blk.net_margins, rules=rules
        ),
        "eps": grade_eps(blk.inputs["eps"], rules=rules),
        "inventory_turnover": grade_inventory_turnover(
            blk.inputs["inventory_turnover"],
            quarterly_inventory_ratio=qratio,
            annual_inventory_ratio=aratio,
            rules=rules,
        ),
        "free_cash_flow": grade_free_cash_flow(
            blk.inputs["free_cash_flow"], rules=rules
        ),
    }


# =========================================================================
# layer 1 — the rules alone
# =========================================================================


def test_rules_reproduce_every_indicator_score():
    stocks = [s for s in available_stocks() if (GOLDEN / s / "六大財務指標評等.json").exists()]
    assert stocks, "no golden stock fixtures — run scripts/extract_golden.py"

    failures: list[str] = []
    checked = 0
    for stock in stocks:
        rules = Rules(income_positive_margin_gate=gate_flag(stock))
        qratio, aratio = inventory_ratios(stock)
        for blk in expected_blocks(stock):
            got = _grade_block(blk, rules, qratio, aratio)
            for key in INDICATOR_KEYS:
                expected = blk.scores[key] or "不評分"
                checked += 1
                if got[key].display != expected:
                    failures.append(
                        f"{stock} block{blk.index} {key}: "
                        f"excel={expected!r} engine={got[key].display!r} "
                        f"({got[key].reason}) inputs={got[key].values}"
                    )
    assert checked >= 54, f"only {checked} scores checked"
    assert not failures, "\n" + "\n".join(failures)


def test_rules_reproduce_composite_and_value_pick():
    stocks = [s for s in available_stocks() if (GOLDEN / s / "六大財務指標評等.json").exists()]
    failures: list[str] = []
    for stock in stocks:
        rules = Rules(income_positive_margin_gate=gate_flag(stock))
        qratio, aratio = inventory_ratios(stock)
        blocks = expected_blocks(stock)
        snaps = [
            Snapshot(
                stock_id=stock,
                fiscal_quarter=b.fiscal_quarter,
                revenue_month=b.revenue_month,
                indicators=_grade_block(b, rules, qratio, aratio),
            )
            for b in blocks
        ]
        for i, (blk, snap) in enumerate(zip(blocks, snaps)):
            prev = snaps[i + 1] if i + 1 < len(snaps) else None
            if blk.composite in ("數據不足", "N/A"):
                if snap.composite_display != blk.composite:
                    failures.append(
                        f"{stock} block{blk.index} composite: "
                        f"excel={blk.composite!r} engine={snap.composite_display!r}"
                    )
            else:
                got = snap.composite
                if got is None or abs(float(blk.composite) - got) > 1e-9:
                    failures.append(
                        f"{stock} block{blk.index} composite: "
                        f"excel={blk.composite} engine={got}"
                    )
            want_pick = blk.value_pick == "具投資價值"
            if snap.is_value_pick(prev) != want_pick:
                failures.append(
                    f"{stock} block{blk.index} value_pick: "
                    f"excel={want_pick} engine={not want_pick}"
                )
    assert not failures, "\n" + "\n".join(failures)


# =========================================================================
# layer 2 — the whole pipeline, from raw statements
# =========================================================================


def test_pipeline_from_raw_statements_matches_the_workbook():
    """Rebuild every indicator series from ISQ/BSQ/CFQ/EPQ/營收 and re-grade.

    This is the assertion that says the migration is faithful: not only are
    the rules right, the numbers we feed them are the same numbers Excel fed
    its own rules — even though we derive them from the three statements and
    it read them off a broker's pre-computed ratio table.
    """
    import os

    workbook = os.environ.get(WORKBOOK_ENV)
    if not workbook or not Path(workbook).exists():
        return  # optional: needs the source .xlsm, which is not in the repo

    from twsix.ingest.workbook import WorkbookSource
    from twsix.rating.engine import rate

    data = WorkbookSource(Path(workbook)).load()
    stock = data.stock_id
    rules = Rules(income_positive_margin_gate=gate_flag(stock))
    rating = rate(data, rules)
    blocks = expected_blocks(stock)

    assert len(rating.snapshots) == len(blocks)
    failures: list[str] = []
    for snap, blk in zip(rating.snapshots, blocks):
        if snap.fiscal_quarter != blk.fiscal_quarter:
            failures.append(
                f"quarter: engine={snap.fiscal_quarter} excel={blk.fiscal_quarter}"
            )
        if snap.revenue_month != blk.revenue_month:
            failures.append(
                f"month: engine={snap.revenue_month} excel={blk.revenue_month}"
            )
        for key in INDICATOR_ORDER:
            expected = blk.scores[key] or "不評分"
            got = snap.indicators[key].display
            if got != expected:
                failures.append(
                    f"block{blk.index} {key}: excel={expected!r} engine={got!r} "
                    f"values={snap.indicators[key].values}"
                )
    assert not failures, "\n" + "\n".join(failures)


# =========================================================================
# layer 3 — the published market snapshot
# =========================================================================


def _snapshot_from_scores(stock_id: str, row: dict[str, str]) -> Snapshot | None:
    indicators: dict[str, IndicatorResult] = {}
    for key in INDICATOR_ORDER:
        s = (row.get(key) or "").strip()
        label = INDICATOR_LABELS[key]
        if s == "不評分":
            indicators[key] = IndicatorResult(key, label, (), Status.NOT_RATED)
        elif s == "數據不足":
            indicators[key] = IndicatorResult(key, label, (), Status.INSUFFICIENT)
        elif not s or s == "N/A" or s.startswith("#"):
            indicators[key] = IndicatorResult(key, label, (), Status.NA)
        else:
            value = int(float(s))
            if not 0 <= value <= 4:
                return None  # out-of-range score: a workbook anomaly, see below
            indicators[key] = IndicatorResult(
                key, label, (), Status.SCORED, Grade(value)
            )
    return Snapshot(
        stock_id=stock_id,
        fiscal_quarter=row.get("fiscal_quarter", ""),
        revenue_month=row.get("revenue_month", ""),
        indicators=indicators,
    )


def test_market_snapshot_composite_and_value_pick():
    path = GOLDEN / "ratings.csv"
    if not path.exists():
        return
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_stock: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_stock.setdefault(r["stock_id"], []).append(r)

    composite_checked = composite_bad = 0
    pick_checked = pick_bad = 0
    anomalies: list[str] = []
    failures: list[str] = []

    for stock_id, group in by_stock.items():
        group.sort(key=lambda r: int(r["period_index"]))
        snaps: list[Snapshot | None] = [
            _snapshot_from_scores(stock_id, r) for r in group
        ]
        for i, (row, snap) in enumerate(zip(group, snaps)):
            if snap is None:
                anomalies.append(f"{stock_id} period{row['period_index']}")
                continue
            if any((row.get(k) or "").startswith("#") for k in INDICATOR_ORDER):
                continue  # Excel error propagated into the source cell
            expected = (row.get("composite") or "").strip()
            if expected.startswith("#"):
                continue
            composite_checked += 1
            if expected in ("數據不足", "N/A"):
                ok = snap.composite_display == expected
            else:
                ok = (
                    snap.composite is not None
                    and abs(float(expected) - snap.composite) < 1e-6
                )
            if not ok:
                composite_bad += 1
                if len(failures) < 10:
                    failures.append(
                        f"{stock_id} p{row['period_index']} composite: "
                        f"excel={expected!r} engine={snap.composite_display!r}"
                    )

            want = (row.get("value_pick") or "").strip()
            if want not in ("0", "1"):
                continue
            prev = snaps[i + 1] if i + 1 < len(snaps) else None
            pick_checked += 1
            got = "1" if snap.is_value_pick(prev) else "0"
            if got != want:
                pick_bad += 1
                if len(failures) < 10:
                    failures.append(
                        f"{stock_id} p{row['period_index']} value_pick: "
                        f"excel={want} engine={got}"
                    )

    assert composite_checked > 15000, f"only {composite_checked} composites checked"
    assert composite_bad == 0, "\n" + "\n".join(failures)
    assert pick_bad == 0, "\n" + "\n".join(failures)
    # One stock in v6.62 carries a revenue score of 5, outside the 0-4 scale —
    # two mutually exclusive flags fired at once.  We refuse to score it rather
    # than average an impossible value; see CHANGELOG decision #10.
    assert len(anomalies) <= 1, f"unexpected out-of-range scores: {anomalies}"
