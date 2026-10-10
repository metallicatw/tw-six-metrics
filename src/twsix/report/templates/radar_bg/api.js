{% raw %}
// ── BG 13 個工具的資料轉接（2026-09-29）──────────────────────────────────────
// 13 個分頁的版面與程式照 BG財報 的工具頁移植（radar_bg/mods.js，由 port.py 產生）；
// 那些程式原本讀它們自己的 data.json、chunk_*.json……這裡把本站的資料（radar.json、
// stock/<代號>.json、market.json、逐日歷史 hist*、基本面歷史 fund.bin）轉成同樣的形狀，
// 移植過去的程式幾乎不用改。每個分頁第一次打開才載入、才計算。
var CF_MODS = {};
var BG = {cache: {}};
function bgResp(obj){ return {ok: true, status: 200, json: function(){ return Promise.resolve(obj); }}; }
function bgMemo(key, make){ return BG.cache[key] || (BG.cache[key] = make()); }
BG.names = function(){
  return bgMemo("names", function(){ var m = {}; R.rows.forEach(function(r){ m[r.c] = r.n; }); return m; });
};
// ── 連結：代號 → ① 個股籌碼多圖（留在本頁）；名稱 → 個股資訊頁；收盤價旁的圖示 → Yahoo 技術分析。
// 移植的程式用字串拼 HTML，所以這三個也回字串；點下去的動作由 init() 在 #cf 上統一處理
// （捕捉階段就攔下來，不會同時觸發那一列原本的點擊）。
function bgAttr(v){ return String(v).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); }
function bgCode(c){ return '<a class="bg-t1" href="#t1-' + bgAttr(c) + '" title="① 個股籌碼多圖">' + c + '</a>'; }
function bgName(c, n){ return '<a class="bg-lk" href="stock/' + encodeURIComponent(c) + '.html" title="個股資訊頁">' + (n || c) + '</a>'; }
function bgYf(c){ return '<a class="yf bg-lk" href="' + bgAttr(yahooTA(c)) + '" target="_blank" rel="noopener" title="Yahoo股市技術分析" aria-label="' + bgAttr(c) + ' Yahoo 技術分析"></a>'; }
// ①②③ 的標題列（2026-10-10）：代號與名稱連個股資訊頁、名稱後面加產業與☆。
// codeEl／nameEl 是移植程式原本填字的那兩格；額外的東西插在 after（預設 nameEl）後面，
// 重查另一檔時先拿掉上一次插的。
function bgDecorate(code, codeEl, nameEl, after){
  if (!code) return;
  var r = ROWS[code] || {}, href = "stock/" + encodeURIComponent(code) + ".html";
  var name = (nameEl && nameEl.textContent) || r.n || "";
  if (codeEl) codeEl.innerHTML = '<a class="bg-lk" href="' + href + '" title="個股資訊頁">' + bgAttr(code) + '</a>';
  if (nameEl && name) nameEl.innerHTML = '<a class="bg-lk" href="' + href + '" title="個股資訊頁">' + bgAttr(name) + '</a>';
  after = after || nameEl; if (!after || !after.parentNode) return;
  var host = after.parentNode;
  host.querySelectorAll(".bg-deco").forEach(function(x){ x.remove(); });
  var html = (r.ind && after !== nameEl ? "" : (r.ind ? '<span class="bg-ind bg-deco">' + bgAttr(r.ind) + '</span>' : "")) +
    '<button type="button" class="star bg-star bg-deco" data-star="' + bgAttr(code) + '" aria-pressed="false" title="加入觀察清單">☆</button>';
  after.insertAdjacentHTML("afterend", html);
  var star = host.querySelector("button.bg-star");
  if (star && typeof TWSIXWatch !== "undefined") TWSIXWatch.paint(star);
}
BG.ind = function(c){ var r = ROWS[c]; return r && r.ind ? r.ind : "#N/A"; };
// 匯出：移植過去的程式用 window.claude.use("downloads").save({filename, data})
if (!window.claude) window.claude = {use: function(k){
  return Promise.resolve(k === "downloads" ? {save: function(o){
    var text = String(o.data || ""), a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], {type: "text/csv;charset=utf-8"}));
    a.download = o.filename || "download.csv";
    document.body.appendChild(a); a.click();
    setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    return Promise.resolve();
  }} : null);
}};
function bgMissing(path){ return Promise.reject(new Error("沒有這份資料：" + path)); }

