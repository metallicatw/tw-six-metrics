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
    fiscal_quarter: str = ""
    revenue_month: str = ""
    excluded: str = ""

    periods: list[dict[str, Any]] = field(default_factory=list)
    indicators: list[dict[str, Any]] = field(default_factory=list)
    latest_composite: Number = None

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


def _news(reader: Any) -> Any:
    """〔個股新聞〕, if it was fetched.  See :mod:`twsix.ingest.news`."""
    from ..ingest import news as news_mod  # noqa: PLC0415

    grid = reader.grid(news_mod.SHEET) if hasattr(reader, "grid") else []
    if not grid:
        return None
    return news_mod.describe(news_mod.from_grid(grid))


def _merged_yoy(reader: Any) -> list[tuple[str, Number]]:
    """〔營收〕AD/AE — the labelled series the rating engine grades."""
    from ..ingest.valuation_source import REVENUE

    out: list[tuple[str, Number]] = []
    for row in reader.row_numbers(REVENUE):
        label = reader.text(REVENUE, "AD", row).strip()
        if label:
            out.append((label, reader.num(REVENUE, "AE", row)))
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
        monthly_revenue,
        quarterly_eps,
        yearly_prices,
    )

    page = StockPage(
        stock_id=rating.stock_id or valuation.stock_id,
        name=rating.name or valuation.name,
        market_price=valuation.market_price,
        # 有每日全市場行情就用它的日期；沒有才退回從分頁推出來的那一個。
        price_date=quote.label if quote is not None else market_close(reader)[1],
        excluded=getattr(rating, "excluded", "") or "",
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
        for key in INDICATOR_ORDER:
            result = newest.indicators[key]
            page.indicators.append(
                {
                    "key": key,
                    "label": INDICATOR_LABELS[key],
                    "letter": result.letter,
                    "badge": result.letter in GRADE_LETTERS,
                    "display": result.display,
                    "reason": result.reason,
                    # Reversed, both of them, together: the row reads left to
                    # right like every chart on the page, and the labels stay
                    # welded to their own numbers.
                    "values": [
                        None if v is None else round(float(v), 2)
                        for v in reversed(result.values or ())
                    ],
                    "periods": list(reversed(result.periods or ())),
                }
            )

    # -- charts -----------------------------------------------------------
    months = monthly_revenue(reader)
    if months:
        window = months[:24]
        labels = [m for m, _ in window]
        page.figures["revenue"] = charts.bars(
            labels, [v for _, v in window], title="月營收", unit=" 仟元", digits=0
        )
    # 〔營收〕AD/AE rather than A/B: the graded series folds January into
    # February, so its labels are not the same list as the revenue bars'.
    # Drawing them on one frame would need two y scales, which is the one
    # chart form this project refuses — they are two stacked panels instead.
    merged = _merged_yoy(reader)[:24]
    if merged:
        page.figures["revenue_yoy"] = charts.line(
            [label for label, _ in merged],
            [None if v is None else float(v) * 100 for _, v in merged],
            title="月營收年增率（1-2月合併）",
            unit="%",
            digits=1,
        )
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
    page.institutional = institutional(inst_grid, inst_days)
    page.news = _news(reader)

    # Goodinfo 的兩張：有就畫，沒有就在〔尚未建置〕裡說為什麼。匯進來之後那
    # 一頁的理由就不再適用了，所以清單是算出來的，不是寫死的。
    grid = reader.grid if hasattr(reader, "grid") else (lambda _n: [])
    page.holders = holders(grid(HOLDERS))
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
