/* 在 Node 裡跑**真正的 site.js**，驗〔目標價試算盤〕的〔進場成本價位〕。
 *
 * 和 watchlist_harness.mjs 同一個做法：site.js 每一段 IIFE 開頭都有「找不到
 * 元素就 return」的守門，所以只要把試算盤用到的那十幾個元素做成假的，其餘一律
 * 回 null，就只剩試算盤那一段真的執行。
 *
 * 用法：node calc_harness.mjs site.js  →  stdout 是一串 [步驟, 結果]。
 */
import fs from 'fs';

const store = new Map();
function el(id, attrs = {}) {
  const h = {};
  return {
    id, value: '', innerHTML: '', textContent: '', hidden: false, attrs,
    getAttribute: k => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = String(v); },
    addEventListener: (ev, fn) => { (h[ev] = h[ev] || []).push(fn); },
    fire: ev => (h[ev] || []).forEach(fn => fn({ key: '', preventDefault() {} })),
    focus: () => {},
  };
}
const seed = { revenue: 1000, shares: 1, growth: { latest: 0, recent6: 0 },
               margin: { avg: 0.1, sigma: 0 }, pe: { low: 10, mid: 10, high: 10 } };
const E = {
  calc: el('calc', { 'data-code': '2330', 'data-seed': JSON.stringify(seed),
                     'data-price': '100', 'data-price-date': '2026.09.22' }),
};
for (const id of ['c-rev', 'c-sh', 'c-g', 'c-m', 'c-pe', 'calc-out', 'calc-basis',
                  'c-run', 'c-reset', 'c-cost', 'c-cost-reset', 'c-cost-note']) E[id] = el(id);

const doc = {
  getElementById: id => E[id] || null, querySelector: () => null,
  querySelectorAll: () => [], addEventListener: () => {},
  body: { getAttribute: () => null },
  documentElement: { classList: { add: () => {}, remove: () => {} } },
};
const localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};
const win = { addEventListener: () => {}, TWSIX: { rel: '', repo: '', built: '' } };
const src = fs.readFileSync(process.argv[2], 'utf8');
function load() {
  new Function('localStorage', 'document', 'window', 'fetch', 'sessionStorage', 'TWSIX', src)(
    localStorage, doc, win, () => Promise.reject(new Error('no network')),
    { getItem: () => null, setItem: () => {}, removeItem: () => {} }, win.TWSIX);
}

/* 讀矩陣：第一張目標價表（.mt1）左上那一格的目標價與第二行，以及那張表上面的說明。 */
function read() {
  const html = E['calc-out'].innerHTML;
  const t = html.split('<table class="matrix mt1">')[1] || '';
  const v = (t.match(/<span class="v">([^<]*)<\/span>/) || [])[1];
  const d = (t.match(/<span class="d">([^<]*)<\/span>/) || [])[1];
  const legends = html.match(/<p class="mlegend">.*?<\/p>/g) || [];
  return { v, d, legend: (legends[1] || '').replace(/<[^>]+>/g, ''),
           bycost: /class="bycost"/.test(legends[1] || ''),
           reset_hidden: E['c-cost-reset'].hidden, note: E['c-cost-note'].textContent,
           stored: store.has('twsix.cost.2330') ? store.get('twsix.cost.2330') : null };
}

const out = [];
load();
out.push(['現價', read()]);
E['c-cost'].value = '50'; E['c-cost'].fire('input');
out.push(['成本 50', read()]);
E['c-cost'].value = '-3'; E['c-cost'].fire('input');
out.push(['成本亂填', read()]);
E['c-cost'].value = '80'; E['c-cost'].fire('input');
/* 重新載入這一頁：記住的成本要讀回來，而且一載入就用它算。 */
E['c-cost'].value = ''; E['calc-out'].innerHTML = '';
load();
out.push(['重新載入', read()]);
E['c-cost-reset'].fire('click');
out.push(['回到現價', read()]);
process.stdout.write(JSON.stringify(out));