// ① 個股籌碼多圖：dates.json 各圖同一組 120 個交易日；個股序列由 stock/<代號>.json 的 d 換算
var T1_KEYS = ["price", "fi_ti_cap60", "fi_amt20", "fi_turnover20", "turn_ex_holder20", "fi_ti_per_holder60", "fi_ti_per_holder60_rank",
  "wide", "val_20d_pct", "val_over_cap20", "val_per_holder20", "val_per_holder20_rank", "greed1", "greed2", "fear1", "fear2", "diff20", "diff60"];
function t1Stock(code){
  return stock(code).then(function(s){
    var d = s && s.d; if (!d) return null;
    return t1Map(d);
  }).catch(function(){ return null; });
}
function t1Map(d){
    var m = function(a, f){ return (a || []).map(function(v){ return v == null ? null : f(v); }); };
    var id = function(v){ return v; };
    return {price: d.cl, fi_ti_cap60: d.z, fi_amt20: m(d.fa20, function(v){ return v * 100; }), val_amt20: m(d.va, function(v){ return v * 100; }),
      fi_turnover20: d.ft, turn_ex_holder20: d.tex, fi_ti_per_holder60: d.fpw, fi_ti_per_holder60_rank: d.wr,
      holder_cnt: d.hc, holder_ratio: d.hp, holder_stock: d.hk, total_holders: d.sh,
      val_20d_pct: d.vs, val_over_cap20: d.vc, val_per_holder20: d.vpw, val_per_holder20_rank: d.xr,
      greed1: m(d.g20, id), greed2: m(d.g60, id), fear1: m(d.g20, function(v){ return 20 - v; }), fear2: m(d.g60, function(v){ return 60 - v; }),
      diff20: m(d.g20, function(v){ return 2 * v - 20; }), diff60: m(d.g60, function(v){ return 2 * v - 60; })};
}

// ── ①② 的長歷史（2026-10-10）：stock/<代號>.L.bin，按需下載 ────────────────────
// 表頭 long.json（日期、欄位、倍率）全站一份；每檔一個 gzip 檔，格式和 hist_*.bin 相同
// （逐日差分＋zigzag＋varint，缺值是 int32 最小值），用同一個 readSeq 解。
var BG_LONG = {head: null, cache: {}};
function bgLong(code){
  if (BG_LONG.cache[code]) return BG_LONG.cache[code];
  var head = BG_LONG.head || (BG_LONG.head = getJSON("long.json"));
  var p = head.then(function(h){
    return getBin("stock/" + code + ".L.bin").then(function(u){
      var n = h.dates.length, A = new Int32Array(n), pos = 0, d = {};
      h.fields.forEach(function(f){
        pos = readSeq(u, pos, A, 0, n);
        var arr = new Array(n), any = false;
        for (var j = 0; j < n; j++){ var v = A[j]; arr[j] = v === SENT ? null : v / f[1]; if (arr[j] !== null) any = true; }
        if (any) d[f[0]] = arr;
      });
      return {dates: h.dates, d: d};
    });
  });
  p.catch(function(){ delete BG_LONG.cache[code]; });
  return (BG_LONG.cache[code] = p);
}
function t1Long(code){ return bgLong(code).then(function(L){ return {dates: L.dates, s: t1Map(L.d)}; }); }
function t2Long(code){ return bgLong(code).then(function(L){ return {dates: L.dates, c: L.d.cl || [], hr: L.d.hp || [], hc: L.d.hc || [], sh: L.d.sh || []}; }); }

