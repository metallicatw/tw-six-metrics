#!/usr/bin/env python3
"""Turn the v6.62 workbook into the project's regression fixtures.

Two outputs land in ``tests/golden/``:

* ``ratings.csv``   — one row per (stock, period) from the 〔評等清單〕 sheet:
  the six indicator scores, the composite, and the value-pick flag that
  Excel itself computed.  1,741 stocks x 9 periods.
* ``5439/``          — every raw statement row the workbook holds for the
  single stock it was last saved on, so the end-to-end test has real input.

Run:  python scripts/extract_golden.py path/to/workbook.xlsm
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from twsix.xlsx.extract import Workbook, index_to_col  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden"

# 〔評等清單〕layout.  The workbook's own VBA walks the indicator columns with
#   For c = 10 To 146 Step 17
# so there are 9 period groups, each 17 columns wide, starting at column H(8).
GROUP_COUNT = 9
GROUP_WIDTH = 17
GROUP0_START = 8  # column H

# offsets within a group
OFF_QUARTER = 0  # 財報季度
OFF_MONTH = 1  # 營收月份
OFF_INDICATORS = 2  # 營收年增率 .. 自由現金流量 (6 columns)
OFF_COMPOSITE = 8  # 本期綜合評分
OFF_DELTA = 9  # 綜合評分變化
OFF_VALUE_PICK = 10  # 具價值投資

INDICATORS = [
    "revenue_yoy",
    "operating_margin",
    "net_income_yoy",
    "eps",
    "inventory_turnover",
    "free_cash_flow",
]

# 〔評價簡表〕/〔六大財務指標評等〕 source sheets worth freezing for the
# single-stock end-to-end test.
DETAIL_SHEETS = [
    "六大財務指標評等",
    "評價簡表",
    "FRQ",
    "ISQ",
    "BSQ",
    "CFQ",
    "EPQ",
    "OPQ",
    "BASIC",
    "BASIC2",
    "營收",
    "股利",
    "年度交易資訊(上市櫃合併)",
    # The valuation sheets.  Without these the four valuation models have no
    # Excel answer to diff against, which is why their outputs were only ever
    # "input-verified" — the target price and the 便宜/合理/昂貴 prices could
    # not be reconciled.  Capturing them promotes those tests to real
    # cell-for-cell reconciliation.
    "EPS預估與估價",
    "殖利率估價",
    "河流圖",
    "財務指標評等預估",
]


#: The fixtures and the live workbook reader must render cells identically —
#: when they drifted, the reader saw "114.0" where the fixtures said "114" and
#: a whole valuation model silently went dark.  One definition, imported.
from twsix.ingest.valuation_source import cell_text as _clean  # noqa: E402


def extract_ratings(wb: Workbook) -> list[dict[str, str]]:
    cells = wb.cached_values("評等清單", min_row=5)
    rows_present = sorted({r for (r, _c) in cells})
    out: list[dict[str, str]] = []

    for r in rows_present:
        stock_id = _clean(cells.get((r, 1)))
        if not stock_id:
            continue
        # column A holds a numeric code; normalise 1101.0 -> "1101"
        base = {
            "stock_id": stock_id,
            "name": _clean(cells.get((r, 2))),
            "listed_date": _clean(cells.get((r, 3))),
            "market": _clean(cells.get((r, 4))),
            "industry": _clean(cells.get((r, 5))),
            "capital_e8": _clean(cells.get((r, 6))),
            "market_cap_e8": _clean(cells.get((r, 7))),
        }
        for k in range(GROUP_COUNT):
            start = GROUP0_START + k * GROUP_WIDTH
            rec = dict(base)
            rec["period_index"] = str(k + 1)
            rec["fiscal_quarter"] = _clean(cells.get((r, start + OFF_QUARTER)))
            rec["revenue_month"] = _clean(cells.get((r, start + OFF_MONTH)))
            for i, name in enumerate(INDICATORS):
                rec[name] = _clean(cells.get((r, start + OFF_INDICATORS + i)))
            rec["composite"] = _clean(cells.get((r, start + OFF_COMPOSITE)))
            rec["composite_delta"] = _clean(cells.get((r, start + OFF_DELTA)))
            rec["value_pick"] = _clean(cells.get((r, start + OFF_VALUE_PICK)))
            if not rec["fiscal_quarter"] and not rec["composite"]:
                continue
            out.append(rec)
    return out


def extract_detail(wb: Workbook, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name in DETAIL_SHEETS:
        try:
            cells = wb.cached_values(name)
        except KeyError:
            continue
        grid: dict[str, dict[str, str]] = {}
        for (r, c), v in cells.items():
            grid.setdefault(str(r), {})[index_to_col(c)] = _clean(v)
        safe = name.replace("/", "_").replace("(", "_").replace(")", "_")
        (out_dir / f"{safe}.json").write_text(
            json.dumps(grid, ensure_ascii=False, indent=0, sort_keys=True),
            encoding="utf-8",
        )
        counts[name] = len(cells)
    return counts


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    GOLDEN.mkdir(parents=True, exist_ok=True)

    with Workbook(src) as wb:
        print(f"workbook: {src.name}  ({len(wb.sheets)} sheets)")

        ratings = extract_ratings(wb)
        fields = [
            "stock_id",
            "name",
            "listed_date",
            "market",
            "industry",
            "capital_e8",
            "market_cap_e8",
            "period_index",
            "fiscal_quarter",
            "revenue_month",
            *INDICATORS,
            "composite",
            "composite_delta",
            "value_pick",
        ]
        target = GOLDEN / "ratings.csv"
        with target.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(ratings)
        stocks = len({r["stock_id"] for r in ratings})
        print(f"  ratings.csv     {len(ratings):>6} rows / {stocks} stocks")

        stock_id = _clean(wb.cached_values("評價簡表", 1, 1).get((1, 2))) or "detail"
        counts = extract_detail(wb, GOLDEN / stock_id)
        print(f"  {stock_id}/           {len(counts)} sheets")
        for k, v in counts.items():
            print(f"      {k:<24} {v:>6} cells")

        meta = {
            "source_file": src.name,
            "sheet_count": len(wb.sheets),
            "rating_rows": len(ratings),
            "stock_count": stocks,
            "detail_stock": stock_id,
            "detail_sheets": counts,
        }
        (GOLDEN / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
