"""登入畫面：每一頁都有、可以換、可以拿掉，而且每個建站的呼叫端都把帳密傳進去。"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

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


def _build_site_steps(text: str) -> list[str]:
    """每一個 `uses: ./.github/actions/build-site` 那一步的整段文字。

    不用 yaml：ci 的第一步是「零相依測試」，那台機器上沒有 PyYAML（2026-10-03
    這條測試就是因為 `import yaml` 在那一步紅掉）。一步從 `- ` 開頭到下一個同縮排
    的 `- ` 為止。
    """
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if "uses: ./.github/actions/build-site" not in line:
            continue
        start = i
        while start > 0 and not lines[start].lstrip().startswith("- "):
            start -= 1
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = i + 1
        while end < len(lines):
            cur = lines[end]
            if cur.strip() and len(cur) - len(cur.lstrip()) <= indent:
                break
            end += 1
        out.append("\n".join(lines[start:end]))
    return out


def test_every_build_site_caller_passes_the_login_secrets():
    """action 讀不到 secrets。漏傳的那一條一建站，就會把整站的門拿掉。"""
    missing = []
    seen = 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for step in _build_site_steps(wf.read_text("utf-8")):
            seen += 1
            for key in ("SITE_LOGIN_USER", "SITE_LOGIN_PASSWORD"):
                if f"{key}: ${{{{ secrets.{key} }}}}" not in step:
                    missing.append(f"{wf.name}: {key}")
    assert seen >= 7, f"只找到 {seen} 個建站步驟，解析可能壞了"
    assert not missing, "這些建站步驟沒有把登入帳密傳進去：\n  " + "\n  ".join(missing)


def test_a_page_without_head_is_left_alone_even_with_a_header_tag():
    frag = "<header class='top'>x</header>"
    assert sg.apply(frag, sg.block("u", "p")) == frag
