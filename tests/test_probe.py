"""候選端點的真實回應——存下來，還沒解析。

這個專案最貴的一次錯誤：原本的 `ingest/` 照官方 API 文件寫、從未實跑過，九張表
裡六張欄位對錯位——看起來全部正常，但都是錯的。從此改成兩段式：先存回應，讀過
之後才寫解析器。

所以這個檔案問的不是「解析對不對」（還沒有解析器），而是「我們手上這幾份，是不
是真的回應」。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from twsix.ingest.probe import CANDIDATES, head, load, save

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "reference/samples"


def test_saving_the_same_response_twice_gives_the_same_bytes():
    """gzip 預設把「現在幾點」寫進檔頭。

    樣本進版控是為了被讀，而每次重跑 probe 都製造一個假差異，會讓「端點改版了
    嗎」這件事再也讀不出來——manifest 與個股分頁踩過同一個洞。
    """
    tmp = Path(tempfile.mkdtemp())
    meta = {"name": "x", "url": "https://example.invalid"}
    first = save(tmp, "x", b"hello", meta).read_bytes()
    second = save(tmp, "x", b"hello", meta).read_bytes()
    assert first == second
    assert load(tmp, "x") == b"hello"
    assert json.loads((tmp / "x.meta.json").read_text("utf-8"))["url"].startswith("https")


def test_the_head_is_one_line_so_a_block_page_is_obvious():
    """「回了 200 但內容是一頁 HTML」看狀態碼看不出來，看開頭一眼就知道。"""
    assert head(b"<html>\n  <body>\n  \xe5\x9b\xa0\xe7\x82\xba", 40).startswith("<html>")
    assert "\n" not in head(b"a\nb\nc")


def test_every_candidate_is_named_once_and_says_what_we_expect():
    names = [c.name for c in CANDIDATES]
    assert len(names) == len(set(names))
    for c in CANDIDATES:
        assert c.url.startswith("https://")
        assert c.expect, f"{c.name} 沒有寫「預期它回什麼」——那是給人對照用的"


def test_the_four_endpoints_stage_two_needs_are_real_responses_now():
    """階段二要的四個端點，樣本都在，而且都是真的資料而不是一頁擋人的 HTML。

    ⚠️ 這幾份是**寫解析器的依據**。哪天端點改版、樣本重抓，這個測試會第一個
    告訴你形狀變了。
    """
    for name, needle in (
        # 上市日收盤：已經在用的那一個
        ("twse_daily_all", '"Code"'),
        # 上櫃日收盤
        ("tpex_daily_openapi", '"SecuritiesCompanyCode"'),
        # 上市三大法人（openapi 那個候選回的是一頁 HTML，這個才是真的）
        ("twse_t86_rwd", "三大法人買賣超日報"),
        # 上櫃三大法人
        ("tpex_insti_openapi", '"Date"'),
    ):
        body = load(SAMPLES, name).decode("utf-8", errors="replace")
        assert len(body) > 50_000, f"{name} 的樣本太小，多半不是真的資料"
        assert needle in body, f"{name} 的樣本裡找不到 {needle}"
        meta = json.loads((SAMPLES / f"{name}.meta.json").read_text("utf-8"))
        assert meta.get("bytes", 0) > 50_000 and "error" not in meta


def test_the_dud_candidate_is_kept_rather_than_quietly_dropped():
    """`openapi.twse.com.tw/v1/fund/T86` 回的是一頁 HTML，不是資料。

    留著這份 1 KB 的樣本，是為了不要有人半年後再猜一次同一個網址——「試過了，
    它不是」本身就是結論。
    """
    meta = json.loads((SAMPLES / "twse_t86_openapi.meta.json").read_text("utf-8"))
    assert meta.get("bytes", 0) < 5_000
    assert "html" in meta.get("head", "").lower()


def test_there_is_a_way_to_refresh_the_samples_from_a_runner():
    """證交所擋過機房 IP，而 runner 的 IP 是通的——哪一邊通得了本身就是事實之一。"""
    wf = (ROOT / ".github/workflows/probe.yml").read_text("utf-8")
    assert "twsix probe" in wf
    assert "git add reference/samples" in wf
    assert "workflow_dispatch" in wf
