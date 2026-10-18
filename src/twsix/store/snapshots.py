
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def atomic_write(target: Path, payload: bytes) -> Path:
    import os

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp{os.getpid()}")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return target


@dataclass
class Manifest:

    schema_version: int = SCHEMA_VERSION
    generated_at: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def stamp(self) -> None:
        self.generated_at = datetime.now(UTC).isoformat(timespec="seconds")


class Store:

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)


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
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialised)
        atomic_write(self.path(table), text.getvalue().encode("utf-8"))
        return len(materialised)

    def write_gz(
        self,
        table: str,
        rows: Iterable[dict[str, Any]],
        columns: Sequence[str],
        *,
        sort_by: Sequence[str] | None = None,
    ) -> int:
        import gzip
        import io

        materialised = [{c: _fmt(r.get(c)) for c in columns} for r in rows]
        if sort_by:
            materialised.sort(key=lambda r: tuple(str(r.get(c, "")) for c in sort_by))
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(materialised)
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as fh:
            fh.write(text.getvalue().encode("utf-8"))
        atomic_write(self.root / f"{table}.csv.gz", buf.getvalue())
        return len(materialised)

    def read_gz(self, table: str) -> list[dict[str, str]]:
        import gzip
        import io

        target = self.root / f"{table}.csv.gz"
        if not target.exists():
            return []
        text = gzip.decompress(target.read_bytes()).decode("utf-8")
        return list(csv.DictReader(io.StringIO(text)))

    def read(self, table: str) -> list[dict[str, str]]:
        target = self.path(table)
        if not target.exists():
            return []
        with target.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def exists(self, table: str) -> bool:
        return self.path(table).exists()

    def upsert(
        self,
        table: str,
        key_field: str,
        key: str,
        rows: Iterable[dict[str, Any]],
        columns: Sequence[str],
        *,
        sort_by: Sequence[str] | None = None,
    ) -> int:
        fresh = list(rows)
        kept = [r for r in self.read(table) if r.get(key_field) != key]
        self.write(table, kept + fresh, columns, sort_by=sort_by)
        return len(fresh)


    def write_json(self, name: str, payload: Any) -> Path:
        return atomic_write(
            self.root / f"{name}.json",
            (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )

    def read_json(self, name: str, default: Any = None) -> Any:
        target = self.root / f"{name}.json"
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))


    def load_manifest(self) -> Manifest:
        raw = self.read_json("manifest")
        if not raw:
            return Manifest()
        return Manifest(**raw)

    def save_manifest(self, manifest: Manifest) -> None:
        fresh = self._normalised(manifest)
        old = self.read_json("manifest") or {}
        if {k: v for k, v in old.items() if k != "generated_at"} == {
            k: v for k, v in fresh.items() if k != "generated_at"
        }:
            return
        manifest.stamp()
        fresh["generated_at"] = manifest.generated_at
        self.write_json("manifest", fresh)

    @staticmethod
    def _normalised(manifest: Manifest) -> dict[str, Any]:
        data = asdict(manifest)
        data["sources"] = sorted(
            data.get("sources") or [], key=lambda s: str(s.get("name", ""))
        )
        return data


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value != value:
            return ""
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)



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


def vintage(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("fiscal_quarter") or "", row.get("revenue_month") or "")


def rating_rows(rating: Any) -> list[dict[str, Any]]:
    from ..models import INDICATOR_ORDER

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



VALUATION_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "name",
    "as_of",
    "revenue_month",
    "market_price",
    "growth_rate",
    "trailing_eps",
    "forecast_eps",
    "forecast_margin",
    "forecast_revenue",
    "pe_high",
    "pe_low",
    "target_price",
    "downside_price",
    "expected_return",
    "expected_risk",
    "reward_risk",
    "risk_free",
    "forward_pe",
    "eps_growth",
    "peg",
    "total_return",
    "dividend",
    "payout_ratio",
    "cheap_price",
    "fair_price",
    "expensive_price",
    "current_yield",
    "verdict",
    "gaps",
)


def valuation_row(v: Any) -> dict[str, Any]:
    f, p, g, y = v.forecast, v.pe_view, v.growth_view, v.yield_view
    return {
        "stock_id": v.stock_id,
        "name": v.name,
        "as_of": v.as_of,
        "revenue_month": f.revenue_month if f else "",
        "market_price": v.market_price,
        "growth_rate": v.growth_rate,
        "trailing_eps": v.trailing_eps,
        "forecast_eps": f.eps if f else None,
        "forecast_margin": f.net_margin if f else None,
        "forecast_revenue": f.projected_revenue if f else None,
        "pe_high": v.band.high if v.band else None,
        "pe_low": v.band.low if v.band else None,
        "target_price": p.target_price if p else None,
        "downside_price": p.downside_price if p else None,
        "expected_return": p.expected_return if p else None,
        "expected_risk": p.expected_risk if p else None,
        "reward_risk": p.reward_risk if p else None,
        "risk_free": 1 if (p is not None and p.risk_free) else 0,
        "forward_pe": g.forward_pe if g else None,
        "eps_growth": g.eps_growth if g else None,
        "peg": g.peg if g else None,
        "total_return": g.total_return if g else None,
        "dividend": y.dividend if y else None,
        "payout_ratio": y.payout_ratio if y else None,
        "cheap_price": y.cheap if y else None,
        "fair_price": y.fair if y else None,
        "expensive_price": y.expensive if y else None,
        "current_yield": y.current_yield if y else None,
        "verdict": v.verdict,
        "gaps": ";".join(f"{k}={t}" for k, t in sorted((v.gaps or {}).items())),
    }
