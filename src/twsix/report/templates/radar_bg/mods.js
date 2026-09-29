{% raw %}/* ── t1 ← BG 01stockchart ── */
CF_MODS["t1"] = function(ROOT, API){
var PFX = "m1-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;


(function(){
  "use strict";

  var META = null, DATES = null;
  var chunkCache = {};
  var activeCharts = [];
  var isDark = false;

  function computeIsDark(){
    var attr = document.documentElement.getAttribute('data-theme');
    if(attr === 'dark') return true;
    if(attr === 'light') return false;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function cssVar(name){
    return getComputedStyle(ROOT).getPropertyValue(name).trim();
  }

  function fmtMD(iso){
    if(!iso) return '';
    var p = iso.split('-');
    return (p[1]|0) + '/' + (p[2]|0);
  }

  function setStatus(msg, isErr){
    var el = __id('status');
    el.textContent = msg || '';
    el.className = 'status' + (isErr ? ' err' : '');
  }

  function chunkIdFor(code){
    var c = code.charAt(0);
    return (c >= '0' && c <= '9') ? c : '9';
  }

  function loadJSON(path){
    return __fetch(path).then(function(r){
      if(!r.ok) throw new Error('無法載入 ' + path);
      return r.json();
    });
  }

  function ensureChunk(id){
    if(chunkCache[id]) return chunkCache[id];
    var p = loadJSON('chunk_' + id + '.json');
    chunkCache[id] = p;
    return p;
  }

  function resolveCode(raw){
    raw = (raw || '').trim();
    if(!raw) return null;
    if(META[raw]) return raw;
    // 允許輸入名稱做模糊比對
    var hit = null;
    for(var code in META){
      if(META[code] && META[code].indexOf(raw) !== -1){ hit = code; break; }
    }
    return hit;
  }

  // ---- panel definitions (順序對應原檔案 5x4 圖表排版) ----
  var PANELS = [
    {grp:'a', tag:'外資法人', title:'外資+投信買賣超/資本額 60日累計', type:'line', key:'fi_ti_cap60', dk:'fi_ti_cap60', color:'group-a-line'},
    {grp:'b', tag:'大戶籌碼', title:'大戶人數', type:'line', key:'holder_cnt', dk:'wide', color:'group-b-line', int:true},
    {grp:'c', tag:'成交量能', title:'成交金額20日累計佔全市場比例(%)', type:'bar', key:'val_20d_pct', dk:'val_20d_pct', color:'group-c-line'},
    {grp:'d', tag:'貪婪恐懼', title:'貪婪指標1（買盤比例20日總和）', type:'line', key:'greed1', dk:'greed1', color:'red'},
    {grp:'d', tag:'貪婪恐懼', title:'貪婪指標2（買盤比例60日總和）', type:'line', key:'greed2', dk:'greed2', color:'red'},

    {grp:'a', tag:'外資法人', title:'紅:法人預估成交額20日(M) / 藍:成交金額20日(M)', type:'dual', keys:['fi_amt20','val_amt20'], dk:'fi_amt20', colors:['red','blue']},
    {grp:'b', tag:'大戶籌碼', title:'大戶比例(%)', type:'line', key:'holder_ratio', dk:'wide', color:'group-b-line'},
    {grp:'c', tag:'成交量能', title:'成交金額/資本額倍數 20日累計', type:'bar', key:'val_over_cap20', dk:'val_over_cap20', color:'group-c-line'},
    {grp:'d', tag:'貪婪恐懼', title:'恐懼指標1（賣盤比例20日總和）', type:'line', key:'fear1', dk:'fear1', color:'blue'},
    {grp:'d', tag:'貪婪恐懼', title:'恐懼指標2（賣盤比例60日總和）', type:'line', key:'fear2', dk:'fear2', color:'blue'},

    {grp:'a', tag:'外資法人', title:'外資投信20日市值周轉率', type:'line', key:'fi_turnover20', dk:'fi_turnover20', color:'group-a-line'},
    {grp:'b', tag:'大戶籌碼', title:'大戶庫存張數', type:'line', key:'holder_stock', dk:'wide', color:'group-b-line', int:true},
    {grp:'c', tag:'成交量能', title:'紅:法人預估成交額20日(M) / 藍:成交金額20日(M)', type:'dual', keys:['fi_amt20','val_amt20'], dk:'fi_amt20', colors:['red','blue']},
    {grp:'d', tag:'貪婪恐懼', title:'紅:貪婪指標1 / 藍:恐懼指標1', type:'dual', keys:['greed1','fear1'], dk:'greed1', colors:['red','blue']},
    {grp:'d', tag:'貪婪恐懼', title:'紅:貪婪指標2 / 藍:恐懼指標2', type:'dual', keys:['greed2','fear2'], dk:'greed2', colors:['red','blue']},

    {grp:'a', tag:'外資法人', title:'扣掉大戶之20日周轉率(%)', type:'line', key:'turn_ex_holder20', dk:'turn_ex_holder20', color:'group-a-line'},
    {grp:'b', tag:'大戶籌碼', title:'總股東人數', type:'line', key:'total_holders', dk:'wide', color:'group-b-line', int:true},
    {grp:'c', tag:'成交量能', title:'紅:法人預估成交額20日(M) / 藍:成交金額20日(M)', type:'dual', keys:['fi_amt20','val_amt20'], dk:'fi_amt20', colors:['red','blue']},
    {grp:'d', tag:'貪婪恐懼', title:'買盤比例20日－賣盤比例20日', type:'line', key:'diff20', dk:'diff20', color:'purple'},
    {grp:'d', tag:'貪婪恐懼', title:'買盤比例60日－賣盤比例60日', type:'line', key:'diff60', dk:'diff60', color:'purple'},

    {grp:'a', tag:'外資法人', title:'外資投信買賣超除以大戶人數60日(千)', type:'line', key:'fi_ti_per_holder60', dk:'fi_ti_per_holder60', color:'group-a-line'},
    {grp:'a', tag:'外資法人', title:'外資投信買賣超除以大戶人數60日排名', type:'line', key:'fi_ti_per_holder60_rank', dk:'fi_ti_per_holder60_rank', color:'group-a-line'},
    {grp:'c', tag:'成交量能', title:'成交金額除以大戶人數20日(千)', type:'line', key:'val_per_holder20', dk:'val_per_holder20', color:'group-c-line'},
    {grp:'c', tag:'成交量能', title:'成交金額除以大戶人數20日排名', type:'line', key:'val_per_holder20_rank', dk:'val_per_holder20_rank', color:'group-c-line'}
  ];

  PANELS.forEach(function(p, i){ p._i = i; });

  var GROUPS = [
    {key:'a', label:'外資法人'},
    {key:'b', label:'大戶籌碼'},
    {key:'c', label:'成交量能'},
    {key:'d', label:'貪婪恐懼'}
  ];

  var currentCode = null, currentStock = null;

  function buildGrid(){
    var grid = __id('grid');
    grid.innerHTML = '';
    GROUPS.forEach(function(g){
      var panels = PANELS.filter(function(p){ return p.grp === g.key; });
      var section = document.createElement('div');
      section.className = 'section';
      section.setAttribute('data-grp', g.key);

      var heading = document.createElement('div');
      heading.className = 'section-heading';
      var t = document.createElement('span'); t.className = 't'; t.textContent = g.label;
      var n = document.createElement('span'); n.className = 'n'; n.textContent = panels.length + ' 張圖';
      heading.appendChild(t); heading.appendChild(n);
      section.appendChild(heading);

      var cards = document.createElement('div');
      cards.className = 'section-cards';
      panels.forEach(function(p){
        var card = document.createElement('div');
        card.className = 'card g-' + p.grp;
        var tag = document.createElement('div');
        tag.className = 'tag'; tag.textContent = p.tag;
        var h3 = document.createElement('h3');
        h3.textContent = p.title;
        var wrap = document.createElement('div');
        wrap.className = 'canvas-wrap';
        var canvas = document.createElement('canvas');
        canvas.id = PFX + 'panel-' + p._i;
        wrap.appendChild(canvas);
        card.appendChild(tag); card.appendChild(h3); card.appendChild(wrap);
        cards.appendChild(card);
      });
      section.appendChild(cards);
      grid.appendChild(section);
    });
  }

  var heroChart = null;

  function destroyCharts(){
    activeCharts.forEach(function(c){ try{ c.destroy(); }catch(e){} });
    activeCharts = [];
  }

  function evenIndices(len, count){
    if(len <= 0) return [];
    if(len <= count) { var all=[]; for(var i=0;i<len;i++) all.push(i); return all; }
    var idxs = [];
    for(var i=0;i<count;i++){
      idxs.push(Math.round(i * (len - 1) / (count - 1)));
    }
    // 去重，且一定保留最後一個索引（最新日期）在最右邊
    idxs[idxs.length-1] = len - 1;
    return idxs.filter(function(v,i,a){ return a.indexOf(v) === i; });
  }

  function baseScales(xLabels){
    var gridColor = cssVar('--border');
    var tickColor = isDark ? cssVar('--ink-soft') : cssVar('--ink-soft');
    var wantIdxs = evenIndices(xLabels.length, 6);
    return {
      x:{
        grid:{ display:false },
        afterBuildTicks: function(axis){
          axis.ticks = wantIdxs.map(function(i){ return { value: i }; });
        },
        ticks:{ color: tickColor, autoSkip:false, font:{ size:9 } }
      },
      y:{
        position:'right',
        grid:{ color: gridColor },
        ticks:{ color: tickColor, font:{ size:9 }, maxTicksLimit:5 }
      }
    };
  }

  function commonOptions(xLabels){
    return {
      responsive:true, maintainAspectRatio:false,
      animation:{ duration:250 },
      interaction:{ mode:'index', intersect:false },
      plugins:{
        legend:{ display:false },
        tooltip:{
          titleFont:{ size:10 }, bodyFont:{ size:10 },
          callbacks:{
            title: function(items){ return items.length ? xLabels[items[0].dataIndex] : ''; }
          }
        }
      },
      scales: baseScales(xLabels)
    };
  }

  function lineDataset(label, data, colorVar, fillOpacity){
    var color = cssVar(colorVar);
    return {
      label: label, data: data, borderColor: color,
      backgroundColor: color, pointRadius:0, borderWidth:1.75,
      tension:0.15, spanGaps:true
    };
  }

  function renderHero(price){
    if(heroChart){ try{ heroChart.destroy(); }catch(e){} heroChart = null; }
    var ctx = __id('heroCanvas');
    var xLabels = (DATES.price || []).map(fmtMD);
    heroChart = new Chart(ctx, {
      type:'line',
      data:{ labels: xLabels, datasets:[ lineDataset('股價', price, '--accent') ] },
      options: Object.assign(commonOptions(xLabels), {
        plugins: Object.assign({}, commonOptions(xLabels).plugins, {
          tooltip:{ callbacks:{
            title: function(items){ return items.length ? xLabels[items[0].dataIndex] : ''; },
            label: function(item){ return '股價 ' + Number(item.parsed.y).toFixed(2) + ' 元'; }
          }}
        })
      })
    });
  }

  function renderPanel(panel, stock){
    var canvas = __id('panel-' + panel._i);
    var dLabels = (DATES[panel.dk] || []).map(fmtMD);
    var opts = commonOptions(dLabels);
    var chart;

    if(panel.type === 'bar'){
      var data = stock[panel.key] || [];
      var color = cssVar('--' + panel.color);
      chart = new Chart(canvas, {
        type:'bar',
        data:{ labels:dLabels, datasets:[{ label:panel.title, data:data, backgroundColor: color, borderWidth:0, barPercentage:0.9, categoryPercentage:0.9 }] },
        options: opts
      });
    } else if(panel.type === 'dual'){
      var d1 = stock[panel.keys[0]] || [];
      var d2 = stock[panel.keys[1]] || [];
      chart = new Chart(canvas, {
        type:'line',
        data:{ labels:dLabels, datasets:[
          lineDataset(panel.keys[0], d1, '--' + panel.colors[0]),
          lineDataset(panel.keys[1], d2, '--' + panel.colors[1])
        ]},
        options: opts
      });
    } else {
      var vals = stock[panel.key] || [];
      chart = new Chart(canvas, {
        type:'line',
        data:{ labels:dLabels, datasets:[ lineDataset(panel.title, vals, '--' + panel.color) ] },
        options: opts
      });
    }
    return chart;
  }

  function renderAllPanels(){
    destroyCharts();
    PANELS.forEach(function(p){
      var chart = renderPanel(p, currentStock);
      activeCharts.push(chart);
    });
  }

  function showStock(code, stock){
    currentCode = code; currentStock = stock;

    __id('stockbar').hidden = false;
    __id('heroCard').hidden = false;
    __id('grid').hidden = false;

    __id('sbCode').textContent = code;
    __id('sbName').textContent = META[code] || '';
    var pd = DATES.price || [];
    __id('sbAsof').textContent = pd.length ? ('資料至 ' + pd[pd.length-1]) : '';

    renderHero(stock.price || []);
    renderAllPanels();
  }

  function doLookup(raw){
    var code = resolveCode(raw);
    if(!code){
      setStatus('查無「' + raw + '」，請確認代號或名稱是否正確。', true);
      return;
    }
    setStatus('讀取 ' + code + ' ' + (META[code]||'') + ' 資料中…');
    API.stock(code).then(function(stock){
      if(!stock){
        setStatus('資料庫內找不到 ' + code + ' 的籌碼資料。', true);
        return;
      }
      setStatus('');
      showStock(code, stock);
    }).catch(function(err){
      setStatus('讀取資料失敗：' + err.message, true);
    });
  }

  var suggestList = [], suggestIndex = -1;

  function hideSuggest(){
    var box = __id('suggestBox');
    box.hidden = true; box.innerHTML = '';
    suggestList = []; suggestIndex = -1;
  }

  function highlightSuggest(){
    var items = ROOT.querySelectorAll('#m1-suggestBox .suggest-item');
    items.forEach(function(el, i){ el.classList.toggle('active', i === suggestIndex); });
  }

  function selectSuggestion(code){
    __id('codeInput').value = code;
    hideSuggest();
    doLookup(code);
  }

  function updateSuggest(query){
    var box = __id('suggestBox');
    query = (query || '').trim();
    if(!query || !META){ hideSuggest(); return; }

    var byCode = [], byName = [];
    for(var code in META){
      var name = META[code] || '';
      if(code.indexOf(query) === 0){ byCode.push(code); }
      else if(name.indexOf(query) !== -1){ byName.push(code); }
    }
    suggestList = byCode.concat(byName).slice(0, 8);
    suggestIndex = -1;

    if(!suggestList.length){ hideSuggest(); return; }

    box.innerHTML = '';
    suggestList.forEach(function(c){
      var item = document.createElement('div');
      item.className = 'suggest-item';
      var codeSpan = document.createElement('span'); codeSpan.className = 'code'; codeSpan.textContent = c;
      var nameSpan = document.createElement('span'); nameSpan.className = 'name'; nameSpan.textContent = META[c];
      item.appendChild(codeSpan); item.appendChild(nameSpan);
      item.addEventListener('mousedown', function(e){ e.preventDefault(); selectSuggestion(c); });
      box.appendChild(item);
    });
    box.hidden = false;
  }

  function init(){
    isDark = computeIsDark();
    if(window.matchMedia){
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(){ isDark = computeIsDark(); });
    }

    buildGrid();

    Promise.all([ loadJSON('meta.json'), loadJSON('dates.json') ]).then(function(res){
      META = res[0]; DATES = res[1];
      setStatus('');
      var start = '2330';
      __id('codeInput').value = start;
      doLookup(start);
    }).catch(function(err){
      setStatus('基礎資料載入失敗：' + err.message, true);
    });

    var input = __id('codeInput');

    __id('searchBtn').addEventListener('click', function(){
      hideSuggest();
      doLookup(input.value);
    });
    input.addEventListener('input', function(){ updateSuggest(input.value); });
    input.addEventListener('keydown', function(e){
      if(e.key === 'Enter'){
        if(suggestIndex >= 0 && suggestList[suggestIndex]){
          selectSuggestion(suggestList[suggestIndex]);
        } else {
          hideSuggest();
          doLookup(this.value);
        }
      } else if(e.key === 'ArrowDown'){
        if(suggestList.length){ e.preventDefault(); suggestIndex = (suggestIndex + 1) % suggestList.length; highlightSuggest(); }
      } else if(e.key === 'ArrowUp'){
        if(suggestList.length){ e.preventDefault(); suggestIndex = (suggestIndex - 1 + suggestList.length) % suggestList.length; highlightSuggest(); }
      } else if(e.key === 'Escape'){
        hideSuggest();
      }
    });
    input.addEventListener('blur', function(){ setTimeout(hideSuggest, 150); });
  }

  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

};

/* ── t2 ← BG 02holder ── */
CF_MODS["t2"] = function(ROOT, API){
var PFX = "m2-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

(function () {
  var TIERS = ['1','5','10','15','20','30','40','50','100','200','400','800','1000'];
  var DAILY_WINDOW_TRADING_DAYS = 120;
  var state = { meta: null, dates: null, chunks: {}, current: null, weeklyIdx: null, dailyIdx: null };

  function sliceArr(arr, idxs) {
    if (!arr) return null;
    var out = new Array(idxs.length);
    for (var i = 0; i < idxs.length; i++) out[i] = arr[idxs[i]];
    return out;
  }
  var tooltip = __id('tooltip');
  var msgEl = __id('msg');

  function fmtInt(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Math.round(v).toLocaleString('en-US');
  }
  function fmtPrice(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtPct(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Number(v).toFixed(2) + '%';
  }
  // Excel stores custody holdings in shares (股); 1張 = 1000股.
  function fmtLot(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Math.round(v / 1000).toLocaleString('en-US');
  }
  function shortDate(d) { return d.slice(5).replace('-', '/'); }

  async function loadJSON(path) {
    var res = await __fetch(path);
    if (!res.ok) throw new Error('load failed: ' + path);
    return res.json();
  }

  async function ensureChunk(digit) {
    if (state.chunks[digit]) return state.chunks[digit];
    var data = await loadJSON('stockdata/chunk_' + digit + '.json');
    state.chunks[digit] = data;
    return data;
  }

  function buildDatalist() {
    var dl = __id('stockList');
    var frag = document.createDocumentFragment();
    var codes = Object.keys(state.meta).sort();
    for (var i = 0; i < codes.length; i++) {
      var opt = document.createElement('option');
      opt.value = codes[i] + ' ' + state.meta[codes[i]];
      frag.appendChild(opt);
    }
    dl.appendChild(frag);
  }

  function resolveCode(raw) {
    raw = (raw || '').trim();
    if (!raw) return null;
    var m = raw.match(/^(\d{4,6})/);
    if (m && state.meta[m[1]]) return m[1];
    // exact name match
    for (var code in state.meta) {
      if (state.meta[code] === raw) return code;
    }
    // substring name match
    for (var code2 in state.meta) {
      if (state.meta[code2].indexOf(raw) !== -1) return code2;
    }
    return null;
  }

  // ---------- chart rendering ----------
  var NS = 'http://www.w3.org/2000/svg';
  function el(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  function buildSeries(dates, values) {
    var pts = [];
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (v === null || v === undefined) continue;
      pts.push({ i: i, d: dates[i], v: v });
    }
    return pts;
  }

  function drawChart(container, opts) {
    // opts: dates[], values[], color, format
    container.innerHTML = '';
    var W = 400, H = 230, padL = 8, padR = 8, padT = 16, padB = 28;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none' });
    container.appendChild(svg);

    var pts = buildSeries(opts.dates, opts.values);
    if (pts.length === 0) {
      var t = el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' });
      t.textContent = '無資料';
      svg.appendChild(t);
      return;
    }
    var vmin = Infinity, vmax = -Infinity;
    for (var i = 0; i < pts.length; i++) { if (pts[i].v < vmin) vmin = pts[i].v; if (pts[i].v > vmax) vmax = pts[i].v; }
    if (vmin === vmax) { vmin -= 1; vmax += 1; }
    var pad = (vmax - vmin) * 0.12;
    vmin -= pad; vmax += pad;

    var n = opts.values.length;
    function xAt(idx) { return padL + (n <= 1 ? 0 : (idx / (n - 1)) * plotW); }
    function yAt(v) { return padT + (1 - (v - vmin) / (vmax - vmin)) * plotH; }

    // grid: baseline only (recessive)
    svg.appendChild(el('line', { class: 'grid-line', x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH }));

    // path
    var d = '';
    for (var j = 0; j < pts.length; j++) {
      var x = xAt(pts[j].i), y = yAt(pts[j].v);
      d += (j === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2) + ' ';
    }
    svg.appendChild(el('path', { class: 'line', d: d, stroke: opts.color }));

    // min/max labels
    var realMax = -Infinity, realMin = Infinity;
    for (var k = 0; k < pts.length; k++) { if (pts[k].v > realMax) realMax = pts[k].v; if (pts[k].v < realMin) realMin = pts[k].v; }
    var lblMax = el('text', { class: 'val-max', x: padL, y: padT + 7 });
    lblMax.textContent = opts.format(realMax);
    svg.appendChild(lblMax);
    var lblMin = el('text', { class: 'val-min', x: padL, y: padT + plotH - 2 });
    lblMin.textContent = opts.format(realMin);
    svg.appendChild(lblMin);

    // date axis: several evenly spaced ticks (not just first/last)
    var tickCount = Math.max(2, opts.ticks || 4);
    for (var ti = 0; ti < tickCount; ti++) {
      var frac = ti / (tickCount - 1);
      var idx = Math.round(frac * (n - 1));
      var tx = xAt(idx);
      var anchor = ti === 0 ? 'start' : (ti === tickCount - 1 ? 'end' : 'middle');
      var lblX = ti === 0 ? padL : (ti === tickCount - 1 ? W - padR : tx);
      svg.appendChild(el('line', { class: 'grid-line', x1: tx, x2: tx, y1: padT, y2: padT + plotH, opacity: ti === 0 || ti === tickCount - 1 ? 0 : 0.6 }));
      var lbl = el('text', { class: 'date-lbl', x: lblX, y: H - 4, 'text-anchor': anchor });
      lbl.textContent = shortDate(opts.dates[idx]);
      svg.appendChild(lbl);
    }

    // endpoint marker
    var last = pts[pts.length - 1];
    var ex = xAt(last.i), ey = yAt(last.v);
    svg.appendChild(el('circle', { class: 'end-ring', cx: ex, cy: ey, r: 7 }));
    svg.appendChild(el('circle', { cx: ex, cy: ey, r: 4.5, fill: opts.color }));

    // hover elements
    var crossV = el('line', { class: 'cross', x1: 0, x2: 0, y1: padT, y2: padT + plotH });
    var crossH = el('line', { class: 'cross', x1: padL, x2: W - padR, y1: 0, y2: 0 });
    var hoverDot = el('circle', { class: 'hover-dot', r: 5, fill: opts.color, stroke: 'var(--surface)', 'stroke-width': 2 });
    svg.appendChild(crossV); svg.appendChild(crossH); svg.appendChild(hoverDot);

    var overlay = el('rect', { class: 'overlay', x: 0, y: 0, width: W, height: H });
    svg.appendChild(overlay);

    function pointFromEvent(evt) {
      var pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      var ctm = svg.getScreenCTM();
      if (!ctm) return null;
      return pt.matrixTransform(ctm.inverse());
    }

    function updateAt(evt) {
      var loc = pointFromEvent(evt);
      if (!loc) return;
      var idx = Math.round(((loc.x - padL) / plotW) * (n - 1));
      idx = Math.max(0, Math.min(n - 1, idx));
      var val = opts.values[idx];
      var date = opts.dates[idx];
      if (val === null || val === undefined) { hideCrosshair(); return; }
      var x = xAt(idx), y = yAt(val);
      crossV.setAttribute('x1', x); crossV.setAttribute('x2', x); crossV.style.opacity = 1;
      crossH.setAttribute('y1', y); crossH.setAttribute('y2', y); crossH.style.opacity = 1;
      hoverDot.setAttribute('cx', x); hoverDot.setAttribute('cy', y); hoverDot.style.opacity = 1;
      tooltip.innerHTML = date + '　<b>' + opts.format(val) + '</b>';
      tooltip.style.left = evt.clientX + 'px';
      tooltip.style.top = evt.clientY + 'px';
      tooltip.style.opacity = 1;
    }
    function hideCrosshair() {
      crossV.style.opacity = 0; crossH.style.opacity = 0; hoverDot.style.opacity = 0; tooltip.style.opacity = 0;
    }
    // Pointer Events cover mouse hover AND touch drag/tap in one API, so the
    // same crosshair+tooltip works on phones, not just desktop hover. A mouse
    // hides the instant it leaves; a finger has no "hover", so on release we
    // leave the reading up for a couple seconds instead of yanking it away
    // the moment the tap ends.
    var hideTimer = null;
    function cancelHide() { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } }
    function scheduleHide(evt) {
      cancelHide();
      if (evt && evt.pointerType === 'touch') {
        hideTimer = setTimeout(hideCrosshair, 2000);
      } else {
        hideCrosshair();
      }
    }
    overlay.addEventListener('pointerdown', function (evt) { cancelHide(); updateAt(evt); });
    overlay.addEventListener('pointermove', function (evt) { cancelHide(); updateAt(evt); });
    overlay.addEventListener('pointerup', scheduleHide);
    overlay.addEventListener('pointercancel', scheduleHide);
    overlay.addEventListener('pointerleave', function (evt) { if (!evt || evt.pointerType !== 'touch') hideCrosshair(); });
  }

  function makePanel(gridEl, title, accentClass, rowStart) {
    var panel = document.createElement('div');
    panel.className = 'panel ' + accentClass + (rowStart ? ' row-start' : '');
    var t = document.createElement('div'); t.className = 'ptitle'; t.textContent = title;
    var now = document.createElement('div'); now.className = 'pnow';
    var box = document.createElement('div'); box.className = 'chartbox';
    panel.appendChild(t); panel.appendChild(now); panel.appendChild(box);
    gridEl.appendChild(panel);
    return { panel: panel, now: now, box: box };
  }

  function renderMetric(gridEl, title, accentClass, dates, values, color, format, ticks, rowStart) {
    var p = makePanel(gridEl, title, accentClass, rowStart);
    var lastVal = null;
    for (var i = values.length - 1; i >= 0; i--) { if (values[i] !== null && values[i] !== undefined) { lastVal = values[i]; break; } }
    p.now.textContent = format(lastVal);
    drawChart(p.box, { dates: dates, values: values, color: color, format: format, ticks: ticks });
  }

  function clearGrid(id) { __id(id).innerHTML = ''; }

  async function showStock(code) {
    var digit = /^[0-9]/.test(code[0]) ? code[0] : '9';
    var chunk;
    try {
      chunk = {}; chunk[code] = await API.entry(code);
    } catch (e) {
      msgEl.textContent = '資料載入失敗，請稍後再試。';
      return;
    }
    var entry = chunk[code];
    if (!entry) {
      msgEl.textContent = '查無「' + code + '」的資料。';
      return;
    }
    msgEl.textContent = '';
    state.current = code;
    __id('curCode').textContent = code;
    __id('curName').textContent = state.meta[code] || '';

    var dd = state.dailyDates, di = state.dailyIdx, wd = state.weeklyDates, wi = state.weeklyIdx;
    __id('dailyCaption').textContent = '每日資料（近' + DAILY_WINDOW_TRADING_DAYS + '個交易日）　' + dd[0] + ' ～ ' + dd[dd.length - 1];
    __id('stockCaption').textContent = '集保股權分散表（週更，近' + DAILY_WINDOW_TRADING_DAYS + '個交易日）　' + wd[0] + ' ～ ' + wd[wd.length - 1];
    __id('peopleCaption').textContent = '集保股權分散表（週更，近' + DAILY_WINDOW_TRADING_DAYS + '個交易日）　' + wd[0] + ' ～ ' + wd[wd.length - 1];

    clearGrid('dailyGrid'); clearGrid('stockGrid'); clearGrid('peopleGrid');

    var dailyGrid = __id('dailyGrid');
    renderMetric(dailyGrid, '收盤價', 'accent-orange', dd, sliceArr(entry.c, di), 'var(--orange)', fmtPrice, 6);
    renderMetric(dailyGrid, '大戶比例（持股市值5000萬以上）', 'accent-blue', dd, sliceArr(entry.hr, di), 'var(--blue)', fmtPct, 6);
    renderMetric(dailyGrid, '大戶人數', 'accent-blue', dd, sliceArr(entry.hc, di), 'var(--blue)', fmtInt, 6);
    renderMetric(dailyGrid, '總股東人數', 'accent-aqua', dd, sliceArr(entry.sh, di), 'var(--aqua)', fmtInt, 6);

    var ROW_START_TIERS = { '1': true, '30': true, '400': true };

    var stockGrid = __id('stockGrid');
    renderMetric(stockGrid, '總集保張數（張）', 'accent-aqua', wd, sliceArr(entry.cw, wi), 'var(--aqua)', fmtLot, 5, true);
    renderMetric(stockGrid, '收盤價（對應週）', 'accent-orange', wd, sliceArr(entry.cp, wi), 'var(--orange)', fmtPrice, 5);
    for (var i = 0; i < TIERS.length; i++) {
      var t = TIERS[i];
      renderMetric(stockGrid, t + '張以上－持股合計數（張）', 'accent-blue', wd, sliceArr(entry.st[t], wi), 'var(--blue)', fmtLot, 5, !!ROW_START_TIERS[t]);
    }

    var peopleGrid = __id('peopleGrid');
    renderMetric(peopleGrid, '總股東人數', 'accent-aqua', wd, sliceArr(entry.shw, wi), 'var(--aqua)', fmtInt, 5, true);
    renderMetric(peopleGrid, '收盤價（對應週）', 'accent-orange', wd, sliceArr(entry.cp, wi), 'var(--orange)', fmtPrice, 5);
    for (var j = 0; j < TIERS.length; j++) {
      var t2 = TIERS[j];
      renderMetric(peopleGrid, t2 + '張以上－股東人數', 'accent-blue', wd, sliceArr(entry.pt[t2], wi), 'var(--blue)', fmtInt, 5, !!ROW_START_TIERS[t2]);
    }
  }

  function handleSubmit() {
    var input = __id('stockInput');
    var code = resolveCode(input.value);
    if (!code) { msgEl.textContent = '請輸入正確的股票代號或名稱（例如 2330 或 台積電）。'; return; }
    input.value = code + ' ' + state.meta[code];
    showStock(code);
  }

  async function init() {
    try {
      var res = await Promise.all([loadJSON('stockdata/meta.json'), loadJSON('stockdata/dates.json')]);
      state.meta = res[0]; state.dates = res[1];
      buildDatalist();
      // Daily window: last N trading days (dates.daily already only lists trading days).
      var dAll = state.dates.daily;
      var dKeep = [];
      for (var di = Math.max(0, dAll.length - DAILY_WINDOW_TRADING_DAYS); di < dAll.length; di++) dKeep.push(di);
      state.dailyIdx = dKeep;
      state.dailyDates = sliceArr(dAll, dKeep);
      // Weekly window: same cutoff date as the daily 120-trading-day window,
      // so both sections cover the same calendar span (not a separate 120
      // calendar-day count, which would drift from the trading-day window).
      var wAll = state.dates.weekly;
      var cutoff = dAll[dKeep[0]];
      var keep = [];
      for (var wi = 0; wi < wAll.length; wi++) { if (wAll[wi] >= cutoff) keep.push(wi); }
      state.weeklyIdx = keep;
      state.weeklyDates = sliceArr(wAll, keep);
    } catch (e) {
      msgEl.textContent = '資料索引載入失敗，請重新整理頁面。';
      return;
    }
    __id('goBtn').addEventListener('click', handleSubmit);
    __id('stockInput').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') handleSubmit();
    });
    __id('stockInput').value = '2330 台積電';
    showStock('2330');
  }

  init();
})();

};