// ── 縮放區間＋雙滑桿＋疊加股價（①② 共用，2026-10-10）───────────────────────────
// 和個股頁〔股價健診〕同一種操作：按鈕跳到固定長度、滑桿拉起訖。onChange(a, b, px) 的
// a、b 是陣列索引（含兩端），px 是「疊加股價」有沒有勾。setData(n, dates) 在長歷史載入後
// 換成更長的那一份：目前看的是「最後 k 天」就維持最後 k 天。
function bgRangeUI(host, opt){
  var BTN = opt.buttons || [[63, "近3月"], [120, "近120日"], [250, "近1年"], [0, "全部"]];
  host.innerHTML = '<div class="bg-rng"><span class="lab">縮放區間：</span>' +
    BTN.map(function(b){ return '<button type="button" data-n="' + b[0] + '">' + b[1] + "</button>"; }).join("") +
    (opt.price ? '<label class="px"><input type="checkbox"> 疊加股價</label>' : "") + "</div>" +
    '<div class="bg-rng-sl"><input type="range" min="0" value="0" aria-label="區間起點"><input type="range" min="0" value="0" aria-label="區間終點"></div>' +
    '<p class="bg-rng-note"></p>';
  var r = host.querySelectorAll(".bg-rng-sl input"), r0 = r[0], r1 = r[1], note = host.querySelector(".bg-rng-note");
  var cb = host.querySelector(".px input"), n = 0, dates = [], view = [0, 0], pending = 0, span = opt.span || 120, want = 0;
  function mark(){
    var len = view[1] - view[0] + 1, atEnd = view[1] === n - 1;
    [].forEach.call(host.querySelectorAll("button[data-n]"), function(b){
      var k = +b.getAttribute("data-n");
      var on = want ? (k ? want === k : want === 1e9) : (atEnd && (k ? len === k : view[0] === 0));
      b.classList.toggle("on", on);
      b.disabled = !!k && k > n && !opt.more;
    });
    note.textContent = n ? dates[view[0]] + " ～ " + dates[view[1]] + "（" + len + " 個交易日）" + (opt.more ? "　較早的資料載入中…" : "") : "";
  }
  function fire(){ pending = 0; mark(); opt.onChange(view[0], view[1], cb ? cb.checked : false); }
  function set(a, b, now){
    view = [Math.max(0, Math.min(a, b)), Math.min(n - 1, Math.max(a, b))];
    r0.value = view[0]; r1.value = view[1];
    if (now) fire(); else if (!pending) pending = requestAnimationFrame(fire);
  }
  r0.addEventListener("input", function(){ want = 0; set(+r0.value, +r1.value); });
  r1.addEventListener("input", function(){ want = 0; set(+r0.value, +r1.value); });
  if (cb) cb.addEventListener("change", function(){ fire(); });
  [].forEach.call(host.querySelectorAll("button[data-n]"), function(b){
    b.addEventListener("click", function(){ var k = +b.getAttribute("data-n"); want = k || 1e9; set(k ? n - k : 0, n - 1, true); });
  });
  return {
    setData: function(len, ds, more){
      var keep = want || (n ? Math.max(1, view[1] - view[0] + 1) : span);
      var endNow = !n || view[1] === n - 1;
      n = len; dates = ds; opt.more = !!more;
      r0.max = r1.max = Math.max(0, n - 1);
      if (endNow) set(n - Math.min(keep, n), n - 1, true); else set(view[0], view[1], true);
    },
    price: function(){ return cb ? cb.checked : false; }
  };
}

// 疊加股價時，股價那條線的樣子（灰色虛線、右側另一個刻度）
var BG_PX_COLOR = "rgba(150,156,166,.85)";
function t1Fetch(path){
  if (path === "meta.json") return Promise.resolve(bgResp(BG.names()));
  if (path === "dates.json") return getJSON("market.json").then(function(mk){ var o = {}; T1_KEYS.forEach(function(k){ o[k] = mk.dates; }); return bgResp(o); });
  return bgMissing(path);
}

