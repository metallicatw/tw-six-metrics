"""登入畫面：每一頁都有、可以換、可以拿掉，而且每個建站的呼叫端都把帳密傳進去。"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("site_gate", ROOT / "scripts" / "site_gate.py")
sg = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["site_gate"] = sg
_spec.loader.exec_module(sg)

PAGE = "<!doctype html><html><head><meta charset='utf-8'><title>台股｜x</title></head><body>hi</body></html>"


def test_the_page_carries_only_a_hash_never_the_password():
    out = sg.apply(PAGE, sg.block("egg", "s3cret-pw"))
    assert "s3cret-pw" not in out
    salt, digest = sg.credentials("egg", "s3cret-pw")
    assert digest == hashlib.sha256(f"{salt}egg\ns3cret-pw".encode()).hexdigest()
    assert digest in out and out.index(sg.BEGIN) > out.index("<head>")


def test_reapplying_replaces_instead_of_stacking():
    once = sg.apply(PAGE, sg.block("egg", "a"))
    twice = sg.apply(once, sg.block("egg", "b"))
    assert twice.count(sg.BEGIN) == 1
    assert sg.credentials("egg", "b")[1] in twice and sg.credentials("egg", "a")[1] not in twice
    assert sg.apply(twice, None) == PAGE           # 沒設帳密：整段拿掉，頁面回原樣


def test_same_credentials_give_the_same_hash_across_builds():
    assert sg.credentials("egg", "pw") == sg.credentials("egg", "pw")
    assert sg.credentials("egg", "pw") != sg.credentials("egg2", "pw")


def test_every_build_site_caller_passes_the_login_secrets():
    """action 讀不到 secrets。漏傳的那一條一建站，就會把整站的門拿掉。"""
    missing = []
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(wf.read_text("utf-8"))
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                if "actions/build-site" in str(step.get("uses", "")):
                    env = step.get("env") or {}
                    for key in ("SITE_LOGIN_USER", "SITE_LOGIN_PASSWORD"):
                        if f"secrets.{key}" not in str(env.get(key, "")):
                            missing.append(f"{wf.name}: {key}")
    assert not missing, "這些建站步驟沒有把登入帳密傳進去：\n  " + "\n  ".join(missing)


def test_a_page_without_head_is_left_alone_even_with_a_header_tag():
    frag = "<header class='top'>x</header>"
    assert sg.apply(frag, sg.block("u", "p")) == frag
