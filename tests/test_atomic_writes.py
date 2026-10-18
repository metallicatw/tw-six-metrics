
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
        def __str__(self) -> str:
            raise RuntimeError("boom")

    with contextlib.suppress(RuntimeError):
        store.write("ratings", [{"stock_id": Boom()}], ("stock_id",))
    assert store.path("ratings").read_bytes() == good, "失敗的寫入把舊資料弄壞了"