// ② 大戶籌碼看板：每日（d）＋集保週（h）。週的日期用台積電那一份（全市場每週都有）當共同刻度
function t2Weeks(){ return bgMemo("t2weeks", function(){ return stock("2330").then(function(s){ return (s.h && s.h.w) || []; }).catch(function(){ return []; }); }); }
function t2Entry(code){
  return Promise.all([stock(code), t2Weeks()]).then(function(res){
    var s = res[0], W = res[1], d = s.d || {}, h = s.h || {}, pos = {};
    (h.w || []).forEach(function(w, i){ pos[w] = i; });
    var wk = function(arr, mul){ return W.map(function(w){ var i = pos[w]; var v = i == null || !arr ? null : arr[i]; return v == null ? null : v * (mul || 1); }); };
    var st = {}, pt = {};
    ["1", "5", "10", "15", "20", "30", "40", "50", "100", "200", "400", "800", "1000"].forEach(function(t){
      st[t] = wk((h.lots || {})[t], 1000); pt[t] = wk((h.ppl || {})[t]);
    });
    return {c: d.cl || [], hr: d.hp || [], hc: d.hc || [], sh: d.sh || [], cw: wk(h.tot, 1000), cp: wk(h.cp), shw: wk(h.sh), st: st, pt: pt};
  }).catch(function(){ return null; });
}
function t2Fetch(path){
  if (path === "stockdata/meta.json") return Promise.resolve(bgResp(BG.names()));
  if (path === "stockdata/dates.json") return Promise.all([getJSON("market.json"), t2Weeks()]).then(function(r){ return bgResp({daily: r[0].dates, weekly: r[1]}); });
  return bgMissing(path);
}

// ③ 個股基本面：季（近 20 季）與月（近 24 個月）的序列，新的在前
function t3Rec(code){
  return stock(code).then(function(s){
    var q = s.fq || {}, f = s.fs || {}, m = s.fm || {};
    var ql = (q.q || []).slice();
    (f.q || []).forEach(function(x){ if (ql.indexOf(x) < 0) ql.push(x); });
    ql.sort();
    var QL = ql.slice().reverse();
    var byQ = function(src, labels, arr){ var p = {}; (labels || []).forEach(function(x, i){ p[x] = i; }); return QL.map(function(x){ var i = p[x]; return i == null || !arr ? null : (arr[i] == null ? null : arr[i]); }); };
    var ML = (m.m || []).slice().reverse();
    var rv = function(a){ return (a || []).slice().reverse(); };
    // 營收變動說明：近 24 個月（新→舊），當期與去年同期兩欄
    var notesL = [], notes = {};
    if (m.m && m.m.length){
      var last = m.m[m.m.length - 1], y = +last.slice(0, 4), mo = +last.slice(5, 7);
      for (var i = 0; i < 24; i++){
        var yy = y, mm = mo - i; while (mm <= 0){ mm += 12; yy--; }
        var lb = yy + "-" + (mm < 10 ? "0" : "") + mm;
        notesL.push(lb);
        if (m.notes && m.notes[lb]) notes[String(i)] = m.notes[lb];
      }
    }
    var r = ROWS[code] || {};
    return {QL: QL, ML: {rev: ML, price: ML, notes: notesL}, d: {
      eps_q: byQ(null, q.q, q.eps), eps4_q: byQ(null, q.q, q.eps4), eps4_yoy_q: byQ(null, q.q, q.eps4y),
      opm_q: byQ(null, q.q, q.opm), opinc_q: byQ(null, q.q, q.op), opinc_yoy_q: byQ(null, q.q, q.opy),
      retained_apic_ratio_q: byQ(null, q.q, q.rap), retained_ratio_q: byQ(null, q.q, q.rer), apic_ratio_q: byQ(null, q.q, q.apr), retained_q: byQ(null, q.q, q.retained), apic_q: byQ(null, q.q, q.apic),
      capital_q: byQ(null, q.q, q.capital), roa_q: byQ(null, q.q, q.roa),
      inv_q: byQ(null, f.q, f.inv), inv_turn_q: byQ(null, f.q, f.inv_turn), inv_rev_ratio_q: byQ(null, f.q, f.inv_rev),
      cl_q: byQ(null, f.q, f.cl), cl_rev_ratio_q: byQ(null, f.q, f.cl_rev), cl_capital_ratio_q: byQ(null, f.q, f.cl_cap),
      capex_q: byQ(null, f.q, f.capex), capex_cap_ratio_q: byQ(null, f.q, f.cx_cap),
      rev_m: rv(m.rev), rev_yoy_m: rv(m.yoy), rev_yoy3_m: rv(m.yoy3), rev_yoy12_m: rv(m.yoy12), price_m: rv(m.price),
      notes: notes, price_latest: isnum(r.p) ? r.p : null, price_latest_date: R.asof}};
  }).catch(function(){ return null; });
}
function t3Fetch(path){
  if (path === "meta.json") return Promise.resolve(bgResp(bgMemo("t3meta", function(){ var o = {}; R.rows.forEach(function(r){ o[r.c] = {name: r.n, ind: r.ind || ""}; }); return o; })));
  if (path === "quarter_labels.json") return Promise.resolve(bgResp([]));
  if (path === "month_labels.json") return Promise.resolve(bgResp({rev: [], price: [], notes: []}));
  return bgMissing(path);
}

