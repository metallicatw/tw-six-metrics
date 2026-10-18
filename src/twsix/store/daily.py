
from __future__ import annotations

import csv
import gzip
import io
import math
from dataclasses import dataclass
from pathlib import Path

LOOKBACK = 10


@dataclass(frozen=True)
class Quote:

    date: str
    close: float | None
    change: float | None = None
    volume: float | None = None

    @property
    def label(self) -> str:
        return self.date.replace("-", ".")


def _num(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _rows(path: Path) -> list[dict[str, str]]:
    try:
        text = gzip.decompress(path.read_bytes()).decode("utf-8")
    except (OSError, ValueError):
        return []
    return list(csv.DictReader(io.StringIO(text)))


def latest_quotes(data_dir: Path, *, lookback: int = LOOKBACK) -> dict[str, Quote]:
    folder = data_dir / "market" / "daily" / "prices"
    if not folder.is_dir():
        return {}
    out: dict[str, Quote] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            if not code or code in out:
                continue
            close = _num(row.get("close", ""))
            if close is None:
                continue
            out[code] = Quote(
                date=(row.get("date") or path.stem).strip(),
                close=close,
                change=_num(row.get("change", "")),
                volume=_num(row.get("volume", "")),
            )
    return out


INST_DAYS = 20

INST_LOOKBACK = 30


def close_history(
    data_dir: Path, *, lookback: int = INST_LOOKBACK, days: int = INST_DAYS
) -> dict[str, list[Quote]]:
    folder = data_dir / "market" / "daily" / "prices"
    if not folder.is_dir():
        return {}
    out: dict[str, list[Quote]] = {}
    seen: dict[str, set[str]] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            close = _num(row.get("close", ""))
            if not code or close is None:
                continue
            have = out.setdefault(code, [])
            got = seen.setdefault(code, set())
            date = (row.get("date") or path.stem).strip()
            if len(have) >= days or date in got:
                continue
            got.add(date)
            have.append(Quote(date=date, close=close))
    return out


@dataclass(frozen=True)
class InstDay:

    date: str
    foreign: float | None
    trust: float | None
    dealer: float | None
    total: float | None
    foreign_held: float | None = None
    foreign_pct: float | None = None
    issued_lots: float | None = None

    @property
    def roc_label(self) -> str:
        y, m, d = self.date.split("-")
        return f"{int(y) - 1911}/{m}/{d}"


def _lots(text: str) -> float | None:
    value = _num(text)
    if value is None:
        return None
    value /= 1000
    return float(math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5))


def institutional_history(
    data_dir: Path, *, lookback: int = INST_LOOKBACK, days: int = INST_DAYS
) -> dict[str, list[InstDay]]:
    folder = data_dir / "market" / "daily" / "institutional"
    if not folder.is_dir():
        return {}
    qfii = qfii_by_day(data_dir, lookback=lookback)
    out: dict[str, list[InstDay]] = {}
    seen: dict[str, set[str]] = {}
    inst_dates: set[str] = set()
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            date = (row.get("date") or "").strip()
            if not code or not date:
                continue
            inst_dates.add(date)
            have = out.setdefault(code, [])
            got = seen.setdefault(code, set())
            if len(have) >= days or date in got:
                continue
            got.add(date)
            foreign = _lots(row.get("foreign", ""))
            trust = _lots(row.get("trust", ""))
            dealer = _lots(row.get("dealer", ""))
            parts = [v for v in (foreign, trust, dealer) if v is not None]
            held, pct, issued = qfii.get((date, code), (None, None, None))
            have.append(
                InstDay(
                    date=date,
                    foreign=foreign,
                    trust=trust,
                    dealer=dealer,
                    total=sum(parts) if len(parts) == 3 else _lots(row.get("total", "")),
                    foreign_held=held,
                    foreign_pct=pct,
                    issued_lots=issued,
                )
            )
    for (date, code), (held, pct, issued) in qfii.items():
        if len(code) != 4 or date not in inst_dates or date in seen.get(code, ()):
            continue
        have = out.setdefault(code, [])
        seen.setdefault(code, set()).add(date)
        have.append(InstDay(date=date, foreign=0.0, trust=0.0, dealer=0.0, total=0.0,
                            foreign_held=held, foreign_pct=pct, issued_lots=issued))
    for have in out.values():
        have.sort(key=lambda d: d.date, reverse=True)
        del have[days:]
    return out