/* ── t3 ← BG 03fund ── */
CF_MODS["t3"] = function(ROOT, API){
var PFX = "m3-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

(function(){
  "use strict";

  // ---------------------------------------------------------------
  // theme tokens (read once; charts re-read on paint for simplicity)
  // ---------------------------------------------------------------
  function cssVar(name){
    return getComputedStyle(ROOT).getPropertyValue(name).trim();
  }

  // ---------------------------------------------------------------
  // data loading
  // ---------------------------------------------------------------
  var META = null, QLABELS = null, MLABELS = null;
  var chunkCache = {};

  function loadJSON(path){
    return __fetch(path).then(function(r){
      if(!r.ok) throw new Error("fetch failed: " + path);
      return r.json();
    });
  }

  function chunkForCode(code){
    var c = code[0];
    return (c >= "0" && c <= "9") ? ("chunk_" + c + ".json") : null;
  }

  function getRecord(code){
    return API.rec(code);
    var file = chunkForCode(code);
    if(!file) return Promise.resolve(null);
    if(chunkCache[file]) return Promise.resolve(chunkCache[file][code] || null);
    return loadJSON(file).then(function(data){
      chunkCache[file] = data;
      return data[code] || null;
    });
  }

  // ---------------------------------------------------------------
  // search
  // ---------------------------------------------------------------
  var searchIndex = [];
  var $search = __id("search");
  var $dropdown = __id("dropdown");
  var activeIdx = -1;
  var currentMatches = [];

  function buildIndex(){
    searchIndex = Object.keys(META).map(function(code){
      var m = META[code];
      return { code: code, name: m.name || "", ind: m.ind || "" };
    });
  }

  function matchStock(q){
    q = q.trim();
    if(!q) return [];
    var out = [];
    var qUpper = q.toUpperCase();
    for(var i=0;i<searchIndex.length && out.length < 8;i++){
      var it = searchIndex[i];
      if(it.code.indexOf(qUpper) === 0 || (it.name && it.name.indexOf(q) !== -1)){
        out.push(it);
      }
    }
    return out;
  }

  function renderDropdown(items){
    currentMatches = items;
    activeIdx = -1;
    if(!items.length){
      $dropdown.innerHTML = '<div class="dd-empty">找不到符合的股票代號或名稱</div>';
      $dropdown.classList.add("open");
      return;
    }
    $dropdown.innerHTML = items.map(function(it, i){
      return '<div class="dd-item" data-idx="'+i+'" data-code="'+it.code+'">' +
        '<span class="code">'+it.code+'</span>' +
        '<span class="nm">'+escapeHtml(it.name)+'</span>' +
        '<span class="ind">'+escapeHtml(it.ind||"")+'</span>' +
      '</div>';
    }).join("");
    $dropdown.classList.add("open");
    Array.prototype.forEach.call($dropdown.querySelectorAll(".dd-item"), function(el){
      el.addEventListener("click", function(){
        selectStock(el.getAttribute("data-code"));
      });
    });
  }

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, function(c){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
    });
  }

  function closeDropdown(){ $dropdown.classList.remove("open"); }

  $search.addEventListener("input", function(){
    renderDropdown(matchStock($search.value));
  });
  $search.addEventListener("keydown", function(e){
    if(!$dropdown.classList.contains("open")) return;
    if(e.key === "ArrowDown"){
      e.preventDefault();
      activeIdx = Math.min(activeIdx+1, currentMatches.length-1);
      highlightActive();
    } else if(e.key === "ArrowUp"){
      e.preventDefault();
      activeIdx = Math.max(activeIdx-1, 0);
      highlightActive();
    } else if(e.key === "Enter"){
      if(activeIdx >= 0 && currentMatches[activeIdx]){
        selectStock(currentMatches[activeIdx].code);
      } else if(currentMatches.length){
        selectStock(currentMatches[0].code);
      }
    } else if(e.key === "Escape"){
      closeDropdown();
    }
  });
  function highlightActive(){
    Array.prototype.forEach.call($dropdown.querySelectorAll(".dd-item"), function(el, i){
      el.classList.toggle("active", i === activeIdx);
    });
  }
  document.addEventListener("click", function(e){
    if(!e.target.closest(".search-row")) closeDropdown();
  });

  function selectStock(code){
    closeDropdown();
    $search.value = "";
    $search.blur();
    loadAndRender(code);
  }

  // ---------------------------------------------------------------
  // number formatting
  // ---------------------------------------------------------------
  function fmtMoney(v){
    if(v === null || v === undefined) return "—";
    return Math.round(v).toLocaleString("en-US");
  }
  function fmtPct(v, nd){
    if(v === null || v === undefined) return "—";
    return v.toFixed(nd===undefined?1:nd) + "%";
  }
  function fmtNum(v, nd){
    if(v === null || v === undefined) return "—";
    return v.toFixed(nd===undefined?2:nd);
  }

  // ---------------------------------------------------------------
  // chart engine (hand-rolled inline SVG, no dependency)
  // ---------------------------------------------------------------
  var SVGNS = "http://www.w3.org/2000/svg";
  function el(tag, attrs){
    var e = document.createElementNS(SVGNS, tag);
    for(var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function niceStep(rough){
    var pow = Math.pow(10, Math.floor(Math.log10(rough)));
    var f = rough / pow;
    var nf = f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10;
    return nf * pow;
  }
  function niceTicks(min, max, count){
    if(min === max){ min -= 1; max += 1; }
    var range = max - min;
    var step = niceStep(range / count);
    var niceMin = Math.floor(min / step) * step;
    var niceMax = Math.ceil(max / step) * step;
    var ticks = [];
    for(var v = niceMin; v <= niceMax + step*0.001; v += step) ticks.push(Math.round(v*1e6)/1e6);
    return { min: niceMin, max: niceMax, ticks: ticks };
  }

  var tooltipEl = __id("tooltip");
  function showTooltip(x, y, html){
    tooltipEl.innerHTML = html;
    tooltipEl.style.left = x + "px";
    tooltipEl.style.top = (y - 10) + "px";
    tooltipEl.classList.add("show");
  }
  function hideTooltip(){ tooltipEl.classList.remove("show"); }

  var W = 600, PAD_L = 8, PAD_R = 46, PAD_T = 10, PAD_B = 26;

  function baseSvg(h){
    var svg = el("svg", { viewBox: "0 0 " + W + " " + h, preserveAspectRatio:"none" });
    return svg;
  }

  function pickLabelStride(n, maxLabels){
    return Math.max(1, Math.ceil(n / maxLabels));
  }

  // oldest->newest ordering for plotting (source arrays are newest-first)
  function chrono(arr){
    return arr.slice().reverse();
  }
  // keep only the most recent N periods (still newest-first input), then flip to oldest->newest
  var RECENT_QUARTERS = 20;  // 最近5年(20季)
  var RECENT_MONTHS = 24;   // ~最近3年(以現況約等於最近24個月)
  function recentChrono(arr, n){
    return arr.slice(0, n).reverse();
  }

  function renderBarChart(container, opts){
    // opts: labels(oldest->newest), values(oldest->newest), unit, diverging(bool), fmt(fn), height
    var labels = opts.labels, values = opts.values;
    var h = opts.height || 190;
    var n = values.length;
    var innerW = W - PAD_L - PAD_R, innerH = h - PAD_T - PAD_B;

    var nums = values.filter(function(v){ return v !== null && v !== undefined; });
    var minV = Math.min(0, nums.length? Math.min.apply(null, nums) : 0);
    var maxV = Math.max(0, nums.length? Math.max.apply(null, nums) : 1);
    var t = niceTicks(minV, maxV, 4);
    var y0 = t.min, y1 = t.max;
    var yScale = function(v){ return PAD_T + innerH - (v - y0) / (y1 - y0) * innerH; };
    var zeroY = yScale(0);

    var svg = baseSvg(h);
    var accent = cssVar("--accent"), good = cssVar("--good"), crit = cssVar("--critical"), grid = cssVar("--grid"), muted = cssVar("--muted"), baseline = cssVar("--baseline");

    t.ticks.forEach(function(tv){
      var y = yScale(tv);
      svg.appendChild(el("line", {x1:PAD_L, x2:W-PAD_R, y1:y, y2:y, stroke:grid, "stroke-width":1}));
      var txt = el("text", {x:W-PAD_R+6, y:y+3, "text-anchor":"start", "font-size":12, fill:muted, "font-family":"IBM Plex Mono, monospace"});
      txt.textContent = compactNumber(tv);
      svg.appendChild(txt);
    });
    svg.appendChild(el("line", {x1:PAD_L, x2:W-PAD_R, y1:zeroY, y2:zeroY, stroke:baseline, "stroke-width":1}));

    var bw = innerW / n;
    var barW = Math.max(1.5, bw * 0.62);
    var stride = pickLabelStride(n, 9);

    var hitAreas = [];
    for(var i=0;i<n;i++){
      var v = values[i];
      var cx = PAD_L + bw*i + bw/2;
      if(v !== null && v !== undefined){
        var y = yScale(v);
        var top = Math.min(y, zeroY), barH = Math.max(1, Math.abs(y - zeroY));
        var color = opts.diverging ? (v >= 0 ? good : crit) : accent;
        var r = Math.min(4, barW/2, barH);
        var rect = el("rect", {
          x: cx - barW/2, y: top, width: barW, height: barH,
          fill: color, rx: r, ry: r
        });
        svg.appendChild(rect);
      }
      if(i % stride === 0 || i === n-1){
        var lb = el("text", {x:cx, y:h-6, "text-anchor":"middle", "font-size":12, fill:muted, "font-family":"IBM Plex Mono, monospace"});
        lb.textContent = labels[i];
        svg.appendChild(lb);
      }
      hitAreas.push({x:PAD_L+bw*i, w:bw, i:i});
    }

    var hitRect = el("rect", {x:PAD_L, y:0, width: innerW, height:h, fill:"transparent"});
    svg.appendChild(hitRect);
    attachHover(svg, container, hitAreas, function(i){
      var v = values[i];
      return { label: labels[i], html: labels[i] + '<br><b>' + (opts.fmt? opts.fmt(v) : fmtNum(v)) + (opts.unit? (' ' + opts.unit) : '') + '</b>' };
    });

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function compactNumber(v){
    var av = Math.abs(v);
    if(av >= 1000000) return (v/1000000).toFixed(1) + "M";
    if(av >= 1000) return (v/1000).toFixed(0) + "k";
    if(av !== 0 && av < 1) return v.toFixed(2);
    return Math.round(v).toString();
  }

  function renderLineChart(container, opts){
    // opts: labels, series:[{values, color, name}], height, fmt, unit
    var labels = opts.labels;
    var h = opts.height || 190;
    var n = labels.length;
    var innerW = W - PAD_L - PAD_R, innerH = h - PAD_T - PAD_B;

    var allNums = [];
    opts.series.forEach(function(s){ s.values.forEach(function(v){ if(v!==null && v!==undefined) allNums.push(v); }); });
    var minV = allNums.length? Math.min.apply(null, allNums) : 0;
    var maxV = allNums.length? Math.max.apply(null, allNums) : 1;
    if(opts.zeroBase) minV = Math.min(0, minV);
    var t = niceTicks(minV, maxV, 4);
    var yScale = function(v){ return PAD_T + innerH - (v - t.min) / (t.max - t.min) * innerH; };
    var xScale = function(i){ return n<=1 ? PAD_L+innerW/2 : PAD_L + innerW * i/(n-1); };

    var svg = baseSvg(h);
    var grid = cssVar("--grid"), muted = cssVar("--muted"), baseline = cssVar("--baseline");

    t.ticks.forEach(function(tv){
      var y = yScale(tv);
      svg.appendChild(el("line", {x1:PAD_L, x2:W-PAD_R, y1:y, y2:y, stroke:grid, "stroke-width":1}));
      var txt = el("text", {x:W-PAD_R+6, y:y+3, "text-anchor":"start", "font-size":12, fill:muted, "font-family":"IBM Plex Mono, monospace"});
      txt.textContent = compactNumber(tv);
      svg.appendChild(txt);
    });
    if(t.min < 0 && t.max > 0){
      svg.appendChild(el("line", {x1:PAD_L, x2:W-PAD_R, y1:yScale(0), y2:yScale(0), stroke:baseline, "stroke-width":1}));
    }

    var stride = pickLabelStride(n, 9);
    for(var i=0;i<n;i++){
      if(i % stride === 0 || i === n-1){
        var lb = el("text", {x:xScale(i), y:h-6, "text-anchor":"middle", "font-size":12, fill:muted, "font-family":"IBM Plex Mono, monospace"});
        lb.textContent = labels[i];
        svg.appendChild(lb);
      }
    }

    opts.series.forEach(function(s){
      var d = "";
      var started = false;
      for(var i=0;i<n;i++){
        var v = s.values[i];
        if(v === null || v === undefined){ started = false; continue; }
        var x = xScale(i), y = yScale(v);
        d += (started ? "L" : "M") + x.toFixed(2) + "," + y.toFixed(2) + " ";
        started = true;
      }
      svg.appendChild(el("path", {d:d, fill:"none", stroke:s.color, "stroke-width":2, "stroke-linejoin":"round", "stroke-linecap":"round"}));
      // emphasize last point
      for(var j=n-1;j>=0;j--){
        if(s.values[j] !== null && s.values[j] !== undefined){
          svg.appendChild(el("circle", {cx:xScale(j), cy:yScale(s.values[j]), r:3, fill:s.color}));
          break;
        }
      }
    });

    var hitAreas = [];
    var stepW = n>1 ? innerW/(n-1) : innerW;
    for(var k=0;k<n;k++) hitAreas.push({x: xScale(k)-stepW/2, w: stepW, i:k});

    var hitRect = el("rect", {x:PAD_L, y:0, width: innerW, height:h, fill:"transparent"});
    svg.appendChild(hitRect);
    attachHover(svg, container, hitAreas, function(i){
      var lines = opts.series.map(function(s){
        var v = s.values[i];
        return '<span style="color:'+s.color+'">●</span> ' + (s.name? s.name+': ' : '') + (opts.fmt? opts.fmt(v) : fmtNum(v)) + (opts.unit? (' '+opts.unit):'');
      }).join("<br>");
      return { label: labels[i], html: labels[i] + '<br>' + lines };
    });

    container.innerHTML = "";
    container.appendChild(svg);
  }

  function attachHover(svg, container, hitAreas, tooltipFn){
    function handleMove(clientX, clientY, svgX){
      var found = null;
      for(var i=0;i<hitAreas.length;i++){
        var ha = hitAreas[i];
        if(svgX >= ha.x && svgX <= ha.x + ha.w){ found = ha.i; break; }
      }
      if(found === null){ hideTooltip(); return; }
      var info = tooltipFn(found);
      showTooltip(clientX, clientY, info.html);
    }
    function toSvgX(clientX){
      var rect = svg.getBoundingClientRect();
      var relX = (clientX - rect.left) / rect.width;
      return relX * W;
    }
    svg.addEventListener("mousemove", function(e){
      handleMove(e.clientX, e.clientY, toSvgX(e.clientX));
    });
    svg.addEventListener("mouseleave", hideTooltip);
    svg.addEventListener("touchstart", function(e){
      var touch = e.touches[0];
      handleMove(touch.clientX, touch.clientY, toSvgX(touch.clientX));
    }, {passive:true});
    svg.addEventListener("touchmove", function(e){
      var touch = e.touches[0];
      handleMove(touch.clientX, touch.clientY, toSvgX(touch.clientX));
      e.preventDefault();
    }, {passive:false});
    svg.addEventListener("touchend", hideTooltip);
  }

  // ---------------------------------------------------------------
  // section / card builders
  // ---------------------------------------------------------------
  function card(title, unit, latestHtml){
    var d = document.createElement("div");
    d.className = "card";
    d.innerHTML =
      '<div class="chead"><span class="ctitle">'+title+'</span><span class="cunit">'+(unit||"")+'</span></div>' +
      (latestHtml ? '<div class="clatest">'+latestHtml+'</div>' : '') +
      '<div class="chart-box"></div>';
    return d;
  }

  function latestValueHtml(values, fmt, dates){
    // values/dates are newest-first: the latest valid value is the first non-null from index 0
    var idx = -1;
    for(var i=0;i<values.length;i++){ if(values[i]!==null && values[i]!==undefined){ idx = i; break; } }
    if(idx === -1) return "—";
    var d = dates && dates[idx] ? '<span class="d">'+dates[idx]+'</span>' : "";
    return fmt(values[idx]) + d;
  }

  function group(title, count){
    var s = document.createElement("section");
    s.className = "grp";
    s.innerHTML = '<div class="grp-title"><h2>'+title+'</h2><span class="n">'+count+' 圖</span></div><div class="grid"></div>';
    return s;
  }

  // ---------------------------------------------------------------
  // main render
  // ---------------------------------------------------------------
  function kpiHtml(label, value, cls){
    return '<div class="kpi"><div class="lbl">'+label+'</div><div class="val'+(cls?(' '+cls):'')+'">'+value+'</div></div>';
  }
  function kpiLinkHtml(label, href, linkText){
    return '<a class="kpi kpi-link" href="'+href+'" target="_blank" rel="noopener noreferrer">'+
      '<div class="lbl">'+label+'</div><div class="val link">'+linkText+'</div></a>';
  }
  function kpiPriceHtml(label, value, dateStr, href){
    var valHtml = value!==null? fmtNum(value,2)+' 元' : '—';
    var dateHtml = dateStr? ' <span class="d">'+dateStr+'</span>' : '';
    return '<a class="kpi kpi-link" href="'+href+'" target="_blank" rel="noopener noreferrer">'+
      '<div class="lbl">'+label+'</div><div class="val">'+valHtml+dateHtml+'</div></a>';
  }

  function lastValid(arr){
    for(var i=0;i<arr.length;i++) if(arr[i]!==null && arr[i]!==undefined) return arr[i];
    return null;
  }

  function render(code, meta, rec){
    __id("stockHead").hidden = false;
    __id("kpis").hidden = false;
    __id("stockName").textContent = meta.name || code;
    __id("stockCode").textContent = code;
    __id("stockInd").textContent = meta.ind || "";

    QLABELS = rec.QL; MLABELS = rec.ML;
    var qLabels = recentChrono(QLABELS, RECENT_QUARTERS);
    var mRevLabels = recentChrono(MLABELS.rev, RECENT_MONTHS);
    var mPriceLabels = recentChrono(MLABELS.price, RECENT_MONTHS).map(function(s){ return s.length>7 ? s.slice(0,7) : s; });

    var d = rec.d;
    var eps_q = recentChrono(d.eps_q, RECENT_QUARTERS), eps4_q = recentChrono(d.eps4_q, RECENT_QUARTERS), eps4_yoy_q = recentChrono(d.eps4_yoy_q, RECENT_QUARTERS);
    var opm_q = recentChrono(d.opm_q, RECENT_QUARTERS), opinc_q = recentChrono(d.opinc_q, RECENT_QUARTERS), opinc_yoy_q = recentChrono(d.opinc_yoy_q, RECENT_QUARTERS);
    var price_m = recentChrono(d.price_m, RECENT_MONTHS), rev_m = recentChrono(d.rev_m, RECENT_MONTHS), rev_yoy_m = recentChrono(d.rev_yoy_m, RECENT_MONTHS);
    var rev_yoy3_m = recentChrono(d.rev_yoy3_m, RECENT_MONTHS), rev_yoy12_m = recentChrono(d.rev_yoy12_m, RECENT_MONTHS);
    var inv_q = recentChrono(d.inv_q, RECENT_QUARTERS), inv_turn_q = recentChrono(d.inv_turn_q, RECENT_QUARTERS), inv_rev_ratio_q = recentChrono(d.inv_rev_ratio_q, RECENT_QUARTERS);
    var cl_q = recentChrono(d.cl_q, RECENT_QUARTERS), cl_rev_ratio_q = recentChrono(d.cl_rev_ratio_q, RECENT_QUARTERS), cl_capital_ratio_q = recentChrono(d.cl_capital_ratio_q, RECENT_QUARTERS);
    var capex_q = recentChrono(d.capex_q, RECENT_QUARTERS), capex_cap_ratio_q = recentChrono(d.capex_cap_ratio_q, RECENT_QUARTERS), roa_q = recentChrono(d.roa_q, RECENT_QUARTERS);
    var capital_q = recentChrono(d.capital_q, RECENT_QUARTERS), retained_q = recentChrono(d.retained_q, RECENT_QUARTERS);
    var apic_q = recentChrono(d.apic_q, RECENT_QUARTERS), retained_apic_ratio_q = recentChrono(d.retained_apic_ratio_q, RECENT_QUARTERS);

    // KPI strip
    var kpiEl = __id("kpis");
    var lrYoy = lastValid(d.rev_yoy_m), leYoy = lastValid(d.eps4_yoy_q), lopm = lastValid(d.opm_q);
    kpiEl.innerHTML =
      kpiPriceHtml("最新收盤價", d.price_latest, d.price_latest_date, "https://tw.stock.yahoo.com/quote/"+encodeURIComponent(code)) +
      kpiHtml("單月營收年增率", lrYoy!==null? fmtPct(lrYoy): "—", lrYoy>0?"up":lrYoy<0?"down":"") +
      kpiHtml("四季EPS年增率", leYoy!==null? fmtPct(leYoy): "—", leYoy>0?"up":leYoy<0?"down":"") +
      kpiHtml("最新營益率", lopm!==null? fmtPct(lopm): "—");

    var main = __id("main");
    main.innerHTML = "";

    // --- group 1: EPS ---
    var g1 = group("獲利能力(近五年)", 3);
    var grid1 = g1.querySelector(".grid");
    var c1 = card("單季EPS", "元", latestValueHtml(d.eps_q, function(v){return fmtNum(v,2);}, QLABELS));
    grid1.appendChild(c1);
    renderBarChart(c1.querySelector(".chart-box"), {labels:qLabels, values:eps_q, fmt:function(v){return fmtNum(v,2);}, unit:"元"});
    var c2 = card("四季EPS", "元", latestValueHtml(d.eps4_q, function(v){return fmtNum(v,2);}, QLABELS));
    grid1.appendChild(c2);
    renderBarChart(c2.querySelector(".chart-box"), {labels:qLabels, values:eps4_q, fmt:function(v){return fmtNum(v,2);}, unit:"元"});
    var c3 = card("四季EPS年增率", "%", latestValueHtml(d.eps4_yoy_q, function(v){return fmtPct(v);}, QLABELS));
    grid1.appendChild(c3);
    renderBarChart(c3.querySelector(".chart-box"), {labels:qLabels, values:eps4_yoy_q, diverging:true, fmt:fmtPct, unit:""});

    // --- group 2: 營運 ---
    var g2 = group("營運與獲利率(近五年)", 3);
    var grid2 = g2.querySelector(".grid");
    var c4 = card("單季營業利益", "百萬元", latestValueHtml(d.opinc_q, fmtMoney, QLABELS));
    grid2.appendChild(c4);
    renderBarChart(c4.querySelector(".chart-box"), {labels:qLabels, values:opinc_q, fmt:fmtMoney, unit:"百萬"});
    var c5 = card("營業利益年增率", "%", latestValueHtml(d.opinc_yoy_q, fmtPct, QLABELS));
    grid2.appendChild(c5);
    renderBarChart(c5.querySelector(".chart-box"), {labels:qLabels, values:opinc_yoy_q, diverging:true, fmt:fmtPct, unit:""});
    var c6 = card("營益率", "%", latestValueHtml(d.opm_q, fmtPct, QLABELS));
    grid2.appendChild(c6);
    renderLineChart(c6.querySelector(".chart-box"), {labels:qLabels, series:[{values:opm_q, color:cssVar("--accent")}], fmt:fmtPct, unit:""});

    // --- group 2b: 資本結構與保留盈餘 ---
    var g2b = group("資本結構與保留盈餘(近五年)", 4);
    var grid2b = g2b.querySelector(".grid");
    var c2b1 = card("(保留盈餘+資本公積)比例", "%", latestValueHtml(d.retained_apic_ratio_q, fmtPct, QLABELS));
    grid2b.appendChild(c2b1);
    renderLineChart(c2b1.querySelector(".chart-box"), {labels:qLabels, series:[{values:retained_apic_ratio_q, color:cssVar("--accent")}], fmt:fmtPct, unit:""});
    var c2b2 = card("保留盈餘", "百萬元", latestValueHtml(d.retained_q, fmtMoney, QLABELS));
    grid2b.appendChild(c2b2);
    renderBarChart(c2b2.querySelector(".chart-box"), {labels:qLabels, values:retained_q, fmt:fmtMoney, unit:"百萬"});
    var c2b3 = card("資本公積", "百萬元", latestValueHtml(d.apic_q, fmtMoney, QLABELS));
    grid2b.appendChild(c2b3);
    renderBarChart(c2b3.querySelector(".chart-box"), {labels:qLabels, values:apic_q, fmt:fmtMoney, unit:"百萬"});
    var c2b4 = card("股本", "百萬元", latestValueHtml(d.capital_q, fmtMoney, QLABELS));
    grid2b.appendChild(c2b4);
    renderBarChart(c2b4.querySelector(".chart-box"), {labels:qLabels, values:capital_q, fmt:fmtMoney, unit:"百萬"});
    var noteCard = document.createElement("div");
    noteCard.className = "card note-card";
    noteCard.innerHTML =
      '<div class="chead"><span class="ctitle">WACC（加權平均資本成本）</span></div>' +
      '<p>WACC 不好算，參考國外網站比較快。資產負債表上的「保留盈餘」只是過去戰果的堆積。要分辨這筆錢的性質，我們必須從靜態的「存量」轉向動態的「增量」。</p>' +
      '<p><b>創造價值（投資）</b>：如果增量 ROE 持續高於公司的加權平均資本成本（WACC），這筆錢就是「創造獲利的投資」，代表公司在進行複利滾動。</p>' +
      '<p><b>紅后效應（維護）</b>：如果公司留了很多錢，但 EPS 只是原地踏步、或增量 ROE 低於 WACC，這就是為了「維持競爭力」而不得不花的錢。</p>';
    g2b.appendChild(noteCard);

    // --- group 3: 月營收與股價 ---
    var g3 = group("月營收與股價(近兩年)", 4);
    var grid3 = g3.querySelector(".grid");
    var c8 = card("單月營收", "百萬元", latestValueHtml(d.rev_m, fmtMoney, MLABELS.rev));
    grid3.appendChild(c8);
    renderBarChart(c8.querySelector(".chart-box"), {labels:mRevLabels, values:rev_m, fmt:fmtMoney, unit:"百萬"});
    var c9 = card("單月營收年增率", "%", latestValueHtml(d.rev_yoy_m, fmtPct, MLABELS.rev));
    grid3.appendChild(c9);
    renderLineChart(c9.querySelector(".chart-box"), {labels:mRevLabels, series:[{values:rev_yoy_m, color:cssVar("--accent")}], zeroBase:true, fmt:fmtPct, unit:""});
    var c7 = card("月營收公告日股價", "元", latestValueHtml(d.price_m, function(v){return fmtNum(v,1);}, MLABELS.price));
    grid3.appendChild(c7);
    renderLineChart(c7.querySelector(".chart-box"), {labels:mPriceLabels, series:[{values:price_m, color:cssVar("--accent")}], fmt:function(v){return fmtNum(v,1);}, unit:"元"});
    var c10 = card("3月／12月營收年增率", "%");
    c10.querySelector(".chead").insertAdjacentHTML("afterend",
      '<div class="legend"><span><span class="sw" style="background:'+cssVar("--accent")+'"></span>3個月累計年增率</span>'+
      '<span><span class="sw" style="background:'+cssVar("--accent-2")+'"></span>12個月累計年增率</span></div>');
    grid3.appendChild(c10);
    renderLineChart(c10.querySelector(".chart-box"), {labels:mRevLabels, series:[
      {values:rev_yoy3_m, color:cssVar("--accent"), name:"3月"},
      {values:rev_yoy12_m, color:cssVar("--accent-2"), name:"12月"}
    ], zeroBase:true, fmt:fmtPct, unit:""});

    // --- group 4: 存貨 ---
    var g4 = group("存貨(近五年)", 3);
    var grid4 = g4.querySelector(".grid");
    var c11 = card("單季存貨", "百萬元", latestValueHtml(d.inv_q, fmtMoney, QLABELS));
    grid4.appendChild(c11);
    renderBarChart(c11.querySelector(".chart-box"), {labels:qLabels, values:inv_q, fmt:fmtMoney, unit:"百萬"});
    var c12 = card("存貨周轉率", "次", latestValueHtml(d.inv_turn_q, function(v){return fmtNum(v,3);}, QLABELS));
    grid4.appendChild(c12);
    renderLineChart(c12.querySelector(".chart-box"), {labels:qLabels, series:[{values:inv_turn_q, color:cssVar("--accent")}], fmt:function(v){return fmtNum(v,3);}, unit:""});
    var c13 = card("存貨營收比", "%", latestValueHtml(d.inv_rev_ratio_q, fmtPct, QLABELS));
    grid4.appendChild(c13);
    renderLineChart(c13.querySelector(".chart-box"), {labels:qLabels, series:[{values:inv_rev_ratio_q, color:cssVar("--accent")}], fmt:fmtPct, unit:""});

    // --- group 5: 合約負債 ---
    var g5 = group("合約負債(近五年)", 3);
    var grid5 = g5.querySelector(".grid");
    var c14 = card("單季合約負債(全部)", "百萬元", latestValueHtml(d.cl_q, fmtMoney, QLABELS));
    grid5.appendChild(c14);
    renderBarChart(c14.querySelector(".chart-box"), {labels:qLabels, values:cl_q, fmt:fmtMoney, unit:"百萬"});
    var c15 = card("合約負債年增額佔四季營收比", "%", latestValueHtml(d.cl_rev_ratio_q, fmtPct, QLABELS));
    grid5.appendChild(c15);
    renderLineChart(c15.querySelector(".chart-box"), {labels:qLabels, series:[{values:cl_rev_ratio_q, color:cssVar("--accent")}], zeroBase:true, fmt:fmtPct, unit:""});
    var c16 = card("合約負債佔股本比", "%", latestValueHtml(d.cl_capital_ratio_q, fmtPct, QLABELS));
    grid5.appendChild(c16);
    renderLineChart(c16.querySelector(".chart-box"), {labels:qLabels, series:[{values:cl_capital_ratio_q, color:cssVar("--accent")}], fmt:fmtPct, unit:""});

    // --- group 6: 資本支出 / ROA ---
    var g6 = group("資本支出與資產報酬(近五年)", 3);
    var grid6 = g6.querySelector(".grid");
    var c17 = card("單季取得不動產廠房設備", "百萬元", latestValueHtml(d.capex_q, fmtMoney, QLABELS));
    grid6.appendChild(c17);
    renderBarChart(c17.querySelector(".chart-box"), {labels:qLabels, values:capex_q, fmt:fmtMoney, unit:"百萬"});
    var c18 = card("資本支出(四季)佔股本比", "%", latestValueHtml(d.capex_cap_ratio_q, fmtPct, QLABELS));
    grid6.appendChild(c18);
    renderLineChart(c18.querySelector(".chart-box"), {labels:qLabels, series:[{values:capex_cap_ratio_q, color:cssVar("--accent")}], fmt:fmtPct, unit:""});
    var c19 = card("四季ROA", "%", latestValueHtml(d.roa_q, fmtPct, QLABELS));
    grid6.appendChild(c19);
    renderLineChart(c19.querySelector(".chart-box"), {labels:qLabels, series:[{values:roa_q, color:cssVar("--accent")}], fmt:fmtPct, unit:""});

    // --- group 7: 月營收變動說明 ---
    var g7 = group("月營收變動說明", 1);
    var notesCard = document.createElement("div");
    notesCard.className = "card notes-card";
    var notesLabels = MLABELS.notes;
    var rows = "";
    var count = Math.min(12, notesLabels.length - 12);
    for(var i=0;i<count;i++){
      var curDate = notesLabels[i], lyDate = notesLabels[i+12];
      var curText = d.notes[String(i)] || "-";
      var lyText = d.notes[String(i+12)] || "-";
      rows += '<div class="notes-row">' +
        '<div class="notes-cell"><span class="nd">'+curDate+'</span><span class="nt'+(curText==="-"?" dim":"")+'">'+escapeHtml(curText)+'</span></div>' +
        '<div class="notes-cell"><span class="nd">'+lyDate+'</span><span class="nt'+(lyText==="-"?" dim":"")+'">'+escapeHtml(lyText)+'</span></div>' +
      '</div>';
    }
    notesCard.innerHTML = '<div class="notes-head"><span style="padding-left:14px">當期公告說明</span><span style="padding-left:14px">去年同期公告說明</span></div>' + rows;
    g7.querySelector(".grid").replaceWith(notesCard);
    main.appendChild(g3);
    main.appendChild(g7);
    main.appendChild(g1);
    main.appendChild(g2);
    main.appendChild(g2b);
    main.appendChild(g4);
    main.appendChild(g5);
    main.appendChild(g6);
  }

  function loadAndRender(code){
    var meta = META[code];
    if(!meta){
      __id("main").innerHTML = '<div class="loading-note">找不到代號 '+escapeHtml(code)+' 的資料</div>';
      return;
    }
    __id("main").innerHTML = '<div class="loading-note">載入 '+escapeHtml(meta.name||code)+' 資料中…</div>';
    getRecord(code).then(function(rec){
      if(!rec){
        __id("main").innerHTML = '<div class="loading-note">代號 '+escapeHtml(code)+' 暫無基本面資料</div>';
        return;
      }
      render(code, meta, rec);
    }).catch(function(err){
      __id("main").innerHTML = '<div class="loading-note">資料載入失敗，請重新整理頁面再試一次</div>';
      console.error(err);
    });
  }

  // ---------------------------------------------------------------
  // boot
  // ---------------------------------------------------------------
  Promise.all([
    loadJSON("meta.json"),
    loadJSON("quarter_labels.json"),
    loadJSON("month_labels.json")
  ]).then(function(results){
    META = results[0]; QLABELS = results[1]; MLABELS = results[2];
    buildIndex();
    var initial = "2330";
    if(!META[initial]) initial = "2330";
    loadAndRender(initial);
  }).catch(function(err){
    __id("main").innerHTML = '<div class="loading-note">資料索引載入失敗，請重新整理頁面再試一次</div>';
    console.error(err);
  });
})();

};

/* ── t4 ← BG 04chip ── */
CF_MODS["t4"] = function(ROOT, API){
var PFX = "m4-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

(function(){
  var STATE = { stocks: [], filtered: [], sortKey:'c', sortDir:1, page:1, pageSize:50, dayIdx:0, dates:[], backtestDays:20, view:'day' };

  // 原檔「全上市櫃現況」裡還有以下 8 組參數：扣掉大戶之20日周轉率、外資投信周轉率、
  // 買盤比例減賣盤比例20日、買盤比例減賣盤比例60日，以及這 4 項各自的「20日增減」版本。
  // 為了避免試用版介面參數過多讓使用者混亂，這 8 組不開放使用者輸入，固定寫死為 -9999
  // （等同原檔「不納入該條件」的寫法），永遠不會排除任何個股。
  var DISABLED_PARAMS = {
    turnover_ex_holder_20d: -9999,        // 扣掉大戶之20日周轉率
    turnover_foreign_trust: -9999,        // 外資投信周轉率
    buy_sell_ratio_20d: -9999,            // 買盤比例減賣盤比例20日
    buy_sell_ratio_60d: -9999,            // 買盤比例減賣盤比例60日
    turnover_ex_holder_20d_chg20d: -9999, // 扣掉大戶之20日周轉率的20日增減
    turnover_foreign_trust_chg20d: -9999, // 外資投信周轉率的20日增減
    buy_sell_ratio_20d_chg20d: -9999,     // 買盤比例減賣盤比例20日的20日增減
    buy_sell_ratio_60d_chg20d: -9999      // 買盤比例減賣盤比例60日的20日增減
  };

  var $ = function(id){ return __id(id); };

  function validDay(v){
    var n = Number(v);
    return (v!=='' && Number.isInteger(n) && n>=1 && n<=60) ? n : null;
  }

  function fmtNum(v, digits){
    if(v===null || v===undefined || Number.isNaN(v)) return '—';
    return Number(v).toLocaleString('zh-TW', {minimumFractionDigits:digits||0, maximumFractionDigits:digits||0});
  }

  // 回測彙總表格子空間很擠（要塞20欄），不用千分位逗號，省下的寬度換成看得到更多天
  function fmtCompact(v, digits){
    if(v===null || v===undefined || Number.isNaN(v)) return '';
    return Number(v).toFixed(digits==null?2:digits);
  }

  function fmtDate(iso){
    if(!iso) return '—';
    var p = iso.split('-');
    return (p[1]|0) + '/' + (p[2]|0);
  }

  // 回測欄位一律讀依日期索引的 _h 陣列；dayIdx=0 是最新一天（跟舊版單日邏輯完全一致）
  var FIELD_MAP = { price:'price_h', wr:'wr_h', xr:'xr_h', yr:'yr_h', z:'z_h', hr:'hr_h' };
  function valueAt(s, key, dayIdx){
    if(key==='hp') return s.hp_h ? s.hp_h[dayIdx] : null;
    if(key==='sh') return s.sh_h ? s.sh_h[dayIdx] : null;
    if(key==='c' || key==='n') return s[key];
    var arr = s[FIELD_MAP[key]];
    return arr ? arr[dayIdx] : null;
  }

  function passesFilters(s, dayIdx){
    var v;

    var hr = valueAt(s,'hr',dayIdx), z = valueAt(s,'z',dayIdx), wr = valueAt(s,'wr',dayIdx),
        xr = valueAt(s,'xr',dayIdx), yr = valueAt(s,'yr',dayIdx);

    v = $('hr_top').value; if(v!==''){ if(!(hr!=null && hr <= Number(v))) return false; }
    v = $('z_min').value; if(v!==''){ if(!(z!=null && z >= Number(v))) return false; }

    var hp0 = valueAt(s,'hp',dayIdx);
    v = $('hp_min').value; if(v!==''){ if(!(hp0!=null && hp0 >= Number(v))) return false; }
    var hpTrendVal = $('hp_trend_val').value;
    var hpDay = validDay($('hp_trend_n').value);
    if(hpTrendVal!=='' && hpDay!==null){
      var need = Number(hpTrendVal);
      var hpN = valueAt(s,'hp',dayIdx+hpDay);
      if(hp0==null || hpN==null) return false;
      if(!(hp0-hpN >= need)) return false;
    }
    var shDay = validDay($('sh_down_n').value);
    if(shDay!==null){
      var sh0 = valueAt(s,'sh',dayIdx), shN = valueAt(s,'sh',dayIdx+shDay);
      if(sh0==null || shN==null) return false;
      if(!(sh0 < shN)) return false;
    }

    v = $('r1_max').value; if(v!==''){ if(!(wr!=null && wr <= Number(v))) return false; }
    v = $('r2_max').value; if(v!==''){ if(!(xr!=null && xr <= Number(v))) return false; }
    v = $('r3_max').value; if(v!==''){ if(!(yr!=null && yr <= Number(v))) return false; }

    return true;
  }

  function runFilter(){
    STATE.filtered = STATE.stocks.filter(function(s){ return passesFilters(s, STATE.dayIdx); });
    STATE.page = 1;
    sortFiltered();
    render();
    if(STATE.view==='backtest') renderBacktest();
  }

  function sortFiltered(){
    var key = STATE.sortKey, dir = STATE.sortDir;
    STATE.filtered.sort(function(a,b){
      var av = valueAt(a,key,STATE.dayIdx), bv = valueAt(b,key,STATE.dayIdx);
      if(av===null||av===undefined) av = (typeof bv==='number') ? Infinity : '';
      if(bv===null||bv===undefined) bv = (typeof av==='number') ? Infinity : '';
      if(av<bv) return -1*dir;
      if(av>bv) return 1*dir;
      return 0;
    });
  }

  function render(){
    $('matchCount').textContent = STATE.filtered.length.toLocaleString('zh-TW');
    $('totalCount').textContent = STATE.stocks.length.toLocaleString('zh-TW');
    $('dayLabelText').textContent = STATE.dates.length ? ('（篩選日：' + fmtDate(STATE.dates[STATE.dayIdx]) + '）') : '';

    var pages = Math.max(1, Math.ceil(STATE.filtered.length / STATE.pageSize));
    if(STATE.page>pages) STATE.page = pages;
    $('pageInfo').textContent = '第 ' + STATE.page + ' / ' + pages + ' 頁';
    $('prevPage').disabled = STATE.page<=1;
    $('nextPage').disabled = STATE.page>=pages;

    var start = (STATE.page-1)*STATE.pageSize;
    var slice = STATE.filtered.slice(start, start+STATE.pageSize);
    var body = $('resultBody');

    if(slice.length===0){
      body.innerHTML = '<tr><td colspan="10" class="empty">沒有符合條件的個股，試著放寬篩選門檻。</td></tr>';
      return;
    }

    var html = slice.map(function(s){
      return '<tr>'+
        '<td class="code num">'+s.c+'</td>'+
        '<td class="name">'+s.n+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'price',STATE.dayIdx),2)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'wr',STATE.dayIdx),0)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'xr',STATE.dayIdx),0)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'yr',STATE.dayIdx),0)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'hp',STATE.dayIdx),2)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'sh',STATE.dayIdx),0)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'z',STATE.dayIdx),3)+'</td>'+
        '<td class="num">'+fmtNum(valueAt(s,'hr',STATE.dayIdx),0)+'</td>'+
      '</tr>';
    }).join('');
    body.innerHTML = html;
  }

  // 20天回測彙總表：同一組篩選條件，逐一套用最近 backtestDays 天各自的資料重新篩選一次，
  // 收斂成「哪些個股在哪幾天符合過」的寬表，格子放符合當天的收盤價，沒符合就留空。
  // 點表頭某一天的日期，可以把「那一天有符合條件」的個股排到最上面（組內依代號排序），
  // 方便只看那一天的篩選結果；再點一次同一天可以還原成單純依代號排序。
  var BACKTEST = { matched: null, codesAll: [], n: 0, sortDay: null };

  function computeBacktest(){
    var n = Math.min(STATE.backtestDays, STATE.dates.length);
    var matched = {}; // code -> { s, prices: [n] }
    for(var day=0; day<n; day++){
      for(var i=0;i<STATE.stocks.length;i++){
        var s = STATE.stocks[i];
        if(!passesFilters(s, day)) continue;
        if(!matched[s.c]) matched[s.c] = { s:s, prices:new Array(n).fill(null) };
        matched[s.c].prices[day] = valueAt(s,'price',day);
      }
    }
    BACKTEST.matched = matched;
    BACKTEST.codesAll = Object.keys(matched).sort();
    BACKTEST.n = n;
  }

  function orderedBacktestCodes(){
    var matched = BACKTEST.matched, day = BACKTEST.sortDay;
    var codes = BACKTEST.codesAll.slice();
    if(day==null) return codes;
    codes.sort(function(a,b){
      var ah = matched[a].prices[day]!=null ? 0 : 1, bh = matched[b].prices[day]!=null ? 0 : 1;
      if(ah!==bh) return ah-bh;
      return a<b ? -1 : a>b ? 1 : 0;
    });
    return codes;
  }

  function renderBacktestTable(){
    var n = BACKTEST.n, matched = BACKTEST.matched, day = BACKTEST.sortDay;

    var headHtml = '<th>代號</th><th>名稱</th>' + STATE.dates.slice(0,n).map(function(d,i){
      var cls = [];
      if(i===0) cls.push('newest');
      if(i===day) cls.push('active-sort');
      return '<th'+(cls.length?' class="'+cls.join(' ')+'"':'')+' data-day="'+i+'" title="點這一天：把那天有符合條件的個股排到最上面，組內依代號排序">'+fmtDate(d)+(i===day?' ▾':'')+'</th>';
    }).join('');
    $('backtestHead').innerHTML = headHtml;
    $('backtestColgroup').innerHTML = '<col class="code"><col class="name">' + '<col>'.repeat(n);

    var codes = orderedBacktestCodes();
    if(!codes.length){
      $('backtestBody').innerHTML = '<tr><td colspan="'+(n+2)+'" class="empty">這 '+n+' 天裡沒有任何一天符合這組篩選條件的個股，試著放寬篩選門檻。</td></tr>';
      return;
    }
    var bodyHtml = codes.map(function(c){
      var m = matched[c];
      var cells = m.prices.map(function(p,i){
        var v = p!=null?fmtCompact(p,2):'';
        var cls = [];
        if(p!=null) cls.push('hit');
        if(i===day) cls.push('active-sort');
        return '<td'+(cls.length?' class="'+cls.join(' ')+'"':'')+' title="'+fmtDate(STATE.dates[i])+' '+m.s.n+' '+v+'">'+v+'</td>';
      }).join('');
      return '<tr><td class="code num" title="'+c+' '+m.s.n+'">'+c+'</td><td class="name" title="'+m.s.n+'">'+m.s.n+'</td>'+cells+'</tr>';
    }).join('');
    $('backtestBody').innerHTML = bodyHtml;

    if(day==null){
      $('backtestHint').textContent =
        '這 '+n+' 天裡共有 '+codes.length+' 檔個股至少符合過一天的篩選條件。每一欄是一個回測日，用同一組篩選條件重新計算那一天的結果；格子顯示的是「該檔股票在那一天有符合條件」時的收盤價，沒有符合就留空。依代號排序；點任一天的日期欄位，可以把那一天有符合條件的個股排到最上面。';
    } else {
      var hitCount = codes.filter(function(c){ return matched[c].prices[day]!=null; }).length;
      $('backtestHint').innerHTML =
        fmtDate(STATE.dates[day])+' 當天共有 <b>'+hitCount+'</b> 檔符合條件，已排到最上面並依代號排序；其餘個股（其他天有符合過、這天沒有）排在後面。再點一次「'+fmtDate(STATE.dates[day])+'」可還原成依代號排序。';
    }
  }

  function renderBacktest(){
    computeBacktest();
    BACKTEST.sortDay = null;
    renderBacktestTable();
  }

  function setView(v){
    STATE.view = v;
    $('tabDay').setAttribute('aria-pressed', v==='day');
    $('tabBacktest').setAttribute('aria-pressed', v==='backtest');
    $('dayView').hidden = v!=='day';
    $('dayPager').hidden = v!=='day';
    $('backtestView').hidden = v!=='backtest';
    if(v==='backtest') renderBacktest();
  }

  function wireSort(){
    ROOT.querySelectorAll('#m4-resultTable thead th').forEach(function(th){
      th.addEventListener('click', function(){
        var key = th.getAttribute('data-key');
        if(STATE.sortKey===key){ STATE.sortDir *= -1; } else { STATE.sortKey = key; STATE.sortDir = (key==='n'||key==='c') ? 1 : 1; }
        ROOT.querySelectorAll('#m4-resultTable thead th').forEach(function(t){ t.classList.remove('sorted'); });
        th.classList.add('sorted');
        sortFiltered(); STATE.page=1; render();
      });
    });
  }

  function applySample(){
    $('hr_top').value = 300;
    $('z_min').value = 0.05;
    $('hp_min').value = '';
    $('hp_trend_val').value = 0.5;
    $('hp_trend_n').value = 20;
    $('sh_down_n').value = 20;
    $('r1_max').value = 700;
    $('r2_max').value = 700;
    $('r3_max').value = 700;
    runFilter();
  }

  function resetFilters(){
    ROOT.querySelectorAll('#m4-filterForm input[type=number]').forEach(function(i){ i.value=''; });
    runFilter();
  }

  // ---------------------------------------------------------------
  // 匯出目前篩選結果（單日結果、依目前排序，非分頁裁切後的全部符合筆數）成 CSV，Excel 可直接開啟
  // ---------------------------------------------------------------
  function csvEscape(v){
    v = (v===null || v===undefined) ? '' : String(v);
    if(/[",\n]/.test(v)) v = '"' + v.replace(/"/g,'""') + '"';
    return v;
  }
  function buildCSV(headers, rows){
    var lines = [headers.map(csvEscape).join(',')];
    rows.forEach(function(r){ lines.push(r.map(csvEscape).join(',')); });
    return '﻿' + lines.join('\r\n');
  }
  async function exportResults(){
    if(!window.claude || !window.claude.use){ alert('此檢視環境不支援匯出檔案功能。'); return; }
    var downloads = await window.claude.use('downloads');
    if(!downloads){ alert('此檢視環境目前無法匯出檔案。'); return; }
    var headers = ['代號','名稱','收盤價','法人/大戶排名','量/大戶排名','法人60日排名','大戶比例%','總股東人數','買賣超/資本額','大戶人數排名'];
    var rows = STATE.filtered.map(function(s){
      return [
        s.c, s.n,
        fmtNum(valueAt(s,'price',STATE.dayIdx),2),
        fmtNum(valueAt(s,'wr',STATE.dayIdx),0),
        fmtNum(valueAt(s,'xr',STATE.dayIdx),0),
        fmtNum(valueAt(s,'yr',STATE.dayIdx),0),
        fmtNum(valueAt(s,'hp',STATE.dayIdx),2),
        fmtNum(valueAt(s,'sh',STATE.dayIdx),0),
        fmtNum(valueAt(s,'z',STATE.dayIdx),3),
        fmtNum(valueAt(s,'hr',STATE.dayIdx),0)
      ];
    });
    var dayLabel = STATE.dates.length ? STATE.dates[STATE.dayIdx] : '';
    var csv = buildCSV(headers, rows);
    try{
      await downloads.save({filename: '籌碼數據自訂篩選器_篩選結果_'+dayLabel+'.csv', data: csv});
    }catch(e){
      if(!e || e.code !== 'declined') alert('匯出失敗：'+(e && e.message ? e.message : e));
    }
  }

  $('runBtn').addEventListener('click', runFilter);
  $('sampleBtn').addEventListener('click', applySample);
  $('resetBtn').addEventListener('click', resetFilters);
  $('exportBtn').addEventListener('click', exportResults);
  $('prevPage').addEventListener('click', function(){ if(STATE.page>1){ STATE.page--; render(); } });
  $('nextPage').addEventListener('click', function(){ STATE.page++; render(); });
  $('tabDay').addEventListener('click', function(){ setView('day'); });
  $('tabBacktest').addEventListener('click', function(){ setView('backtest'); });
  $('asOfDay').addEventListener('change', function(){ STATE.dayIdx = Number(this.value) || 0; runFilter(); });
  ROOT.querySelectorAll('.backtest-toolbar .seg button').forEach(function(btn){
    btn.addEventListener('click', function(){
      var size = btn.getAttribute('data-size');
      ROOT.querySelectorAll('.backtest-toolbar .seg button').forEach(function(b){ b.setAttribute('aria-pressed', b===btn); });
      $('backtestTable').className = 'size-' + size;
    });
  });
  $('backtestHead').addEventListener('click', function(e){
    var th = e.target.closest('th[data-day]');
    if(!th || !BACKTEST.matched) return;
    var day = Number(th.getAttribute('data-day'));
    BACKTEST.sortDay = (BACKTEST.sortDay===day) ? null : day;
    renderBacktestTable();
  });
  wireSort();

  __fetch('data.json').then(function(r){ return r.json(); }).then(function(data){
    STATE.stocks = data.stocks;
    STATE.filtered = data.stocks.slice();
    STATE.dates = data.dates || [];
    STATE.backtestDays = data.backtestDays || Math.min(20, STATE.dates.length);

    var sel = $('asOfDay');
    sel.innerHTML = STATE.dates.slice(0, STATE.backtestDays).map(function(d, i){
      return '<option value="'+i+'">'+fmtDate(d)+(i===0?'（最新）':'')+'</option>';
    }).join('');

    sortFiltered();
    render();
  }).catch(function(err){
    $('resultBody').innerHTML = '<tr><td colspan="10" class="empty">資料載入失敗：'+err+'</td></tr>';
  });
})();

};

