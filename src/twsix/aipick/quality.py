
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .data import NAN, available_from, isnan

VETO_AT = 3
ACCRUAL_HIGH = 0.10
NON_OP_SHARE = 0.50
LEVERAGE_LEVEL = 0.60
LEVERAGE_JUMP = 0.10
SHRINK = -0.20
PLEDGE_HIGH = 0.30
DIRECTORS_LAG_DAYS = 45

FLAG_TEXT = {
    "op_loss": "本業虧損",
    "loss2": "連兩季虧損",
    "non_op": "獲利靠業外",
    "cash_gap": "獲利沒有變成現金",
    "accrual": "應計比率偏高",
    "leverage": "負債快速上升",
    "shrink": "營收大幅衰退",
    "pledge": "董監高質押",
    "news_auditor": "非例行更換簽證會計師",
    "news_cfo": "財務／會計主管異動",
    "news_distress": "退票、重整或繼續經營疑慮",
    "news_incident": "停工、火災或重大災害",
}


@dataclass(frozen=True)
class Verdict:

    quarter: str
    flags: tuple[str, ...]
    details: tuple[str, ...]
    extra: int = 0

    @property
    def score(self) -> int:
        return len(self.flags) + self.extra

    @property
    def veto(self) -> bool:
        return self.score >= VETO_AT


def _prev(yq: tuple[int, int], back: int = 1) -> tuple[int, int]:
    y, q = yq
    q -= back
    while q <= 0:
        q += 4
        y -= 1
    return (y, q)


def single(stmts: dict, yq: tuple[int, int], key: str) -> float:
    cur = stmts.get(yq, {}).get(key, NAN)
    if isnan(cur):
        return NAN
    if yq[1] == 1:
        return cur
    before = stmts.get(_prev(yq), {}).get(key, NAN)
    return NAN if isnan(before) else cur - before


def ttm(stmts: dict, yq: tuple[int, int], key: str) -> float:
    vals = [single(stmts, _prev(yq, k), key) for k in range(4)]
    return NAN if any(isnan(v) for v in vals) else sum(vals)


def quarter_flags(stmts: dict, yq: tuple[int, int]) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    details: list[str] = []
    ql = f"{yq[0] + 1911}Q{yq[1]}"

    op = single(stmts, yq, "op_income")
    if not isnan(op) and op < 0:
        flags.append("op_loss")
        details.append(f"{ql} 營業利益 {op / 1000:,.0f} 百萬")
    n0, n1 = single(stmts, yq, "net_income"), single(stmts, _prev(yq), "net_income")
    if not isnan(n0) and not isnan(n1) and n0 < 0 and n1 < 0:
        flags.append("loss2")
        details.append(f"最近兩季淨利 {n1 / 1000:,.0f}、{n0 / 1000:,.0f} 百萬")
    pre, nonop = ttm(stmts, yq, "pretax"), ttm(stmts, yq, "non_op")
    if not isnan(pre) and not isnan(nonop) and pre > 0 and nonop / pre > NON_OP_SHARE:
        flags.append("non_op")
        details.append(f"近四季業外占稅前淨利 {nonop / pre:.0%}")
    ni, cfo = ttm(stmts, yq, "net_income"), ttm(stmts, yq, "cfo")
    if not isnan(ni) and not isnan(cfo) and ni > 0 and cfo < 0:
        flags.append("cash_gap")
        details.append(f"近四季淨利 {ni / 1000:,.0f} 百萬、營業現金流 {cfo / 1000:,.0f} 百萬")
    assets = stmts.get(yq, {}).get("assets", NAN)
    if not isnan(ni) and not isnan(cfo) and not isnan(assets) and assets > 0:
        acc = (ni - cfo) / assets
        if acc > ACCRUAL_HIGH:
            flags.append("accrual")
            details.append(f"應計比率 {acc:.1%}（淨利 − 營業現金流 ÷ 總資產）")
    liab, liab_ly = stmts.get(yq, {}).get("liabilities", NAN), stmts.get(_prev(yq, 4), {}).get("liabilities", NAN)
    assets_ly = stmts.get(_prev(yq, 4), {}).get("assets", NAN)
    if all(not isnan(v) and v > 0 for v in (liab, assets, liab_ly, assets_ly)):
        lev, lev_ly = liab / assets, liab_ly / assets_ly
        if lev > LEVERAGE_LEVEL and lev - lev_ly > LEVERAGE_JUMP:
            flags.append("leverage")
            details.append(f"負債比 {lev_ly:.0%} → {lev:.0%}")
    rev, rev_ly = ttm(stmts, yq, "revenue"), ttm(stmts, _prev(yq, 4), "revenue")
    if not isnan(rev) and not isnan(rev_ly) and rev_ly > 0 and rev / rev_ly - 1 < SHRINK:
        flags.append("shrink")
        details.append(f"近四季營收年增 {rev / rev_ly - 1:+.0%}")
    return flags, details


def pledge_ratio_asof(directors: list[tuple[str, float, float]], day: str) -> tuple[float, str]:
    d0 = date.fromisoformat(day)
    best = (NAN, "")
    for month, held, pledged in directors:
        seen = date(int(month[:4]), int(month[4:6]), 1) + timedelta(days=DIRECTORS_LAG_DAYS)
        if seen > d0:
            break
        if not isnan(held) and held > 0 and not isnan(pledged):
            best = (pledged / held, month)
    return best


class QualityBook:

    def __init__(self, statements: dict, directors: dict, news=None):
        self.statements = statements
        self.directors = directors
        self.news = news
        self._timeline: dict[str, list[tuple[str, tuple[int, int]]]] = {}
        self._cache: dict[tuple[str, tuple[int, int]], tuple[list[str], list[str]]] = {}
        for code, stmts in statements.items():
            self._timeline[code] = sorted((available_from(*yq), yq) for yq in stmts)

    def latest_quarter(self, code: str, day: str) -> tuple[int, int] | None:
        best = None
        for avail, yq in self._timeline.get(code, []):
            if avail <= day:
                best = yq
            else:
                break
        return best

    def verdict(self, code: str, day: str) -> Verdict | None:
        yq = self.latest_quarter(code, day)
        if yq is None:
            return None
        key = (code, yq)
        if key not in self._cache:
            self._cache[key] = quarter_flags(self.statements[code], yq)
        flags, details = list(self._cache[key][0]), list(self._cache[key][1])
        ratio, month = pledge_ratio_asof(self.directors.get(code, []), day)
        if not isnan(ratio) and ratio > PLEDGE_HIGH:
            flags.append("pledge")
            details.append(f"{month[:4]}/{month[4:]} 董監質押比 {ratio:.0%}")
        extra = 0
        if self.news is not None:
            from .news import FLAG_RULES  # noqa: PLC0415

            for flag, d, subject in self.news.flags(code, day):
                flags.append(f"news_{flag}")
                details.append(f"{d} 重訊：{subject[:40]}")
                extra += FLAG_RULES[flag]["weight"] - 1
        return Verdict(f"{yq[0] + 1911}Q{yq[1]}", tuple(flags), tuple(details), extra)

    def vetoed(self, code: str, day: str) -> bool:
        v = self.verdict(code, day)
        return bool(v and v.veto)
