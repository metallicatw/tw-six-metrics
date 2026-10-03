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


def test_password_mode_ships_only_hashes_never_passwords():
    cfg = sg.config_from_env({"SITE_LOGIN_USERS": "egg:s3cret-pw\nDoris:pa:ss"})
    assert cfg is not None and cfg["mode"] == "password"
    js = sg.gate_js(cfg)
    assert "s3cret-pw" not in js and "pa:ss" not in js
    salt, digest = sg.credentials("egg", "s3cret-pw")
    assert digest == hashlib.sha256(f"{salt}egg\ns3cret-pw".encode()).hexdigest()
    assert digest in js
    assert sg.credentials("Doris", "pa:ss") == sg.credentials("doris", "pa:ss")   # 帳號不分大小寫
    assert [u["u"] for u in cfg["users"]] == ["egg", "doris"]


def test_legacy_single_user_secrets_still_work():
    cfg = sg.config_from_env({"SITE_LOGIN_USER": "egg", "SITE_LOGIN_PASSWORD": "pw"})
    assert cfg and cfg["mode"] == "password" and len(cfg["users"]) == 1


def test_firebase_config_wins_and_accepts_the_console_snippet():
    snippet = """const firebaseConfig = {
      apiKey: "AIzaFake",
      authDomain: "tw-six.firebaseapp.com",
      projectId: "tw-six",
      storageBucket: "tw-six.appspot.com",
      messagingSenderId: "123",
      appId: "1:123:web:abc"
    };"""
    cfg = sg.config_from_env({"FIREBASE_CONFIG": snippet, "SITE_LOGIN_USERS": "a:b"})
    assert cfg and cfg["mode"] == "firebase"
    assert cfg["fb"]["projectId"] == "tw-six" and cfg["owner"] == sg.OWNER
    assert sg.OWNER in cfg["defaults"]


def test_nothing_configured_means_no_gate():
    assert sg.config_from_env({}) is None


def test_the_token_and_the_view_mode_are_never_synced():
    """GitHub 權杖只能留在這台瀏覽器（專案的安全規則），手機／電腦版是裝置的事。"""
    js = sg.GATE_JS.read_text("utf-8")
    assert 'k !== "twsix.token"' in js and 'k !== "twsix.viewmode"' in js


def test_rules_pin_the_owner_and_scope_user_data_to_its_owner():
    rules = (ROOT / "reference" / "firestore.rules").read_text("utf-8")
    assert sg.OWNER in rules
    assert "request.auth.uid == uid" in rules
    assert "allow read, write: if false;" in rules


def test_every_page_gets_one_script_tag_at_its_depth():
    import os
    import tempfile

    tmp_path = Path(tempfile.mkdtemp(prefix="twsix-gate-"))
    (tmp_path / "stock").mkdir()
    (tmp_path / "index.html").write_text(PAGE, "utf-8")
    (tmp_path / "stock" / "2330.html").write_text(PAGE, "utf-8")
    old = dict(os.environ)
    try:
        os.environ["SITE_LOGIN_USERS"] = "egg:pw"
        sg.main([str(tmp_path)])
        sg.main([str(tmp_path)])                      # 重跑不疊加
        top = (tmp_path / "index.html").read_text("utf-8")
        deep = (tmp_path / "stock" / "2330.html").read_text("utf-8")
        assert top.count(sg.BEGIN) == 1 and '<script src="gate.js">' in top
        assert '<script src="../gate.js">' in deep
        assert (tmp_path / "gate.js").exists()
        os.environ.pop("SITE_LOGIN_USERS")
        sg.main([str(tmp_path)])                      # 拿掉設定：整段與 gate.js 都拿掉
        assert (tmp_path / "index.html").read_text("utf-8") == PAGE
        assert not (tmp_path / "gate.js").exists()
    finally:
        os.environ.clear()
        os.environ.update(old)


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
            for key, src in (("SITE_LOGIN_USER", "secrets"), ("SITE_LOGIN_PASSWORD", "secrets"),
                             ("SITE_LOGIN_USERS", "secrets"), ("FIREBASE_CONFIG", "vars")):
                if f"{key}: ${{{{ {src}.{key} }}}}" not in step:
                    missing.append(f"{wf.name}: {key}")
    assert seen >= 7, f"只找到 {seen} 個建站步驟，解析可能壞了"
    assert not missing, "這些建站步驟沒有把登入帳密傳進去：\n  " + "\n  ".join(missing)


def test_a_page_without_head_is_left_alone_even_with_a_header_tag():
    frag = "<header class='top'>x</header>"
    assert sg.apply(frag, sg.tag("")) == frag