/* ── t5 ← BG 05fundscreen ── */
CF_MODS["t5"] = function(ROOT, API){
var PFX = "m5-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

(function(){
  "use strict";

  // ---------------------------------------------------------------
  // field definitions
  // ---------------------------------------------------------------
  var RANGE_GROUPS = [
    { title:"營收動能", fields:[
      { key:"rev_yoy_1m", label:"單月營收年增率", unit:"%" },
      { key:"rev_yoy_3m", label:"3月營收年增率", unit:"%" },
      { key:"rev_yoy_12m", label:"12月營收年增率", unit:"%" }
    ]},
    { title:"獲利成長", fields:[
      { key:"eps4_yoy", label:"四季EPS年增率", unit:"%" },
      { key:"opinc_yoy", label:"營業利益年增率", unit:"%" },
      { key:"eps4", label:"四季EPS", unit:"元" },
      { key:"eps_q", label:"單季EPS", unit:"元" }
    ]},
    { title:"獲利能力", fields:[
      { key:"opm", label:"營益率", unit:"%" },
      { key:"npm", label:"稅後淨利率", unit:"%" }
    ]},
    { title:"合約負債與資本支出", fields:[
      { key:"cl_rev_ratio", label:"合約負債佔四季營收比", unit:"%" },
      { key:"cl_cap_ratio", label:"合約負債佔股本比", unit:"%" },
      { key:"capex_cap_ratio", label:"資本支出佔股本比", unit:"%" }
    ]},
    { title:"規模", fields:[
      { key:"rev4q", label:"四季營收", unit:"百萬" },
      { key:"capital", label:"股本", unit:"百萬" }
    ]}
  ];

  // ---------------------------------------------------------------
  // 「篩選月」對應期別：季報依公告截止日（Q1→5/15、Q2→8/14、Q3→11/14、Q4/年報→次年3/31）、
  // 月營收依公告截止日（每月10日前公佈上個月）回推「那一天實際已公佈的最新一期」是哪一季/哪個月。
  // ---------------------------------------------------------------
  var FUND = { quarterLabels: [], monthLabels: [], monthKeys: [] };
  var fundIdxCache = {};

  function computeFundIdx(dateObj){
    var y = dateObj.getFullYear(), m = dateObj.getMonth()+1, d = dateObj.getDate();
    var q4prev = new Date(y,2,31), q1d = new Date(y,4,15), q2d = new Date(y,7,14), q3d = new Date(y,10,14);
    var qy, qq;
    if(dateObj < q4prev){ qy = y-1; qq = 3; }
    else if(dateObj < q1d){ qy = y-1; qq = 4; }
    else if(dateObj < q2d){ qy = y; qq = 1; }
    else if(dateObj < q3d){ qy = y; qq = 2; }
    else { qy = y; qq = 3; }
    var qIdx = FUND.quarterLabels.indexOf(qy + "Q" + qq);

    var back = d >= 10 ? 1 : 2;
    var my = y, mm = m - back;
    while(mm <= 0){ mm += 12; my -= 1; }
    var mIdx = FUND.monthKeys.indexOf(my*100 + mm);

    return { qIdx: qIdx<0?null:qIdx, mIdx: mIdx<0?null:mIdx };
  }
  function fundIdxForDay(dayIdx){
    if(fundIdxCache[dayIdx]) return fundIdxCache[dayIdx];
    var iso = DATES[dayIdx];
    var p = iso.split("-");
    var r = computeFundIdx(new Date(Number(p[0]), Number(p[1])-1, Number(p[2])));
    fundIdxCache[dayIdx] = r;
    return r;
  }
  function arrAt(arr, idx){ return (arr && idx!=null && arr[idx]!==undefined) ? arr[idx] : null; }

  function getValue(r, key, dayIdx){
    return API.fundVal(r.code, "ann", dayIdx, key);
    var fi = fundIdxForDay(dayIdx);
    switch(key){
      case "price": return arrAt(r.price_m, dayIdx);
      case "rev_yoy_1m": return arrAt(r.rev_yoy_1m, fi.mIdx);
      case "rev_yoy_3m": return arrAt(r.rev_yoy_3m, fi.mIdx);
      case "rev_yoy_12m": return arrAt(r.rev_yoy_12m, fi.mIdx);
      case "eps4_yoy": return arrAt(r.eps4_yoy, fi.qIdx);
      case "opinc_yoy": return arrAt(r.opinc_yoy, fi.qIdx);
      case "eps4": return arrAt(r.eps4, fi.qIdx);
      case "eps_q": return arrAt(r.eps_q, fi.qIdx);
      case "opm": return arrAt(r.opm, fi.qIdx);
      case "npm": return arrAt(r.npm, fi.qIdx);
      case "cl_rev_ratio": return arrAt(r.cl_rev_ratio, fi.qIdx);
      case "cl_cap_ratio": return arrAt(r.cl_cap_ratio, fi.qIdx);
      case "capex_cap_ratio": return arrAt(r.capex_cap_ratio, fi.qIdx);
      case "rev4q": return arrAt(r.rev4q, fi.qIdx);
      case "capital": return arrAt(r.capital, fi.qIdx);
      default: return null;
    }
  }

  var FLAGS = [
    { key:"eps4_h4", label:"四季EPS創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"eps4_h8", label:"四季EPS創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"epsq_h4", label:"單季EPS創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"epsq_h8", label:"單季EPS創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"opm_h4", label:"營益率創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"opm_h8", label:"營益率創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"npm_h4", label:"稅後淨利率創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"npm_h8", label:"稅後淨利率創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"revm_h12", label:"月營收創近12個月新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } },
    { key:"revm_h24", label:"月營收創近24個月新高", test:function(r,d){ return API.fundFlag(r.code, "ann", d, this.key); } }
  ];
  function ge(a, b){ return a !== null && a !== undefined && b !== null && b !== undefined && a >= b; }

  var TABLE_COLUMNS = [
    { key:"code", label:"代號", left:true },
    { key:"name", label:"名稱", left:true },
    { key:"ind", label:"產業", left:true },
    { key:"price", label:"收盤價", unit:"num2", get:function(r,d){ return getValue(r,"price",d); } },
    { key:"rev_yoy_1m", label:"月營收YoY", unit:"pct1", get:function(r,d){ return getValue(r,"rev_yoy_1m",d); } },
    { key:"rev_yoy_3m", label:"3月營收YoY", unit:"pct1", get:function(r,d){ return getValue(r,"rev_yoy_3m",d); } },
    { key:"eps4_yoy", label:"四季EPS YoY", unit:"pct1", get:function(r,d){ return getValue(r,"eps4_yoy",d); } },
    { key:"eps_q", label:"單季EPS", unit:"num2", get:function(r,d){ return getValue(r,"eps_q",d); } },
    { key:"opm", label:"營益率", unit:"pct1", get:function(r,d){ return getValue(r,"opm",d); } },
    { key:"npm", label:"稅後淨利率", unit:"pct1", get:function(r,d){ return getValue(r,"npm",d); } },
    { key:"capital", label:"股本(百萬)", unit:"money", get:function(r,d){ return getValue(r,"capital",d); } },
    { key:"rev4q", label:"四季營收(百萬)", unit:"money", get:function(r,d){ return getValue(r,"rev4q",d); } }
  ];

  // ---------------------------------------------------------------
  // state
  // ---------------------------------------------------------------
  var ALL = [];          // [{code, ...fields}]
  var DATES = [];        // 24個月營收公告日（最新在前）
  var BACKTEST_DAYS = 24;
  var dayIdx = 0;
  var view = "day";
  var selectedInds = null; // null = all
  var sortState = { key:null, dir:1 };
  var MAX_ROWS = 400;

  function fmtVal(v, unit){
    if(v === null || v === undefined) return "—";
    if(unit === "pct1") return v.toFixed(1) + "%";
    if(unit === "num2") return v.toFixed(2);
    if(unit === "money") return Math.round(v).toLocaleString("en-US");
    return String(v);
  }
  function fmtCompact(v, digits){
    if(v === null || v === undefined || Number.isNaN(v)) return "";
    return Number(v).toFixed(digits==null?2:digits);
  }
  function fmtDate(iso){
    if(!iso) return "—";
    var p = iso.split("-");
    return p[0].slice(2) + "/" + (p[1]|0) + "/" + (p[2]|0);
  }

  // ---------------------------------------------------------------
  // build filter UI
  // ---------------------------------------------------------------
  var rangeGroupsEl = __id("rangeGroups");
  rangeGroupsEl.innerHTML = RANGE_GROUPS.map(function(g){
    return '<h3>'+g.title+'</h3>' + g.fields.map(function(f){
      return '<div class="range-row" data-key="'+f.key+'">' +
        '<label>'+f.label+'<span class="unit">'+f.unit+'</span></label>' +
        '<div class="range-inputs">' +
          '<input type="number" class="min" data-key="'+f.key+'" data-bound="min" placeholder="最小">' +
          '<span>~</span>' +
          '<input type="number" class="max" data-key="'+f.key+'" data-bound="max" placeholder="最大">' +
        '</div></div>';
    }).join("");
  }).join("");

  var flagGroupEl = __id("flagGroup");
  flagGroupEl.innerHTML = FLAGS.map(function(f){
    return '<label class="check-row"><input type="checkbox" data-flag="'+f.key+'"> '+f.label+'</label>';
  }).join("");

  Array.prototype.forEach.call(rangeGroupsEl.querySelectorAll("input"), function(el){
    el.addEventListener("input", debounce(applyFilters, 150));
  });
  Array.prototype.forEach.call(flagGroupEl.querySelectorAll("input"), function(el){
    el.addEventListener("change", applyFilters);
  });
  __id("searchBox").addEventListener("input", debounce(applyFilters, 150));

  function debounce(fn, ms){
    var t;
    return function(){
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function(){ fn.apply(null, args); }, ms);
    };
  }

  // ---------------------------------------------------------------
  // industry picker
  // ---------------------------------------------------------------
  function buildIndPicker(industries){
    var listEl = __id("indList");
    listEl.innerHTML = industries.map(function(ind){
      var label = (ind === "#N/A" || !ind) ? "未分類" : ind;
      return '<label><input type="checkbox" value="'+escapeAttr(ind)+'" checked> '+escapeHtml(label)+'</label>';
    }).join("");
    Array.prototype.forEach.call(listEl.querySelectorAll("input"), function(el){
      el.addEventListener("change", function(){ syncIndSelection(); applyFilters(); });
    });
    __id("indAll").addEventListener("click", function(){
      Array.prototype.forEach.call(listEl.querySelectorAll("input"), function(el){ el.checked = true; });
      syncIndSelection(); applyFilters();
    });
    __id("indNone").addEventListener("click", function(){
      Array.prototype.forEach.call(listEl.querySelectorAll("input"), function(el){ el.checked = false; });
      syncIndSelection(); applyFilters();
    });
    syncIndSelection();
  }
  function syncIndSelection(){
    var listEl = __id("indList");
    var boxes = listEl.querySelectorAll("input");
    var total = boxes.length, checked = 0;
    var set = {};
    Array.prototype.forEach.call(boxes, function(el){
      if(el.checked){ checked++; set[el.value] = true; }
    });
    selectedInds = (checked === total) ? null : set;
    __id("indSummary").textContent = (checked === total) ? "(全部)" : "("+checked+"/"+total+")";
  }

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; });
  }
  function escapeAttr(s){ return escapeHtml(s); }

  function currentRanges(){
    var ranges = {};
    Array.prototype.forEach.call(rangeGroupsEl.querySelectorAll(".range-row"), function(row){
      var key = row.getAttribute("data-key");
      var min = row.querySelector('[data-bound="min"]').value;
      var max = row.querySelector('[data-bound="max"]').value;
      ranges[key] = { min: min === "" ? null : parseFloat(min), max: max === "" ? null : parseFloat(max) };
    });
    return ranges;
  }
  function currentFlags(){
    var activeFlags = [];
    Array.prototype.forEach.call(flagGroupEl.querySelectorAll("input"), function(el){
      if(el.checked) activeFlags.push(FLAGS.filter(function(f){ return f.key === el.getAttribute("data-flag"); })[0]);
    });
    return activeFlags;
  }

  // ---------------------------------------------------------------
  // filtering / sorting / rendering (單月結果)
  // ---------------------------------------------------------------
  function passesFilters(r, q, ranges, activeFlags, dayIdx){
    if(q && r.code.indexOf(q) !== 0 && (r.name || "").indexOf(q) === -1) return false;
    if(selectedInds && !selectedInds[r.ind || "#N/A"]) return false;
    for(var i=0;i<RANGE_GROUPS.length;i++){
      var fields = RANGE_GROUPS[i].fields;
      for(var j=0;j<fields.length;j++){
        var key = fields[j].key;
        var rg = ranges[key];
        if(rg.min === null && rg.max === null) continue;
        var v = getValue(r, key, dayIdx);
        if(v === null || v === undefined) return false;
        if(rg.min !== null && v < rg.min) return false;
        if(rg.max !== null && v > rg.max) return false;
      }
    }
    for(var k=0;k<activeFlags.length;k++){
      if(!activeFlags[k].test(r, dayIdx)) return false;
    }
    return true;
  }

  function applyFilters(){
    var q = __id("searchBox").value.trim().toUpperCase();
    var ranges = currentRanges();
    var activeFlags = currentFlags();

    var out = ALL.filter(function(r){ return passesFilters(r, q, ranges, activeFlags, dayIdx); });

    if(sortState.key){
      var col = TABLE_COLUMNS.filter(function(c){ return c.key === sortState.key; })[0];
      out.sort(function(a,b){
        var va = col.get ? col.get(a, dayIdx) : a[col.key];
        var vb = col.get ? col.get(b, dayIdx) : b[col.key];
        if(va === null || va === undefined) va = col.left ? "" : -Infinity;
        if(vb === null || vb === undefined) vb = col.left ? "" : -Infinity;
        if(va < vb) return -1 * sortState.dir;
        if(va > vb) return 1 * sortState.dir;
        return 0;
      });
    }

    renderTable(out);
    CURRENT_ROWS = out;
    __id("dayLabelText").textContent = DATES.length ? ("（篩選月：" + fmtDate(DATES[dayIdx]) + " 公告）") : "";
    if(view==="backtest") renderBacktest();
  }

  // ---------------------------------------------------------------
  // 匯出目前篩選結果（單月結果、依目前排序，全部符合筆數）成 CSV，Excel 可直接開啟
  // ---------------------------------------------------------------
  var CURRENT_ROWS = [];
  function csvEscape(v){
    v = (v===null || v===undefined) ? "" : String(v);
    if(/[",\n]/.test(v)) v = '"' + v.replace(/"/g,'""') + '"';
    return v;
  }
  function buildCSV(headers, rows){
    var lines = [headers.map(csvEscape).join(",")];
    rows.forEach(function(r){ lines.push(r.map(csvEscape).join(",")); });
    return "﻿" + lines.join("\r\n");
  }
  async function exportResults(){
    if(!window.claude || !window.claude.use){ alert("此檢視環境不支援匯出檔案功能。"); return; }
    var downloads = await window.claude.use("downloads");
    if(!downloads){ alert("此檢視環境目前無法匯出檔案。"); return; }
    var headers = TABLE_COLUMNS.map(function(c){ return c.label; });
    var rows = CURRENT_ROWS.map(function(r){
      return TABLE_COLUMNS.map(function(c){
        if(c.key === "code") return r.code;
        if(c.key === "name") return r.name || "";
        if(c.key === "ind") return (r.ind==="#N/A"||!r.ind) ? "未分類" : r.ind;
        var v = c.get(r, dayIdx);
        return fmtVal(v, c.unit);
      });
    });
    var dayLabel = DATES.length ? DATES[dayIdx] : "";
    var csv = buildCSV(headers, rows);
    try{
      await downloads.save({filename: "基本面財務指標篩選器_篩選結果_"+dayLabel+".csv", data: csv});
    }catch(e){
      if(!e || e.code !== "declined") alert("匯出失敗："+(e && e.message ? e.message : e));
    }
  }
  __id("exportBtn").addEventListener("click", exportResults);

  function renderTable(rows){
    __id("matchCount").textContent = rows.length.toLocaleString("en-US");
    var body = __id("bodyRows");
    if(rows.length === 0){
      body.innerHTML = '<tr class="empty-row"><td colspan="'+TABLE_COLUMNS.length+'">沒有符合條件的股票，試著放寬篩選條件</td></tr>';
      return;
    }
    var shown = rows.slice(0, MAX_ROWS);
    var html = shown.map(function(r){
      return "<tr>" + TABLE_COLUMNS.map(function(c){
        if(c.key === "code") return '<td class="left code">'+r.code+'</td>';
        if(c.key === "name") return '<td class="left">'+escapeHtml(r.name||"")+'</td>';
        if(c.key === "ind") return '<td class="left">'+escapeHtml((r.ind==="#N/A"||!r.ind)?"未分類":r.ind)+'</td>';
        var v = c.get(r, dayIdx);
        var cls = "";
        if(c.unit === "pct1" && v !== null && v !== undefined){ cls = v >= 0 ? "pos" : "neg"; }
        return '<td class="'+cls+'">'+fmtVal(v, c.unit)+'</td>';
      }).join("") + "</tr>";
    }).join("");
    if(rows.length > MAX_ROWS){
      html += '<tr class="more-row"><td colspan="'+TABLE_COLUMNS.length+'">還有 '+(rows.length-MAX_ROWS).toLocaleString("en-US")+' 檔符合條件，請縮小篩選範圍以完整顯示</td></tr>';
    }
    body.innerHTML = html;
  }

  function renderHead(){
    var head = __id("headRow");
    head.innerHTML = TABLE_COLUMNS.map(function(c){
      return '<th class="'+(c.left?"left":"")+'" data-key="'+c.key+'">'+c.label+'<span class="arrow" data-arrow="'+c.key+'"></span></th>';
    }).join("");
    Array.prototype.forEach.call(head.querySelectorAll("th"), function(th){
      th.addEventListener("click", function(){
        var key = th.getAttribute("data-key");
        if(sortState.key === key){ sortState.dir *= -1; }
        else { sortState.key = key; sortState.dir = -1; }
        updateSortArrows();
        applyFilters();
      });
    });
  }
  function updateSortArrows(){
    Array.prototype.forEach.call(ROOT.querySelectorAll(".arrow"), function(el){ el.textContent = ""; });
    if(sortState.key){
      var el = ROOT.querySelector('.arrow[data-arrow="'+sortState.key+'"]');
      if(el) el.textContent = sortState.dir === 1 ? "▲" : "▼";
    }
  }

  // ---------------------------------------------------------------
  // 24個月回測彙總表：同一組篩選條件，依公告截止日規則逐一套用最近 BACKTEST_DAYS 次
  // 月營收公告日重新篩選一次，收斂成寬表；格子放符合當次公告日的收盤價。
  // ---------------------------------------------------------------
  var BACKTEST = { matched:null, codesAll:[], n:0, sortDay:null };

  function computeBacktest(){
    var q = __id("searchBox").value.trim().toUpperCase();
    var ranges = currentRanges();
    var activeFlags = currentFlags();

    var n = Math.min(BACKTEST_DAYS, DATES.length);
    var matched = {};
    for(var day=0; day<n; day++){
      for(var i=0;i<ALL.length;i++){
        var r = ALL[i];
        if(!passesFilters(r, q, ranges, activeFlags, day)) continue;
        if(!matched[r.code]) matched[r.code] = { r:r, prices:new Array(n).fill(null) };
        matched[r.code].prices[day] = getValue(r, "price", day);
      }
    }
    BACKTEST.matched = matched;
    BACKTEST.codesAll = Object.keys(matched).sort();
    BACKTEST.n = n;
  }

  function orderedBacktestCodes(){
    var matched = BACKTEST.matched, day = BACKTEST.sortDay;
    var codes = BACKTEST.codesAll.slice();
    if(day == null) return codes;
    codes.sort(function(a,b){
      var ah = matched[a].prices[day]!=null ? 0 : 1, bh = matched[b].prices[day]!=null ? 0 : 1;
      if(ah!==bh) return ah-bh;
      return a<b ? -1 : a>b ? 1 : 0;
    });
    return codes;
  }

  function renderBacktestTable(){
    var n = BACKTEST.n, matched = BACKTEST.matched, day = BACKTEST.sortDay;

    var headHtml = "<th>代號</th><th>名稱</th>" + DATES.slice(0,n).map(function(d,i){
      var cls = [];
      if(i===0) cls.push("newest");
      if(i===day) cls.push("active-sort");
      return "<th"+(cls.length?' class="'+cls.join(" ")+'"':"")+' data-day="'+i+'" title="點這一次公告日：把那次有符合條件的個股排到最上面，組內依代號排序">'+fmtDate(d)+(i===day?" ▾":"")+"</th>";
    }).join("");
    __id("backtestHead").innerHTML = headHtml;
    __id("backtestColgroup").innerHTML = '<col class="code"><col class="name">' + "<col>".repeat(n);

    var codes = orderedBacktestCodes();
    if(!codes.length){
      __id("backtestBody").innerHTML = '<tr><td colspan="'+(n+2)+'" class="empty-row">這 '+n+' 次公告日裡沒有任何一次符合這組篩選條件的個股，試著放寬篩選門檻。</td></tr>';
      return;
    }
    var bodyHtml = codes.map(function(c){
      var m = matched[c];
      var cells = m.prices.map(function(p,i){
        var v = p!=null?fmtCompact(p,2):"";
        var cls = [];
        if(p!=null) cls.push("hit");
        if(i===day) cls.push("active-sort");
        return "<td"+(cls.length?' class="'+cls.join(" ")+'"':"")+' title="'+fmtDate(DATES[i])+" "+m.r.name+" "+v+'">'+v+"</td>";
      }).join("");
      return '<tr><td class="left code num" title="'+c+" "+m.r.name+'">'+c+'</td><td class="left" title="'+m.r.name+'">'+escapeHtml(m.r.name||"")+"</td>"+cells+"</tr>";
    }).join("");
    __id("backtestBody").innerHTML = bodyHtml;

    if(day==null){
      __id("backtestHint").textContent =
        "這 "+n+" 次公告日裡共有 "+codes.length+" 檔個股至少符合過一次篩選條件。每一欄是一次月營收公告日，用同一組篩選條件依公告截止日規則重新計算那一天的結果；格子顯示的是「該檔股票在那次公告日有符合條件」時的收盤價，沒有符合就留空。依代號排序；點任一次公告日的欄位，可以把那次有符合條件的個股排到最上面。";
    } else {
      var hitCount = codes.filter(function(c){ return matched[c].prices[day]!=null; }).length;
      __id("backtestHint").innerHTML =
        fmtDate(DATES[day])+" 公告當天共有 <b>"+hitCount+"</b> 檔符合條件，已排到最上面並依代號排序；其餘個股（其他次有符合過、這次沒有）排在後面。再點一次「"+fmtDate(DATES[day])+"」可還原成依代號排序。";
    }
  }

  function renderBacktest(){
    computeBacktest();
    BACKTEST.sortDay = null;
    renderBacktestTable();
  }

  function setView(v){
    view = v;
    __id("tabDay").setAttribute("aria-pressed", v==="day");
    __id("tabBacktest").setAttribute("aria-pressed", v==="backtest");
    __id("dayView").hidden = v!=="day";
    __id("backtestView").hidden = v!=="backtest";
    if(v==="backtest") renderBacktest();
  }

  __id("tabDay").addEventListener("click", function(){ setView("day"); });
  __id("tabBacktest").addEventListener("click", function(){ setView("backtest"); });
  __id("asOfDay").addEventListener("change", function(){ dayIdx = Number(this.value) || 0; applyFilters(); });
  Array.prototype.forEach.call(ROOT.querySelectorAll("#m5-backtestView .backtest-toolbar .seg button"), function(btn){
    btn.addEventListener("click", function(){
      var size = btn.getAttribute("data-size");
      Array.prototype.forEach.call(ROOT.querySelectorAll("#m5-backtestView .backtest-toolbar .seg button"), function(b){ b.setAttribute("aria-pressed", b===btn); });
      __id("backtestTable").className = "size-" + size;
    });
  });
  __id("backtestHead").addEventListener("click", function(e){
    var th = e.target.closest("th[data-day]");
    if(!th || !BACKTEST.matched) return;
    var day = Number(th.getAttribute("data-day"));
    BACKTEST.sortDay = (BACKTEST.sortDay===day) ? null : day;
    renderBacktestTable();
  });

  function clearAllFilters(){
    __id("searchBox").value = "";
    Array.prototype.forEach.call(rangeGroupsEl.querySelectorAll("input"), function(el){ el.value = ""; });
    Array.prototype.forEach.call(flagGroupEl.querySelectorAll("input"), function(el){ el.checked = false; });
    Array.prototype.forEach.call(ROOT.querySelectorAll("#m5-indList input"), function(el){ el.checked = true; });
    syncIndSelection();
    sortState = { key:null, dir:1 };
    updateSortArrows();
  }

  __id("resetBtn").addEventListener("click", function(){
    clearAllFilters();
    Array.prototype.forEach.call(ROOT.querySelectorAll(".btn.example"), function(b){ b.setAttribute("aria-pressed","false"); });
    applyFilters();
  });

  // ---------------------------------------------------------------
  // 篩選範例：三個預設條件組合，方便第一次使用的人點點看，不代表任何選股建議（見上方警語）
  // ---------------------------------------------------------------
  function setRange(key, bound, v){
    var row = rangeGroupsEl.querySelector('.range-row[data-key="'+key+'"]');
    if(row) row.querySelector('[data-bound="'+bound+'"]').value = v;
  }
  function setFlag(key, on){
    var el = flagGroupEl.querySelector('input[data-flag="'+key+'"]');
    if(el) el.checked = !!on;
  }

  var EXAMPLES = [
    { key:"rev", label:"範例①　營收動能", apply:function(){
        setRange("rev_yoy_1m","min",10); setRange("rev_yoy_3m","min",10);
      }},
    { key:"profit", label:"範例②　獲利成長", apply:function(){
        setRange("eps4_yoy","min",20); setRange("opinc_yoy","min",10);
      }},
    { key:"high", label:"範例③　創高動能", apply:function(){
        setFlag("revm_h12",true); setFlag("epsq_h4",true);
      }}
  ];

  var exampleBtnsEl = __id("exampleBtns");
  exampleBtnsEl.innerHTML = EXAMPLES.map(function(ex){
    return '<button type="button" class="btn example" data-ex="'+ex.key+'" aria-pressed="false">'+ex.label+'</button>';
  }).join("");
  Array.prototype.forEach.call(exampleBtnsEl.querySelectorAll(".btn.example"), function(btn, i){
    btn.addEventListener("click", function(){
      var wasOn = btn.getAttribute("aria-pressed") === "true";
      clearAllFilters();
      Array.prototype.forEach.call(exampleBtnsEl.querySelectorAll(".btn.example"), function(b){ b.setAttribute("aria-pressed","false"); });
      if(!wasOn){
        EXAMPLES[i].apply();
        btn.setAttribute("aria-pressed","true");
      }
      applyFilters();
    });
  });

  // ---------------------------------------------------------------
  // boot
  // ---------------------------------------------------------------
  __fetch("screener.json").then(function(r){ return r.json(); }).then(function(data){
    var rows = data.rows;
    ALL = Object.keys(rows).map(function(code){
      var r = rows[code];
      r.code = code;
      return r;
    });
    __id("totalCount").textContent = ALL.length.toLocaleString("en-US");

    FUND.quarterLabels = data.quarterLabels || [];
    FUND.monthLabels = data.monthLabels || [];
    FUND.monthKeys = FUND.monthLabels.map(function(v){ return Math.round(v*100); });

    DATES = (data.priceDates || []).slice(0, BACKTEST_DAYS);

    var sel = __id("asOfDay");
    sel.innerHTML = DATES.map(function(d, i){
      return '<option value="'+i+'">'+fmtDate(d)+(i===0?"（最新）":"")+"</option>";
    }).join("");

    var indSet = {};
    ALL.forEach(function(r){ indSet[r.ind || "#N/A"] = true; });
    var industries = Object.keys(indSet).sort();
    buildIndPicker(industries);

    renderHead();
    sortState = { key:"code", dir:1 };
    updateSortArrows();
    applyFilters();
  }).catch(function(err){
    __id("bodyRows").innerHTML = '<tr class="empty-row"><td colspan="'+TABLE_COLUMNS.length+'">資料載入失敗，請重新整理頁面再試一次</td></tr>';
    console.error(err);
  });
})();

};

