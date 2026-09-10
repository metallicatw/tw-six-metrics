"""每日全市場：收盤行情與三大法人買賣超。

**這個模組的每一條欄位規則都是從 `reference/samples/` 裡的真實回應讀出來的**，
不是從文件。四份樣本、四種版面，而且沒有一種和另一種一樣：

* 上市收盤 `STOCK_DAY_ALL`：英文欄名（`Code`/`ClosingPrice`），日期是民國
  `1150901`，1,377 筆。
* 上櫃收盤 `tpex_mainboard_daily_close_quotes`：另一組英文欄名
  （`SecuritiesCompanyCode`/`Close`），日期一樣是民國，但 **10,813 筆**——裡面
  絕大多數是 ETF、權證、債券。
* 上市三大法人 `T86`：中文欄名，而且是 `fields` + `data` 的二維陣列，日期是
  **西元** `20260902`，數字帶千分位逗號，證券名稱尾巴有空白。
* 上櫃三大法人 `tpex_3insti_daily_trading`：英文欄名，但欄名本身**排版不一致**
  ——`' Foreign Investors …-Total Sell'` 開頭有一個空格、`'Dealers -TotalSell'`
  中間有一個空格、`'ForeignInvestorsInclude MainlandAreaInvestors-Difference'`
  裡面有一個空格。所以欄位一律先正規化（去空白）再比對，否則會有一半的欄位
  安靜地讀成 None。

只留四位數字的代號。上櫃那 10,813 筆裡只有 887 筆是四位數，其餘是 ETF 與權證；
六大指標的母體是上市櫃**公司**，多存十倍的權證只是讓每天的檔案大十倍。

日期以**每一列自己帶的那個**為準，不是抓取當天：上市與上櫃的開放資料不一定同一
時間更新（樣本裡就差了一天），用抓取日命名會把兩天的資料寫進同一個檔案。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import HttpClient

TWSE_PRICES = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
#: 證交所網站自己用的每日收盤行情。
#:
#: 為什麼兩個來源都要：**openapi 那份會落後一個交易日**。實測台北時間 16:30
#: 它還停在前一天，而這一份在 00:36 已經是當天的。兩個都抓、照日期分堆，落後
#: 的那一份只是重複寫一次昨天的檔案（位元組一樣，不會產生 commit），而今天的
#: 價格有人補上。
TWSE_PRICES_WEB = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?type=ALLBUT0999&response=json"
)
TPEX_PRICES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"

#: 回補用：同樣兩個交易所，但指定某一個過去的交易日。
#:
#: 每日快照只有排程上線之後的那幾天，而〔外資投信〕圖上的股價要蓋滿 20 個交易
#: 日的視窗——不回補的話那條線要等四個星期才會長齊。
#:
#: 上市那個就是 `TWSE_PRICES_WEB` 加一個 `date`，回應結構一模一樣，所以
#: `parse_twse_mi_index` 原封不動就能用（樣本：twse_mi_index_dated）。
#: 上櫃的不是 openapi 那份（它只給今天），是網站自己用的那支，結構不同——
#: 見 `parse_tpex_rwd`（樣本：tpex_daily_rwd_dated）。
TWSE_PRICES_DATED = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
    "?date={ymd}&type=ALLBUT0999&response=json"
)
TPEX_PRICES_DATED = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/otc"
    "?date={y}/{m}/{d}&type=EW&response=json"
)
#: `openapi.twse.com.tw/v1/fund/T86` 回的是一頁 1 KB 的 HTML，不是資料
#: （`reference/samples/twse_t86_openapi` 就是那一頁）。真的在這裡。
TWSE_INSTITUTIONAL = "https://www.twse.com.tw/rwd/zh/fund/T86?selectType=ALL&response=json"
TPEX_INSTITUTIONAL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"

#: 帶日期的版本。上市就是 T86 加一個 `date=YYYYMMDD`，回應結構一模一樣，
#: `parse_twse_institutional` 原封不動就能用（樣本：twse_t86_rwd_dated）。
#: ⚠️ 打太密會回 307 —— 那是 WAF 不是限流，重試沒有用，要拉開間隔。
#:
#: 上櫃不是 openapi 那份（它只給今天、沒有日期參數），是網站自己用的那支，
#: 回的是位置陣列而且欄名重複，所以另有一支 parser
#: （`parse_tpex_institutional_dated`，樣本：tpex_insti_rwd_dated）。
TWSE_INSTITUTIONAL_DATED = (
    "https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALL&response=json"
)
TPEX_INSTITUTIONAL_DATED = (
    "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={y}/{m}/{d}"
)

#: 交易日以台北時間為準。排程跑在 UTC 的 runner 上，直接用 `date.today()`
#: 會在台北時間深夜跨日時指到前一天。
TAIPEI = timezone(timedelta(hours=8))

PRICE_COLUMNS: tuple[str, ...] = (
    "date", "code", "market", "close", "open", "high", "low", "change", "volume",
)
INSTITUTIONAL_COLUMNS: tuple[str, ...] = (
    "date", "code", "market", "foreign", "trust", "dealer", "total",
)

_CODE = re.compile(r"^\d{4}$")


def _key(name: str) -> str:
    """欄名正規化：去掉所有空白。上櫃法人那份的欄名排版不一致，這是唯一穩的比法。"""
    return "".join(str(name).split())


def _pick(row: dict[str, Any], *names: str) -> Any:
    wanted = {_key(n) for n in names}
    for k, v in row.items():
        if _key(k) in wanted:
            return v
    return None


def _num(value: Any) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text or text in ("--", "---", "N/A", "－", "null"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date(value: Any) -> str:
    """`1150902`（民國）或 `20260902`（西元）都換成 `2026-09-02`。

    兩種都出現在真實回應裡，而且分屬不同的端點——所以這裡看長度，不猜。
    """
    text = str(value or "").strip().replace("/", "").replace("-", "")
    if len(text) == 7 and text.isdigit():  # 民國 1150902
        return f"{int(text[:3]) + 1911:04d}-{text[3:5]}-{text[5:7]}"
    if len(text) == 8 and text.isdigit():  # 西元 20260902
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return ""


def parse_twse_prices(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(row.get("Code", "")).strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(row.get("Date")),
                "code": code,
                "market": "上市",
                "close": _num(row.get("ClosingPrice")),
                "open": _num(row.get("OpeningPrice")),
                "high": _num(row.get("HighestPrice")),
                "low": _num(row.get("LowestPrice")),
                "change": _num(row.get("Change")),
                "volume": _num(row.get("TradeVolume")),
            }
        )
    return out


def parse_tpex_prices(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(_pick(row, "SecuritiesCompanyCode") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(_pick(row, "Date")),
                "code": code,
                "market": "上櫃",
                "close": _num(_pick(row, "Close")),
                "open": _num(_pick(row, "Open")),
                "high": _num(_pick(row, "High")),
                "low": _num(_pick(row, "Low")),
                "change": _num(_pick(row, "Change")),
                "volume": _num(_pick(row, "TradingShares")),
            }
        )
    return out


def parse_twse_mi_index(payload: Any) -> list[dict[str, Any]]:
    """證交所網站的每日收盤行情。**表要用標題找，不是用索引**。

    這個回應裡有十張表（價格指數、報酬指數、大盤統計、漲跌家數……），每日收盤行
    情只是其中一張，而它現在排在第九個——那是今天的排列，不是承諾。

    「漲跌(+/-)」欄放的是一段 HTML（`<p style= color:green>-</p>`），漲跌的**數字**
    在另一欄。所以方向要從那段標記裡取，不能直接當數字讀。
    """
    tables = (payload or {}).get("tables") or ()
    table = next(
        (t for t in tables if "每日收盤行情" in str(t.get("title", ""))), None
    )
    if not table:
        return []
    fields = [_key(f) for f in table.get("fields") or ()]
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], name: str) -> Any:
        i = index.get(_key(name))
        return row[i] if i is not None and i < len(row) else None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in table.get("data") or ():
        code = str(at(row, "證券代號") or "").strip()
        if not _CODE.match(code):
            continue
        change = _num(at(row, "漲跌價差"))
        if change is not None and "-" in _tag_text(at(row, "漲跌(+/-)")):
            change = -change
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上市",
                "close": _num(at(row, "收盤價")),
                "open": _num(at(row, "開盤價")),
                "high": _num(at(row, "最高價")),
                "low": _num(at(row, "最低價")),
                "change": change,
                "volume": _num(at(row, "成交股數")),
            }
        )
    return out


def parse_tpex_rwd(payload: Any) -> list[dict[str, Any]]:
    """櫃買網站自己用的每日收盤行情（帶日期那一支）。

    和上市那份的形狀**不一樣**，所以不能共用 parser：

    * 只有一張表，但仍然照標題找而不是照索引取——索引是今天的排列，不是承諾。
    * 欄名帶著空白與 HTML（`'收盤 '`、`'最後買量<br>(張數)'`），所以用 `_key`
      正規化之後再對，不能直接字串相等。
    * 漲跌是一欄合起來的（`'+0.08'`），不像上市那份把方向放在另一欄的 HTML 裡。

    日期取**頂層**那個 `date`（`20260901`）而不是表內那個（`115/09/01`）：兩者
    指同一天，但前者已經是西元，和其他來源寫進檔案的格式一致。

    樣本：`reference/samples/tpex_daily_rwd_dated`（1,014 列，其中 888 檔是四碼
    上櫃股票，其餘是 ETF 與受益證券，由 `_CODE` 擋掉）。
    """
    tables = (payload or {}).get("tables") or ()
    table = next(
        (t for t in tables if "每日收盤行情" in str(t.get("title", ""))), None
    )
    if not table:
        return []
    fields = [_key(f) for f in table.get("fields") or ()]
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], name: str) -> Any:
        i = index.get(_key(name))
        return row[i] if i is not None and i < len(row) else None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in table.get("data") or ():
        code = str(at(row, "代號") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上櫃",
                "close": _num(at(row, "收盤")),
                "open": _num(at(row, "開盤")),
                "high": _num(at(row, "最高")),
                "low": _num(at(row, "最低")),
                "change": _num(at(row, "漲跌")),
                "volume": _num(at(row, "成交股數")),
            }
        )
    return out


def _tag_text(value: Any) -> str:
    """`<p style= color:green>-</p>` -> `-`。"""
    return re.sub(r"<[^>]*>", "", str(value or "")).strip()


def merge_prices(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把幾個來源併起來，同一天同一檔只留一列。

    兩個上市來源會重疊（openapi 落後的那一天，網站那份也有），重複寫進同一個檔案
    只會讓列數變兩倍，而不是讓資料變新。
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        for row in group:
            key = (str(row.get("date") or ""), str(row.get("code") or ""))
            if key[0] and key[1] and key not in seen:
                seen[key] = row
    return list(seen.values())


def parse_twse_institutional(payload: Any) -> list[dict[str, Any]]:
    """`fields` + `data` 的二維陣列，欄位靠**名字**對，不靠位置。

    靠位置就是活頁簿當年 `CFQ!59` 那種寫法：欄位插一欄，全部往右移一格，而且
    不會有任何錯誤訊息。
    """
    fields = [_key(f) for f in (payload or {}).get("fields") or ()]
    if not fields:
        return []
    index = {name: i for i, name in enumerate(fields)}

    def at(row: list[Any], *names: str) -> Any:
        for n in names:
            i = index.get(_key(n))
            if i is not None and i < len(row):
                return row[i]
        return None

    day = _date((payload or {}).get("date"))
    out: list[dict[str, Any]] = []
    for row in (payload or {}).get("data") or ():
        code = str(at(row, "證券代號") or "").strip()
        if not _CODE.match(code):
            continue
        foreign = _num(at(row, "外陸資買賣超股數(不含外資自營商)"))
        dealer_self = _num(at(row, "自營商買賣超股數(自行買賣)"))
        dealer_hedge = _num(at(row, "自營商買賣超股數(避險)"))
        dealer = _num(at(row, "自營商買賣超股數"))
        if dealer is None and (dealer_self is not None or dealer_hedge is not None):
            dealer = (dealer_self or 0) + (dealer_hedge or 0)
        out.append(
            {
                "date": day,
                "code": code,
                "market": "上市",
                "foreign": foreign,
                "trust": _num(at(row, "投信買賣超股數")),
                "dealer": dealer,
                "total": _num(at(row, "三大法人買賣超股數")),
            }
        )
    return out


def parse_tpex_institutional(payload: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in payload or ():
        code = str(_pick(row, "SecuritiesCompanyCode") or "").strip()
        if not _CODE.match(code):
            continue
        out.append(
            {
                "date": _date(_pick(row, "Date")),
                "code": code,
                "market": "上櫃",
                # 欄名裡的空白位置每一欄都不一樣，所以比對前先把空白全部去掉。
                "foreign": _num(
                    _pick(row, "ForeignInvestorsIncludeMainlandAreaInvestors-Difference")
                ),
                "trust": _num(_pick(row, "SecuritiesInvestmentTrustCompanies-Difference")),
                "dealer": _num(_pick(row, "Dealers-Difference")),
                "total": _num(_pick(row, "TotalDifference")),
            }
        )
    return out


#: 上櫃逐日三大法人：`tables[0].fields` 裡的欄名是重複的（買進股數／賣出股數／
#: 買賣超股數 各出現八次），所以只能靠位置。位置從實際回應數出來，不是從文件抄的：
#:
#:   2~4   外資及陸資（不含外資自營商）
#:   5~7   外資自營商
#:   8~10  外資及陸資合計          ← foreign
#:   11~13 投信                    ← trust
#:   14~16 自營商（自行買賣）
#:   17~19 自營商（避險）
#:   20~22 自營商合計              ← dealer
#:   23    三大法人買賣超股數合計   ← total
_TPEX_INSTI_COLS = {"foreign": 10, "trust": 13, "dealer": 22, "total": 23}
_TPEX_INSTI_MIN_COLS = 24


def parse_tpex_institutional_dated(payload: Any) -> list[dict[str, Any]]:
    """上櫃某一個過去交易日的三大法人買賣超。

    openapi 那支（`parse_tpex_institutional`）只給「今天」，沒有日期參數，所以
    歷史補不回來。這一支打的是網頁版的
    `insti/dailyTrade?type=Daily&sect=EW&date=YYYY/MM/DD`，實測 date 是真的有效
    （不同日期回不同的列數與數字，非交易日回空的 data）。

    **位置對應要自己驗算，不能只相信位置。** 欄名全是重複的，所以萬一哪天欄序
    變了，靠位置取出來的數字會是別欄的值——而且完全不會報錯，只會在報告上出現
    一組看起來很正常的錯誤數字。這裡的守門是這張表自己的恆等式：

        三大法人合計 = 外資合計 + 投信 + 自營商合計

    逐列驗算，對不上的比例超過一成就整批拒收，回空的 list。呼叫端看到空的會
    當作「這天沒抓到」，既有資料不動——比默默寫進錯誤數字好得多。
    """
    tables = (payload or {}).get("tables") or []
    table = tables[0] if tables else {}
    rows = table.get("data") or []
    if not rows:
        return []
    day = _date(str(table.get("date") or (payload or {}).get("date") or ""))

    out: list[dict[str, Any]] = []
    checked = bad = 0
    for row in rows:
        if len(row) < _TPEX_INSTI_MIN_COLS:
            continue
        code = str(row[0] or "").strip()
        if not _CODE.match(code):
            continue
        vals = {k: _num(row[i]) for k, i in _TPEX_INSTI_COLS.items()}
        # 恆等式驗算。三個分項都有值才算得動；有 None 就不列入判斷（不是錯誤）。
        parts = (vals["foreign"], vals["trust"], vals["dealer"])
        if vals["total"] is not None and all(v is not None for v in parts):
            checked += 1
            if sum(parts) != vals["total"]:
                bad += 1
        out.append({"date": day, "code": code, "market": "上櫃", **vals})

    if checked and bad / checked > 0.10:
        print(
            f"    ⚠️ 上櫃三大法人 {day}：{bad}/{checked} 列的"
            "「合計 = 外資 + 投信 + 自營商」對不上，欄序可能變了，整批不採用。"
        )
        return []
    return out


def by_date(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """依每一列自己帶的日期分堆。上市與上櫃不一定同一天更新。"""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = str(row.get("date") or "")
        if day:
            out.setdefault(day, []).append(row)
    return out


class Daily:
    """四個端點，四個請求，換到整個市場的當日行情與法人買賣超。"""

    def __init__(self, http: HttpClient):
        self.http = http
        #: 這一輪有哪個來源沒拿到。呼叫端要把它變成 `::warning::`——
        #: 原本只是印一行字，混在幾十行輸出中間，而 workflow 照樣成功、照樣
        #: commit 一份少了半個市場的檔案。沒有人會去讀那一行。
        self.problems: list[str] = []

    def _json(self, url: str) -> Any:
        raw = self.http.get(url, use_cache=False)
        return json.loads(raw.decode("utf-8-sig", errors="replace"))

    def prices(self, day: str | None = None) -> list[dict[str, Any]]:
        """三個來源：上市兩個（開放資料與網站）、上櫃一個，上櫃再加一個備援。

        上市抓兩份不是保險，是因為**它們不同步**：開放資料那份實測會落後一個交
        易日。哪一份先有今天的資料，今天的價格就從哪一份來。任何一份掛掉，其餘
        照樣存——一個端點失敗不該把另外兩個抓好的資料丟掉。

        上櫃只有一個來源，所以它掛掉就是**半個市場不見**。備援見
        `_tpex_by_date()`。
        """
        groups: list[list[dict[str, Any]]] = []
        for url, parse in (
            (TWSE_PRICES, parse_twse_prices),
            (TWSE_PRICES_WEB, parse_twse_mi_index),
            (TPEX_PRICES, parse_tpex_prices),
        ):
            try:
                groups.append(parse(self._json(url)))
            except Exception as exc:  # noqa: BLE001 - 一個來源掛掉不該拖垮其餘
                self.problems.append(f"{url.split('/')[2]} 沒拿到：{exc}")
                print(f"    （{url.split('/')[2]} 沒拿到：{exc}）")

        rows = merge_prices(*groups)
        if not any(r.get("market") == "上櫃" for r in rows):
            iso = day or datetime.now(TAIPEI).date().isoformat()
            extra = self._tpex_by_date(iso)
            if extra:
                rows = merge_prices(rows, extra)
        return rows

    def _tpex_by_date(self, iso: str) -> list[dict[str, Any]]:
        """上櫃收盤的備援來源：交易所網站自己用的那支，指定日期。

        為什麼需要備援：`TPEX_PRICES`（openapi 那支）的回應是 **4.3 MB**，裡面
        一萬多筆絕大多數是權證與 ETF，真正要的上櫃股票只有八百多檔。實測它會
        **傳到一半被切斷**（`transfer closed with N bytes remaining`），而且每次
        斷在不同的位元組數——這不是逾時，所以調高 timeout 沒有用。

        這一支是同一個交易所的另一個端點，回應 146 KB、只含上櫃股票，實測連打
        三次都完整。程式與 parser 都是回補（`prices_on`）本來就在用的，
        這裡只是把它接到當日這條路上。

        拿不到就記進 `problems` 讓呼叫端變成 `::warning::`，不丟例外——備援失敗
        不該把已經抓好的上市資料一起拖掉。
        """
        y, m, d = iso.split("-")
        url = TPEX_PRICES_DATED.format(y=y, m=m, d=d)
        try:
            rows = parse_tpex_rwd(self._json(url))
        except Exception as exc:  # noqa: BLE001 - 備援失敗不該拖垮已經抓好的
            self.problems.append(f"上櫃備援（{iso}）也沒拿到：{exc}")
            print(f"    （上櫃備援 {iso} 也沒拿到：{exc}）")
            return []
        if not rows:
            # 非交易日兩邊都回空表，這不是錯誤。真的是交易日卻空的話，
            # 呼叫端那道「完全沒有上櫃的資料」的檢查會接住。
            print(f"    （上櫃備援 {iso} 回空表，可能是非交易日）")
            return []
        print(f"    （上櫃改用備援來源 {iso}，取得 {len(rows)} 檔）")
        return rows

    def prices_on(self, day: str) -> list[dict[str, Any]]:
        """某一個過去交易日的全市場收盤。*day* 是 `YYYY-MM-DD`。

        兩個交易所各一個請求。非交易日兩邊都回空表（不是錯誤），所以呼叫端拿到
        空 list 的意思是「那天沒有開市」，不需要另外判斷行事曆。

        一邊掛掉不把另一邊丟掉——理由和 `prices()` 一樣，只是這裡連 `problems`
        都不記：回補是補歷史，少一天下次再補就好，不該讓整批停下來。
        """
        y, m, d = day.split("-")
        out: list[dict[str, Any]] = []
        for url, parse in (
            (TWSE_PRICES_DATED.format(ymd=f"{y}{m}{d}"), parse_twse_mi_index),
            (TPEX_PRICES_DATED.format(y=y, m=m, d=d), parse_tpex_rwd),
        ):
            try:
                out += parse(self._json(url))
            except Exception as exc:  # noqa: BLE001
                print(f"    （{url.split('/')[2]} {day} 沒拿到：{exc}）")
        return out

    def institutional(self) -> list[dict[str, Any]]:
        return parse_twse_institutional(
            self._json(TWSE_INSTITUTIONAL)
        ) + parse_tpex_institutional(self._json(TPEX_INSTITUTIONAL))

    def institutional_on(self, day: str) -> list[dict[str, Any]]:
        """某一個過去交易日的全市場三大法人買賣超。*day* 是 `YYYY-MM-DD`。

        跟 `prices_on` 同一個形狀：兩個交易所各一個請求，非交易日兩邊都回空表
        （不是錯誤），一邊掛掉不把另一邊丟掉。

        存在的理由：每日排程用的那兩個端點都只給「今天」。上櫃那支是 openapi，
        連日期參數都沒有——所以在找到這一支網頁版之前，昨天以前的三大法人是
        「錯過就沒有了」。
        """
        y, m, d = day.split("-")
        out: list[dict[str, Any]] = []
        for url, parse in (
            (TWSE_INSTITUTIONAL_DATED.format(ymd=f"{y}{m}{d}"), parse_twse_institutional),
            (TPEX_INSTITUTIONAL_DATED.format(y=y, m=m, d=d), parse_tpex_institutional_dated),
        ):
            try:
                out += parse(self._json(url))
            except Exception as exc:  # noqa: BLE001
                print(f"    （{url.split('/')[2]} {day} 沒拿到：{exc}）")
        return out