// ④⑥ 籌碼資料：最近 80 個交易日（新的在前），每檔一組 *_h 陣列
function chipData(){
  return bgMemo("chip", function(){
    return loadHist("b").then(function(){
      var nd = HS.nd, from = HS.from, dates = [], stocks = [];
      for (var d = nd - 1; d >= from; d--) dates.push(HS.dates[d]);
      for (var s = 0; s < HS.nc; s++){
        var o = {c: HS.codes[s], n: (ROWS[HS.codes[s]] || {}).n || HS.codes[s]}, keys = {price_h: "cl", wr_h: "wr", xr_h: "xr", yr_h: "yr", z_h: "z", hr_h: "hr", hp_h: "hp", sh_h: "sh"};
        for (var k in keys){
          var a = new Array(nd - from), f = keys[k], int = f === "wr" || f === "xr" || f === "yr" || f === "hr" || f === "sh";
          for (var j = 0, dd = nd - 1; dd >= from; dd--, j++) a[j] = int ? hvi(f, s, dd) : hv(f, s, dd);
          o[k] = a;
        }
        o.price = o.price_h[0];
        stocks.push(o);
      }
      return {stocks: stocks, dates: dates, backtestDays: Math.min(20, dates.length)};
    });
  });
}
function t4Fetch(path){ return path === "data.json" ? chipData().then(bgResp) : bgMissing(path); }

// ⑤⑥ 基本面：「那一天已經公布」的快照（fund.bin）；欄位名稱對照移植程式用的鍵
var BG_FMAP = {rev_yoy_1m: "r1", rev_yoy_3m: "r3", rev_yoy_12m: "r12", eps4_yoy: "e4y", opinc_yoy: "oy", eps4: "e4", eps_q: "eq",
  opm: "om", npm: "nm", cl_rev_ratio: "cl_rv", cl_cap_ratio: "cl_cap", capex_cap_ratio: "cx_cap", rev4q: "rv4", capital: "cap"};
var BG_FLAGMAP = {eps4_h4: "e4h4", eps4_h8: "e4h8", epsq_h4: "eqh4", epsq_h8: "eqh8", opm_h4: "omh4", opm_h8: "omh8",
  npm_h4: "nmh4", npm_h8: "nmh8", revm_h12: "rh12", revm_h24: "rh24"};
// block：FD.ann（⑤，dayIdx＝第幾次公告，0＝最新）或 FD.days（⑥，dayIdx＝第幾個交易日，0＝最新）
BG.fundAt = function(code, block, dayIdx){
  if (!FD) return null;
  var B = FD[block], s = FD.idx[code]; if (!B || s == null) return null;
  var j = B.nd - 1 - dayIdx; if (j < 0) return null;
  var key = block + ":" + code + ":" + j;
  var c = BG.cache.f || (BG.cache.f = {});
  return c[key] || (c[key] = fundRow(B, s, j));
};
BG.fundVal = function(code, block, dayIdx, key){
  var f = BG.fundAt(code, block, dayIdx); if (!f) return null;
  if (key === "price") return isnum(f.p0) ? f.p0 : null;
  var k = BG_FMAP[key]; if (!k) return null;
  return isnum(f[k]) ? f[k] : null;
};
BG.fundFlag = function(code, block, dayIdx, flag){ var f = BG.fundAt(code, block, dayIdx); return !!(f && f[BG_FLAGMAP[flag]]); };
function t5Fetch(path){
  if (path !== "screener.json") return bgMissing(path);
  return loadFund().then(function(){
    var rows = {};
    FD.codes.forEach(function(c){ rows[c] = {name: (ROWS[c] || {}).n || c, ind: BG.ind(c)}; });
    return bgResp({rows: rows, priceDates: FD.ann.dates.slice().reverse(), quarterLabels: [], monthLabels: []});
  });
}
function t6Fetch(path){
  if (path === "chip_data.json") return Promise.all([chipData(), loadFund()]).then(function(r){ return bgResp(r[0]); });
  if (path === "fund_data.json") return loadFund().then(function(){
    var rows = {};
    FD.codes.forEach(function(c){ rows[c] = {name: (ROWS[c] || {}).n || c, ind: BG.ind(c)}; });
    return bgResp({rows: rows, quarterLabels: [], monthLabels: []});
  });
  return bgMissing(path);
}

