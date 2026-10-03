"""在網站每一頁加上登入畫面（帳號＋密碼）。

## 它擋得住什麼、擋不住什麼

這是**純前端**的門：密碼對了才把頁面內容顯示出來。它擋的是「拿到網址的一般人」，
擋不住懂技術的人——網站是 GitHub Pages、repo 是公開的，原始資料（data/ 底下的
CSV、網站的 JSON）本來就能直接下載，看網頁原始碼也繞得過去。2026-10-03 討論過
三個等級（純前端／整頁加密／Cloudflare Access），使用者選了這一個。

## 帳號密碼放哪裡

repo secret `SITE_LOGIN_USER` 與 `SITE_LOGIN_PASSWORD`。建站時從環境變數讀，頁面上
只放**雜湊**（SHA-256，帳號決定 salt），不放明文；兩個都沒設就把門拿掉（本機建站、
測試都不受影響）。改密碼只要改 secret，下一次建站全站一起換——包括增量建站沿用
快取、這一次沒有重畫的那些頁面：這支每一次都重寫每一頁的那一段。

## 怎麼記住登入

登入成功後把雜湊存在瀏覽器（勾「記住我」用 localStorage，否則 sessionStorage，
關掉分頁就要重登）。密碼一改，雜湊跟著變，舊的登入自動失效。網址加 `?logout`
就登出；登入後頁首右上角（「切換手機版」右邊）有登出圖示，沒有站內頁首的頁面則固定在畫面右上角。

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
#tg-out{position:absolute;top:8px;right:20px;z-index:6;width:32px;height:32px;padding:0;display:inline-flex;align-items:center;justify-content:center;
appearance:none;cursor:pointer;border-radius:999px;border:1px solid var(--rule,#d2dee5);background:var(--surface-2,#e3ecf1);color:var(--ink-2,#33424f)}
#tg-out:hover{border-color:var(--up,#cf3327);color:var(--up,#cf3327)}
#tg-out:focus-visible{outline:2px solid var(--accent-2,#127a8f);outline-offset:2px}
#tg-out.tg-float{position:fixed;top:10px;right:12px;z-index:2147483646;box-shadow:0 2px 8px rgba(0,0,0,.18)}
html.tg-in header.top button.viewmode{right:60px}
html.tg-in header.top h1{padding-right:146px}
@keyframes tgs{20%,60%{transform:translateX(-7px)}40%,80%{transform:translateX(7px)}}
"""

JS = r"""
(function(){var H=%(hash)s,S=%(salt)s,K="twsix-gate",d=document.documentElement;
function get(s){try{return s.getItem(K)}catch(e){return null}}
function put(s,v){try{s.setItem(K,v)}catch(e){}}
function out(){try{localStorage.removeItem(K);sessionStorage.removeItem(K)}catch(e){}location.reload()}
function exit(){if(document.getElementById("tg-out"))return;var x=document.createElement("button"),h=document.querySelector("header.top .in");
x.id="tg-out";x.type="button";x.title="登出";x.setAttribute("aria-label","登出");
x.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></svg>';
x.addEventListener("click",out);if(h){h.appendChild(x);d.classList.add("tg-in")}else{x.className="tg-float";document.body.appendChild(x)}}
function later(f){if(document.body)f();else document.addEventListener("DOMContentLoaded",f)}
if(/[?&]logout\b/.test(location.search)){try{localStorage.removeItem(K);sessionStorage.removeItem(K)}catch(e){}}
else if(get(localStorage)===H||get(sessionStorage)===H){later(exit);return}
d.classList.add("tg-lock");
function hex(b){return Array.prototype.map.call(new Uint8Array(b),function(x){return("0"+x.toString(16)).slice(-2)}).join("")}
function show(){if(document.getElementById("tg"))return;var w=document.createElement("div");w.id="tg";
w.innerHTML='<form class="tg-card" autocomplete="on"><div class="tg-mark"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l5-5 4 4 8-8"/><path d="M14 8h6v6"/></svg></div>'+
'<h1></h1><p class="tg-sub">請登入後繼續</p>'+
'<label for="tg-u">帳號</label><input id="tg-u" type="text" name="username" autocomplete="username" required>'+
'<label for="tg-p">密碼</label><input id="tg-p" type="password" name="password" autocomplete="current-password" required>'+
'<div class="tg-row"><label><input id="tg-r" type="checkbox" checked>記住我</label></div>'+
'<button type="submit">登入</button><p class="tg-err" role="alert"></p><p class="tg-foot">僅限授權使用者</p></form>';
var t=w.querySelector("h1").appendChild(document.createElement("a"));t.href=%(home)s;t.textContent=%(title)s;
document.body.appendChild(w);var f=w.querySelector("form"),e=w.querySelector(".tg-err"),b=w.querySelector("button");
setTimeout(function(){w.querySelector("#tg-u").focus()},30);
f.addEventListener("submit",function(ev){ev.preventDefault();
if(!(window.crypto&&crypto.subtle)){e.textContent="這個瀏覽器不支援安全登入，請改用 https 開啟";return}
var u=w.querySelector("#tg-u").value.trim(),p=w.querySelector("#tg-p").value;b.disabled=true;e.textContent="";
crypto.subtle.digest("SHA-256",new TextEncoder().encode(S+u+"\n"+p)).then(function(r){b.disabled=false;
if(hex(r)===H){put(w.querySelector("#tg-r").checked?localStorage:sessionStorage,H);d.classList.remove("tg-lock");w.remove();exit()}
else{e.textContent="帳號或密碼不正確";f.classList.remove("tg-shake");void f.offsetWidth;f.classList.add("tg-shake");w.querySelector("#tg-p").select()}})})}
later(show)})();
"""


def credentials(user: str, password: str) -> tuple[str, str]:
    """(salt, hash)。salt 由帳號決定：同一組帳密每次建站得到同一個雜湊，
    讀者不會因為網站重建就被登出。"""
    salt = hashlib.sha256(f"twsix-gate|{user}".encode()).hexdigest()[:16]
    digest = hashlib.sha256(f"{salt}{user}\n{password}".encode()).hexdigest()
    return salt, digest


def block(user: str, password: str) -> str:
    salt, digest = credentials(user, password)
    js = JS % {"hash": json.dumps(digest), "salt": json.dumps(salt),
               "title": json.dumps(TITLE, ensure_ascii=False), "home": json.dumps(HOME)}
    css = " ".join(line.strip() for line in CSS.strip().splitlines())
    return f"{BEGIN}<style>{css}</style><script>{js.strip()}</script>{END}"


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
    user = os.environ.get("SITE_LOGIN_USER", "").strip()
    password = os.environ.get("SITE_LOGIN_PASSWORD", "")
    gate = block(user, password) if user and password else None
    changed = 0
    for path in root.rglob("*.html"):
        text = path.read_text("utf-8", errors="replace")
        new = apply(text, gate)
        if new != text:
            path.write_text(new, "utf-8")
            changed += 1
    state = "加上登入畫面" if gate else "沒有設定 SITE_LOGIN_USER／SITE_LOGIN_PASSWORD，不加登入"
    print(f"登入畫面：{state}（改了 {changed} 頁）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
