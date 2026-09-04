"""全市場官方資料 → :class:`FinancialData`。

這是〔評等清單〕停在一年前的活頁簿快照那件事的另一半。階段 0 把期別放進檔名，
讓 `data/market/` 開始累積歷史；這裡把累積下來的東西讀回來，組成評分引擎吃的
那個資料結構——和 `WorkbookSource`／`GridsSource` 並排的第三條路，差別只在資料
從哪裡來。

三件從**真實檔案**（不是文件）讀出來、而且會改變寫法的事：

1. **官方季報是「累計」，不是「單季」。** 5439 的 115Q2 營業收入是 5,591,086
   仟元；券商鏡像的 2026.2Q 是 3,053 百萬、2026.1Q 是 2,538 百萬——相加正好
   5,591。所以單季必須相減，而且 Q1 不減。上一季沒抓到的時候就沒有單季可算，
   這裡選擇**留空**而不是拿累計數字充當單季：一個混了半年數字的「單季」營益率
   看起來完全正常，錯得無聲無息。

2. **上市與上櫃的欄名不一樣，而且不是整齊地不一樣。** 上市全中文
   （`公司代號`／`年度`／`季別`）；上櫃的損益表是英文
   （`SecuritiesCompanyCode`／`Year`／`Season`），資產負債表卻又是中文的
   `年度`／`季別` 配英文的 `SecuritiesCompanyCode`。所以每個欄位都用一組候選
   名稱去找，不假設一種版面。

3. **官方開放資料的資產負債表沒有「存貨」，也完全沒有現金流量表。** 欄位只到
   流動資產／流動負債／資產總計這種彙總層級。也就是說六大指標裡的**存貨週轉率
   與自由現金流量，這條路拿不到**——不是還沒寫，是來源裡沒有。它們要嘛繼續走
   券商鏡像，要嘛之後從公開資訊觀測站的完整報表取（那是表單 POST 回 HTML，
   **必須先存一份真實回應**才能寫解析器）。

   所以這個來源現在能供應四個指標：營收年增率、營業利益率、稅後淨利年增率、
   每股盈餘。剩下兩個留空，而 `Snapshot.composite` 遇到缺項會整格作廢——這是
   對的行為，不要為了讓表格好看而繞過它。
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..calendar_tw import Quarter
from ..rating.engine import FinancialData

#: 檔名就是期別：`115Q2.csv`、`11507.csv`。
_QUARTER_FILE = re.compile(r"^(\d{3})Q([1-4])$")
_MONTH_FILE = re.compile(r"^(\d{3})(\d{2})$")

#: 同一個意思在兩個交易所有兩個欄名。逐一試，不假設版面。
CODE_KEYS = ("公司代號", "SecuritiesCompanyCode")
#: 簡稱優先：基本資料表的 `公司名稱` 是「臺灣水泥股份有限公司」，而清單上要的是
#: 「台泥」——損益表與月營收表的 `公司名稱` 剛好就是簡稱。
NAME_KEYS = ("公司簡稱", "CompanyAbbreviation", "公司名稱", "CompanyName")
INDUSTRY_KEYS = ("產業別",)

#: 公司基本資料那個「產業別」欄位是**代碼**，不是名稱。只翻譯兩個，理由見
#: :meth:`MarketData.industry`。
INDUSTRY_CODES = {"17": "金融保險業", "91": "存託憑證"}

#: 存託憑證（DR）：原股在境外掛牌，台灣這邊沒有月營收也沒有台灣格式的財報，
#: 所以六大指標一項都算不出來。實測 9136 巨騰-DR 抓了十四張、只差〔營收〕那一張
#: ——而那一張永遠不會有，於是它每一批都被重抓一次。
DR_INDUSTRY = "存託憑證"

REVENUE_KEYS = ("營業收入",)
OPERATING_INCOME_KEYS = ("營業利益（損失）",)
#: 母公司業主的部分才是「稅後淨利」；沒有非控制權益的公司這一欄可能是空的。
NET_INCOME_KEYS = ("淨利（淨損）歸屬於母公司業主", "本期淨利（淨損）")
EPS_KEYS = ("基本每股盈餘（元）",)

MONTH_REVENUE_KEYS = ("營業收入-當月營收",)
MONTH_LAST_YEAR_KEYS = ("營業收入-去年當月營收",)
MONTH_YOY_KEYS = ("營業收入-去年同月增減(%)",)

#: 不適用六大指標的產業。**三種寫法都要認**：
#:
#: * 「金融保險業」——上市月營收表寫的。
#: * 「金融保險」——舊資料裡出現過的短寫。
#: * 「金融業」——**上櫃**月營收表寫的。少了這一個，9 檔券商（5864 致和證、
#:   6015 宏遠證、6016 康和證……）會一路排進補課佇列，而它們的六大指標本來就
#:   不適用。實測那一輪 82 檔失敗裡有 7 檔是它們。
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
    """`data/market/` 底下所有期別，讀一次、查很多次。

    全市場重評是 1,741 次查詢，而每一期只有一個檔案——所以檔案讀進來一次就好，
    照股票代號建索引，之後每一檔只是幾次 dict 查表。這正是「工作單位是一檔股票、
    資料的發布單位是一個期別的全市場」那個落差，在讀取端該有的樣子。
    """

    root: Path
    #: {期別: {代號: 那一列}}
    income: dict[Quarter, dict[str, dict[str, str]]] = field(default_factory=dict)
    balance: dict[Quarter, dict[str, dict[str, str]]] = field(default_factory=dict)
    #: {「115/07」: {代號: 那一列}}
    revenue: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    #: {代號: 上市／上櫃}
    markets: dict[str, str] = field(default_factory=dict)
    #: {代號: 公司簡稱}
    names: dict[str, str] = field(default_factory=dict)
    #: {代號: 公司基本資料那個「產業別」**代碼**}。月營收表查不到產業的時候
    #: （金控、保險、存託憑證都不在那張表裡）退回來問這裡。
    industry_codes: dict[str, str] = field(default_factory=dict)

    # -- 讀取 ---------------------------------------------------------------

    @classmethod
    def load(cls, root: str | Path) -> MarketData:
        data = cls(root=Path(root))
        market = data.root / "market"
        for exchange, label in (("twse", "上市"), ("tpex", "上櫃")):
            for kind, target in (("income", data.income), ("balance", data.balance)):
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
                    # 這張表的「產業別」是代碼（台積電是 24），月營收表那張是
                    # 名稱。同一個欄名，兩種內容——所以分開存，不要混在一起。
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

    # -- 查詢 ---------------------------------------------------------------

    @property
    def quarters(self) -> list[Quarter]:
        """有損益表的期別，新的在前。"""
        return sorted(self.income, reverse=True)

    @property
    def months(self) -> list[str]:
        """有月營收的月份標籤，新的在前。"""
        return sorted(self.revenue, reverse=True)

    def codes(self) -> list[str]:
        """任何一張表裡出現過的股票代號。"""
        seen: set[str] = set(self.markets)
        return sorted(seen)

    def industry(self, code: str) -> str:
        """月營收表帶的是中文產業別；上市公司基本資料帶的是代碼「01」。

        所以產業別問月營收，不問基本資料——同一個欄名，兩種內容。

        **但有一整類公司不在月營收表裡**：金控與保險（沒有「月營收」這種東西）、
        以及存託憑證。它們在這裡問不到產業，於是產業是空字串、`excluded` 是空的，
        補課佇列就一直把它們排進去、一直抓不到。

        所以問不到的時候退回基本資料的**代碼**——只認兩個，而且兩個都是對著真實
        的檔案讀出來的，不是猜的：

        * `17` = 金融保險業。2850 新產（產險）與 2883 凱基金（金控）都是 17。
        * `91` = 存託憑證。9136 巨騰-DR 與 910322 康師傅-DR 都是 91，而它們的
          名字結尾也正好是 `-DR`。

        （對照組：2330 台積電是 `24`，所以這確實是一套代碼而不是別的東西。）

        其餘的代碼不翻譯：這裡要回答的只有「這一檔適不適用六大指標」，把整張
        代碼對照表憑印象寫出來只會多出一堆沒被驗證過的字串。
        """
        for month in self.months:
            row = self.revenue.get(month, {}).get(code)
            if row:
                value = _first(row, INDUSTRY_KEYS)
                if value:
                    return value
        return INDUSTRY_CODES.get(self.industry_codes.get(code, ""), "")

    # -- 組裝 ---------------------------------------------------------------

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
                # 上一季沒抓到就沒有單季可算。拿累計當單季會安靜地錯。
                continue
            revenue = _single(row, previous, REVENUE_KEYS, quarter)
            operating = _single(row, previous, OPERATING_INCOME_KEYS, quarter)
            net = _single(row, previous, NET_INCOME_KEYS, quarter)
            eps = _single(row, previous, EPS_KEYS, quarter)
            if revenue:
                if operating is not None:
                    data.operating_margin[quarter] = round(operating / revenue * 100, 2)
                if net is not None:
                    data.net_margin[quarter] = round(net / revenue * 100, 2)
            if net is not None:
                data.net_income[quarter] = net
            if eps is not None:
                # 累計 EPS 是兩位小數，相減之後的尾數沒有意義。
                data.eps[quarter] = round(eps, 2)

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
        # 〔營收〕AD：一月併進二月，合併那一列的年增率要用一＋二月合計去算，
        # 而不是二月自己的年增率——活頁簿就是這樣做的，這裡照抄。
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
    """累計數字換成單季。Q1 的累計就是單季，其餘要減掉上一季的累計。"""
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
