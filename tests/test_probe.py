
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from twsix.ingest.probe import CANDIDATES, head, load, save

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "reference/samples"


def test_saving_the_same_response_twice_gives_the_same_bytes():
    tmp = Path(tempfile.mkdtemp())
    meta = {"name": "x", "url": "https://example.invalid"}
    first = save(tmp, "x", b"hello", meta).read_bytes()
    second = save(tmp, "x", b"hello", meta).read_bytes()
    assert first == second
    assert load(tmp, "x") == b"hello"
    assert json.loads((tmp / "x.meta.json").read_text("utf-8"))["url"].startswith("https")


def test_the_head_is_one_line_so_a_block_page_is_obvious():
    assert head(b"<html>\n  <body>\n  \xe5\x9b\xa0\xe7\x82\xba", 40).startswith("<html>")
    assert "\n" not in head(b"a\nb\nc")


def test_every_candidate_is_named_once_and_says_what_we_expect():
    names = [c.name for c in CANDIDATES]
    assert len(names) == len(set(names))
    for c in CANDIDATES:
        assert c.url.startswith("https://")
        assert c.expect, f"{c.name} 沒有寫「預期它回什麼」——那是給人對照用的"


def test_the_four_endpoints_stage_two_needs_are_real_responses_now():
    for name, needle in (
        ("twse_daily_all", '"Code"'),
        ("tpex_daily_openapi", '"SecuritiesCompanyCode"'),
        ("twse_t86_rwd", "三大法人買賣超日報"),
        ("tpex_insti_openapi", '"Date"'),
    ):
        body = load(SAMPLES, name).decode("utf-8", errors="replace")
        assert len(body) > 50_000, f"{name} 的樣本太小，多半不是真的資料"
        assert needle in body, f"{name} 的樣本裡找不到 {needle}"
        meta = json.loads((SAMPLES / f"{name}.meta.json").read_text("utf-8"))
        assert meta.get("bytes", 0) > 50_000 and "error" not in meta


def test_the_dud_candidate_is_kept_rather_than_quietly_dropped():
    meta = json.loads((SAMPLES / "twse_t86_openapi.meta.json").read_text("utf-8"))
    assert meta.get("bytes", 0) < 5_000
    assert "html" in meta.get("head", "").lower()


def test_a_candidate_with_form_fields_is_sent_as_a_post():
    withform = [c for c in CANDIDATES if c.form]
    assert withform, "沒有任何候選帶表單，那 POST 這條路等於沒有測到"
    for c in withform:
        assert {"step", "firstin", "isQuery", "TYPEK", "year", "season"} <= set(c.form), (
            f"{c.name} 的表單少了欄位，送出去會回空殼"
        )
        if c.sample_pending:
            continue
        meta = json.loads((SAMPLES / f"{c.name}.meta.json").read_text("utf-8"))
        assert meta.get("form") == c.form, f"{c.name} 的樣本不是用現在這組參數抓的"


def test_a_pending_sample_says_why_and_stops_being_pending_once_it_is_there():
    for c in CANDIDATES:
        if not c.sample_pending:
            continue
        assert len(c.sample_pending) > 20, f"{c.name} 的 sample_pending 沒寫清楚理由"
        assert not (SAMPLES / f"{c.name}.raw.gz").exists(), (
            f"{c.name} 的樣本已經在版控裡了，請把 sample_pending 這一行刪掉"
        )


def test_no_summary_report_carries_inventory():
    for name in ("mops_balance_summary", "mops_income_summary"):
        body = load(SAMPLES, name).decode("utf-8", errors="replace")
        assert len(body) > 1_000_000, f"{name} 又抓回空殼了"
        assert body.count("<table") >= 7, f"{name} 的表少了，形狀變了"
        assert "存貨" not in body, (
            f"{name} 裡出現了存貨——那就值得重看一次這條路"
        )
    assert "存貨" not in load(SAMPLES, "mops_cashflow_summary").decode(
        "utf-8", errors="replace"
    )


def test_the_cash_flow_summary_really_carries_the_two_columns_we_derive_fcf_from():
    body = load(SAMPLES, "mops_cashflow_summary").decode("utf-8", errors="replace")
    assert len(body) > 400_000, "現金流量表彙總又抓回空殼了"
    for column in ("營業活動之淨現金流入", "投資活動之淨現金流入"):
        assert column in body, f"現金流量表彙總裡找不到「{column}」，欄名可能改了"


def test_there_is_a_way_to_refresh_the_samples_from_a_runner():
    wf = (ROOT / ".github/workflows/probe.yml").read_text("utf-8")
    assert "twsix probe" in wf
    assert "git add reference/samples" in wf
    assert "workflow_dispatch" in wf


def test_the_whole_market_news_feed_carries_stock_codes():
    body = load(SAMPLES, "cnyes_category_tw_stock").decode("utf-8", errors="replace")
    assert len(body) > 100_000
    data = json.loads(body)["items"]
    assert data["per_page"] == 30, "一頁的篇數變了，排程要抓幾頁會跟著變"
    assert data["total"] > 300
    coded = [x for x in data["data"] if x.get("market")]
    assert coded, "沒有任何一篇帶股票代號——這條路就不成立"
    one = coded[0]["market"][0]
    assert one["code"].strip() and one["name"].strip()
    assert coded[0]["publishAt"] > 1_700_000_000, "publishAt 不是 epoch 秒了"


def test_no_test_file_depends_on_pytest():
    import re
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    pattern = re.compile(r"^\s*(?:import\s+pytest|from\s+pytest\b)", re.M)
    offenders = []
    for path in sorted(tests_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            line = text[: m.start()].count("\n") + 1
            offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "這些測試 import 了 pytest，但 CI 上沒有裝："
        + "、".join(offenders)
        + "。要斷言例外請用 try/except + raise AssertionError。"
    )
