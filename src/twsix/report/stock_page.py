
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

GRADE_LETTERS = frozenset({"AA", "A", "BB", "B", "C"})

Number = float | None

REWARD_RISK_RULES: tuple[tuple[str, str, str], ...] = (
    ("> 2", "買進", "報酬風險比大於 2，才有買進的意義"),
    ("0.67 ~ 2", "靜待", "多空不明，靜待股價或預估股價區間之變動"),
    ("< 0.67", "減碼", "考慮減碼或賣出"),
    ("< 0.5", "空頭", "考慮布局空頭部位（更嚴格的門檻為 0.25）"),
)

REWARD_RISK_NOTES: tuple[str, ...] = (
    "EPS、PER 與報酬風險比之動態方法，越接近下半年越會失去參考意義。",
    "實務上要先檢視當年度（迄今）之股價高低點是否已出現。",
)

RESEARCH_THRESHOLD = 3.0

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
        "取去年起往前最多五個年度（至少 3 年），各去掉最高與最低的一年，其餘平均",
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
    if ratio is None:
        return ("—", "無報酬風險比")
    if ratio <= 0:
        return ("價格高估", "目標價低於現在的股價，預期報酬為負：股價已超過基本面撐得住的價值")
    if ratio > 2:
        return ("買進", REWARD_RISK_RULES[0][2])
    if ratio < 0.5:
        return ("空頭", REWARD_RISK_RULES[3][2])
    if ratio < 0.67:
        return ("減碼", REWARD_RISK_RULES[2][2])
    return ("靜待", REWARD_RISK_RULES[1][2])


def _change_pct(quote: Any) -> float | None:
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

    id: str
    title: str
    note: str = ""
    gap: str = ""


@dataclass
class StockPage:

    stock_id: str
    name: str = ""
    market_price: Number = None
    price_date: str = ""
    price_change: Number = None
    price_change_pct: Number = None
    fiscal_quarter: str = ""
    revenue_month: str = ""
    market: str = ""
    industry: str = ""
    excluded: str = ""

    periods: list[dict[str, Any]] = field(default_factory=list)
    indicators: list[dict[str, Any]] = field(default_factory=list)
    latest_composite: Number = None
    revenue_rows: list[dict[str, Any]] = field(default_factory=list)

    forecast: dict[str, Any] = field(default_factory=dict)
    calc: dict[str, Any] = field(default_factory=dict)
    methodology: dict[str, Any] = field(default_factory=dict)
    pe: dict[str, Any] = field(default_factory=dict)
    growth: dict[str, Any] = field(default_factory=dict)
    dividend: dict[str, Any] = field(default_factory=dict)
    dividend_lag_rows: list[dict[str, Any]] = field(default_factory=list)

    figures: dict[str, str] = field(default_factory=dict)
    gaps: dict[str, str] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    statements: dict[str, str] = field(default_factory=dict)
    river: River | None = None
    news: Any = None
    institutional: Institutional | None = None
    holders: Holders | None = None
    directors: Directors | None = None
    revenue_season: Seasonal | None = None
    profit_season: Seasonal | None = None
    unbuilt: list[dict[str, str]] = field(default_factory=list)
    health: dict[str, Any] = field(default_factory=dict)
    growth_q: dict[str, Any] = field(default_factory=dict)
    three_year: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)

    @property
    def worth_researching(self) -> bool:
        return (
            self.latest_composite is not None
            and self.latest_composite >= RESEARCH_THRESHOLD
        )


def _weekly_closes(reader: Any) -> list[tuple[str, float]]:
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
    from ..ingest import news as news_mod  # noqa: PLC0415

    grid = reader.grid(news_mod.SHEET) if hasattr(reader, "grid") else []
    items = news_mod.from_grid(grid) if grid else []
    if extra:
        items = news_mod.merge_items(items, list(extra))
    if not items:
        return None
    return news_mod.describe(items)


REVENUE_MONTHS = 36


TABLE_PERIODS = 8


def _eight_periods(data: Any, snapshot: Any) -> dict[str, tuple[list[str], list[Number]]]:
    if data is None:
        return {}
    out: dict[str, tuple[list[str], list[Number]]] = {}

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
        ("non_operating_ratio", getattr(data, "non_operating_ratio", {}) or {}),
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
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    m = sum(nums) / len(nums)
    return (sum((x - m) ** 2 for x in nums) / (len(nums) - 1)) ** 0.5


def _calc_seed(reader: Any, stock_id: str, valuation: Any) -> dict[str, Any]:
    from ..ingest.valuation_source import read_valuation_input

    try:
        raw = read_valuation_input(reader, stock_id=stock_id)
    except Exception:  # noqa: BLE001 - 少了輸入就沒有試算盤，不影響其他區塊
        return {}

    yoy = [v for v in (raw.monthly_revenue_yoy or ())]
    latest = yoy[0] if yoy else None
    recent6 = _mean(yoy[:6])
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
        "revenue": None if raw.last_year_revenue is None else raw.last_year_revenue / 1000,
        "shares": None if raw.weighted_shares is None else raw.weighted_shares / 100,
        "price": valuation.market_price,
        "growth": {"latest": latest, "recent6": recent6},
        "margin": {"avg": avg_margin, "sigma": sd},
        "pe": {"low": pe_low, "mid": pe_mid, "high": pe_high},
        "years": years,
    }


