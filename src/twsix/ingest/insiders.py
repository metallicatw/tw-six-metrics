"""公開資訊觀測站 董監事持股餘額明細 —— 〔董監持股〕的原始來源.

和〔大戶持股〕同一個道理：Goodinfo 只是把這份公開資料整理過。直接向源頭要，
而且一次要整個市場。

    上市　https://openapi.twse.com.tw/v1/opendata/t187ap11_L
    上櫃　https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O

兩個請求涵蓋 1,975 家公司，每月更新（月報申報期限是次月 15 日）。一列一個人：

    {"出表日期":"1150820","資料年月":"11507","公司代號":"5439","公司名稱":"高技",
     "職稱":"董事長本人","姓名":"張景山","目前持股":"2402000","設質股數":"0", ...}

比 Goodinfo 多的是**逐人明細**——誰持有多少、質押多少，看得到名字。

## 「全體董監」怎麼算

這份表除了董監，也含經理人（總經理、副總、財會主管）與「其他」，而且同一個人
會出現在多列（李泰輝同時是董事與總經理，同一筆 850,000 股）。整份直接加總會
重複計算。

規則：**職稱含「董事」或「監察人」，且不含「法人代表人」。**

後半條是關鍵。法人董事（久舜投資、景玉投資）本身是董事，它指派的自然人代表
另有自己的持股；代表人不是董事，法人才是。5439 這一期：

    含代表人　11,035,189 股 = 11,035 張
    去代表人　10,014,687 股 = 10,015 張　← Goodinfo 顯示的數字

10,015 張、10.8%、質押 0——三個數字全中。這條規則是**對出來的**，不是從法規
文字推的。

## 持股比例的分母

Goodinfo 標「發行張數」，但它的值和集保庫存合計一模一樣（5439：9.298 萬張）。
所以這裡也用 TDCC 的合計當分母，兩張表因此互相咬合，不必再引第三個來源。
大型股上兩者相差 0.1% 以內（台積電集保 25,932,370 千股 vs 發行 25,930,380）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .base import HttpClient

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O"
SHEET = "董監持股"

ALL = "全體董監持股"
INDEPENDENT = "獨立董監持股"

COLUMNS: tuple[str, ...] = (
    "月別",
    "發行張數(萬張)",
    f"{ALL}-持股張數",
    f"{ALL}-持股(%)",
    f"{ALL}-持股增減",
    f"{ALL}-質押張數",
    f"{ALL}-質押(%)",
    f"{INDEPENDENT}-持股張數",
    f"{INDEPENDENT}-持股(%)",
)


class NotInsiderData(Exception):
    """回應不是董監事持股餘額明細。"""


def is_director(title: str) -> bool:
    """這一列算不算「董監」。

    法人代表人不算——法人本身才是董事，而它已經自己佔一列。少了這半條，5439
    會多出 1,020 張，Goodinfo 的數字就對不起來。
    """
    if "法人代表人" in title:
        return False
    return "董事" in title or "監察人" in title


def month_label(roc: str) -> str:
    """「11507」-> 「2026/07」。"""
    t = (roc or "").strip()
    if len(t) != 5 or not t.isdigit():
        raise NotInsiderData(f"看不懂的資料年月：{roc!r}")
    return f"{int(t[:3]) + 1911}/{t[3:]}"


@dataclass(frozen=True)
class Person:
    title: str
    name: str
    held: int
    pledged: int


@dataclass(frozen=True)
class Company:
    stock_id: str
    name: str
    month: str  # 2026/07
    people: tuple[Person, ...]

    def _sum(self, only_independent: bool = False) -> tuple[int, int]:
        """董監持股合計。**同一個持有人只算一次。**

        一個法人董事可以占好幾席，而明細是**一席一列**——每一列都帶著那個法人
        自己的全部持股。統一（1216）的高權投資就占了三席：董事長本人一列、董事
        本人兩列，三列都寫著同樣的 284,330,536 股。

        逐列相加會把那一塊算三次：1,130,457 張，實際是 561,796 張，多了一倍。
        質押更整齊——240,090 張正好是 80,030 的三倍。

        這個洞是使用者從 Goodinfo 匯入 1216 的歷史時撞出來的：兩邊差了兩倍，
        而扣掉重複的兩次之後**一股不差**。5439 沒撞到，因為它的董事沒有人占兩席。

        以姓名（法人就是公司名）去重。同一家公司的董事會裡兩個同名的人，比起
        把同一塊股票數三次，是遠小的風險。
        """
        held = pledged = 0
        seen: set[str] = set()
        for p in self.people:
            if not is_director(p.title):
                continue
            if only_independent and "獨立" not in p.title:
                continue
            if p.name in seen:
                continue
            seen.add(p.name)
            held += p.held
            pledged += p.pledged
        return held, pledged

    @property
    def held(self) -> int:
        return self._sum()[0]

    @property
    def pledged(self) -> int:
        return self._sum()[1]

    @property
    def independent_held(self) -> int:
        return self._sum(only_independent=True)[0]


def _int(value: Any) -> int:
    text = str(value or "").strip().replace(",", "")
    if not text or text in ("-", "—"):
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse(records: Iterable[Mapping[str, Any]]) -> dict[str, Company]:
    """一份（或兩份合起來的）明細 -> 依公司代號索引。

    兩個交易所的欄名差一個尾隨空白（上市是 ``"選任時持股 "``），這裡沒用到那一欄，
    但提醒了一件事：欄名照抄，不要自己整理。
    """
    bags: dict[str, list[Person]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for row in records:
        code = str(row.get("公司代號") or "").strip()
        if not code:
            continue
        title = str(row.get("職稱") or "").strip()
        bags.setdefault(code, []).append(
            Person(
                title=title,
                name=str(row.get("姓名") or "").strip(),
                held=_int(row.get("目前持股")),
                pledged=_int(row.get("設質股數")),
            )
        )
        if code not in meta:
            meta[code] = (
                str(row.get("公司名稱") or "").strip(),
                month_label(str(row.get("資料年月") or "")),
            )
    if not bags:
        raise NotInsiderData("整份沒有任何一列")
    return {
        code: Company(
            stock_id=code, name=meta[code][0], month=meta[code][1], people=tuple(people)
        )
        for code, people in bags.items()
    }


@dataclass
class Insiders:
    http: HttpClient

    def fetch(self) -> dict[str, Company]:
        """上市 + 上櫃，兩個請求。

        一邊掛掉時不整批失敗：一半的市場好過沒有市場，而且缺哪一邊看得出來
        （回傳的公司數會少一大截）。
        """
        out: dict[str, Company] = {}
        errors: list[str] = []
        for url in (TWSE_URL, TPEX_URL):
            try:
                out.update(parse(self.http.get_json(url)))
            except Exception as exc:  # noqa: BLE001 - 另一邊還有機會
                errors.append(f"{url}: {exc}")
        if not out:
            raise NotInsiderData("；".join(errors) or "兩個交易所都沒有資料")
        return out


def row(company: Company, *, custody_shares: int | None) -> list[str]:
    """一列格線，欄位順序同 :data:`COLUMNS`。持股增減留白，由 :func:`grid` 補。"""

    def lots(shares: int) -> str:
        return f"{shares / 1000:,.0f}"

    def pct(shares: int) -> str:
        if not custody_shares:
            return ""
        return f"{shares / custody_shares * 100:.2f}"

    held, pledged = company._sum()
    ind_held, _ = company._sum(only_independent=True)
    return [
        company.month,
        f"{custody_shares / 10_000_000:.3f}" if custody_shares else "",
        lots(held),
        pct(held),
        "",  # 持股增減：要有上一個月才算得出來
        lots(pledged),
        f"{pledged / held * 100:.2f}" if held else "",
        lots(ind_held),
        pct(ind_held),
    ]


def grid(rows: Sequence[Sequence[str]]) -> list[list[str]]:
    """補上「持股增減」並排成新到舊。

    增減是「和上一個月比」，所以它不是抓回來的資料，是兩列之間的關係——只有在
    兩列都在手上時才算得出來。缺了上一個月就留白，不要填 0：0 的意思是「沒有
    變動」，留白的意思是「不知道」。
    """
    ordered = sorted(rows, key=lambda r: str(r[0]), reverse=True)
    at_lots = COLUMNS.index(f"{ALL}-持股張數")
    at_delta = COLUMNS.index(f"{ALL}-持股增減")
    out: list[list[str]] = []
    for i, raw in enumerate(ordered):
        cells = [str(c) for c in raw]
        older = ordered[i + 1] if i + 1 < len(ordered) else None
        if older is not None:
            try:
                now = float(cells[at_lots].replace(",", ""))
                was = float(str(older[at_lots]).replace(",", ""))
                cells[at_delta] = f"{now - was:+,.0f}" if now != was else "0"
            except ValueError:
                cells[at_delta] = ""
        out.append(cells)
    return [list(COLUMNS), *out]
