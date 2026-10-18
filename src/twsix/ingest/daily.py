
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import HttpClient

TWSE_PRICES = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_PRICES_WEB = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999&response=json"
)
TPEX_PRICES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

TWSE_PRICES_DATED = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?date={ymd}&type=ALLBUT0999&response=json"
)
TPEX_PRICES_DATED = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
    "?date={y}/{m}/{d}&type=EW&response=json"
)
TWSE_INSTITUTIONAL = "https://www.twse.com.tw/rwd/zh/fund/T86?selectType=ALL&response=json"
TPEX_INSTITUTIONAL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"

TWSE_INSTITUTIONAL_DATED = (
    "https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALL&response=json"
)
TPEX_INSTITUTIONAL_DATED = (
    "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={y}/{m}/{d}"
)

TWSE_QFII_DATED = (
    "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={ymd}&selectType=ALLBUT0999&response=json"
)
TPEX_QFII_DATED = "https://www.tpex.org.tw/www/zh-tw/insti/qfii?date={y}%2F{m}%2F{d}&response=json"

TAIPEI = timezone(timedelta(hours=8))

PRICE_COLUMNS: tuple[str, ...] = (
    "date", "code", "market", "close", "open", "high", "low", "change", "volume", "value",
)
INSTITUTIONAL_COLUMNS: tuple[str, ...] = (
    "date", "code", "market", "foreign", "trust", "dealer", "total",
    "f_buy", "f_sell", "t_buy", "t_sell",
)

QFII_COLUMNS: tuple[str, ...] = ("date", "code", "market", "issued", "held", "pct")

_CODE = re.compile(r"^(?:\d{4}|91\d{4})$")


def _key(name: str) -> str:
    return "".join(str(name).split())


def _pick(row: dict[str, Any], *names: str) -> Any:
    wanted = {_key(n) for n in names}
    for k, v in row.items():
        if _key(k) in wanted:
            return v
    return None


def _num(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text in ("--", "---", "N/A", "－", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date(value: Any) -> str:
    text = str(value or "").strip().replace("/", "").replace("-", "")
    if len(text) == 7 and text.isdigit():
        return f"{int(text[:3]) + 1911:04d}-{text[3:5]}-{text[5:7]}"
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return ""


def parse_twse_prices(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(row.get("Code", "")).strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(row.get("Date")),
                "code": code,
                "market": "上市",
                "close": _num(row.get("ClosingPrice")),
                "open": _num(row.get("OpeningPrice")),
                "high": _num(row.get("HighestPrice")),
                "low": _num(row.get("LowestPrice")),
                "change": _num(row.get("Change")),
                "volume": _num(row.get("TradeVolume")),
                "value": _num(row.get("TradeValue")),
            }
        )
    return out


def parse_tpex_prices(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(_pick(row, "SecuritiesCompanyCode") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(_pick(row, "Date")),
                "code": code,
                "market": "上櫃",
                "close": _num(_pick(row, "Close")),
                "open": _num(_pick(row, "Open")),
                "high": _num(_pick(row, "High")),
                "low": _num(_pick(row, "Low")),
                "change": _num(_pick(row, "Change")),
                "volume": _num(_pick(row, "TradingShares")),
                "value": _num(_pick(row, "TransactionAmount")),
            }
        )
    return out


def parse_twse_mi_index(payload: Any) -> list[dict[str, Any]]:
    tables = (payload or {}).get("tables") or ()
    table = next(
        (t for t in tables if "每日收盤行情" in str(t.get("title", ""))), None
    )
    if not table:
        return []
    fields = [_key(f) for f in table.get("fields") or ()]
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], name: str) -> Any:
        i = index.get(_key(name))
        return row[i] if i is not None and i < len(row) else None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in table.get("data") or ():
        code = str(at(row, "證券代號") or "").strip()
        if not _CODE.match(code):
            continue
        change = _num(at(row, "漲跌價差"))
        if change is not None and "-" in _tag_text(at(row, "漲跌(+/-)")):
            change = -change
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上市",
                "close": _num(at(row, "收盤價")),
                "open": _num(at(row, "開盤價")),
                "high": _num(at(row, "最高價")),
                "low": _num(at(row, "最低價")),
                "change": change,
                "volume": _num(at(row, "成交股數")),
                "value": _num(at(row, "成交金額")),
            }
        )
    return out


