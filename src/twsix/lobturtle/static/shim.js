/* 金股道靜態版：把 /api/... 換成建站時輸出的 JSON；回測在瀏覽器裡算（與 indicators.LobsterBacktester 同一套規則）。
   需要伺服器的功能（PDF、本機⇄NAS 同步、即時更新、即時國際情勢）在靜態版隱藏。 */
(function () {
  "use strict";
  var realFetch = window.fetch.bind(window);
  var embedded = window.parent !== window;
  var btData = null;

  function json(obj) {
    return Promise.resolve(new Response(JSON.stringify(obj), { status: 200, headers: { "Content-Type": "application/json" } }));
  }
  function evalCond(v, op, th, invert) {
    var sign = invert ? -1 : 1;
    if (op === "gt") return v > th ? sign : 0;
    if (op === "lt") return v < th ? -sign : 0;
    if (op === "both") return invert ? (v <= th ? 1 : -1) : (v > th ? 1 : -1);
    return 0;
  }
  function runBacktest(d, p) {
    var conds = [
      [p.c1_op == null ? "both" : p.c1_op, +p.c1_threshold || 0, false, d.lobster],
      [p.c2_op == null ? "both" : p.c2_op, +p.c2_threshold || 0, false, d.lobster_sum],
      [p.c3_op == null ? "both" : p.c3_op, p.c3_threshold == null ? 15 : +p.c3_threshold, true, d.mxf],
      [p.c4_op == null ? "both" : p.c4_op, p.c4_threshold == null ? 30 : +p.c4_threshold, true, d.tmf]
    ].filter(function (c) { return c[0]; });
    var n = d.labels.length, scores = [];
    for (var i = 0; i < n; i++) {
      var tot = 0, used = 0;
      conds.forEach(function (c) { var v = c[3][i]; if (v == null || isNaN(v)) return; used++; tot += evalCond(+v, c[0], c[1], c[2]); });
      scores.push(conds.length && used ? tot : null);
    }
    var eff = 0;
    if (p.c4_op == null || p.c4_op) { for (var k = 0; k < n; k++) if (d.tmf[k] != null) { eff = k; break; } }
    var end = n - 1, bd = p.buyDays || 30, sd = p.sellDays || 30;
    var bf = isNaN(p.buyFrom) ? -1 : p.buyFrom, bt = isNaN(p.buyTo) ? 2 : p.buyTo;
    var sf = isNaN(p.sellFrom) ? 2 : p.sellFrom, st = isNaN(p.sellTo) ? -1 : p.sellTo;
    var trades = [], pos = null, lastPx = null, lastDt = d.labels[end], lastSc = null;
    for (var j = eff; j <= end; j++) {
      var sc = scores[j], px = d.point[j];
      if (sc == null || px == null) continue;
      lastPx = px; lastDt = d.labels[j]; lastSc = sc;
      if (!pos) {
        if (sc >= bt) {
          for (var a = Math.max(eff, j - bd); a < j; a++) if (scores[a] != null && scores[a] <= bf) {
            pos = { buyIdx: j, buyDate: d.labels[j], buyPrice: px, buyScore: sc }; break; }
        }
      } else if (sc <= st) {
        for (var b = Math.max(eff, j - sd); b < j; b++) if (scores[b] != null && scores[b] >= sf) {
          var pnl = Math.round((px - pos.buyPrice) * 100) / 100;
          trades.push(Object.assign({}, pos, { sellIdx: j, sellDate: d.labels[j], sellPrice: px, sellScore: sc,
            holdDays: j - pos.buyIdx, profitPts: pnl, returnPct: Math.round(pnl / pos.buyPrice * 10000) / 100, open: false }));
          pos = null; break;
        }
      }
    }
    var holding = null;
    if (pos && lastPx != null) {
      var hp = Math.round((lastPx - pos.buyPrice) * 100) / 100;
      holding = Object.assign({}, pos, { lastDate: lastDt, lastPrice: lastPx, lastScore: lastSc, holdDays: end - pos.buyIdx,
        profitPts: hp, returnPct: Math.round(hp / pos.buyPrice * 10000) / 100 });
    }
    var tt = trades.length, wins = trades.filter(function (t) { return t.profitPts > 0; }).length;
    var sum = function (f) { return trades.reduce(function (s, t) { return s + f(t); }, 0); };
    var cum = trades.reduce(function (c, t) { return c * (1 + t.returnPct / 100); }, 1);
    var r2 = function (v) { return Math.round(v * 100) / 100; };
    return { effectiveStartIdx: eff, effectiveStartDate: d.labels[eff] || "", effectiveEndDate: d.labels[end] || "",
      effectiveDays: Math.max(0, end - eff + 1), scores: scores, trades: trades, holding: holding,
      summary: { totalTrades: tt, wins: wins, losses: tt - wins, winRatePct: tt ? r2(wins / tt * 100) : 0,
        avgReturnPct: tt ? r2(sum(function (t) { return t.returnPct; }) / tt) : 0, sumReturnPct: r2(sum(function (t) { return t.returnPct; })),
        cumReturnPct: r2((cum - 1) * 100), totalProfitPts: r2(sum(function (t) { return t.profitPts; })),
        maxWinPct: tt ? Math.max.apply(null, trades.map(function (t) { return t.returnPct; })) : 0,
        maxLossPct: tt ? Math.min.apply(null, trades.map(function (t) { return t.returnPct; })) : 0 } };
  }

  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var m = url.match(/^\/api\/([^?]+)/);
    if (!m) return realFetch(input, init);
    var path = m[1].replace(/\/$/, "");
    var method = ((init && init.method) || "GET").toUpperCase();
    if (path === "charts/lobster/backtest/run") {
      var p = {}; try { p = JSON.parse((init && init.body) || "{}"); } catch (e) {}
      var load = btData ? Promise.resolve(btData) : realFetch("api/charts/lobster/backtest.json").then(function (r) { return r.json(); });
      return load.then(function (d) { btData = d; return json(runBacktest(d, p)); });
    }
    if (method !== "GET") return json({ ok: false, error: "金股道靜態版不提供這個功能（請在龍蝦／海龜原系統操作）" });
    return realFetch("api/" + path + ".json");
  };

  document.addEventListener("DOMContentLoaded", function () {
    var css = document.createElement("style");
    css.textContent = "#btn-download-pdf,#btn-open-sync,#btn-refresh-intel,#btn-refresh-db{display:none!important}" +
      (embedded ? "#btn-back-to-top{display:none!important}" : "");
    document.head.appendChild(css);
  });
  // 金股道的深色／淺色切換同步到這一頁
  function setTheme(t) {
    if (t !== "light" && t !== "dark") return;
    var cur = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    if (cur === t) return;
    var b = document.getElementById("btn-theme-toggle-desktop") || document.getElementById("btn-theme-toggle");
    if (b) b.click(); else document.documentElement.setAttribute("data-theme", t);
  }
  window.addEventListener("message", function (e) { if (e.data && e.data.twsixTheme) setTheme(e.data.twsixTheme); });
  try { var t0 = localStorage.getItem("twsix-theme"); if (t0) { localStorage.setItem("lobturtle-theme", t0); document.documentElement.setAttribute("data-theme", t0); } } catch (e) {}
})();