def qfii_by_day(
    data_dir: Path, *, lookback: int = INST_LOOKBACK
) -> dict[tuple[str, str], tuple[float | None, float | None, float | None]]:
    folder = data_dir / "market" / "daily" / "qfii"
    out: dict[tuple[str, str], tuple[float | None, float | None, float | None]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:lookback]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            date = (row.get("date") or "").strip()
            if not code or not date:
                continue
            pct = _num(row.get("pct", ""))
            issued = _num(row.get("issued", ""))
            out[(date, code)] = (_lots(row.get("held", "")), None if pct is None else pct / 100,
                                 None if issued is None else issued / 1000)
    return out


def foreign_daily(
    data_dir: Path, *, days: int = 760
) -> dict[str, dict[str, tuple[float | None, float | None]]]:
    root = data_dir / "market" / "daily"
    out: dict[str, dict[str, tuple[float | None, float | None]]] = {}
    inst = root / "institutional"
    keep = sorted(p.name[:10] for p in (root / "prices").glob("*.csv.gz"))[-days:] \
        if (root / "prices").is_dir() else []
    first = keep[0] if keep else ""
    if inst.is_dir():
        for path in sorted(inst.glob("*.csv.gz")):
            if path.name[:10] < first:
                continue
            for row in _rows(path):
                code = (row.get("code") or "").strip()
                day = (row.get("date") or path.name[:10]).strip()
                if code:
                    out.setdefault(code, {})[day] = (_lots(row.get("foreign", "")), None)
    q = root / "qfii"
    if q.is_dir():
        for path in sorted(q.glob("*.csv.gz")):
            if path.name[:10] < first:
                continue
            for row in _rows(path):
                code = (row.get("code") or "").strip()
                day = (row.get("date") or path.name[:10]).strip()
                pct = _num(row.get("pct", ""))
                if not code or pct is None:
                    continue
                slot = out.setdefault(code, {})
                net = slot.get(day, (None, None))[0]
                slot[day] = (0.0 if net is None and len(code) == 4 else net, pct)
    return out


