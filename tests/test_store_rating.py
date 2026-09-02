"""抓一檔股票之後，清單上那一列要跟著動。

在這之前，「立即更新」只更新個股頁；清單那一列還是活頁簿匯入時的快照。
同一個網站上兩個數字互相矛盾，而且沒有任何一處說明為什麼——讀者看到的是
個股頁寫 2026.2Q、清單寫 2025.2Q 的同一檔股票。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from twsix.cli import _store_rating, _vintage
from twsix.store.snapshots import RATING_COLUMNS, Store


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


class _Snap:
    def __init__(self, quarter: str, month: str, composite: float | None):
        self.fiscal_quarter = quarter
        self.revenue_month = month
        self.composite = composite
        self.composite_display = "數據不足" if composite is None else f"{composite:g}"
        self.indicators = {
            k: SimpleNamespace(display="", letter="A", values=[], reason="")
            for k in (
                "revenue_yoy", "operating_margin", "net_income_yoy",
                "eps", "inventory_turnover", "free_cash_flow",
            )
        }


class _Rating:
    """rating_rows() 只用到這幾個屬性；用真的 StockRating 會把測試綁進評分引擎。"""

    def __init__(self, stock_id: str, quarter: str, month: str, name: str = ""):
        self.stock_id = stock_id
        self.name = name
        self.market = ""
        self.industry = ""
        self.snapshots = [_Snap(quarter, month, 3.5), _Snap("2025.4Q", "114/12", 3.0)]

    def value_picks(self):
        return [True, False]


def _seed(root: Path, **over: str) -> None:
    base = {c: "" for c in RATING_COLUMNS}
    rows = []
    for code, name, industry in (("1101", "台泥", "水泥工業"), ("5439", "高技", "電子零組件業")):
        row = dict(base)
        row.update(
            stock_id=code, name=name, market="上市", industry=industry,
            period_index="1", fiscal_quarter="2025.2Q", revenue_month="114/08",
            composite="1",
        )
        row.update(over if code == "5439" else {})
        rows.append(row)
    Store(root).write("ratings", rows, RATING_COLUMNS,
                      sort_by=("stock_id", "period_index"))


def test_a_fresh_fetch_replaces_that_stocks_rows_and_nobody_elses():
    root = _tmp()
    _seed(root)
    _store_rating(root, _Rating("5439", "2026.2Q", "115/07", name="高技"))

    rows = Store(root).read("ratings")
    mine = [r for r in rows if r["stock_id"] == "5439"]
    assert len(mine) == 2                      # 兩期，取代原本的一列
    assert mine[0]["fiscal_quarter"] == "2026.2Q"
    others = [r for r in rows if r["stock_id"] == "1101"]
    assert len(others) == 1 and others[0]["fiscal_quarter"] == "2025.2Q"


def test_the_market_and_industry_survive_an_update():
    """個股報表上沒有「產業」——那一欄只存在於活頁簿的全市場清單。

    這是真的踩過的坑：更新一檔股票會把它的產業清空，於是它從清單的產業篩選和
    搜尋索引裡消失。更新一檔的代價變成弄丟它。
    """
    root = _tmp()
    _seed(root)
    _store_rating(root, _Rating("5439", "2026.2Q", "115/07"))

    row = next(r for r in Store(root).read("ratings")
               if r["stock_id"] == "5439" and r["period_index"] == "1")
    assert row["industry"] == "電子零組件業"
    assert row["market"] == "上市"
    assert row["name"] == "高技"


def test_an_older_fetch_does_not_overwrite_a_newer_row():
    """抓取會失敗成「拿到一份比較短的資料」，而不是明白地失敗。

    那種時候維持舊值比較好：清單上一個過期但完整的評等，仍然是一個評等；
    用半份資料蓋掉它，得到的是一個看起來一樣正常、其實錯的評等。
    """
    root = _tmp()
    _seed(root, fiscal_quarter="2026.2Q", revenue_month="115/07", composite="3.17")
    _store_rating(root, _Rating("5439", "2025.4Q", "114/12"))

    row = next(r for r in Store(root).read("ratings")
               if r["stock_id"] == "5439" and r["period_index"] == "1")
    assert row["fiscal_quarter"] == "2026.2Q"
    assert row["composite"] == "3.17"


def test_the_same_quarter_still_writes_because_the_month_may_have_moved():
    """同一季、營收月份往前走一個月，是最常見的更新——不能因為季別相同就跳過。"""
    root = _tmp()
    _seed(root, fiscal_quarter="2026.2Q", revenue_month="115/06")
    _store_rating(root, _Rating("5439", "2026.2Q", "115/07"))

    row = next(r for r in Store(root).read("ratings")
               if r["stock_id"] == "5439" and r["period_index"] == "1")
    assert row["revenue_month"] == "115/07"


def test_vintage_compares_quarter_first_then_month():
    assert _vintage({"fiscal_quarter": "2026.2Q", "revenue_month": "115/01"}) > _vintage(
        {"fiscal_quarter": "2025.4Q", "revenue_month": "115/12"}
    )
    assert _vintage({"fiscal_quarter": "", "revenue_month": ""}) == ("", "")


def test_a_stock_that_is_not_on_the_list_does_not_get_added_to_it():
    """這張表的成員名單是全市場快照決定的，不該被「某人搜尋過這一檔」改變。

    而且個股報表上沒有市場與產業，硬塞進去只會得到一列半空的資料——比不在那裡
    更糟：它會出現在清單上、產業欄空白、用產業篩選找不到。實際踩到的是 2882
    （國泰金），金融保險業本來就不在六大指標的適用範圍裡。
    """
    root = _tmp()
    _seed(root)
    _store_rating(root, _Rating("2882", "2026.2Q", "115/07", name="國泰金"))

    codes = {r["stock_id"] for r in Store(root).read("ratings")}
    assert codes == {"1101", "5439"}


def test_no_table_at_all_means_nothing_to_update():
    """連表都還沒有的時候也一樣：先有全市場快照，才有「更新其中一列」。"""
    root = _tmp()
    _store_rating(root, _Rating("5439", "2026.2Q", "115/07", name="高技"))
    assert Store(root).read("ratings") == []
