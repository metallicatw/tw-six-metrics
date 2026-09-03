"""剛更新完再按一次「立即更新」，不該再抓一次。

13 個請求、一分半鐘，換回來的是一模一樣的資料——而那一分半鐘裡使用者是盯著
螢幕在等的。判斷要在**送出之前**做，而且要在三個地方都成立：瀏覽器（連
workflow 都不要開）、workflow（別人直接觸發時的第二道）、以及 CLI。
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from twsix.calendar_tw import DATA_HOUR, data_epoch
from twsix.cli import fetched_at, is_fresh

ROOT = Path(__file__).resolve().parents[1]
TAIPEI = timezone(timedelta(hours=8))


def test_the_line_is_five_in_the_afternoon_not_midnight():
    """收盤是 13:30，但收盤行情約 14:00、三大法人約 16:00 才上站。

    用午夜當界線的話，早上九點按下更新會抓到「昨天的數字配今天的日期」——這個
    專案已經因為那件事錯過一次（〔BASIC〕的最近交易日跑在自己的 OHLC 前面）。
    """
    assert DATA_HOUR == 17
    # 週三傍晚六點：今天的資料已經齊了。
    assert data_epoch(datetime(2026, 9, 2, 18, tzinfo=TAIPEI)) == datetime(
        2026, 9, 2, 17, tzinfo=TAIPEI
    )
    # 週三早上十點：今天的還沒有，最新的一份是昨天下午的。
    assert data_epoch(datetime(2026, 9, 2, 10, tzinfo=TAIPEI)) == datetime(
        2026, 9, 1, 17, tzinfo=TAIPEI
    )


def test_the_weekend_does_not_produce_new_data():
    """星期六早上按更新，該比對的是星期五下午——不是星期五凌晨，也不是星期六。"""
    saturday = datetime(2026, 9, 5, 10, tzinfo=TAIPEI)
    monday_morning = datetime(2026, 9, 7, 10, tzinfo=TAIPEI)
    friday_close = datetime(2026, 9, 4, 17, tzinfo=TAIPEI)
    assert data_epoch(saturday) == friday_close
    assert data_epoch(monday_morning) == friday_close
    # 星期一傍晚才有新的一份。
    assert data_epoch(datetime(2026, 9, 7, 18, tzinfo=TAIPEI)) == datetime(
        2026, 9, 7, 17, tzinfo=TAIPEI
    )


def test_a_fetch_after_the_line_makes_the_next_press_a_no_op():
    base = Path(tempfile.mkdtemp())
    (base / "ISQ.json.gz").write_bytes(b"x")
    now = datetime(2026, 9, 2, 18, 30, tzinfo=TAIPEI)

    (base / "_fetched.txt").write_text(
        datetime(2026, 9, 2, 18, tzinfo=TAIPEI).isoformat() + "\n", encoding="utf-8"
    )
    assert is_fresh(base, now), "剛抓完的不該再抓"

    # 同一天，但在資料上站之前抓的——那一份是昨天的數字，要重抓。
    (base / "_fetched.txt").write_text(
        datetime(2026, 9, 2, 10, tzinfo=TAIPEI).isoformat() + "\n", encoding="utf-8"
    )
    assert not is_fresh(base, now), "早上抓的擋不住傍晚的更新"


def test_the_old_date_only_stamp_counts_as_stale():
    """舊記號只有日期，回答不了「幾點抓的」。

    當成那天的 00:00，也就是一定過期：第一次按下更新會真的去抓，之後就有完整的
    時間戳了。寧可多抓一次，也不要用一個猜出來的時間把更新擋掉。
    """
    base = Path(tempfile.mkdtemp())
    (base / "ISQ.json.gz").write_bytes(b"x")
    (base / "_fetched.txt").write_text("2026-09-02\n", encoding="utf-8")
    assert fetched_at(base) == datetime(2026, 9, 2, tzinfo=TAIPEI)
    assert not is_fresh(base, datetime(2026, 9, 2, 18, tzinfo=TAIPEI))


def test_a_stamp_without_any_sheets_is_not_freshness():
    """記號再新，沒有報表就是沒有報表——那種目錄要能被重抓。"""
    base = Path(tempfile.mkdtemp())
    (base / "_fetched.txt").write_text(
        datetime(2026, 9, 2, 18, tzinfo=TAIPEI).isoformat() + "\n", encoding="utf-8"
    )
    assert not is_fresh(base, datetime(2026, 9, 2, 18, 30, tzinfo=TAIPEI))


def test_the_browser_decides_before_it_opens_a_workflow_at_all():
    """最省的一次抓取，是沒有送出的那一次。

    索引裡帶著抓取時間戳（第六欄），所以瀏覽器自己就能判斷——連 runner 都不必
    開。第二次按同一顆按鈕才會強制重抓，那句「我知道，我就是要重抓」不必跑去
    Actions 分頁講。
    """
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "function dataEpoch()" in js and "function isFresh(" in js
    assert "data[i][5]" in js, "沒有讀索引的第六欄（抓取時間戳）"
    assert "forced[code]" in js, "第二次按應該要能強制重抓"
    assert "force ? 'true' : 'false'" in js, "強制重抓沒有傳給 workflow"
    # 17:00 台北 = 09:00 UTC。寫錯這個數字，整個判斷會偏八小時。
    assert "Date.UTC(y, m, d, 9, 0, 0)" in js


def test_the_workflow_asks_before_it_fetches():
    """瀏覽器擋不到的路（別人直接在 Actions 分頁觸發）要有第二道。"""
    wf = (ROOT / ".github/workflows/stock.yml").read_text("utf-8")
    assert "twsix fresh" in wf
    assert "steps.need.outputs.stale == 'yes'" in wf
    # 抓、commit、建站、發布，以及發布之後那一步存快取——全部跟著跳過，否則會
    # 發布一份沒有變的網站，或存一份沒有變的快取。
    assert wf.count("steps.need.outputs.stale == 'yes'") == 5


def test_a_run_that_skipped_everything_does_not_leave_the_panel_spinning():
    """「成功」有兩種：真的抓了並發布了，還有**什麼都沒做**。

    workflow 判斷這一檔已經是最新的、四步一起跳過的時候，網站不會換——所以面板
    再怎麼等 build.json 都不會變，會停在「等 Pages CDN 換檔」直到六分鐘後說
    「等太久了，2308 還沒出現」。一次完全正常的判斷，看起來像當掉。實際踩到過。

    所以完成之後要問一句 workflow 到底做了什麼：建站那一步被跳過，就代表沒有新
    的一份要等。
    """
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "function afterRun(" in js
    assert "/actions/runs/" in js and "/jobs" in js
    assert "'skipped'" in js
    assert "已經是最新的" in js
    # 問不到就照舊等——那是原本的行為，不能因為多了這一段而變成不等。
    assert ".catch(keepWaiting)" in js


def test_the_browser_asks_the_server_before_it_pays_for_a_runner():
    """索引可能是這一頁載入時抓的，而 GitHub Pages 給 JSON 的是 max-age=600。

    手上那份一舊，「已經是最新的」就擋不住，於是派了一台 runner 去問一個我們
    已經知道答案的問題——實測那是 64 秒，而正確答案是「不必抓」。

    一個 80 KB 的請求換掉一整台 runner 加一分鐘。問不到就用手上那份，不會比原本
    更糟。
    """
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "function stampFromServer(" in js
    assert "cache: 'no-store'" in js
    # 平常瀏覽時的索引也要跟著建站編號換網址，否則同樣會拿到十分鐘前的快取。
    assert "'?v=' + encodeURIComponent(TWSIX.built)" in js
    # 送出之前的那一步要在確認之後才發生。
    assert js.index("function stampFromServer(") < js.index("function dispatch(")


def test_the_way_out_of_the_guard_is_a_button_not_a_hidden_second_press():
    """「已經是最新的」是個**啟發式**判斷，所以一定要留一條「不管怎樣都抓」。

    它會錯：後來新增的區塊（大戶持股、董監持股就是這樣加進來的）只能靠重抓補上，
    快取存到半份的也是，鏡像站更正過數字的也是。

    原本那條路是**再按一次同一顆按鈕**——一個看不見的模式。同一顆按鈕在第一次和
    第二次做不同的事，唯一的說明是面板上一句「真的要重抓的話，再按一次」；按下去
    之後也分不清剛才那一次到底算不算數。要保留的能力是對的，說法不對。

    所以改成明講：面板上一顆寫著「仍要重抓」的按鈕。按過就清掉，下一次照樣先問。
    """
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "仍要重抓" in js
    # 面板上那句話沒了。註解裡還留著這段歷史，那是刻意的——會被讀到的是字串。
    assert "真的要重抓的話" not in js, "面板上還在教人用那個看不見的模式"
    # 按下去才設 forced，不是第一次被擋下來就設。
    assert "forced[code] = true;\n                 runOnGithub(code);" in js
    # 用掉就清掉，否則第二次之後這一檔的守門形同不存在。
    assert "delete forced[code];" in js


def test_the_listing_no_longer_offers_a_filter_that_filters_nothing():
    """「只看有完整報告」在只有 183 檔抓過報表的時候會把 1,741 列篩到 183 列。

    補課排程跑完之後，清單上**每一列**都有完整報告——那個勾選框篩掉零列。一個
    永遠不改變畫面的勾選框比沒有更糟：讀者會以為自己勾錯了、或以為篩選壞了。

    它要回答的問題（「這一檔的報表有多新」）已經由〔最後更新日〕那一欄接手，而且
    答得比「有／沒有」更好——所以是功成身退，不是砍功能。
    """
    listing = (ROOT / "src/twsix/report/templates/list.html.j2").read_text("utf-8")
    assert "only-full" not in listing
    assert "only-watched" in listing and "only-picks" in listing, "另外兩個還要留著"
    js = (ROOT / "src/twsix/report/templates/site.js").read_text("utf-8")
    assert "onlyFull" not in js, "腳本裡還在找一個不存在的元素"
    # 那一欄本身要留著：它才是現在回答「多新」的地方。
    macros = (ROOT / "src/twsix/report/templates/_macros.html.j2").read_text("utf-8")
    assert "when-cell" in macros and "最後<br>更新日" in macros
