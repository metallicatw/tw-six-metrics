"""每日全市場的「成交金額」與「法人買進／賣出分開的股數」.

〔籌碼雷達〕要的兩樣東西，原本的每日行情檔沒有存：

* **成交金額**（元）。行情檔只有成交股數，金額只能用 股數 × 收盤價 估。高價股
  盤中振幅大時，那個估計可以差好幾個百分點。
* **法人的買進與賣出**。三大法人檔只存了買賣超（淨額）。「法人預估成交額」
  「法人市值周轉率」要的是買進＋賣出，淨額算不出來。

兩樣東西其實**本來就在**每日抓的那四個回應裡（上市 MI_INDEX 有「成交金額」、
T86 有「外陸資買進／賣出股數」「投信買進／賣出股數」；上櫃兩支同理），只是既有
的 parser 沒有讀它們。這裡**不改**既有的 parser 與檔案格式，另外讀一次、另外存：

    data/market/daily/flows/<YYYY-MM-DD>.csv.gz
        date, code, market, value, f_buy, f_sell, t_buy, t_sell

外資的口徑跟既有的三大法人檔一致：上市是「外陸資（不含外資自營商）」、上櫃是
「外資及陸資合計」——所以 `f_buy − f_sell` 會等於三大法人檔裡的 `foreign`。
每一列都拿「買進 − 賣出 ＝ 買賣超」驗算，對不上的比例超過一成整批不收（欄序
可能變了）。
"""

from __future__ import annotations

import json
from typing import Any

from .base import HttpClient
from .daily import (
    _CODE,
    TPEX_INSTITUTIONAL_DATED,
    TPEX_PRICES_DATED,
    TWSE_INSTITUTIONAL_DATED,
    TWSE_PRICES_DATED,
    _date,
    _key,
    _num,
)

FIELDS = ("date", "code", "market", "value", "f_buy", "f_sell", "t_buy", "t_sell")

#: 上櫃三大法人明細的位置（和 daily._TPEX_INSTI_COLS 同一份實測）：
#: 8~10 外資及陸資合計（買、賣、超）、11~13 投信（買、賣、超）
_TPEX_F = (8, 9, 10)
_TPEX_T = (11, 12, 13)


def _table(payload: Any, title: str) -> dict:
    tables = (payload or {}).get("tables") or ()
    return next((t for t in tables if title in str(t.get("title", ""))), {}) or {}


def parse_twse_value(payload: Any) -> dict[str, float]:
    """上市 MI_INDEX 的「每日收盤行情」表 → `{代號: 成交金額}`。"""
    table = _table(payload, "每日收盤行情")
    fields = [_key(f) for f in table.get("fields") or ()]
    idx = {n: i for i, n in enumerate(fields)}
    ic, iv = idx.get(_key("證券代號")), idx.get(_key("成交金額"))
    if ic is None or iv is None:
        return {}
    out: dict[str, float] = {}
    for row in table.get("data") or ():
        code = str(row[ic] or "").strip()
        v = _num(row[iv]) if iv < len(row) else None
        if _CODE.match(code) and v is not None:
            out[code] = v
    return out


def parse_tpex_value(payload: Any) -> dict[str, float]:
    """上櫃每日收盤行情（帶日期那一支）→ `{代號: 成交金額}`。欄名帶空白，要正規化。"""
    table = _table(payload, "每日收盤行情")
    fields = [_key(f) for f in table.get("fields") or ()]
    idx = {n: i for i, n in enumerate(fields)}
    ic, iv = idx.get(_key("代號")), idx.get(_key("成交金額(元)"))
    if ic is None or iv is None:
        return {}
    out: dict[str, float] = {}
    for row in table.get("data") or ():
        code = str(row[ic] or "").strip()
        v = _num(row[iv]) if iv < len(row) else None
        if _CODE.match(code) and v is not None:
            out[code] = v
    return out


def _checked(rows: list[dict[str, Any]], nets: list[tuple[float | None, float | None]],
             label: str) -> list[dict[str, Any]]:
    """買進 − 賣出 ＝ 買賣超，對不上超過一成就整批不收。"""
    checked = bad = 0
    for row, (fnet, tnet) in zip(rows, nets, strict=True):
        for b, s, n in ((row["f_buy"], row["f_sell"], fnet), (row["t_buy"], row["t_sell"], tnet)):
            if b is None or s is None or n is None:
                continue
            checked += 1
            if abs((b - s) - n) > 0.5:
                bad += 1
    if checked and bad / checked > 0.10:
        print(f"    ⚠️ {label}：{bad}/{checked} 筆「買進 − 賣出 ≠ 買賣超」，欄序可能變了，整批不採用。")
        return []
    return rows


