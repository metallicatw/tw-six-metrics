"""寫到一半被讀到——那次失敗的訊息裡完全看不出是誰在寫。

「加一檔個股」刻意讓測試和抓取**平行跑**（省下二十幾秒的開機時間）。抓取會重寫
`data/ratings.csv`，而測試把同一個檔案當樣本讀。8261 那一次正好撞上：

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe5 in position 0:
    unexpected end of data

於是「測試沒過，不 commit 這次抓到的資料」——一次完全正常的抓取被自己的測試擋掉。

`os.replace` 是同一個檔案系統上的原子操作：讀到的不是舊的就是新的，沒有中間狀態。
同樣的保護也適用於 runner 被砍在寫入中途：留下來的是完整的舊檔，不是半份資料。
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

from twsix.store import sheets as sheet_store
from twsix.store.snapshots import Store, atomic_write


def test_a_reader_never_sees_half_a_file():
    root = Path(tempfile.mkdtemp())
    target = root / "ratings.csv"
    atomic_write(target, b"stock_id\n1101\n")
    before = target.read_bytes()
    atomic_write(target, b"stock_id\n" + b"x" * 500_000)
    assert target.read_bytes() != before
    assert not list(root.glob(".*tmp*")), "暫存檔沒有收乾淨"


def test_every_data_writer_goes_through_it():
    """三個寫入端都要——評等表、每日行情、個股分頁。漏掉任何一個，那條路就會
    在平行跑的時候把半份檔案端給讀的人。"""
    import inspect

    from twsix.store import snapshots

    for fn in (snapshots.Store.write, snapshots.Store.write_gz, snapshots.Store.write_json):
        assert "atomic_write" in inspect.getsource(fn), f"{fn.__name__} 不是原子寫入"
    assert "atomic_write" in inspect.getsource(sheet_store.write_grid)


def test_the_old_file_survives_a_write_that_never_finishes():
    root = Path(tempfile.mkdtemp())
    store = Store(root)
    store.write("ratings", [{"stock_id": "1101"}], ("stock_id",))
    good = store.path("ratings").read_bytes()

    class Boom:
        def __str__(self) -> str:  # 序列化到一半炸掉
            raise RuntimeError("boom")

    with contextlib.suppress(RuntimeError):
        store.write("ratings", [{"stock_id": Boom()}], ("stock_id",))
    assert store.path("ratings").read_bytes() == good, "失敗的寫入把舊資料弄壞了"