/* ── t6 ← BG 06merged ── */
CF_MODS["t6"] = function(ROOT, API){
var PFX = "m6-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

(function(){
  "use strict";

  // ---------------------------------------------------------------
  // fundamentals field definitions (from 全市場選股雷達)
  // ---------------------------------------------------------------
  var RANGE_GROUPS = [
    { title:"營收動能", fields:[
      { key:"rev_yoy_1m", label:"單月營收年增率", unit:"%" },
      { key:"rev_yoy_3m", label:"3月營收年增率", unit:"%" },
      { key:"rev_yoy_12m", label:"12月營收年增率", unit:"%" }
    ]},
    { title:"獲利成長", fields:[
      { key:"eps4_yoy", label:"四季EPS年增率", unit:"%" },
      { key:"opinc_yoy", label:"營業利益年增率", unit:"%" },
      { key:"eps4", label:"四季EPS", unit:"元" },
      { key:"eps_q", label:"單季EPS", unit:"元" }
    ]},
    { title:"獲利能力", fields:[
      { key:"opm", label:"營益率", unit:"%" },
      { key:"npm", label:"稅後淨利率", unit:"%" }
    ]},
    { title:"合約負債與資本支出", fields:[
      { key:"cl_rev_ratio", label:"合約負債佔四季營收比", unit:"%" },
      { key:"cl_cap_ratio", label:"合約負債佔股本比", unit:"%" },
      { key:"capex_cap_ratio", label:"資本支出佔股本比", unit:"%" }
    ]},
    { title:"規模", fields:[
      { key:"rev4q", label:"四季營收", unit:"百萬" },
      { key:"capital", label:"股本", unit:"百萬" }
    ]}
  ];

  // ---------------------------------------------------------------
  // 基本面「篩選日對應期別」：季報依公告截止日（Q1→5/15、Q2→8/14、Q3→11/14、
  // Q4/年報→次年3/31）、月營收依公告截止日（每月10日前公佈上個月）回推「那一天
  // 實際已公佈的最新一期」是哪一季/哪個月，避免用到當時還沒公佈的未來資料。
  // ---------------------------------------------------------------
  var FUND = { quarterLabels: [], monthLabels: [], monthKeys: [] };
  var fundIdxCache = {};

  function computeFundIdx(dateObj){
    var y = dateObj.getFullYear(), m = dateObj.getMonth()+1, d = dateObj.getDate();
    var q4prev = new Date(y,2,31), q1d = new Date(y,4,15), q2d = new Date(y,7,14), q3d = new Date(y,10,14);
    var qy, qq;
    if(dateObj < q4prev){ qy = y-1; qq = 3; }
    else if(dateObj < q1d){ qy = y-1; qq = 4; }
    else if(dateObj < q2d){ qy = y; qq = 1; }
    else if(dateObj < q3d){ qy = y; qq = 2; }
    else { qy = y; qq = 3; }
    var qIdx = FUND.quarterLabels.indexOf(qy + "Q" + qq);

    var back = d >= 10 ? 1 : 2;
    var my = y, mm = m - back;
    while(mm <= 0){ mm += 12; my -= 1; }
    var mIdx = FUND.monthKeys.indexOf(my*100 + mm);

    return { qIdx: qIdx<0?null:qIdx, mIdx: mIdx<0?null:mIdx };
  }
  function fundIdxForDay(dayIdx){
    if(fundIdxCache[dayIdx]) return fundIdxCache[dayIdx];
    var iso = DATES[dayIdx];
    var p = iso.split("-");
    var r = computeFundIdx(new Date(Number(p[0]), Number(p[1])-1, Number(p[2])));
    fundIdxCache[dayIdx] = r;
    return r;
  }
  function arrAt(arr, idx){ return (arr && idx!=null && arr[idx]!==undefined) ? arr[idx] : null; }

  function getValue(r, key, dayIdx){
    return API.fundVal(r.code, "days", dayIdx, key);
    var fi = fundIdxForDay(dayIdx);
    switch(key){
      case "rev_yoy_1m": return arrAt(r.rev_yoy_1m, fi.mIdx);
      case "rev_yoy_3m": return arrAt(r.rev_yoy_3m, fi.mIdx);
      case "rev_yoy_12m": return arrAt(r.rev_yoy_12m, fi.mIdx);
      case "eps4_yoy": return arrAt(r.eps4_yoy, fi.qIdx);
      case "opinc_yoy": return arrAt(r.opinc_yoy, fi.qIdx);
      case "eps4": return arrAt(r.eps4, fi.qIdx);
      case "eps_q": return arrAt(r.eps_q, fi.qIdx);
      case "opm": return arrAt(r.opm, fi.qIdx);
      case "npm": return arrAt(r.npm, fi.qIdx);
      case "cl_rev_ratio": return arrAt(r.cl_rev_ratio, fi.qIdx);
      case "cl_cap_ratio": return arrAt(r.cl_cap_ratio, fi.qIdx);
      case "capex_cap_ratio": return arrAt(r.capex_cap_ratio, fi.qIdx);
      case "rev4q": return arrAt(r.rev4q, fi.qIdx);
      case "capital": return arrAt(r.capital, fi.qIdx);
      default: return null;
    }
  }

  var FLAGS = [
    { key:"eps4_h4", label:"四季EPS創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"eps4_h8", label:"四季EPS創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"epsq_h4", label:"單季EPS創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"epsq_h8", label:"單季EPS創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"opm_h4", label:"營益率創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"opm_h8", label:"營益率創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"npm_h4", label:"稅後淨利率創近4季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"npm_h8", label:"稅後淨利率創近8季新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"revm_h12", label:"月營收創近12個月新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } },
    { key:"revm_h24", label:"月營收創近24個月新高", test:function(r,d){ return API.fundFlag(r.code, "days", d, this.key); } }
  ];
  function ge(a, b){ return a !== null && a !== undefined && b !== null && b !== undefined && a >= b; }

  // chip 欄位一律用 valueAtDay(r, key, dayIdx) 讀依日期索引的 _h 陣列；dayIdx=0 是最新一天
  var CHIP_FIELD_MAP = { price:"price_h", wr:"wr_h", xr:"xr_h", yr:"yr_h", z:"z_h", hr:"hr_h" };
  function valueAtDay(r, key, dayIdx){
    if(key === "hp") return r.hp_h ? r.hp_h[dayIdx] : null;
    if(key === "sh") return r.sh_h ? r.sh_h[dayIdx] : null;
    var arr = r[CHIP_FIELD_MAP[key]];
    return arr ? arr[dayIdx] : null;
  }

  var TABLE_COLUMNS = [
    { key:"code", label:"代號", left:true },
    { key:"name", label:"名稱", left:true },
    { key:"ind", label:"產業", left:true },
    { key:"price", label:"收盤價", unit:"num2", get:function(r,d){ return valueAtDay(r,"price",d); }, grp:"chip" },
    { key:"wr", label:"法人/大戶排名", unit:"int", get:function(r,d){ return valueAtDay(r,"wr",d); }, grp:"chip" },
    { key:"xr", label:"量/大戶排名", unit:"int", get:function(r,d){ return valueAtDay(r,"xr",d); }, grp:"chip" },
    { key:"yr", label:"法人60日排名", unit:"int", get:function(r,d){ return valueAtDay(r,"yr",d); }, grp:"chip" },
    { key:"hp", label:"大戶比例%", unit:"num2", get:function(r,d){ return valueAtDay(r,"hp",d); }, grp:"chip" },
    { key:"sh", label:"總股東人數", unit:"money", get:function(r,d){ return valueAtDay(r,"sh",d); }, grp:"chip" },
    { key:"z", label:"買賣超/資本額", unit:"num3", get:function(r,d){ return valueAtDay(r,"z",d); }, grp:"chip" },
    { key:"hr", label:"大戶人數排名", unit:"int", get:function(r,d){ return valueAtDay(r,"hr",d); }, grp:"chip" },
    { key:"rev_yoy_1m", label:"月營收YoY", unit:"pct1", get:function(r,d){ return getValue(r,"rev_yoy_1m",d); }, grp:"fund" },
    { key:"eps4_yoy", label:"四季EPS YoY", unit:"pct1", get:function(r,d){ return getValue(r,"eps4_yoy",d); }, grp:"fund" },
    { key:"eps_q", label:"單季EPS", unit:"num2", get:function(r,d){ return getValue(r,"eps_q",d); }, grp:"fund" },
    { key:"opm", label:"營益率", unit:"pct1", get:function(r,d){ return getValue(r,"opm",d); }, grp:"fund" },
    { key:"npm", label:"稅後淨利率", unit:"pct1", get:function(r,d){ return getValue(r,"npm",d); }, grp:"fund" },
    { key:"capital", label:"股本(百萬)", unit:"money", get:function(r,d){ return getValue(r,"capital",d); }, grp:"fund" },
    { key:"rev4q", label:"四季營收(百萬)", unit:"money", get:function(r,d){ return getValue(r,"rev4q",d); }, grp:"fund" }
  ];

  // ---------------------------------------------------------------
  // state
  // ---------------------------------------------------------------
  var ALL = [];
  var DATES = [];
  var BACKTEST_DAYS = 20;
  var dayIdx = 0;
  var view = "day";
  var selectedInds = null;
  var sortState = { key:"eps4_yoy", dir:-1 };
  var MAX_ROWS = 300;

  function fmtVal(v, unit){
    if(v === null || v === undefined) return "—";
    if(unit === "pct1") return v.toFixed(1) + "%";
    if(unit === "num1") return v.toFixed(1);
    if(unit === "num2") return v.toFixed(2);
    if(unit === "num3") return v.toFixed(3);
    if(unit === "int") return Math.round(v).toLocaleString("en-US");
    if(unit === "money") return Math.round(v).toLocaleString("en-US");
    return String(v);
  }
  function fmtCompact(v, digits){
    if(v === null || v === undefined || Number.isNaN(v)) return "";
    return Number(v).toFixed(digits==null?2:digits);
  }
  function fmtDate(iso){
    if(!iso) return "—";
    var p = iso.split("-");
    return (p[1]|0) + "/" + (p[2]|0);
  }

  // ---------------------------------------------------------------
  // build fundamentals range/flag UI
  // ---------------------------------------------------------------
  var rangeGroupsEl = __id("rangeGroups");
  rangeGroupsEl.innerHTML = RANGE_GROUPS.map(function(g){
    return '<h3>'+g.title+'</h3>' + g.fields.map(function(f){
      return '<div class="range-row" data-key="'+f.key+'">' +
        '<label>'+f.label+'<span class="unit">'+f.unit+'</span></label>' +
        '<div class="range-inputs">' +
          '<input type="number" class="min" data-key="'+f.key+'" data-bound="min" placeholder="最小">' +
          '<span>~</span>' +
          '<input type="number" class="max" data-key="'+f.key+'" data-bound="max" placeholder="最大">' +
        '</div></div>';
    }).join("");
  }).join("");

  var flagGroupEl = __id("flagGroup");
  flagGroupEl.innerHTML = FLAGS.map(function(f){
    return '<label class="check-row"><input type="checkbox" data-flag="'+f.key+'"> '+f.label+'</label>';
  }).join("");

  Array.prototype.forEach.call(rangeGroupsEl.querySelectorAll("input"), function(el){
    el.addEventListener("input", debounce(applyFilters, 150));
  });
  Array.prototype.forEach.call(flagGroupEl.querySelectorAll("input"), function(el){
    el.addEventListener("change", applyFilters);
  });
  __id("searchBox").addEventListener("input", debounce(applyFilters, 150));

  var CHIP_INPUT_IDS = ["r1_max","r2_max","r3_max","hp_min","hp_trend_n","hp_trend_val","sh_down_n","z_min","hr_top"];
  CHIP_INPUT_IDS.forEach(function(id){
    __id(id).addEventListener("input", debounce(applyFilters, 150));
  });

  function debounce(fn, ms){
    var t;
    return function(){
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function(){ fn.apply(null, args); }, ms);
    };
  }

  function validDay(v){
    var n = Number(v);
    return (v !== "" && Number.isInteger(n) && n >= 1 && n <= 60) ? n : null;
  }

  // ---------------------------------------------------------------
  // industry picker
  // ---------------------------------------------------------------
  function buildIndPicker(industries){
    var listEl = __id("indList");
    listEl.innerHTML = industries.map(function(ind){
      var label = (ind === "#N/A" || !ind) ? "未分類/僅籌碼資料" : ind;
      return '<label><input type="checkbox" value="'+escapeAttr(ind)+'" checked> '+escapeHtml(label)+'</label>';
    }).join("");
    Array.prototype.forEach.call(listEl.querySelectorAll("input"), function(el){
      el.addEventListener("change", function(){ syncIndSelection(); applyFilters(); });
    });
    __id("indAll").addEventListener("click", function(){
      Array.prototype.forEach.call(listEl.querySelectorAll("input"), function(el){ el.checked = true; });
      syncIndSelection(); applyFilters();
    });
    __id("indNone").addEventListener("click", function(){
      Array.prototype.forEach.call(listEl.querySelectorAll("input"), function(el){ el.checked = false; });
      syncIndSelection(); applyFilters();
    });
    syncIndSelection();
  }
  function syncIndSelection(){
    var listEl = __id("indList");
    var boxes = listEl.querySelectorAll("input");
    var total = boxes.length, checked = 0;
    var set = {};
    Array.prototype.forEach.call(boxes, function(el){
      if(el.checked){ checked++; set[el.value] = true; }
    });
    selectedInds = (checked === total) ? null : set;
    __id("indSummary").textContent = (checked === total) ? "(全部)" : "("+checked+"/"+total+")";
  }

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; });
  }
  function escapeAttr(s){ return escapeHtml(s); }

  // ---------------------------------------------------------------
  // chip filter（依 dayIdx 讀 _h 陣列；跟籌碼數據自訂篩選器同一套語意）
  // ---------------------------------------------------------------
  function passesChipFilters(s, day){
    var v;
    var hr = valueAtDay(s,"hr",day), z = valueAtDay(s,"z",day), wr = valueAtDay(s,"wr",day),
        xr = valueAtDay(s,"xr",day), yr = valueAtDay(s,"yr",day);

    v = __id("hr_top").value; if(v !== ""){ if(!(hr != null && hr <= Number(v))) return false; }
    v = __id("z_min").value; if(v !== ""){ if(!(z != null && z >= Number(v))) return false; }

    var hp0 = valueAtDay(s,"hp",day);
    v = __id("hp_min").value; if(v !== ""){ if(!(hp0 != null && hp0 >= Number(v))) return false; }
    var hpTrendVal = __id("hp_trend_val").value;
    var hpDay = validDay(__id("hp_trend_n").value);
    if(hpTrendVal !== "" && hpDay !== null){
      var need = Number(hpTrendVal);
      var hpN = valueAtDay(s,"hp",day+hpDay);
      if(hp0 == null || hpN == null) return false;
      if(!(hp0 - hpN >= need)) return false;
    }
    var shDay = validDay(__id("sh_down_n").value);
    if(shDay !== null){
      var sh0 = valueAtDay(s,"sh",day), shN = valueAtDay(s,"sh",day+shDay);
      if(sh0 == null || shN == null) return false;
      if(!(sh0 < shN)) return false;
    }

    v = __id("r1_max").value; if(v !== ""){ if(!(wr != null && wr <= Number(v))) return false; }
    v = __id("r2_max").value; if(v !== ""){ if(!(xr != null && xr <= Number(v))) return false; }
    v = __id("r3_max").value; if(v !== ""){ if(!(yr != null && yr <= Number(v))) return false; }

    return true;
  }

  // 基本面條件（範圍＋創高勾選）依篩選日換算成當時已公佈的季度/月份（見上面 fundIdxForDay）；
  // search/產業篩選則跟日期無關
  function passesNonChip(r, q, ranges, activeFlags, dayIdx){
    if(q && r.code.indexOf(q) !== 0 && (r.name || "").indexOf(q) === -1) return false;
    if(selectedInds && !selectedInds[r.ind || "#N/A"]) return false;
    for(var i=0;i<RANGE_GROUPS.length;i++){
      var fields = RANGE_GROUPS[i].fields;
      for(var j=0;j<fields.length;j++){
        var key = fields[j].key;
        var rg = ranges[key];
        if(rg.min === null && rg.max === null) continue;
        var v = getValue(r, key, dayIdx);
        if(v === null || v === undefined) return false;
        if(rg.min !== null && v < rg.min) return false;
        if(rg.max !== null && v > rg.max) return false;
      }
    }
    for(var k=0;k<activeFlags.length;k++){
      if(!activeFlags[k].test(r, dayIdx)) return false;
    }
    return true;
  }

  function currentRanges(){
    var ranges = {};
    Array.prototype.forEach.call(rangeGroupsEl.querySelectorAll(".range-row"), function(row){
      var key = row.getAttribute("data-key");
      var min = row.querySelector('[data-bound="min"]').value;
      var max = row.querySelector('[data-bound="max"]').value;
      ranges[key] = { min: min === "" ? null : parseFloat(min), max: max === "" ? null : parseFloat(max) };
    });
    return ranges;
  }
  function currentFlags(){
    var activeFlags = [];
    Array.prototype.forEach.call(flagGroupEl.querySelectorAll("input"), function(el){
      if(el.checked) activeFlags.push(FLAGS.filter(function(f){ return f.key === el.getAttribute("data-flag"); })[0]);
    });
    return activeFlags;
  }

  // ---------------------------------------------------------------
  // filtering / sorting / rendering (單日結果)
  // ---------------------------------------------------------------
  function applyFilters(){
    var q = __id("searchBox").value.trim().toUpperCase();
    var ranges = currentRanges();
    var activeFlags = currentFlags();

    var out = ALL.filter(function(r){
      if(!passesNonChip(r, q, ranges, activeFlags, dayIdx)) return false;
      if(!passesChipFilters(r, dayIdx)) return false;
      return true;
    });

    if(sortState.key){
      var col = TABLE_COLUMNS.filter(function(c){ return c.key === sortState.key; })[0];
      out.sort(function(a,b){
        var va = col.get ? col.get(a, dayIdx) : a[col.key];
        var vb = col.get ? col.get(b, dayIdx) : b[col.key];
        if(va === null || va === undefined) va = col.left ? "" : -Infinity;
        if(vb === null || vb === undefined) vb = col.left ? "" : -Infinity;
        if(va < vb) return -1 * sortState.dir;
        if(va > vb) return 1 * sortState.dir;
        return 0;
      });
    }

    renderTable(out);
    CURRENT_ROWS = out;
    __id("dayLabelText").textContent = DATES.length ? ("（篩選日："+fmtDate(DATES[dayIdx])+"）") : "";
    if(view==="backtest") renderBacktest();
  }

  // ---------------------------------------------------------------
  // 匯出目前篩選結果（單日結果、依目前排序，全部符合筆數）成 CSV，Excel 可直接開啟
  // ---------------------------------------------------------------
  var CURRENT_ROWS = [];
  function csvEscape(v){
    v = (v===null || v===undefined) ? "" : String(v);
    if(/[",\n]/.test(v)) v = '"' + v.replace(/"/g,'""') + '"';
    return v;
  }
  function buildCSV(headers, rows){
    var lines = [headers.map(csvEscape).join(",")];
    rows.forEach(function(r){ lines.push(r.map(csvEscape).join(",")); });
    return "﻿" + lines.join("\r\n");
  }
  async function exportResults(){
    if(!window.claude || !window.claude.use){ alert("此檢視環境不支援匯出檔案功能。"); return; }
    var downloads = await window.claude.use("downloads");
    if(!downloads){ alert("此檢視環境目前無法匯出檔案。"); return; }
    var headers = TABLE_COLUMNS.map(function(c){ return c.label; });
    var rows = CURRENT_ROWS.map(function(r){
      return TABLE_COLUMNS.map(function(c){
        if(c.key === "code") return r.code;
        if(c.key === "name") return r.name || "";
        if(c.key === "ind") return (r.ind==="#N/A"||!r.ind) ? "未分類/僅籌碼資料" : r.ind;
        var v = c.get(r, dayIdx);
        return fmtVal(v, c.unit);
      });
    });
    var dayLabel = DATES.length ? DATES[dayIdx] : "";
    var csv = buildCSV(headers, rows);
    try{
      await downloads.save({filename: "籌碼×基本面雙向交叉檢索器_篩選結果_"+dayLabel+".csv", data: csv});
    }catch(e){
      if(!e || e.code !== "declined") alert("匯出失敗："+(e && e.message ? e.message : e));
    }
  }
  __id("exportBtn").addEventListener("click", exportResults);

  function renderTable(rows){
    __id("matchCount").textContent = rows.length.toLocaleString("en-US");
    var body = __id("bodyRows");
    if(rows.length === 0){
      body.innerHTML = '<tr class="empty-row"><td colspan="'+TABLE_COLUMNS.length+'">沒有符合條件的股票，試著放寬篩選條件</td></tr>';
      return;
    }
    var shown = rows.slice(0, MAX_ROWS);
    var html = shown.map(function(r){
      return "<tr>" + TABLE_COLUMNS.map(function(c){
        if(c.key === "code") return '<td class="left code">'+r.code+'</td>';
        if(c.key === "name") return '<td class="left">'+escapeHtml(r.name||"")+'</td>';
        if(c.key === "ind") return '<td class="left">'+escapeHtml((r.ind==="#N/A"||!r.ind)?"未分類/僅籌碼資料":r.ind)+'</td>';
        var v = c.get(r, dayIdx);
        var cls = "";
        if(c.unit === "pct1" && v !== null && v !== undefined){ cls = v >= 0 ? "pos" : "neg"; }
        return '<td class="'+cls+'">'+fmtVal(v, c.unit)+'</td>';
      }).join("") + "</tr>";
    }).join("");
    if(rows.length > MAX_ROWS){
      html += '<tr class="more-row"><td colspan="'+TABLE_COLUMNS.length+'">還有 '+(rows.length-MAX_ROWS).toLocaleString("en-US")+' 檔符合條件，請縮小篩選範圍以完整顯示</td></tr>';
    }
    body.innerHTML = html;
  }

  function renderHead(){
    var head = __id("headRow");
    head.innerHTML = TABLE_COLUMNS.map(function(c){
      var grpCls = c.grp === "chip" ? "grp-chip" : (c.grp === "fund" ? "grp-fund" : "");
      return '<th class="'+(c.left?"left":"")+' '+grpCls+'" data-key="'+c.key+'">'+c.label+'<span class="arrow" data-arrow="'+c.key+'"></span></th>';
    }).join("");
    Array.prototype.forEach.call(head.querySelectorAll("th"), function(th){
      th.addEventListener("click", function(){
        var key = th.getAttribute("data-key");
        if(sortState.key === key){ sortState.dir *= -1; }
        else { sortState.key = key; sortState.dir = -1; }
        updateSortArrows();
        applyFilters();
      });
    });
    updateSortArrows();
  }
  function updateSortArrows(){
    Array.prototype.forEach.call(ROOT.querySelectorAll(".arrow"), function(el){ el.textContent = ""; });
    if(sortState.key){
      var el = ROOT.querySelector('.arrow[data-arrow="'+sortState.key+'"]');
      if(el) el.textContent = sortState.dir === 1 ? "▲" : "▼";
    }
  }

  // ---------------------------------------------------------------
  // 20天回測彙總表：同一組篩選條件，逐一套用最近 BACKTEST_DAYS 天重新篩選一次，收斂成寬表。
  // 籌碼條件依當天籌碼資料重算；基本面條件依當天實際「已公佈」的季度/月份重算
  // （不是每天都用同一份基本面快照——公告截止日剛好落在這20天窗口內時，前後幾天用的
  // 季度/月份會不一樣，這是刻意的，避免用到當時還沒公佈的未來資料）。
  // ---------------------------------------------------------------
  var BACKTEST = { matched:null, codesAll:[], n:0, sortDay:null };

  function computeBacktest(){
    var q = __id("searchBox").value.trim().toUpperCase();
    var ranges = currentRanges();
    var activeFlags = currentFlags();

    var n = Math.min(BACKTEST_DAYS, DATES.length);
    var matched = {};
    for(var day=0; day<n; day++){
      for(var i=0;i<ALL.length;i++){
        var r = ALL[i];
        if(!passesNonChip(r, q, ranges, activeFlags, day)) continue;
        if(!passesChipFilters(r, day)) continue;
        if(!matched[r.code]) matched[r.code] = { r:r, prices:new Array(n).fill(null) };
        matched[r.code].prices[day] = valueAtDay(r, "price", day);
      }
    }
    BACKTEST.matched = matched;
    BACKTEST.codesAll = Object.keys(matched).sort();
    BACKTEST.n = n;
  }

  function orderedBacktestCodes(){
    var matched = BACKTEST.matched, day = BACKTEST.sortDay;
    var codes = BACKTEST.codesAll.slice();
    if(day == null) return codes;
    codes.sort(function(a,b){
      var ah = matched[a].prices[day]!=null ? 0 : 1, bh = matched[b].prices[day]!=null ? 0 : 1;
      if(ah!==bh) return ah-bh;
      return a<b ? -1 : a>b ? 1 : 0;
    });
    return codes;
  }

  function renderBacktestTable(){
    var n = BACKTEST.n, matched = BACKTEST.matched, day = BACKTEST.sortDay;

    var headHtml = "<th>代號</th><th>名稱</th>" + DATES.slice(0,n).map(function(d,i){
      var cls = [];
      if(i===0) cls.push("newest");
      if(i===day) cls.push("active-sort");
      return "<th"+(cls.length?' class="'+cls.join(" ")+'"':"")+' data-day="'+i+'" title="點這一天：把那天有符合條件的個股排到最上面，組內依代號排序">'+fmtDate(d)+(i===day?" ▾":"")+"</th>";
    }).join("");
    __id("backtestHead").innerHTML = headHtml;
    __id("backtestColgroup").innerHTML = '<col class="code"><col class="name">' + "<col>".repeat(n);

    var codes = orderedBacktestCodes();
    if(!codes.length){
      __id("backtestBody").innerHTML = '<tr><td colspan="'+(n+2)+'" class="empty-row">這 '+n+' 天裡沒有任何一天符合這組篩選條件的個股，試著放寬篩選門檻。</td></tr>';
      return;
    }
    var bodyHtml = codes.map(function(c){
      var m = matched[c];
      var cells = m.prices.map(function(p,i){
        var v = p!=null?fmtCompact(p,2):"";
        var cls = [];
        if(p!=null) cls.push("hit");
        if(i===day) cls.push("active-sort");
        return "<td"+(cls.length?' class="'+cls.join(" ")+'"':"")+' title="'+fmtDate(DATES[i])+" "+m.r.name+" "+v+'">'+v+"</td>";
      }).join("");
      return '<tr><td class="left code num" title="'+c+" "+m.r.name+'">'+c+'</td><td class="left" title="'+m.r.name+'">'+escapeHtml(m.r.name||"")+"</td>"+cells+"</tr>";
    }).join("");
    __id("backtestBody").innerHTML = bodyHtml;

    if(day==null){
      __id("backtestHint").textContent =
        "這 "+n+" 天裡共有 "+codes.length+" 檔個股至少符合過一天的篩選條件。每一欄是一個回測日，用同一組篩選條件重新計算那一天的結果——籌碼條件依當天籌碼資料重算，基本面條件依當天實際已公佈的季度/月份重算；格子顯示的是「該檔股票在那一天有符合條件」時的收盤價，沒有符合就留空。依代號排序；點任一天的日期欄位，可以把那一天有符合條件的個股排到最上面。";
    } else {
      var hitCount = codes.filter(function(c){ return matched[c].prices[day]!=null; }).length;
      __id("backtestHint").innerHTML =
        fmtDate(DATES[day])+" 當天共有 <b>"+hitCount+"</b> 檔符合條件，已排到最上面並依代號排序；其餘個股（其他天有符合過、這天沒有）排在後面。再點一次「"+fmtDate(DATES[day])+"」可還原成依代號排序。";
    }
  }

  function renderBacktest(){
    computeBacktest();
    BACKTEST.sortDay = null;
    renderBacktestTable();
  }

  function setView(v){
    view = v;
    __id("tabDay").setAttribute("aria-pressed", v==="day");
    __id("tabBacktest").setAttribute("aria-pressed", v==="backtest");
    __id("dayView").hidden = v!=="day";
    __id("backtestView").hidden = v!=="backtest";
    if(v==="backtest") renderBacktest();
  }

  __id("tabDay").addEventListener("click", function(){ setView("day"); });
  __id("tabBacktest").addEventListener("click", function(){ setView("backtest"); });
  __id("asOfDay").addEventListener("change", function(){ dayIdx = Number(this.value) || 0; applyFilters(); });
  Array.prototype.forEach.call(ROOT.querySelectorAll("#m6-backtestView .backtest-toolbar .seg button"), function(btn){
    btn.addEventListener("click", function(){
      var size = btn.getAttribute("data-size");
      Array.prototype.forEach.call(ROOT.querySelectorAll("#m6-backtestView .backtest-toolbar .seg button"), function(b){ b.setAttribute("aria-pressed", b===btn); });
      __id("backtestTable").className = "size-" + size;
    });
  });
  __id("backtestHead").addEventListener("click", function(e){
    var th = e.target.closest("th[data-day]");
    if(!th || !BACKTEST.matched) return;
    var day = Number(th.getAttribute("data-day"));
    BACKTEST.sortDay = (BACKTEST.sortDay===day) ? null : day;
    renderBacktestTable();
  });

  function clearAllFilters(){
    __id("searchBox").value = "";
    Array.prototype.forEach.call(rangeGroupsEl.querySelectorAll("input"), function(el){ el.value = ""; });
    Array.prototype.forEach.call(flagGroupEl.querySelectorAll("input"), function(el){ el.checked = false; });
    CHIP_INPUT_IDS.forEach(function(id){ __id(id).value = ""; });
    Array.prototype.forEach.call(ROOT.querySelectorAll("#m6-indList input"), function(el){ el.checked = true; });
    syncIndSelection();
    sortState = { key:null, dir:1 };
    updateSortArrows();
  }

  __id("resetBtn").addEventListener("click", function(){
    clearAllFilters();
    Array.prototype.forEach.call(ROOT.querySelectorAll(".btn.example"), function(b){ b.setAttribute("aria-pressed","false"); });
    applyFilters();
  });

  // ---------------------------------------------------------------
  // 篩選範例：三個預設條件組合，方便第一次使用的人點點看，不代表任何選股建議（見上方警語）
  // ---------------------------------------------------------------
  function setVal(id, v){ __id(id).value = v; }
  function setRange(key, bound, v){
    var row = rangeGroupsEl.querySelector('.range-row[data-key="'+key+'"]');
    if(row) row.querySelector('[data-bound="'+bound+'"]').value = v;
  }
  function setFlag(key, on){
    var el = flagGroupEl.querySelector('input[data-flag="'+key+'"]');
    if(el) el.checked = !!on;
  }

  var EXAMPLES = [
    { key:"chip", label:"範例①　籌碼面動能", apply:function(){
        setVal("hr_top",300); setVal("z_min",0.05); setVal("hp_trend_val",0.5); setVal("hp_trend_n",20);
        setVal("sh_down_n",20); setVal("r1_max",700); setVal("r2_max",700); setVal("r3_max",700);
      }},
    { key:"fund", label:"範例②　基本面成長", apply:function(){
        setRange("eps4_yoy","min",20); setRange("rev_yoy_1m","min",10);
      }},
    { key:"combo", label:"範例③　籌碼＋基本面共振", apply:function(){
        setVal("hr_top",500); setVal("r3_max",700); setRange("eps4_yoy","min",0); setFlag("epsq_h4",true);
      }}
  ];

  var exampleBtnsEl = __id("exampleBtns");
  exampleBtnsEl.innerHTML = EXAMPLES.map(function(ex){
    return '<button type="button" class="btn example" data-ex="'+ex.key+'" aria-pressed="false">'+ex.label+'</button>';
  }).join("");
  Array.prototype.forEach.call(exampleBtnsEl.querySelectorAll(".btn.example"), function(btn, i){
    btn.addEventListener("click", function(){
      var wasOn = btn.getAttribute("aria-pressed") === "true";
      clearAllFilters();
      Array.prototype.forEach.call(exampleBtnsEl.querySelectorAll(".btn.example"), function(b){ b.setAttribute("aria-pressed","false"); });
      if(!wasOn){
        EXAMPLES[i].apply();
        btn.setAttribute("aria-pressed","true");
      }
      applyFilters();
    });
  });

  // ---------------------------------------------------------------
  // boot: fetch both datasets and merge by code
  // ---------------------------------------------------------------
  Promise.all([
    __fetch("chip_data.json").then(function(r){ return r.json(); }),
    __fetch("fund_data.json").then(function(r){ return r.json(); })
  ]).then(function(results){
    var chipData = results[0];
    var chipStocks = chipData.stocks;
    var fund = results[1].rows;

    DATES = chipData.dates || [];
    BACKTEST_DAYS = chipData.backtestDays || Math.min(20, DATES.length);

    FUND.quarterLabels = results[1].quarterLabels || [];
    FUND.monthLabels = results[1].monthLabels || [];
    FUND.monthKeys = FUND.monthLabels.map(function(v){ return Math.round(v*100); });

    var byCode = {};
    chipStocks.forEach(function(s){
      byCode[s.c] = {
        code: s.c, name: s.n, ind: null,
        price: s.price, wr: s.wr, xr: s.xr, yr: s.yr, z: s.z, hr: s.hr, hp: s.hp, sh: s.sh,
        price_h: s.price_h, wr_h: s.wr_h, xr_h: s.xr_h, yr_h: s.yr_h, z_h: s.z_h, hr_h: s.hr_h, hp_h: s.hp_h, sh_h: s.sh_h
      };
    });
    Object.keys(fund).forEach(function(code){
      var f = fund[code];
      if(!byCode[code]) byCode[code] = { code: code, name: f.name, ind: f.ind };
      var rec = byCode[code];
      rec.name = rec.name || f.name;
      rec.ind = f.ind;
      [
        "rev_m","rev_yoy_1m","rev_yoy_3m","rev_yoy_12m","rev_m_high12","rev_m_high24",
        "eps4_yoy","opinc_yoy","eps4","eps4_high4","eps4_high8","eps_q","eps_q_high4","eps_q_high8",
        "opm","opm_high4","opm_high8","npm","npm_high4","npm_high8",
        "cl_rev_ratio","cl_cap_ratio","capex_cap_ratio","rev4q","capital"
      ].forEach(function(k){ rec[k] = f[k]; });
    });

    ALL = Object.keys(byCode).map(function(c){ return byCode[c]; });
    __id("totalCount").textContent = ALL.length.toLocaleString("en-US");

    var sel = __id("asOfDay");
    sel.innerHTML = DATES.slice(0, BACKTEST_DAYS).map(function(d, i){
      return '<option value="'+i+'">'+fmtDate(d)+(i===0?"（最新）":"")+"</option>";
    }).join("");

    var indSet = {};
    ALL.forEach(function(r){ indSet[r.ind || "#N/A"] = true; });
    var industries = Object.keys(indSet).sort();
    buildIndPicker(industries);

    renderHead();
    applyFilters();
  }).catch(function(err){
    __id("bodyRows").innerHTML = '<tr class="empty-row"><td colspan="'+TABLE_COLUMNS.length+'">資料載入失敗，請重新整理頁面再試一次</td></tr>';
    console.error(err);
  });
})();

};

