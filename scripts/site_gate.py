
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

BEGIN, END = "<!--twsix-gate-->", "<!--/twsix-gate-->"
TITLE = "金股道"
TAGLINE = "GoldenWay｜禾熟之時，金股自到"
HOME = "https://metallicatw.github.io/tw-six-metrics/index.html"
FIREBASE_SDK = "11.0.2"
GATE_JS = Path(__file__).with_name("gate.js")
LOGO_SVG = Path(__file__).resolve().parents[1] / "src/twsix/report/templates/icons/favicon.svg"
_BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
_HEAD = re.compile(r"<head(?:\s[^>]*)?>", re.I)

CSS = """
html.tg-lock body>*:not(#tg){display:none!important}
html.tg-lock body{background:#0b1016!important;margin:0}
#tg{position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;
padding:16px;box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI","Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
background:radial-gradient(700px 420px at 50% 28%,rgba(200,150,46,.13),transparent 70%),#0b1016;color:#e8eef4}
#tg *{box-sizing:border-box}
#tg .tg-card{width:100%;max-width:360px;background:#141b22;border:1px solid rgba(255,255,255,.07);border-radius:16px;
padding:34px 28px 22px;box-shadow:0 24px 60px rgba(0,0,0,.5);text-align:center}
#tg .tg-mark{width:88px;height:88px;margin:0 auto 14px;display:flex;align-items:center;justify-content:center;
filter:drop-shadow(0 8px 22px rgba(200,150,46,.25))}
#tg .tg-mark svg{display:block;width:88px;height:88px}
#tg h1{margin:0;font-size:26px;font-weight:700;text-align:center;letter-spacing:.24em;text-indent:.24em;
background:linear-gradient(180deg,#f3d27a,#c8962e);-webkit-background-clip:text;background-clip:text;color:transparent}
#tg .tg-tag{margin:6px 0 26px;text-align:center;font-size:12px;letter-spacing:.14em;color:#b8924a}
#tg .tg-sub{margin:0 0 18px;text-align:center;font-size:13px;color:#8b99a6}
#tg label{display:block;text-align:left;font-size:12px;color:#b6c3cf;margin:0 0 6px;letter-spacing:.06em}
#tg input[type=text],#tg input[type=password]{width:100%;height:44px;border-radius:10px;border:1px solid rgba(255,255,255,.12);
background:#0b1016;color:#fff;font-size:15px;padding:0 14px;margin:0 0 14px;outline:none;transition:border-color .15s,box-shadow .15s}
#tg input:focus{border-color:#c8962e;box-shadow:0 0 0 3px rgba(200,150,46,.22)}
#tg .tg-row{display:flex;align-items:center;justify-content:space-between;margin:2px 0 18px;font-size:13px;color:#b6c3cf}
#tg .tg-row label{display:flex;align-items:center;gap:8px;margin:0;font-size:13px;letter-spacing:0;cursor:pointer}
#tg .tg-row input{accent-color:#c8962e;width:16px;height:16px;margin:0}
#tg button{width:100%;height:46px;border:0;border-radius:10px;cursor:pointer;font-size:15px;font-weight:700;letter-spacing:.2em;
color:#1a1206;background:linear-gradient(180deg,#f0cd74,#c8962e);box-shadow:0 10px 24px rgba(200,150,46,.22);transition:transform .08s,filter .15s}
#tg button:hover{filter:brightness(1.06)}#tg button:active{transform:translateY(1px)}
#tg button[disabled]{opacity:.6;cursor:wait}
#tg .tg-err{min-height:18px;margin:10px 0 0;text-align:center;font-size:13px;color:#ff9a8f}
#tg .tg-foot{margin:14px 0 0;padding-top:14px;border-top:1px solid rgba(255,255,255,.07);text-align:center;font-size:12px;color:#8b99a6;letter-spacing:.04em}
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
    user = user.strip().lower()
    salt = hashlib.sha256(f"twsix-gate|{user}".encode()).hexdigest()[:16]
    digest = hashlib.sha256(f"{salt}{user}\n{password}".encode()).hexdigest()
    return salt, digest


def parse_users(text: str) -> list[tuple[str, str]]:
    out = []
    for line in re.split(r"[\r\n;,]+", text or ""):
        if ":" not in line:
            continue
        user, password = line.split(":", 1)
        if user.strip() and password:
            out.append((user.strip(), password))
    return out


def logo_svg() -> str:
    try:
        svg = LOGO_SVG.read_text(encoding="utf-8")
    except OSError:
        return ""
    svg = re.sub(r"<!--.*?-->", "", svg, flags=re.S)
    svg = re.sub(r'id="([\w-]+)"', r'id="tgf-\1"', svg)
    svg = re.sub(r"url\(#([\w-]+)\)", r"url(#tgf-\1)", svg)
    svg = svg.replace("<svg ", '<svg width="88" height="88" aria-hidden="true" ', 1)
    return re.sub(r">\s+<", "><", svg).strip()


def config_from_env(env: dict[str, str] | None = None) -> dict | None:
    env = dict(os.environ if env is None else env)
    common = {"title": TITLE, "tagline": TAGLINE, "home": HOME, "logo": logo_svg()}
    fb = (env.get("FIREBASE_CONFIG") or "").strip()
    if fb:
        if "{" in fb and "}" in fb:
            fb = fb[fb.index("{"): fb.rindex("}") + 1]
        try:
            cfg = json.loads(fb)
        except json.JSONDecodeError:
            cfg = json.loads(re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', fb.rstrip(";")))
        need = ("apiKey", "authDomain", "projectId", "appId")
        missing = [k for k in need if not cfg.get(k)]
        if missing:
            raise SystemExit(f"FIREBASE_CONFIG 少了 {', '.join(missing)}")
        owner = (env.get("SITE_OWNER") or "").strip().lower()
        owner_h = hashlib.sha256(owner.encode()).hexdigest() if owner else ""
        return {"mode": "firebase", "fb": cfg, "ownerH": owner_h, "sdk": FIREBASE_SDK, **common}
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
