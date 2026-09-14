"""櫃買少送的那一段憑證鏈，我們自己補上——這裡守著那個補丁還有效。

2026-09-07 櫃買（www.tpex.org.tw）換了新憑證，而新的那一份只送 leaf、不送中繼。
瀏覽器會照 leaf 的 AIA 欄位自己去抓中繼，所以人看網頁完全正常；Python 的 ssl
不做這件事，於是每一個櫃買的請求都是：

    [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
    unable to get local issuer certificate

證交所沒事，只有櫃買。上櫃那一半的收盤行情、上櫃三大法人、年度交易資訊整批抓不
到——而且不會寫壞資料，只會停在原地。停在原地不會有人發現，只會變成「那 249 檔
怎麼補都補不完」。

這一條測試**不打網路**（CI 不該依賴櫃買今天心情好不好）。它驗的是三件離線就驗得
出來、而且壞掉不會有其他症狀的事：

1. 那個 PEM 檔還在，而且真的被載進 TLS context。
2. 裡面那兩張是說好的那兩張（比 SHA-256 指紋，不是比名字）。
3. 憑證還沒過期——而且**過期前 90 天就開始叫**，不是等到當天。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import subprocess
from pathlib import Path

CHAIN = Path(__file__).resolve().parents[1] / "src" / "twsix" / "ingest" / "twca_chain.pem"

#: 換檔的時候拿這個對。名字會重複（TWCA 底下不只一張 SSL Sub-CA），指紋不會。
EXPECTED = {
    "TWCA SSL Certification Authority":
        "01af2324d098098f5e0cdf6faabada430b21cce777f47eacb26248b2fda3e531",
    "TWCA CYBER Root CA":
        "3f63bb2814be174ec8b6439cf08d6d56f0b7c405883a5648a334424d6b3ec558",
}

#: 到期前這麼多天就開始叫。憑證過期那天才發現，等於那一天的資料直接沒有——
#: 而換憑證這件事要去 TWCA 抓新的、驗、提交、合併，不是十分鐘做得完的。
WARN_DAYS = 90


def _certs() -> list[bytes]:
    raw = CHAIN.read_bytes()
    out = []
    for block in raw.split(b"-----END CERTIFICATE-----"):
        if b"-----BEGIN CERTIFICATE-----" not in block:
            continue
        body = block.split(b"-----BEGIN CERTIFICATE-----")[1]
        out.append(b"-----BEGIN CERTIFICATE-----" + body + b"-----END CERTIFICATE-----\n")
    return out


def _field(pem: bytes, *args: str) -> str:
    p = subprocess.run(["openssl", "x509", "-noout", *args],
                       input=pem, capture_output=True)
    return p.stdout.decode("utf-8", "replace").strip()


def test_那個_pem_還在而且被載進_tls_context():
    """檔案不見了不會報錯，只會讓櫃買整批再次抓不到——安靜地。"""
    import sys

    sys.path.insert(0, str(CHAIN.parents[3]))
    from twsix.ingest.base import tls_context

    assert CHAIN.is_file(), f"找不到 {CHAIN}"

    ctx = tls_context()
    loaded = {c["subject"][-1][0][1] for c in ctx.get_ca_certs()}
    for name in EXPECTED:
        assert name in loaded, (
            f"{name} 沒有被載進 TLS context——櫃買會再次整批抓不到。"
            f"目前載了 {len(loaded)} 張根憑證。"
        )


def test_裡面那兩張是說好的那兩張():
    """比指紋不是比名字。

    TWCA 底下的 SSL Sub-CA 不只一張，名字一樣、公鑰不一樣。放錯一張的症狀和
    沒放一樣（還是驗不過），但看檔案看不出來。
    """
    certs = _certs()
    assert len(certs) == 2, f"預期兩張憑證（中繼＋根），檔案裡有 {len(certs)} 張"

    got = {}
    for pem in certs:
        cn = _field(pem, "-subject").rsplit("CN = ", 1)[-1].strip()
        der = subprocess.run(["openssl", "x509", "-outform", "DER"],
                             input=pem, capture_output=True).stdout
        got[cn] = hashlib.sha256(der).hexdigest()

    assert got == EXPECTED, (
        "憑證和預期的指紋對不上。\n"
        f"  檔案裡：{got}\n"
        f"  預期：  {EXPECTED}\n"
        "換憑證是可以的，但要連這裡的指紋一起換，而且換之前先確認新的那一張真的"
        "驗得過櫃買的 leaf。"
    )


def test_中繼真的是那張根簽的():
    """兩張湊不成一條鏈的話，補了也是白補。"""
    certs = _certs()
    subj = {_field(p, "-subject"): p for p in certs}
    inter = next(p for s, p in subj.items() if "SSL Sub-CA" in s)
    root = next(p for s, p in subj.items() if "CYBER Root CA" in s)
    assert "TWCA CYBER Root CA" in _field(inter, "-issuer"), "中繼不是那張根簽的"
    # 比的是 DN 本身，不是 openssl 印出來那一行——那兩行一個以 `subject=` 開頭、
    # 一個以 `issuer=` 開頭，直接比永遠不相等。
    def _dn(text: str) -> str:
        return text.split("=", 1)[1].strip()

    assert _dn(_field(root, "-subject")) == _dn(_field(root, "-issuer")), "根不是自簽的"


def test_憑證還沒過期而且離到期還夠遠():
    """過期當天才發現，等於那一天的上櫃資料直接沒有。

    兩張一起在同一個測試裡跑（不是 pytest 的 parametrize）：這個 repo 的測試由
    scripts/run_tests.py 收集，那支只認得「沒有參數的 test_ 函式」——parametrize
    的那一個會以 TypeError 收場，而那個錯誤看起來像測試寫壞了，不像跑錯了。
    """
    certs = _certs()
    for which in sorted(EXPECTED):
        pem = next(p for p in certs if which in _field(p, "-subject"))
        raw = _field(pem, "-enddate").split("=", 1)[1].strip()
        end = dt.datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.UTC)
        left = (end - dt.datetime.now(dt.UTC)).days
        assert left > 0, f"{which} 已經在 {end:%Y-%m-%d} 過期了"
        assert left > WARN_DAYS, (
            f"{which} 還有 {left} 天到期（{end:%Y-%m-%d}）。"
            "去 TWCA 抓新的一張，連同這裡的指紋一起換——"
            "見 src/twsix/ingest/twca_chain.pem 的檔頭。"
        )


def test_檔頭有寫清楚為什麼需要這個檔案():
    """一個沒有理由的憑證檔，下一個人只會不敢動它。"""
    head = CHAIN.read_text(encoding="utf-8")[:3000]
    for token in ("tpex", "AIA", "unable to get local issuer certificate"):
        assert token in head, f"檔頭沒有提到 {token}，將來沒有人知道這是幹嘛的"