/* ── t7 ← BG 07ranktrail ── */
CF_MODS["t7"] = function(ROOT, API){
var PFX = "m7-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

const CFG = {"mode": "single", "codes": ["3037"], "top50": true};
const NS = 'http://www.w3.org/2000/svg';
const VW = 660, VH = 636, PL = 70, PR = 22, PT = 38, PB = 70;
const PW = VW - PL - PR, PH = VH - PT - PB;
const $ = id => __id(id);
let D, M, byCode = {}, idx = 59, scale = 'log', timer = null;
let codes = CFG.codes.slice();

function fmtDate(s){ return s.replace(/-/g,'/'); }
// X：對數模式時兩端都放大（買超前段、賣超前段），中間壓縮；Y：對數模式時只放大前段
function tfx(r){
  if (scale === 'lin') return (r - 1) / (M - 1);
  const mid = (M + 1) / 2;
  return r <= mid ? 0.5 * Math.log(r) / Math.log(mid) : 1 - 0.5 * Math.log(M + 1 - r) / Math.log(mid);
}
function tfy(r){ return scale === 'lin' ? (r - 1) / (M - 1) : Math.log(r) / Math.log(M); }
function px(r){ return PL + (1 - tfx(r)) * PW; }
function py(r){ return PT + tfy(r) * PH; }
function el(tag, attrs, parent){ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function cssVar(n){ return getComputedStyle(ROOT).getPropertyValue(n).trim(); }
function colorOf(i){ return CFG.mode === 'single' ? 'var(--accent)' : `var(--s${(i % 8) + 1})`; }
function delta(a, b){ // rank change from a (earlier) to b (later): positive = moved toward #1
  if (a == null || b == null) return '<span class="dn">—</span>';
  const d = a - b;
  if (d === 0) return '<span class="dn">0</span>';
  return d > 0 ? `<span class="up">+${d}</span>` : `<span class="dn">${d}</span>`;
}
function lookup(q){
  q = q.trim(); if (!q) return null;
  const code = q.split(/\s+/)[0];
  if (byCode[code]) return code;
  const hit = D.stocks.find(s => s.n === q || s.n.replace('*','') === q);
  return hit ? hit.c : null;
}

function drawAxes(svg){
  const lin = [1,250,500,750,1000,1250,1500,1750,M];
  const xt = scale === 'lin' ? lin : [1,3,10,30,100,300,Math.ceil(M/2),M-299,M-99,M-29,M-9,M-2,M];
  const yt = scale === 'lin' ? lin : [1,3,10,30,100,300,1000,M];
  const g = el('g', {}, svg);
  el('rect', {x:PL, y:PT, width:PW, height:PH, fill:'none', stroke:'var(--line)'}, g);
  xt.forEach(t => {
    const x = px(t);
    el('line', {x1:x, x2:x, y1:PT, y2:PT+PH, stroke:'var(--grid)'}, g);
    el('text', {x, y:PT+PH+16, 'text-anchor':'middle', class:'tick'}, g).textContent = t;
  });
  yt.forEach(t => {
    const y = py(t);
    el('line', {x1:PL, x2:PL+PW, y1:y, y2:y, stroke:'var(--grid)'}, g);
    el('text', {x:PL-8, y:y+4, 'text-anchor':'end', class:'tick'}, g).textContent = t;
  });
  const mid = Math.ceil(M / 2);
  el('line', {x1:px(mid), x2:px(mid), y1:PT, y2:PT+PH, stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.45}, g);
  el('line', {x1:PL, x2:PL+PW, y1:py(mid), y2:py(mid), stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.45}, g);
  el('text', {x:PL+PW/2, y:VH-26, 'text-anchor':'middle', class:'axt'}, g).textContent = '外資投信買賣超金額60日累計排名 → 越右名次越前（最右＝第1名）';
  const yl = el('text', {x:0, y:0, 'text-anchor':'middle', class:'axt', transform:`translate(20 ${PT+PH/2}) rotate(-90)`}, g);
  yl.textContent = '成交金額20日累計佔比排名 ↑ 越上名次越前（最上＝第1名）';
  const c = [[PL+PW, PT-10, 'end', '↗ 買超前段・成交佔比前段'], [PL, PT-10, 'start', '↖ 賣超前段・成交佔比前段'],
             [PL+PW-8, PT+PH-8, 'end', '買超前段・成交佔比後段'], [PL+8, PT+PH-8, 'start', '賣超前段・成交佔比後段']];
  c.forEach(([x,y,a,t]) => { el('text', {x, y, 'text-anchor':a, class:'corner'}, g).textContent = t; });
}

function render(){
  const svg = $('svg'); svg.innerHTML = '';
  drawAxes(svg);
  const labels = [];
  codes.forEach((code, si) => {
    const s = byCode[code]; if (!s) return;
    const col = colorOf(CFG.codes.indexOf(code) >= 0 ? si : si);
    const g = el('g', {}, svg);
    let prev = null;
    for (let i = 0; i <= idx; i++) {
      const xr = s.x[i], yr = s.y[i];
      if (xr == null || yr == null) { prev = null; continue; }
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const X = px(xr), Y = py(yr);
      if (prev) el('line', {x1:prev[0], y1:prev[1], x2:X, y2:Y, stroke:col, 'stroke-width':1.6, 'stroke-opacity':a*0.8}, g);
      prev = [X, Y];
    }
    for (let i = 0; i <= idx; i++) {
      const xr = s.x[i], yr = s.y[i];
      if (xr == null || yr == null) continue;
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const cur = i === idx;
      el('circle', {cx:px(xr), cy:py(yr), r:cur ? 7 : 3.2, fill:col, 'fill-opacity':cur ? 1 : a,
        stroke:cur ? 'var(--panel)' : 'none', 'stroke-width':2, 'data-c':code, 'data-i':i, style:'cursor:pointer'}, g);
      if (cur) labels.push({x:px(xr), y:py(yr), t:`${s.c} ${s.n}`, col});
    }
  });
  labels.forEach(l => {
    const right = l.x < PL + PW - 120;
    const t = el('text', {x: right ? l.x + 11 : l.x - 11, y: Math.max(PT + 14, Math.min(PT + PH - 6, l.y - 9)),
      'text-anchor': right ? 'start' : 'end', class:'lbl', fill:l.col}, svg);
    t.textContent = l.t;
  });
  syncTop50();
  $('day').value = idx;
  $('dateLabel').textContent = fmtDate(D.dates[idx]);
  renderSide(); renderNotes();
}

function renderNotes(){
  const box = $('notes'); box.innerHTML = '';
  codes.forEach(code => {
    const s = byCode[code]; if (!s) return;
    const xs = s.x.filter(v => v != null), ys = s.y.filter(v => v != null);
    if (xs.length && new Set(xs).size === 1 && new Set(ys).size === 1) {
      const d = document.createElement('div'); d.className = 'note';
      d.textContent = `${s.c} ${s.n}：這 ${xs.length} 個交易日兩項排名都沒變（X＝${xs[0]}、Y＝${ys[0]}），所有點疊在同一個位置。`;
      box.appendChild(d);
    }
  });
}

function renderSide(){
  const side = $('side');
  if (CFG.mode === 'single') {
    const s = byCode[codes[0]]; if (!s) { side.innerHTML = ''; return; }
    let rows = '';
    for (let i = D.dates.length - 1; i >= 0; i--) {
      rows += `<tr data-i="${i}" class="${i === idx ? 'cur' : ''}"><td>${fmtDate(D.dates[i]).slice(5)}</td>` +
        `<td>${s.x[i] ?? '—'}</td><td>${i ? delta(s.x[i-1], s.x[i]) : ''}</td>` +
        `<td>${s.y[i] ?? '—'}</td><td>${i ? delta(s.y[i-1], s.y[i]) : ''}</td></tr>`;
    }
    side.innerHTML = `<h2>${s.c} ${s.n}</h2>
      <div class="kv"><span class="h"></span><span class="h">X 買賣超排名</span><span class="h">Y 成交佔比排名</span>
        <span>${fmtDate(D.dates[0]).slice(5)}</span><span class="num">${s.x[0] ?? '—'}</span><span class="num">${s.y[0] ?? '—'}</span>
        <span>${fmtDate(D.dates[idx]).slice(5)}</span><span class="num">${s.x[idx] ?? '—'}</span><span class="num">${s.y[idx] ?? '—'}</span>
        <span>變化</span><span class="num">${delta(s.x[0], s.x[idx])}</span><span class="num">${delta(s.y[0], s.y[idx])}</span></div>
      <p class="hint">「+」代表名次往第 1 名前進。點表格任一列可跳到那一天。</p>
      <div class="tbl-wrap"><table><thead><tr><th>日期</th><th>X 排名</th><th>較前日</th><th>Y 排名</th><th>較前日</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } else {
    let rows = '';
    codes.forEach((code, si) => {
      const s = byCode[code]; if (!s) return;
      rows += `<tr><td><span class="chip" style="background:${colorOf(si)}"></span>${s.c} ${s.n}</td>` +
        `<td>${s.x[idx] ?? '—'}</td><td>${delta(s.x[0], s.x[idx])}</td><td>${s.y[idx] ?? '—'}</td><td>${delta(s.y[0], s.y[idx])}</td>` +
        `<td><button class="x" data-rm="${code}" aria-label="移除 ${s.n}">×</button></td></tr>`;
    });
    side.innerHTML = `<h2>${fmtDate(D.dates[idx])} 排名</h2>
      <div class="tbl-wrap" style="max-height:none"><table><thead><tr><th>個股</th><th>X</th><th>較${fmtDate(D.dates[0]).slice(5)}</th><th>Y</th><th>較${fmtDate(D.dates[0]).slice(5)}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint">「+」代表名次往第 1 名前進。最多同時比較 8 檔，按 × 移除。</p>`;
  }
}

let TOP50 = [];
function syncTop50(){
  ROOT.querySelectorAll('.t50grid button').forEach(b => b.setAttribute('aria-pressed', b.dataset.c === codes[0]));
}
function pick(c, autoplay){
  stop();
  codes = [c];
  $('code').value = `${c} ${byCode[c].n}`;
  $('err').textContent = '';
  if (autoplay) { idx = 0; play(); } else render();
}
// 兩份清單：x＝法人買超（外資投信買賣超金額60日累計排名）、y＝成交佔比（成交金額20日累計佔比排名），都取資料最後一天前 50 名
const LISTS = { x: '外資投信買賣超金額 60 日累計排名', y: '成交金額 20 日累計佔比排名' };
function listTop(k){
  const last = D.dates.length - 1;
  return D.stocks.filter(s => s[k][last] != null).sort((a, b) => a[k][last] - b[k][last]).slice(0, 50);
}
function showList(k){
  $('tabX').setAttribute('aria-selected', k === 'x'); $('tabY').setAttribute('aria-selected', k === 'y');
  $('t50x').hidden = k !== 'x'; $('t50y').hidden = k !== 'y';
  $('t50title').textContent = `依 ${fmtDate(D.dates[D.dates.length - 1])} ${LISTS[k]}排序`;
}
function buildTop50(){
  const last = D.dates.length - 1;
  TOP50 = listTop('x');
  ['x', 'y'].forEach(k => {
    $('t50' + k).innerHTML = listTop(k).map(s => `<button type="button" data-c="${s.c}" aria-pressed="false" title="第 ${s[k][last]} 名　${s.c} ${s.n}">` +
      `<span class="rk">${s[k][last]}</span><span class="cd">${s.c}</span><span class="nm">${s.n}</span></button>`).join('');
    $('t50' + k).addEventListener('click', e => { const b = e.target.closest('button[data-c]'); if (b) pick(b.dataset.c, true); });
  });
  $('tabX').onclick = () => showList('x'); $('tabY').onclick = () => showList('y');
  showList('x');
}

function stop(){ if (timer) { clearInterval(timer); timer = null; } $('play').textContent = '▶ 播放'; }
function play(){
  if (timer) { stop(); return; }
  if (idx >= D.dates.length - 1) idx = 0;
  $('play').textContent = '❚❚ 暫停';
  render();
  timer = setInterval(() => { if (idx >= D.dates.length - 1) { stop(); return; } idx++; render(); }, +$('speed').value);
}

function setScale(s){ scale = s; $('scLin').setAttribute('aria-pressed', s === 'lin'); $('scLog').setAttribute('aria-pressed', s === 'log'); render(); }

function init(data){
  D = data; M = data.maxRank;
  data.stocks.forEach(s => byCode[s.c] = s);
  const dl = document.createElement('datalist'); dl.id = PFX + 'stocklist';
  dl.innerHTML = data.stocks.map(s => `<option value="${s.c} ${s.n}">`).join('');
  document.body.appendChild(dl);
  $('day').max = data.dates.length - 1; idx = data.dates.length - 1;
  $('sub').textContent = `資料區間 ${fmtDate(data.dates[0])}–${fmtDate(data.dates[data.dates.length-1])}・${data.dates.length} 個交易日・` +
    (CFG.trial ? `試用版僅示範 ${data.stocks.length} 檔權值股（歷史快照）` : `全上市櫃 ${data.stocks.length.toLocaleString()} 檔`);

  $('day').addEventListener('input', e => { stop(); idx = +e.target.value; render(); });
  $('prev').onclick = () => { stop(); if (idx > 0) { idx--; render(); } };
  $('next').onclick = () => { stop(); if (idx < D.dates.length - 1) { idx++; render(); } };
  $('play').onclick = play;
  $('speed').onchange = () => { if (timer) { stop(); play(); } };
  $('scLin').onclick = () => setScale('lin');
  $('scLog').onclick = () => setScale('log');
  $('side').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-i]'); if (tr) { stop(); idx = +tr.dataset.i; render(); }
    const rm = e.target.closest('[data-rm]'); if (rm) { codes = codes.filter(c => c !== rm.dataset.rm); render(); }
  });

  buildTop50();
  if (CFG.top50 && TOP50.length) codes = [byCode["2330"] ? "2330" : TOP50[0].c];

  const inp = $('code'), err = $('err');
  const submit = () => {
    const c = lookup(inp.value);
    if (!c) { err.textContent = CFG.trial ? '試用版只有示範的 8 檔，其他個股請到完整版查詢。' : '找不到這個代號或名稱，請重新輸入。'; return; }
    err.textContent = '';
    if (CFG.mode === 'single') { pick(c, true); return; }
    else {
      if (codes.includes(c)) { err.textContent = '這檔已經在圖上了。'; return; }
      if (codes.length >= 8) { err.textContent = '最多 8 檔，請先移除一檔。'; return; }
      codes.push(c); inp.value = '';
    }
    render();
  };
  $('go').onclick = submit;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  if (CFG.mode === 'single') inp.value = `${codes[0]} ${byCode[codes[0]].n}`;

  const tip = $('tip'), box = $('chartBox');
  $('svg').addEventListener('pointerover', e => {
    const c = e.target.closest('circle[data-c]'); if (!c) return;
    const s = byCode[c.dataset.c], i = +c.dataset.i;
    tip.textContent = `${fmtDate(D.dates[i])}　${s.c} ${s.n}　X ${s.x[i]}／Y ${s.y[i]}`;
    const r = c.getBoundingClientRect(), b = box.getBoundingClientRect();
    tip.style.left = (r.left + r.width / 2 - b.left) + 'px'; tip.style.top = (r.top - b.top) + 'px';
    tip.hidden = false;
  });
  $('svg').addEventListener('pointerout', e => { if (e.target.closest('circle[data-c]')) tip.hidden = true; });
  render();
}

__fetch('data.json').then(r => r.json()).then(init).catch(() => { $('sub').textContent = '資料讀取失敗，請重新整理頁面。'; });

};

/* ── t8 ← BG 08rankcmp ── */
CF_MODS["t8"] = function(ROOT, API){
var PFX = "m8-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

const CFG = {"mode": "compare", "codes": ["2330", "3037", "3017", "2454", "2327", "2317"]};
const NS = 'http://www.w3.org/2000/svg';
const VW = 660, VH = 636, PL = 70, PR = 22, PT = 38, PB = 70;
const PW = VW - PL - PR, PH = VH - PT - PB;
const $ = id => __id(id);
let D, M, byCode = {}, idx = 59, scale = 'log', timer = null;
let codes = CFG.codes.slice();

function fmtDate(s){ return s.replace(/-/g,'/'); }
// X：對數模式時兩端都放大（買超前段、賣超前段），中間壓縮；Y：對數模式時只放大前段
function tfx(r){
  if (scale === 'lin') return (r - 1) / (M - 1);
  const mid = (M + 1) / 2;
  return r <= mid ? 0.5 * Math.log(r) / Math.log(mid) : 1 - 0.5 * Math.log(M + 1 - r) / Math.log(mid);
}
function tfy(r){ return scale === 'lin' ? (r - 1) / (M - 1) : Math.log(r) / Math.log(M); }
function px(r){ return PL + (1 - tfx(r)) * PW; }
function py(r){ return PT + tfy(r) * PH; }
function el(tag, attrs, parent){ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function cssVar(n){ return getComputedStyle(ROOT).getPropertyValue(n).trim(); }
function colorOf(i){ return CFG.mode === 'single' ? 'var(--accent)' : `var(--s${(i % 8) + 1})`; }
function delta(a, b){ // rank change from a (earlier) to b (later): positive = moved toward #1
  if (a == null || b == null) return '<span class="dn">—</span>';
  const d = a - b;
  if (d === 0) return '<span class="dn">0</span>';
  return d > 0 ? `<span class="up">+${d}</span>` : `<span class="dn">${d}</span>`;
}
function lookup(q){
  q = q.trim(); if (!q) return null;
  const code = q.split(/\s+/)[0];
  if (byCode[code]) return code;
  const hit = D.stocks.find(s => s.n === q || s.n.replace('*','') === q);
  return hit ? hit.c : null;
}

function drawAxes(svg){
  const lin = [1,250,500,750,1000,1250,1500,1750,M];
  const xt = scale === 'lin' ? lin : [1,3,10,30,100,300,Math.ceil(M/2),M-299,M-99,M-29,M-9,M-2,M];
  const yt = scale === 'lin' ? lin : [1,3,10,30,100,300,1000,M];
  const g = el('g', {}, svg);
  el('rect', {x:PL, y:PT, width:PW, height:PH, fill:'none', stroke:'var(--line)'}, g);
  xt.forEach(t => {
    const x = px(t);
    el('line', {x1:x, x2:x, y1:PT, y2:PT+PH, stroke:'var(--grid)'}, g);
    el('text', {x, y:PT+PH+16, 'text-anchor':'middle', class:'tick'}, g).textContent = t;
  });
  yt.forEach(t => {
    const y = py(t);
    el('line', {x1:PL, x2:PL+PW, y1:y, y2:y, stroke:'var(--grid)'}, g);
    el('text', {x:PL-8, y:y+4, 'text-anchor':'end', class:'tick'}, g).textContent = t;
  });
  const mid = Math.ceil(M / 2);
  el('line', {x1:px(mid), x2:px(mid), y1:PT, y2:PT+PH, stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.45}, g);
  el('line', {x1:PL, x2:PL+PW, y1:py(mid), y2:py(mid), stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.45}, g);
  el('text', {x:PL+PW/2, y:VH-26, 'text-anchor':'middle', class:'axt'}, g).textContent = '外資投信買賣超金額60日累計排名 → 越右名次越前（最右＝第1名）';
  const yl = el('text', {x:0, y:0, 'text-anchor':'middle', class:'axt', transform:`translate(20 ${PT+PH/2}) rotate(-90)`}, g);
  yl.textContent = '成交金額20日累計佔比排名 ↑ 越上名次越前（最上＝第1名）';
  const c = [[PL+PW, PT-10, 'end', '↗ 買超前段・成交佔比前段'], [PL, PT-10, 'start', '↖ 賣超前段・成交佔比前段'],
             [PL+PW-8, PT+PH-8, 'end', '買超前段・成交佔比後段'], [PL+8, PT+PH-8, 'start', '賣超前段・成交佔比後段']];
  c.forEach(([x,y,a,t]) => { el('text', {x, y, 'text-anchor':a, class:'corner'}, g).textContent = t; });
}

function render(){
  const svg = $('svg'); svg.innerHTML = '';
  drawAxes(svg);
  const labels = [];
  codes.forEach((code, si) => {
    const s = byCode[code]; if (!s) return;
    const col = colorOf(CFG.codes.indexOf(code) >= 0 ? si : si);
    const g = el('g', {}, svg);
    let prev = null;
    for (let i = 0; i <= idx; i++) {
      const xr = s.x[i], yr = s.y[i];
      if (xr == null || yr == null) { prev = null; continue; }
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const X = px(xr), Y = py(yr);
      if (prev) el('line', {x1:prev[0], y1:prev[1], x2:X, y2:Y, stroke:col, 'stroke-width':1.6, 'stroke-opacity':a*0.8}, g);
      prev = [X, Y];
    }
    for (let i = 0; i <= idx; i++) {
      const xr = s.x[i], yr = s.y[i];
      if (xr == null || yr == null) continue;
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const cur = i === idx;
      el('circle', {cx:px(xr), cy:py(yr), r:cur ? 7 : 3.2, fill:col, 'fill-opacity':cur ? 1 : a,
        stroke:cur ? 'var(--panel)' : 'none', 'stroke-width':2, 'data-c':code, 'data-i':i, style:'cursor:pointer'}, g);
      if (cur) labels.push({x:px(xr), y:py(yr), t:`${s.c} ${s.n}`, col});
    }
  });
  labels.forEach(l => {
    const right = l.x < PL + PW - 120;
    const t = el('text', {x: right ? l.x + 11 : l.x - 11, y: Math.max(PT + 14, Math.min(PT + PH - 6, l.y - 9)),
      'text-anchor': right ? 'start' : 'end', class:'lbl', fill:l.col}, svg);
    t.textContent = l.t;
  });
  $('day').value = idx;
  $('dateLabel').textContent = fmtDate(D.dates[idx]);
  renderSide(); renderNotes();
}

function renderNotes(){
  const box = $('notes'); box.innerHTML = '';
  codes.forEach(code => {
    const s = byCode[code]; if (!s) return;
    const xs = s.x.filter(v => v != null), ys = s.y.filter(v => v != null);
    if (xs.length && new Set(xs).size === 1 && new Set(ys).size === 1) {
      const d = document.createElement('div'); d.className = 'note';
      d.textContent = `${s.c} ${s.n}：這 ${xs.length} 個交易日兩項排名都沒變（X＝${xs[0]}、Y＝${ys[0]}），所有點疊在同一個位置。`;
      box.appendChild(d);
    }
  });
}

function renderSide(){
  const side = $('side');
  if (CFG.mode === 'single') {
    const s = byCode[codes[0]]; if (!s) { side.innerHTML = ''; return; }
    let rows = '';
    for (let i = D.dates.length - 1; i >= 0; i--) {
      rows += `<tr data-i="${i}" class="${i === idx ? 'cur' : ''}"><td>${fmtDate(D.dates[i]).slice(5)}</td>` +
        `<td>${s.x[i] ?? '—'}</td><td>${i ? delta(s.x[i-1], s.x[i]) : ''}</td>` +
        `<td>${s.y[i] ?? '—'}</td><td>${i ? delta(s.y[i-1], s.y[i]) : ''}</td></tr>`;
    }
    side.innerHTML = `<h2>${s.c} ${s.n}</h2>
      <div class="kv"><span class="h"></span><span class="h">X 買賣超排名</span><span class="h">Y 成交佔比排名</span>
        <span>${fmtDate(D.dates[0]).slice(5)}</span><span class="num">${s.x[0] ?? '—'}</span><span class="num">${s.y[0] ?? '—'}</span>
        <span>${fmtDate(D.dates[idx]).slice(5)}</span><span class="num">${s.x[idx] ?? '—'}</span><span class="num">${s.y[idx] ?? '—'}</span>
        <span>變化</span><span class="num">${delta(s.x[0], s.x[idx])}</span><span class="num">${delta(s.y[0], s.y[idx])}</span></div>
      <p class="hint">「+」代表名次往第 1 名前進。點表格任一列可跳到那一天。</p>
      <div class="tbl-wrap"><table><thead><tr><th>日期</th><th>X 排名</th><th>較前日</th><th>Y 排名</th><th>較前日</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } else {
    let rows = '';
    codes.forEach((code, si) => {
      const s = byCode[code]; if (!s) return;
      rows += `<tr><td><span class="chip" style="background:${colorOf(si)}"></span>${s.c} ${s.n}</td>` +
        `<td>${s.x[idx] ?? '—'}</td><td>${delta(s.x[0], s.x[idx])}</td><td>${s.y[idx] ?? '—'}</td><td>${delta(s.y[0], s.y[idx])}</td>` +
        `<td><button class="x" data-rm="${code}" aria-label="移除 ${s.n}">×</button></td></tr>`;
    });
    side.innerHTML = `<h2>${fmtDate(D.dates[idx])} 排名</h2>
      <div class="tbl-wrap" style="max-height:none"><table><thead><tr><th>個股</th><th>X</th><th>較${fmtDate(D.dates[0]).slice(5)}</th><th>Y</th><th>較${fmtDate(D.dates[0]).slice(5)}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint">「+」代表名次往第 1 名前進。最多同時比較 8 檔，按 × 移除。</p>`;
  }
}

function stop(){ if (timer) { clearInterval(timer); timer = null; } $('play').textContent = '▶ 播放'; }
function play(){
  if (timer) { stop(); return; }
  if (idx >= D.dates.length - 1) idx = 0;
  $('play').textContent = '❚❚ 暫停';
  render();
  timer = setInterval(() => { if (idx >= D.dates.length - 1) { stop(); return; } idx++; render(); }, +$('speed').value);
}

function setScale(s){ scale = s; $('scLin').setAttribute('aria-pressed', s === 'lin'); $('scLog').setAttribute('aria-pressed', s === 'log'); render(); }

function init(data){
  D = data; M = data.maxRank;
  data.stocks.forEach(s => byCode[s.c] = s);
  const dl = document.createElement('datalist'); dl.id = PFX + 'stocklist';
  dl.innerHTML = data.stocks.map(s => `<option value="${s.c} ${s.n}">`).join('');
  document.body.appendChild(dl);
  $('day').max = data.dates.length - 1; idx = data.dates.length - 1;
  $('sub').textContent = `資料區間 ${fmtDate(data.dates[0])}–${fmtDate(data.dates[data.dates.length-1])}・${data.dates.length} 個交易日・` +
    (CFG.trial ? `試用版僅示範 ${data.stocks.length} 檔權值股（歷史快照）` : `全上市櫃 ${data.stocks.length.toLocaleString()} 檔`);

  $('day').addEventListener('input', e => { stop(); idx = +e.target.value; render(); });
  $('prev').onclick = () => { stop(); if (idx > 0) { idx--; render(); } };
  $('next').onclick = () => { stop(); if (idx < D.dates.length - 1) { idx++; render(); } };
  $('play').onclick = play;
  $('speed').onchange = () => { if (timer) { stop(); play(); } };
  $('scLin').onclick = () => setScale('lin');
  $('scLog').onclick = () => setScale('log');
  $('side').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-i]'); if (tr) { stop(); idx = +tr.dataset.i; render(); }
    const rm = e.target.closest('[data-rm]'); if (rm) { codes = codes.filter(c => c !== rm.dataset.rm); render(); }
  });

  const inp = $('code'), err = $('err');
  const submit = () => {
    const c = lookup(inp.value);
    if (!c) { err.textContent = CFG.trial ? '試用版只有示範的 8 檔，其他個股請到完整版查詢。' : '找不到這個代號或名稱，請重新輸入。'; return; }
    err.textContent = '';
    if (CFG.mode === 'single') { codes = [c]; inp.value = `${c} ${byCode[c].n}`; }
    else {
      if (codes.includes(c)) { err.textContent = '這檔已經在圖上了。'; return; }
      if (codes.length >= 8) { err.textContent = '最多 8 檔，請先移除一檔。'; return; }
      codes.push(c); inp.value = '';
    }
    render();
  };
  $('go').onclick = submit;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  if (CFG.mode === 'single') inp.value = `${codes[0]} ${byCode[codes[0]].n}`;

  const tip = $('tip'), box = $('chartBox');
  $('svg').addEventListener('pointerover', e => {
    const c = e.target.closest('circle[data-c]'); if (!c) return;
    const s = byCode[c.dataset.c], i = +c.dataset.i;
    tip.textContent = `${fmtDate(D.dates[i])}　${s.c} ${s.n}　X ${s.x[i]}／Y ${s.y[i]}`;
    const r = c.getBoundingClientRect(), b = box.getBoundingClientRect();
    tip.style.left = (r.left + r.width / 2 - b.left) + 'px'; tip.style.top = (r.top - b.top) + 'px';
    tip.hidden = false;
  });
  $('svg').addEventListener('pointerout', e => { if (e.target.closest('circle[data-c]')) tip.hidden = true; });
  render();
}

