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
    # 抓、commit、建站、發布——四步都要跟著跳過，否則會發布一份沒有變的網站。
    assert wf.count("steps.need.outputs.stale == 'yes'") == 4
