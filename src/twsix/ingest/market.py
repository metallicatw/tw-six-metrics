
from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..calendar_tw import Quarter
from ..rating.engine import FinancialData

_QUARTER_FILE = re.compile(r"^(\d{3})Q([1-4])$")
_MONTH_FILE = re.compile(r"^(\d{3})(\d{2})$")

CODE_KEYS = ("公司代號", "SecuritiesCompanyCode")
NAME_KEYS = ("公司簡稱", "CompanyAbbreviation", "公司名稱", "CompanyName")
INDUSTRY_KEYS = ("產業別",)

INDUSTRY_CODES = {"17": "金融保險業", "91": "存託憑證"}

DR_INDUSTRY = "存託憑證"

REVENUE_KEYS = ("營業收入",)
OPERATING_INCOME_KEYS = ("營業利益（損失）",)
NET_INCOME_KEYS = ("淨利（淨損）歸屬於母公司業主", "本期淨利（淨損）")
EPS_KEYS = ("基本每股盈餘（元）",)
NON_OPERATING_KEYS = ("營業外收入及支出",)
PRETAX_INCOME_KEYS = ("稅前淨利（淨損）",)

CF_OPERATING_KEYS = ("營業活動之淨現金流入（流出）",)
CF_INVESTING_KEYS = ("投資活動之淨現金流入（流出）",)

THOUSANDS_PER_MILLION = 1000

MONTH_REVENUE_KEYS = ("營業收入-當月營收",)
MONTH_LAST_YEAR_KEYS = ("營業收入-去年當月營收",)
MONTH_YOY_KEYS = ("營業收入-去年同月增減(%)",)

EXCLUDED_INDUSTRIES = ("金融保險業", "金融保險", "金融業")