__fetch('data.json').then(r => r.json()).then(init).catch(() => { $('sub').textContent = '資料讀取失敗，請重新整理頁面。'; });

};

/* ── t9 ← BG 09rankgrid ── */
CF_MODS["t9"] = function(ROOT, API){
var PFX = "m9-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

const SHEETS = [['turnover', '成交資金佔比排名'], ['inst', '外資投信買賣超排名']];
const $ = id => __id(id);
let D, target = '';

const norm = s => s.replace(/\*/g, '').trim();
const mmdd = d => d.slice(5).replace('-', '/');

// 1,977 名 × 60 天、兩張表約 24 萬格，全部畫出來會很卡：只畫看得到的列（上下多畫一些），捲動時再補
const BUF = 45, EDGE = 15;
const VG = {}, NG = {}, POS = {};   // NG：名稱去掉 * 的表；POS[key][名稱] = 每一天的名次（沒有排名＝0）
const fitCache = new Map();         // 名稱 → 塞不下時的縮字 class，欄寬或字級改變時清掉重量

function indexSheet(key){
  const { grid } = D[key];
  NG[key] = grid.map(col => col.map(n => n == null ? null : norm(n)));
  const pos = POS[key] = {};
  NG[key].forEach((col, c) => col.forEach((n, r) => { if (n) (pos[n] ||= new Array(grid.length).fill(0))[c] = r + 1; }));
}

function buildSheet(key){
  indexSheet(key);
  const { dates, grid } = D[key];
  const box = $('sheet-' + key);
  box.innerHTML = '<table><colgroup><col class="rk"><col class="dc" span="' + dates.length + '"></colgroup><thead><tr><th class="corner">名次</th>' + dates.map(d => `<th>${mmdd(d)}</th>`).join('') + '</tr></thead><tbody></tbody></table>';
  const tb = box.querySelector('table');
  VG[key] = { box, tb, body: tb.tBodies[0], from: -1, to: -1, rowH: 16, rows: Math.max(...grid.map(c => c.length)) };
  box.addEventListener('scroll', () => renderRows(key));
}

function renderRows(key, force = false){
  const v = VG[key], { dates, grid } = D[key], ng = NG[key], N = v.rows;
  const y = Math.max(0, v.box.scrollTop - v.tb.tHead.offsetHeight);
  const a = Math.floor(y / v.rowH), b = Math.min(N, Math.ceil((y + v.box.clientHeight) / v.rowH));
  if (!force && v.from >= 0 && a >= v.from + (v.from ? EDGE : 0) && b <= v.to - (v.to < N ? EDGE : 0)) return;
  const from = Math.max(0, a - BUF), to = Math.min(N, b + BUF), span = dates.length + 1;
  const sp = n => n > 0 ? `<tr class="sp"><td colspan="${span}" style="height:${n * v.rowH}px"></td></tr>` : '';
  let h = sp(from);
  for (let r = from; r < to; r++) {
    h += `<tr class="r${(r + 1) % 10 ? '' : ' ten'}"><th>${r + 1}</th>`;
    for (let c = 0; c < dates.length; c++) {
      const n = grid[c][r];
      if (n == null) { h += '<td></td>'; continue; }
      const nn = ng[c][r], [hc, ha] = cellMark(nn), cls = [fitCache.get(nn), hc].filter(Boolean).join(' ');
      h += `<td data-n="${nn}"${cls ? ` class="${cls}"` : ''}${ha} title="${mmdd(dates[c])}　第 ${r + 1} 名　${n}">${n}</td>`;
    }
    h += '</tr>';
  }
  v.body.innerHTML = h + sp(N - to);
  v.from = from; v.to = to;
  fit(v.body);
}

// 新出現的名稱量一次寬度，塞不下就縮字（結果記起來，之後同名直接套用）
function fit(root){
  const fresh = [...root.querySelectorAll('td[data-n]')].filter(td => !fitCache.has(td.dataset.n));
  if (!fresh.length) return;
  const over = fresh.filter(td => td.scrollWidth > td.clientWidth);
  over.forEach(td => td.classList.add('tight'));
  const still = over.filter(td => td.scrollWidth > td.clientWidth);
  still.forEach(td => td.classList.add('tighter'));
  // 標色的格子是粗體，量出來會偏寬，不拿來當記錄
  fresh.forEach(td => { if (!td.classList.contains('hl') && td.dataset.k === undefined)
    fitCache.set(td.dataset.n, td.classList.contains('tighter') ? 'tight tighter' : td.classList.contains('tight') ? 'tight' : ''); });
}

function measureRowH(key){
  const v = VG[key], rs = v.body.querySelectorAll('tr.r');
  if (rs.length < 2) return false;
  const h = (rs[rs.length - 1].getBoundingClientRect().bottom - rs[0].getBoundingClientRect().top) / rs.length;
  if (Math.abs(h - v.rowH) < 0.01) return false;
  v.rowH = h; return true;
}

function refresh(){ SHEETS.forEach(([k]) => renderRows(k, true)); }

// 這一檔名次最好的那一格（同名次取最新一天）
function findPos(key, name){
  const p = POS[key][name]; if (!p) return null;
  let r = 0, c = -1;
  p.forEach((x, i) => { if (x && (!r || x < r)) { r = x; c = i; } });
  return c < 0 ? null : { r: r - 1, c };
}

function scrollToCell(key, p){
  const v = VG[key], ths = v.tb.tHead.rows[0].cells;
  const x = ths[p.c + 1].getBoundingClientRect().left - v.tb.getBoundingClientRect().left;
  v.box.scrollTo({ left: Math.max(0, x - 80), top: Math.max(0, v.tb.tHead.offsetHeight + p.r * v.rowH - 60) });
  // 不等捲動事件，直接把另一張對齊、兩張都補畫
  if ($('sync').checked) SHEETS.forEach(([k]) => { const o = VG[k].box; if (o !== v.box) { o.scrollTop = v.box.scrollTop; o.scrollLeft = v.box.scrollLeft; } });
  SHEETS.forEach(([k]) => renderRows(k));
}

function stats(key, name){
  const { dates } = D[key], p = POS[key][name];
  const s = { days: 0, latest: 0, oldest: 0, best: 0, bestDate: '', worst: 0, worstDate: '' };
  if (!p) return s;
  p.forEach((r, c) => {
    if (!r) return;
    s.days++;
    if (!s.best || r < s.best) { s.best = r; s.bestDate = dates[c]; }
    if (r > s.worst) { s.worst = r; s.worstDate = dates[c]; }
  });
  s.latest = p[0]; s.oldest = p[p.length - 1];
  return s;
}

const cellMark = n => n && n === target ? ['hl', ''] : ['', ''];

function resolve(q){
  q = q.trim(); if (!q) return '';
  const code = q.split(/\s+/)[0];
  if (D.codes[code]) return norm(D.codes[code]);
  const n = norm(q.replace(/^\d+[A-Z]?\s+/, ''));
  if (Object.values(D.codes).some(v => norm(v) === n)) return n;
  return null;
}

function summarize(){
  const box = $('summary');
  if (!target) { box.innerHTML = ''; return; }
  box.innerHTML = SHEETS.map(([key, label]) => {
    const { dates } = D[key], s = stats(key, target), rk = x => x ? `第 <span class="num">${x}</span> 名` : '無排名';
    const body = s.days
      ? `${mmdd(dates[0])} <span class="big">${rk(s.latest)}</span>・${mmdd(dates[dates.length - 1])} ${rk(s.oldest)}・最佳第 <span class="num">${s.best}</span> 名（${mmdd(s.bestDate)}）・最差第 <span class="num">${s.worst}</span> 名（${mmdd(s.worstDate)}）`
      : `這 ${dates.length} 天都沒有排名資料`;
    return `<div class="sum"><h3>${label}（共 ${VG[key].rows.toLocaleString()} 名）</h3>${body}</div>`;
  }).join('');
}

// 依字級決定一次顯示幾天：小 20 天、中 12 天、大 8 天
const DAYS_VISIBLE = { s: 20, m: 12, l: 8 };
const RANK_COL = { s: 30, m: 36, l: 44 };
function layout(){
  const size = $('pair').dataset.size;
  ROOT.querySelectorAll('.sheet').forEach(box => {
    const tb = box.querySelector('table'); if (!tb) return;
    const rw = RANK_COL[size];
    const n = tb.querySelector('col.dc').span, want = DAYS_VISIBLE[size];
    const apply = cw => {
      tb.querySelector('col.rk').style.width = rw + 'px';
      tb.querySelector('col.dc').style.width = cw + 'px';
      tb.style.width = (rw + cw * n) + 'px';
    };
    const first = Math.max(20, Math.floor((box.clientWidth - rw) / want));
    apply(first);
    // 排好之後實際量一次（框線會讓每欄多出幾個像素），再校正成剛好塞下指定天數
    const ths = tb.querySelectorAll('thead th');
    const x = el => el.getBoundingClientRect().left - tb.getBoundingClientRect().left;  // 相對表格本身的位置
    const start = x(ths[1]), overhead = (x(ths[2]) - x(ths[1])) - first;
    apply(Math.max(20, Math.floor((box.clientWidth - start) / want) - overhead));
  });
  // 欄寬或字級變了：縮字記錄清掉重量，列高重新量過再重畫
  fitCache.clear();
  SHEETS.forEach(([k]) => { renderRows(k, true); if (measureRowH(k)) renderRows(k, true); });
}

function scrollToMark(){
  // 只捲動表格本身，不捲動整頁；捲到名次最好的那一格
  if (!target) return;
  const keys = $('sync').checked ? ['turnover'] : SHEETS.map(([k]) => k);
  keys.forEach(k => { const p = findPos(k, target); if (p) scrollToCell(k, p); });
}

function toTopLeft(){ ROOT.querySelectorAll('.sheet').forEach(s => { s.scrollTop = 0; s.scrollLeft = 0; }); SHEETS.forEach(([k]) => renderRows(k)); }

function mark(name, scroll = true){
  target = name;
  refresh();
  summarize();
  if (scroll) toTopLeft();
  ROOT.querySelectorAll('.t50grid button').forEach(b => b.setAttribute('aria-pressed', b.dataset.n === name));
}

function submit(){
  const n = resolve($('q').value);
  if (n === '') { $('err').textContent = '請輸入代號或名稱。'; return; }
  if (n === null) { $('err').textContent = '找不到這個代號或名稱，請重新輸入。'; return; }
  $('err').textContent = '';
  mark(n);
}

function codeOfName(n){ return Object.keys(D.codes).find(c => norm(D.codes[c]) === n) || ""; }
const LISTS = { inst: "外資投信買賣超排名", turnover: "成交資金佔比排名" };
function showList(k){
  $("tabI").setAttribute("aria-selected", k === "inst"); $("tabT").setAttribute("aria-selected", k === "turnover");
  $("t50inst").hidden = k !== "inst"; $("t50turnover").hidden = k !== "turnover";
  $("t50title").textContent = `依 ${D[k].dates[0].replace(/-/g, "/")} ${LISTS[k]}排序`;
}
function buildTop50(){
  ["inst", "turnover"].forEach(k => {
    const box = $("t50" + k);
    box.innerHTML = D[k].grid[0].slice(0, 50).map((n, i) => { const nk = norm(n), c = codeOfName(nk);
      return `<button type="button" data-n="${nk}" aria-pressed="false" title="第 ${i + 1} 名　${c} ${n}">` +
        `<span class="rk">${i + 1}</span><span class="cd">${c}</span><span class="nm">${n}</span></button>`; }).join("");
    box.addEventListener("click", e => {
      const b = e.target.closest("button[data-n]"); if (!b) return;
      const c = codeOfName(b.dataset.n);
      $("q").value = c ? `${c} ${D.codes[c]}` : b.dataset.n;
      $("err").textContent = "";
      mark(b.dataset.n);
    });
  });
  $("tabI").onclick = () => showList("inst"); $("tabT").onclick = () => showList("turnover");
  showList("inst");
}

function init(data){
  D = data;
  const dates = D.turnover.dates;
  $('sub').textContent = `資料區間 ${dates[dates.length - 1].replace(/-/g, '/')}–${dates[0].replace(/-/g, '/')}・最近 ${dates.length} 個交易日・每日全部 ${D.turnover.grid[0].length.toLocaleString()} 名`;
  SHEETS.forEach(([k]) => buildSheet(k));
  const seen = new Set([...Object.keys(POS.turnover), ...Object.keys(POS.inst)]);
  const dl = document.createElement('datalist'); dl.id = PFX + 'namelist';
  dl.innerHTML = Object.entries(D.codes).filter(([, n]) => seen.has(norm(n))).map(([c, n]) => `<option value="${c} ${n}">`).join('');
  document.body.appendChild(dl);

  // 同步捲動：捲一張，另一張跟到同樣的位置
  const sheets = [...ROOT.querySelectorAll('.sheet')];
  let syncing = false;
  sheets.forEach(s => s.addEventListener('scroll', () => {
    if (!$('sync').checked || syncing) return;
    syncing = true;
    sheets.forEach(o => { if (o !== s) { o.scrollTop = s.scrollTop; o.scrollLeft = s.scrollLeft; } });
    requestAnimationFrame(() => { syncing = false; });
  }));
  $('sync').onchange = () => { if ($('sync').checked) { const s = sheets[0]; sheets[1].scrollTop = s.scrollTop; sheets[1].scrollLeft = s.scrollLeft; } };
  // 字級切換（記住這位使用者上次選的）
  const setSize = s => {
    $('pair').dataset.size = s;
    ROOT.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', b.dataset.size === s));
    try { localStorage.setItem('rankGridSize', s); } catch (e) {}
  };
  ROOT.querySelectorAll('.seg button').forEach(b => b.onclick = () => { setSize(b.dataset.size); layout(); });
  try { const s = localStorage.getItem('rankGridSize'); if (s) setSize(s); } catch (e) {}
  layout();
  let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(layout, 150); });

  $('go').onclick = submit;
  $('q').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  $('clear').onclick = () => { $('q').value = ''; $('err').textContent = ''; mark(''); };
  ROOT.querySelectorAll('.sheet').forEach(s => s.addEventListener('click', e => {
    const td = e.target.closest('td'); if (!td || !td.dataset.n) return;
    const code = Object.keys(D.codes).find(c => norm(D.codes[c]) === td.dataset.n);
    $('q').value = code ? `${code} ${D.codes[code]}` : td.dataset.n;
    $('err').textContent = '';
    mark(td.dataset.n, false);
  }));

  // 開啟時先建前 50 名清單，預設帶入第 1 名
  buildTop50();
  const first = norm(D.codes["2330"] || D.inst.grid[0][0]), fc = codeOfName(first);
  $('q').value = fc ? `${fc} ${D.codes[fc]}` : first;
  mark(first, false);
  ROOT.querySelectorAll('.sheet').forEach(s => { s.scrollTop = 0; s.scrollLeft = 0; });
}

__fetch('data.json').then(r => r.json()).then(d => { init(d); if (document.fonts) document.fonts.ready.then(layout); }).catch(() => { $('sub').textContent = '資料讀取失敗，請重新整理頁面。'; });

};

/* ── t10 ← BG 10rankgridm ── */
CF_MODS["t10"] = function(ROOT, API){
var PFX = "m10-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

const SHEETS = [['turnover', '成交資金佔比排名'], ['inst', '外資投信買賣超排名']];
const MAX = 8;
const $ = id => __id(id);
let D, picked = [];   // picked: [{ name, code, k }]，k = 顏色編號 0-7

const norm = s => s.replace(/\*/g, '').trim();
const mmdd = d => d.slice(5).replace('-', '/');
const codeOf = name => Object.keys(D.codes).find(c => norm(D.codes[c]) === name) || '';

// 1,977 名 × 60 天、兩張表約 24 萬格，全部畫出來會很卡：只畫看得到的列（上下多畫一些），捲動時再補
const BUF = 45, EDGE = 15;
const VG = {}, NG = {}, POS = {};   // NG：名稱去掉 * 的表；POS[key][名稱] = 每一天的名次（沒有排名＝0）
const fitCache = new Map();         // 名稱 → 塞不下時的縮字 class，欄寬或字級改變時清掉重量

function indexSheet(key){
  const { grid } = D[key];
  NG[key] = grid.map(col => col.map(n => n == null ? null : norm(n)));
  const pos = POS[key] = {};
  NG[key].forEach((col, c) => col.forEach((n, r) => { if (n) (pos[n] ||= new Array(grid.length).fill(0))[c] = r + 1; }));
}

function buildSheet(key){
  indexSheet(key);
  const { dates, grid } = D[key];
  const box = $('sheet-' + key);
  box.innerHTML = '<table class="g"><colgroup><col class="rk"><col class="dc" span="' + dates.length + '"></colgroup><thead><tr><th class="corner">名次</th>' + dates.map(d => `<th>${mmdd(d)}</th>`).join('') + '</tr></thead><tbody></tbody></table>';
  const tb = box.querySelector('table');
  VG[key] = { box, tb, body: tb.tBodies[0], from: -1, to: -1, rowH: 16, rows: Math.max(...grid.map(c => c.length)) };
  box.addEventListener('scroll', () => renderRows(key));
}

function renderRows(key, force = false){
  const v = VG[key], { dates, grid } = D[key], ng = NG[key], N = v.rows;
  const y = Math.max(0, v.box.scrollTop - v.tb.tHead.offsetHeight);
  const a = Math.floor(y / v.rowH), b = Math.min(N, Math.ceil((y + v.box.clientHeight) / v.rowH));
  if (!force && v.from >= 0 && a >= v.from + (v.from ? EDGE : 0) && b <= v.to - (v.to < N ? EDGE : 0)) return;
  const from = Math.max(0, a - BUF), to = Math.min(N, b + BUF), span = dates.length + 1;
  const sp = n => n > 0 ? `<tr class="sp"><td colspan="${span}" style="height:${n * v.rowH}px"></td></tr>` : '';
  let h = sp(from);
  for (let r = from; r < to; r++) {
    h += `<tr class="r${(r + 1) % 10 ? '' : ' ten'}"><th>${r + 1}</th>`;
    for (let c = 0; c < dates.length; c++) {
      const n = grid[c][r];
      if (n == null) { h += '<td></td>'; continue; }
      const nn = ng[c][r], [hc, ha] = cellMark(nn), cls = [fitCache.get(nn), hc].filter(Boolean).join(' ');
      h += `<td data-n="${nn}"${cls ? ` class="${cls}"` : ''}${ha} title="${mmdd(dates[c])}　第 ${r + 1} 名　${n}">${n}</td>`;
    }
    h += '</tr>';
  }
  v.body.innerHTML = h + sp(N - to);
  v.from = from; v.to = to;
  fit(v.body);
}

// 新出現的名稱量一次寬度，塞不下就縮字（結果記起來，之後同名直接套用）
function fit(root){
  const fresh = [...root.querySelectorAll('td[data-n]')].filter(td => !fitCache.has(td.dataset.n));
  if (!fresh.length) return;
  const over = fresh.filter(td => td.scrollWidth > td.clientWidth);
  over.forEach(td => td.classList.add('tight'));
  const still = over.filter(td => td.scrollWidth > td.clientWidth);
  still.forEach(td => td.classList.add('tighter'));
  // 標色的格子是粗體，量出來會偏寬，不拿來當記錄
  fresh.forEach(td => { if (!td.classList.contains('hl') && td.dataset.k === undefined)
    fitCache.set(td.dataset.n, td.classList.contains('tighter') ? 'tight tighter' : td.classList.contains('tight') ? 'tight' : ''); });
}

function measureRowH(key){
  const v = VG[key], rs = v.body.querySelectorAll('tr.r');
  if (rs.length < 2) return false;
  const h = (rs[rs.length - 1].getBoundingClientRect().bottom - rs[0].getBoundingClientRect().top) / rs.length;
  if (Math.abs(h - v.rowH) < 0.01) return false;
  v.rowH = h; return true;
}

function refresh(){ SHEETS.forEach(([k]) => renderRows(k, true)); }

// 這一檔名次最好的那一格（同名次取最新一天）
function findPos(key, name){
  const p = POS[key][name]; if (!p) return null;
  let r = 0, c = -1;
  p.forEach((x, i) => { if (x && (!r || x < r)) { r = x; c = i; } });
  return c < 0 ? null : { r: r - 1, c };
}

function scrollToCell(key, p){
  const v = VG[key], ths = v.tb.tHead.rows[0].cells;
  const x = ths[p.c + 1].getBoundingClientRect().left - v.tb.getBoundingClientRect().left;
  v.box.scrollTo({ left: Math.max(0, x - 80), top: Math.max(0, v.tb.tHead.offsetHeight + p.r * v.rowH - 60) });
  // 不等捲動事件，直接把另一張對齊、兩張都補畫
  if ($('sync').checked) SHEETS.forEach(([k]) => { const o = VG[k].box; if (o !== v.box) { o.scrollTop = v.box.scrollTop; o.scrollLeft = v.box.scrollLeft; } });
  SHEETS.forEach(([k]) => renderRows(k));
}

function stats(key, name){
  const { dates } = D[key], p = POS[key][name];
  const s = { days: 0, latest: 0, oldest: 0, best: 0, bestDate: '', worst: 0, worstDate: '' };
  if (!p) return s;
  p.forEach((r, c) => {
    if (!r) return;
    s.days++;
    if (!s.best || r < s.best) { s.best = r; s.bestDate = dates[c]; }
    if (r > s.worst) { s.worst = r; s.worstDate = dates[c]; }
  });
  s.latest = p[0]; s.oldest = p[p.length - 1];
  return s;
}

let KMAP = new Map();   // 名稱 → 顏色編號
const cellMark = n => KMAP.has(n) ? ['', ` data-k="${KMAP.get(n)}"`] : ['', ''];

// 一個輸入片段 → 股票名稱（代號或名稱都可以）
function resolveToken(tok){
  if (D.codes[tok]) return norm(D.codes[tok]);
  const n = norm(tok);
  return Object.values(D.codes).some(v => norm(v) === n) ? n : null;
}

function renderPicked(){
  const box = $('picked');
  if (!picked.length) {
    box.innerHTML = '<p class="empty">還沒有標示任何個股。在上方輸入股票代號後按「加入」，最多 8 檔。</p>';
    return;
  }
  const dates = D.turnover.dates, total = dates.length, last = mmdd(dates[0]);
  const first = mmdd(dates[total - 1]), f = x => x || '—';
  const cell = s => s.days
    ? `<td class="n">${f(s.latest)}</td><td class="n">${f(s.oldest)}</td><td class="n">${s.best}（${mmdd(s.bestDate)}）</td><td class="n">${s.worst}（${mmdd(s.worstDate)}）</td>`
    : '<td class="n">—</td>'.repeat(4);
  box.innerHTML = `<table class="stat"><thead>
      <tr><th rowspan="2">個股</th><th class="grp" colspan="4">成交資金佔比排名（共 ${VG.turnover.rows.toLocaleString()} 名）</th><th class="grp" colspan="4">外資投信買賣超排名（共 ${VG.inst.rows.toLocaleString()} 名）</th><th rowspan="2"></th></tr>
      <tr><th class="n">${last} 名次</th><th class="n">${first} 名次</th><th class="n">最佳名次</th><th class="n">最差名次</th><th class="n">${last} 名次</th><th class="n">${first} 名次</th><th class="n">最佳名次</th><th class="n">最差名次</th></tr>
    </thead><tbody>` +
    picked.map(p => `<tr><td><span class="chip" style="background:var(--h${p.k})">${p.code} ${p.name}</span></td>` +
      cell(stats('turnover', p.name)) + cell(stats('inst', p.name)) +
      `<td><button class="rm" data-rm="${p.name}" aria-label="移除 ${p.name}">×</button></td></tr>`).join('') +
    '</tbody></table>';
}

function paint(){
  KMAP = new Map(picked.map(p => [p.name, p.k]));
  refresh();
  renderPicked();
}

function freeColor(){
  const used = new Set(picked.map(p => p.k));
  for (let k = 0; k < MAX; k++) if (!used.has(k)) return k;
  return -1;
}

// 加入多檔；回傳沒加進去的原因
function add(names, jump = true){
  const msgs = [];
  let lastAdded = null;
  names.forEach(n => {
    if (picked.some(p => p.name === n)) return;
    if (picked.length >= MAX) { msgs.push(`已經有 ${MAX} 檔，${n} 沒有加入，請先移除一檔`); return; }
    picked.push({ name: n, code: codeOf(n), k: freeColor() });
    lastAdded = n;
  });
  paint();
  if (lastAdded && jump) jumpTo(lastAdded);
  return msgs;
}

function remove(name){
  picked = picked.filter(p => p.name !== name);
  paint();
}

function submit(){
  const raw = $('q').value.trim();
  if (!raw) { $('err').textContent = '請輸入股票代號。'; return; }
  const toks = raw.split(/[\s,，、;；]+/).filter(Boolean);
  const names = [], bad = [];
  toks.forEach(tok => {
    const n = resolveToken(tok);
    if (n) { if (!names.includes(n)) names.push(n); }
    else bad.push(tok);
  });
  // 「3443 創意」這種代號加名稱的寫法：名稱已經由代號解析過，不算錯誤
  const badReal = bad.filter(tok => !names.includes(norm(tok)));
  const msgs = add(names);
  if (badReal.length) msgs.unshift(`找不到：${badReal.join('、')}`);
  $('err').textContent = msgs.join('；');
  if (!msgs.length) $('q').value = '';
}

// 依字級決定一次顯示幾天：小 20 天、中 12 天、大 8 天
const DAYS_VISIBLE = { s: 20, m: 12, l: 8 };
const RANK_COL = { s: 30, m: 36, l: 44 };
function layout(){
  const size = $('pair').dataset.size;
  ROOT.querySelectorAll('.sheet').forEach(box => {
    const tb = box.querySelector('table'); if (!tb) return;
    const rw = RANK_COL[size];
    const n = tb.querySelector('col.dc').span, want = DAYS_VISIBLE[size];
    const apply = cw => {
      tb.querySelector('col.rk').style.width = rw + 'px';
      tb.querySelector('col.dc').style.width = cw + 'px';
      tb.style.width = (rw + cw * n) + 'px';
    };
    const first = Math.max(20, Math.floor((box.clientWidth - rw) / want));
    apply(first);
    // 排好之後實際量一次（框線會讓每欄多出幾個像素），再校正成剛好塞下指定天數
    const ths = tb.querySelectorAll('thead th');
    const x = el => el.getBoundingClientRect().left - tb.getBoundingClientRect().left;  // 相對表格本身的位置
    const start = x(ths[1]), overhead = (x(ths[2]) - x(ths[1])) - first;
    apply(Math.max(20, Math.floor((box.clientWidth - start) / want) - overhead));
  });
  // 欄寬或字級變了：縮字記錄清掉重量，列高重新量過再重畫
  fitCache.clear();
  SHEETS.forEach(([k]) => { renderRows(k, true); if (measureRowH(k)) renderRows(k, true); });
}

// 只捲動表格本身，不捲動整頁；捲到這一檔名次最好的那一格
function jumpTo(name){
  if ($('sync').checked) { const p = findPos('turnover', name) || findPos('inst', name); if (p) scrollToCell('turnover', p); return; }
  SHEETS.forEach(([k]) => { const p = findPos(k, name); if (p) scrollToCell(k, p); });
}

function init(data){
  D = data;
  const dates = D.turnover.dates;
  $('sub').textContent = `資料區間 ${dates[dates.length - 1].replace(/-/g, '/')}–${dates[0].replace(/-/g, '/')}・最近 ${dates.length} 個交易日・每日全部 ${D.turnover.grid[0].length.toLocaleString()} 名`;
  SHEETS.forEach(([k]) => buildSheet(k));
  const seen = new Set([...Object.keys(POS.turnover), ...Object.keys(POS.inst)]);
  const dl = document.createElement('datalist'); dl.id = PFX + 'namelist';
  dl.innerHTML = Object.entries(D.codes).filter(([, n]) => seen.has(norm(n))).map(([c, n]) => `<option value="${c}">${c} ${n}</option>`).join('');
  document.body.appendChild(dl);

  // 同步捲動：捲一張，另一張跟到同樣的位置
  const sheets = [...ROOT.querySelectorAll('.sheet')];
  let syncing = false;
  sheets.forEach(s => s.addEventListener('scroll', () => {
    if (!$('sync').checked || syncing) return;
    syncing = true;
    sheets.forEach(o => { if (o !== s) { o.scrollTop = s.scrollTop; o.scrollLeft = s.scrollLeft; } });
    requestAnimationFrame(() => { syncing = false; });
  }));
  $('sync').onchange = () => { if ($('sync').checked) { const s = sheets[0]; sheets[1].scrollTop = s.scrollTop; sheets[1].scrollLeft = s.scrollLeft; } };

  // 字級切換（記住這位使用者上次選的）
  const setSize = s => {
    $('pair').dataset.size = s;
    ROOT.querySelectorAll('.seg button').forEach(b => b.setAttribute('aria-pressed', b.dataset.size === s));
    try { localStorage.setItem('rankGridMultiSize', s); } catch (e) {}
  };
  ROOT.querySelectorAll('.seg button').forEach(b => b.onclick = () => { setSize(b.dataset.size); layout(); });
  try { const s = localStorage.getItem('rankGridMultiSize'); if (s) setSize(s); } catch (e) {}
  layout();
  let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(layout, 150); });

  $('go').onclick = submit;
  $('q').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  $('clear').onclick = () => { picked = []; $('q').value = ''; $('err').textContent = ''; paint(); };
  $('picked').addEventListener('click', e => { const b = e.target.closest('[data-rm]'); if (b) { $('err').textContent = ''; remove(b.dataset.rm); } });
  sheets.forEach(s => s.addEventListener('click', e => {
    const td = e.target.closest('td'); if (!td || !td.dataset.n) return;
    $('err').textContent = '';
    if (td.dataset.k !== undefined) { remove(td.dataset.n); return; }
    const msgs = add([td.dataset.n], false);
    $('err').textContent = msgs.join('；');
  }));

  // 開啟時先放 6 檔示範多檔標示效果（僅示範操作，非推薦），使用者可自行移除、改輸入其他代號
  add(['創意', '奇鋐', '南亞科', '欣興', '鴻海', '長榮']);
}

