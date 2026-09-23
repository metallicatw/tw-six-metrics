/* 在 Node 裡跑**真正的 site.js**，驗〔股價健診〕與〔推估三年目標價〕的算式。
 *
 * pxDecode／pxSMA／pxChecks／y3Eps 是 site.js 最外層的純函式；其餘每一段 IIFE
 * 開頭都有「找不到元素就 return」的守門，所以 DOM 一律回 null 就只剩它們可用。
 *
 * 用法：node pxhealth_harness.mjs site.js case.json  →  stdout 是結果 JSON。
 */
import fs from 'fs';
const doc = {
  getElementById: () => null, querySelector: () => null,
  querySelectorAll: () => [], addEventListener: () => {},
  body: { getAttribute: () => null },
  documentElement: { classList: { add: () => {}, remove: () => {} } },
};
const store = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const win = { addEventListener: () => {}, TWSIX: { rel: '', repo: '', built: '' } };
const src = fs.readFileSync(process.argv[2], 'utf8');
const api = new Function(
  'localStorage', 'document', 'window', 'fetch', 'sessionStorage', 'TWSIX',
  src + '\nreturn {pxDecode, pxSMA, pxChecks, y3Eps};',
)(store, doc, win, () => Promise.reject(new Error('no network')), store, win.TWSIX);
const c = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = {};
if (c.decode) out.decode = api.pxDecode(c.decode);
if (c.sma) out.sma = api.pxSMA(c.sma.c, c.sma.n);
if (c.checks) {
  const C = c.checks.c;
  const MA = {20: api.pxSMA(C, 20), 60: api.pxSMA(C, 60), 240: api.pxSMA(C, 240)};
  out.checks = api.pxChecks(C, MA, C.length - 1, c.checks.p);
}
if (c.y3) out.y3 = api.y3Eps(c.y3.rev, c.y3.sh, c.y3.g, c.y3.m);
process.stdout.write(JSON.stringify(out));