def _first(row: Mapping[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


def _num(row: Mapping[str, str], keys: Iterable[str]) -> float | None:
    text = _first(row, keys).replace(",", "")
    if not text or text in ("--", "N/A", "－"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class MarketData:

    root: Path
    income: dict[Quarter, dict[str, dict[str, str]]] = field(default_factory=dict)
    balance: dict[Quarter, dict[str, dict[str, str]]] = field(default_factory=dict)
    cashflow: dict[Quarter, dict[str, dict[str, str]]] = field(default_factory=dict)
    revenue: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    markets: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    industry_codes: dict[str, str] = field(default_factory=dict)


    @classmethod
    def load(cls, root: str | Path) -> MarketData:
        data = cls(root=Path(root))
        market = data.root / "market"
        for exchange, label in (("twse", "上市"), ("tpex", "上櫃")):
            for kind, target in (("income", data.income), ("balance", data.balance),
                                 ("cashflow", data.cashflow)):
                for path in sorted(market.glob(f"{exchange}_{kind}/*.csv")):
                    m = _QUARTER_FILE.match(path.stem)
                    if not m:
                        continue
                    quarter = Quarter(int(m.group(1)) + 1911, int(m.group(2)))
                    target.setdefault(quarter, {}).update(data._rows(path, label))
            for path in sorted(market.glob(f"{exchange}_revenue/*.csv")):
                m = _MONTH_FILE.match(path.stem)
                if not m:
                    continue
                label_month = f"{int(m.group(1))}/{m.group(2)}"
                data.revenue.setdefault(label_month, {}).update(data._rows(path, label))
            companies = data.root / f"{exchange}_companies.csv"
            if companies.exists():
                for code, row in data._rows(companies, label).items():
                    value = _first(row, INDUSTRY_KEYS)
                    if value and value.isdigit():
                        data.industry_codes.setdefault(code, value)
        return data

    def _rows(self, path: Path, market: str) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                code = _first(row, CODE_KEYS)
                if not code:
                    continue
                out[code] = row
                self.markets.setdefault(code, market)
                name = _first(row, NAME_KEYS)
                if name and code not in self.names:
                    self.names[code] = name
        return out


    @property
    def quarters(self) -> list[Quarter]:
        return sorted(self.income, reverse=True)

    @property
    def months(self) -> list[str]:
        return sorted(self.revenue, reverse=True)

    def codes(self) -> list[str]:
        seen: set[str] = set(self.markets)
        return sorted(seen)

    def industry(self, code: str) -> str:
        for month in self.months:
            row = self.revenue.get(month, {}).get(code)
            if row:
                value = _first(row, INDUSTRY_KEYS)
                if value:
                    return value
        return INDUSTRY_CODES.get(self.industry_codes.get(code, ""), "")


    def financials(self, code: str) -> FinancialData:
        industry = self.industry(code)
        data = FinancialData(
            stock_id=code,
            name=self.names.get(code, ""),
            market=self.markets.get(code, ""),
            industry=industry,
            excluded=(
                "金融保險業不適用"
                if industry in EXCLUDED_INDUSTRIES
                else "存託憑證不適用（原股在境外掛牌，沒有台灣格式的財報與月營收）"
                if industry == DR_INDUSTRY
                else ""
            ),
        )
        self._statements(code, data)
        self._revenue(code, data)
        return data

    def _statements(self, code: str, data: FinancialData) -> None:
        for quarter in self.quarters:
            row = self.income.get(quarter, {}).get(code)
            if not row:
                continue
            previous = (
                None
                if quarter.q == 1
                else self.income.get(quarter.shift(-1), {}).get(code)
            )
            if quarter.q != 1 and previous is None:
                continue
            revenue = _single(row, previous, REVENUE_KEYS, quarter)
            operating = _single(row, previous, OPERATING_INCOME_KEYS, quarter)
            net = _single(row, previous, NET_INCOME_KEYS, quarter)
            eps = _single(row, previous, EPS_KEYS, quarter)
            non_op = _single(row, previous, NON_OPERATING_KEYS, quarter)
            pretax = _single(row, previous, PRETAX_INCOME_KEYS, quarter)
            if revenue:
                if operating is not None:
                    data.operating_margin[quarter] = round(operating / revenue * 100, 2)
                if net is not None:
                    data.net_margin[quarter] = round(net / revenue * 100, 2)
            if non_op is not None and pretax:
                data.non_operating_ratio[quarter] = round(non_op / pretax * 100, 2)
            if net is not None:
                data.net_income[quarter] = net
            if eps is not None:
                data.eps[quarter] = round(eps, 2)
        self._cash_flow(code, data)

    def _cash_flow(self, code: str, data: FinancialData) -> None:
        for quarter in sorted(self.cashflow, reverse=True):
            row = self.cashflow.get(quarter, {}).get(code)
            if not row:
                continue
            previous = (
                None
                if quarter.q == 1
                else self.cashflow.get(quarter.shift(-1), {}).get(code)
            )
            if quarter.q != 1 and previous is None:
                continue
            operating = _single(row, previous, CF_OPERATING_KEYS, quarter)
            investing = _single(row, previous, CF_INVESTING_KEYS, quarter)
            if operating is None or investing is None:
                continue
            data.free_cash_flow[quarter] = round(
                (operating + investing) / THOUSANDS_PER_MILLION, 2
            )

    def _revenue(self, code: str, data: FinancialData) -> None:
        raw: dict[str, tuple[float | None, float | None, float | None]] = {}
        for month in self.months:
            row = self.revenue.get(month, {}).get(code)
            if not row:
                continue
            raw[month] = (
                _num(row, MONTH_REVENUE_KEYS),
                _num(row, MONTH_LAST_YEAR_KEYS),
                _num(row, MONTH_YOY_KEYS),
            )
        labels = sorted(raw, reverse=True)
        data.revenue_months_raw = labels
        merged: list[str] = []
        for label in labels:
            year, part = label.split("/")
            if part != "02":
                merged.append(label)
                if raw[label][2] is not None:
                    data.revenue_yoy[label] = raw[label][2]
                continue
            january = raw.get(f"{year}/01")
            if january is None:
                merged.append(label)
                if raw[label][2] is not None:
                    data.revenue_yoy[label] = raw[label][2]
                continue
            combined = f"{year}/01-02"
            merged.append(combined)
            now = _add(raw[label][0], january[0])
            before = _add(raw[label][1], january[1])
            if now is not None and before:
                data.revenue_yoy[combined] = round((now - before) / abs(before) * 100, 2)
        data.revenue_months = [m for m in merged if not m.endswith("/01")]


def _single(
    row: Mapping[str, str],
    previous: Mapping[str, str] | None,
    keys: Iterable[str],
    quarter: Quarter,
) -> float | None:
    now = _num(row, keys)
    if now is None:
        return None
    if quarter.q == 1:
        return now
    if previous is None:
        return None
    before = _num(previous, keys)
    if before is None:
        return None
    return now - before


def _add(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a + b