GROWTH_METHOD_LABELS: dict[str, tuple[str, str]] = {
    "1&6": ("最近一月與近六月平均孰低", "MIN(最近一個月年增率, 近六個月平均年增率)"),
    "3&6": ("近三月與近六月平均孰低", "MIN(近三個月平均年增率, 近六個月平均年增率)"),
    "12m": ("近十二月累計年增率", "近十二個月累計營收 ÷ 前十二個月累計營收 − 1"),
}

MARGIN_METHOD_LABELS: dict[str, tuple[str, str]] = {
    "4q_avg": ("近四季平均", "近四季稅後淨利率的算術平均"),
    "4q_min": ("近四季最低", "近四季稅後淨利率中最保守的一季"),
    "current": ("最近一季", "最近一季（當季）稅後淨利率"),
}

PE_BASIS_LABELS: dict[str, tuple[str, str]] = {
    "current_year": ("當年度", "只取最近一個完整年度的最高／最低本益比"),
    "avg_3y": (
        "3年平均（排除極端值後）",
        "窗格（去年起往前最多五年、至少三年）先各丟掉一個最高與一個最低年度，剩下的取最近三年平均",
    ),
    "avg_5y": (
        "5年平均（排除極端值後）",
        "近五個（至少三個）完整年度中，各丟掉一個最高與一個最低年度，其餘平均",
    ),
    "min_current_5y": ("當年與5年平均孰低", "取「當年度」與「5年平均（排除極端值）」兩者中較低的一個"),
}


def _methodology(valuation: Any, settings: Any) -> dict[str, Any]:
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
    closes: Any = None,
    news_items: Any = None,
    history: Any = None,
    foreign_months: Any = None,
) -> StockPage:
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
        price_date=quote.label if quote is not None else market_close(reader)[1],
        price_change=getattr(quote, "change", None) if quote is not None else None,
        price_change_pct=_change_pct(quote),
        excluded=getattr(rating, "excluded", "") or "",
        market=(getattr(rating, "market", "") or getattr(data, "market", "") or ""),
        industry=(getattr(rating, "industry", "") or getattr(data, "industry", "") or ""),
        gaps=dict(valuation.gaps or {}),
    )

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

    if rating.snapshots:
        newest = rating.snapshots[0]
        shown = _eight_periods(data, newest)

        def _unscored(key, label, reason, after):
            got = shown.get(key)
            if not got or not any(v is not None for v in got[1]):
                return
            at = next(
                (i + 1 for i, r in enumerate(page.indicators) if r["key"] == after),
                len(page.indicators),
            )
            page.indicators.insert(
                at,
                {
                    "key": key,
                    "label": label,
                    "letter": "",
                    "badge": False,
                    "display": "—",
                    "reason": reason,
                    "scored": False,
                    "values": [
                        None if v is None else round(float(v), 2) for v in got[1]
                    ],
                    "periods": list(got[0]),
                },
            )

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
                    "values": [
                        None if v is None else round(float(v), 2) for v in values
                    ],
                    "periods": list(labels),
                }
            )
        _unscored(
            "net_margin",
            "淨利率（歸母）",
            "不列入評分；歸屬母公司稅後淨利 ÷ 營收",
            after="operating_margin",
        )
        _unscored(
            "non_operating_ratio",
            "業外佔比",
            "不列入評分；營業外收入及支出 ÷ 稅前淨利",
            after="net_margin",
        )

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

    every_month = revenue_detail(reader)
    months = [(row[0], row[1]) for row in every_month if row[1] is not None]
    detail = every_month[:REVENUE_MONTHS]
    if detail:
        page.figures["revenue"] = charts.combo(
            [row[0] for row in detail],
            bar=("月營收", [None if r[1] is None else r[1] / 1000 for r in detail]),
            lines=[("年增率", [r[3] for r in detail], "var(--m0)")],
            title="三年營收趨勢",
            table=False,
            bar_unit=" 百萬",
            bar_digits=0,
            bar_colour="var(--m1)",
            bar_axis="left",
            line_unit="%",
            line_digits=1,
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

    from .health import encode_history, financial_health, growth_analysis, three_year_seed

    page.health = financial_health(data, page.fiscal_quarter)
    page.growth_q = growth_analysis(data, page.fiscal_quarter)
    page.three_year = three_year_seed(data, page.calc, page.fiscal_quarter)
    if history:
        page.history = encode_history(list(history[0]), list(history[1]))

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
    page.institutional = institutional(inst_grid, inst_days, closes)
    page.news = _news(reader, news_items)

    grid = reader.grid if hasattr(reader, "grid") else (lambda _n: [])
    from ..ingest import weekly_prices  # noqa: PLC0415

    page.holders = holders(grid(HOLDERS), weekly_prices.closes(grid(weekly_prices.SHEET)))
    page.directors = directors(grid(DIRECTORS), history, foreign_months)
    have = {HOLDERS: page.holders, DIRECTORS: page.directors}
    page.unbuilt = [
        {"name": n, "why": w} for n, w in UNBUILT_PAGES if not have.get(n)
    ]

    from ..ingest.yearly_trading import SHEET as YEARLY  # noqa: PLC0415
    from ..ingest.yearly_trading import is_derived

    derived = {YEARLY} if is_derived(grid(YEARLY) or []) else set()
    page.sources = [
        {"sheet": name, "ok": name in set(sheets_present),
         "note": "推算：由股價週線與每日行情算出" if name in derived else ""}
        for name in (
            "FRQ", "CFQ", "ISQ", "BSQ", "BASIC", "營收", "OPQ", "EPQ", "股利",
            "三大法人", "年財務比率", "年度交易資訊_上市櫃合併_",
            "股價(週)", "個股新聞", HOLDERS, DIRECTORS,
        )
    ]
    return page
