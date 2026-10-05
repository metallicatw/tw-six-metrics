/* 網站登入（由 scripts/site_gate.py 產生 site/gate.js，每一頁 <head> 第一個載入）。
 *
 * 兩種模式，看建站時給了什麼設定：
 *
 *   firebase  Google 帳號登入，只放行授權名單上的 email；觀察清單、持有成本、
 *             篩選條件（localStorage 裡 twsix.* 的那些）存到 Firestore，跟著帳號
 *             在每台裝置之間同步。名單與資料的存取由 Firestore 規則把關
 *             （reference/firestore.rules），不是只靠這支前端程式。
 *   password  帳號＋密碼（頁面上只有雜湊）。純前端，只擋一般人；設定不同步。
 *
 * ⚠️ twsix.token（GitHub 權杖）與 twsix.viewmode（這台裝置要看手機版還是電腦版）
 *    永遠不上傳。
 */
(function () {
  var C = __CONFIG__;
  /* 被站內頁面用 iframe 嵌進去的（〔市場監控〕〔趨勢選股〕那兩份報告）：外層頁面已經
     把關、也已經有登出圖示了，這裡什麼都不做——不鎖、不畫第二顆登出、不重複同步。
     讀得到 top 的 document 才算站內（同源）；被別的網站嵌進去的照常把關。 */
  try { if (window.top !== window.self && window.top.document) return; } catch (e) {}
  var d = document.documentElement, K = "twsix-gate", M = "twsix-sync";
  var SP = Storage.prototype, _get = SP.getItem, _set = SP.setItem, _rm = SP.removeItem;

  var st = document.createElement("style");
  st.textContent = __CSS__;
  (document.head || d).appendChild(st);

  function lget(k) { try { return _get.call(localStorage, k); } catch (e) { return null; } }
  function lset(k, v) { try { _set.call(localStorage, k, v); } catch (e) {} }
  function lrm(k) { try { _rm.call(localStorage, k); } catch (e) {} }
  function sget(k) { try { return _get.call(sessionStorage, k); } catch (e) { return null; } }
  function sset(k, v) { try { _set.call(sessionStorage, k, v); } catch (e) {} }
  function later(f) { if (document.body) f(); else document.addEventListener("DOMContentLoaded", f); }
  function lock() { d.classList.add("tg-lock"); }
  function unlock() { d.classList.remove("tg-lock"); var w = document.getElementById("tg"); if (w) w.remove(); }

  /* 哪些鍵跟著帳號走。 */
  function synced(k) {
    return typeof k === "string" && k.indexOf("twsix.") === 0 && k !== "twsix.token" && k !== "twsix.viewmode";
  }
  function localKv() {
    var kv = {};
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (synced(k)) kv[k] = _get.call(localStorage, k);
      }
    } catch (e) {}
    return kv;
  }
  function clearLocal() { Object.keys(localKv()).forEach(lrm); }

  /* ── 外框：登入卡片 ─────────────────────────────────────────────── */
  function card(inner) {
    var w = document.getElementById("tg");
    if (!w) { w = document.createElement("div"); w.id = "tg"; document.body.appendChild(w); }
    w.innerHTML = '<div class="tg-card"><div class="tg-mark">' + (C.logo || '') + '</div>' +
      '<h1></h1>' + inner + '<p class="tg-foot">僅限授權使用者</p></div>';
    w.querySelector("h1").textContent = C.title;   // 純文字，不加連結（2026-10-04）
    return w;
  }
  function icon(id, title, path, onClick) {
    if (document.getElementById(id)) return;
    var box = document.getElementById("tg-icons"), h = document.querySelector("header.top .in");
    if (!box) {
      box = document.createElement("div"); box.id = "tg-icons";
      if (h) h.appendChild(box); else { box.classList.add("tg-float"); document.body.appendChild(box); }
    }
    var x = document.createElement("button");
    x.id = id; x.type = "button"; x.title = title; x.setAttribute("aria-label", title); x.className = "tg-ic";
    x.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + path + '</svg>';
    x.addEventListener("click", onClick);
    if (id === "tg-out") box.appendChild(x); else box.insertBefore(x, box.firstChild);   // 登出永遠在最右邊
    if (h) {
      // 「切換手機版」那顆按鈕與標題讓出圖示的寬度。
      var w = box.offsetWidth + 8, vm = h.querySelector("button.viewmode"), t = h.querySelector("h1");
      if (vm) vm.style.right = (20 + w) + "px";
      if (t) t.style.paddingRight = (104 + w) + "px";
    }
  }
  var OUT_PATH = '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>';
  var ADMIN_PATH = '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>';

  if (C.mode === "password") return passwordMode();
  if (C.mode === "firebase") return firebaseMode();

  /* ── 帳號＋密碼 ───────────────────────────────────────────────────── */
  function passwordMode() {
    var ok = {};
    C.users.forEach(function (u) { ok[u.h] = 1; });
    function out() { lrm(K); try { sessionStorage.removeItem(K); } catch (e) {} location.reload(); }
    function exit() { later(function () { icon("tg-out", "登出", OUT_PATH, out); }); }
    if (/[?&]logout\b/.test(location.search)) { lrm(K); try { sessionStorage.removeItem(K); } catch (e) {} }
    else if (ok[lget(K)] || ok[sget(K)]) { exit(); return; }
    lock();
    function hex(b) { return Array.prototype.map.call(new Uint8Array(b), function (x) { return ("0" + x.toString(16)).slice(-2); }).join(""); }
    later(function () {
      var w = card('<p class="tg-sub">請登入後繼續</p><form autocomplete="on">' +
        '<label for="tg-u">帳號</label><input id="tg-u" type="text" name="username" autocomplete="username" required>' +
        '<label for="tg-p">密碼</label><input id="tg-p" type="password" name="password" autocomplete="current-password" required>' +
        '<div class="tg-row"><label><input id="tg-r" type="checkbox" checked>記住我</label></div>' +
        '<button type="submit" class="tg-go">登入</button><p class="tg-err" role="alert"></p></form>');
      var f = w.querySelector("form"), e = w.querySelector(".tg-err"), b = w.querySelector(".tg-go");
      setTimeout(function () { w.querySelector("#tg-u").focus(); }, 30);
      f.addEventListener("submit", function (ev) {
        ev.preventDefault();
        if (!(window.crypto && crypto.subtle)) { e.textContent = "這個瀏覽器不支援安全登入，請改用 https 開啟"; return; }
        var u = w.querySelector("#tg-u").value.trim().toLowerCase(), p = w.querySelector("#tg-p").value;
        var me = C.users.filter(function (x) { return x.u === u; })[0];
        b.disabled = true; e.textContent = "";
        var salt = me ? me.s : "x";
        crypto.subtle.digest("SHA-256", new TextEncoder().encode(salt + u + "\n" + p)).then(function (r) {
          b.disabled = false;
          var h = hex(r);
          if (me && h === me.h) {
            var store = w.querySelector("#tg-r").checked ? localStorage : sessionStorage;
            try { _set.call(store, K, h); } catch (x) {}
            unlock(); exit();
          } else {
            e.textContent = "帳號或密碼不正確";
            f.classList.remove("tg-shake"); void f.offsetWidth; f.classList.add("tg-shake");
            w.querySelector("#tg-p").select();
          }
        });
      });
    });
  }

  /* ── Google 帳號＋雲端同步 ───────────────────────────────────────── */
  function firebaseMode() {
    var cached = lget(K) || "";
    if (cached.indexOf("fb:") !== 0) lock();   // 這台瀏覽器之前登入過的就先放行，背景再確認

    /* 本機的改動：記下「有沒同步的」，稍後一起上傳。 */
    var user = null, ref = null, timer = null, denied = "";
    function meta() { try { return JSON.parse(lget(M) || "null"); } catch (e) { return null; } }
    function setMeta(m) { lset(M, JSON.stringify(m)); }
    // seq：本機改了幾次；synced：雲端已經有到第幾次。兩個不一樣＝有還沒上傳的改動。
    function dirty(m) { return !!m && (m.seq || 0) !== (m.synced || 0); }
    function touched(k) {
      if (!synced(k)) return;
      var m = meta() || {}; m.seq = (m.seq || 0) + 1; setMeta(m);
      if (ref) { clearTimeout(timer); timer = setTimeout(push, 1200); }
    }
    // 只有值真的變了才算改動：清單頁每次載入都會把篩選條件原樣寫回去一次，
    // 那不能被當成「本機有新改動」而蓋掉別台裝置剛存上去的版本。
    SP.setItem = function (k, v) {
      var mine = this === window.localStorage, before = mine ? _get.call(this, k) : null;
      _set.call(this, k, v);
      if (mine && before !== String(v)) touched(k);
    };
    SP.removeItem = function (k) {
      var mine = this === window.localStorage, before = mine ? _get.call(this, k) : null;
      _rm.call(this, k);
      if (mine && before !== null) touched(k);
    };
    window.addEventListener("pagehide", function () { if (timer) { clearTimeout(timer); push(); } });

    function push() {
      timer = null;
      if (!ref || !user) return;
      var rev = Date.now(), seq = (meta() || {}).seq || 0;
      ref.set({ email: user.email.toLowerCase(), kv: localKv(), rev: rev,
                updated: firebase.firestore.FieldValue.serverTimestamp() })
        .then(function () {
          var m = meta() || {};                       // 上傳途中又改了的話 seq 會比較大，留著下次再傳
          setMeta({ uid: user.uid, rev: rev, seq: m.seq || seq, synced: seq });
        })
        .catch(function (e) { console.warn("[登入] 雲端同步失敗", e); });
    }
    function replaceLocal(kv) {
      clearLocal();
      Object.keys(kv || {}).forEach(function (k) { if (synced(k) && typeof kv[k] === "string") lset(k, kv[k]); });
    }
    function reloadOnce(rev) {
      // 換了一份資料就重新載入這一頁，讓畫面讀到新的清單；同一份只重載一次，不會打轉。
      if (sget("twsix-sync-reload") === String(rev)) return;
      sset("twsix-sync-reload", String(rev));
      location.reload();
    }
    function sync() {
      ref.get().then(function (snap) {
        var r = snap.exists ? snap.data() : null, m = meta();
        if (!m || m.uid !== user.uid) {
          var other = m && m.uid && m.uid !== user.uid;
          if (other) clearLocal();                             // 這台瀏覽器上一位是別的帳號：不要把他的資料帶過來
          if (!r || !r.kv) { push(); return; }                 // 這個帳號第一次登入：把這台瀏覽器原有的清單搬上去
          // 這台裝置第一次登入、雲端已經有資料（例如先在手機登入過）：合併，不是覆蓋。
          // 觀察清單取聯集（雲端的順序在前），其他設定以雲端為準、雲端沒有的保留本機的。
          var mine = other ? {} : localKv(), kv = {}, k;
          for (k in mine) kv[k] = mine[k];
          for (k in r.kv) kv[k] = r.kv[k];
          if (mine["twsix.watchlist"] && r.kv["twsix.watchlist"]) {
            try {
              var a = JSON.parse(r.kv["twsix.watchlist"]) || [], b = JSON.parse(mine["twsix.watchlist"]) || [];
              b.forEach(function (c) { if (a.indexOf(c) < 0) a.push(c); });
              kv["twsix.watchlist"] = JSON.stringify(a);
            } catch (e) {}
          }
          // 觀察清單的子群組（2026-10-05）：同一個 id 的群組代號取聯集（雲端的順序在前），
          // 只有一邊有的群組都留著（雲端的排前面）；目前選的群組以雲端為準。
          if (mine["twsix.wgroups"] && r.kv["twsix.wgroups"]) {
            try {
              var gc = JSON.parse(r.kv["twsix.wgroups"]), gm = JSON.parse(mine["twsix.wgroups"]), byId = {};
              (gc.groups || []).forEach(function (g) { byId[g.id] = g; });
              (gm.groups || []).forEach(function (g) {
                var o = byId[g.id];
                if (!o) { gc.groups.push(g); byId[g.id] = g; return; }
                (g.codes || []).forEach(function (c) { if ((o.codes || (o.codes = [])).indexOf(c) < 0) o.codes.push(c); });
              });
              kv["twsix.wgroups"] = JSON.stringify(gc);
            } catch (e) {}
          } else if (mine["twsix.watchlist"] && r.kv["twsix.wgroups"]) {
            // 這台還是舊版的單一清單：併進雲端的第一個群組〔我的自選〕。
            try {
              var gw = JSON.parse(r.kv["twsix.wgroups"]), first = (gw.groups || [])[0], old = JSON.parse(mine["twsix.watchlist"]) || [];
              if (first) { old.forEach(function (c) { if ((first.codes || (first.codes = [])).indexOf(c) < 0) first.codes.push(c); }); kv["twsix.wgroups"] = JSON.stringify(gw); }
            } catch (e) {}
          }
          replaceLocal(kv);
          var same = JSON.stringify(kv) === JSON.stringify(r.kv);
          setMeta({ uid: user.uid, rev: r.rev || 0, seq: same ? 0 : 1, synced: 0 });
          if (!same) push();                                   // 合併出新東西：傳回雲端
          reloadOnce(r.rev || 0);
          return;
        }
        // 本機有還沒上傳的改動：以本機為準（那是剛剛才做的事），蓋回雲端。
        if (dirty(m) || !r) { push(); return; }
        if ((r.rev || 0) > (m.rev || 0)) { replaceLocal(r.kv); setMeta({ uid: user.uid, rev: r.rev }); reloadOnce(r.rev); }
      }).catch(function (e) { console.warn("[登入] 讀取雲端資料失敗", e); });
    }

    function logout() {
      clearTimeout(timer); timer = null;
      var done = function () { clearLocal(); lrm(K); lrm(M); location.reload(); };
      (window.firebase && firebase.apps.length ? firebase.auth().signOut() : Promise.resolve()).then(done, done);
    }

    function showLogin(msg) {
      lock();
      later(function () {
        var w = card('<p class="tg-sub">請使用授權的 Google 帳號登入</p>' +
          '<button type="button" class="tg-go tg-google"><svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>使用 Google 帳號登入</button>' +
          '<p class="tg-err" role="alert"></p>');
        var b = w.querySelector(".tg-google"), e = w.querySelector(".tg-err");
        if (msg) e.textContent = msg;
        b.addEventListener("click", function () {
          if (!window.firebase || !firebase.apps.length) { e.textContent = "登入元件還在載入，請稍候再按一次"; return; }
          b.disabled = true; e.textContent = "";
          var p = new firebase.auth.GoogleAuthProvider();
          p.setCustomParameters({ prompt: "select_account" });
          firebase.auth().signInWithPopup(p).catch(function (err) {
            b.disabled = false;
            if (err && /popup-blocked|operation-not-supported/.test(err.code || "")) return firebase.auth().signInWithRedirect(p);
            if (err && /popup-closed|cancelled-popup/.test(err.code || "")) return;
            e.textContent = "登入失敗：" + ((err && err.code) || err);
          });
        });
      });
    }

    function adminPanel() {
      var db = firebase.firestore(), doc = db.doc("config/allowlist");
      doc.get().then(function (s) {
        var data = s.exists ? s.data() : { emails: C.defaults, admins: [C.owner] };
        var w = card('<p class="tg-sub">授權名單（一行一個 Gmail）</p>' +
          '<textarea id="tg-list" rows="8" spellcheck="false"></textarea>' +
          '<label for="tg-adm">管理員（一行一個；' + C.owner + ' 固定是管理員）</label>' +
          '<textarea id="tg-adm" rows="3" spellcheck="false"></textarea>' +
          '<div class="tg-btns"><button type="button" class="tg-go tg-save">儲存</button><button type="button" class="tg-ghost">關閉</button></div>' +
          '<p class="tg-err" role="alert"></p>');
        w.classList.add("tg-modal");
        w.querySelector("#tg-list").value = (data.emails || []).join("\n");
        w.querySelector("#tg-adm").value = (data.admins || []).join("\n");
        w.querySelector(".tg-ghost").onclick = function () { w.remove(); };
        w.querySelector(".tg-save").onclick = function () {
          var clean = function (t) {
            var seen = {};
            return t.split(/[\s,;]+/).map(function (x) { return x.trim().toLowerCase(); })
              .filter(function (x) { return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(x) && !seen[x] && (seen[x] = 1); });
          };
          var emails = clean(w.querySelector("#tg-list").value), admins = clean(w.querySelector("#tg-adm").value);
          if (admins.indexOf(C.owner) < 0) admins.unshift(C.owner);
          var e = w.querySelector(".tg-err");
          doc.set({ emails: emails, admins: admins }).then(function () {
            e.style.color = "#5eead4"; e.textContent = "已儲存：" + emails.length + " 位使用者、" + admins.length + " 位管理員";
          }, function (err) { e.style.color = ""; e.textContent = "儲存失敗：" + ((err && err.code) || err); });
        };
      }, function (err) { alert("讀不到名單：" + ((err && err.code) || err)); });
    }

    function allowed(u) {
      var email = (u.email || "").toLowerCase(), doc = firebase.firestore().doc("config/allowlist");
      return doc.get().then(function (s) {
        if (!s.exists) {
          if (email !== C.owner) return null;
          var init = { emails: C.defaults, admins: [C.owner] };     // 第一次：管理員登入時建立名單
          return doc.set(init).then(function () { return init; });
        }
        return s.data();
      }).then(function (list) {
        if (!list) return { ok: false };
        var admins = list.admins || [], emails = list.emails || [];
        return { ok: email === C.owner || emails.indexOf(email) >= 0 || admins.indexOf(email) >= 0,
                 admin: email === C.owner || admins.indexOf(email) >= 0 };
      }, function () { return { ok: false }; });   // 規則拒絕＝不在名單上
    }

    function load(src) {
      return new Promise(function (ok, bad) {
        var s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad;
        (document.head || d).appendChild(s);
      });
    }
    var base = "https://www.gstatic.com/firebasejs/" + C.sdk + "/firebase-";
    load(base + "app-compat.js")
      .then(function () { return Promise.all([load(base + "auth-compat.js"), load(base + "firestore-compat.js")]); })
      .then(function () {
        firebase.initializeApp(C.fb);
        firebase.auth().onAuthStateChanged(function (u) {
          // 沒有登入：只顯示登入卡片，**不動本機的資料**。
          // 2026-10-04 的教訓：這裡原本會在「這台瀏覽器之前登入過」時清掉本機清單，而
          // 「之前登入過」是看 twsix-gate 這個鍵——帳號密碼模式也用同一個鍵存雜湊，於是
          // 從帳號密碼切到 Google 登入的那一刻，還沒登入就先把觀察清單清掉了，也就沒有
          // 東西可以搬上雲端。清掉本機資料只在按「登出」時做（見 logout）。
          if (!u) { if ((lget(K) || "").indexOf("fb:") === 0) lrm(K); showLogin(denied); denied = ""; return; }
          allowed(u).then(function (res) {
            if (!res.ok) {
              lrm(K);
              denied = "這個 Google 帳號（" + u.email + "）不在授權名單上，請洽管理員。";
              showLogin(denied);
              firebase.auth().signOut();
              return;
            }
            user = u; ref = firebase.firestore().doc("users/" + u.uid);
            lset(K, "fb:" + u.email.toLowerCase());
            unlock();
            later(function () {
              icon("tg-out", "登出（" + u.email + "）", OUT_PATH, logout);
              if (res.admin) icon("tg-admin", "授權名單管理", ADMIN_PATH, adminPanel);
            });
            sync();
          });
        });
      })
      .catch(function () {
        if (!lget(K)) showLogin("登入元件載入失敗，請檢查網路後重新整理。");
      });
  }
})();