def parse_tpex_rwd(payload: Any) -> list[dict[str, Any]]:
    tables = (payload or {}).get("tables") or ()
    table = next(
        (t for t in tables if "每日收盤行情" in str(t.get("title", ""))), None
    )
    if not table:
        return []
    fields = [_key(f) for f in table.get("fields") or ()]
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], name: str) -> Any:
        i = index.get(_key(name))
        return row[i] if i is not None and i < len(row) else None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in table.get("data") or ():
        code = str(at(row, "代號") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上櫃",
                "close": _num(at(row, "收盤")),
                "open": _num(at(row, "開盤")),
                "high": _num(at(row, "最高")),
                "low": _num(at(row, "最低")),
                "change": _num(at(row, "漲跌")),
                "volume": _num(at(row, "成交股數")),
                "value": _num(at(row, "成交金額(元)")),
            }
        )
    return out


def _tag_text(value: Any) -> str:
    return re.sub(r"<[^>]*>", "", str(value or "")).strip()


def merge_prices(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        for row in group:
            key = (str(row.get("date") or ""), str(row.get("code") or ""))
            if key[0] and key[1] and key not in seen:
                seen[key] = row
    return list(seen.values())


def parse_twse_institutional(payload: Any) -> list[dict[str, Any]]:
    fields = [_key(f) for f in (payload or {}).get("fields") or ()]
    if not fields:
        return []
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], *names: str) -> Any:
        for n in names:
            i = index.get(_key(n))
            if i is not None and i < len(row):
                return row[i]
        return None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in (payload or {}).get("data") or ():
        code = str(at(row, "證券代號") or "").strip()
        if not _CODE.match(code):
            continue
        foreign = _num(at(row, "外陸資買賣超股數(不含外資自營商)"))
        dealer_self = _num(at(row, "自營商買賣超股數(自行買賣)"))
        dealer_hedge = _num(at(row, "自營商買賣超股數(避險)"))
        dealer = _num(at(row, "自營商買賣超股數"))
        if dealer is None and (dealer_self is not None or dealer_hedge is not None):
            dealer = (dealer_self or 0) + (dealer_hedge or 0)
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上市",
                "foreign": foreign,
                "trust": _num(at(row, "投信買賣超股數")),
                "dealer": dealer,
                "total": _num(at(row, "三大法人買賣超股數")),
                "f_buy": _num(at(row, "外陸資買進股數(不含外資自營商)")),
                "f_sell": _num(at(row, "外陸資賣出股數(不含外資自營商)")),
                "t_buy": _num(at(row, "投信買進股數")),
                "t_sell": _num(at(row, "投信賣出股數")),
            }
        )
    return _check_gross(out, f"上市三大法人 {day}")


def parse_tpex_institutional(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(_pick(row, "SecuritiesCompanyCode") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(_pick(row, "Date")),
                "code": code,
                "market": "上櫃",
                "foreign": _num(
                    _pick(row, "ForeignInvestorsIncludeMainlandAreaInvestors-Difference")
                ),
                "trust": _num(_pick(row, "SecuritiesInvestmentTrustCompanies-Difference")),
                "dealer": _num(_pick(row, "Dealers-Difference")),
                "total": _num(_pick(row, "TotalDifference")),
                "f_buy": _num(_pick(row, "ForeignInvestorsIncludeMainlandAreaInvestors-TotalBuy")),
                "f_sell": _num(_pick(row, "ForeignInvestorsIncludeMainlandAreaInvestors-TotalSell")),
                "t_buy": _num(_pick(row, "SecuritiesInvestmentTrustCompanies-TotalBuy")),
                "t_sell": _num(_pick(row, "SecuritiesInvestmentTrustCompanies-TotalSell")),
            }
        )
    return _check_gross(out, "上櫃三大法人（開放資料）")


_TPEX_INSTI_COLS = {"foreign": 10, "trust": 13, "dealer": 22, "total": 23,
                    "f_buy": 8, "f_sell": 9, "t_buy": 11, "t_sell": 12}
_TPEX_INSTI_MIN_COLS = 24


