"""〔年度交易資訊(上市櫃合併)〕 — the one sheet that does not come from MoneyDJ.

The workbook fetches a stock's yearly trading summary from the two exchanges
(`Module1.MergeYTV_New` merges them) and the valuation reads three columns off
it: 最高價, 最低價, 收盤平均價 by 民國 year.  Those three are what the P/E band
is built from when 〔EPS預估與估價〕L2 is set to 自行計算 — the workbook's
default — and what the whole dividend-yield model needs.  Without this sheet a
fetched stock can still be forecast and priced off the published P/E, but
〔殖利率估價〕 abstains.

Both exchanges' responses are now fixtures — 5439 (上櫃) from 櫃買 and 2330
(上市) from 證交所, under ``tests/pages/``.  Having both mattered: they
disagree on three things, and each disagreement would have been invisible in a
parser written against only one.

* 櫃買 labels the price columns 「盤中最高價」/「盤中最低價」 and carries an
  extra 「加權平均價(B/A)」 in the position where 證交所 has 最高價 — so the
  columns are matched by name, not index.
* 櫃買 lists years newest-first, 證交所 oldest-first — so :func:`parse` sorts.
* 櫃買 includes the running year, 證交所 stops at the last completed one — so
  :func:`~twsix.ingest.valuation_source.yearly_prices` takes an anchor, without
  which every 上市 stock's series would sit one year off.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .base import FetchError, HttpClient

TWSE_YEARLY = "https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK"
TPEX_YEARLY = "https://www.tpex.org.tw/www/zh-tw/statistics/yearlyStock"

SHEET = "年度交易資訊_上市櫃合併_"

#: Where each field lands in the sheet, 0-based.  The workbook keeps the
#: exchange's own column order, and the valuation addresses E / G / I.
COL_YEAR = 0
COL_HIGH = 4
COL_LOW = 6
COL_AVG = 8
WIDTH = 9

ORIGIN = 3  # the body starts at sheet row 3

#: Field names as the exchanges label them.  Matched by 「含有」 rather than
#: equality, and that is not defensiveness: 櫃買 labels its columns
#: 「盤中最高價」/「盤中最低價」 where 證交所 says 「最高價」/「最低價」, and
#: 櫃買 carries an extra 「加權平均價(B/A)」 column that 證交所 does not have.
#: Matching by position would read the wrong column off one of the two.
FIELD_ALIASES: dict[int, tuple[str, ...]] = {
    COL_YEAR: ("年度",),
    COL_HIGH: ("最高價",),
    COL_LOW: ("最低價",),
    COL_AVG: ("收盤平均價", "平均收盤價", "收盤價平均"),
}


@dataclass(frozen=True)
class Year:
    """One year of trading, as the sheet holds it."""

    year: int  # 民國
    high: float | None
    low: float | None
    avg: float | None


class NotListedHere(FetchError):
    """The exchange answered, and said it has no such stock.

    5439 is 上櫃, so 證交所 returns a ``stat`` explaining there is no matching
    data rather than an error.  That is a normal half of every fetch — each
    stock is listed on exactly one of the two — so it must not read as a
    failure, or every single-stock fetch would report one.
    """


def _envelope(payload: Any) -> tuple[list[str], list[list[Any]]]:
    """Both exchanges answer with ``fields`` + ``data``; 櫃買 nests it in ``tables``.

    櫃買 returns two tables — the yearly history first, then a one-row
    「近年最高價／最低價」 summary whose column names would also match the
    aliases below.  Taking the first is deliberate.

    Returning the pair rather than a DataFrame-ish object keeps the mapping
    explicit: a renamed column is then a contract failure with a name in it,
    not a KeyError three functions away.
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("tables"), list) and payload["tables"]:
            return _envelope(payload["tables"][0])
        fields = payload.get("fields") or payload.get("Fields") or []
        data = payload.get("data") or payload.get("Data") or []
        if fields and isinstance(data, list):
            return [str(f) for f in fields], [list(r) for r in data]
        stat = str(payload.get("stat", "")).strip()
        if stat and stat.lower() != "ok":
            raise NotListedHere(stat)
    raise FetchError("回應格式無法辨識：找不到 fields / data")


