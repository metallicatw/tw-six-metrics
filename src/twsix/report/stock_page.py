"""One stock, four pages — 〔評價簡表〕〔六大財務指標評等〕〔EPS預估與估價〕〔殖利率估價〕.

The workbook's flow is a single stock at a time: type a code into 〔評價簡表〕
B1, then read across four sheets.  That is the flow this page reproduces, in
the order the 操作說明 sheet gives it, as one document with four sections
rather than four files — the sections are four views of the same fetch, and
splitting them would mean four round trips for the reader to answer one
question.

Everything here is a view model.  No arithmetic happens in the template: a
number that reaches Jinja is already the number the sheet shows, so a wrong
figure is traceable to a function with a test rather than to an expression
buried in markup.

Two things are deliberately *not* silent:

* A model that could not run says which input was missing (``gaps``), because
  a blank section and a section that legitimately has nothing to say look
  identical, and only one of them is a bug.
* 〔EPS預估與估價〕's two warnings and its four 報酬風險比 criteria are rendered
  next to the ratio, never below the fold.  The workbook puts them on the same
  screen as the number for a reason: the ratio is a signal with a season, and
  a reader who sees 3.57 without 「越接近下半年越會失去參考意義」 has been told
  half of what the author wrote.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..ingest.goodinfo import DIRECTORS, HOLDERS
from ..ingest.valuation_source import market_close
from ..models import INDICATOR_LABELS, INDICATOR_ORDER
from . import charts
from .sections import (
    Directors,
    Holders,
    Institutional,
    River,
    Seasonal,
    build_pe_river,
    directors,
    holders,
    institutional,
    profit_seasonality,
    revenue_seasonality,
    statement_figures,
)

#: The five letters that get a coloured badge.  Anything else — 「數據不足」,
#: 「不評分」 — is a sentence, not a grade: it went into a 26px badge whose
#: class matched no rule, so it rendered as dark text on a transparent chip
#: and was invisible in dark mode.  Those read as plain muted text instead.
GRADE_LETTERS = frozenset({"AA", "A", "BB", "B", "C"})

Number = float | None

#: 〔EPS預估與估價〕K17~K23 — 總大EPS、PER動態調整推估法.  Ordered high to low
#: so the row a stock lands in reads as a position on one scale.
REWARD_RISK_RULES: tuple[tuple[str, str, str], ...] = (
    ("> 2", "買進", "報酬風險比大於 2，才有買進的意義"),
    ("0.67 ~ 2", "靜待", "多空不明，靜待股價或預估股價區間之變動"),
    ("< 0.67", "減碼", "考慮減碼或賣出"),
    ("< 0.5", "空頭", "考慮布局空頭部位（更嚴格的門檻為 0.25）"),
)

#: The author's own warnings, verbatim.  They travel with the ratio.
REWARD_RISK_NOTES: tuple[str, ...] = (
    "EPS、PER 與報酬風險比之動態方法，越接近下半年越會失去參考意義。",
    "實務上要先檢視當年度（迄今）之股價高低點是否已出現。",
)

#: 〔操作說明〕's own filter, kept as the author wrote it.
RESEARCH_THRESHOLD = 3.0

#: 〔EPS預估與估價〕 field by field: (欄位, 公式, 活頁簿出處).
#:
#: 每一格都是活頁簿的公式搬過來的，但公式只活在程式的 docstring 裡——讀者看到的
#: 只有數字。一個沒有出處的估值和一個猜出來的估值，在畫面上長得一模一樣，而它們
#: 值得的信任天差地別。這張表把出處放回讀者眼前。
#:
#: 出處寫的是欄位而不是單一儲存格：活頁簿裡每個月一列，欄位才是穩定的座標。
FORECAST_BASIS: tuple[tuple[str, str, str], ...] = (
    (
        "預估成長率",
        "MIN(最近一個月營收年增率, 近六月平均年增率)",
        "〔營收〕K；方法開關在〔EPS預估與估價〕D2"
        "（另有「近三月與近六月孰低」與「近十二月累計年增率」）",
    ),
    (
        "預估營收",
        "去年全年營收 × (1 ＋ 預估成長率)",
        "C 欄 × D 欄 → E 欄。單位百萬元（原始資料是仟元，除以 1000）",
    ),
    (
        "稅後淨利率",
        "近四季稅後淨利率的平均",
        "F 欄；開關在 F16（4季平均／4季最低／當季）",
    ),
    ("預估淨利", "預估營收 × 稅後淨利率", "E 欄 × F 欄 → G 欄（母公司）"),
    ("加權平均股數", "最新一期加權平均股數", "H 欄，單位百萬股"),
    ("預估 EPS", "預估淨利 ÷ 加權平均股數", "G 欄 ÷ H 欄 → I 欄"),
    (
        "近四季 EPS",
        "最近四季 EPS 合計",
        "I2；這也是〔BASIC〕本益比的分母",
    ),
    (
        "本益比高／低點",
        "取最近五個年度（不含當年），各去掉最高與最低的一年，剩下三年平均",
        "〔BASIC2〕J7:M8，去極端值的過程攤在該表第 18／19 列；"
        "開關在 K2（當年度／3年平均／5年平均／當年5年孰低）",
    ),
    (
        "歷年本益比",
        "年度最高價 ÷ 年度 EPS、年度最低價 ÷ 年度 EPS",
        "L2 設為「自行計算」時的算法；設為「公開資訊」則直接取〔BASIC〕的公布值",
    ),
    ("目標價", "本益比高點 × 預估 EPS", "K 欄 × I 欄 → M 欄"),
    ("下檔價", "本益比低點 × 預估 EPS", "L 欄 × I 欄 → N 欄"),
    ("預期報酬", "目標價 ÷ 市價 － 1", "P 欄"),
    ("預期風險", "下檔價 ÷ 市價 － 1", "Q 欄；市價已低於下檔價時記為「無風險」"),
    ("報酬風險比", "｜預期報酬 ÷ 預期風險｜", "R 欄；判斷準則見下方 K17:L21"),
    ("預估本益比", "市價 ÷ 預估 EPS", "AA 欄"),
    (
        "EPS 成長率",
        "(預估 EPS － 近四季 EPS) ÷ ｜近四季 EPS｜",
        "AB 欄；為負時不給 PEG，也不給 PEG 目標價",
    ),
    ("PEG", "預估本益比 ÷ (EPS 成長率 × 100)", "AC 欄"),
    (
        "總報酬本益比",
        "(EPS 成長率 ＋ 平均殖利率) ÷ 預估本益比 × 100",
        "AD 欄；平均殖利率取自〔殖利率估價〕M13",
    ),
)

#: 對帳結果與兩個必須講清楚的差異。放在表格下面，因為它們是「這張表可以信到
#: 什麼程度」，而不是公式本身。
FORECAST_BASIS_NOTES: tuple[str, ...] = (
    "以 5439 對帳：預估成長率、本益比高點、本益比低點三欄與活頁簿自己算出的值"
    "相符到小數第 10 位；預估 EPS 相差 0.03%，因為〔六大財務指標評等〕公布的"
    "稅後淨利率只印到小數兩位，而 Excel 內部用的是未四捨五入的值。",
    "本站預設的本益比基準是「5年平均（排除極端值）」；原始 .xlsm 存檔時 K2 停在"
    "「3年平均」，兩組數字活頁簿都算好了（〔BASIC2〕K 欄與 L 欄）。要切換改"
    "config/settings.toml 的 pe_basis 一行即可，目標價與下檔價會跟著變。",
    "所有估值都是機械式套用活頁簿的公式，不是預測；越接近下半年，動態推估法越"
    "會失去參考意義。",
)


def reward_risk_band(ratio: Number) -> tuple[str, str]:
    """Which of the four criteria this ratio falls in: (label, why)."""
    if ratio is None:
        return ("—", "無報酬風險比")
    if ratio > 2:
        return ("買進", REWARD_RISK_RULES[0][2])
    if ratio < 0.5:
        return ("空頭", REWARD_RISK_RULES[3][2])
    if ratio < 0.67:
        return ("減碼", REWARD_RISK_RULES[2][2])
    return ("靜待", REWARD_RISK_RULES[1][2])


def _change_pct(quote: Any) -> float | None:
    """漲跌幅（%）。分母是前一個交易日的收盤，也就是 `close - change`。

    拿當日收盤當分母是這一類計算最常見的錯：漲得越多、錯得越多，而且永遠是
    低估。漲停板（+10%）用錯分母會算成 9.09%，看起來只是「差一點」。
    """
    if quote is None:
        return None
    close = getattr(quote, "close", None)
    change = getattr(quote, "change", None)
    if close is None or change is None:
        return None
    prev = close - change
    if not prev:
        return None
    return round(change / prev * 100, 2)


@dataclass
class Section:
    """One of the four, with its own id so the nav can link to it."""

    id: str
    title: str
    note: str = ""
    gap: str = ""


@dataclass
class StockPage:
    """Everything the template renders, already computed."""

    stock_id: str
    name: str = ""
    market_price: Number = None
    #: 那個市價是哪一天的收盤價，``YYYY.MM.DD``；說不出來就留空。
    #: 整頁的估值都掛在這個數字上，而一個標錯日期的股價會讓人以為它們比實際新
    #: ——所以寧可不標。判斷方式見 ingest.valuation_source.market_close。
    price_date: str = ""
    #: 那一天的漲跌點數與漲跌幅（%）。來源和 `price_date` 一樣是每日全市場行情，
    #: 不是活頁簿——活頁簿只有一個價格，說不出它比前一天高還是低。
    #: 兩個都可能是 None（沒有每日行情、或那一檔當天沒成交），那時候不顯示。
    price_change: Number = None
    price_change_pct: Number = None
    fiscal_quarter: str = ""
    revenue_month: str = ""
    #: 上市／上櫃，以及產業別。兩個都只是識別，不參與任何計算。
    #:
    #: 放在股名旁邊是因為「2404 漢唐」本身說不出這是一家做什麼的公司——而讀者
    #: 判斷一個營益率是高是低，第一件要知道的事就是它跟誰比。原本要捲到清單頁
    #: 或〔評價簡表〕才看得到產業，而那正是最需要它的那一眼之後。
    market: str = ""
    industry: str = ""
    excluded: str = ""

    periods: list[dict[str, Any]] = field(default_factory=list)
    indicators: list[dict[str, Any]] = field(default_factory=list)
    latest_composite: Number = None
    #: 月營收表：``(月份, 當月營收 百萬, 月增率 %, 年增率 %, 累計營收 百萬,
    #: 累計年增率 %)``，最新在上。金額在這裡就已經換成百萬——版面上一欄十位數
    #: 的仟元讀不出量級，而換算放在模板裡等於每個模板各自記得除以一千一次。
    revenue_rows: list[dict[str, Any]] = field(default_factory=list)

    forecast: dict[str, Any] = field(default_factory=dict)
    #: 目標價試算盤的種子——原始數字，不是格式化過的字串。
    calc: dict[str, Any] = field(default_factory=dict)
    #: 〔EPS預估與估價〕計算方式說明——逐格列出公式與本檔實際代入的數字，
    #: 給展開後的說明區塊用。內容依 settings 目前生效的方法動態產生。
    methodology: dict[str, Any] = field(default_factory=dict)
    pe: dict[str, Any] = field(default_factory=dict)
    growth: dict[str, Any] = field(default_factory=dict)
    dividend: dict[str, Any] = field(default_factory=dict)
    dividend_lag_rows: list[dict[str, Any]] = field(default_factory=list)

    figures: dict[str, str] = field(default_factory=dict)
    gaps: dict[str, str] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    #: The remaining workbook pages — see :mod:`twsix.report.sections`.
    statements: dict[str, str] = field(default_factory=dict)
    river: River | None = None
    news: Any = None
    institutional: Institutional | None = None
    #: Goodinfo 的兩張。唯二不是程式抓的——見 twsix fetch-page --import。
    holders: Holders | None = None
    directors: Directors | None = None
    revenue_season: Seasonal | None = None
    profit_season: Seasonal | None = None
    unbuilt: list[dict[str, str]] = field(default_factory=list)

    @property
    def worth_researching(self) -> bool:
        """〔操作說明〕: 綜合評價 3 分以上才有研究必要."""
        return (
            self.latest_composite is not None
            and self.latest_composite >= RESEARCH_THRESHOLD
        )


def _weekly_closes(reader: Any) -> list[tuple[str, float]]:
    """〔股價(週)〕's close, trimmed to the window the river is drawn over.

    The mirror hands back everything it has — 5439 reaches to 2000 — and the
    first draft plotted all 1347 weeks.  It was legible only in the sense that
    nothing overlapped: twenty-six years of a stock that spent twenty of them
    under 60 and the last three above 200 compresses the whole early history
    into a flat line along the bottom, and the part a reader came for into the
    right-hand eighth of the frame.

    〔河流圖〕's own combo box exists for exactly this and defaults to seven
    years back, so that is the window.  The zones are unaffected — they come
    from the yearly series, which still spans everything the exchange has.
    """
    from ..ingest import weekly_prices  # noqa: PLC0415

    grid = reader.grid(weekly_prices.SHEET) if hasattr(reader, "grid") else []
    if not grid:
        return []
    series = weekly_prices.closes(grid)
    if not series:
        return []
    latest = int(series[-1][0][:4])
    start = latest - weekly_prices.DEFAULT_YEARS + 1
    return [(d, v) for d, v in series if int(d[:4]) >= start]


def _news(reader: Any, extra: Any = None) -> Any:
    """〔個股新聞〕, if it was fetched.  See :mod:`twsix.ingest.news`.

    *extra* 是每日排程從**全市場分類列表**抓回來的那幾則（一天兩次，一個請求換
    一整批）。分頁那一份是關鍵字索引抓的，歷史深但只有按「立即更新」才會換；
    這一份每天新但只涵蓋有上新聞的股票。所以是合併，不是取代——同一篇（同連結）
    只留一次，新的在前。

    分頁沒抓過但每日資料有的那些股票，也會有這一節：那是真的新聞，沒有理由因為
    「還沒有人按過那一檔的更新」就不給看。
    """
    from ..ingest import news as news_mod  # noqa: PLC0415

    grid = reader.grid(news_mod.SHEET) if hasattr(reader, "grid") else []
    items = news_mod.from_grid(grid) if grid else []
    if extra:
        items = news_mod.merge_items(items, list(extra))
    if not items:
        return None
    return news_mod.describe(items)


#: 三年營收趨勢畫幾個月。三年而不是兩年：月營收有明顯的年度季節性，兩個循環
#: 分不出「今年比去年低」和「每年這個月都低」。
REVENUE_MONTHS = 36


#: 評等表上每一列印幾期。
#:
#: 評分的窗口不是這個數字，而且**不可以**是：規則書寫的是「營業利益率看四季」、
#: 「自由現金流量看九季」，每一項各自不同，因為那是規則的一部分。表格上各列長短
#: 不一則是另一回事——讀者橫著掃的時候，一列六格、一列四格，對不齊的那幾格看起來
#: 像是資料缺了。所以顯示的數列另外取，統一八期，取自和評分同一份 FinancialData。
TABLE_PERIODS = 8


def _eight_periods(data: Any, snapshot: Any) -> dict[str, tuple[list[str], list[Number]]]:
    """每一個指標的**顯示**數列：八期，最新在前。

    刻意不從 ``snapshot.indicators[key].values`` 讀——那是評分吃的窗口，長度由
    規則決定（四季、六季、九季各有各的理由）。顯示要的是齊長，而兩者一旦共用
    同一個數字，改版面就會動到評分。這裡直接問 ``FinancialData``，也就是評分
    自己讀的那一份，所以兩邊不可能各說各話。
    """
    if data is None:
        return {}
    out: dict[str, tuple[list[str], list[Number]]] = {}

    # 合併過的那一條（一月併進二月，`115/01-02`），不是 raw。
    #
    # raw 那一條同時留著 `115/01-02` **和** `115/01`，而二月沒有自己的一列——
    # 八格的窗口裡因此會同時出現兩個一月，看起來像資料重複了。合併版一期一格，
    # 而且它正是這一列的等第實際評分的那一條（`revenue_window(0, …)`）。
    months = list(getattr(data, "revenue_months", []) or [])[:TABLE_PERIODS]
    if months:
        out["revenue_yoy"] = (months, [data.revenue_yoy.get(m) for m in months])

    latest = getattr(snapshot, "fiscal_quarter", "") or ""
    quarters = [q for q in getattr(data, "quarters", []) if str(q) <= latest] or list(
        getattr(data, "quarters", [])
    )
    quarters = quarters[:TABLE_PERIODS]
    if not quarters:
        return out
    labels = [str(q) for q in quarters]
    for key, source in (
        ("operating_margin", data.operating_margin),
        ("eps", data.eps),
        ("inventory_turnover", data.inventory_turnover),
        ("free_cash_flow", data.free_cash_flow),
        ("net_margin", data.net_margin),
    ):
        out[key] = (labels, [source.get(q) for q in quarters])
    out["net_income_yoy"] = (
        labels,
        list(data.net_income_yoy(quarters[0], len(quarters))),
    )
    return out


def _pct(value: Number, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:,.{digits}f}%"


def _num(value: Number, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


#: 還沒有資料的頁面，以及缺什麼。
#:
#: 這兩張曾經是「Goodinfo 擋住」的代表作。現在不是了——它們的原始資料是集保
#: 結算所與公開資訊觀測站的開放資料，一次抓整個市場，每週三個請求。Goodinfo
#: 只是把同一份資料整理過而已。
#:
#: 所以缺的不再是「來源不給」，是「這一檔還沒累積到快照」：官方只給最新一期，
#: 歷史要靠每週跑一次長出來。
UNBUILT_PAGES: tuple[tuple[str, str], ...] = (
    (
        HOLDERS,
        "還沒有這一檔的集保股權分散快照。執行 twsix fetch-ownership（一次抓整個"
        "市場，之後每週的排程會自己累積），或用 twsix fetch-page --import 匯入"
        "從 Goodinfo 存下來的歷史",
    ),
    (
        DIRECTORS,
        "還沒有這一檔的董監持股快照。同上：twsix fetch-ownership 會從公開資訊"
        "觀測站抓上市與上櫃兩份，涵蓋全市場",
    ),
)



def _mean(values: Sequence[Any]) -> float | None:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _sigma(values: Sequence[Any]) -> float | None:
    """樣本標準差（n-1）。

    四個點用哪一種除數是有差的：5439 近四季的淨利率，母體式是 1.4%，樣本式是
    1.7%——而參考工具上寫的正是 1.7%。四季是「這家公司的表現」抽出來的四個樣本，
    不是全部，所以樣本式也是對的那一個。
    """
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    m = sum(nums) / len(nums)
    return (sum((x - m) ** 2 for x in nums) / (len(nums) - 1)) ** 0.5


def _calc_seed(reader: Any, stock_id: str, valuation: Any) -> dict[str, Any]:
    """目標價試算盤的起始值。

    每一個預設值都要說得出它從哪裡來——一個試算盤最容易變成的東西，就是一組
    看起來很精確、其實是憑空填的參數。所以三個成長率不是「-6/4/90」這種手寫的
    數字，而是這一檔自己的月營收年增率：最近一個月、近六個月平均、今年以來累計。
    淨利率同理：近四季平均，上下各一個標準差。本益比用估價區間的低／中／高。

    讀者當然可以改——那正是這個盤的用途。但打開的時候看到的是**這一檔的事實**，
    不是別人的假設。
    """
    from ..ingest.valuation_source import read_valuation_input

    try:
        raw = read_valuation_input(reader, stock_id=stock_id)
    except Exception:  # noqa: BLE001 - 少了輸入就沒有試算盤，不影響其他區塊
        return {}

    yoy = [v for v in (raw.monthly_revenue_yoy or ())]
    latest = yoy[0] if yoy else None
    recent6 = _mean(yoy[:6])
    # 「今年以來累計年增率」沒有放進來。
    #
    # 參考工具上有這個數字（5439 是 40.8%），我試著從月營收自己算，換了幾種
    # 視窗長度都對不上——那代表它算的不是我想的那件事，可能是來源自己публ的
    # 累計欄位。對不上就不放：一個看起來很精確、其實來路不明的預設值，比少一個
    # 參考值糟得多，因為它會被當成事實填進試算盤。
    #
    # 「最近月」與「近六月均」是自己算的，而且和參考工具逐位相同（4.5%、43.6%）。
    margins = [v for v in (raw.net_margins or ())][:4]
    avg_margin = _mean(margins)
    sd = _sigma(margins)

    band = valuation.band
    pe_low = band.low if band is not None else None
    pe_high = band.high if band is not None else None
    pe_mid = None if pe_low is None or pe_high is None else (pe_low + pe_high) / 2

    years = []
    from ..ingest.valuation_source import current_roc_year

    try:
        newest = current_roc_year(reader) + 1911
    except Exception:  # noqa: BLE001
        newest = None
    highs = [v for v in (getattr(raw, "price_high", ()) or ())]
    lows = [v for v in (getattr(raw, "price_low", ()) or ())]
    epss = [v for v in (getattr(raw, "annual_eps", ()) or ())]
    phigh = [v for v in (getattr(raw, "pe_high", ()) or ())]
    plow = [v for v in (getattr(raw, "pe_low", ()) or ())]
    # 今年還沒過完，EPS 是空的——那一列在「近四年」的表上只是一行破折號，
    # 佔掉一個本來可以放完整年度的位置。從第一個有 EPS 的年度起算。
    start = next((i for i, v in enumerate(epss) if v is not None), 0)
    for k in range(4):
        i = start + k
        if newest is None or i >= len(highs):
            break
        years.append({
            "year": newest - i,
            "high": highs[i] if i < len(highs) else None,
            "low": lows[i] if i < len(lows) else None,
            "eps": epss[i] if i < len(epss) else None,
            "pe_high": phigh[i] if i < len(phigh) else None,
            "pe_low": plow[i] if i < len(plow) else None,
        })

    return {
        # 年營收：去年全年，仟元 -> 百萬元
        "revenue": None if raw.last_year_revenue is None else raw.last_year_revenue / 1000,
        # 股數：ValuationInput 記的是百萬股 -> 億股
        "shares": None if raw.weighted_shares is None else raw.weighted_shares / 100,
        "price": valuation.market_price,
        "growth": {"latest": latest, "recent6": recent6},
        "margin": {"avg": avg_margin, "sigma": sd},
        "pe": {"low": pe_low, "mid": pe_mid, "high": pe_high},
        "years": years,
    }


#: D2 的三種營收成長率取法，對照 pick_growth() 的邏輯與 〔營收〕欄位出處。
GROWTH_METHOD_LABELS: dict[str, tuple[str, str]] = {
    "1&6": ("最近一月與近六月平均孰低", "MIN(最近一個月年增率, 近六個月平均年增率)"),
    "3&6": ("近三月與近六月平均孰低", "MIN(近三個月平均年增率, 近六個月平均年增率)"),
    "12m": ("近十二月累計年增率", "近十二個月累計營收 ÷ 前十二個月累計營收 − 1"),
}

#: F16 的三種淨利率取法。
MARGIN_METHOD_LABELS: dict[str, tuple[str, str]] = {
    "4q_avg": ("近四季平均", "近四季稅後淨利率的算術平均"),
    "4q_min": ("近四季最低", "近四季稅後淨利率中最保守的一季"),
    "current": ("最近一季", "最近一季（當季）稅後淨利率"),
}

#: K2 的四種本益比區間取法，對照 PeBand.from_history() 的規則。
PE_BASIS_LABELS: dict[str, tuple[str, str]] = {
    "current_year": ("當年度", "只取最近一個完整年度的最高／最低本益比"),
    "avg_3y": (
        "3年平均（排除極端值後）",
        "五年窗格先各丟掉一個最高與一個最低年度，剩下的三年中取最近三年平均",
    ),
    "avg_5y": (
        "5年平均（排除極端值後）",
        "近五個完整年度中，各丟掉一個最高與一個最低年度，剩下三年平均",
    ),
    "min_current_5y": ("當年與5年平均孰低", "取「當年度」與「5年平均（排除極端值）」兩者中較低的一個"),
}


def _methodology(valuation: Any, settings: Any) -> dict[str, Any]:
    """組出〔EPS預估與估價〕說明區塊要用的文字與數字，全部帶真實代入值。

    不在模板裡算——模板只認得已經算好的字串，這樣一個說明文字錯了，
    可以直接對到這個函式，而不是散在 Jinja 運算式裡。
    """
    f = getattr(settings, "forecast", None)
    growth_method = getattr(f, "revenue_growth_method", "1&6")
    margin_method = getattr(f, "margin_method", "4q_avg")
    pe_basis = getattr(f, "pe_basis", "avg_5y")

    g_label, g_formula = GROWTH_METHOD_LABELS.get(growth_method, ("—", "—"))
    m_label, m_formula = MARGIN_METHOD_LABELS.get(margin_method, ("—", "—"))
    p_label, p_formula = PE_BASIS_LABELS.get(pe_basis, ("—", "—"))

    row = valuation.forecast
    band = valuation.band
    pe_view = valuation.pe_view

    return {
        "growth_method_label": g_label,
        "growth_method_formula": g_formula,
        "growth_rate": _pct(row.growth_rate) if row else "—",
        "last_year_revenue": _num(row.last_year_revenue / 1000, 1) if row else "—",
        "projected_revenue": _num(row.projected_revenue, 1) if row else "—",
        "margin_method_label": m_label,
        "margin_method_formula": m_formula,
        "net_margin": _pct(row.net_margin) if row else "—",
        "projected_income": _num(row.projected_income, 1) if row else "—",
        "weighted_shares": _num(row.weighted_shares, 0) if row else "—",
        "forecast_eps": _num(row.eps) if row else "—",
        "pe_basis_label": p_label,
        "pe_basis_formula": p_formula,
        "band_low": _num(band.low) if band else "—",
        "band_high": _num(band.high) if band else "—",
        "target_price": _num(pe_view.target_price) if pe_view else "—",
        "downside_price": _num(pe_view.downside_price) if pe_view else "—",
    }


def build_page(
    rating: Any,
    valuation: Any,
    reader: Any,
    *,
    data: Any = None,
    sheets_present: Sequence[str] = (),
    settings: Any = None,
    quote: Any = None,
    inst_days: Any = None,
    #: 這一檔最近 20 個交易日的收盤（`store.daily.close_history` 的一段）。
    #: 〔外資投信〕那兩張圖下面接的股價走勢用它；沒有就不畫那一格。
    closes: Any = None,
    news_items: Any = None,
) -> StockPage:
    """Assemble the four sections from one rating and one valuation.

    ``reader`` is the same :class:`~twsix.ingest.valuation_source.CellReader`
    the valuation was built from, so the page can show the raw series behind a
    number (月營收, 歷年股利) without a second source of truth.
    """
    from ..ingest.valuation_source import (
        annual_eps,
        current_roc_year,
        dividends,
        quarterly_eps,
        revenue_detail,
        yearly_prices,
    )

    page = StockPage(
        stock_id=rating.stock_id or valuation.stock_id,
        name=rating.name or valuation.name,
        market_price=valuation.market_price,
        # 有每日全市場行情就用它的日期；沒有才退回從分頁推出來的那一個。
        price_date=quote.label if quote is not None else market_close(reader)[1],
        price_change=getattr(quote, "change", None) if quote is not None else None,
        # 漲跌幅要用「前一天的收盤」當分母，也就是 close - change。
        # 拿 close 當分母是常見的錯，漲得越多錯得越多。
        price_change_pct=_change_pct(quote),
        excluded=getattr(rating, "excluded", "") or "",
        # 兩個來源都問過：評等那一份（來自 ratings.csv）和 FinancialData。
        # 先問 rating 是因為個股頁多半是從清單點進來的，那一份一定有值。
        market=(getattr(rating, "market", "") or getattr(data, "market", "") or ""),
        industry=(getattr(rating, "industry", "") or getattr(data, "industry", "") or ""),
        gaps=dict(valuation.gaps or {}),
    )

    # -- 評價簡表 ---------------------------------------------------------
    for i, snap in enumerate(rating.snapshots):
        page.periods.append(
            {
                "index": i + 1,
                "quarter": snap.fiscal_quarter,
                "month": snap.revenue_month,
                "grades": {
                    k: {
                        "text": snap.indicators[k].letter or "—",
                        "badge": snap.indicators[k].letter in GRADE_LETTERS,
                    }
                    for k in INDICATOR_ORDER
                },
                "composite": snap.composite_display,
                # 3.166666667 is what the sheet stores; two places is what a
                # reader compares.  The full value stays in the cell's title.
                "composite_short": (
                    f"{snap.composite:.2f}"
                    if snap.composite is not None
                    else snap.composite_display
                ),
                "value_pick": False,
            }
        )
    picks = rating.value_picks()
    for row, pick in zip(page.periods, picks, strict=False):
        row["value_pick"] = bool(pick)
    if rating.snapshots:
        newest = rating.snapshots[0]
        page.fiscal_quarter = newest.fiscal_quarter
        page.revenue_month = newest.revenue_month
        page.latest_composite = newest.composite

    # -- 六大財務指標評等 -------------------------------------------------
    if rating.snapshots:
        newest = rating.snapshots[0]
        shown = _eight_periods(data, newest)
        for key in INDICATOR_ORDER:
            result = newest.indicators[key]
            labels, values = shown.get(
                key, (list(result.periods or ()), list(result.values or ()))
            )
            page.indicators.append(
                {
                    "key": key,
                    "label": INDICATOR_LABELS[key],
                    "letter": result.letter,
                    "badge": result.letter in GRADE_LETTERS,
                    "display": result.display,
                    "reason": result.reason,
                    "scored": True,
                    # 最新在**左**，和這一頁上每一張表一致（圖則是最新在右）。
                    # 表用來查一個數字，而讀者要查的多半是最新那一期；圖用來看
                    # 走勢，而走勢的方向在時間往右跑的時候才是對的。兩種排法各
                    # 有各的理由，混在同一頁上才是錯的——所以整站只有這一條規則。
                    "values": [
                        None if v is None else round(float(v), 2) for v in values
                    ],
                    "periods": list(labels),
                }
            )
        # 第七列：淨利率（歸母）。**不評分**——六大指標是六個，多一個等第就是
        # 多一條沒有人訂過的規則。它在這裡是因為上一列（自由現金流量）與再上面
        # 那兩列（稅後淨利年增率、EPS）都是「賺多少」，而這一列回答的是「賺得
        # 有多厚」，而那正是前三列單獨看不出來的事。
        margin = shown.get("net_margin")
        if margin and any(v is not None for v in margin[1]):
            page.indicators.append(
                {
                    "key": "net_margin",
                    "label": "淨利率（歸母）",
                    "letter": "",
                    "badge": False,
                    "display": "—",
                    "reason": "不列入評分；歸屬母公司稅後淨利 ÷ 營收",
                    "scored": False,
                    "values": [
                        None if v is None else round(float(v), 2) for v in margin[1]
                    ],
                    "periods": list(margin[0]),
                }
            )

        # 八季財報趨勢：兩條率（左軸 %）＋ EPS（右軸 元）。
        #
        # 這三條放在同一張圖上，是因為它們三個合起來才回答得了「這家公司賺的錢
        # 是不是變好賺了」：營業利益率是本業的厚度、淨利率（歸母）是扣完業外與
        # 少數股權之後真正留給股東的厚度，而 EPS 是那個厚度乘上規模的結果。
        # 兩條率同一個刻度所以比得出「業外吃掉多少」，EPS 是另一個單位，只能給
        # 它自己的軸——而右軸的刻度、長條、圖例三個同色就是在講這件事。
        rates = shown.get("operating_margin")
        margins = shown.get("net_margin")
        eps_q = shown.get("eps")
        if rates and eps_q and any(v is not None for v in eps_q[1]):
            page.figures["eight_quarters"] = charts.combo(
                rates[0],
                bar=("EPS", eps_q[1]),
                lines=[
                    ("營業利益率", rates[1], "var(--m1)"),
                    *(
                        [("淨利率（歸母）", margins[1], "var(--m2)")]
                        if margins
                        else []
                    ),
                ],
                title="八季財報趨勢",
                bar_unit=" 元",
                bar_digits=2,
                bar_colour="var(--price)",
                bar_axis="right",
                line_unit="%",
                line_digits=2,
                label_every=1,
                note="註：淨利率（歸母）＝ 歸屬母公司稅後淨利 ÷ 營收。",
            )

    # -- charts -----------------------------------------------------------
    #
    # 月營收與它的年增率畫在同一張圖上，兩條軸。
    #
    # 原本是上下兩格，理由寫在 charts.py 開頭：兩個刻度的交叉點沒有意義。那個
    # 理由沒有錯，但它擋掉的是這張圖唯一要回答的問題——「營收在跌的那幾個月，
    # 年增率是不是也翻負了」。分成兩格之後，要回答它得在兩格之間來回對垂直位置。
    # 交叉點仍然沒有意義，所以圖例寫明哪一條看哪一軸，下面的表兩組數字都列。
    every_month = revenue_detail(reader)
    #: 〔營收季節性〕吃的是**整段**歷史（每個月佔當年的比重），不是畫在圖上的
    #: 那三年——三年只有三個樣本，平均出來的季節性是噪音。
    months = [(row[0], row[1]) for row in every_month if row[1] is not None]
    detail = every_month[:REVENUE_MONTHS]
    if detail:
        page.figures["revenue"] = charts.combo(
            [row[0] for row in detail],
            # 仟元 → 百萬。十位數的仟元在座標軸上只剩一團 0。
            bar=("月營收", [None if r[1] is None else r[1] / 1000 for r in detail]),
            lines=[("年增率", [r[3] for r in detail], "var(--m0)")],
            title="三年營收趨勢",
            bar_unit=" 百萬",
            bar_digits=0,
            bar_colour="var(--m1)",
            bar_axis="left",
            line_unit="%",
            line_digits=1,
            # 間隔算出來，不是寫死的——目的是讓**最後一格**剛好落在間隔上。
            #
            # `_x_labels` 會強制印最新那一格，但它跟前一格太近就會被讓掉；三十六
            # 個月配 every=3 正好是這個情形，於是整張圖唯一沒有標籤的就是最右邊
            # 那一根，也就是讀者最想確認的「現在在哪裡」。(n-1)//7 讓最後一格必定
            # 對齊，而且期數變少時它自己會縮。
            label_every=max(1, (len(detail) - 1) // 7),
        )
        page.revenue_rows = [
            {
                "month": row[0],
                "revenue": None if row[1] is None else row[1] / 1000,
                "mom": row[2],
                "yoy": row[3],
                "cumulative": None if row[4] is None else row[4] / 1000,
                "cumulative_yoy": row[5],
            }
            for row in detail
        ]
    # 〔營收〕AD/AE（一月併入二月）是**評分**吃的那一條，和上面那張圖的 A/E 不是
    # 同一組標籤。它跟著評等走，所以留在六大指標那一段裡（statement_figures）。
    eps_series = quarterly_eps(reader)[:20]
    if eps_series:
        page.figures["eps"] = charts.bars(
            [q for q, _ in eps_series],
            [v for _, v in eps_series],
            title="單季 EPS",
            unit=" 元",
            digits=2,
            label_every=2,
        )

    # -- EPS預估與估價 ----------------------------------------------------
    if valuation.forecast is not None:
        row = valuation.forecast
        page.forecast = {
            "revenue_month": row.revenue_month,
            "growth_rate": _pct(row.growth_rate),
            "projected_revenue": _num(row.projected_revenue, 0),
            "net_margin": _pct(row.net_margin),
            "projected_income": _num(row.projected_income, 0),
            "weighted_shares": _num(row.weighted_shares, 0),
            "eps": _num(row.eps),
            "trailing_eps": _num(valuation.trailing_eps),
        }
        page.methodology = _methodology(valuation, settings)
    page.calc = _calc_seed(reader, page.stock_id, valuation)

    if valuation.pe_view is not None and valuation.band is not None:
        view = valuation.pe_view
        label, why = reward_risk_band(view.reward_risk)
        page.pe = {
            "band_low": _num(valuation.band.low),
            "band_high": _num(valuation.band.high),
            "target": _num(view.target_price),
            "downside": _num(view.downside_price),
            "expected_return": _pct(view.expected_return),
            "expected_risk": "無風險" if view.risk_free else _pct(view.expected_risk),
            "reward_risk": "—" if view.reward_risk is None else f"{view.reward_risk:,.2f}",
            "verdict": label,
            "verdict_why": why,
        }
        page.figures["pe_band"] = charts.price_band(
            [("下檔", view.downside_price), ("目標", view.target_price)],
            view.market_price,
            title="本益比估價區間",
            scale="range",
        )
    if valuation.growth_view is not None:
        g = valuation.growth_view
        page.growth = {
            "forward_pe": _num(g.forward_pe),
            "eps_growth": _pct(g.eps_growth),
            "peg": "—" if g.peg is None else _num(g.peg),
            "total_return": "—" if g.total_return is None else _num(g.total_return),
            "peg_prices": {k: _num(v) for k, v in sorted(g.peg_prices.items())},
            "total_return_prices": {
                k: _num(v) for k, v in sorted(g.total_return_prices.items())
            },
        }

    # -- 殖利率估價 -------------------------------------------------------
    if valuation.yield_view is not None:
        y = valuation.yield_view
        page.dividend = {
            "dividend": _num(y.dividend),
            "payout_ratio": _pct(y.payout_ratio, 1),
            "cheap": _num(y.cheap),
            "fair": _num(y.fair),
            "expensive": _num(y.expensive),
            "current_yield": _pct(y.current_yield) if y.current_yield else "—",
            "verdict": (
                y.verdict(valuation.market_price)
                if valuation.market_price is not None
                else "—"
            ),
        }
        page.figures["yield_band"] = charts.price_band(
            [("便宜", y.cheap), ("合理", y.fair), ("昂貴", y.expensive)],
            valuation.market_price,
            title="殖利率估價區間",
        )

    # 〔殖利率估價〕70~76 列：把「發放年」與「盈餘年」並排，是股利遞延一年
    # 最直接的證據，也是這條規則唯一看得見的地方。
    years, p_hi, p_lo, p_avg = yearly_prices(reader, current_roc_year(reader))
    cash = dividends(reader, years)
    for i, year in enumerate(years[:12]):
        page.dividend_lag_rows.append(
            {
                "year": year,
                "high": _num(p_hi[i]) if i < len(p_hi) else "—",
                "low": _num(p_lo[i]) if i < len(p_lo) else "—",
                "avg": _num(p_avg[i]) if i < len(p_avg) else "—",
                "cash_earned": _num(cash[i]) if i < len(cash) else "—",
                "cash_paid": _num(cash[i + 1]) if i + 1 < len(cash) else "—",
            }
        )

    # -- 財報圖表 / 河流圖 / 季節性 / 評等預估 ------------------------------
    if data is not None:
        page.statements = statement_figures(data)
    page.revenue_season = revenue_seasonality(months)
    page.profit_season = profit_seasonality(quarterly_eps(reader))

    low_q = getattr(getattr(settings, "forecast", None), "river_low_percentile", 0.025)
    high_q = getattr(getattr(settings, "forecast", None), "river_high_percentile", 0.975)
    annual = annual_eps(reader, years)
    page.river = build_pe_river(
        p_avg,
        annual,
        market_price=valuation.market_price,
        current_eps=valuation.trailing_eps,
        low_q=low_q,
        high_q=high_q,
        weekly=_weekly_closes(reader),
        quarterly=quarterly_eps(reader),
    )
    inst_grid = reader.grid("三大法人") if hasattr(reader, "grid") else []
    # 每日排程抓回來的全市場三大法人買賣超。券商鏡像那張分頁只有按「立即更新」
    # 才會重抓，而這一份每個交易日收盤後自己就有了——合併規則見 `institutional`。
    page.institutional = institutional(inst_grid, inst_days, closes)
    page.news = _news(reader, news_items)

    # Goodinfo 的兩張：有就畫，沒有就在〔尚未建置〕裡說為什麼。匯進來之後那
    # 一頁的理由就不再適用了，所以清單是算出來的，不是寫死的。
    grid = reader.grid if hasattr(reader, "grid") else (lambda _n: [])
    # 〔大戶持股〕圖下面那一格股價走勢的資料在**另一張分頁**（股價(週)）——
    # 大戶持股那張表只有持股比例，沒有價。
    from ..ingest import weekly_prices  # noqa: PLC0415

    page.holders = holders(grid(HOLDERS), weekly_prices.closes(grid(weekly_prices.SHEET)))
    page.directors = directors(grid(DIRECTORS))
    have = {HOLDERS: page.holders, DIRECTORS: page.directors}
    page.unbuilt = [
        {"name": n, "why": w} for n, w in UNBUILT_PAGES if not have.get(n)
    ]

    page.sources = [
        {"sheet": name, "ok": name in set(sheets_present)}
        for name in (
            "FRQ", "CFQ", "ISQ", "BSQ", "BASIC", "營收", "OPQ", "EPQ", "股利",
            "三大法人", "年財務比率", "年度交易資訊_上市櫃合併_",
            "股價(週)", "個股新聞", HOLDERS, DIRECTORS,
        )
    ]
    return page
