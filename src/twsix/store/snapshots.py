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
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def atomic_write(target: Path, payload: bytes) -> Path:
    """先寫暫存檔，再用 `os.replace` 換上去。

    為什麼不能直接開檔寫：**有人正在讀**。「加一檔個股」那條 workflow 刻意讓測試
    和抓取平行跑（省下二十幾秒的開機時間），而測試會讀 `data/ratings.csv` 當樣本；
    抓取寫到一半的那一瞬間，讀到的是半份檔案，於是測試以
    「UnicodeDecodeError: unexpected end of data」失敗——訊息裡完全看不出是誰在寫。

    `os.replace` 是同一個檔案系統上的原子操作：讀到的不是舊的就是新的，沒有中間
    狀態。同樣的保護也適用於 runner 被砍在寫入中途——那時留在 repo 裡的會是完整的
    舊檔，而不是一份截斷的資料。
    """
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
    """What a data directory contains and where it came from."""

    schema_version: int = SCHEMA_VERSION
    generated_at: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def stamp(self) -> None:
        self.generated_at = datetime.now(UTC).isoformat(timespec="seconds")


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
        """壓縮存的表——給**寫下去就不再改**的資料用（例如每天一個檔的收盤行情）。

        一天約 2,000 列、100 KB，一年 250 個交易日。壓縮之後每天約 25 KB，一年
        6 MB。這種檔案 diff 不需要讀懂：它不會被改寫，只會多一個——「這一天的資
        料」本身就是一整個 commit 的內容。反而是評等表那種**會被改寫**的，diff
        就是稽核軌跡，所以那些留在未壓縮的 CSV。

        gzip 固定 mtime=0：同樣的內容寫兩次得到同一個檔案，所以排程一天跑兩次
        （早收盤一次、晚上補一次）不會製造出第二個 commit。
        """
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
        """Replace every row whose ``key_field`` is ``key``, keep the rest.

        The whole-market table is one snapshot of 1,741 stocks taken from the
        workbook, and it cannot be re-taken — but a single stock *can* be
        re-fetched, and when it is, its row in that table is the one thing on
        the site still showing last year's answer.  This is the seam: one
        stock's rows are replaced, everyone else's are copied through
        untouched, so the table becomes 「1,740 檔是舊的、這一檔是新的」 rather
        than all-or-nothing.

        Returns the number of rows written for ``key`` (0 means the stock was
        removed, which no caller currently wants).
        """
        fresh = list(rows)
        kept = [r for r in self.read(table) if r.get(key_field) != key]
        self.write(table, kept + fresh, columns, sort_by=sort_by)
        return len(fresh)

    # -- json blobs -------------------------------------------------------

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

    # -- manifest ---------------------------------------------------------

    def load_manifest(self) -> Manifest:
        raw = self.read_json("manifest")
        if not raw:
            return Manifest()
        return Manifest(**raw)

    def save_manifest(self, manifest: Manifest) -> None:
        """只有在描述真的變了的時候才重寫，時間戳也才跟著換。

        這個檔案每天被排程寫一次。如果每次都蓋上「現在幾點」，那麼即使整批資料
        一個位元組都沒變，manifest 自己也會製造出一個 commit——一年 365 個只有
        時間戳在動的雜訊 commit，而且會讓「這次抓取有沒有拿到新東西」這件事，
        從 git 歷史上再也讀不出來。

        時間戳的意思因此收窄成一句更有用的話：**這份描述是什麼時候開始成立的**，
        不是「最後一次確認它還成立是什麼時候」。後者 git 已經記著了。

        ``sources`` 寫出去之前先照名稱排序。它是一個「每張表一筆」的集合，不是
        一份有順序的紀錄，但它存成 list——而呼叫端是逐張表抓、抓到就把那一筆移到
        尾巴，所以**清單的順序會跟著抓取順序跑**。第一次排程就踩到了：內容一個
        字都沒變，八筆的順序從字母序變成抓取序，於是 diff 有 20 行進 20 行出，
        照樣 commit 了一次。哪一張表這次失敗了也會讓順序不一樣。

        排過序之後，「這份描述有沒有變」問的才是內容。
        """
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
        """寫出去的樣子——順序不受抓取順序影響。"""
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


# -- the valuation table ---------------------------------------------------

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
    """Flatten a :class:`~twsix.valuation.StockValuation` into one storable row."""
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
        # "缺股價;無預估EPS" — kept so a blank section on the page can explain itself
        "gaps": ";".join(f"{k}={t}" for k, t in sorted((v.gaps or {}).items())),
    }
