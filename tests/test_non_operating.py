
from __future__ import annotations

from twsix.calendar_tw import Quarter
from twsix.ingest.workbook import LAYOUT
from twsix.transform.statements import QuarterStatements, non_operating_ratio


def _s(**kw):
    return QuarterStatements(quarter=Quarter(2026, 2), **kw)


def test_the_ratio_is_non_operating_over_pretax():
    v = non_operating_ratio(_s(non_operating=95_827.0, pretax_income=862_430.0))
    assert round(v, 2) == 11.11


def test_a_loss_making_core_business_shows_up_as_a_ratio_over_one_hundred():
    v = non_operating_ratio(_s(non_operating=120.0, pretax_income=100.0))
    assert v == 120.0


def test_a_negative_pretax_flips_the_sign_and_is_not_absolute_valued():
    v = non_operating_ratio(_s(non_operating=50.0, pretax_income=-100.0))
    assert v == -50.0


def test_a_zero_pretax_is_blank_not_infinity():
    assert non_operating_ratio(_s(non_operating=50.0, pretax_income=0.0)) is None
    assert non_operating_ratio(_s(non_operating=50.0)) is None
    assert non_operating_ratio(_s(pretax_income=100.0)) is None


def test_the_isq_rows_point_at_the_totals_not_the_line_items():
    rows = LAYOUT["ISQ"][1]
    assert rows["non_operating"] == 69
    assert rows["pretax_income"] == 70
    assert rows["operating_income"] < rows["non_operating"] < rows["pretax_income"]


def test_the_summary_report_column_names_are_the_ones_the_exchanges_use():
    from twsix.ingest.market import NON_OPERATING_KEYS, PRETAX_INCOME_KEYS

    assert NON_OPERATING_KEYS == ("營業外收入及支出",)
    assert PRETAX_INCOME_KEYS == ("稅前淨利（淨損）",)