def parse_twse_flows(payload: Any) -> list[dict[str, Any]]:
    """上市 T86 → 外資、投信的買進與賣出股數。欄位靠名字對。"""
    fields = [_key(f) for f in (payload or {}).get("fields") or ()]
    if not fields:
        return []
    idx = {n: i for i, n in enumerate(fields)}

    def at(row, name):
        i = idx.get(_key(name))
        return _num(row[i]) if i is not None and i < len(row) else None

    day = _date((payload or {}).get("date"))
    rows, nets = [], []
    for row in (payload or {}).get("data") or ():
        i = idx.get(_key("證券代號"))
        code = str(row[i] if i is not None else "").strip()
        if not _CODE.match(code):
            continue
        rows.append({
            "date": day, "code": code, "market": "上市",
            "f_buy": at(row, "外陸資買進股數(不含外資自營商)"),
            "f_sell": at(row, "外陸資賣出股數(不含外資自營商)"),
            "t_buy": at(row, "投信買進股數"),
            "t_sell": at(row, "投信賣出股數"),
        })
        nets.append((at(row, "外陸資買賣超股數(不含外資自營商)"), at(row, "投信買賣超股數")))
    return _checked(rows, nets, f"上市法人明細 {day}")


def parse_tpex_flows(payload: Any) -> list[dict[str, Any]]:
    """上櫃三大法人明細（帶日期）→ 外資合計、投信的買進與賣出股數。欄名重複，靠位置。"""
    tables = (payload or {}).get("tables") or []
    table = tables[0] if tables else {}
    day = _date(str(table.get("date") or (payload or {}).get("date") or ""))
    rows, nets = [], []
    for row in table.get("data") or []:
        if len(row) < 14:
            continue
        code = str(row[0] or "").strip()
        if not _CODE.match(code):
            continue
        rows.append({
            "date": day, "code": code, "market": "上櫃",
            "f_buy": _num(row[_TPEX_F[0]]), "f_sell": _num(row[_TPEX_F[1]]),
            "t_buy": _num(row[_TPEX_T[0]]), "t_sell": _num(row[_TPEX_T[1]]),
        })
        nets.append((_num(row[_TPEX_F[2]]), _num(row[_TPEX_T[2]])))
    return _checked(rows, nets, f"上櫃法人明細 {day}")


def combine(day: str, values: dict[str, float], flows: list[dict[str, Any]],
            markets: dict[str, str]) -> list[dict[str, Any]]:
    """同一天的成交金額與法人明細併成一張表（有其一就留）。"""
    by: dict[str, dict[str, Any]] = {}
    for code, v in values.items():
        by[code] = {"date": day, "code": code, "market": markets.get(code, ""), "value": v}
    for r in flows:
        slot = by.setdefault(r["code"], {"date": day, "code": r["code"], "market": r["market"]})
        slot.update({k: r[k] for k in ("f_buy", "f_sell", "t_buy", "t_sell")})
        slot["market"] = slot.get("market") or r["market"]
    return [by[c] for c in sorted(by)]


class Flows:
    """某一個交易日的四個請求 → 一張 flows 表。非交易日回空 list。"""

    def __init__(self, http: HttpClient):
        self.http = http
        self.problems: list[str] = []

    def _json(self, url: str) -> Any:
        raw = self.http.get(url, use_cache=False)
        return json.loads(raw.decode("utf-8-sig", errors="replace"))

    def on(self, day: str) -> list[dict[str, Any]]:
        y, m, d = day.split("-")
        values: dict[str, float] = {}
        markets: dict[str, str] = {}
        flows: list[dict[str, Any]] = []
        jobs = (
            (TWSE_PRICES_DATED.format(ymd=f"{y}{m}{d}"), "value", parse_twse_value, "上市"),
            (TPEX_PRICES_DATED.format(y=y, m=m, d=d), "value", parse_tpex_value, "上櫃"),
            (TWSE_INSTITUTIONAL_DATED.format(ymd=f"{y}{m}{d}"), "flow", parse_twse_flows, ""),
            (TPEX_INSTITUTIONAL_DATED.format(y=y, m=m, d=d), "flow", parse_tpex_flows, ""),
        )
        for url, kind, parse, market in jobs:
            try:
                got = parse(self._json(url))
            except Exception as exc:  # noqa: BLE001 - 一支掛掉不該丟掉其他三支
                self.problems.append(f"{url.split('/')[2]} {day}：{exc}")
                print(f"    （{url.split('/')[2]} {day} 沒拿到：{exc}）")
                continue
            if kind == "value":
                values.update(got)
                markets.update(dict.fromkeys(got, market))
            else:
                flows += got
        if not values and not flows:
            return []
        return combine(day, values, flows, markets)
