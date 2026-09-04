/* 在 Node 裡跑**真正的 site.js**，只為了驗一件事：觀察清單那份狀態。
 *
 * 這個檔案存在的理由是「字串比對證明不了行為」。以前那幾條測試看的是
 * `assert "TWSIXWatch.toggle(" in js`——它只證明那幾個字打對了，不證明按一下
 * 星號真的會亮、清單頁與個股頁看到的是不是同一份。
 *
 * 不需要瀏覽器：site.js 每一段 IIFE 開頭都有「找不到元素就 return」的守門，
 * 所以把 DOM 查詢一律回 null，就只剩下 TWSIXWatch 那一段真的執行。
 */
import fs from 'fs';

const store = new Map();
const doc = {
  getElementById: () => null, querySelector: () => null,
  querySelectorAll: () => [], addEventListener: () => {},
  body: { getAttribute: () => null },
};
const localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};
const win = { addEventListener: () => {}, TWSIX: {rel: '', repo: '', built: ''} };
const src = fs.readFileSync(process.argv[2], 'utf8');
const W = new Function(
  'localStorage', 'document', 'window', 'fetch', 'sessionStorage', 'TWSIX',
  src + '\nreturn TWSIXWatch;',
)(localStorage, doc, win, () => Promise.reject(new Error('no network')),
  {getItem: () => null, setItem: () => {}, removeItem: () => {}}, win.TWSIX);

function star(code){
  const attrs = {'data-star': code};
  return {
    getAttribute: k => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = v; },
    classList: {toggle: () => {}},
    textContent: '', title: '', attrs,
  };
}
const out = [];
const snap = s => ({mark: s.textContent, pressed: s.attrs['aria-pressed'],
                    title: s.title, label: s.attrs['aria-label']});

const page = star('2330'), row = star('2330'), other = star('1101');
W.paint(page); out.push(['初始', snap(page)]);
W.toggle('2330'); W.paint(page); out.push(['個股頁按一下', snap(page)]);
out.push(['存起來的', store.get('twsix.watchlist')]);
W.paint(row); out.push(['清單同一檔', snap(row)]);
W.paint(other); out.push(['清單別檔', snap(other)]);
out.push(['count', W.count()]);
W.toggle('2330'); W.paint(page); out.push(['取消之後', snap(page)]);

store.set('twsix.watchlist', JSON.stringify(['1101', '2330']));
W.reload(); W.paint(page); W.paint(other);
out.push(['reload 之後', [snap(page).mark, snap(other).mark, W.count()]]);

store.set('twsix.watchlist', '{壞掉的 JSON');
W.reload();
out.push(['壞掉的 JSON', W.count()]);

console.log(JSON.stringify(out));
