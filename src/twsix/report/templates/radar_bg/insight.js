{% raw %}
var CFI = (function(){
  "use strict";
  var FS_KEY = "twsix.cf.insfs", HOVER_KEY = "twsix.cf.inshover", OPEN_KEY = "twsix.cf.inscard";
  var FS_MIN = 13, FS_MAX = 20, FS_DEF = 15;
  var DAYS = 120;

  function nn(v){ return typeof v === "number" && isFinite(v); }
  function esc(t){ return String(t == null ? "" : t).replace(/[&<>"]/g, function(c){ return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  function sum(a){ var t = 0; for (var i = 0; i < a.length; i++) t += a[i]; return t; }
  function avg(a){ return a.length ? sum(a) / a.length : null; }
  function clean(a){ return (a || []).filter(nn); }
  function fx(v, d){ return Number(v).toFixed(d); }
  function grp(v, d){ return Number(v).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d}); }
  function sgn(v, d, suf){ return (v > 0 ? "+" : v < 0 ? "−" : "") + grp(Math.abs(v), d) + (suf || ""); }
  function tone(v){ return v > 0 ? "up" : v < 0 ? "dn" : "eq"; }
  function chip(v, d, suf){ return '<b class="cfi-' + tone(v) + '">' + sgn(v, d, suf) + "</b>"; }
  function yi(m){ var y = m / 100; return y.toLocaleString("en-US", {maximumFractionDigits: Math.abs(y) >= 100 ? 0 : 1}); }
  function people(v){ return Math.round(v).toLocaleString("en-US"); }
  function pct(a, b){ return nn(a) && nn(b) && b > 0 ? (a - b) / b * 100 : null; }
  function mlab(s){ return String(s).replace("-", "/"); }
  function rev(a){ return (a || []).slice().reverse(); }

  function pos(lo, hi, v){
    var p = hi === lo ? 0.5 : (v - lo) / (hi - lo);
    return p >= 0.8 ? {t: "接近半年高點", k: "hi"} : p <= 0.2 ? {t: "接近半年低點", k: "lo"} : {t: "位於半年區間中段", k: "mid"};
  }
  function rankMove(a, b){
    if (!nn(a) || !nn(b)) return "";
    var d = a - b;
    return "第 " + people(a) + " 名 → 第 <b>" + people(b) + "</b> 名" + (d > 0 ? '（<span class="cfi-up">前進 ' + people(d) + " 名</span>）" : d < 0 ? '（<span class="cfi-dn">後退 ' + people(-d) + " 名</span>）" : "（持平）");
  }

  function spark(vals, o){
    o = o || {};
    var v = vals.map(function(x){ return nn(x) ? x : null; }), w = o.w || 132, h = o.h || 30, n = v.length;
    var ok = clean(v);
    if (ok.length < 2) return "";
    var lo = Math.min.apply(null, ok), hi = Math.max.apply(null, ok);
    if (o.bar){ lo = Math.min(0, lo); hi = Math.max(0, hi); }
    if (hi === lo){ hi += 1; lo -= 1; }
    var y = function(t){ return 2 + (1 - (t - lo) / (hi - lo)) * (h - 4); };
    var s = '<svg class="cfi-sp" viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" aria-hidden="true" focusable="false">';
    if (o.bar){
      var bw = w / n, z = y(0);
      v.forEach(function(t, i){
        if (t === null) return;
        var top = Math.min(y(t), z), ht = Math.max(1, Math.abs(y(t) - z));
        s += '<rect x="' + (i * bw + bw * 0.15).toFixed(1) + '" y="' + top.toFixed(1) + '" width="' + (bw * 0.7).toFixed(1) + '" height="' + ht.toFixed(1) + '" class="' + (i === n - 1 ? "last" : t < 0 ? "neg" : "") + '"/>';
      });
      if (lo < 0) s += '<line x1="0" x2="' + w + '" y1="' + z.toFixed(1) + '" y2="' + z.toFixed(1) + '" class="zero"/>';
    } else {
      var d = "", pen = false, last = null;
      v.forEach(function(t, i){
        if (t === null){ pen = false; return; }
        var X = (n === 1 ? w / 2 : i / (n - 1) * (w - 4) + 2), Y = y(t);
        d += (pen ? "L" : "M") + X.toFixed(1) + " " + Y.toFixed(1);
        pen = true; last = [X, Y];
      });
      if (o.zero && lo < 0 && hi > 0) s += '<line x1="0" x2="' + w + '" y1="' + y(0).toFixed(1) + '" y2="' + y(0).toFixed(1) + '" class="zero"/>';
      s += '<path d="' + d + '"/>';
      if (last) s += '<circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '" r="2.4"/>';
    }
    return s + "</svg>";
  }

  function lastIdx(a){ for (var i = a.length - 1; i >= 0; i--) if (nn(a[i])) return i; return -1; }
  function firstIdx(a){ for (var i = 0; i < a.length; i++) if (nn(a[i])) return i; return -1; }

  function model(s, dates){
    var fq = s.fq || {}, fs = s.fs || {}, fm = s.fm || {}, d = s.d || {};
    var ql = rev(fq.q), pq = {};
    (fs.q || []).forEach(function(q, i){ pq[q] = i; });
    var onQ = function(arr){ return ql.map(function(q){ var i = pq[q]; return i == null || !arr ? null : (nn(arr[i]) ? arr[i] : null); }); };
    var F = {ml: rev(fm.m), rm: rev(fm.rev), ry: rev(fm.yoy), ql: ql, eq: rev(fq.eps), e4: rev(fq.eps4),
      op: rev(fq.opm), oi: rev(fq.op), oy: rev(fq.opy), cx: onQ(fs.capex), cl: onQ(fs.cl), sheetQ: (fs.q || []).length};
    var n = 0;
    for (var k in d) n = Math.max(n, d[k].length);
    var cut = function(a){ a = a || []; return a.slice(Math.max(0, a.length - DAYS)); };
    var C = {};
    ["cl", "hp", "hc", "sh", "z", "wr", "vs", "vc", "xr", "g20", "g60"].forEach(function(k){ C[k] = cut(d[k]); });
    var dl = (dates || []).slice(Math.max(0, (dates || []).length - Math.min(n, DAYS)));
    C.dates = dl;
    C.diff = C.g60.map(function(v){ return nn(v) ? 2 * v - 60 : null; });
    return {fund: F, chip: C};
  }

  function hiFlag(vals, lbls, what, fmt, n, unit){
    var w = vals.slice(0, n);
    if (w.length < n || !w.every(nn)) return null;
    var mx = Math.max.apply(null, w);
    if (w[0] >= mx) return {flag: what + "創近 " + n + " " + unit + "新高", text: '<span class="cfi-flag">' + what + "創近 " + n + " " + unit + "新高</span>"};
    var w4 = w.slice(0, 4);
    if (w[0] >= Math.max.apply(null, w4)) return {flag: what + "創近 4 " + unit + "新高", text: '<span class="cfi-flag">' + what + "創近 4 " + unit + "新高</span>，近 " + n + " " + unit + "高點是 " + fmt(mx) + "（" + lbls[w.indexOf(mx)] + "）"};
    return null;
  }
  function ttm(a, k){ var t = 0; for (var i = k; i < k + 4; i++){ if (!nn(a[i])) return null; t += a[i]; } return t; }

  function secRevenue(F, out){
    var rm = F.rm, ry = F.ry, ml = F.ml.map(mlab);
    if (!nn(rm[0])) return null;
    var L = [], head = '<b class="cfi-big">' + yi(rm[0]) + "</b> 億元" + (nn(ry[0]) ? "　年增 " + chip(ry[0], 1, "%") : "");
    var prev = [];
    for (var i = 1; i <= 3; i++) if (nn(ry[i])) prev.push(ml[i] + " " + sgn(ry[i], 1, "%"));
    if (prev.length) L.push("前三個月年增率：" + prev.join("、"));
    var run = 0; while (run < ry.length && nn(ry[run]) && ry[run] > 0) run++;
    if (run >= 2){ L.push("單月年增率連續 <b>" + run + "</b> 個月為正"); out.flags.push({t: "營收連 " + run + " 月年增", k: "up"}); }
    else if (nn(ry[0]) && ry[0] <= 0){
      var neg = 0; while (neg < ry.length && nn(ry[neg]) && ry[neg] <= 0) neg++;
      if (neg >= 2){ L.push("單月年增率連續 <b>" + neg + "</b> 個月為負"); out.flags.push({t: "營收連 " + neg + " 月年減", k: "dn"}); }
    }
    var w12 = rm.slice(0, 12), w24 = rm.slice(0, 24);
    var ok12 = w12.length === 12 && w12.every(nn), ok24 = w24.length === 24 && w24.every(nn);
    var m12 = ok12 ? Math.max.apply(null, w12) : null, m24 = ok24 ? Math.max.apply(null, w24) : null;
    if (ok24 && rm[0] >= m24){ L.push('<span class="cfi-flag">單月營收創近 24 個月新高</span>'); out.flags.push({t: "營收創 24 個月新高", k: "up"}); }
    else if (ok12 && rm[0] >= m12){
      L.push('<span class="cfi-flag">單月營收創近 12 個月新高</span>' + (ok24 ? "，近 24 個月高點是 " + yi(m24) + " 億元（" + ml[w24.indexOf(m24)] + "）" : ""));
      out.flags.push({t: "營收創 12 個月新高", k: "up"});
    } else if (ok12){
      var rank = 1; for (var j = 1; j < 12; j++) if (w12[j] > rm[0]) rank++;
      L.push("本月是近 12 個月第 <b>" + rank + "</b> 高，近 12 個月高點 " + yi(m12) + " 億元（" + ml[w12.indexOf(m12)] + "）");
    }
    if (ok12){
      var yv = ry.slice(0, 12), ok = clean(yv), pos_ = ok.filter(function(v){ return v > 0; }).length;
      var t = "近 12 個月（" + ml[11] + "～" + ml[0] + "）有 <b>" + pos_ + "</b>／" + ok.length + " 個月年增為正";
      if (ok.length){
        var iMax = yv.indexOf(Math.max.apply(null, ok)), iMin = yv.indexOf(Math.min.apply(null, ok));
        t += "；年增率最高 " + sgn(yv[iMax], 1, "%") + "（" + ml[iMax] + "）、最低 " + sgn(yv[iMin], 1, "%") + "（" + ml[iMin] + "）";
      }
      L.push(t);
      var p12 = rm.slice(12, 24);
      if (p12.length === 12 && p12.every(nn) && sum(p12) > 0) L.push("近 12 個月營收合計 " + yi(sum(w12)) + " 億元，較前 12 個月 " + chip(pct(sum(w12), sum(p12)), 1, "%"));
      var h2 = sum(rm.slice(6, 12));
      if (h2 > 0) L.push("近 6 個月月均營收較前 6 個月 " + chip(pct(sum(rm.slice(0, 6)), h2), 1, "%"));
    }
    var tb = "";
    if (ok12){
      var mx = Math.max.apply(null, w12) || 1;
      tb = '<table class="cfi-tbl"><thead><tr><th>月份</th><th>單月營收（億）</th><th>年增率</th></tr></thead><tbody>';
      for (var m = 0; m < 12; m++){
        tb += "<tr><td>" + ml[m] + '</td><td class="n"><span class="cfi-bar" style="--w:' + Math.max(3, rm[m] / mx * 100).toFixed(0) + '%"></span>' + yi(rm[m]) + '</td><td class="n">' + (nn(ry[m]) ? chip(ry[m], 1, "%") : "–") + "</td></tr>";
      }
      tb += "</tbody></table>";
    }
    return {k: "月營收", sub: ml[0], head: head, spark: spark(rev(rm.slice(0, 24)), {bar: true}), lines: L, table: tb, tlabel: "看近 12 個月逐月數字"};
  }

  function secEps(F, out){
    var eq = F.eq, e4 = F.e4, ql = F.ql;
    if (!nn(eq[0])) return null;
    var L = [], head = '<b class="cfi-big">' + fx(eq[0], 2) + "</b> 元";
    if (nn(eq[4])){
      if (eq[4] > 0) head += "　較去年同季 " + chip((eq[0] - eq[4]) / eq[4] * 100, 0, "%");
      else head += "　去年同季 " + fx(eq[4], 2) + " 元（" + (eq[0] > 0 ? "由虧轉盈" : "仍為虧損") + "）";
    }
    if (nn(e4[0])){
      var t = "近四季累計 EPS <b>" + fx(e4[0], 2) + "</b> 元";
      if (nn(e4[4]) && e4[4] > 0) t += "，較一年前（" + fx(e4[4], 2) + " 元）" + chip((e4[0] - e4[4]) / e4[4] * 100, 1, "%");
      L.push(t);
      var h = hiFlag(e4, ql, "近四季累計 EPS ", function(v){ return fx(v, 2) + " 元"; }, 8, "季");
      if (h){ L.push(h.text); out.flags.push({t: h.flag.replace("近四季累計 EPS ", "累計 EPS "), k: "up"}); }
    }
    var yy = [];
    for (var q = 0; q < 4; q++){ var yq = pct(e4[q], e4[q + 4]); if (yq !== null) yy.push(ql[q] + " " + sgn(yq, 1, "%")); }
    if (yy.length){
      var y0 = pct(e4[0], e4[4]), y3 = pct(e4[3], e4[7]);
      L.push("累計 EPS 年增率逐季（新→舊）：" + yy.join("、") + (y0 !== null && y3 !== null ? (y0 - y3 > 3 ? "；比三季前高" : y0 - y3 < -3 ? "；比三季前低" : "；與三季前相近") : ""));
    }
    var run = 0; while (run < 8 && nn(eq[run]) && nn(eq[run + 4]) && eq[run] > eq[run + 4]) run++;
    if (run >= 2){ L.push("單季 EPS 連續 <b>" + run + "</b> 季高於去年同季"); out.flags.push({t: "EPS 連 " + run + " 季年增", k: "up"}); }
    return {k: "EPS", sub: ql[0], head: head, spark: spark(rev(eq.slice(0, 8)), {bar: true}), lines: L, note: "圖：近 8 季單季 EPS"};
  }

  function secOpm(F, out){
    var op = F.op, oi = F.oi, oy = F.oy, ql = F.ql;
    if (!nn(op[0]) && !nn(oi[0])) return null;
    var L = [], head = "";
    if (nn(op[0])){
      head = '<b class="cfi-big">' + fx(op[0], 1) + "%</b>";
      var parts = [];
      if (nn(op[1])) parts.push("較上一季 " + chip(op[0] - op[1], 1, " 個百分點"));
      if (nn(op[4])) parts.push("較去年同季 " + chip(op[0] - op[4], 1, " 個百分點"));
      if (parts.length) L.push(parts.join("，"));
      var a = clean(op.slice(0, 4)), b = clean(op.slice(4, 8));
      if (a.length === 4 && b.length === 4){
        var dd = avg(a) - avg(b);
        L.push("近四季平均 " + fx(avg(a), 1) + "%，前四季平均 " + fx(avg(b), 1) + "%（" + (dd > 0.3 ? "高於前四季" : dd < -0.3 ? "低於前四季" : "大致持平") + "）");
      }
      var h = hiFlag(op, ql, "營業利益率", function(v){ return fx(v, 1) + "%"; }, 8, "季");
      if (h){ L.push(h.text); out.flags.push({t: h.flag.replace("營業利益率", "營益率"), k: "up"}); }
    }
    if (nn(oi[0])){
      var y0 = nn(oy[0]) ? oy[0] : pct(oi[0], oi[4]);
      L.push("營業利益 <b>" + yi(oi[0]) + "</b> 億元" + (nn(y0) ? "，年增 " + chip(y0, 1, "%") : ""));
      var ys = [];
      for (var q = 1; q < 4; q++){ var yq = nn(oy[q]) ? oy[q] : pct(oi[q], oi[q + 4]); if (nn(yq)) ys.push(ql[q] + " " + sgn(yq, 1, "%")); }
      if (ys.length) L.push("前三季營業利益年增率：" + ys.join("、"));
      var c4 = oi.slice(0, 4), p4 = oi.slice(4, 8);
      if (c4.length === 4 && p4.length === 4 && c4.every(nn) && p4.every(nn) && sum(p4) > 0){
        L.push("近四季營業利益合計 " + yi(sum(c4)) + " 億元，較前四季 " + chip(pct(sum(c4), sum(p4)), 1, "%"));
        var rs = [], rl = [];
        for (var k = 0; k < 8; k++){ var r = ttm(oi, k); if (r === null) break; rs.push(r); rl.push(ql[k]); }
        var h2 = hiFlag(rs, rl, "近四季營業利益合計", function(v){ return yi(v) + " 億元"; }, 8, "季");
        if (h2) L.push(h2.text);
      }
    }
    return {k: "營業利益率與營業利益", sub: ql[0], head: head || '<b class="cfi-big">' + yi(oi[0]) + "</b> 億元", spark: spark(rev(op.slice(0, 8))), lines: L, note: "圖：近 8 季營業利益率"};
  }

  function secSheet(F){
    var cx = F.cx, cl = F.cl, ql = F.ql, rows = [];
    for (var i = 0; i < 5; i++){
      var st = i * 4;
      if (!ql[st + 3]) continue;
      var w = cx.slice(st, st + 4);
      rows.push({label: i === 0 ? "近四季" : i === 1 ? "前四季" : "前第 " + i + " 個四季", span: ql[st + 3] + "～" + ql[st],
        cx: w.length === 4 && w.every(nn) ? sum(w) : null, cl: nn(cl[st]) ? cl[st] : null});
    }
    while (rows.length && rows[rows.length - 1].cx === null && rows[rows.length - 1].cl === null) rows.pop();
    if (!rows.length) return {k: "資本支出與合約負債", sub: "", head: '<span class="cfi-soft">尚無個股季報資料</span>', lines: ["本站的個股季報（存貨、合約負債、資本支出）從開始存檔的季別起逐季累積，最多保留 20 季。"]};
    var L = [], first = rows[0], second = rows[1];
    var head = first.cx !== null ? '<b class="cfi-big">' + yi(first.cx) + "</b> 億元<span class=\"cfi-soft\">（近四季資本支出）</span>" : '<span class="cfi-soft">資本支出資料不足四季</span>';
    if (first.cx !== null && second && second.cx !== null) L.push("近四季資本支出較前四季 " + chip(pct(first.cx, second.cx), 0, "%"));
    var last = rows[rows.length - 1];
    if (rows.length >= 3 && last.cx) L.push("約為 " + last.label + "（" + last.span + "）的 " + fx(first.cx / last.cx, 1) + " 倍");
    var cls = rows.map(function(x){ return x.cl; }), okCl = clean(cls), anyCl = okCl.some(function(v){ return v; });
    if (!okCl.length) L.push("合約負債：資料未取得");
    else if (!anyCl) L.push("合約負債：取得的期別都是 0（來源資料無法分辨實際為零或公司未揭露此科目）");
    else if (first.cl !== null){
      var t = "合約負債最新期末餘額 <b>" + yi(first.cl) + "</b> 億元";
      if (second && second.cl !== null && second.cl > 0) t += "，較一年前 " + chip(pct(first.cl, second.cl), 0, "%");
      if (okCl.length >= 3 && first.cl >= Math.max.apply(null, okCl)) t += '，<span class="cfi-flag">為取得期別中最高</span>';
      L.push(t);
    }
    if (F.sheetQ < 20) L.push('<span class="cfi-soft">本站個股季報目前累積 ' + F.sheetQ + " 季（逐季增加，最多 20 季），較早的期別以「–」表示。</span>");
    var mxC = Math.max.apply(null, rows.map(function(x){ return x.cx || 0; })) || 1, mxL = Math.max.apply(null, rows.map(function(x){ return x.cl || 0; })) || 1;
    var tb = '<table class="cfi-tbl"><thead><tr><th>期間</th><th>資本支出<br>（四季合計，億）</th><th>合約負債<br>（期末，億）</th></tr></thead><tbody>';
    rows.forEach(function(x){
      tb += "<tr><td>" + x.label + '<br><span class="cfi-soft">' + x.span + "</span></td>" +
        '<td class="n">' + (x.cx === null ? "–" : '<span class="cfi-bar" style="--w:' + Math.max(3, x.cx / mxC * 100).toFixed(0) + '%"></span>' + yi(x.cx)) + "</td>" +
        '<td class="n">' + (x.cl === null ? "–" : '<span class="cfi-bar b" style="--w:' + Math.max(3, x.cl / mxL * 100).toFixed(0) + '%"></span>' + yi(x.cl)) + "</td></tr>";
    });
    tb += "</tbody></table>";
    return {k: "資本支出與合約負債", sub: "四季為一期", head: head, lines: L, table: tb, tlabel: "看各期數字", openTable: true};
  }

  function span(C){ var d = C.dates; return d.length ? mlab(d[0].slice(5)) + "～" + mlab(d[d.length - 1].slice(5)) : ""; }

  function secWhale(C, out){
    var a = C.hp, i0 = firstIdx(a), i1 = lastIdx(a);
    if (i1 < 0 || i0 === i1) return null;
    var ok = clean(a), lo = Math.min.apply(null, ok), hi = Math.max.apply(null, ok), d = a[i1] - a[i0], p = pos(lo, hi, a[i1]);
    var L = ["由 " + fx(a[i0], 2) + "% " + (Math.abs(d) < 0.3 ? "大致持平於" : d > 0 ? "升到" : "降到") + " <b>" + fx(a[i1], 2) + "%</b>",
      p.t + "（半年高 " + fx(hi, 2) + "%／低 " + fx(lo, 2) + "%）"];
    if (p.k === "hi") out.flags.push({t: "大戶比例近半年高點", k: "up"});
    if (p.k === "lo") out.flags.push({t: "大戶比例近半年低點", k: "dn"});
    var h = C.hc, h0 = firstIdx(h), h1 = lastIdx(h);
    if (h1 > h0 && h0 >= 0) L.push("大戶人數 " + people(h[h0]) + " 人 → <b>" + people(h[h1]) + "</b> 人（" + chip(h[h1] - h[h0], 0, " 人") + "）");
    return {k: "大戶比例", sub: span(C), head: '<b class="cfi-big">' + fx(a[i1], 2) + "%</b>　" + chip(d, 2, " 個百分點"), spark: spark(a), lines: L};
  }

  function secHolders(C, out){
    var a = C.sh, i0 = firstIdx(a), i1 = lastIdx(a);
    if (i1 < 0 || i0 === i1) return null;
    var ok = clean(a), g = pct(a[i1], a[i0]), p = pos(Math.min.apply(null, ok), Math.max.apply(null, ok), a[i1]);
    var L = [people(a[i0]) + " 人 → <b>" + people(a[i1]) + "</b> 人，" + p.t];
    if (g !== null && Math.abs(g) >= 5) out.flags.push({t: "總股東人數半年" + (g < 0 ? "減少 " : "增加 ") + fx(Math.abs(g), 0) + "%", k: "eq"});
    if (g !== null && Math.abs(g) > 50) L.push('<span class="cfi-soft">變動幅度很大，可能受增資、減資、面額變更或合併等事件影響，請自行查證。</span>');
    return {k: "總股東人數", sub: span(C), head: '<b class="cfi-big">' + people(a[i1]) + "</b> 人" + (g !== null ? "　" + chip(g, 1, "%") : ""), spark: spark(a), lines: L};
  }

  function secInst(C, out){
    var a = C.z, i1 = lastIdx(a);
    if (i1 < 0) return null;
    var ok = clean(a), lo = Math.min.apply(null, ok), hi = Math.max.apply(null, ok), v = a[i1], p = pos(lo, hi, v);
    var L = ["近 60 日合計為" + (v > 0 ? "<b>買超</b>" : v < 0 ? "<b>賣超</b>" : "持平") + "；半年區間 " + sgn(lo, 2, "%") + " ～ " + sgn(hi, 2, "%") + "，" + p.t];
    out.flags.push({t: "外資投信 60 日" + (v > 0 ? "買超" : v < 0 ? "賣超" : "持平"), k: tone(v)});
    if (i1 >= 20 && nn(a[i1 - 20])){
      var c = v - a[i1 - 20];
      L.push("近 20 個交易日變化 " + chip(c, 2, " 個百分點") + "（" + (c > 0.05 ? "上升" : c < -0.05 ? "下降" : "變動不大") + "）");
    }
    var r = C.wr, r0 = firstIdx(r), r1 = lastIdx(r);
    if (r1 > r0 && r0 >= 0) L.push("外資投信買賣超 ÷ 大戶人數排名：" + rankMove(r[r0], r[r1]));
    return {k: "外資＋投信買賣超 ÷ 資本額（60 日累計）", sub: span(C), head: '<b class="cfi-big cfi-' + tone(v) + '">' + sgn(v, 2, "%") + "</b>", spark: spark(a, {zero: true}), lines: L};
  }

  function secFlow(C){
    var a = C.vs, i1 = lastIdx(a);
    if (i1 < 0) return null;
    var ok = clean(a), lo = Math.min.apply(null, ok), hi = Math.max.apply(null, ok), mean = avg(ok), p = pos(lo, hi, a[i1]);
    var L = ["半年平均 " + fx(mean, 2) + "%，" + p.t + "（半年高 " + fx(hi, 2) + "%／低 " + fx(lo, 2) + "%）"];
    var b = C.vc, j = lastIdx(b);
    if (j >= 0){
      var bm = avg(clean(b)), ratio = bm ? b[j] / bm : null;
      L.push("成交金額 ÷ 資本額（20 日累計）" + fx(b[j], 2) + " 倍" + (ratio !== null ? "，" + (ratio >= 1.2 ? "高於" : ratio <= 0.8 ? "低於" : "接近") + "半年平均（" + fx(bm, 2) + " 倍）" : ""));
    }
    var r = C.xr, r0 = firstIdx(r), r1 = lastIdx(r);
    if (r1 > r0 && r0 >= 0) L.push("成交金額 ÷ 大戶人數排名：" + rankMove(r[r0], r[r1]));
    return {k: "成交金額占全市場（20 日累計）", sub: span(C), head: '<b class="cfi-big">' + fx(a[i1], 2) + "%</b>", spark: spark(a), lines: L};
  }

  function secPower(C, out){
    var g = C.g60, j = lastIdx(g);
    if (j < 0) return null;
    var g2 = g[j], f2 = 60 - g2, df = 2 * g2 - 60, ok = clean(C.diff), mean = avg(ok);
    var posPct = ok.length ? ok.filter(function(v){ return v > 0; }).length / ok.length * 100 : null;
    var L = ["買盤比例合計 <b>" + fx(g2, 1) + "</b>、賣盤比例合計 <b>" + fx(f2, 1) + "</b>（" + (Math.abs(df) < 1 ? "兩者接近" : df > 0 ? "買盤較多" : "賣盤較多") + "）"];
    if (mean !== null) L.push("半年內差值平均 " + sgn(mean, 2) + "，" + fx(posPct, 0) + "% 的交易日為正");
    var k = lastIdx(C.g20);
    if (k >= 0) L.push("近 20 日買盤減賣盤 " + chip(2 * C.g20[k] - 20, 2));
    if (Math.abs(df) >= 1) out.flags.push({t: "60 日" + (df > 0 ? "買盤" : "賣盤") + "比例較高", k: df > 0 ? "up" : "dn"});
    return {k: "買盤比例 − 賣盤比例（60 日）", sub: span(C), head: chip(df, 2), spark: spark(C.diff, {zero: true}), lines: L};
  }

  function build(s, dates){
    var M = model(s, dates), out = {flags: []};
    var fund = [secRevenue(M.fund, out), secEps(M.fund, out), secOpm(M.fund, out), secSheet(M.fund)].filter(Boolean);
    var chipS = [secWhale(M.chip, out), secHolders(M.chip, out), secInst(M.chip, out), secFlow(M.chip), secPower(M.chip, out)].filter(Boolean);
    return {fund: fund, chip: chipS, flags: out.flags, M: M};
  }

  function secHtml(x, wide){
    var h = '<section class="cfi-sec"><header><h5>' + esc(x.k) + "</h5>" + (x.sub ? '<span class="cfi-when">' + esc(x.sub) + "</span>" : "") + "</header>" +
      '<div class="cfi-head"><div class="cfi-val">' + x.head + "</div>" + (x.spark ? '<div class="cfi-spk" title="' + esc(x.note || "") + '">' + x.spark + "</div>" : "") + "</div>";
    if (x.lines && x.lines.length) h += "<ul>" + x.lines.map(function(l){ return "<li>" + l + "</li>"; }).join("") + "</ul>";
    if (x.table) h += (wide || x.openTable ? '<details class="cfi-more" open>' : '<details class="cfi-more">') + "<summary>" + esc(x.tlabel || "看數字") + "</summary>" + x.table + "</details>";
    return h + "</section>";
  }

  var NOTE = "以上文字由程式依公開資料自動整理，只描述特定期間的數值與變化，不含任何分析意見、預測或買賣建議；財報數字以公開資訊觀測站公告為準。金額單位：新台幣億元。";
  function bodyHtml(B, wide){
    var flags = B.flags.length ? '<div class="cfi-flags" aria-label="重點">' + B.flags.map(function(f){ return '<span class="cfi-tag ' + f.k + '">' + esc(f.t) + "</span>"; }).join("") + "</div>" : "";
    var f = B.fund.length ? B.fund.map(function(x){ return secHtml(x, wide); }).join("") : '<p class="cfi-soft">查無這一檔的財報與月營收資料（金融股、新上市櫃或 KY 股可能缺）。</p>';
    var c = B.chip.length ? B.chip.map(function(x){ return secHtml(x, wide); }).join("") : '<p class="cfi-soft">查無這一檔近半年的籌碼資料。</p>';
    return flags + '<div class="cfi-cols"><div class="cfi-col f"><h4>基本面<span>近 5 年財報與 24 個月營收</span></h4>' + f + '</div><div class="cfi-col c"><h4>籌碼<span>近半年（約 120 個交易日）</span></h4>' + c + "</div></div>" +
      '<p class="cfi-note">' + NOTE + "</p>";
  }

  var DATES = null;
  function dates(){ return DATES || (DATES = getJSON("market.json").then(function(m){ return m.dates || []; }).catch(function(){ return []; })); }
  function load(code){ return Promise.all([stock(code), dates()]).then(function(r){ return build(r[0], r[1]); }); }

  function fsGet(){ try { var v = +localStorage.getItem(FS_KEY); return v >= FS_MIN && v <= FS_MAX ? v : FS_DEF; } catch (e) { return FS_DEF; } }
  function fsSet(v){ v = Math.max(FS_MIN, Math.min(FS_MAX, v)); try { localStorage.setItem(FS_KEY, String(v)); } catch (e) {} document.querySelectorAll(".cfi").forEach(function(x){ x.style.setProperty("--cfi-fs", v + "px"); }); return v; }
  function flag(key, v){ try { if (v === undefined) return localStorage.getItem(key) === "1"; localStorage.setItem(key, v ? "1" : "0"); } catch (e) {} return !!v; }

  function fsBtns(){ return '<span class="cfi-fs" role="group" aria-label="字級"><button type="button" data-fs="-1" title="字小一點">A−</button><button type="button" data-fs="1" title="字大一點">A＋</button></span>'; }

  var CARD = {code: null};
  function card(host, code){
    if (!host) return;
    CARD.code = code;
    var r = ROWS[code] || {}, open = !flag(OPEN_KEY + ".off");
    host.hidden = false;
    host.className = "cfi cfi-card";
    host.style.setProperty("--cfi-fs", fsGet() + "px");
    host.innerHTML = '<div class="cfi-bar-top"><button type="button" class="cfi-tgl" aria-expanded="' + open + '">' + (open ? "▾" : "▸") + ' 基本面與籌碼概況</button><span class="cfi-who">' + esc(code + " " + (r.n || "")) + "</span>" + fsBtns() + "</div>" +
      '<div class="cfi-body"' + (open ? "" : " hidden") + '><p class="cfi-soft">載入中…</p></div>';
    host.querySelector(".cfi-tgl").onclick = function(){
      var b = host.querySelector(".cfi-body"), on = b.hidden;
      b.hidden = !on; this.setAttribute("aria-expanded", on); this.textContent = (on ? "▾" : "▸") + " 基本面與籌碼概況"; flag(OPEN_KEY + ".off", !on);
    };
    load(code).then(function(B){ if (CARD.code === code) host.querySelector(".cfi-body").innerHTML = bodyHtml(B, true); })
      .catch(function(){ if (CARD.code === code) host.querySelector(".cfi-body").innerHTML = '<p class="cfi-soft">這一檔的資料載入失敗，請稍後再試。</p>'; });
  }

  var D = {el: null, code: null, row: null, list: null, timer: null};
  function rowsOf(tb){ return tb ? [].filter.call(tb.rows, function(tr){ return codeOf(tr); }) : []; }
  function codeOf(tr){ var a = tr && tr.querySelector && tr.querySelector('a.bg-lk[href^="stock/"]'); return a ? decodeURIComponent(a.getAttribute("href").slice(6).replace(/\.html$/, "")) : null; }
  function drawer(){
    if (D.el) return D.el;
    var el = document.createElement("aside");
    el.className = "cfi cfi-drawer"; el.id = "cfi-drawer"; el.hidden = true;
    el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "基本面與籌碼概況");
    el.innerHTML = '<div class="cfi-dh"><div class="cfi-who"></div><div class="cfi-tools">' + fsBtns() +
      '<label class="cfi-hv" title="開著面板時，滑鼠移到表格的另一列就直接切換"><input type="checkbox"> 滑過切換</label>' +
      '<button type="button" class="cfi-x" aria-label="關閉" title="關閉（Esc）">✕</button></div>' +
      '<div class="cfi-nav"><button type="button" data-nav="-1">‹ 上一檔</button><span class="cfi-pos"></span><button type="button" data-nav="1">下一檔 ›</button><span class="cfi-keys">鍵盤 ↑ ↓ 切換・Esc 關閉</span></div></div>' +
      '<div class="cfi-db"></div>';
    (document.getElementById("cf") || document.body).appendChild(el);
    el.querySelector(".cfi-x").onclick = close;
    var hv = el.querySelector(".cfi-hv input");
    hv.checked = flag(HOVER_KEY); hv.onchange = function(){ flag(HOVER_KEY, hv.checked); };
    el.addEventListener("click", function(e){
      var n = e.target.closest("[data-nav]"); if (n){ step(+n.getAttribute("data-nav")); return; }
      var go = e.target.closest("[data-cfgo]"); if (go){ var t = go.getAttribute("data-cfgo"); close(); open(t, D.code || go.getAttribute("data-code")); window.scrollTo(0, $("cf-tabs").getBoundingClientRect().top + window.pageYOffset - 8); }
    });
    D.el = el;
    return el;
  }
  function paintRow(){
    document.querySelectorAll("#cf tr.cfi-cur").forEach(function(t){ t.classList.remove("cfi-cur"); });
    if (D.row && D.row.isConnected) D.row.classList.add("cfi-cur");
  }
  function show(code, tr){
    var el = drawer(), r = ROWS[code] || {};
    D.code = code; D.row = tr || null; D.list = tr ? tr.parentNode : null;
    el.style.setProperty("--cfi-fs", fsGet() + "px");
    el.querySelector(".cfi-who").innerHTML = '<a class="bg-lk" href="stock/' + encodeURIComponent(code) + '.html" title="個股資訊頁"><span class="c">' + esc(code) + '</span> <span class="n">' + esc(r.n || "") + "</span></a>" +
      (r.ind ? '<span class="cfi-ind">' + esc(r.ind) + "</span>" : "") +
      (nn(r.p) ? '<span class="cfi-px">' + grp(r.p, r.p >= 100 ? 1 : 2) + " 元<small>" + esc((R && R.asof) || "") + "</small></span>" : "") +
      '<button type="button" class="star bg-star" data-star="' + esc(code) + '" aria-pressed="false" title="加入觀察清單">☆</button>' +
      '<span class="cfi-go"><button type="button" data-cfgo="t1" title="① 個股籌碼多圖">①</button><button type="button" data-cfgo="t2" title="② 大戶籌碼">②</button><button type="button" data-cfgo="t3" title="③ 基本面">③</button></span>';
    var star = el.querySelector("button.bg-star");
    if (star && typeof TWSIXWatch !== "undefined") TWSIXWatch.paint(star);
    var rows = rowsOf(D.list), i = rows.indexOf(tr);
    el.querySelector(".cfi-nav").hidden = !(rows.length > 1 && i >= 0);
    el.querySelector(".cfi-pos").textContent = i >= 0 ? (i + 1) + " / " + rows.length : "";
    el.querySelector('[data-nav="-1"]').disabled = i <= 0;
    el.querySelector('[data-nav="1"]').disabled = i < 0 || i >= rows.length - 1;
    var body = el.querySelector(".cfi-db");
    body.innerHTML = '<p class="cfi-soft">載入中…</p>';
    el.hidden = false;
    document.documentElement.classList.add("cfi-on");
    paintRow();
    load(code).then(function(B){ if (D.code === code){ body.innerHTML = bodyHtml(B, false); body.scrollTop = 0; } })
      .catch(function(){ if (D.code === code) body.innerHTML = '<p class="cfi-soft">這一檔的資料載入失敗，請稍後再試。</p>'; });
  }
  function close(){
    if (!D.el) return;
    D.el.hidden = true; D.code = null;
    document.documentElement.classList.remove("cfi-on");
    document.querySelectorAll("#cf tr.cfi-cur").forEach(function(t){ t.classList.remove("cfi-cur"); });
  }
  function step(k){
    var rows = rowsOf(D.list), i = rows.indexOf(D.row);
    if (i < 0) return;
    var tr = rows[i + k]; if (!tr) return;
    show(codeOf(tr), tr);
    tr.scrollIntoView({block: "nearest"});
  }

  var ROW_TABS = ["cf-t4", "cf-t5", "cf-t6"];
  function rowPanel(tr){ var p = tr.closest(".cf-panel"); return p && ROW_TABS.indexOf(p.id) >= 0; }
  function wire(){
    var root = document.getElementById("cf"); if (!root) return;
    root.addEventListener("click", function(e){
      var b = e.target.closest && e.target.closest("button.bg-ins");
      if (b){ e.preventDefault(); e.stopPropagation(); var tr = b.closest("tr"); show(b.getAttribute("data-ins"), tr && codeOf(tr) === b.getAttribute("data-ins") ? tr : null); return; }
      var st = e.target.closest && e.target.closest(".cfi-drawer button.bg-star");
      if (st && typeof TWSIXWatch !== "undefined"){
        if (window.TWSIXStarMenu) TWSIXStarMenu.open(st); else TWSIXWatch.toggle(st.getAttribute("data-star"));
        TWSIXWatch.paint(st); return;
      }
      var fsb = e.target.closest && e.target.closest(".cfi [data-fs]");
      if (fsb){ fsSet(fsGet() + (+fsb.getAttribute("data-fs"))); return; }
      var tr2 = e.target.closest && e.target.closest(".bgm tbody tr");
      if (!tr2 || !rowPanel(tr2) || e.target.closest("a,button,input,select,label,textarea,summary")) return;
      var c = codeOf(tr2); if (c) show(c, tr2);
    }, true);
    root.addEventListener("mouseover", function(e){
      if (!D.code || !flag(HOVER_KEY) || !window.matchMedia("(hover: hover)").matches) return;
      var tr = e.target.closest && e.target.closest(".bgm tbody tr");
      if (!tr || tr === D.row || !rowPanel(tr)) return;
      var c = codeOf(tr); if (!c) return;
      clearTimeout(D.timer);
      D.timer = setTimeout(function(){ show(c, tr); }, 260);
    });
    document.addEventListener("keydown", function(e){
      if (!D.code || !D.el || D.el.hidden) return;
      var t = e.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (e.key === "Escape"){ close(); return; }
      if (typing) return;
      if (e.key === "ArrowDown" || e.key === "j"){ e.preventDefault(); step(1); }
      else if (e.key === "ArrowUp" || e.key === "k"){ e.preventDefault(); step(-1); }
    });
  }

  return {build: build, bodyHtml: bodyHtml, card: card, show: show, close: close, wire: wire, model: model};
})();
{% endraw %}
