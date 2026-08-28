"""Where fetched data lands, and how it gets into version control.

CSV, not Parquet.  A binary column store would be faster to query, but this
repository's data files exist to be *reviewed*: when a scheduled run changes
1,700 ratings, the diff is the audit trail, and a diff you cannot read is not
an audit trail.  The files are small enough that speed never becomes the
constraint (the full rating table is under 2 MB).

Every write is deterministic — sorted rows, fixed column order, ``\\n`` line
endings — so an unchanged fetch produces a byte-identical file and no commit.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1


@dataclass
class Manifest:
    """What a data directory contains and where it came from."""

    schema_version: int = SCHEMA_VERSION
    generated_at: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def stamp(self) -> None:
        self.generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """A directory of CSV tables plus a manifest."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- tables -----------------------------------------------------------

    def path(self, table: str) -> Path:
        return self.root / f"{table}.csv"

    def write(
        self,
        table: str,
        rows: Iterable[dict[str, Any]],
        columns: Sequence[str],
        *,
        sort_by: Sequence[str] | None = None,
    ) -> int:
        materialised = [{c: _fmt(r.get(c)) for c in columns} for r in rows]
        if sort_by:
            materialised.sort(key=lambda r: tuple(str(r.get(c, "")) for c in sort_by))
        target = self.path(table)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns), lineterminator="\n")
            writer.writeheader()
            writer.writerows(materialised)
        return len(materialised)

    def read(self, table: str) -> list[dict[str, str]]:
        target = self.path(table)
        if not target.exists():
            return []
        with target.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def exists(self, table: str) -> bool:
        return self.path(table).exists()

    # -- json blobs -------------------------------------------------------

    def write_json(self, name: str, payload: Any) -> Path:
        target = self.root / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.root / f"{name}.json"
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))

    # -- manifest ---------------------------------------------------------

    def load_manifest(self) -> Manifest:
        raw = self.read_json("manifest")
        if not raw:
            return Manifest()
        return Manifest(**raw)

    def save_manifest(self, manifest: Manifest) -> None:
        manifest.stamp()
        self.write_json("manifest", asdict(manifest))


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value != value:  # NaN
            return ""
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


# -- the rating table ------------------------------------------------------

RATING_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "name",
    "market",
    "industry",
    "period_index",
    "fiscal_quarter",
    "revenue_month",
    "revenue_yoy",
    "operating_margin",
    "net_income_yoy",
    "eps",
    "inventory_turnover",
    "free_cash_flow",
    "composite",
    "composite_delta",
    "value_pick",
    "revenue_yoy_grade",
    "operating_margin_grade",
    "net_income_yoy_grade",
    "eps_grade",
    "inventory_turnover_grade",
    "free_cash_flow_grade",
    "revenue_yoy_values",
    "operating_margin_values",
    "net_income_yoy_values",
    "eps_values",
    "inventory_turnover_values",
    "free_cash_flow_values",
    "revenue_yoy_reason",
    "operating_margin_reason",
    "net_income_yoy_reason",
    "eps_reason",
    "inventory_turnover_reason",
    "free_cash_flow_reason",
)


def rating_rows(rating: Any) -> list[dict[str, Any]]:
    """Flatten a :class:`~twsix.models.StockRating` into storable rows."""
    from ..models import INDICATOR_ORDER  # local import keeps store dependency-free

    picks = rating.value_picks()
    out: list[dict[str, Any]] = []
    for i, snap in enumerate(rating.snapshots):
        prev = rating.snapshots[i + 1] if i + 1 < len(rating.snapshots) else None
        cur_c, prev_c = snap.composite, (prev.composite if prev else None)
        row: dict[str, Any] = {
            "stock_id": rating.stock_id,
            "name": rating.name,
            "market": rating.market,
            "industry": rating.industry,
            "period_index": i + 1,
            "fiscal_quarter": snap.fiscal_quarter,
            "revenue_month": snap.revenue_month,
            "composite": snap.composite_display,
            "composite_delta": (
                None if cur_c is None or prev_c is None else cur_c - prev_c
            ),
            "value_pick": picks[i],
        }
        for key in INDICATOR_ORDER:
            result = snap.indicators[key]
            row[key] = result.display
            row[f"{key}_grade"] = result.letter
            row[f"{key}_values"] = " / ".join(
                "—" if v is None else f"{v:g}" for v in result.values
            )
            row[f"{key}_reason"] = result.reason
        out.append(row)
    return out
