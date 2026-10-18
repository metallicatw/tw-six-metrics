from __future__ import annotations

import datetime as dt
import hashlib
import subprocess
from pathlib import Path

CHAIN = Path(__file__).resolve().parents[1] / "src" / "twsix" / "ingest" / "twca_chain.pem"

EXPECTED = {
    "TWCA SSL Certification Authority":
        "01af2324d098098f5e0cdf6faabada430b21cce777f47eacb26248b2fda3e531",
    "TWCA CYBER Root CA":
        "3f63bb2814be174ec8b6439cf08d6d56f0b7c405883a5648a334424d6b3ec558",
}

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
    certs = _certs()
    subj = {_field(p, "-subject"): p for p in certs}
    inter = next(p for s, p in subj.items() if "SSL Sub-CA" in s)
    root = next(p for s, p in subj.items() if "CYBER Root CA" in s)
    assert "TWCA CYBER Root CA" in _field(inter, "-issuer"), "中繼不是那張根簽的"
    def _dn(text: str) -> str:
        return text.split("=", 1)[1].strip()

    assert _dn(_field(root, "-subject")) == _dn(_field(root, "-issuer")), "根不是自簽的"


def test_憑證還沒過期而且離到期還夠遠():
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
    head = CHAIN.read_text(encoding="utf-8")[:3000]
    for token in ("tpex", "AIA", "unable to get local issuer certificate"):
        assert token in head, f"檔頭沒有提到 {token}，將來沒有人知道這是幹嘛的"
