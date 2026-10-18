
from __future__ import annotations

import csv
from pathlib import Path

from twsix.ingest import market, tpex, twse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CHECKABLE: dict[tuple[str, str], str] = {
    ("twse", "company"): "twse_companies.csv",
    ("tpex", "company"): "tpex_companies.csv",
    ("twse", "revenue"): "market/twse_revenue/*.csv",
    ("tpex", "revenue"): "market/tpex_revenue/*.csv",
}

UNCHECKABLE: dict[tuple[str, str], str] = {
    ("twse", "income"): "存下來的那一份由 MOPS 彙總報表寫，欄名不是開放資料的",
    ("twse", "balance"): "同上",
    ("tpex", "income"): "同上",
    ("tpex", "balance"): "同上",
    ("twse", "stock_day_all"): "存檔前已經正規化成 date/code/market/close",
    ("twse", "dividend"): "目前沒有任何一份存檔",
}


def _header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def _newest(pattern: str) -> Path | None:
    if "*" in pattern:
        matches = sorted(DATA.glob(pattern))
        return matches[-1] if matches else None
    target = DATA / pattern
    return target if target.exists() else None


def _modules():
    return (("twse", twse), ("tpex", tpex))




def test_契約宣告的欄位在真實檔案裡都在():
    problems: list[str] = []
    for label, module in _modules():
        for key, wanted in module.CONTRACT_KEYS.items():
            pattern = CHECKABLE.get((label, key))
            if pattern is None:
                continue
            path = _newest(pattern)
            if path is None:
                problems.append(f"{label}.{key}：說要驗 {pattern}，但檔案不在")
                continue
            have = set(_header(path))
            missing = [k for k in wanted if k not in have]
            if missing:
                problems.append(
                    f"{label}.{key}（{path.name}）少了 {missing}；"
                    f"實際的欄名是 {sorted(have)[:6]}…"
                )
    assert not problems, "\n".join(problems)


def test_每一個端點都決定過怎麼驗():
    for label, module in _modules():
        declared = set(module.CONTRACT_KEYS)
        decided = {k for (m, k) in CHECKABLE if m == label}
        decided |= {k for (m, k) in UNCHECKABLE if m == label}
        assert not declared - decided, (
            f"{label}：{sorted(declared - decided)} 有寫契約但沒決定怎麼驗"
        )
        assert not decided - declared, (
            f"{label}：{sorted(decided - declared)} 在 CHECKABLE／UNCHECKABLE 裡，"
            "但 CONTRACT_KEYS 已經沒有它了"
        )


def test_不能離線驗的都要有理由():
    for (label, key), why in UNCHECKABLE.items():
        assert why.strip(), f"{label}.{key} 的理由是空的"




READER_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "income": {
        "代號": market.CODE_KEYS,
        "名稱": market.NAME_KEYS,
        "營業收入": market.REVENUE_KEYS,
        "營業利益": market.OPERATING_INCOME_KEYS,
        "稅後淨利": market.NET_INCOME_KEYS,
        "每股盈餘": market.EPS_KEYS,
        "業外損益": market.NON_OPERATING_KEYS,
        "稅前淨利": market.PRETAX_INCOME_KEYS,
    },
    "cashflow": {
        "代號": market.CODE_KEYS,
        "營業活動": market.CF_OPERATING_KEYS,
        "投資活動": market.CF_INVESTING_KEYS,
    },
    "revenue": {
        "代號": market.CODE_KEYS,
        "當月營收": market.MONTH_REVENUE_KEYS,
        "去年當月": market.MONTH_LAST_YEAR_KEYS,
        "去年同月增減": market.MONTH_YOY_KEYS,
    },
}

BALANCE_HAS_NO_READER = True


def test_存貨還是沒有來源():
    for label, module in _modules():
        for key, wanted in module.CONTRACT_KEYS.items():
            assert "存貨" not in wanted, (
                f"{label}.{key} 又宣告有「存貨」了。真的有的話請一起把"
                "`rating/indicators.py` 的存貨周轉率接回去，不要只改這個 dict"
            )
    found: list[str] = []
    for exchange in ("twse", "tpex"):
        folder = DATA / "market" / f"{exchange}_balance"
        for path in sorted(folder.glob("*.csv")):
            if any("存貨" in c for c in _header(path)):
                found.append(f"{exchange}_balance/{path.name}")
    assert not found, (
        "資產負債表裡出現「存貨」了：" + "、".join(found) +
        "。存貨周轉率可以不用再留白——去看 `rating/indicators.py`"
    )


def test_每一期的檔案都帶著讀取端要的欄位():
    problems: list[str] = []
    checked = 0
    for kind, groups in READER_KEYS.items():
        for exchange in ("twse", "tpex"):
            folder = DATA / "market" / f"{exchange}_{kind}"
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.csv")):
                have = set(_header(path))
                checked += 1
                for what, aliases in groups.items():
                    if not any(a in have for a in aliases):
                        problems.append(
                            f"{exchange}_{kind}/{path.name}：找不到「{what}」"
                            f"（試過 {list(aliases)}）"
                        )
    assert checked, "一個期別檔案都沒讀到——路徑寫錯了？"
    assert not problems, f"檢查了 {checked} 份檔案：\n" + "\n".join(problems)


def test_一般業那兩檔真的取得到數字():
    for exchange, code in (("twse", "2330"), ("tpex", "5439")):
        folder = DATA / "market" / f"{exchange}_income"
        paths = sorted(folder.glob("*.csv"))
        assert paths, f"{folder} 底下沒有任何一期"
        path = paths[-1]
        with path.open(encoding="utf-8", newline="") as fh:
            row = next(
                (r for r in csv.DictReader(fh)
                 if market._first(r, market.CODE_KEYS) == code), None)
        assert row, f"{path.name} 裡找不到 {code}"
        for what, aliases in (("營業收入", market.REVENUE_KEYS),
                              ("營業利益", market.OPERATING_INCOME_KEYS),
                              ("每股盈餘", market.EPS_KEYS)):
            assert market._num(row, aliases) is not None, (
                f"{path.name} 的 {code} 取不到「{what}」——欄位還在，值是空的"
            )