def foreign_month_end(data_dir: Path) -> dict[str, dict[str, float]]:
    folder = data_dir / "market" / "daily" / "qfii"
    out: dict[str, dict[str, float]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.csv.gz")):
        month = path.name[:7].replace("-", "/")
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            pct = _num(row.get("pct", ""))
            if code and pct is not None:
                out.setdefault(code, {})[month] = round(pct, 2)
    return out


def read_day_rows(data_dir: Path, folder: str, day: str) -> list[dict[str, str]]:
    path = data_dir / "market" / "daily" / folder / f"{day}.csv.gz"
    return _rows(path) if path.exists() else []


def merge_day_rows(
    old: list[dict[str, str]], new: list[dict[str, str]]
) -> list[dict[str, str]]:
    merged: dict[str, dict] = {}
    for rows in (old, new):
        for r in rows:
            code = r.get("code") or ""
            if not code:
                continue
            slot = merged.setdefault(code, {})
            for k, v in r.items():
                if v is not None and v != "":
                    slot[k] = v
                else:
                    slot.setdefault(k, v)
    return list(merged.values())


COMPLETE_FIELDS = {
    "prices": ("close", "value"),
    "institutional": ("foreign", "trust", "dealer", "f_buy", "t_buy"),
    "qfii": ("held", "pct"),
}


def day_complete(rows: list[dict[str, str]], folder: str) -> bool:
    need = COMPLETE_FIELDS.get(folder, ())
    for market in ("上市", "上櫃"):
        if not any(
            (r.get("market") or "") == market
            and all(str(r.get(k) or "").strip() for k in need)
            for r in rows
        ):
            return False
    return True


HISTORY_DAYS = 760


def price_history(
    data_dir: Path, *, days: int = HISTORY_DAYS
) -> dict[str, tuple[list[str], list[float]]]:
    folder = data_dir / "market" / "daily" / "prices"
    if not folder.is_dir():
        return {}
    dates: dict[str, list[str]] = {}
    closes: dict[str, list[float]] = {}
    for path in sorted(folder.glob("*.csv.gz"), reverse=True)[:days]:
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            close = _num(row.get("close", ""))
            if not code or close is None or close <= 0:
                continue
            d = dates.setdefault(code, [])
            day = (row.get("date") or path.name[:10]).strip()
            if d and d[-1] == day:
                continue
            d.append(day)
            closes.setdefault(code, []).append(close)
    return {
        code: (list(reversed(d)), list(reversed(closes[code])))
        for code, d in dates.items()
    }



_WEEKLY_CACHE: dict[str, dict[str, list[tuple]]] = {}


def weekly_bars(data_dir: Path) -> dict[str, list[tuple[str, float, float, float, float, float]]]:
    key = str(Path(data_dir).resolve())
    if key in _WEEKLY_CACHE:
        return _WEEKLY_CACHE[key]
    from datetime import date as _date  # noqa: PLC0415

    folder = data_dir / "market" / "daily" / "prices"
    files = sorted(folder.glob("*.csv.gz")) if folder.is_dir() else []
    acc: dict[str, dict[tuple[int, int], list]] = {}
    labels: dict[tuple[int, int], str] = {}
    first_week = None
    for path in files:
        day = path.name[:10]
        try:
            y, m, d = (int(x) for x in day.split("-"))
            wk = _date(y, m, d).isocalendar()[:2]
        except ValueError:
            continue
        if first_week is None:
            first_week = wk
        if wk == first_week:
            continue
        label = labels.setdefault(wk, f"{y:04d}/{m:02d}/{d:02d}")
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            o, h, lo, c = (_num(row.get(k, "")) for k in ("open", "high", "low", "close"))
            v = _num(row.get("volume", "")) or 0.0
            if not code or c is None:
                continue
            slot = acc.setdefault(code, {}).get(wk)
            if slot is None:
                acc[code][wk] = [label, o if o is not None else c, h if h is not None else c,
                                 lo if lo is not None else c, c, v]
                continue
            slot[2] = max(slot[2], h if h is not None else c)
            slot[3] = min(slot[3], lo if lo is not None else c)
            slot[4] = c
            slot[5] += v
    out = {
        code: [(s[0], s[1], s[2], s[3], s[4], round(s[5] / 1000)) for _, s in sorted(weeks.items())]
        for code, weeks in acc.items()
    }
    _WEEKLY_CACHE[key] = out
    return out


_YEARLY_CACHE: dict[str, dict[str, dict[int, tuple[float, float, float]]]] = {}


def yearly_from_daily(data_dir: Path) -> dict[str, dict[int, tuple[float, float, float]]]:
    key = str(Path(data_dir).resolve())
    if key in _YEARLY_CACHE:
        return _YEARLY_CACHE[key]
    folder = data_dir / "market" / "daily" / "prices"
    files = sorted(folder.glob("*.csv.gz")) if folder.is_dir() else []
    acc: dict[str, dict[int, list[float]]] = {}
    first_year = int(files[0].name[:4]) if files else 0
    for path in files:
        year = int(path.name[:4])
        if year == first_year:
            continue
        for row in _rows(path):
            code = (row.get("code") or "").strip()
            c = _num(row.get("close", ""))
            if not code or c is None:
                continue
            h = _num(row.get("high", "")) or c
            lo = _num(row.get("low", "")) or c
            slot = acc.setdefault(code, {}).get(year)
            if slot is None:
                acc[code][year] = [h, lo, c, 1]
            else:
                slot[0] = max(slot[0], h)
                slot[1] = min(slot[1], lo)
                slot[2] += c
                slot[3] += 1
    out = {code: {y: (s[0], s[1], round(s[2] / s[3], 2)) for y, s in ys.items()}
           for code, ys in acc.items()}
    _YEARLY_CACHE[key] = out
    return out
