

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
  src + '\nreturn {pxDecode, pxSMA, pxChecks, y3Eps, pxFirstValid};',
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
if (c.first) out.first = api.pxFirstValid(c.first);
if (c.y3) out.y3 = api.y3Eps(c.y3.rev, c.y3.sh, c.y3.g, c.y3.m);
process.stdout.write(JSON.stringify(out));
