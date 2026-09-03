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


def test_a_candidate_with_form_fields_is_sent_as_a_post():
    """公開資訊觀測站的彙總報表，GET 回的是一頁 2.4 KB 的空殼。

    使用者跑 `twsix probe --group statements` 拿到的就是那兩份空殼——不是端點壞
    了，是那個網址只認 POST 表單。表單欄位是從 `t163sb05` 那一頁**讀出來**的，
    不是猜的。
    """
    forms = {c.name: c.form for c in CANDIDATES if c.form}
    assert forms, "沒有任何候選帶表單，那 POST 這條路等於沒有測到"
    for name, form in forms.items():
        assert {"step", "firstin", "isQuery", "TYPEK", "year", "season"} <= set(form), (
            f"{name} 的表單少了欄位，送出去會回空殼"
        )
        meta = json.loads((SAMPLES / f"{name}.meta.json").read_text("utf-8"))
        assert meta.get("form") == form, f"{name} 的樣本不是用現在這組參數抓的"


def test_the_summary_report_does_not_carry_the_two_missing_indicators():
    """存貨週轉率與自由現金流量，這條路解不掉——而且是量過的，不是推測的。

    帶了表單之後回的是真資料（1.3 MB／1.6 MB，一頁七張表，一般業 1,049 家），
    所以「抓不到」不是因為沒抓成功。但它的一般業欄位是「流動資產／非流動資產／
    資產總計／流動負債……」——和我們已經在抓的官方開放資料同一個彙總層級，整份
    檔案裡「存貨」出現 **0 次**。

    留著這兩份樣本，是為了不要有人半年後再走一次同一條路。下一個候選是個股的
    完整財報（`t164sb*`），一樣要先有真實回應才准寫解析器。
    """
    for name in ("mops_balance_summary", "mops_income_summary"):
        body = load(SAMPLES, name).decode("utf-8", errors="replace")
        assert len(body) > 1_000_000, f"{name} 又抓回空殼了"
        assert body.count("<table") >= 7, f"{name} 的表少了，形狀變了"
        assert "存貨" not in body, (
            f"{name} 裡出現了存貨——那就值得重看一次這條路"
        )


def test_there_is_a_way_to_refresh_the_samples_from_a_runner():
    """證交所擋過機房 IP，而 runner 的 IP 是通的——哪一邊通得了本身就是事實之一。"""
    wf = (ROOT / ".github/workflows/probe.yml").read_text("utf-8")
    assert "twsix probe" in wf
    assert "git add reference/samples" in wf
    assert "workflow_dispatch" in wf


def test_the_whole_market_news_feed_carries_stock_codes():
    """〔個股新聞〕能不能像三大法人一樣接上每日排程，取決於這一件事。

    現在的來源是鉅亨網的**關鍵字索引**（`q=<代號>`），一檔一個請求——1,769 檔就是
    1,769 個請求，不可能每天跑。分類新聞列表不一樣：一個請求換到一整批，而每一篇
    帶著它提到的股票代號，所以可以反過來分派到個股。

    留這份樣本與這條測試，是因為「它帶不帶代號」正是整條路成不成立的那一格。
    """
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
