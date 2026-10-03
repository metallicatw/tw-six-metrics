"""網站登入：每一頁 <head> 第一個載入 site/gate.js。

## 兩種模式（看建站時有什麼設定）

1. **Google 帳號＋雲端同步**（repo variable ``FIREBASE_CONFIG`` 有設定時）
   * 只有授權名單上的 Gmail 進得來。名單存在 Firestore 的 ``config/allowlist``，
     管理員登入後頁首右上角有「授權名單管理」圖示，可以直接新增／移除。
   * 觀察清單、持有成本、清單與選股的篩選條件（瀏覽器裡 ``twsix.*`` 的鍵）存到
     Firestore 的 ``users/<uid>``，同一個帳號在電腦、手機上看到同一份。
   * 名單與每個人的資料由 Firestore 規則把關（``reference/firestore.rules``）：
     別人的資料讀不到也改不到。網頁本身仍是公開 repo 建出來的靜態頁，懂技術的人
     還是拿得到**頁面上的公開資料**；擋住的是名單外的人使用、以及每個人的私人設定。
   * GitHub 權杖（``twsix.token``）與手機版／電腦版切換（``twsix.viewmode``）不上傳。

2. **帳號＋密碼**（repo secret ``SITE_LOGIN_USERS``：一行一組 ``帳號:密碼``；舊的
   ``SITE_LOGIN_USER``＋``SITE_LOGIN_PASSWORD`` 也還認得）
   * 純前端，只擋一般人，頁面上只有雜湊。設定不同步。

兩個都沒設就沒有登入。

## 為什麼是一支獨立的 gate.js 而不是每頁內嵌

內嵌的話 1,950 頁每頁多 10 KB；而且增量建站沿用快取、這一次沒重畫的舊頁面也要
換成這一次的設定。所以每一頁只放一行 ``<script src=".../gate.js">``（這支每次建站
都重寫那一行），設定與程式都在 gate.js 裡，換設定只重寫一個檔。

用法：``python scripts/site_gate.py site``（build-site action 在上傳 Pages 之前跑）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

BEGIN, END = "<!--twsix-gate-->", "<!--/twsix-gate-->"
TITLE = "台股與全球市場觀測站"
HOME = "https://metallicatw.github.io/tw-six-metrics/index.html"
#: 系統管理員：永遠在名單上、永遠是管理員（Firestore 規則裡也寫死這一個）。
OWNER = "eggeggyang2005@gmail.com"
#: 第一次啟用時的預設名單（2026-09-30 使用者指定）。之後由管理員在網頁上改。
DEFAULT_USERS = ("eggeggyang2005@gmail.com", "nirvanatw@gmail.com", "doris.yang1108@gmail.com")
FIREBASE_SDK = "11.0.2"
GATE_JS = Path(__file__).with_name("gate.js")
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
_HEAD = re.compile(r"<head(?:\s[^>]*)?>", re.I)  # 不能吃到 <header>

CSS = """
html.tg-lock body>*:not(#tg){display:none!important}
html.tg-lock body{background:#0b1a22!important;margin:0}
#tg{position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;
padding:16px;box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
background:radial-gradient(1200px 600px at 15% 10%,rgba(14,124,111,.55),transparent 60%),
radial-gradient(900px 500px at 90% 90%,rgba(18,122,143,.45),transparent 60%),#0b1a22;color:#e8f1f4}
#tg *{box-sizing:border-box}
#tg .tg-card{width:100%;max-width:380px;background:rgba(255,255,255,.06);backdrop-filter:blur(14px);
-webkit-backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.14);border-radius:18px;
padding:32px 28px 26px;box-shadow:0 24px 60px rgba(0,0,0,.45)}
#tg .tg-mark{width:52px;height:52px;border-radius:14px;margin:0 auto 14px;display:flex;align-items:center;justify-content:center;
background:linear-gradient(135deg,#10b981,#127a8f);box-shadow:0 8px 24px rgba(16,185,129,.35)}
#tg h1{margin:0 0 4px;font-size:20px;font-weight:700;text-align:center;letter-spacing:.04em;color:#fff}
#tg h1 a{color:inherit;text-decoration:none;border-bottom:1px dashed rgba(255,255,255,.35)}
#tg h1 a:hover{color:#5eead4;border-bottom-color:#5eead4}
#tg .tg-sub{margin:0 0 22px;text-align:center;font-size:13px;color:#9fb6bf}
#tg label{display:block;font-size:12px;color:#b9ccd3;margin:0 0 6px;letter-spacing:.06em}
#tg input[type=text],#tg input[type=password]{width:100%;height:44px;border-radius:10px;border:1px solid rgba(255,255,255,.18);
background:rgba(0,0,0,.25);color:#fff;font-size:15px;padding:0 14px;margin:0 0 14px;outline:none;transition:border-color .15s,box-shadow .15s}
#tg input:focus{border-color:#22c1a8;box-shadow:0 0 0 3px rgba(34,193,168,.25)}
#tg .tg-row{display:flex;align-items:center;justify-content:space-between;margin:2px 0 18px;font-size:13px;color:#b9ccd3}
#tg .tg-row label{display:flex;align-items:center;gap:8px;margin:0;font-size:13px;letter-spacing:0;cursor:pointer}
#tg .tg-row input{accent-color:#10b981;width:16px;height:16px;margin:0}
#tg button{width:100%;height:46px;border:0;border-radius:10px;cursor:pointer;font-size:15px;font-weight:700;letter-spacing:.2em;
color:#06231d;background:linear-gradient(135deg,#34d399,#22c1a8);box-shadow:0 10px 24px rgba(16,185,129,.3);transition:transform .08s,filter .15s}
#tg button:hover{filter:brightness(1.06)}#tg button:active{transform:translateY(1px)}
#tg button[disabled]{opacity:.6;cursor:wait}
#tg .tg-err{min-height:20px;margin:12px 0 0;text-align:center;font-size:13px;color:#ff9a8f}
#tg .tg-foot{margin:18px 0 0;text-align:center;font-size:11px;color:#6f8a94}
#tg .tg-shake{animation:tgs .35s}
#tg-icons{position:absolute;top:8px;right:20px;z-index:6;display:flex;gap:8px}
#tg-icons.tg-float{position:fixed;top:10px;right:12px;z-index:2147483646}
#tg-icons .tg-ic{width:32px;height:32px;padding:0;display:inline-flex;align-items:center;justify-content:center;
appearance:none;cursor:pointer;border-radius:999px;border:1px solid var(--rule,#d2dee5);background:var(--surface-2,#e3ecf1);color:var(--ink-2,#33424f)}
#tg-icons.tg-float .tg-ic{box-shadow:0 2px 8px rgba(0,0,0,.18)}
#tg-icons .tg-ic:hover{border-color:var(--accent,#0e7c6f);color:var(--accent,#0e7c6f)}
#tg-icons #tg-out:hover{border-color:var(--up,#cf3327);color:var(--up,#cf3327)}
#tg-icons .tg-ic:focus-visible{outline:2px solid var(--accent-2,#127a8f);outline-offset:2px}
#tg .tg-google{display:flex;align-items:center;justify-content:center;gap:10px;letter-spacing:.06em;background:#fff;color:#1f2937;box-shadow:0 10px 24px rgba(0,0,0,.3)}
#tg.tg-modal{background:rgba(5,15,20,.72)}
#tg textarea{width:100%;border-radius:10px;border:1px solid rgba(255,255,255,.18);background:rgba(0,0,0,.25);color:#fff;
font:14px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;padding:10px 12px;margin:0 0 14px;outline:none;resize:vertical}
#tg textarea:focus{border-color:#22c1a8;box-shadow:0 0 0 3px rgba(34,193,168,.25)}
#tg .tg-btns{display:flex;gap:10px}
#tg .tg-btns button{flex:1}
#tg .tg-ghost{background:transparent!important;color:#e8f1f4!important;border:1px solid rgba(255,255,255,.25)!important;box-shadow:none!important}
"""

def credentials(user: str, password: str) -> tuple[str, str]:
    """(salt, hash)。salt 由帳號決定：同一組帳密每次建站得到同一個雜湊，
    讀者不會因為網站重建就被登出。帳號不分大小寫。"""
    user = user.strip().lower()
    salt = hashlib.sha256(f"twsix-gate|{user}".encode()).hexdigest()[:16]
    digest = hashlib.sha256(f"{salt}{user}\n{password}".encode()).hexdigest()
    return salt, digest


def parse_users(text: str) -> list[tuple[str, str]]:
    """``帳號:密碼`` 一行一組（也接受逗號或分號分隔）。密碼裡可以有冒號。"""
    out = []
    for line in re.split(r"[\r\n;,]+", text or ""):
        if ":" not in line:
            continue
        user, password = line.split(":", 1)
        if user.strip() and password:
            out.append((user.strip(), password))
    return out


def config_from_env(env: dict[str, str] | None = None) -> dict | None:
    env = dict(os.environ if env is None else env)
    common = {"title": TITLE, "home": HOME}
    fb = (env.get("FIREBASE_CONFIG") or "").strip()
    if fb:
        if "{" in fb and "}" in fb:   # 整段「const firebaseConfig = {...};」貼進來也可以
            fb = fb[fb.index("{"): fb.rindex("}") + 1]
        try:
            cfg = json.loads(fb)
        except json.JSONDecodeError:
            # 從 Firebase 主控台複製來的常是 JS 物件寫法（key 沒有引號）。
            cfg = json.loads(re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', fb.rstrip(";")))
        need = ("apiKey", "authDomain", "projectId", "appId")
        missing = [k for k in need if not cfg.get(k)]
        if missing:
            raise SystemExit(f"FIREBASE_CONFIG 少了 {', '.join(missing)}")
        return {"mode": "firebase", "fb": cfg, "owner": OWNER, "defaults": list(DEFAULT_USERS),
                "sdk": FIREBASE_SDK, **common}
    users = parse_users(env.get("SITE_LOGIN_USERS", ""))
    if env.get("SITE_LOGIN_USER", "").strip() and env.get("SITE_LOGIN_PASSWORD"):
        users.append((env["SITE_LOGIN_USER"].strip(), env["SITE_LOGIN_PASSWORD"]))
    if users:
        rows = []
        for user, password in users:
            salt, digest = credentials(user, password)
            rows.append({"u": user.lower(), "s": salt, "h": digest})
        return {"mode": "password", "users": rows, **common}
    return None


def gate_js(config: dict) -> str:
    css = " ".join(line.strip() for line in CSS.strip().splitlines())
    src = GATE_JS.read_text("utf-8")
    return (src.replace("__CONFIG__", json.dumps(config, ensure_ascii=False))
               .replace("__CSS__", json.dumps(css, ensure_ascii=False)))


def tag(rel: str) -> str:
    return f'{BEGIN}<script src="{rel}gate.js"></script>{END}'


def apply(html: str, gate: str | None) -> str:
    """把頁面上的那一段換成 *gate*（None 就拿掉）。沒有 <head> 的片段不動。"""
    html = _BLOCK.sub("", html)
    if not gate:
        return html
    m = _HEAD.search(html)
    if not m:
        return html
    return html[: m.end()] + gate + html[m.end():]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0] if args else "site")
    config = config_from_env()
    js = root / "gate.js"
    if config:
        js.write_text(gate_js(config), "utf-8")
    elif js.exists():
        js.unlink()
    changed = 0
    for path in root.rglob("*.html"):
        depth = len(path.relative_to(root).parts) - 1
        text = path.read_text("utf-8", errors="replace")
        new = apply(text, tag("../" * depth) if config else None)
        if new != text:
            path.write_text(new, "utf-8")
            changed += 1
    state = {"firebase": "Google 帳號登入＋雲端同步", "password": "帳號密碼登入"}.get(
        (config or {}).get("mode", ""), "沒有設定登入，不加")
    if config and config["mode"] == "password":
        state += f"（{len(config['users'])} 組帳號）"
    print(f"登入畫面：{state}（改了 {changed} 頁）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