__fetch('data.json').then(r => r.json()).then(d => { init(d); if (document.fonts) document.fonts.ready.then(layout); }).catch(() => { $('sub').textContent = '資料讀取失敗，請重新整理頁面。'; });

};

/* ── t11 ← BG 11valuetrail ── */
CF_MODS["t11"] = function(ROOT, API){
var PFX = "m11-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

const CFG = {"mode": "single", "codes": ["2330"]};
const NS = 'http://www.w3.org/2000/svg';
const VW = 660, VH = 636, PL = 70, PR = 22, PT = 38, PB = 70;
const PW = VW - PL - PR, PH = VH - PT - PB;
const XC = 10;            // 對稱對數的線性區寬度（億）
const YFLOOR = 0.01;      // 對數 Y 軸的下限（億），低於此值畫在底部
const $ = id => __id(id);
let D, byCode = {}, idx = 59, scale = 'log', range = 'fit', timer = null, AVGS = [];
let codes = CFG.codes.slice();
let dom = {x0:0, x1:1, y0:0, y1:1};

const fmtDate = s => s.replace(/-/g,'/');
const ash = v => Math.asinh(v / XC);
const ylog = v => Math.log10(Math.max(v, YFLOOR));
function fx(v){ return scale === 'lin' ? v : ash(v); }
function fy(v){ return scale === 'lin' ? v : ylog(v); }
function px(v){ return PL + (fx(v) - fx(dom.x0)) / (fx(dom.x1) - fx(dom.x0)) * PW; }
function py(v){ return PT + (1 - (fy(v) - fy(dom.y0)) / (fy(dom.y1) - fy(dom.y0))) * PH; }
function el(tag, attrs, parent){ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function colorOf(i){ return CFG.mode === 'single' ? 'var(--accent)' : `var(--s${(i % 8) + 1})`; }
function fX(v){ if (v == null) return '—'; const a = Math.abs(v); return (a >= 100 ? Math.round(v).toLocaleString() : v.toFixed(a >= 10 ? 1 : 2)); }
function fY(v){ return fX(v); }
function dX(a, b){ if (a == null || b == null) return '<span class="dn">—</span>'; const d = b - a; if (Math.abs(d) < 0.005) return '<span class="dn">0</span>'; return d > 0 ? `<span class="up">+${fX(d)}</span>` : `<span class="dn">${fX(d)}</span>`; }
function dY(a, b){ return dX(a, b); }
function lookup(q){
  q = q.trim(); if (!q) return null;
  const code = q.split(/\s+/)[0];
  if (byCode[code]) return code;
  const hit = D.stocks.find(s => s.n === q || s.n.replace('*','') === q);
  return hit ? hit.c : null;
}

// 座標範圍：全市場＝所有個股 60 天的極值；依所選個股＝所選個股 60 天的極值再留邊
function computeDomain(){
  const list = range === 'all' ? D.stocks : codes.map(c => byCode[c]).filter(Boolean);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  list.forEach(s => {
    s.x.forEach(v => { if (v != null) { x0 = Math.min(x0, v); x1 = Math.max(x1, v); } });
    s.y.forEach(v => { if (v != null) { y0 = Math.min(y0, v); y1 = Math.max(y1, v); } });
  });
  if (!isFinite(x0)) { x0 = -10; x1 = 10; y0 = 0.01; y1 = 1; }
  x0 = Math.min(x0, 0); x1 = Math.max(x1, 0);           // 一定看得到 0（買賣超分界）
  if (range === 'fit') { const a0 = Math.min(...AVGS), a1 = Math.max(...AVGS); y0 = Math.min(y0, a0); y1 = Math.max(y1, a1); }
  if (scale === 'lin') {
    const px_ = (x1 - x0) * 0.06 || 1, py_ = (y1 - y0) * 0.08 || 0.01;
    dom = {x0:x0 - px_, x1:x1 + px_, y0:Math.max(0, y0 - py_), y1:y1 + py_};
  } else {
    const a0 = ash(x0), a1 = ash(x1), pad = (a1 - a0) * 0.06 || 0.5;
    const l0 = ylog(y0), l1 = ylog(y1), padY = Math.max((l1 - l0) * 0.08, 0.08);
    dom = {x0:XC * Math.sinh(a0 - pad), x1:XC * Math.sinh(a1 + pad), y0:Math.pow(10, l0 - padY), y1:Math.pow(10, l1 + padY)};
  }
}

function niceStep(span, n){ const raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; }
function linTicks(a, b, n){ const st = niceStep(b - a, n), out = []; for (let v = Math.ceil(a / st) * st; v <= b + st * 1e-9; v += st) out.push(+v.toPrecision(12)); return out; }
function thin(ticks, pos, gap){ // 依像素間距刪掉太擠的刻度，0 優先保留
  const keep = []; const sorted = ticks.slice().sort((p, q) => (q === 0) - (p === 0));
  sorted.forEach(t => { if (keep.every(k => Math.abs(pos(k) - pos(t)) >= gap)) keep.push(t); });
  return keep;
}
function xTicks(){
  if (scale === 'lin') return linTicks(dom.x0, dom.x1, 7);
  const base = [0]; [1,2,5].forEach(m => [1,10,100,1000,10000].forEach(p => { base.push(m * p, -m * p); }));
  return thin(base.filter(v => v >= dom.x0 && v <= dom.x1), px, 42);
}
function yTicks(){
  if (scale === 'lin') return linTicks(dom.y0, dom.y1, 7);
  const base = []; [1,2,5].forEach(m => [0.01,0.1,1,10,100,1000,10000].forEach(p => base.push(+(m * p).toPrecision(6))));
  return thin(base.filter(v => v >= dom.y0 && v <= dom.y1), py, 26);
}

function drawAxes(svg){
  const g = el('g', {}, svg);
  el('rect', {x:PL, y:PT, width:PW, height:PH, fill:'none', stroke:'var(--line)'}, g);
  xTicks().forEach(t => {
    const x = px(t);
    el('line', {x1:x, x2:x, y1:PT, y2:PT+PH, stroke:'var(--grid)'}, g);
    el('text', {x, y:PT+PH+16, 'text-anchor':'middle', class:'tick'}, g).textContent = t.toLocaleString();
  });
  yTicks().forEach(t => {
    const y = py(t);
    el('line', {x1:PL, x2:PL+PW, y1:y, y2:y, stroke:'var(--grid)'}, g);
    el('text', {x:PL-8, y:y+4, 'text-anchor':'end', class:'tick'}, g).textContent = t.toLocaleString();
  });
  el('line', {x1:px(0), x2:px(0), y1:PT, y2:PT+PH, stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.6}, g);
  const AVG = AVGS[idx];
  if (AVG >= dom.y0 && AVG <= dom.y1) {
    const ya = py(AVG);
    el('line', {x1:PL, x2:PL+PW, y1:ya, y2:ya, stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.45}, g);
    el('text', {x:PL+6, y:ya-5, class:'corner'}, g).textContent = `全市場平均每檔 ${fY(AVG)} 億`;
  }
  el('text', {x:PL+PW/2, y:VH-26, 'text-anchor':'middle', class:'axt'}, g).textContent = '外資投信買賣超金額60日累計（億元）→ 越右買超越多';
  const yl = el('text', {x:0, y:0, 'text-anchor':'middle', class:'axt', transform:`translate(18 ${PT+PH/2}) rotate(-90)`}, g);
  yl.textContent = '成交金額20日累計（億元）↑ 越上成交越大';
  const c = [[PL+PW, PT-10, 'end', '↗ 買超・成交金額大'], [PL, PT-10, 'start', '↖ 賣超・成交金額大'],
             [PL+PW-8, PT+PH-8, 'end', '買超・成交金額小'], [PL+8, PT+PH-8, 'start', '賣超・成交金額小']];
  c.forEach(([x,y,a,t]) => { el('text', {x, y, 'text-anchor':a, class:'corner'}, g).textContent = t; });
}

function render(){
  const svg = $('svg'); svg.innerHTML = '';
  drawAxes(svg);
  const clip = el('clipPath', {id:'plot'}, el('defs', {}, svg));
  el('rect', {x:PL-8, y:PT-8, width:PW+16, height:PH+16}, clip);
  const layer = el('g', {'clip-path':'url(#plot)'}, svg);
  const labels = [];
  codes.forEach((code, si) => {
    const s = byCode[code]; if (!s) return;
    const col = colorOf(si);
    const g = el('g', {}, layer);
    let prev = null;
    for (let i = 0; i <= idx; i++) {
      const xv = s.x[i], yv = s.y[i];
      if (xv == null || yv == null) { prev = null; continue; }
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const X = px(xv), Y = py(yv);
      if (prev) el('line', {x1:prev[0], y1:prev[1], x2:X, y2:Y, stroke:col, 'stroke-width':1.6, 'stroke-opacity':a*0.8}, g);
      prev = [X, Y];
    }
    for (let i = 0; i <= idx; i++) {
      const xv = s.x[i], yv = s.y[i];
      if (xv == null || yv == null) continue;
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const cur = i === idx;
      el('circle', {cx:px(xv), cy:py(yv), r:cur ? 7 : 3.2, fill:col, 'fill-opacity':cur ? 1 : a,
        stroke:cur ? 'var(--panel)' : 'none', 'stroke-width':2, 'data-c':code, 'data-i':i, style:'cursor:pointer'}, g);
      if (cur) labels.push({x:px(xv), y:py(yv), t:`${s.c} ${s.n}`, col});
    }
  });
  labels.forEach(l => {
    const right = l.x < PL + PW - 120;
    const t = el('text', {x: right ? l.x + 11 : l.x - 11, y: Math.max(PT + 14, Math.min(PT + PH - 6, l.y - 9)),
      'text-anchor': right ? 'start' : 'end', class:'lbl', fill:l.col}, svg);
    t.textContent = l.t;
  });
  $('day').value = idx;
  $('dateLabel').textContent = fmtDate(D.dates[idx]);
  renderSide(); syncTop50();
}

function renderSide(){
  const side = $('side');
  const d0 = fmtDate(D.dates[0]).slice(5), di = fmtDate(D.dates[idx]).slice(5);
  if (CFG.mode === 'single') {
    const s = byCode[codes[0]]; if (!s) { side.innerHTML = ''; return; }
    let rows = '';
    for (let i = D.dates.length - 1; i >= 0; i--) {
      rows += `<tr data-i="${i}" class="${i === idx ? 'cur' : ''}"><td>${fmtDate(D.dates[i]).slice(5)}</td>` +
        `<td>${fX(s.x[i])}</td><td>${i ? dX(s.x[i-1], s.x[i]) : ''}</td>` +
        `<td>${fY(s.y[i])}</td><td>${i ? dY(s.y[i-1], s.y[i]) : ''}</td></tr>`;
    }
    side.innerHTML = `<h2>${s.c} ${s.n}</h2>
      <div class="kv"><span class="h"></span><span class="h">X 買賣超（億）</span><span class="h">Y 20日成交（億）</span>
        <span>${d0}</span><span class="num">${fX(s.x[0])}</span><span class="num">${fY(s.y[0])}</span>
        <span>${di}</span><span class="num">${fX(s.x[idx])}</span><span class="num">${fY(s.y[idx])}</span>
        <span>變化</span><span class="num">${dX(s.x[0], s.x[idx])}</span><span class="num">${dY(s.y[0], s.y[idx])}</span>
        <span>${di} 名次</span><span class="num">${s.xr[idx] ?? '—'}</span><span class="num">${s.yr[idx] ?? '—'}</span></div>
      <p class="hint">X、Y 的單位都是億元。名次是全市場 ${D.maxRank.toLocaleString()} 檔中的排名（第 1 名＝買超最多／成交金額最大）。點表格任一列可跳到那一天。</p>
      <div class="tbl-wrap"><table><thead><tr><th>日期</th><th>X 億元</th><th>較前日</th><th>Y 億元</th><th>較前日</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } else {
    let rows = '';
    codes.forEach((code, si) => {
      const s = byCode[code]; if (!s) return;
      rows += `<tr><td><span class="chip" style="background:${colorOf(si)}"></span>${s.c} ${s.n}</td>` +
        `<td>${fX(s.x[idx])}</td><td>${dX(s.x[0], s.x[idx])}</td><td>${fY(s.y[idx])}</td><td>${dY(s.y[0], s.y[idx])}</td>` +
        `<td><button class="x" data-rm="${code}" aria-label="移除 ${s.n}">×</button></td></tr>`;
    });
    side.innerHTML = `<h2>${fmtDate(D.dates[idx])} 數值</h2>
      <div class="tbl-wrap" style="max-height:none"><table><thead><tr><th>個股</th><th>X 億元</th><th>較${d0}</th><th>Y 億元</th><th>較${d0}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint">X、Y 的單位都是億元。最多同時比較 8 檔，按 × 移除。</p>`;
  }
}

// 前 50 名快選（只在單檔版）：x＝法人買超（X 名次）、y＝20日成交金額（Y 名次），都取資料最後一天
const LISTS = { x: ['xr', '外資投信買賣超金額60日累計', v => fX(v)], y: ['yr', '成交金額20日累計', v => fY(v)] };
function listTop(k){
  const last = D.dates.length - 1, rk = LISTS[k][0];
  return D.stocks.filter(s => s[rk][last] != null).sort((a, b) => a[rk][last] - b[rk][last]).slice(0, 50);
}
function syncTop50(){ ROOT.querySelectorAll('.t50grid button').forEach(b => b.setAttribute('aria-pressed', b.dataset.c === codes[0])); }
function pick(c, autoplay){
  stop();
  codes = [c];
  $('code').value = `${c} ${byCode[c].n}`;
  $('err').textContent = '';
  computeDomain();
  if (autoplay) { idx = 0; play(); } else render();
}
function showList(k){
  $('tabX').setAttribute('aria-selected', k === 'x'); $('tabY').setAttribute('aria-selected', k === 'y');
  $('t50x').hidden = k !== 'x'; $('t50y').hidden = k !== 'y';
  $('t50title').textContent = `依 ${fmtDate(D.dates[D.dates.length - 1])}「${LISTS[k][1]}」由大到小`;
}
function buildTop50(){
  if (!$('t50x')) return;
  const last = D.dates.length - 1;
  ['x', 'y'].forEach(k => {
    const [rk, , f] = LISTS[k];
    $('t50' + k).innerHTML = listTop(k).map(s => `<button type="button" data-c="${s.c}" aria-pressed="false" title="第 ${s[rk][last]} 名　${s.c} ${s.n}　${f(s[k][last])} 億">` +
      `<span class="rk">${s[rk][last]}</span><span class="cd">${s.c}</span><span class="nm">${s.n}</span></button>`).join('');
    $('t50' + k).addEventListener('click', e => { const b = e.target.closest('button[data-c]'); if (b) pick(b.dataset.c, true); });
  });
  $('tabX').onclick = () => showList('x'); $('tabY').onclick = () => showList('y');
  $('t50date').textContent = fmtDate(D.dates[last]).slice(5);
  showList('x');
}

function stop(){ if (timer) { clearInterval(timer); timer = null; } $('play').textContent = '▶ 播放'; }
function play(){
  if (timer) { stop(); return; }
  if (idx >= D.dates.length - 1) idx = 0;
  $('play').textContent = '❚❚ 暫停';
  render();
  timer = setInterval(() => { if (idx >= D.dates.length - 1) { stop(); return; } idx++; render(); }, +$('speed').value);
}
function refresh(){ computeDomain(); render(); }
function setScale(s){ scale = s; $('scLin').setAttribute('aria-pressed', s === 'lin'); $('scLog').setAttribute('aria-pressed', s === 'log'); refresh(); }
function setRange(r){ range = r; $('rgAll').setAttribute('aria-pressed', r === 'all'); $('rgFit').setAttribute('aria-pressed', r === 'fit'); refresh(); }

function init(data){
  D = data;
  data.stocks.forEach(s => byCode[s.c] = s);
  AVGS = data.avgY;
  codes = codes.filter(c => byCode[c]);
  const dl = document.createElement('datalist'); dl.id = PFX + 'stocklist';
  dl.innerHTML = data.stocks.map(s => `<option value="${s.c} ${s.n}">`).join('');
  document.body.appendChild(dl);
  $('day').max = data.dates.length - 1; idx = data.dates.length - 1;
  $('sub').textContent = `資料區間 ${fmtDate(data.dates[0])}–${fmtDate(data.dates[data.dates.length-1])}・${data.dates.length} 個交易日・全上市櫃 ${data.stocks.length.toLocaleString()} 檔`;

  $('day').addEventListener('input', e => { stop(); idx = +e.target.value; render(); });
  $('prev').onclick = () => { stop(); if (idx > 0) { idx--; render(); } };
  $('next').onclick = () => { stop(); if (idx < D.dates.length - 1) { idx++; render(); } };
  $('play').onclick = play;
  $('speed').onchange = () => { if (timer) { stop(); play(); } };
  $('scLin').onclick = () => setScale('lin');
  $('scLog').onclick = () => setScale('log');
  $('rgFit').onclick = () => setRange('fit');
  $('rgAll').onclick = () => setRange('all');
  $('side').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-i]'); if (tr) { stop(); idx = +tr.dataset.i; render(); }
    const rm = e.target.closest('[data-rm]'); if (rm) { codes = codes.filter(c => c !== rm.dataset.rm); refresh(); }
  });

  const inp = $('code'), err = $('err');
  const submit = () => {
    const c = lookup(inp.value);
    if (!c) { err.textContent = '找不到這個代號或名稱，請重新輸入。'; return; }
    err.textContent = '';
    if (CFG.mode === 'single') { pick(c, true); return; }
    else {
      if (codes.includes(c)) { err.textContent = '這檔已經在圖上了。'; return; }
      if (codes.length >= 8) { err.textContent = '最多 8 檔，請先移除一檔。'; return; }
      codes.push(c); inp.value = '';
    }
    refresh();
  };
  buildTop50();
  $('go').onclick = submit;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  if (CFG.mode === 'single' && codes[0]) inp.value = `${codes[0]} ${byCode[codes[0]].n}`;

  const tip = $('tip'), box = $('chartBox');
  $('svg').addEventListener('pointerover', e => {
    const c = e.target.closest('circle[data-c]'); if (!c) return;
    const s = byCode[c.dataset.c], i = +c.dataset.i;
    tip.textContent = `${fmtDate(D.dates[i])}　${s.c} ${s.n}　X ${fX(s.x[i])} 億（第 ${s.xr[i] ?? '—'} 名）／Y ${fY(s.y[i])} 億（第 ${s.yr[i] ?? '—'} 名）`;
    const r = c.getBoundingClientRect(), b = box.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(r.left + r.width / 2 - b.left, 150), b.width - 150) + 'px'; tip.style.top = (r.top - b.top) + 'px';
    tip.hidden = false;
  });
  $('svg').addEventListener('pointerout', e => { if (e.target.closest('circle[data-c]')) tip.hidden = true; });
  refresh();
}

__fetch('data.json').then(r => r.json()).then(init).catch(() => { $('sub').textContent = '資料讀取失敗，請重新整理頁面。'; });

};

/* ── t12 ← BG 12valuecmp ── */
CF_MODS["t12"] = function(ROOT, API){
var PFX = "m12-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

const CFG = {"mode": "compare", "codes": ["2330", "3037", "3017", "2454", "2327", "2317"]};
const NS = 'http://www.w3.org/2000/svg';
const VW = 660, VH = 636, PL = 70, PR = 22, PT = 38, PB = 70;
const PW = VW - PL - PR, PH = VH - PT - PB;
const XC = 10;            // 對稱對數的線性區寬度（億）
const YFLOOR = 0.01;      // 對數 Y 軸的下限（億），低於此值畫在底部
const $ = id => __id(id);
let D, byCode = {}, idx = 59, scale = 'log', range = 'fit', timer = null, AVGS = [];
let codes = CFG.codes.slice();
let dom = {x0:0, x1:1, y0:0, y1:1};

const fmtDate = s => s.replace(/-/g,'/');
const ash = v => Math.asinh(v / XC);
const ylog = v => Math.log10(Math.max(v, YFLOOR));
function fx(v){ return scale === 'lin' ? v : ash(v); }
function fy(v){ return scale === 'lin' ? v : ylog(v); }
function px(v){ return PL + (fx(v) - fx(dom.x0)) / (fx(dom.x1) - fx(dom.x0)) * PW; }
function py(v){ return PT + (1 - (fy(v) - fy(dom.y0)) / (fy(dom.y1) - fy(dom.y0))) * PH; }
function el(tag, attrs, parent){ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function colorOf(i){ return CFG.mode === 'single' ? 'var(--accent)' : `var(--s${(i % 8) + 1})`; }
function fX(v){ if (v == null) return '—'; const a = Math.abs(v); return (a >= 100 ? Math.round(v).toLocaleString() : v.toFixed(a >= 10 ? 1 : 2)); }
function fY(v){ return fX(v); }
function dX(a, b){ if (a == null || b == null) return '<span class="dn">—</span>'; const d = b - a; if (Math.abs(d) < 0.005) return '<span class="dn">0</span>'; return d > 0 ? `<span class="up">+${fX(d)}</span>` : `<span class="dn">${fX(d)}</span>`; }
function dY(a, b){ return dX(a, b); }
function lookup(q){
  q = q.trim(); if (!q) return null;
  const code = q.split(/\s+/)[0];
  if (byCode[code]) return code;
  const hit = D.stocks.find(s => s.n === q || s.n.replace('*','') === q);
  return hit ? hit.c : null;
}

// 座標範圍：全市場＝所有個股 60 天的極值；依所選個股＝所選個股 60 天的極值再留邊
function computeDomain(){
  const list = range === 'all' ? D.stocks : codes.map(c => byCode[c]).filter(Boolean);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  list.forEach(s => {
    s.x.forEach(v => { if (v != null) { x0 = Math.min(x0, v); x1 = Math.max(x1, v); } });
    s.y.forEach(v => { if (v != null) { y0 = Math.min(y0, v); y1 = Math.max(y1, v); } });
  });
  if (!isFinite(x0)) { x0 = -10; x1 = 10; y0 = 0.01; y1 = 1; }
  x0 = Math.min(x0, 0); x1 = Math.max(x1, 0);           // 一定看得到 0（買賣超分界）
  if (range === 'fit') { const a0 = Math.min(...AVGS), a1 = Math.max(...AVGS); y0 = Math.min(y0, a0); y1 = Math.max(y1, a1); }
  if (scale === 'lin') {
    const px_ = (x1 - x0) * 0.06 || 1, py_ = (y1 - y0) * 0.08 || 0.01;
    dom = {x0:x0 - px_, x1:x1 + px_, y0:Math.max(0, y0 - py_), y1:y1 + py_};
  } else {
    const a0 = ash(x0), a1 = ash(x1), pad = (a1 - a0) * 0.06 || 0.5;
    const l0 = ylog(y0), l1 = ylog(y1), padY = Math.max((l1 - l0) * 0.08, 0.08);
    dom = {x0:XC * Math.sinh(a0 - pad), x1:XC * Math.sinh(a1 + pad), y0:Math.pow(10, l0 - padY), y1:Math.pow(10, l1 + padY)};
  }
}

function niceStep(span, n){ const raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p; return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p; }
function linTicks(a, b, n){ const st = niceStep(b - a, n), out = []; for (let v = Math.ceil(a / st) * st; v <= b + st * 1e-9; v += st) out.push(+v.toPrecision(12)); return out; }
function thin(ticks, pos, gap){ // 依像素間距刪掉太擠的刻度，0 優先保留
  const keep = []; const sorted = ticks.slice().sort((p, q) => (q === 0) - (p === 0));
  sorted.forEach(t => { if (keep.every(k => Math.abs(pos(k) - pos(t)) >= gap)) keep.push(t); });
  return keep;
}
function xTicks(){
  if (scale === 'lin') return linTicks(dom.x0, dom.x1, 7);
  const base = [0]; [1,2,5].forEach(m => [1,10,100,1000,10000].forEach(p => { base.push(m * p, -m * p); }));
  return thin(base.filter(v => v >= dom.x0 && v <= dom.x1), px, 42);
}
function yTicks(){
  if (scale === 'lin') return linTicks(dom.y0, dom.y1, 7);
  const base = []; [1,2,5].forEach(m => [0.01,0.1,1,10,100,1000,10000].forEach(p => base.push(+(m * p).toPrecision(6))));
  return thin(base.filter(v => v >= dom.y0 && v <= dom.y1), py, 26);
}

function drawAxes(svg){
  const g = el('g', {}, svg);
  el('rect', {x:PL, y:PT, width:PW, height:PH, fill:'none', stroke:'var(--line)'}, g);
  xTicks().forEach(t => {
    const x = px(t);
    el('line', {x1:x, x2:x, y1:PT, y2:PT+PH, stroke:'var(--grid)'}, g);
    el('text', {x, y:PT+PH+16, 'text-anchor':'middle', class:'tick'}, g).textContent = t.toLocaleString();
  });
  yTicks().forEach(t => {
    const y = py(t);
    el('line', {x1:PL, x2:PL+PW, y1:y, y2:y, stroke:'var(--grid)'}, g);
    el('text', {x:PL-8, y:y+4, 'text-anchor':'end', class:'tick'}, g).textContent = t.toLocaleString();
  });
  el('line', {x1:px(0), x2:px(0), y1:PT, y2:PT+PH, stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.6}, g);
  const AVG = AVGS[idx];
  if (AVG >= dom.y0 && AVG <= dom.y1) {
    const ya = py(AVG);
    el('line', {x1:PL, x2:PL+PW, y1:ya, y2:ya, stroke:'var(--muted)', 'stroke-dasharray':'3 4', 'stroke-opacity':.45}, g);
    el('text', {x:PL+6, y:ya-5, class:'corner'}, g).textContent = `全市場平均每檔 ${fY(AVG)} 億`;
  }
  el('text', {x:PL+PW/2, y:VH-26, 'text-anchor':'middle', class:'axt'}, g).textContent = '外資投信買賣超金額60日累計（億元）→ 越右買超越多';
  const yl = el('text', {x:0, y:0, 'text-anchor':'middle', class:'axt', transform:`translate(18 ${PT+PH/2}) rotate(-90)`}, g);
  yl.textContent = '成交金額20日累計（億元）↑ 越上成交越大';
  const c = [[PL+PW, PT-10, 'end', '↗ 買超・成交金額大'], [PL, PT-10, 'start', '↖ 賣超・成交金額大'],
             [PL+PW-8, PT+PH-8, 'end', '買超・成交金額小'], [PL+8, PT+PH-8, 'start', '賣超・成交金額小']];
  c.forEach(([x,y,a,t]) => { el('text', {x, y, 'text-anchor':a, class:'corner'}, g).textContent = t; });
}

function render(){
  const svg = $('svg'); svg.innerHTML = '';
  drawAxes(svg);
  const clip = el('clipPath', {id:'plot'}, el('defs', {}, svg));
  el('rect', {x:PL-8, y:PT-8, width:PW+16, height:PH+16}, clip);
  const layer = el('g', {'clip-path':'url(#plot)'}, svg);
  const labels = [];
  codes.forEach((code, si) => {
    const s = byCode[code]; if (!s) return;
    const col = colorOf(si);
    const g = el('g', {}, layer);
    let prev = null;
    for (let i = 0; i <= idx; i++) {
      const xv = s.x[i], yv = s.y[i];
      if (xv == null || yv == null) { prev = null; continue; }
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const X = px(xv), Y = py(yv);
      if (prev) el('line', {x1:prev[0], y1:prev[1], x2:X, y2:Y, stroke:col, 'stroke-width':1.6, 'stroke-opacity':a*0.8}, g);
      prev = [X, Y];
    }
    for (let i = 0; i <= idx; i++) {
      const xv = s.x[i], yv = s.y[i];
      if (xv == null || yv == null) continue;
      const a = idx === 0 ? 1 : 0.14 + 0.86 * (i / idx);
      const cur = i === idx;
      el('circle', {cx:px(xv), cy:py(yv), r:cur ? 7 : 3.2, fill:col, 'fill-opacity':cur ? 1 : a,
        stroke:cur ? 'var(--panel)' : 'none', 'stroke-width':2, 'data-c':code, 'data-i':i, style:'cursor:pointer'}, g);
      if (cur) labels.push({x:px(xv), y:py(yv), t:`${s.c} ${s.n}`, col});
    }
  });
  labels.forEach(l => {
    const right = l.x < PL + PW - 120;
    const t = el('text', {x: right ? l.x + 11 : l.x - 11, y: Math.max(PT + 14, Math.min(PT + PH - 6, l.y - 9)),
      'text-anchor': right ? 'start' : 'end', class:'lbl', fill:l.col}, svg);
    t.textContent = l.t;
  });
  $('day').value = idx;
  $('dateLabel').textContent = fmtDate(D.dates[idx]);
  renderSide(); syncTop50();
}

function renderSide(){
  const side = $('side');
  const d0 = fmtDate(D.dates[0]).slice(5), di = fmtDate(D.dates[idx]).slice(5);
  if (CFG.mode === 'single') {
    const s = byCode[codes[0]]; if (!s) { side.innerHTML = ''; return; }
    let rows = '';
    for (let i = D.dates.length - 1; i >= 0; i--) {
      rows += `<tr data-i="${i}" class="${i === idx ? 'cur' : ''}"><td>${fmtDate(D.dates[i]).slice(5)}</td>` +
        `<td>${fX(s.x[i])}</td><td>${i ? dX(s.x[i-1], s.x[i]) : ''}</td>` +
        `<td>${fY(s.y[i])}</td><td>${i ? dY(s.y[i-1], s.y[i]) : ''}</td></tr>`;
    }
    side.innerHTML = `<h2>${s.c} ${s.n}</h2>
      <div class="kv"><span class="h"></span><span class="h">X 買賣超（億）</span><span class="h">Y 20日成交（億）</span>
        <span>${d0}</span><span class="num">${fX(s.x[0])}</span><span class="num">${fY(s.y[0])}</span>
        <span>${di}</span><span class="num">${fX(s.x[idx])}</span><span class="num">${fY(s.y[idx])}</span>
        <span>變化</span><span class="num">${dX(s.x[0], s.x[idx])}</span><span class="num">${dY(s.y[0], s.y[idx])}</span>
        <span>${di} 名次</span><span class="num">${s.xr[idx] ?? '—'}</span><span class="num">${s.yr[idx] ?? '—'}</span></div>
      <p class="hint">X、Y 的單位都是億元。名次是全市場 ${D.maxRank.toLocaleString()} 檔中的排名（第 1 名＝買超最多／成交金額最大）。點表格任一列可跳到那一天。</p>
      <div class="tbl-wrap"><table><thead><tr><th>日期</th><th>X 億元</th><th>較前日</th><th>Y 億元</th><th>較前日</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  } else {
    let rows = '';
    codes.forEach((code, si) => {
      const s = byCode[code]; if (!s) return;
      rows += `<tr><td><span class="chip" style="background:${colorOf(si)}"></span>${s.c} ${s.n}</td>` +
        `<td>${fX(s.x[idx])}</td><td>${dX(s.x[0], s.x[idx])}</td><td>${fY(s.y[idx])}</td><td>${dY(s.y[0], s.y[idx])}</td>` +
        `<td><button class="x" data-rm="${code}" aria-label="移除 ${s.n}">×</button></td></tr>`;
    });
    side.innerHTML = `<h2>${fmtDate(D.dates[idx])} 數值</h2>
      <div class="tbl-wrap" style="max-height:none"><table><thead><tr><th>個股</th><th>X 億元</th><th>較${d0}</th><th>Y 億元</th><th>較${d0}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint">X、Y 的單位都是億元。最多同時比較 8 檔，按 × 移除。</p>`;
  }
}

// 前 50 名快選（只在單檔版）：x＝法人買超（X 名次）、y＝20日成交金額（Y 名次），都取資料最後一天
const LISTS = { x: ['xr', '外資投信買賣超金額60日累計', v => fX(v)], y: ['yr', '成交金額20日累計', v => fY(v)] };
function listTop(k){
  const last = D.dates.length - 1, rk = LISTS[k][0];
  return D.stocks.filter(s => s[rk][last] != null).sort((a, b) => a[rk][last] - b[rk][last]).slice(0, 50);
}
function syncTop50(){ ROOT.querySelectorAll('.t50grid button').forEach(b => b.setAttribute('aria-pressed', b.dataset.c === codes[0])); }
function pick(c, autoplay){
  stop();
  codes = [c];
  $('code').value = `${c} ${byCode[c].n}`;
  $('err').textContent = '';
  computeDomain();
  if (autoplay) { idx = 0; play(); } else render();
}
function showList(k){
  $('tabX').setAttribute('aria-selected', k === 'x'); $('tabY').setAttribute('aria-selected', k === 'y');
  $('t50x').hidden = k !== 'x'; $('t50y').hidden = k !== 'y';
  $('t50title').textContent = `依 ${fmtDate(D.dates[D.dates.length - 1])}「${LISTS[k][1]}」由大到小`;
}
function buildTop50(){
  if (!$('t50x')) return;
  const last = D.dates.length - 1;
  ['x', 'y'].forEach(k => {
    const [rk, , f] = LISTS[k];
    $('t50' + k).innerHTML = listTop(k).map(s => `<button type="button" data-c="${s.c}" aria-pressed="false" title="第 ${s[rk][last]} 名　${s.c} ${s.n}　${f(s[k][last])} 億">` +
      `<span class="rk">${s[rk][last]}</span><span class="cd">${s.c}</span><span class="nm">${s.n}</span></button>`).join('');
    $('t50' + k).addEventListener('click', e => { const b = e.target.closest('button[data-c]'); if (b) pick(b.dataset.c, true); });
  });
  $('tabX').onclick = () => showList('x'); $('tabY').onclick = () => showList('y');
  $('t50date').textContent = fmtDate(D.dates[last]).slice(5);
  showList('x');
}

function stop(){ if (timer) { clearInterval(timer); timer = null; } $('play').textContent = '▶ 播放'; }
function play(){
  if (timer) { stop(); return; }
  if (idx >= D.dates.length - 1) idx = 0;
  $('play').textContent = '❚❚ 暫停';
  render();
  timer = setInterval(() => { if (idx >= D.dates.length - 1) { stop(); return; } idx++; render(); }, +$('speed').value);
}
function refresh(){ computeDomain(); render(); }
function setScale(s){ scale = s; $('scLin').setAttribute('aria-pressed', s === 'lin'); $('scLog').setAttribute('aria-pressed', s === 'log'); refresh(); }
function setRange(r){ range = r; $('rgAll').setAttribute('aria-pressed', r === 'all'); $('rgFit').setAttribute('aria-pressed', r === 'fit'); refresh(); }

function init(data){
  D = data;
  data.stocks.forEach(s => byCode[s.c] = s);
  AVGS = data.avgY;
  codes = codes.filter(c => byCode[c]);
  const dl = document.createElement('datalist'); dl.id = PFX + 'stocklist';
  dl.innerHTML = data.stocks.map(s => `<option value="${s.c} ${s.n}">`).join('');
  document.body.appendChild(dl);
  $('day').max = data.dates.length - 1; idx = data.dates.length - 1;
  $('sub').textContent = `資料區間 ${fmtDate(data.dates[0])}–${fmtDate(data.dates[data.dates.length-1])}・${data.dates.length} 個交易日・全上市櫃 ${data.stocks.length.toLocaleString()} 檔`;

  $('day').addEventListener('input', e => { stop(); idx = +e.target.value; render(); });
  $('prev').onclick = () => { stop(); if (idx > 0) { idx--; render(); } };
  $('next').onclick = () => { stop(); if (idx < D.dates.length - 1) { idx++; render(); } };
  $('play').onclick = play;
  $('speed').onchange = () => { if (timer) { stop(); play(); } };
  $('scLin').onclick = () => setScale('lin');
  $('scLog').onclick = () => setScale('log');
  $('rgFit').onclick = () => setRange('fit');
  $('rgAll').onclick = () => setRange('all');
  $('side').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-i]'); if (tr) { stop(); idx = +tr.dataset.i; render(); }
    const rm = e.target.closest('[data-rm]'); if (rm) { codes = codes.filter(c => c !== rm.dataset.rm); refresh(); }
  });

  const inp = $('code'), err = $('err');
  const submit = () => {
    const c = lookup(inp.value);
    if (!c) { err.textContent = '找不到這個代號或名稱，請重新輸入。'; return; }
    err.textContent = '';
    if (CFG.mode === 'single') { pick(c, true); return; }
    else {
      if (codes.includes(c)) { err.textContent = '這檔已經在圖上了。'; return; }
      if (codes.length >= 8) { err.textContent = '最多 8 檔，請先移除一檔。'; return; }
      codes.push(c); inp.value = '';
    }
    refresh();
  };
  buildTop50();
  $('go').onclick = submit;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  if (CFG.mode === 'single' && codes[0]) inp.value = `${codes[0]} ${byCode[codes[0]].n}`;

  const tip = $('tip'), box = $('chartBox');
  $('svg').addEventListener('pointerover', e => {
    const c = e.target.closest('circle[data-c]'); if (!c) return;
    const s = byCode[c.dataset.c], i = +c.dataset.i;
    tip.textContent = `${fmtDate(D.dates[i])}　${s.c} ${s.n}　X ${fX(s.x[i])} 億（第 ${s.xr[i] ?? '—'} 名）／Y ${fY(s.y[i])} 億（第 ${s.yr[i] ?? '—'} 名）`;
    const r = c.getBoundingClientRect(), b = box.getBoundingClientRect();
    tip.style.left = Math.min(Math.max(r.left + r.width / 2 - b.left, 150), b.width - 150) + 'px'; tip.style.top = (r.top - b.top) + 'px';
    tip.hidden = false;
  });
  $('svg').addEventListener('pointerout', e => { if (e.target.closest('circle[data-c]')) tip.hidden = true; });
  refresh();
}