def _column_map(fields: Sequence[str]) -> dict[int, int]:
    """Sheet column -> position in the response, matched by field name."""
    out: dict[int, int] = {}
    for sheet_col, names in FIELD_ALIASES.items():
        for i, field in enumerate(fields):
            text = str(field).strip()
            if any(name in text for name in names) and i not in out.values():
                out[sheet_col] = i
                break
    return out


def _number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text in {"--", "---", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse(payload: Any) -> list[Year]:
    """One exchange's response as a list of years, newest first."""
    fields, data = _envelope(payload)
    cols = _column_map(fields)
    missing = [
        FIELD_ALIASES[c][0] for c in (COL_YEAR, COL_HIGH, COL_LOW, COL_AVG)
        if c not in cols
    ]
    if missing:
        raise FetchError(
            "年度交易資訊缺少欄位：" + "、".join(missing)
            + f"　實際欄位為：{'、'.join(fields)}"
        )
    out: list[Year] = []
    for row in data:
        raw_year = _number(row[cols[COL_YEAR]]) if cols[COL_YEAR] < len(row) else None
        if raw_year is None:
            continue
        year = int(raw_year)
        if year > 1911:  # a Gregorian year slipped in; the sheet is 民國
            year -= 1911
        out.append(
            Year(
                year=year,
                high=_number(row[cols[COL_HIGH]]) if cols[COL_HIGH] < len(row) else None,
                low=_number(row[cols[COL_LOW]]) if cols[COL_LOW] < len(row) else None,
                avg=_number(row[cols[COL_AVG]]) if cols[COL_AVG] < len(row) else None,
            )
        )
    out.sort(key=lambda y: -y.year)
    return out


def merge(listed: Sequence[Year], otc: Sequence[Year]) -> list[Year]:
    """`Module1.MergeYTV_New` — one series from both exchanges.

    A stock that moved from 上櫃 to 上市 has its early years on one and its
    later years on the other, and the sheet is one continuous history.  Where
    both report a year, the listed figure wins; where only one does, that one
    is taken.
    """
    by_year: dict[int, Year] = {y.year: y for y in otc}
    by_year.update({y.year: y for y in listed})
    return sorted(by_year.values(), key=lambda y: -y.year)


#: 本益比區間的「5 年平均」窗口（活頁簿〈BASIC2〉J7:M8，預設 K2＝5年平均）要幾年。
#: **這不是抓取的門檻**——見 `check`。
PE_WINDOW_YEARS = 5


def check(years: Sequence[Year]) -> None:
    """Fail only when there is nothing usable at all.

    以前這裡是「少於 5 年就報錯、整份不存」（2026-10-08 改掉）。那個 5 年是照活頁簿
    本益比區間的 5 年平均窗口訂的，但它擋錯了地方：

    * 估價引擎自己就會判斷夠不夠——5 年窗口裡有 3 年就算得出本益比區間
      （`valuation.eps_forecast.PeBand`），河流圖要 5 個年度倍數（`build_pe_river`），
      不夠的那一項各自留白並寫明原因。
    * 擋在抓取這一步，上市 1～4 年的股票連已經有的那幾年都不存，殖利率估價與
      本益比區間整塊空白，而錯誤訊息還寫「可能是代號有誤」。

    現在：有幾年存幾年。只有「一年都沒有」（今年才上市，交易所還沒有完整年度）
    才報錯——那一種明年一月再問。
    """
    if not years:
        raise FetchError(
            "年度交易資訊只取得 0 年：今年才上市（櫃），交易所還沒有任何完整年度，"
            "至少需要 1 年。"
        )
    if not any(y.high and y.low for y in years):
        raise FetchError("年度交易資訊沒有任何一年有最高／最低價")


def to_grid(years: Sequence[Year]) -> list[list[str]]:
    """The sheet as the rest of the pipeline reads it — body at row 3."""
    grid: list[list[str]] = [[] for _ in range(ORIGIN - 1)]
    for y in years:
        line = [""] * WIDTH
        line[COL_YEAR] = str(y.year)
        for col, value in ((COL_HIGH, y.high), (COL_LOW, y.low), (COL_AVG, y.avg)):
            line[col] = "" if value is None else repr(value)
        grid.append(line)
    return grid


@dataclass
class YearlyTrading:
    """Fetch and merge both exchanges' yearly summaries for one stock."""

    http: HttpClient

    def _get(self, url: str, params: dict[str, str]) -> Any:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self.http.get_json(f"{url}?{query}")

    def raw(self, stock_id: str) -> dict[str, Any]:
        """Both responses, unparsed — what ``--save-raw`` writes."""
        out: dict[str, Any] = {}
        for name, url, params in (
            ("twse", TWSE_YEARLY, {"response": "json", "stockNo": stock_id}),
            ("tpex", TPEX_YEARLY, {"code": stock_id, "id": "", "response": "json"}),
        ):
            try:
                out[name] = self._get(url, params)
            except Exception as exc:  # noqa: BLE001 - one exchange is enough
                out[name] = {"error": str(exc)}
        return out

    def fetch(
        self, stock_id: str, raw: dict[str, Any] | None = None
    ) -> tuple[list[list[str]], list[str]]:
        """The sheet grid, and which exchanges actually supplied it.

        ``raw`` lets a caller that has already downloaded (``--save-raw``) hand
        the payloads straight in, rather than paying for the round trip twice.
        """
        raw = self.raw(stock_id) if raw is None else raw
        parsed: dict[str, list[Year]] = {}
        errors: list[str] = []
        for name in ("twse", "tpex"):
            payload = raw.get(name)
            if isinstance(payload, dict) and "error" in payload:
                errors.append(f"{name}: {payload['error']}")
                continue
            try:
                parsed[name] = parse(payload)
            except NotListedHere:
                continue  # the stock is simply listed on the other exchange
            except FetchError as exc:
                errors.append(f"{name}: {exc}")
        years = merge(parsed.get("twse", []), parsed.get("tpex", []))
        if not years:
            raise FetchError(
                "年度交易資訊抓取失敗：\n  " + "\n  ".join(errors or ["兩個交易所都沒有這檔"])
            )
        # 一邊真的失敗了，就不要把另一邊當成完整答案。
        #
        # `NotListedHere` 不會進 errors（那只是「這檔在另一個交易所」，是正常的），
        # 所以 errors 非空代表真的有一次抓取掛掉。而這裡最貴的情況是**轉板的股票**：
        # 1558 伸興從上櫃轉上市，證交所那半邊 307 失敗、櫃買回了 96–103 共 8 年，
        # 於是 check() 過關（≥5 年）、檔案就這樣寫出去——一份停在民國 103 年、
        # 看起來完全正常的半份資料。本益比河流圖會拿它去算，而且不會有任何錯誤訊息。
        #
        # 少補一次可以下次再補，寫錯不會有人發現。所以寧可這次不寫。
        if errors:
            raise FetchError(
                "年度交易資訊只拿到一半（另一邊失敗，不寫檔以免存下不完整的歷史）：\n  "
                + "\n  ".join(errors)
            )
        check(years)
        sources = [n for n, ys in parsed.items() if ys]
        return to_grid(years), sources


# ---------------------------------------------------------------------------
# 交易所沒有這一檔的年度表時：由股價週線與每日行情推算
#
# 〔年度交易資訊〕是估值的地基——本益比區間（自行計算）拿它的最高／最低價除以年度
# EPS，殖利率估價拿它的最高／最低／收盤平均去除股利。沒有它，那一檔就沒有本益比
# 河流圖的分區、沒有目標價與下檔價、沒有報酬風險比，也就進不了〔趨勢×六大×報酬〕。
#
# 交易所拿不到的原因幾乎都是「上市未滿五年」：證交所的年度表只列已結束的年度，
# （以前 `check()` 還要至少五年才寫檔，2026-10-08 起有幾年存幾年）。但這三個數字不是只有交易所算得出來——
#
# * 每日行情（2024 起整年都在）：逐日算，和交易所的定義一模一樣。
# * 〔股價(週)〕（1998 起）：最高＝各週最高的最高、最低＝各週最低的最低（實測 6,045
#   個年度 97% 分毫不差，其餘是跨年那一週的歸屬）；收盤平均用週收盤平均近似
#   （中位數誤差 0.15%、九成在 0.5% 以內）。
#
# 所以交易所那一份永遠優先；只有**完全沒有**那一份的股票才用推算的，格線第一列
# 寫明「推算」，個股頁的資料來源會標出來。只算已經結束的年度（和證交所一致，
# 當年度由 `yearly_prices` 的 anchor 留白），而且不早於上市（櫃）那一年。

DERIVED_NOTE = "（推算：交易所沒有這一檔的年度資料，由股價週線與每日行情算出）"


def is_derived(grid: Sequence[Sequence[str]]) -> bool:
    return bool(grid) and bool(grid[0]) and str(grid[0][0]).startswith("（推算")


_LISTED: dict[str, dict[str, str]] = {}


def listing_dates(data_dir: Any) -> dict[str, str]:
    """代號 → 上市（櫃）日期 `YYYYMMDD`，取自兩個交易所的公司基本資料快照。讀不到回空的。"""
    import csv  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    root = Path(data_dir)
    key = str(root.resolve())
    if key in _LISTED:
        return _LISTED[key]
    out: dict[str, str] = {}
    for name, code_col, date_col in (("twse_companies.csv", "公司代號", "上市日期"),
                                     ("tpex_companies.csv", "SecuritiesCompanyCode",
                                      "DateOfListing")):
        try:
            with (root / name).open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    code = (row.get(code_col) or "").strip()
                    day = (row.get(date_col) or "").strip()
                    if code and len(day) == 8 and day.isdigit():
                        out[code] = day
        except (OSError, csv.Error):
            continue
    _LISTED[key] = out
    return out


def derive(weekly_grid: Sequence[Sequence[str]], daily: dict[int, tuple[float, float, float]],
           *, this_year: int, listed_year: int = 0) -> list[Year]:
    """推算的年度表（民國年，新的在前）。每日行情有的年份用每日行情，其餘用週線。"""
    weeks: dict[int, list[tuple[float, float, float]]] = {}
    for row in list(weekly_grid)[1:]:
        try:
            y = int(str(row[1])[:4])
            c, h, lo = float(row[2]), float(row[4]), float(row[5])
        except (IndexError, ValueError):
            continue
        weeks.setdefault(y, []).append((c, h, lo))
    out: list[Year] = []
    for y in sorted(set(weeks) | set(daily), reverse=True):
        if y >= this_year or y < listed_year:
            continue
        if y in daily:
            hi, lo, avg = daily[y]
        else:
            ws = weeks[y]
            hi = max(w[1] for w in ws)
            lo = min(w[2] for w in ws)
            avg = round(sum(w[0] for w in ws) / len(ws), 2)
        out.append(Year(year=y - 1911, high=hi, low=lo, avg=avg))
    return out


def with_derived_yearly(grids: dict, data_dir: Any, stock: str, *, this_year: int | None = None) -> dict:
    """沒有〔年度交易資訊〕的股票，補一份推算的（見上面的說明）。有的原樣回傳。"""
    from datetime import date  # noqa: PLC0415

    from ..store.daily import yearly_from_daily  # noqa: PLC0415

    if grids.get(SHEET):
        return grids
    try:
        listed = listing_dates(data_dir).get(stock, "")
        years = derive(
            grids.get("股價(週)") or [],
            yearly_from_daily(data_dir).get(stock, {}),
            this_year=this_year or date.today().year,
            listed_year=int(listed[:4]) if listed else 0,
        )
    except Exception:  # noqa: BLE001 - 推算不出來就照舊（沒有這一張）
        return grids
    if not years:
        return grids
    grid = to_grid(years)
    grid[0] = [DERIVED_NOTE] + [""] * (WIDTH - 1)
    return {**grids, SHEET: grid}


def absence_note(data_dir: Any, stock: str, *, this_year: int | None = None) -> str:
    """推算也推不出來時，說一句為什麼（個股頁資料來源那一格用）。說不出來回空字串。"""
    from datetime import date  # noqa: PLC0415

    listed = listing_dates(data_dir).get(stock, "")
    if listed[:4] == str(this_year or date.today().year):
        return "今年才上市（櫃），還沒有任何一個完整年度"
    return ""


def annotate_sources(page: Any, data_dir: Any, stock: str) -> None:
    """個股頁〔資料來源〕裡〔年度交易資訊〕那一格：沒有的話補上原因。"""
    for src in getattr(page, "sources", None) or []:
        if src.get("sheet") == SHEET and not src.get("ok") and not src.get("note"):
            src["note"] = absence_note(data_dir, stock)

