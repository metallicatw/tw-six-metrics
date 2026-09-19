"""端點少一欄的時候，要有一條具名的測試變紅。

## 這條測試是補上一個已經宣告過、但不存在的保護

`ingest/twse.py` 的 module docstring 寫著：

    Endpoint contracts live in ``ENDPOINTS`` so a change on the exchange's
    side shows up as one failing contract test naming the endpoint, rather
    than as silently empty data three layers downstream.

那條測試不存在。`CONTRACT_KEYS` 這個 dict 從頭到尾沒有任何程式讀它——而它自己
也已經和現實脫節了，三處：

* `twse.balance` 宣告有「存貨」。實際的開放資料早就沒有這一欄（
  `ingest/market.py` 的 docstring 也是這樣寫的），所以**存貨周轉率永遠是空的**。
  兩份文件互相矛盾了不知道多久，因為沒有人在對。
* `tpex.company` 宣告「公司代號」「公司名稱」。櫃買那張表整張是英文欄名
  （`SecuritiesCompanyCode`、`CompanyAbbreviation`），一欄都對不上。
* `tpex.income`／`tpex.balance` 同上。

櫃買那三處之所以沒有造成災難，是因為讀取端 `market.CODE_KEYS` 本來就同時認
兩種拼法。也就是說：**端點真的改過名，而唯一記著這件事的地方是讀取端的別名
列表，不是那份號稱是契約的 dict。**

## 所以這裡驗兩件事

1. `CONTRACT_KEYS` 對得上 repo 裡真實的檔案（能離線驗的那幾張）。
2. **讀取端要的每一個欄位**，在 `data/market/` 底下每一期的檔案裡都找得到。
   這一條才是「端點少一欄當場紅」：欄名是從 `ingest/market.py` 自己的
   `*_KEYS` 常數讀出來的，所以它不會和程式脫節——脫節的那一份就是上面那個
   dict 的下場。

## 為什麼有些不驗

存下來的檔案不一定是端點原樣：

* `income`／`balance` 現在由公開資訊觀測站的**彙總報表**寫（見
  `test_statement_provenance.py`），欄名是 MOPS 的，不是開放資料的。拿它去驗
  開放資料的契約會驗到另一個端點。
* `stock_day_all` 存下來之前先正規化成 `date/code/market/close/...`。
* `dividend` 目前沒有任何一份存檔。

這三種在下面 `UNCHECKABLE` 裡各自寫明理由，而且**漏寫會紅**——新增一個端點
卻沒決定它怎麼驗，就是下一個「宣告了但不存在的保護」。
"""

from __future__ import annotations

import csv
from pathlib import Path

from twsix.ingest import market, tpex, twse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

#: 契約項目 → repo 裡對得上的檔案（相對 `data/`）。glob 的話取最新的那一份。
CHECKABLE: dict[tuple[str, str], str] = {
    ("twse", "company"): "twse_companies.csv",
    ("tpex", "company"): "tpex_companies.csv",
    ("twse", "revenue"): "market/twse_revenue/*.csv",
    ("tpex", "revenue"): "market/tpex_revenue/*.csv",
}

#: 不能離線驗的，連同理由。理由是給下一個人看的，不是給測試看的。
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


# ── 一、契約對得上真實的檔案 ────────────────────────────────────────────


def test_契約宣告的欄位在真實檔案裡都在():
    """`CONTRACT_KEYS` 不是註解，是可以驗的東西——這裡就驗它。

    這一條紅的意思是：端點改了欄名，或者那份 dict 寫錯了。兩種都要有人看。
    """
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
    """驗不了可以，沒決定不行。

    新增一個端點卻兩邊都沒寫，就是下一個「docstring 說有測試、實際上沒有」。
    反過來，`UNCHECKABLE` 裡留著一個已經不存在的端點也要紅——理由會慢慢變成
    謊話，而謊話沒有人會去刪。
    """
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


# ── 二、讀取端要的欄位，每一期都要在 ───────────────────────────────────


#: `ingest/market.py` 自己的別名列表——從那邊讀，不要在這裡抄一份。抄一份的
#: 下場就是 `CONTRACT_KEYS` 現在這個樣子。
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

#: 資產負債表**沒有任何人讀**：`MarketData.balance` 讀進記憶體之後就沒有下文了。
#: 唯一想要它的是存貨周轉率，而存貨那一欄兩條路都沒有。所以這裡不列欄位——
#: 列了就是再宣告一次不存在的保護。等哪天存貨有了來源，這一行連同那個指標
#: 一起復活。
BALANCE_HAS_NO_READER = True


def test_存貨還是沒有來源():
    """這一條紅的時候是**好消息**：存貨有來源了，存貨周轉率可以復活。

    現在的狀況是三份文件各說各話過：`ingest/market.py` 說沒有、
    `ingest/mops_summary.py` 說整個彙總報表家族都沒有、而 `CONTRACT_KEYS` 說
    資產負債表有一欄叫「存貨」。前兩份是對的。既然那個指標是因為這件事而長期
    留白，就把它釘成一條會自己說話的測試，而不是三段註解。
    """
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
    """端點少一欄、改一個字，這裡當場紅——而且訊息會說是哪一期哪一張表。

    對**每一期**驗而不是只驗最新的一期：舊的期別是回補寫的，走的是另一條路，
    而兩條路曾經寫出過不同的欄名（見 `test_statement_provenance.py`）。
    """
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
    """欄名還在、但整欄變成空的——這是改版最安靜的一種。

    2330 在上市、5439 在上櫃，兩檔都是一般業（金融股在彙總報表的另一張表上，
    那張表本來就沒有「營業收入」，所以不能拿它們來驗）。
    """
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