__fetch('data.json').then(r => r.json()).then(init).catch(() => { $('sub').textContent = '資料讀取失敗，請重新整理頁面。'; });

};

/* ── t13 ← BG 13backtest ── */
CF_MODS["t13"] = function(ROOT, API){
var PFX = "m13-";
function __id(id){ return document.getElementById(PFX + id); }
var __fetch = API.fetch;

(function(){
  var $ = function(id){ return __id(id); };
  var D = null;              // data.json
  var R = null;              // 回測結果
  var ui = { tab:'daily', mode:'r20', page:1, pageSize:100, sortKey:'hits', sortDir:-1, stock:null };

  function md(iso){ if(!iso) return '—'; var p = iso.split('-'); return (p[1]|0)+'/'+(p[2]|0); }
  function fx(v,d){ return (v==null||isNaN(v)) ? '—' : Number(v).toFixed(d); }
  function pct(v){ return (v==null||isNaN(v)) ? '—' : (v*100).toFixed(1)+'%'; }
  function sgn(v,d){ if(v==null||isNaN(v)) return '—'; var s=Number(v).toFixed(d); return v>0 ? '+'+s : s; }
  function cls(v){ return v==null ? '' : (v>0 ? 'up' : (v<0 ? 'down' : '')); }
  function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }

  // ---------------- 參數 ----------------
  var FIELDS = ['pA','pB','pC','pE','pF','pG','pH','pI','pJ','pK','pL','pM','pN'];
  function readParams(){
    var bad = [], P = {};
    FIELDS.forEach(function(id){ $(id).classList.remove('bad'); });
    function val(id){ var v = $(id).value.trim(); return v==='' ? null : Number(v); }
    function need(id, label, test){
      var v = val(id);
      if(v==null || isNaN(v) || !test(v)){ bad.push(label); $(id).classList.add('bad'); return null; }
      return v;
    }
    function opt(id, label, test){
      var v = val(id);
      if(v==null) return null;
      if(isNaN(v) || !test(v)){ bad.push(label); $(id).classList.add('bad'); return null; }
      return v;
    }
    var pos = function(v){ return v>=1; }, day = function(v){ return Number.isInteger(v) && v>=1 && v<=D.lookback; };
    P.A = need('pA','法人買超÷大戶人數排名', pos);
    P.B = need('pB','成交金額÷大戶人數排名', pos);
    P.C = need('pC','法人買超金額60日累計排名', pos);
    P.I = need('pI','大戶比例比較天數（1～60）', day);
    P.L = need('pL','總股東人數比較天數（1～60）', day);
    P.M = need('pM','買賣超÷資本額倍數（0 或正數）', function(v){ return v>=0; });
    P.N = need('pN','大戶人數排名', pos);
    P.J = opt('pJ','大戶比例增加幅度', function(){ return true; });
    P.K = opt('pK','本身大戶比例', function(){ return true; });
    P.E = opt('pE','法人買超÷大戶人數排名進步天數', day);
    P.F = opt('pF','成交金額÷大戶人數排名進步天數', day);
    P.G = opt('pG','法人買超金額排名進步天數', day);
    P.H = opt('pH','大戶人數增加天數', day);
    return { P:P, bad:bad };
  }

  // 與原 Excel「整理」分頁相同的判斷（C 欄 = D 欄 且 大戶人數排名 ≤ N）
  function pass(s, k, P){
    var w = s.w[k], x = s.x[k], y = s.y[k];
    if(w==null || x==null || y==null) return false;
    if(!(w<=P.A && x<=P.B && y<=P.C)) return false;                                  // E 欄
    var hp0 = s.hp[k], hpN = s.hp[k+P.I];                                             // F 欄
    if(hp0==null || hpN==null) return false;
    if(!(hp0 - hpN > (P.J==null ? 0 : P.J))) return false;
    if(P.K!=null && !(hp0 > P.K)) return false;
    var sh0 = s.sh[k], shN = s.sh[k+P.L];                                             // G 欄
    if(!sh0 || !shN || !(sh0 - shN < 0)) return false;
    var z = s.z[k]; if(z==null || !(z > P.M)) return false;                           // H 欄
    if(P.E!=null){ var a=s.w[k+P.E]; if(a==null || !(w<=a)) return false; }           // I 欄：排名進步
    if(P.F!=null){ var b=s.x[k+P.F]; if(b==null || !(x<=b)) return false; }
    if(P.G!=null){ var c=s.y[k+P.G]; if(c==null || !(y<=c)) return false; }
    if(P.H!=null){ var h0=s.hc[k], hN=s.hc[k+P.H]; if(h0==null || hN==null || !(h0>=hN)) return false; }
    var hr = s.hr[k]; if(hr==null || !(hr <= P.N)) return false;                      // 大戶人數排名
    return true;
  }

  function bucket(r){ // 與原檔每日分頁的六個級距相同
    if(r>=0 && r<50) return 0; if(r>=50 && r<100) return 1; if(r>=100) return 2;
    if(r<0 && r>=-50) return 3; if(r<-50 && r>=-100) return 4; return 5;
  }

  function runBacktest(P){
    var days = D.days, stocks = D.stocks;
    var daily = [], picks = {}; // code -> {s, hit:[days]}
    for(var k=0; k<days; k++){
      var rows = [], b20=[0,0,0,0,0,0], b60=[0,0,0,0,0,0], pos20=0, pos60=0, n20=0, n60=0, sum20=0, sum60=0;
      for(var i=0; i<stocks.length; i++){
        var s = stocks[i];
        if(!pass(s,k,P)) continue;
        var p0 = s.p[59+k], p20 = s.p[39+k], p60 = s.p[k];
        var r20 = (p0 && p20!=null) ? (p20-p0)/p0*100 : null;
        var r60 = (p0 && p60!=null) ? (p60-p0)/p0*100 : null;
        if(r20!=null){ n20++; sum20+=r20; if(r20>=0) pos20++; b20[bucket(r20)]++; }
        if(r60!=null){ n60++; sum60+=r60; if(r60>=0) pos60++; b60[bucket(r60)]++; }
        if(!picks[s.c]) picks[s.c] = { s:s, cells:new Array(days).fill(null) };
        picks[s.c].cells[k] = { p0:p0, r20:r20, r60:r60 };
        rows.push(s.c);
      }
      daily.push({ k:k, date:D.filterDates[k], n:rows.length, n20:n20, n60:n60,
        rate20: n20 ? pos20/n20 : null, rate60: n60 ? pos60/n60 : null,
        avg20: n20 ? sum20/n20 : null, avg60: n60 ? sum60/n60 : null, b20:b20, b60:b60 });
    }
    var list = Object.keys(picks).map(function(c){
      var m = picks[c], hits=0, s20=0, c20=0, s60=0, c60=0;
      m.cells.forEach(function(v){ if(!v) return; hits++;
        if(v.r20!=null){ s20+=v.r20; c20++; } if(v.r60!=null){ s60+=v.r60; c60++; } });
      return { c:c, n:m.s.n, s:m.s, cells:m.cells, hits:hits, avg20: c20? s20/c20 : null, avg60: c60? s60/c60 : null };
    });
    return { daily:daily, list:list };
  }

  // ---------------- 呈現 ----------------
  function renderTiles(){
    var d = R.daily, activeDays = d.filter(function(x){ return x.n>0; }).length;
    var tot = 0, p20=0, n20=0, p60=0, n60=0, s20=0, s60=0;
    d.forEach(function(x){ tot+=x.n; n20+=x.n20; n60+=x.n60;
      p20 += x.rate20!=null ? Math.round(x.rate20*x.n20) : 0; p60 += x.rate60!=null ? Math.round(x.rate60*x.n60) : 0;
      s20 += x.avg20!=null ? x.avg20*x.n20 : 0; s60 += x.avg60!=null ? x.avg60*x.n60 : 0; });
    var t = [
      ['有篩出個股的天數', activeDays+' / '+D.days, '共 '+D.days+' 個篩選日'],
      ['累計篩出檔次', tot.toLocaleString('zh-TW'), '不重複個股 '+R.list.length+' 檔'],
      ['<span class="key" style="background:var(--s20)"></span>20 日後正報酬比例', n20? pct(p20/n20) : '—', '平均報酬 '+(n20? sgn(s20/n20,2)+'%' : '—')],
      ['<span class="key" style="background:var(--s60)"></span>60 日後正報酬比例', n60? pct(p60/n60) : '—', '平均報酬 '+(n60? sgn(s60/n60,2)+'%' : '—')]
    ];
    $('tiles').innerHTML = t.map(function(x){
      return '<div class="tile"><span class="k">'+x[0]+'</span><span class="v">'+x[1]+'</span><span class="s">'+x[2]+'</span></div>';
    }).join('');
  }

  // 共用：依容器寬度畫 SVG
  function chartBox(el, h){
    var w = Math.max(300, Math.round(el.clientWidth || 600));
    return { w:w, h:h, l:40, r:12, t:10, b:26 };
  }
  function tipAt(el, x, y, html){
    var t = el.querySelector('.tip'); if(!t){ t = document.createElement('div'); t.className='tip'; el.appendChild(t); }
    t.innerHTML = html; t.hidden = false;
    var box = el.getBoundingClientRect(), half = t.offsetWidth/2;
    var sx = x * el.clientWidth / Number(el.dataset.vw);
    sx = Math.min(Math.max(sx, half+2), el.clientWidth-half-2);
    t.style.left = sx+'px'; t.style.top = (y * el.clientWidth / Number(el.dataset.vw) - 6)+'px';
  }
  function hideTip(el){ var t = el.querySelector('.tip'); if(t) t.hidden = true; }
  function niceMax(v){ if(v<=5) return 5; var p = Math.pow(10, Math.floor(Math.log10(v))); var m=[1,2,2.5,5,10]; for(var i=0;i<m.length;i++){ if(m[i]*p>=v) return m[i]*p; } return 10*p; }

  function renderCountChart(){
    var el = $('countChart'), g = chartBox(el, 200), d = R.daily.slice().reverse(); // 舊→新
    var iw = g.w-g.l-g.r, ih = g.h-g.t-g.b, n = d.length, step = iw/n, bw = Math.max(2, step-2);
    var max = niceMax(Math.max.apply(null, d.map(function(x){ return x.n; })) || 1);
    var y = function(v){ return g.t + ih - v/max*ih; };
    var s = '<svg viewBox="0 0 '+g.w+' '+g.h+'" role="img" aria-label="每日篩出檔數長條圖">';
    [0, max/2, max].forEach(function(v){ s += '<line x1="'+g.l+'" x2="'+(g.w-g.r)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="var(--grid)" stroke-width="1"/>'+
      '<text x="'+(g.l-6)+'" y="'+(y(v)+3.5)+'" text-anchor="end">'+Math.round(v)+'</text>'; });
    d.forEach(function(x,i){
      var h = x.n/max*ih, bx = g.l + i*step + (step-bw)/2;
      if(h>0) s += '<path d="M'+bx+','+(g.t+ih)+' v'+(-Math.max(h-2,0))+' q0,-2 2,-2 h'+(bw-4)+' q2,0 2,2 v'+Math.max(h-2,0)+' z" fill="var(--bar)"/>';
      s += '<rect data-i="'+i+'" x="'+(g.l+i*step)+'" y="'+g.t+'" width="'+step+'" height="'+ih+'" fill="transparent"/>';
    });
    [0, Math.floor(n/2), n-1].forEach(function(i){ s += '<text x="'+(g.l+i*step+step/2)+'" y="'+(g.h-8)+'" text-anchor="middle">'+md(d[i].date)+'</text>'; });
    s += '</svg>';
    el.innerHTML = s; el.dataset.vw = g.w;
    el.querySelector('svg').addEventListener('mousemove', function(e){
      var r = e.target.getAttribute && e.target.getAttribute('data-i'); if(r==null){ hideTip(el); return; }
      var x = d[+r]; tipAt(el, g.l + (+r)*step + step/2, y(x.n), '<b>'+md(x.date)+'</b>　篩出 '+x.n+' 檔');
    });
    el.querySelector('svg').addEventListener('mouseleave', function(){ hideTip(el); });
  }

  function renderRateChart(){
    var el = $('rateChart'), g = chartBox(el, 200), d = R.daily.slice().reverse();
    var iw = g.w-g.l-g.r, ih = g.h-g.t-g.b, n = d.length, step = iw/(n-1);
    var x = function(i){ return g.l + i*step; }, y = function(v){ return g.t + ih - v*ih; };
    var s = '<svg viewBox="0 0 '+g.w+' '+g.h+'" role="img" aria-label="每日正報酬比例折線圖">';
    [0, .5, 1].forEach(function(v){ s += '<line x1="'+g.l+'" x2="'+(g.w-g.r)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="var(--grid)" stroke-width="1"/>'+
      '<text x="'+(g.l-6)+'" y="'+(y(v)+3.5)+'" text-anchor="end">'+(v*100)+'%</text>'; });
    function line(key, color){
      var path = '', open = false;
      d.forEach(function(p,i){ var v = p[key]; if(v==null){ open=false; return; } path += (open?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1); open = true; });
      return '<path d="'+path+'" fill="none" stroke="'+color+'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }
    s += line('rate20','var(--s20)') + line('rate60','var(--s60)');
    s += '<line id="rateCross" x1="0" x2="0" y1="'+g.t+'" y2="'+(g.t+ih)+'" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3" visibility="hidden"/>';
    s += '<rect x="'+g.l+'" y="'+g.t+'" width="'+iw+'" height="'+ih+'" fill="transparent" id="rateHit"/>';
    [0, Math.floor(n/2), n-1].forEach(function(i){ s += '<text x="'+x(i)+'" y="'+(g.h-8)+'" text-anchor="middle">'+md(d[i].date)+'</text>'; });
    s += '</svg>';
    el.innerHTML = s; el.dataset.vw = g.w;
    var svg = el.querySelector('svg'), cross = svg.querySelector('#rateCross');
    svg.addEventListener('mousemove', function(e){
      var pt = svg.getBoundingClientRect(), vx = (e.clientX-pt.left) * g.w / pt.width;
      var i = Math.round((vx-g.l)/step); if(i<0||i>=n){ cross.setAttribute('visibility','hidden'); hideTip(el); return; }
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility','visible');
      var p = d[i];
      tipAt(el, x(i), g.t+12, '<b>'+md(p.date)+'</b>（'+p.n+' 檔）<br>20 日後 '+pct(p.rate20)+'<br>60 日後 '+pct(p.rate60));
    });
    svg.addEventListener('mouseleave', function(){ cross.setAttribute('visibility','hidden'); hideTip(el); });
  }

  function renderDaily(){
    $('dailyBody').innerHTML = R.daily.map(function(x){
      function grp(rate, avg, b){
        return '<td class="sep">'+pct(rate)+'</td><td class="'+cls(avg)+'">'+(avg==null?'—':sgn(avg,2)+'%')+'</td>'+
          b.map(function(v){ return '<td class="'+(v?'':'zero')+'">'+v+'</td>'; }).join('');
      }
      return '<tr><td class="l">'+md(x.date)+'</td><td class="'+(x.n?'':'zero')+'">'+x.n+'</td>'+
        grp(x.rate20, x.avg20, x.b20) + grp(x.rate60, x.avg60, x.b60) + '</tr>';
    }).join('');
  }

  function sortedList(){
    var k = ui.sortKey, dir = ui.sortDir;
    return R.list.slice().sort(function(a,b){
      var av = a[k], bv = b[k];
      if(av==null) av = -Infinity; if(bv==null) bv = -Infinity;
      if(av<bv) return -dir; if(av>bv) return dir;
      return a.c < b.c ? -1 : 1;
    });
  }

  function renderMatrix(){
    var list = sortedList(), pages = Math.max(1, Math.ceil(list.length/ui.pageSize));
    if(ui.page>pages) ui.page = pages;
    var slice = list.slice((ui.page-1)*ui.pageSize, ui.page*ui.pageSize);
    var cols = [['c','代號','l stick'],['n','名稱','l stick2'],['hits','篩中天數',''],['avg20','平均20日%',''],['avg60','平均60日%','']];
    $('matrixHead').innerHTML = cols.map(function(c){
      var sorted = ui.sortKey===c[0];
      return '<th class="sortable '+c[2]+(sorted?' sorted':'')+'" data-key="'+c[0]+'" tabindex="0">'+c[1]+(sorted?(ui.sortDir>0?' ▲':' ▼'):'')+'</th>';
    }).join('') + D.filterDates.map(function(d,i){ return '<th'+(i===0?' class="sep"':'')+'>'+md(d)+'</th>'; }).join('');
    if(!list.length){
      $('matrixBody').innerHTML = '<tr><td class="l" colspan="'+(5+D.days)+'" style="padding:30px;color:var(--muted)">這組條件在回測期間沒有篩出任何個股，可以試著放寬門檻。</td></tr>';
    } else {
      $('matrixBody').innerHTML = slice.map(function(m){
        var cells = m.cells.map(function(v,i){
          var sep = i===0 ? ' sep' : '';
          if(!v) return '<td class="cell'+sep+'"></td>';
          var val = v[ui.mode], txt, c;
          if(ui.mode==='p0'){ txt = fx(val,2); c = 'hit-flat'; }
          else { txt = val==null ? '—' : sgn(val,1); c = val==null ? 'hit-flat' : (val>0 ? 'hit-up' : (val<0 ? 'hit-down' : 'hit-flat')); }
          return '<td class="cell '+c+sep+'">'+txt+'</td>';
        }).join('');
        return '<tr data-code="'+esc(m.c)+'" tabindex="0"><td class="l stick">'+esc(m.c)+'</td><td class="l name stick2">'+esc(m.n)+'</td><td>'+m.hits+'</td>'+
          '<td class="'+cls(m.avg20)+'">'+sgn(m.avg20,2)+'</td><td class="'+cls(m.avg60)+'">'+sgn(m.avg60,2)+'</td>'+cells+'</tr>';
      }).join('');
    }
    $('pageInfo').textContent = '第 '+ui.page+' / '+pages+' 頁（共 '+list.length+' 檔）';
    $('prevPage').disabled = ui.page<=1; $('nextPage').disabled = ui.page>=pages;
    var label = { r20:'篩選日後 20 個交易日的漲跌幅', r60:'篩選日後 59 個交易日的漲跌幅', p0:'篩選日當天收盤價' }[ui.mode];
    $('matrixHint').textContent = '列出回測期間至少被篩中一天的個股，日期欄由新到舊。有顏色的格子代表那天被篩中，格子內容是'+label+'；點任一列可看該股走勢。點表頭可排序。';
  }

  function renderStock(){
    var sel = $('stockPick');
    var list = R.list.slice().sort(function(a,b){ return a.c<b.c?-1:1; });
    sel.innerHTML = list.map(function(m){ return '<option value="'+esc(m.c)+'">'+esc(m.c+' '+m.n+'（'+m.hits+' 天）')+'</option>'; }).join('');
    if(!list.length){ $('stockTitle').textContent = '回測期間沒有篩出個股'; $('priceChart').innerHTML=''; $('pickBody').innerHTML=''; return; }
    if(!ui.stock || !R.list.some(function(m){ return m.c===ui.stock; })) ui.stock = list[0].c;
    sel.value = ui.stock;
    var m = R.list.filter(function(x){ return x.c===ui.stock; })[0];
    $('stockTitle').textContent = m.c+' '+m.n+'　被篩中 '+m.hits+' 天';
    drawPrice(m);
    $('pickBody').innerHTML = m.cells.map(function(v,k){
      if(!v) return '';
      return '<tr><td class="l">'+md(D.filterDates[k])+'</td><td>'+fx(v.p0,2)+'</td><td class="'+cls(v.r20)+'">'+sgn(v.r20,2)+'%</td><td class="'+cls(v.r60)+'">'+sgn(v.r60,2)+'%</td></tr>';
    }).join('');
  }

  function drawPrice(m){
    var el = $('priceChart'), g = chartBox(el, 260), p = m.s.p, n = p.length; // p[0] = 最新
    var iw = g.w-g.l-g.r, ih = g.h-g.t-g.b, step = iw/(n-1);
    var vals = p.filter(function(v){ return v!=null; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = (hi-lo)*0.08 || 1;
    lo -= pad; hi += pad;
    var x = function(idx){ return g.l + (n-1-idx)*step; }, y = function(v){ return g.t + ih - (v-lo)/(hi-lo)*ih; };
    var s = '<svg viewBox="0 0 '+g.w+' '+g.h+'" role="img" aria-label="收盤價走勢圖">';
    s += '<rect x="'+x(59+D.days-1)+'" y="'+g.t+'" width="'+(x(59)-x(59+D.days-1))+'" height="'+ih+'" fill="var(--band)"/>';
    [lo+pad, (lo+hi)/2, hi-pad].forEach(function(v){ s += '<line x1="'+g.l+'" x2="'+(g.w-g.r)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="var(--grid)"/>'+
      '<text x="'+(g.l-6)+'" y="'+(y(v)+3.5)+'" text-anchor="end">'+fx(v, v<100?2:0)+'</text>'; });
    var path='', open=false;
    for(var i=n-1;i>=0;i--){ if(p[i]==null){ open=false; continue; } path += (open?'L':'M')+x(i).toFixed(1)+','+y(p[i]).toFixed(1); open=true; }
    s += '<path d="'+path+'" fill="none" stroke="var(--ink)" stroke-width="1.6" stroke-linejoin="round"/>';
    m.cells.forEach(function(v,k){ if(!v || v.p0==null) return;
      s += '<circle cx="'+x(59+k)+'" cy="'+y(v.p0)+'" r="4.5" fill="var(--up)" stroke="var(--surface)" stroke-width="2"/>'; });
    s += '<line id="pxCross" x1="0" x2="0" y1="'+g.t+'" y2="'+(g.t+ih)+'" stroke="var(--muted)" stroke-dasharray="3 3" visibility="hidden"/>';
    s += '<rect x="'+g.l+'" y="'+g.t+'" width="'+iw+'" height="'+ih+'" fill="transparent"/>';
    [n-1, 59+D.days-1, 59, 0].forEach(function(i){ s += '<text x="'+x(i)+'" y="'+(g.h-8)+'" text-anchor="'+(i===n-1?'start':(i===0?'end':'middle'))+'">'+md(D.priceDates[i])+'</text>'; });
    s += '</svg>';
    el.innerHTML = s; el.dataset.vw = g.w;
    var svg = el.querySelector('svg'), cross = svg.querySelector('#pxCross');
    svg.addEventListener('mousemove', function(e){
      var r = svg.getBoundingClientRect(), vx = (e.clientX-r.left)*g.w/r.width;
      var idx = n-1-Math.round((vx-g.l)/step); if(idx<0||idx>=n||p[idx]==null){ cross.setAttribute('visibility','hidden'); hideTip(el); return; }
      cross.setAttribute('x1',x(idx)); cross.setAttribute('x2',x(idx)); cross.setAttribute('visibility','visible');
      var k = idx-59, hit = (k>=0 && k<D.days && m.cells[k]) ? '<br>當天被篩中' : '';
      tipAt(el, x(idx), y(p[idx]), '<b>'+md(D.priceDates[idx])+'</b>　收盤 '+fx(p[idx],2)+hit);
    });
    svg.addEventListener('mouseleave', function(){ cross.setAttribute('visibility','hidden'); hideTip(el); });
  }

  function setTab(t){
    ui.tab = t;
    ROOT.querySelectorAll('[data-tab]').forEach(function(b){ b.setAttribute('aria-pressed', b.dataset.tab===t); });
    ['daily','matrix','stock'].forEach(function(x){ $('tab-'+x).hidden = x!==t; });
    $('matrixTools').hidden = t!=='matrix';
    $('exportBtn').hidden = !(t==='daily' || t==='matrix') || !canExport;
    if(t==='matrix') renderMatrix();
    if(t==='stock') renderStock();
  }

  function renderAll(){
    $('emptyState').hidden = true; $('results').hidden = false;
    renderTiles(); renderCountChart(); renderRateChart(); renderDaily();
    ui.page = 1; setTab(ui.tab);
  }

  // ---------------- 匯出 ----------------
  var canExport = false, downloads = null;
  function csv(rows){ return '﻿' + rows.map(function(r){ return r.map(function(v){ v = v==null?'':String(v); return /[",\n]/.test(v) ? '"'+v.replace(/"/g,'""')+'"' : v; }).join(','); }).join('\r\n'); }
  async function exportCsv(){
    if(!downloads || !R) return;
    var rows, name;
    if(ui.tab==='daily'){
      var hb = ['0~50%','50~100%','>100%','0~-50%','-50~-100%','<-100%'];
      rows = [['篩選日','篩出檔數','20日正報酬比例','20日平均報酬%'].concat(hb.map(function(h){ return '20日 '+h; }), ['60日正報酬比例','60日平均報酬%'], hb.map(function(h){ return '60日 '+h; }))];
      R.daily.forEach(function(x){ rows.push([x.date, x.n, x.rate20==null?'':(x.rate20*100).toFixed(1)+'%', x.avg20==null?'':x.avg20.toFixed(2)].concat(x.b20,
        [x.rate60==null?'':(x.rate60*100).toFixed(1)+'%', x.avg60==null?'':x.avg60.toFixed(2)], x.b60)); });
      name = '籌碼回測檢視表_每日勝率.csv';
    } else {
      var lab = { r20:'20日報酬%', r60:'60日報酬%', p0:'篩選日收盤價' }[ui.mode];
      rows = [['代號','名稱','篩中天數','平均20日%','平均60日%'].concat(D.filterDates)];
      sortedList().forEach(function(m){ rows.push([m.c, m.n, m.hits, m.avg20==null?'':m.avg20.toFixed(2), m.avg60==null?'':m.avg60.toFixed(2)].concat(
        m.cells.map(function(v){ if(!v || v[ui.mode]==null) return ''; return v[ui.mode].toFixed(2); }))); });
      name = '籌碼回測檢視表_個股彙整_'+lab+'.csv';
    }
    try{ await downloads.save({ filename:name, data:csv(rows) }); }
    catch(e){ if(!e || e.code!=='declined'){ $('formError').textContent = '匯出沒有完成：'+(e && e.message ? e.message : e); $('formError').hidden = false; } }
  }

  // ---------------- 事件 ----------------
  $('filterForm').addEventListener('submit', function(e){
    e.preventDefault(); if(!D) return;
    var r = readParams();
    if(r.bad.length){ $('formError').textContent = '請檢查這些欄位：'+r.bad.join('、'); $('formError').hidden = false; return; }
    $('formError').hidden = true;
    R = runBacktest(r.P);
    renderAll();
  });
  $('sampleBtn').addEventListener('click', function(){
    var v = { pA:700, pB:700, pC:700, pE:'', pF:'', pG:'', pH:'', pI:20, pJ:0, pK:'', pL:20, pM:0.05, pN:300 };
    Object.keys(v).forEach(function(id){ $(id).value = v[id]; });
    $('filterForm').requestSubmit ? $('filterForm').requestSubmit() : $('runBtn').click();
  });
  $('resetBtn').addEventListener('click', function(){
    FIELDS.forEach(function(id){ $(id).value=''; $(id).classList.remove('bad'); });
    $('formError').hidden = true; R = null; $('results').hidden = true; $('emptyState').hidden = false;
  });
  ROOT.querySelectorAll('[data-tab]').forEach(function(b){ b.addEventListener('click', function(){ setTab(b.dataset.tab); }); });
  ROOT.querySelectorAll('[data-mode]').forEach(function(b){ b.addEventListener('click', function(){
    ui.mode = b.dataset.mode;
    ROOT.querySelectorAll('[data-mode]').forEach(function(x){ x.setAttribute('aria-pressed', x===b); });
    renderMatrix(); }); });
  function sortBy(key){ if(ui.sortKey===key) ui.sortDir*=-1; else { ui.sortKey=key; ui.sortDir = (key==='c'||key==='n') ? 1 : -1; } ui.page=1; renderMatrix(); }
  $('matrixHead').addEventListener('click', function(e){ var th = e.target.closest('th[data-key]'); if(th) sortBy(th.dataset.key); });
  $('matrixHead').addEventListener('keydown', function(e){ var th = e.target.closest('th[data-key]'); if(th && (e.key==='Enter'||e.key===' ')){ e.preventDefault(); sortBy(th.dataset.key); } });
  function openStock(tr){ ui.stock = tr.dataset.code; setTab('stock'); window.scrollTo({ top: $('results').offsetTop-10 }); }
  $('matrixBody').addEventListener('click', function(e){ var tr = e.target.closest('tr[data-code]'); if(tr) openStock(tr); });
  $('matrixBody').addEventListener('keydown', function(e){ var tr = e.target.closest('tr[data-code]'); if(tr && e.key==='Enter') openStock(tr); });
  $('prevPage').addEventListener('click', function(){ if(ui.page>1){ ui.page--; renderMatrix(); } });
  $('nextPage').addEventListener('click', function(){ ui.page++; renderMatrix(); });
  $('stockPick').addEventListener('change', function(){ ui.stock = this.value; renderStock(); });
  $('exportBtn').addEventListener('click', exportCsv);
  var rz; window.addEventListener('resize', function(){ clearTimeout(rz); rz = setTimeout(function(){ if(!R) return; renderCountChart(); renderRateChart(); if(ui.tab==='stock') renderStock(); }, 150); });

  if(window.claude && window.claude.use){
    window.claude.use('downloads').then(function(dl){ downloads = dl; canExport = !!dl; if(R) setTab(ui.tab); }).catch(function(){});
  }

  __fetch('data.json').then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); }).then(function(data){
    D = data;
    var fd = D.filterDates;
    $('windowText').textContent = md(fd[fd.length-1])+' ～ '+md(fd[0])+'（'+D.days+' 個交易日）';
    $('latestText').textContent = '股價資料至 '+md(D.latest)+'・共 '+D.stocks.length.toLocaleString('zh-TW')+' 檔';
    $('dataNote').textContent = '資料來源：本站用政府資料開放平臺自行計算的逐日籌碼資料（和 ④ 同一套），股價資料至 '+D.latest+'，資料整理時間 '+D.generated+'。';
    $('runBtn').disabled = false; $('sampleBtn').disabled = false;
  }).catch(function(err){
    $('windowText').textContent = '資料載入失敗';
    $('emptyState').innerHTML = '<h3>資料載入失敗</h3><p>'+esc(err.message||err)+'。請重新整理頁面再試一次。</p>';
  });
})();

};
{% endraw %}