def parse_tpex_institutional_dated(payload: Any) -> list[dict[str, Any]]:
    tables = (payload or {}).get("tables") or []
    table = tables[0] if tables else {}
    rows = table.get("data") or []
    if not rows:
        return []
    day = _date(str(table.get("date") or (payload or {}).get("date") or ""))

    out: list[dict[str, Any]] = []
    checked = bad = 0
    for row in rows:
        if len(row) < _TPEX_INSTI_MIN_COLS:
            continue
        code = str(row[0] or "").strip()
        if not _CODE.match(code):
            continue
        vals = {k: _num(row[i]) for k, i in _TPEX_INSTI_COLS.items()}
        parts = (vals["foreign"], vals["trust"], vals["dealer"])
        if vals["total"] is not None and all(v is not None for v in parts):
            checked += 1
            if sum(parts) != vals["total"]:
                bad += 1
        out.append({"date": day, "code": code, "market": "上櫃", **vals})

    if checked and bad / checked > 0.10:
        print(
            f"    ⚠️ 上櫃三大法人 {day}：{bad}/{checked} 列的"
            "「合計 = 外資 + 投信 + 自營商」對不上，欄序可能變了，整批不採用。"
        )
        return []
    return _check_gross(out, f"上櫃三大法人 {day}")


def _pct(value: Any) -> float | None:
    return _num(str(value or "").replace("%", ""))


def _qfii_row(day: str, code: str, market: str, issued: Any, held: Any, pct: Any) -> dict[str, Any]:
    return {
        "date": day, "code": code, "market": market,
        "issued": _num(issued), "held": _num(held), "pct": _pct(pct),
    }


