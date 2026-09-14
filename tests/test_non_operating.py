"""〔業外佔比〕：這一季賺的錢，有多少不是本業賺的。

## 為什麼這一列存在

〔營業利益率〕是本業賺得多厚，〔淨利率（歸母）〕是扣完業外、稅與少數股權之後真正
留給股東的厚度。兩條率差很多的時候看得出「有事發生」，但看不出是業外把它拉上去
還是稅把它吃掉了——而那正是這一列回答的問題。它不評分：六大指標是六個，多一個
等第就是多一條沒有人訂過的規則。

## 這個檔案守的三件事

1. **兩條資料路徑都算得出來**。同一個數字有兩個來源：個股的 ISQ 工作表（券商
   鏡像）與 MOPS 的全市場彙總報表。少做一邊不會報錯，只會讓一部分股票的那一列
   靜靜地不見。
2. **列號與欄名沒有抓錯**。ISQ 第 68 列是「營業外收入及支出－其他」，第 69 列
   才是合計，只差三個字；抓錯不會報錯，只會讓幾乎每一檔都變成接近 0。
3. **負的稅前淨利不會被吞掉也不會被取絕對值**。本業加業外仍然虧的那一季，比例
   會翻號，而翻號之後那把判讀的尺就不適用——那件事必須看得見。
"""

from __future__ import annotations

from twsix.calendar_tw import Quarter
from twsix.ingest.workbook import LAYOUT
from twsix.transform.statements import QuarterStatements, non_operating_ratio


def _s(**kw):
    return QuarterStatements(quarter=Quarter(2026, 2), **kw)


def test_the_ratio_is_non_operating_over_pretax():
    """2330 的 2026.2Q，從它自己的 ISQ 上抄下來的兩個數字。

    95,827 / 862,430 = 11.11%。這兩個數字不是造的，是 data/sheets/2330/ISQ
    第 69 與第 70 列上的值——所以這條測試同時證明了「那兩列就是這兩個東西」。
    """
    v = non_operating_ratio(_s(non_operating=95_827.0, pretax_income=862_430.0))
    assert round(v, 2) == 11.11


def test_a_loss_making_core_business_shows_up_as_a_ratio_over_one_hundred():
    """營業利益是負的、業外把它救成正的稅前淨利——比例會超過 100%。

    這是判讀說明裡「高度警戒」那一格，而它只在比例**沒有**被夾在 0～100 之間
    的時候才看得出來。
    """
    v = non_operating_ratio(_s(non_operating=120.0, pretax_income=100.0))
    assert v == 120.0


def test_a_negative_pretax_flips_the_sign_and_is_not_absolute_valued():
    """稅前淨利為負：比例翻號，而且**不可以**取絕對值。

    取絕對值的話，「本業和業外加起來還是虧」會長得跟「業外貢獻很大」一模一樣。
    那把尺在這一季不適用，而唯一讓讀者知道這件事的線索就是那個負號。
    """
    v = non_operating_ratio(_s(non_operating=50.0, pretax_income=-100.0))
    assert v == -50.0


def test_a_zero_pretax_is_blank_not_infinity():
    """分母是 0 就留空。

    除出來是無限大，而無限大在這一欄的意思不是「業外佔比很高」，是「這一季沒有
    稅前損益可以當分母」。
    """
    assert non_operating_ratio(_s(non_operating=50.0, pretax_income=0.0)) is None
    assert non_operating_ratio(_s(non_operating=50.0)) is None
    assert non_operating_ratio(_s(pretax_income=100.0)) is None


def test_the_isq_rows_point_at_the_totals_not_the_line_items():
    """列號守門。

    第 68 列「營業外收入及支出－其他」是那一段底下的一個明細；第 69 列才是合計。
    抓錯不會報錯、不會缺值，只會讓幾乎每一檔的業外佔比都變成接近 0——一種只有
    拿去跟財報對過才看得出來的錯。

    這裡釘的是 LAYOUT 裡那兩個數字。它們是掃過 data/sheets 底下全部 1,947 份
    ISQ 得到的，而這條測試讓「順手調一下」不會安靜地通過。
    """
    rows = LAYOUT["ISQ"][1]
    assert rows["non_operating"] == 69
    assert rows["pretax_income"] == 70
    # 營業利益在它們上面，而且是既有的那一列——順序錯掉就是讀錯報表。
    assert rows["operating_income"] < rows["non_operating"] < rows["pretax_income"]


def test_the_summary_report_column_names_are_the_ones_the_exchanges_use():
    """彙總報表那條路的欄名。

    上市（twse_income）與上櫃（tpex_income）的欄名一字不差，兩邊都 probe 過。
    欄名打錯不會報錯——`_single` 找不到就回 None，那一列直接不見。
    """
    from twsix.ingest.market import NON_OPERATING_KEYS, PRETAX_INCOME_KEYS

    assert NON_OPERATING_KEYS == ("營業外收入及支出",)
    assert PRETAX_INCOME_KEYS == ("稅前淨利（淨損）",)