// ⑦⑧ 排名軌跡、⑪⑫ 金額軌跡：最近 60 個交易日（舊的在前）
function trailData(kind){
  return bgMemo("trail" + kind, function(){
    return loadHist("b").then(function(){
      var n = Math.min(60, HS.nd - HS.from), d0 = HS.nd - n, dates = HS.dates.slice(d0), stocks = [], maxRank = 0, sumY = new Array(n).fill(0), cntY = new Array(n).fill(0);
      for (var s = 0; s < HS.nc; s++){
        var o = {c: HS.codes[s], n: (ROWS[HS.codes[s]] || {}).n || HS.codes[s], x: [], y: [], xr: [], yr: []}, any = false;
        for (var i = 0; i < n; i++){
          var d = d0 + i, xr = hvi("yr", s, d), yr = hvi("vr", s, d);
          if (xr != null && xr > maxRank) maxRank = xr;
          if (yr != null && yr > maxRank) maxRank = yr;
          o.xr.push(xr); o.yr.push(yr);
          if (kind === "rank"){ o.x.push(xr); o.y.push(yr); if (xr != null) any = true; }
          else {
            var fa = hv("fa", s, d), va = hv("va", s, d);
            o.x.push(fa); o.y.push(va);
            if (va != null){ sumY[i] += va; cntY[i]++; any = true; }
          }
        }
        if (any) stocks.push(o);
      }
      var out = {dates: dates, stocks: stocks, maxRank: maxRank};
      if (kind !== "rank") out.avgY = sumY.map(function(v, i){ return cntY[i] ? v / cntY[i] : null; });
      return out;
    });
  });
}
function t7Fetch(path){ return path === "data.json" ? trailData("rank").then(bgResp) : bgMissing(path); }
function t11Fetch(path){ return path === "data.json" ? trailData("value").then(bgResp) : bgMissing(path); }

// ⑨⑩ 排名榜：最近 60 個交易日（新的在前），每一天依名次排好的名稱清單
function gridData(){
  return bgMemo("grid", function(){
    return loadHist("b").then(function(){
      var n = Math.min(60, HS.nd - HS.from), codes = {}, out = {codes: codes};
      for (var s = 0; s < HS.nc; s++) codes[HS.codes[s]] = (ROWS[HS.codes[s]] || {}).n || HS.codes[s];
      [["turnover", "vr"], ["inst", "yr"]].forEach(function(p){
        var dates = [], grid = [];
        for (var d = HS.nd - 1; d >= HS.nd - n; d--){
          dates.push(HS.dates[d]);
          // 依名次排好（同名次的依代號），一格一檔——名次相同時不會互相蓋掉
          var pairs = [];
          for (var s2 = 0; s2 < HS.nc; s2++){ var r = hvi(p[1], s2, d); if (r != null) pairs.push([r, HS.codes[s2]]); }
          pairs.sort(function(a, b){ return a[0] - b[0] || (a[1] < b[1] ? -1 : 1); });
          grid.push(pairs.map(function(x){ return codes[x[1]]; }));
        }
        out[p[0]] = {dates: dates, grid: grid};
      });
      return out;
    });
  });
}
function t9Fetch(path){ return path === "data.json" ? gridData().then(bgResp) : bgMissing(path); }