def _qfii_sane(rows: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    checked = bad = 0
    for r in rows:
        if r["issued"] and r["held"] is not None and r["pct"] is not None:
            checked += 1
            if abs(r["held"] / r["issued"] * 100 - r["pct"]) > 0.6:
                bad += 1
    if checked and bad / checked > 0.10:
        print(f"    ⚠️ {label}：{bad}/{checked} 筆「持有 ÷ 發行 ≠ 持股比率」，整批不採用。")
        return []
    return rows


def parse_twse_qfii(payload: Any) -> list[dict[str, Any]]:
    payload = payload or {}
    if str(payload.get("stat") or "").upper() != "OK":
        return []
    fields = [_key(f) for f in payload.get("fields") or ()]
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], *names: str) -> Any:
        for n in names:
            i = index.get(_key(n))
            if i is not None and i < len(row):
                return row[i]
        return None

    day = _date(payload.get("date"))
    out = []
    for row in payload.get("data") or ():
        code = str(at(row, "證券代號") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(_qfii_row(
            day, code, "上市",
            at(row, "發行股數"),
            at(row, "全體外資及陸資持有股數"),
            at(row, "全體外資及陸資持股比率"),
        ))
    return _qfii_sane(out, f"上市外資持股 {day}")


def parse_tpex_qfii(payload: Any) -> list[dict[str, Any]]:
    tables = (payload or {}).get("tables") or []
    if not tables:
        return []
    table = tables[0] or {}
    fields = [_key(f) for f in table.get("fields") or ()]

    def col(prefix: str) -> int | None:
        p = _key(prefix)
        return next((i for i, f in enumerate(fields) if f.startswith(p)), None)

    i_code, i_issued = col("代號"), col("發行股數")
    i_held, i_pct = col("僑外資及陸資持有股數"), col("僑外資及陸資持股比率")
    if None in (i_code, i_issued, i_held, i_pct):
        return []
    day = _date(table.get("date"))
    out = []
    for row in table.get("data") or ():
        if len(row) <= max(i_code, i_issued, i_held, i_pct):  # type: ignore[type-var]
            continue
        code = str(row[i_code] or "").strip()
        if not _CODE.match(code):
            continue
        out.append(_qfii_row(day, code, "上櫃", row[i_issued], row[i_held], row[i_pct]))
    return _qfii_sane(out, f"上櫃外資持股 {day}")


def _check_gross(rows: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    checked = bad = 0
    for r in rows:
        for b, s, n in (("f_buy", "f_sell", "foreign"), ("t_buy", "t_sell", "trust")):
            if r.get(b) is None or r.get(s) is None or r.get(n) is None:
                continue
            checked += 1
            if abs((r[b] - r[s]) - r[n]) > 0.5:
                bad += 1
    if checked and bad / checked > 0.10:
        print(f"    ⚠️ {label}：{bad}/{checked} 筆「買進 − 賣出 ≠ 買賣超」，買進／賣出欄不採用。")
        for r in rows:
            for k in ("f_buy", "f_sell", "t_buy", "t_sell"):
                r[k] = None
    return rows


def by_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = str(row.get("date") or "")
        if day:
            out.setdefault(day, []).append(row)
    return out


class Daily:

    def __init__(self, http: HttpClient):
        self.http = http
        self.problems: list[str] = []

    def _json(self, url: str) -> Any:
        raw = self.http.get(url, use_cache=False)
        return json.loads(raw.decode("utf-8-sig", errors="replace"))

    def prices(self, day: str | None = None) -> list[dict[str, Any]]:
        groups: list[list[dict[str, Any]]] = []
        for url, parse in (
            (TWSE_PRICES, parse_twse_prices),
            (TWSE_PRICES_WEB, parse_twse_mi_index),
            (TPEX_PRICES, parse_tpex_prices),
        ):
            try:
                groups.append(parse(self._json(url)))
            except Exception as exc:  # noqa: BLE001 - 一個來源掛掉不該拖垮其餘
                self.problems.append(f"{url.split('/')[2]} 沒拿到：{exc}")
                print(f"    （{url.split('/')[2]} 沒拿到：{exc}）")

        rows = merge_prices(*groups)
        if not any(r.get("market") == "上櫃" for r in rows):
            iso = day or datetime.now(TAIPEI).date().isoformat()
            extra = self._tpex_by_date(iso)
            if extra:
                rows = merge_prices(rows, extra)
        return rows

    def _tpex_by_date(self, iso: str) -> list[dict[str, Any]]:
        y, m, d = iso.split("-")
        url = TPEX_PRICES_DATED.format(y=y, m=m, d=d)
        try:
            rows = parse_tpex_rwd(self._json(url))
        except Exception as exc:  # noqa: BLE001 - 備援失敗不該拖垮已經抓好的
            self.problems.append(f"上櫃備援（{iso}）也沒拿到：{exc}")
            print(f"    （上櫃備援 {iso} 也沒拿到：{exc}）")
            return []
        if not rows:
            print(f"    （上櫃備援 {iso} 回空表，可能是非交易日）")
            return []
        print(f"    （上櫃改用備援來源 {iso}，取得 {len(rows)} 檔）")
        return rows

    def prices_on(self, day: str) -> list[dict[str, Any]]:
        y, m, d = day.split("-")
        out: list[dict[str, Any]] = []
        for url, parse in (
            (TWSE_PRICES_DATED.format(ymd=f"{y}{m}{d}"), parse_twse_mi_index),
            (TPEX_PRICES_DATED.format(y=y, m=m, d=d), parse_tpex_rwd),
        ):
            try:
                out += parse(self._json(url))
            except Exception as exc:  # noqa: BLE001
                print(f"    （{url.split('/')[2]} {day} 沒拿到：{exc}）")
        return out

    def institutional(self) -> list[dict[str, Any]]:
        return parse_twse_institutional(
            self._json(TWSE_INSTITUTIONAL)
        ) + parse_tpex_institutional(self._json(TPEX_INSTITUTIONAL))

    def institutional_on(self, day: str) -> list[dict[str, Any]]:
        y, m, d = day.split("-")
        out: list[dict[str, Any]] = []
        for url, parse in (
            (TWSE_INSTITUTIONAL_DATED.format(ymd=f"{y}{m}{d}"), parse_twse_institutional),
            (TPEX_INSTITUTIONAL_DATED.format(y=y, m=m, d=d), parse_tpex_institutional_dated),
        ):
            try:
                out += parse(self._json(url))
            except Exception as exc:  # noqa: BLE001
                print(f"    （{url.split('/')[2]} {day} 沒拿到：{exc}）")
        return out

    def qfii_on(self, day: str) -> list[dict[str, Any]]:
        y, m, d = day.split("-")
        out: list[dict[str, Any]] = []
        for url, parse in (
            (TWSE_QFII_DATED.format(ymd=f"{y}{m}{d}"), parse_twse_qfii),
            (TPEX_QFII_DATED.format(y=y, m=m, d=d), parse_tpex_qfii),
        ):
            try:
                out += parse(self._json(url))
            except Exception as exc:  # noqa: BLE001
                print(f"    （{url.split('/')[2]} {day} 外資持股沒拿到：{exc}）")
        return out
