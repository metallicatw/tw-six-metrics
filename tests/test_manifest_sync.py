import tempfile

from twsix.store.snapshots import Manifest, Store


def test_寫檔時_manifest_有登記的表列數跟著改():
    store = Store(tempfile.mkdtemp())
    store.write("market/twse_income/115Q3", [{"a": i} for i in range(47)], ["a"])
    store.save_manifest(Manifest(counts={"market/twse_income/115Q3": 47, "ratings": 3}))
    # 季財報回補後來寫了 53 家：manifest 跟著變
    store.write("market/twse_income/115Q3", [{"a": i} for i in range(53)], ["a"])
    assert store.load_manifest().counts["market/twse_income/115Q3"] == 53
    # upsert（評等清單逐檔更新）也一樣
    store.write("ratings", [{"stock_id": "1"}, {"stock_id": "2"}, {"stock_id": "3"}], ["stock_id"])
    store.upsert("ratings", "stock_id", "4", [{"stock_id": "4"}], ["stock_id"])
    assert store.load_manifest().counts["ratings"] == 4
    # 沒登記的表不加進 manifest
    store.write("market/other", [{"a": 1}], ["a"])
    assert "market/other" not in store.load_manifest().counts


def test_沒有_manifest_的資料夾不會憑空產生():
    store = Store(tempfile.mkdtemp())
    store.write("ratings", [{"a": 1}], ["a"])
    assert not (store.root / "manifest.json").exists()