// ⑬ 籌碼回測檢視表：50 個篩選日（新的在前）× 往前比 60 日；股價 120 個交易日（新的在前）
function t13Fetch(path){
  if (path !== "data.json") return bgMissing(path);
  return loadHist("ab").then(function(){
    var days = 50, lookback = 60, N = HS.nd, top = N - 1 - 59, stocks = [];
    var filterDates = [], priceDates = [];
    for (var k = 0; k < days; k++) filterDates.push(HS.dates[top - k]);
    for (var i = 0; i < 120 && N - 1 - i >= 0; i++) priceDates.push(HS.dates[N - 1 - i]);
    for (var s = 0; s < HS.nc; s++){
      var o = {c: HS.codes[s], n: (ROWS[HS.codes[s]] || {}).n || HS.codes[s], p: [], w: [], x: [], y: [], hp: [], sh: [], z: [], hc: [], hr: []};
      for (var j = 0; j < priceDates.length; j++) o.p.push(hv("cl", s, N - 1 - j));
      for (var kk = 0; kk < days + lookback; kk++){
        var d = top - kk;
        if (d < 0){ ["w", "x", "y", "hp", "sh", "z", "hc", "hr"].forEach(function(f){ o[f].push(null); }); continue; }
        o.w.push(hvi("wr", s, d)); o.x.push(hvi("xr", s, d)); o.y.push(hvi("yr", s, d)); o.hp.push(hv("hp", s, d));
        o.sh.push(hvi("sh", s, d)); o.z.push(hv("z", s, d)); o.hc.push(hvi("hc", s, d)); o.hr.push(hvi("hr", s, d));
      }
      stocks.push(o);
    }
    return bgResp({days: days, lookback: lookback, filterDates: filterDates, priceDates: priceDates, latest: HS.dates[N - 1],
      generated: R.generated_at || "", stocks: stocks});
  });
}

var BG_API = {
  t1: {fetch: t1Fetch, stock: t1Stock, long: t1Long}, t2: {fetch: t2Fetch, entry: t2Entry, long: t2Long}, t3: {fetch: t3Fetch, rec: t3Rec},
  t4: {fetch: t4Fetch}, t5: {fetch: t5Fetch}, t6: {fetch: t6Fetch}, t7: {fetch: t7Fetch}, t8: {fetch: t7Fetch},
  t9: {fetch: t9Fetch}, t10: {fetch: t9Fetch}, t11: {fetch: t11Fetch}, t12: {fetch: t11Fetch}, t13: {fetch: t13Fetch}
};
var BG_BOOTED = {};
// ① 要 Chart.js：先讀本站附帶的一份（chipflow/chart.umd.min.js），讀不到才用 cdnjs
function bgChartJs(){
  if (window.Chart) return Promise.resolve();
  return bgMemo("chartjs", function(){
    var load = function(src){ return new Promise(function(ok, bad){ var s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad; document.head.appendChild(s); }); };
    return load(window.CF_URL ? window.CF_URL("chart.umd.min.js") : "chipflow/chart.umd.min.js")
      .catch(function(){ return load("https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js"); });
  });
}
function bgBoot(tab){
  if (BG_BOOTED[tab] || !CF_MODS[tab]) return;
  BG_BOOTED[tab] = true;
  var root = document.querySelector("#cf-" + tab + " .bgm");
  var api = Object.assign({fundAt: BG.fundAt, fundVal: BG.fundVal, fundFlag: BG.fundFlag}, BG_API[tab]);
  var go = function(){ try { CF_MODS[tab](root, api); } catch (e) { console.error(e); root.insertAdjacentHTML("afterbegin", '<p class="bg-err">這個分頁載入失敗：' + String(e && e.message || e).replace(/[<>&]/g, "") + "</p>"); } };
  if (tab === "t1") bgChartJs().then(go, function(){ root.insertAdjacentHTML("afterbegin", '<p class="bg-err">圖表程式庫（Chart.js）載入失敗，請重新整理頁面。</p>'); });
  else go();
}
{% endraw %}
