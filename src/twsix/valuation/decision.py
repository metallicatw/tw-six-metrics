"""估值決策系統：七大標準步驟 × 十一種本益比故事 × 斷捨離五準則 × 下單前五道防線。

方法論（先求敗、再求勝）：
1. 先排除體質有疑慮的股票（斷捨離五準則），再做數學估值。
2. 全部用「保守」參數推一次（Q4 季減、隔年年增取半再減 10 個百分點、淨利率下修、本益比打折），
   保守版本仍然有足夠空間、風險夠小，才是真正的買點。
3. 估值依本益比故事（十一型）選規則；景氣循環、高配息、本益比被壓縮的股票改用殖利率反推。
4. 大盤位階過高（總經四大警訊觸發兩項以上）時，進場要求的往上空間由 60% 提高到 80%。

單位：營收、淨利、股本都用「百萬元」計算，畫面顯示換成「億元」（÷100）；
股數（百萬股）＝ 股本（百萬元）÷ 10（台股面額 10 元）；EPS ＝ 淨利（百萬）÷ 股數（百萬股）。

純函式模組：輸入是 `DecisionInput`，輸出是可直接 JSON 化的 dict（給個股頁〈估值決策〉分頁）。
所有計算過程都留在輸出的 `steps[*].calc` 裡，畫面逐行列出「公式 → 代入 → 結果」。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

Number = float | None

# ── 參數（集中在這裡，方便日後調整與測試）───────────────────────────────

UPSIDE_NORMAL = 0.60          # 一般行情：往上空間至少 60%
UPSIDE_HOT = 0.80             # 大盤位階過高（警訊 ≥ 2）：至少 80%
DOWNSIDE_MAX = 0.20           # 往下風險上限 20%
DOWNSIDE_DEFENSIVE = 0.10     # 防禦型（高配息、景氣循環、本益比被壓縮）上限 10%
PEH_HAIRCUT_TRIGGER = 50.0    # 當年最高本益比 ≥ 50 倍 → 隔年 PEH 打七折
PEH_HAIRCUT = 0.70
HIGH_GROWTH = 0.20            # 今年營收年增 ≥ 20% 才用「取半法」
Q4_SEASON_MIN = 0.05          # 歷史季增 ≥ 5% 才算有旺季
Q_CUT = -0.10                 # 高檔保守：季減 10%
Q_CUT_HOT = -0.15             # 大盤過熱時的保守：季減 15%
YIELD_BUY = (0.08, 0.075, 0.07, 0.065)
YIELD_SELL = 0.05
ONE_OFF_NONOP = 20.0          # 業外佔稅前淨利 ≥ 20%（或偏離 8 季中位數 15 個百分點）視為一次性
SMALL_CAPITAL = 300.0         # 股本 < 3 億元（百萬）＝小股本
CYCLICAL_INDUSTRIES = ("航運", "鋼鐵", "塑膠", "水泥", "玻璃陶瓷", "造紙", "橡膠", "油電燃氣", "化學")


@dataclass
class QuarterRow:
    label: str            # 2026Q3
    year: int
    q: int
    rev: Number = None    # 百萬元
    ni: Number = None     # 歸母稅後淨利（百萬元）
    nm: Number = None     # 稅後淨利率（%）
    om: Number = None     # 營業利益率（%）
    nonop: Number = None  # 業外佔稅前淨利（%）
    eps: Number = None


@dataclass
class YearRow:
    year: int
    high: Number = None
    low: Number = None
    eps: Number = None
    pe_high: Number = None
    pe_low: Number = None
    div: Number = None     # 該盈餘年度配發的現金股利（元）


@dataclass
class DecisionInput:
    stock_id: str
    name: str = ""
    industry: str = ""
    price: Number = None
    price_date: str = ""
    months: list[tuple[int, int, float]] = field(default_factory=list)   # (西元年, 月, 營收百萬) 舊→新
    month_yoy: list[tuple[int, int, float]] = field(default_factory=list)  # (西元年, 月, 年增率%) 舊→新
    annual_rev: dict[int, float] = field(default_factory=dict)          # 季財報加總的年度營收（百萬）
    quarters: list[QuarterRow] = field(default_factory=list)            # 舊→新
    years: list[YearRow] = field(default_factory=list)                  # 新→舊，只放完整年度
    capital: list[tuple[str, float]] = field(default_factory=list)      # (2026Q2, 股本百萬) 舊→新
    inventory: list[tuple[str, float]] = field(default_factory=list)    # 舊→新（百萬）
    contract_liab: list[tuple[str, float]] = field(default_factory=list)
    capex: list[tuple[str, float]] = field(default_factory=list)        # 單季資本支出（百萬，正數）
    cash: Number = None                                                 # 最新現金及約當現金（百萬）
    closes: list[tuple[str, float]] = field(default_factory=list)       # 日收盤 舊→新
    foreign_net: list[float] = field(default_factory=list)              # 外資每日買賣超（張）新→舊
    margin_lots: list[float] = field(default_factory=list)              # 個股融資餘額（張）新→舊
    daytrade_ratio: Number = None                                       # 個股近 20 日當沖比（%）
    macro: dict[str, Any] = field(default_factory=dict)                 # 大盤警訊輸入（見 macro_alerts）


# ── 小工具 ─────────────────────────────────────────────────────────────

def _ok(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _mean(vals: Sequence[Number]) -> Number:
    v = [x for x in vals if _ok(x)]
    return sum(v) / len(v) if v else None


def _median(vals: Sequence[Number]) -> Number:
    v = sorted(x for x in vals if _ok(x))
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _r(v: Number, d: int = 2) -> Number:
    return None if not _ok(v) else round(float(v), d)


def _yi(v: Number) -> str:
    """百萬元 → 「1,234.56 億」。"""
    return "—" if not _ok(v) else f"{v / 100:,.2f} 億"


def _pc(v: Number, d: int = 2, sign: bool = False) -> str:
    if not _ok(v):
        return "—"
    s = f"{v * 100:+,.{d}f}%" if sign else f"{v * 100:,.{d}f}%"
    return s


def _n(v: Number, d: int = 2) -> str:
    return "—" if not _ok(v) else f"{v:,.{d}f}"


def _qlabel(year: int, q: int) -> str:
    return f"{year}Q{q}"


def _qshift(year: int, q: int, n: int) -> tuple[int, int]:
    t = year * 4 + (q - 1) + n
    return t // 4, t % 4 + 1


# ── 第一篇 1.1：總經四大警訊（動態保守折價觸發條件）─────────────────────

def macro_alerts(m: dict[str, Any]) -> dict[str, Any]:
    """大盤位階警訊。輸入（缺的就不判斷，不猜）：
    taiex_drawdown（加權指數距一年高點跌幅，負數）、leaders_down（千金股中自高點回檔 ≥25% 的比例 0~1）、
    mcm1b_pct（市值貨幣比近五年百分位）、m1b_inc_6m／m1b_inc_prev6m（M1B 近 6 個月月均增加額 vs 前 6 個月，億）、
    margin_amt（上市櫃融資餘額，億）、margin_pct（融資餘額近 400 日百分位）、margin_chg20（融資 20 日變化率）、
    daytrade（大盤當沖比 %，近 20 日平均）。
    """
    out = []

    def add(key: str, title: str, hit: bool | None, why: str) -> None:
        out.append({"key": key, "title": title, "hit": hit, "why": why})

    dd, lead = m.get("taiex_drawdown"), m.get("leaders_down")
    if _ok(lead) or _ok(dd):
        hit = (_ok(lead) and lead >= 0.4) or (_ok(dd) and dd <= -0.10)
        bits = []
        if _ok(lead):
            bits.append(f"千金股中有 {lead * 100:.0f}% 已自一年高點回檔 25% 以上")
        if _ok(dd):
            bits.append(f"加權指數距一年高點 {dd * 100:+.1f}%")
        add("leaders", "① 盤面領頭羊先跌", hit, "；".join(bits) + "（門檻：千金股四成以上回檔 25%，或指數回檔 10%）")
    else:
        add("leaders", "① 盤面領頭羊先跌", None, "缺資料")

    pct, inc, prev = m.get("mcm1b_pct"), m.get("m1b_inc_6m"), m.get("m1b_inc_prev6m")
    if _ok(pct) or (_ok(inc) and _ok(prev)):
        shrink = _ok(inc) and _ok(prev) and prev > 0 and inc < prev * 0.8
        hit = (_ok(pct) and pct >= 80) or shrink
        bits = []
        if _ok(pct):
            bits.append(f"市值貨幣比位於近五年第 {pct:.0f} 百分位")
        if _ok(inc) and _ok(prev):
            bits.append(f"M1B 近 6 個月月均增加 {inc:,.0f} 億（前 6 個月 {prev:,.0f} 億）")
        add("money", "② 資金動能惡化", hit, "；".join(bits) + "（門檻：百分位 ≥ 80，或月均增加額萎縮兩成）")
    else:
        add("money", "② 資金動能惡化", None, "缺資料")

    amt, mp, mc = m.get("margin_amt"), m.get("margin_pct"), m.get("margin_chg20")
    if _ok(amt) or _ok(mp):
        hit = (_ok(amt) and amt >= 5800) or (_ok(mp) and mp >= 90)
        bits = []
        if _ok(amt):
            bits.append(f"上市櫃融資餘額 {amt:,.0f} 億")
        if _ok(mp):
            bits.append(f"近 400 日第 {mp:.0f} 百分位")
        if _ok(mc):
            bits.append(f"20 日變化 {mc * 100:+.1f}%")
        add("margin", "③ 融資籌碼過熱", hit, "；".join(bits) + "（門檻：≥ 5,800 億或第 90 百分位；中級回檔要減肥 10% 才算落底）")
    else:
        add("margin", "③ 融資籌碼過熱", None, "缺資料")

    dt = m.get("daytrade")
    if _ok(dt):
        add("daytrade", "④ 當沖投機過熱", dt >= 45, f"大盤當沖比（近 20 日）{dt:.1f}%（門檻：≥ 45%）")
    else:
        add("daytrade", "④ 當沖投機過熱", None, "缺資料")

    hits = sum(1 for a in out if a["hit"])
    known = sum(1 for a in out if a["hit"] is not None)
    hot = hits >= 2
    return {"items": out, "hits": hits, "known": known, "hot": hot,
            "upside_req": UPSIDE_HOT if hot else UPSIDE_NORMAL,
            "summary": (f"大盤警訊 {hits}／{known} 項觸發："
                        + ("位階過高，啟動動態保守折價（往上空間門檻提高到 80%、Q4 改用季減 15%）" if hot
                           else "未達過熱，用一般門檻（往上空間 60%）"))}


# ── 第一篇 1.2：斷捨離五準則 ─────────────────────────────────────────

def _quarter_rev_from_months(months: list[tuple[int, int, float]]) -> dict[tuple[int, int], float]:
    by: dict[tuple[int, int], list[float]] = {}
    for y, mo, v in months:
        by.setdefault((y, (mo - 1) // 3 + 1), []).append(v)
    return {k: sum(v) for k, v in by.items() if len(v) == 3}


def five_criteria(inp: DecisionInput) -> dict[str, Any]:
    items = []

    def add(n: int, title: str, state: str, why: str) -> None:
        items.append({"n": n, "title": title, "state": state, "why": why})

    # 1. 股本膨脹率（近 8 季）
    cap = [v for _, v in inp.capital if _ok(v) and v > 0]
    if len(cap) >= 2:
        base = cap[-9] if len(cap) >= 9 else cap[0]
        g = cap[-1] / base - 1
        span = "近 8 季" if len(cap) >= 9 else f"近 {len(cap) - 1} 季"
        st = "pass" if g < 0.10 else "warn"
        add(1, "股本膨脹率", st, f"{span}股本 {_yi(base)} → {_yi(cap[-1])}（{g * 100:+.1f}%）；"
            + ("無明顯膨脹" if st == "pass" else "膨脹 ≥ 10%，EPS 分母要用最新股本、留意現增／CB 稀釋"))
    else:
        add(1, "股本膨脹率", "na", "缺股本資料")

    # 2. 營收成長極限：單月年增率連續 3 個月遞減
    yoy = [v for _, _, v in inp.month_yoy][-6:]
    if len(yoy) >= 4:
        last4 = yoy[-4:]
        falling = all(last4[i] > last4[i + 1] for i in range(3))
        qrev = _quarter_rev_from_months(inp.months)
        ks = sorted(qrev)
        qoq = (qrev[ks[-1]] / qrev[ks[-2]] - 1) if len(ks) >= 2 and qrev[ks[-2]] else None
        txt = "→".join(f"{v:.1f}%" for v in last4)
        if falling and last4[0] > 0:
            add(2, "營收成長極限", "fail", f"單月年增率連 3 個月遞減（{txt}），疑似遇到成長極限")
        else:
            add(2, "營收成長極限", "pass",
                f"近 4 個月年增率 {txt}，未連 3 月遞減" + (f"；最新一季季增 {qoq * 100:+.1f}%" if _ok(qoq) else ""))
    else:
        add(2, "營收成長極限", "na", "月營收不足")

    # 3. 獲利成長品質：營益率創 8 季新高或連 2~3 季上升；營收增但營益率降＝扣分
    qs = [q for q in inp.quarters if _ok(q.om)]
    if len(qs) >= 4:
        om = [q.om for q in qs][-8:]
        top = om[-1] >= max(om)
        up2 = len(om) >= 3 and om[-1] > om[-2] > om[-3]
        rev_up = len(qs) >= 5 and _ok(qs[-1].rev) and _ok(qs[-5].rev) and qs[-1].rev > qs[-5].rev
        om_dn = om[-1] < om[-2]
        if top or up2:
            add(3, "獲利成長品質", "pass", f"營益率 {om[-1]:.2f}%" + ("，創近 8 季新高" if top else "，連 2 季上升"))
        elif rev_up and om_dn and om[-1] < _mean(om[:-1]):
            add(3, "獲利成長品質", "fail", f"營收年增但營益率下滑到 {om[-1]:.2f}%（近 8 季平均 {_mean(om[:-1]):.2f}%），留意殺價或成本轉嫁困難")
        else:
            add(3, "獲利成長品質", "warn", f"營益率 {om[-1]:.2f}%，未創 8 季新高也未連續上升")
    else:
        add(3, "獲利成長品質", "na", "季財報不足")

    # 4. 存貨與訂單健康度
    inv = [v for _, v in inp.inventory if _ok(v)]
    cl = [v for _, v in inp.contract_liab if _ok(v)]
    bits, st = [], "warn"
    if len(inv) >= 4:
        low8 = inv[-1] <= min(inv[-8:])
        up3 = len(inv) >= 4 and inv[-1] > inv[-2] > inv[-3] > inv[-4]
        last_rev = inp.quarters[-1].rev if inp.quarters and _ok(inp.quarters[-1].rev) else None
        ratio = (inv[-1] / last_rev) if last_rev else None
        revs = [q.rev for q in inp.quarters if _ok(q.rev)]
        ratio_prev = (inv[-4] / revs[-4]) if len(revs) >= 4 and revs[-4] else None
        if low8:
            bits.append(f"存貨 {_yi(inv[-1])} 創近 8 季新低")
            st = "pass"
        elif up3:
            bits.append(f"存貨連 3 季上升到 {_yi(inv[-1])}")
        if _ok(ratio):
            bits.append(f"存貨／單季營收 {ratio * 100:.0f}%" + (f"（三季前 {ratio_prev * 100:.0f}%）" if _ok(ratio_prev) else ""))
            if ratio >= 0.8 and not low8:
                st = "fail"
            elif up3 and _ok(ratio_prev) and ratio > ratio_prev * 1.1:
                st = "fail"
                bits.append("存貨增加比營收快，留意超額備貨")
            elif up3:
                bits.append("存貨隨營收成長而增加，比率未惡化")
    if len(cl) >= 4 and cl[-1] > 0 and cl[-1] >= max(cl):
            bits.append(f"合約負債 {_yi(cl[-1])} 創歷史新高（在手訂單強）")
            st = "pass" if st != "fail" else "warn"
    cx = [v for _, v in inp.capex if _ok(v)]
    cl_q = dict(inp.contract_liab)
    tags = [t for t, _ in inp.contract_liab]
    if len(cx) >= 8 and sum(cx[-8:-4]) > 0 and len(tags) >= 5 and cl_q.get(tags[-5]):
        from ..clcapex import quadrant  # noqa: PLC0415

        qd = quadrant((cl_q[tags[-1]] / cl_q[tags[-5]] - 1) * 100, sum(cx[-4:]) / sum(cx[-8:-4]))
        if qd and qd["key"] in ("best", "risk_a", "risk_b"):
            bits.append(qd["title"])
            if qd["key"] == "best" and st != "fail":
                st = "pass"
            elif qd["key"] == "risk_a" and st == "pass":
                st = "warn"
    add(4, "存貨與訂單健康度", st if bits else "na", "；".join(bits) if bits else "缺存貨／合約負債資料")

    # 5. 獲利爆發動能：成長 1.0／2.0；小股本扣分
    y_now = inp.quarters[-1].year if inp.quarters else None
    last_full = next((y for y in inp.years if _ok(y.eps)), None)
    if y_now and last_full and last_full.eps and last_full.eps > 0:
        cum = [q.eps for q in inp.quarters if q.year == y_now and _ok(q.eps)]
        c = sum(cum)
        ratio = c / last_full.eps
        n = len(cum)
        tag = ("成長 2.0" if (ratio >= 1.3 or (n <= 2 and ratio >= 1.0)) else
               "成長 1.0" if ratio >= 1.0 else "")
        txt = f"{y_now} 前 {n} 季 EPS 合計 {c:.2f} 元，是去年全年 {last_full.eps:.2f} 元的 {ratio:.2f} 倍"
        capv = cap[-1] if cap else None
        small = _ok(capv) and capv < SMALL_CAPITAL
        dt = inp.daytrade_ratio
        risky = small and _ok(dt) and dt >= 60
        if tag:
            st5 = "warn" if risky else "pass"
            add(5, "獲利爆發動能", st5, f"{txt}（符合{tag}）" + ("；但股本小於 3 億、當沖比過高，部位難放大" if risky else
                                                         ("；股本小於 3 億，波動大" if small else "")))
        else:
            add(5, "獲利爆發動能", "warn", txt + "（尚未符合成長 1.0）")
    else:
        add(5, "獲利爆發動能", "na", "缺去年全年 EPS 或今年季 EPS")

    fails = sum(1 for i in items if i["state"] == "fail")
    return {"items": items, "fails": fails,
            "verdict": ("好球帶：可以進入估值" if fails == 0 else f"斷捨離：{fails} 項不及格，估值僅供參考")}


# ── 第一篇 1.4：十一種本益比故事 ───────────────────────────────────────

STORIES = {
    1: ("強本益比", "PEH 與 PEL 連年雙雙推升；連漲 3~4 年、PEH 達 50~60 倍以上時嚴防成長極限，隔年 PEH 打七折。"),
    2: ("景氣循環股", "獲利隨報價劇烈波動，不硬套本益比；改用現金股利殖利率與股價淨值比推買賣點。"),
    3: ("本益比低點墊高", "PEL 逐年墊高，拉回接近 PEL 或年線布局，往下風險常低於 5%~10%。"),
    4: ("本益比被壓縮", "EPS 連年成長但本益比連年下降，等轉折確認（營益率、售貨天數），用高殖利率反推買點。"),
    5: ("穩定的本益比區間", "大型績優股，本益比區間規律；用「營收年增取半＋四季平均淨利率」穩健推算。"),
    6: ("PEL 變高、PEH 難預測", "PEH 常在 60 倍以上游走，不猜高點，只從 PEL 防守評估下檔。"),
    7: ("本益比過高／評估不出來", "過去獲利極低致本益比近百倍，需搭配營益率創高、自由現金流轉正等轉折評估。"),
    8: ("轉機股（過去虧損）", "過去虧損算不出歷史本益比；等預估本益比回到 20 倍以下再布局。"),
    9: ("高配息率穩定", "歷年配息率 70%~85% 以上，結合殖利率推算低點。"),
    10: ("千金股／高市值", "市值破千億、本益比 50 倍以上，市值再翻倍很辛苦；加入市值天花板、PEH 下修 30%。"),
    11: ("價值成長（網紅策略）", "5 年營收年增 >10%、EPS 與股利連 5 年成長、本益比連 3 年下降；等本益比掉到 15 倍以下。"),
}
STORY_PRIORITY = (8, 2, 1, 10, 7, 6, 4, 3, 9, 11, 5)
DEFENSIVE_STORIES = {2, 4, 9}


def _rising(vals: Sequence[Number], n: int) -> bool:
    v = [x for x in vals if _ok(x)]
    return len(v) >= n and all(v[i] < v[i + 1] for i in range(len(v) - n, len(v) - 1))


def _falling(vals: Sequence[Number], n: int) -> bool:
    v = [x for x in vals if _ok(x)]
    return len(v) >= n and all(v[i] > v[i + 1] for i in range(len(v) - n, len(v) - 1))


def classify(inp: DecisionInput, cur_pe_high: Number, cur_pe_low: Number, eps_cur: Number,
             market_cap: Number) -> dict[str, Any]:
    ys = list(reversed(inp.years[:6]))            # 舊→新
    peh = [y.pe_high for y in ys] + [cur_pe_high]
    pel = [y.pe_low for y in ys] + [cur_pe_low]
    eps = [y.eps for y in ys]
    divs = [y.div for y in ys]
    pe_avg = [(_mean([a, b])) for a, b in zip(peh, pel, strict=False)]
    hits: dict[int, str] = {}

    recent_eps = [e for e in eps[-4:] if e is not None]
    if any(e <= 0 for e in recent_eps) and _ok(eps_cur) and eps_cur > 0:
        hits[8] = "近 4 年有虧損年度，今年轉盈"
    ind = inp.industry or ""
    eps_ok = [e for e in eps if _ok(e)]
    cv = (math.sqrt(sum((e - _mean(eps_ok)) ** 2 for e in eps_ok) / len(eps_ok)) / abs(_mean(eps_ok))
          if len(eps_ok) >= 4 and _mean(eps_ok) else None)
    drops = sum(1 for a, b in zip(eps_ok, eps_ok[1:], strict=False) if b < a * 0.85)
    if any(k in ind for k in CYCLICAL_INDUSTRIES):
        hits[2] = f"產業「{ind}」屬原物料／運價驅動"
    elif _ok(cv) and cv >= 0.6 and drops >= 2 and 8 not in hits:
        hits[7] = f"近年 EPS 起伏大（變異係數 {cv:.2f}、{drops} 次明顯衰退），歷史本益比失真"
    big = (_ok(inp.price) and inp.price >= 1000) or (_ok(market_cap) and market_cap >= 100_000)
    if big and _ok(cur_pe_high) and cur_pe_high >= 50:
        hits[10] = f"股價／市值高（市值 {_yi(market_cap)}），當年最高本益比 {cur_pe_high:.1f} 倍"
    avg_pe = _mean(pe_avg[-3:])
    if _ok(avg_pe) and avg_pe >= 60:
        hits.setdefault(7, f"近 3 年平均本益比 {avg_pe:.0f} 倍")
    peh_recent = [x for x in peh[-3:] if _ok(x)]
    if peh_recent and min(peh_recent) >= 60 and _rising(pel, 3):
        hits[6] = "PEH 連 3 年 ≥ 60 倍、PEL 墊高"
    prior_h = [x for x in peh[-4:-1] if _ok(x)]
    prior_l = [x for x in pel[-4:-1] if _ok(x)]
    eps_up = _rising(eps_ok[-3:] + ([eps_cur] if _ok(eps_cur) else []), 3)
    if (len(prior_h) >= 2 and _ok(peh[-1]) and peh[-1] >= max(prior_h) and _ok(pel[-1])
            and pel[-1] >= _median(prior_l) and eps_up):
        hits[1] = (f"今年 PEH {peh[-1]:.1f} 倍創近年新高、PEL {pel[-1]:.1f} 倍高於近年中位數，EPS 連年成長")
    eps_seq = eps_ok + ([eps_cur] if _ok(eps_cur) else [])
    if _rising(eps_seq, 4) and _falling(pe_avg, 3):
        hits[4] = "EPS 連 3 年成長，本益比連 2 年下降"
    if _rising(pel, 3) and 1 not in hits:
        hits[3] = "PEL 連 2 年墊高"
    pays = [d / e for d, e in zip(divs, eps, strict=False) if _ok(d) and _ok(e) and e > 0]
    pe_level = _mean([x for x in pe_avg[-3:] if _ok(x)])
    if len(pays) >= 4 and min(pays[-5:]) >= 0.65 and (not _ok(pe_level) or pe_level <= 22):
        hits[9] = f"近 {min(5, len(pays))} 年配息率皆 ≥ 65%（最低 {min(pays[-5:]) * 100:.0f}%）"
    divs_ok = [d for d in divs if _ok(d)]
    if (_rising(eps_seq, 5) and len(divs_ok) >= 5 and _rising(divs_ok, 5) and _falling(pe_avg, 3)):
        hits[11] = "EPS 與股利連 5 年成長、本益比連 3 年下降"
    if not hits or all(k in (3, 9) for k in hits):
        lo, hi = [x for x in pel if _ok(x)], [x for x in peh if _ok(x)]
        if len(hi) >= 3 and len(lo) >= 3 and max(hi) / max(min(hi), 1e-9) < 2.2:
            hits.setdefault(5, "本益比區間規律（歷年最高本益比的高低差不到 2.2 倍）")
    primary = next((k for k in STORY_PRIORITY if k in hits), 5)
    if primary not in hits:
        hits[5] = "沒有明顯的特殊型態，以穩定區間方式估算"
    return {"primary": primary, "name": STORIES[primary][0], "strategy": STORIES[primary][1],
            "matched": [{"n": k, "name": STORIES[k][0], "why": hits[k]} for k in STORY_PRIORITY if k in hits]}


# ── 第一篇 1.3：七大標準步驟 ───────────────────────────────────────────

SCN = ("保守", "中性", "樂觀")


def evaluate_decision(inp: DecisionInput) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    gaps: list[str] = []
    macro = macro_alerts(inp.macro or {})
    hot = macro["hot"]
    crit = five_criteria(inp)

    if not inp.months:
        return {"ok": False, "gaps": ["缺月營收"], "macro": macro, "criteria": crit}
    cap_now = inp.capital[-1][1] if inp.capital else None
    if not _ok(cap_now) or cap_now <= 0:
        return {"ok": False, "gaps": ["缺股本"], "macro": macro, "criteria": crit}
    shares = cap_now / 10.0                                  # 百萬股
    Y = inp.months[-1][0]
    by_m = {(y, m): v for y, m, v in inp.months}
    qrev = _quarter_rev_from_months(inp.months)
    ly_months = [by_m.get((Y - 1, m)) for m in range(1, 13)]
    ly_total = sum(ly_months) if all(_ok(v) for v in ly_months) else (inp.annual_rev or {}).get(Y - 1)
    steps: list[dict[str, Any]] = []

    # ── 步驟一：今年剩餘季別營收（三情境）與全年營收 ──
    known_m = [m for m in range(1, 13) if _ok(by_m.get((Y, m)))]
    last_m = max(known_m)
    full_q = [q for q in range(1, 5) if (Y, q) in qrev]
    last_q = max(full_q) if full_q else None
    if last_q is None:                         # 今年連一季都還不完整：用去年最後一季當基準
        base_q_rev = qrev.get((Y - 1, 4))
        base_q_label = _qlabel(Y - 1, 4)
    else:
        base_q_rev = qrev[(Y, last_q)]
        base_q_label = _qlabel(Y, last_q)
    nxt = (last_q or 0) + 1
    # 歷史旺季：過去 5 年「下一季 ÷ 基準季」的季增率
    season = []
    for k in range(1, 6):
        a = qrev.get((Y - k, nxt)) if nxt <= 4 else None
        b = qrev.get((Y - k, last_q)) if last_q else None
        if _ok(a) and _ok(b) and b:
            season.append(a / b - 1)
    season_avg = _mean(season)
    seasonal = _ok(season_avg) and season_avg >= Q4_SEASON_MIN
    cut = Q_CUT_HOT if hot else Q_CUT
    up = min(0.10, max(0.05, season_avg / 2)) if seasonal else 0.0
    qoq = {"保守": cut, "中性": (0.0 if not hot else cut / 2) if not seasonal else (0.0 if hot else up / 2),
           "樂觀": up if seasonal else 0.05}
    rev_cur: dict[str, float] = {}
    rest_detail: dict[str, list[str]] = {s: [] for s in SCN}
    actual_y = sum(by_m.get((Y, m), 0.0) for m in known_m)
    if not _ok(base_q_rev):
        gaps.append("缺最近一季的完整月營收")
    else:
        for s in SCN:
            total, cur = actual_y, base_q_rev
            for q in range(nxt, 5):
                cur = cur * (1 + qoq[s])
                months_q = [m for m in range(3 * q - 2, 3 * q + 1)]
                have = sum(by_m.get((Y, m), 0.0) for m in months_q if m in known_m)
                miss = sum(1 for m in months_q if m not in known_m)
                add = cur * miss / 3
                total += add
                rest_detail[s].append(f"{_qlabel(Y, q)} 預估 {_yi(cur)}（已公告 {_yi(have)}，補 {miss} 個月 {_yi(add)}）")
            rev_cur[s] = total
    g_cur = {s: (rev_cur[s] / ly_total - 1) if ly_total and s in rev_cur else None for s in SCN}
    steps.append({
        "n": 1, "title": "推估今年剩餘季別營收與全年總營收",
        "rule": ("歷史有旺季效應（過去 5 年下一季平均季增 "
                 f"{_pc(season_avg, 1)}）→ 樂觀取季增 {_pc(up, 1)}" if seasonal else
                 "下一季沒有明顯旺季效應 → 中性用「季平」（下一季＝最近完整一季）")
                + f"；保守用高檔季減 {_pc(cut, 0)}" + ("（大盤過熱，改季減 15%）" if hot else ""),
        "calc": [f"今年（{Y}）已公告 1–{last_m} 月營收合計 {_yi(actual_y)}；基準季 {base_q_label} 營收 {_yi(base_q_rev)}",
                 *[f"{s}（季增 {_pc(qoq[s], 1, True)}）：" + "；".join(rest_detail[s]) for s in SCN if rest_detail[s]],
                 *[f"{s}：{Y} 全年營收 ＝ {_yi(rev_cur.get(s))}，年增率 ＝ {_yi(rev_cur.get(s))} ÷ 去年 {_yi(ly_total)} − 1 ＝ {_pc(g_cur[s], 2)}"
                   for s in SCN if s in rev_cur]],
        "out": {s: {"rev": _r((rev_cur.get(s) or 0) / 100), "yoy": _r(g_cur[s], 4)} for s in SCN},
    })
    if not rev_cur or not ly_total:
        gaps.append("缺去年完整 12 個月營收")

    # ── 步驟二：明年營收（取半法／五年平均／近三月年化）──
    ann = {y: v for y, v in (inp.annual_rev or {}).items() if y < Y and _ok(v) and v > 0}
    for k in range(1, 7):
        mm = [by_m.get((Y - k, m)) for m in range(1, 13)]
        if all(_ok(v) for v in mm):
            ann[Y - k] = sum(mm)                     # 月營收完整的年度以月營收為準
    hist_yoy = [ann[y] / ann[y - 1] - 1 for y in sorted(ann) if (y - 1) in ann]
    avg5 = _mean(hist_yoy[-5:])
    last3 = [v for _, _, v in inp.months[-3:]]
    run3 = sum(last3) / 3 * 12 if len(last3) == 3 else None
    g_n = g_cur.get("中性")
    rules: dict[str, Number] = {}
    if _ok(g_n):
        rules["half"] = g_n / 2
        rules["half_minus10"] = g_n / 2 - 0.10
    if _ok(avg5):
        rules["avg5"] = avg5
    if _ok(run3) and rev_cur.get("中性"):
        rules["run3_10"] = run3 * 1.10 / rev_cur["中性"] - 1
        rules["run3_15"] = run3 * 1.15 / rev_cur["中性"] - 1
    high = _ok(g_n) and g_n >= HIGH_GROWTH
    if high:
        g_next = {"保守": rules["half_minus10"], "中性": rules["half"],
                  "樂觀": max(rules["half"], rules.get("run3_10", rules["half"]))}
        why2 = f"今年營收年增 {_pc(g_n, 1)} ≥ 20%，基期墊高 → 取半法（保守再減 10 個百分點）"
    else:
        base5 = avg5 if _ok(avg5) else (g_n if _ok(g_n) else 0.0)
        g_next = {"保守": min(base5, rules.get("half", base5)) - 0.03, "中性": base5,
                  "樂觀": max(base5, rules.get("run3_10", base5))}
        why2 = (f"今年營收年增 {_pc(g_n, 1)} 未達 20% → 以過去 5 年平均年增 {_pc(avg5, 1)} 為中性"
                if _ok(avg5) else "歷史年度營收不足 5 年 → 以今年年增率為中性")
    g_next = {s: max(-0.30, v) for s, v in g_next.items() if _ok(v)}
    rev_next = {s: rev_cur[s] * (1 + g_next[s]) for s in SCN if s in rev_cur and s in g_next}
    steps.append({
        "n": 2, "title": "推估明年全年營收", "rule": why2,
        "calc": [
            f"取半法：{_pc(g_n, 2)} ÷ 2 ＝ {_pc(rules.get('half'), 2)}；取半再減 10 個百分點 ＝ {_pc(rules.get('half_minus10'), 2)}",
            f"過去 5 年平均營收年增率 ＝ {_pc(avg5, 2)}（{len(hist_yoy[-5:])} 年）",
            f"近 3 個月平均月營收 × 12 ＝ {_yi(run3)}；再加 10%／15% 相當於明年年增 {_pc(rules.get('run3_10'), 1)}／{_pc(rules.get('run3_15'), 1)}",
            *[f"{s}：{Y + 1} 營收 ＝ {_yi(rev_cur.get(s))} ×（1 {g_next[s] * 100:+.2f}%）＝ {_yi(rev_next.get(s))}" for s in SCN if s in rev_next],
        ],
        "out": {s: {"rev": _r((rev_next.get(s) or 0) / 100), "yoy": _r(g_next.get(s), 4)} for s in SCN},
    })

    # ── 步驟三：純本業稅後淨利率與今年 EPS ──
    qs = inp.quarters[-8:]
    med_nonop = _median([q.nonop for q in qs])
    pure: list[tuple[str, float, bool]] = []
    for q in qs[-4:]:
        if not _ok(q.nm):
            continue
        oneoff = _ok(q.nonop) and (abs(q.nonop) >= ONE_OFF_NONOP or
                                   (_ok(med_nonop) and abs(q.nonop - med_nonop) >= 15))
        v = q.nm * (1 - q.nonop / 100) if oneoff else q.nm
        pure.append((q.label, v, oneoff))
    pm = [v for _, v, _ in pure]
    if len(pm) >= 4 and max(pm) > 0 and min(pm) > 0 and max(pm) / min(pm) >= 1.5:
        trimmed = sorted(pm)[1:-1]
        avg4 = _mean(trimmed)
        trim_note = f"四季差距大（最高 {max(pm):.2f}%／最低 {min(pm):.2f}%），刪掉最高與最低後平均"
    else:
        avg4 = _mean(pm)
        trim_note = "近四季平均"
    avg3 = _mean(pm[-3:])
    om8 = [q.om for q in qs if _ok(q.om)]
    om_top = bool(om8) and om8[-1] >= max(om8)
    om_down = len(om8) >= 2 and om8[-1] < om8[-2]
    if not _ok(avg4):
        gaps.append("缺近四季稅後淨利率")
        margin = {}
    else:
        margin = {"保守": min(avg4, avg3 if _ok(avg3) else avg4) - (0.5 if om_down else 0.0),
                  "中性": avg4,
                  "樂觀": max(avg4, avg3 if _ok(avg3) else avg4) + (1.0 if om_top else 0.5)}
        margin = {s: max(0.0, v) for s, v in margin.items()}
    pub = [q for q in inp.quarters if q.year == Y and _ok(q.eps)]
    eps_pub = sum(q.eps for q in pub)
    pub_qs = {q.q for q in pub}
    eps_cur: dict[str, float] = {}
    eps_lines = []
    for s in SCN:
        if s not in margin or s not in rev_cur:
            continue
        # 未公布財報的季別營收 ＝ 全年預估 − 已公布季別的實際營收
        unpub_rev = rev_cur[s] - sum(qrev.get((Y, q), 0.0) for q in pub_qs)
        e = eps_pub + unpub_rev * margin[s] / 100 / shares
        eps_cur[s] = e
        eps_lines.append(f"{s}：已公布 {Y}Q{','.join(str(x) for x in sorted(pub_qs)) or '—'} EPS 合計 {eps_pub:.2f} 元 ＋ "
                         f"未公布季別營收 {_yi(unpub_rev)} × 淨利率 {margin[s]:.2f}% ÷ 股數 {shares:,.1f} 百萬股 ＝ {e:.2f} 元")
    steps.append({
        "n": 3, "title": "設定純本業稅後淨利率，算今年預估 EPS",
        "rule": ("剔除一次性業外：業外佔稅前淨利 ≥ 20%（或偏離 8 季中位數 15 個百分點）的季別，淨利率乘上（1 − 業外佔比）還原本業；"
                 f"{trim_note}。保守取四季與三季平均較低者" + ("、營益率下滑再減 0.5 個百分點" if om_down else "")
                 + "；樂觀" + ("營益率創 8 季新高加 1 個百分點" if om_top else "加 0.5 個百分點")
                 + f"。股數用最新股本 {_yi(cap_now)} ÷ 10 元。"),
        "calc": [*[f"{lb} 稅後淨利率 {v:.2f}%" + ("（含一次性業外，已還原本業）" if o else "") for lb, v, o in pure],
                 f"近四季（{trim_note}）＝ {_n(avg4)}%；近三季平均 ＝ {_n(avg3)}%",
                 *[f"{s} 淨利率 ＝ {margin[s]:.2f}%" for s in SCN if s in margin],
                 *eps_lines],
        "out": {s: {"margin": _r(margin.get(s)), "eps": _r(eps_cur.get(s))} for s in SCN},
    })

    # ── 步驟四：明年 EPS ──
    eps_next = {s: rev_next[s] * margin[s] / 100 / shares for s in SCN if s in rev_next and s in margin}
    steps.append({
        "n": 4, "title": "計算明年預估 EPS（三情境）",
        "rule": "明年稅後淨利 ＝ 明年營收 × 淨利率；明年 EPS ＝ 明年淨利 ÷ 最新股數",
        "calc": [f"{s}：{_yi(rev_next[s])} × {margin[s]:.2f}% ＝ 淨利 {_yi(rev_next[s] * margin[s] / 100)}，÷ {shares:,.1f} 百萬股 ＝ {eps_next[s]:.2f} 元"
                 for s in SCN if s in eps_next],
        "out": {s: {"eps": _r(eps_next.get(s))} for s in SCN},
    })

    # ── 步驟五：配息率與殖利率反推 ──
    pays = [(y.year, y.div / y.eps) for y in inp.years[:6] if _ok(y.div) and _ok(y.eps) and y.eps > 0 and 0 < y.div / y.eps <= 1.2]
    eps_c = eps_cur.get("中性")
    last_eps = next((y.eps for y in inp.years if _ok(y.eps)), None)
    surge = _ok(eps_c) and _ok(last_eps) and last_eps > 0 and eps_c / last_eps - 1 >= 0.5
    if pays:
        pay = min(p for _, p in pays[:5])
        pay_note = f"近 {min(5, len(pays))} 年最低配息率 {pay * 100:.1f}%"
        if surge:
            pay = max(0.3, pay - 0.05)
            pay_note += "；今年獲利暴增 ≥ 50%，公司常保留資金，再下修 5 個百分點"
    else:
        pay, pay_note = None, "沒有足夠的配息紀錄"
    dps = eps_c * pay if _ok(eps_c) and _ok(pay) and eps_c > 0 else None
    cash_need = dps * shares if _ok(dps) else None
    yb = {f"{y * 100:g}%": (dps / y if _ok(dps) else None) for y in YIELD_BUY}
    ysell = dps / YIELD_SELL if _ok(dps) else None
    calc5 = ["歷年配息率：" + "、".join(f"{y} {p * 100:.0f}%" for y, p in pays[:6]) if pays else "歷年配息率：無",
             f"採用配息率 {_pc(pay, 1)}（{pay_note}）",
             f"預估每股現金股利 ＝ 今年中性 EPS {_n(eps_c)} × {_pc(pay, 1)} ＝ {_n(dps)} 元"]
    if _ok(cash_need):
        calc5.append(f"配息所需現金 ＝ {_n(dps)} × {shares:,.1f} 百萬股 ＝ {_yi(cash_need)}"
                     + (f"；帳上現金 {_yi(inp.cash)}（{'足夠' if inp.cash >= cash_need else '不足，配息恐打折'}）" if _ok(inp.cash) else ""))
    calc5 += [f"殖利率 {k} 防禦買進價 ＝ {_n(dps)} ÷ {k} ＝ {_n(v)} 元" for k, v in yb.items()]
    calc5.append(f"殖利率 5% 波段賣出價 ＝ {_n(dps)} ÷ 5% ＝ {_n(ysell)} 元")
    steps.append({"n": 5, "title": "配息率評估與現金股利殖利率反推", "rule": "獲利暴增時配息率常下降，取歷史相對低檔；高殖利率（6.5%~8%）反推防禦買點、5% 反推賣點",
                  "calc": calc5, "out": {"payout": _r(pay, 4), "dps": _r(dps), "yield_buy": {k: _r(v) for k, v in yb.items()}, "yield_sell": _r(ysell)}})

    # ── 步驟六：目標本益比區間（PEH／PEL）與折價 ──
    ytd = [c for d, c in inp.closes if d.startswith(str(Y))]
    ytd_hi = max(ytd) if ytd else None
    ytd_lo = min(ytd) if ytd else None
    cur_peh = ytd_hi / eps_c if _ok(ytd_hi) and _ok(eps_c) and eps_c > 0 else None
    cur_pel = ytd_lo / eps_c if _ok(ytd_lo) and _ok(eps_c) and eps_c > 0 else None
    mcap = inp.price * shares if _ok(inp.price) else None        # 百萬元
    story = classify(inp, cur_peh, cur_pel, eps_c, mcap)
    sid = story["primary"]
    hist = [y for y in inp.years[:5] if _ok(y.pe_high) and _ok(y.pe_low) and y.pe_low > 0]
    hist = [y for y in hist if y.pe_high <= 100] or hist      # 獲利極低的年度本益比失真（> 100 倍）不列入
    peh_hist = [y.pe_high for y in hist]
    pel_hist = [y.pe_low for y in hist]
    prev_peh = peh_hist[0] if peh_hist else None
    base_peh = cur_peh if _ok(cur_peh) else prev_peh
    rule6 = []
    if not _ok(base_peh):
        peh_next = None
        gaps.append("缺歷年本益比")
    elif base_peh >= PEH_HAIRCUT_TRIGGER or sid in (1, 10) and base_peh >= 40:
        peh_next = base_peh * PEH_HAIRCUT
        rule6.append(f"當年最高本益比 {base_peh:.2f} 倍偏高 → 打七折 ＝ {peh_next:.2f} 倍")
    elif sid == 4:
        peh_next = base_peh
        rule6.append(f"本益比被壓縮型：不再往下等比例遞減，等轉折確認後本益比溫和修復，取今年 PEH ＝ {peh_next:.2f} 倍")
    elif _ok(prev_peh) and 0.65 <= base_peh / prev_peh < 1:
        ratio = base_peh / prev_peh
        peh_next = base_peh * ratio
        rule6.append(f"PEH 收斂：今年 {base_peh:.2f} 倍較去年 {prev_peh:.2f} 倍減少 {(1 - ratio) * 100:.2f}% → 明年再等比例下調 ＝ {peh_next:.2f} 倍")
    elif _ok(prev_peh) and base_peh < prev_peh:
        peh_next = base_peh
        rule6.append(f"今年 PEH {base_peh:.2f} 倍比去年 {prev_peh:.2f} 倍低很多（多半是獲利暴增、本益比被動壓縮），不再等比例遞減，取今年 PEH")
    else:
        avg_h = _mean(peh_hist[:4] + [base_peh])
        peh_next = min(base_peh, avg_h) if _ok(avg_h) else base_peh
        rule6.append(f"PEH 沒有過熱也沒有收斂 → 取今年與近 4 年平均較低者 ＝ {peh_next:.2f} 倍")
    pel_pool = pel_hist[:4] + ([cur_pel] if _ok(cur_pel) else [])
    if sid in (1, 3, 6):
        pel_next = cur_pel if _ok(cur_pel) else (pel_hist[0] if pel_hist else None)
        rule6.append(f"PEL 墊高／強本益比型 → 採今年 PEL ＝ {_n(pel_next)} 倍")
    elif sid == 4 and pel_pool:
        pel_next = min(_median(pel_pool), cur_pel) if _ok(cur_pel) else _median(pel_pool)
        rule6.append(f"本益比被壓縮型：PEL 取今年與歷年中位數較低者 ＝ {pel_next:.2f} 倍（買點另以高殖利率反推）")
    elif sid == 10 and (_ok(cur_pel) or pel_pool):
        base_l = cur_pel if _ok(cur_pel) else _median(pel_pool)
        pel_next = base_l * 1.3
        rule6.append(f"千金股雙向收斂：PEH 下修 30%、PEL（今年 {base_l:.2f} 倍）上調 30% ＝ {pel_next:.2f} 倍")
    else:
        pel_next = _median(pel_pool)
        rule6.append(f"PEL 取近 4 年＋今年最低本益比的中位數 ＝ {_n(pel_next)} 倍")
    if _ok(pel_next) and _ok(peh_next) and pel_next >= peh_next:
        pel_next = peh_next * 0.5
        rule6.append("PEL 不得高於 PEH，改用 PEH 的一半")
    ph = {s: eps_next[s] * peh_next for s in eps_next} if _ok(peh_next) else {}
    pl = {s: eps_next[s] * pel_next for s in eps_next} if _ok(pel_next) else {}
    yield_model = sid == 2 and _ok(pay)
    if yield_model:
        # 景氣循環股：不硬套本益比，改用殖利率法（賣點 5%、低點 8%）；三情境的股利用各自的今年 EPS
        ph = {s: eps_cur[s] * pay / YIELD_SELL for s in eps_cur if eps_cur[s] > 0}
        pl = {s: eps_cur[s] * pay / YIELD_BUY[0] for s in eps_cur if eps_cur[s] > 0}
        rule6.append("景氣循環股改用殖利率法：目標高價 ＝ 預估股利 ÷ 5%，預估低價 ＝ 預估股利 ÷ 8%（各情境股利 ＝ 今年 EPS × 配息率）")
    steps.append({
        "n": 6, "title": "設定目標本益比區間（PEH／PEL）與估值折價",
        "rule": f"本益比故事：類別{sid}「{story['name']}」— {story['strategy']}",
        "calc": [*[f"{y.year}：最高價 {_n(y.high)}／最低價 {_n(y.low)}，EPS {_n(y.eps)} → PEH {_n(y.pe_high)} 倍／PEL {_n(y.pe_low)} 倍" for y in hist],
                 f"{Y}（今年到目前）：最高收盤 {_n(ytd_hi)}／最低收盤 {_n(ytd_lo)}，÷ 今年中性 EPS {_n(eps_c)} → PEH {_n(cur_peh)} 倍／PEL {_n(cur_pel)} 倍",
                 *rule6,
                 *([f"{s}：股利 {eps_cur[s] * pay:.2f} 元 → 目標高價 {ph[s]:,.1f} 元、預估低價 {pl[s]:,.1f} 元"
                    for s in SCN if s in ph and s in pl] if yield_model else
                   [f"{s}：明年目標高價 PH ＝ {eps_next[s]:.2f} × {peh_next:.2f} ＝ {ph[s]:,.1f} 元；預估低價 PL ＝ {eps_next[s]:.2f} × {pel_next:.2f} ＝ {pl[s]:,.1f} 元"
                    for s in SCN if s in ph and s in pl])],
        "out": {"peh": _r(peh_next), "pel": _r(pel_next), "ph": {s: _r(v, 1) for s, v in ph.items()}, "pl": {s: _r(v, 1) for s, v in pl.items()}},
    })

    # ── 步驟七：扣息成本、往上空間與往下風險 ──
    price = inp.price
    defensive = sid in DEFENSIVE_STORIES
    dn_max = DOWNSIDE_DEFENSIVE if defensive else DOWNSIDE_MAX
    up_req = macro["upside_req"]
    cost = price - dps if _ok(price) and _ok(dps) else price
    upside = {s: ph[s] / cost - 1 for s in ph} if _ok(cost) and cost > 0 else {}
    downside = {s: 1 - pl[s] / cost for s in pl} if _ok(cost) and cost > 0 else {}
    entry = None
    if "中性" in ph and "中性" in pl:
        e1 = ph["中性"] / (1 + up_req)
        e2 = pl["中性"] / (1 - dn_max)
        entry = min(e1, e2) + (dps or 0.0)
    steps.append({
        "n": 7, "title": "扣除現金股利成本，計算往上空間與往下風險",
        "rule": f"往上空間 ≥ {up_req * 100:.0f}%、往下風險 ≤ {dn_max * 100:.0f}%" + ("（防禦型個股）" if defensive else ""),
        "calc": [f"實質持有成本 ＝ 股價 {_n(price)} − 預估股利 {_n(dps)} ＝ {_n(cost)} 元",
                 *[f"{s}：往上空間 ＝ {ph[s]:,.1f} ÷ {cost:,.2f} − 1 ＝ {_pc(upside[s], 2)}；往下風險 ＝ 1 − {pl[s]:,.1f} ÷ {cost:,.2f} ＝ {_pc(downside[s], 2)}"
                   for s in SCN if s in upside and s in downside],
                 (f"同時滿足兩個門檻的最高買價（中性）＝ min（{ph['中性']:,.1f} ÷ {1 + up_req:.2f}，{pl['中性']:,.1f} ÷ {1 - dn_max:.2f}）＋ 股利 {_n(dps)} ＝ {entry:,.1f} 元"
                  if _ok(entry) else "缺目標價，無法反推進場價")],
        "out": {"cost": _r(cost), "upside": {s: _r(v, 4) for s, v in upside.items()},
                "downside": {s: _r(v, 4) for s, v in downside.items()}, "entry": _r(entry, 1)},
    })

    # ── 第六篇：下單前五道防線 ──
    defenses = []
    ok_n = _ok(upside.get("中性")) and _ok(downside.get("中性"))
    d1 = ok_n and upside["中性"] >= up_req and downside["中性"] <= dn_max
    defenses.append({"n": 1, "title": "空間與風險比", "pass": d1 if ok_n else None,
                     "why": (f"中性：往上 {_pc(upside.get('中性'), 1)}（要 ≥ {up_req * 100:.0f}%）、往下 {_pc(downside.get('中性'), 1)}（要 ≤ {dn_max * 100:.0f}%）"
                             if ok_n else "缺目標價")})
    closes = [c for _, c in inp.closes]
    ma240 = _mean(closes[-240:]) if len(closes) >= 200 else None
    hi250 = max(closes[-250:]) if closes else None
    dd = (closes[-1] / hi250 - 1) if closes and hi250 else None
    d2 = None
    if _ok(ma240) or _ok(dd):
        d2 = (_ok(ma240) and closes[-1] <= ma240 * 1.05) or (_ok(dd) and dd <= -0.25)
    defenses.append({"n": 2, "title": "均線與回檔幅度", "pass": d2,
                     "why": f"年線（240 日均）{_n(ma240)}，收盤 {_n(closes[-1] if closes else None)}；距一年高點 {_pc(dd, 1)}（要接近年線或回檔 ≥ 25%）"})
    ml = inp.margin_lots
    if len(ml) >= 21 and ml[20] > 0:
        chg = ml[0] / ml[20] - 1
        chg40 = (ml[0] / ml[40] - 1) if len(ml) >= 41 and ml[40] > 0 else None
        d3 = chg <= -0.10 or (_ok(chg40) and chg40 <= -0.10)
        defenses.append({"n": 3, "title": "融資與量能沉澱", "pass": d3,
                         "why": f"融資餘額 20 日 {_pc(chg, 1, True)}" + (f"、40 日 {_pc(chg40, 1, True)}" if _ok(chg40) else "") + "（要明顯減少 ≥ 10%）"})
    else:
        defenses.append({"n": 3, "title": "融資與量能沉澱", "pass": None, "why": "缺個股融資資料（市場監控同步後就會有）"})
    fn = inp.foreign_net
    if len(fn) >= 40:
        f5, f20, f40 = sum(fn[:5]), sum(fn[:20]), sum(fn[5:40])
        d4 = f5 > 0 and f40 < 0
        defenses.append({"n": 4, "title": "法人籌碼動向", "pass": d4 or (f20 > 0 and f5 > 0),
                         "why": f"外資近 5 日 {f5:+,.0f} 張、近 20 日 {f20:+,.0f} 張、前 35 日 {f40:+,.0f} 張（要由賣轉買）"})
    else:
        defenses.append({"n": 4, "title": "法人籌碼動向", "pass": None, "why": "外資買賣超資料不足 40 天"})
    ok_c = _ok(upside.get("保守")) and _ok(downside.get("保守"))
    d5 = ok_c and upside["保守"] >= up_req and downside["保守"] <= dn_max
    defenses.append({"n": 5, "title": "最保守參數壓力測試", "pass": d5 if ok_c else None,
                     "why": (f"保守：往上 {_pc(upside.get('保守'), 1)}、往下 {_pc(downside.get('保守'), 1)}；"
                             "營收季減、年增取半再減、淨利率下修、本益比打折後仍要過關" if ok_c else "缺保守情境")})

    # ── 最終決策 ──
    passed = sum(1 for d in defenses if d["pass"])
    known = sum(1 for d in defenses if d["pass"] is not None)
    over = _ok(price) and "中性" in ph and price > ph["中性"]
    near_top = _ok(price) and "中性" in ph and price >= ph["中性"] * 0.9
    if gaps and not ph:
        action, tone = "資料不足", "na"
        why = "；".join(gaps)
    elif over:
        action, tone = "價格高估", "dn"
        why = f"股價 {_n(price)} 已高於明年中性目標高價 {_n(ph['中性'], 1)}"
    elif near_top or (_ok(ysell) and _ok(price) and price >= ysell and sid in (2, 9)):
        action, tone = "持有者分批獲利了結", "warn"
        why = "接近目標高價（或殖利率已低於 5%）"
    elif crit["fails"]:
        action, tone = "觀望（體質未過斷捨離）", "warn"
        why = "；".join(i["title"] for i in crit["items"] if i["state"] == "fail") + " 不及格"
    elif defenses[0]["pass"] and defenses[4]["pass"] and passed >= 4:
        action, tone = "可分批買進", "up"
        why = f"五道防線通過 {passed}／{known}，保守壓力測試也過關"
    elif defenses[0]["pass"]:
        action, tone = "小量試單，等其餘防線", "mid"
        why = f"空間與風險比達標，五道防線通過 {passed}／{known}"
    else:
        action, tone = "等待買點", "mid"
        why = (f"股價還沒到位：中性情境的防禦進場價約 {_n(entry, 1)} 元" if _ok(entry) else "空間或風險未達門檻")
    zone = {
        "entry": _r(entry, 1),
        "yield_7": _r(yb.get("7%")), "yield_8": _r(yb.get("8%")),
        "ph": _r(ph.get("中性"), 1), "pl": _r(pl.get("中性"), 1), "ysell": _r(ysell),
    }
    return {
        "ok": True, "year": Y, "price": _r(price), "price_date": inp.price_date, "shares": _r(shares, 1),
        "macro": macro, "criteria": crit, "story": story, "steps": steps, "defenses": defenses,
        "decision": {"action": action, "tone": tone, "why": why, "passed": passed, "known": known, "zone": zone},
        "summary": {s: {"eps_cur": _r(eps_cur.get(s)), "eps_next": _r(eps_next.get(s)), "ph": _r(ph.get(s), 1),
                        "pl": _r(pl.get(s), 1), "up": _r(upside.get(s), 4), "down": _r(downside.get(s), 4)} for s in SCN},
        "gaps": gaps,
    }
