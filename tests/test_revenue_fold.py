"""全市場月營收折回每一檔的〔營收〕分頁。

這一支修的是一個**綠燈的失敗**：〔全市場官方資料（月營收／季財報）〕跑完、
commit 了、workflow 綠燈，而 1,877 檔的個股頁上月營收還停在 115/07。原因是抓回來
的 `data/market/*_revenue/11508.csv` 是給評等清單用的，個股頁那張圖讀的是
`data/sheets/<代號>/營收.json.gz`——中間沒有人把前者攤回後者。

所以這裡守的是三件會安靜出錯的事：**欄位對應**、**格式**、以及**重疊時誰贏**。
"""

from __future__ import annotations

from twsix.ingest.merge_sheets import period_key
from twsix.ingest.revenue_fold import HEADER, folded, month_label, to_row

#: 官方開放資料上 5439 的 115/08 那一列，欄名與數值照抄
#: `data/market/tpex_revenue/11508.csv`。
OFFICIAL_5439 = {
    "公司代號": "5439",
    "資料年月": "11508",
    "營業收入-當月營收": "1108099",
    "營業收入-上月比較增減(%)": "5.500784044527255",
    "營業收入-去年當月營收": "1052950",
    "營業收入-去年同月增減(%)": "5.237570634882948",
    "累計營業收入-當月累計營收": "7749508",
    "累計營業收入-前期比較增減(%)": "34.29374766595645",
}

#: 券商鏡像抓回來的同一個月，照抄 `data/sheets/5439/營收.json.gz`。
MIRROR_5439 = ["115/08", "1,108,099", "5.50%", "1,052,950", "5.24%", "7,749,508", "34.29%", ""]


def test_the_official_feed_reproduces_the_mirror_cell_for_cell():
    """折進去的不是一個近似值，是同一個數字。

    這是整支模組唯一真正需要證明的事：官方那份的七個欄位，換算成分頁的格式之後
    要和券商鏡像那一列**逐格相同**。四捨五入差一位、千分位少一個逗號，畫面上都
    看得出來是兩種來源拼起來的，而那種不一致遲早會被讀成資料本身的差異。

    全 repo 對過帳：2,018 個兩邊都有的月份，1,988 筆逐欄相同、24 筆是官方比較
    完整（鏡像那一格是空的）、6 筆真的不同（見下一條）。
    """
    assert to_row(OFFICIAL_5439) == MIRROR_5439


def test_a_month_the_mirror_never_had_is_added():
    """分頁沒有的月份要補進去，而且補在最上面——〔營收〕是新的排在前面。"""
    old = [
        list(HEADER),
        ["115/07", "1,050,323", "-4.78%", "1,005,270", "4.48%", "6,641,409", "40.78%", ""],
        ["115/06", "1,103,029", "10.28%", "903,156", "22.13%", "5,591,086", "50.61%", ""],
    ]
    out = folded(old, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    data = [r for r in out if r and period_key(r[0])]
    assert [r[0] for r in data] == ["115/08", "115/07", "115/06"]
    assert data[0] == MIRROR_5439
    # 表頭留在原位：讀取端是按位置找它的。
    assert out[0] == list(HEADER)


def test_the_official_number_wins_when_both_sides_have_the_month():
    """同一個月兩邊都有，用官方那一份——而這不是一條偏好，是量過的。

    2,018 個重疊的月份裡有 6 筆真的不同，逐筆看過之後沒有一筆是官方錯：

      * 4804 115/07：官方累計 70,627、鏡像 1,076。官方那一列的〔備註〕寫著
        「上海地區業務清算。」——那是一個有解釋的數字。
      * 3631 115/07：官方當月 6,997、鏡像 5,065。備註「本月收入較去年同期營收
        增多肇因於錫价上漲50%多」。
      * 6283 115/07：當月與年增率兩邊一樣，只有月增率不同——因為兩邊對**上個月**
        的認知不同（官方的上月營收 121,651）。也就是說公司更正過六月。
      * 5310 115/07：-78.12% vs -78.13%，純粹是四捨五入。

    官方那一份是公司自己申報的，鏡像是第三方轉載；公司更正之後鏡像不一定跟上。
    所以重疊的時候官方贏。
    """
    stale = [
        list(HEADER),
        ["115/08", "999,999", "0.00%", "1", "0.00%", "1", "0.00%", ""],
    ]
    out = folded(stale, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    data = [r for r in out if r and period_key(r[0])]
    assert len(data) == 1, "同一個月不可以留下兩列"
    assert data[0] == MIRROR_5439


def test_nothing_to_add_reports_nothing_rather_than_rewriting():
    """已經有那個月就回 None，不要把 1,958 個 gzip 每天重寫一次。

    回原樣也「正確」，但每一次排程都會產生兩千個內容相同、位元組不同的檔案
    （gzip 帶時間戳），而那會讓每一筆 commit 都看起來動了整個資料庫。
    """
    old = [list(HEADER), MIRROR_5439]
    assert folded(old, {"115/08": to_row(OFFICIAL_5439)}) is None


def test_a_stock_with_no_sheet_yet_gets_a_usable_one():
    """還沒有分頁的那一檔，自己造一張最小的——欄數要和鏡像那張一致。"""
    out = folded(None, {"115/08": to_row(OFFICIAL_5439)})
    assert out is not None
    assert out[0] == list(HEADER)
    assert len(out[1]) == len(HEADER)


def test_the_month_label_is_the_one_the_sheet_uses():
    """`11508` 是官方的寫法，`115/08` 是分頁的。認錯的話合併會當成兩個不同的月。"""
    assert month_label("11508") == "115/08"
    assert month_label("11412") == "114/12"
    assert month_label("") == ""
    assert month_label("亂寫") == ""


def test_a_blank_cell_stays_blank_instead_of_becoming_zero():
    """官方那一格是空的就留空。塞 0 進去的話，畫面上會出現一條假的零成長。"""
    row = to_row({"資料年月": "11508", "營業收入-當月營收": "1000",
                  "營業收入-去年同月增減(%)": ""})
    assert row[1] == "1,000"
    assert row[4] == ""


def test_a_big_percentage_keeps_its_thousands_separator():
    """基期小的時候年增率會是四位數，而鏡像那張表寫的是 `4,533.33%`。

    少了逗號的話，同一張分頁上哪一列是官方折進來的、哪一列是鏡像抓的，光看格式
    就分得出來——而那種差異遲早會被誤讀成資料本身的差異。
    """
    row = to_row({"資料年月": "11507", "營業收入-去年同月增減(%)": "4533.333"})
    assert row[4] == "4,533.33%"
