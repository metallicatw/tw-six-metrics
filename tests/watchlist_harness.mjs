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
  /* 燈泡那一段開頭會 `documentElement.classList.add('js')`——那是「這一頁有
     JavaScript」的宣告，不是它自己的功能。stub 少了這一個屬性，整份 site.js
     會在載入時就丟例外，於是下面要驗的 TWSIXWatch 一行都跑不到。 */
  documentElement: { classList: { add: () => {}, remove: () => {} } },
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
/* 存檔的起點：只有舊版的單一清單（twsix.watchlist）、還沒有子群組——reload 會把它變成
   第一個群組〔我的自選〕。2026-10-05 子群組上線之後，這正是每一台舊瀏覽器第一次打開的狀態。 */
function seed(v){ store.delete('twsix.wgroups'); store.set('twsix.watchlist', v); }
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

seed(JSON.stringify(['1101', '2330']));
W.reload(); W.paint(page); W.paint(other);
out.push(['reload 之後', [snap(page).mark, snap(other).mark, W.count()]]);

seed('{壞掉的 JSON');
W.reload();
out.push(['壞掉的 JSON', W.count()]);

/* ── 自訂順序 ───────────────────────────────────────────────────────
 *
 * 存的是一個陣列，而順序就是使用者排的順序。上一版是把它讀進物件再
 * `Object.keys()` 存回去——而 JS 物件的「整數樣」鍵（"1101"、"2330"）一律照
 * 數字大小排。所以不管按星號的先後，存進去永遠是代號小到大：存的是陣列、
 * 看起來也像有順序，順序卻不是使用者給的那個。 */
seed('[]');
W.reload();
['2330', '1101', '6811'].forEach(c => W.toggle(c));
out.push(['按星號的先後', W.order()]);

out.push(['往上移一格', (W.move('6811', -1), W.order())]);
out.push(['移完存起來的', store.get('twsix.watchlist')]);
out.push(['第一個再往上', [W.move('2330', -1), W.order()]]);
out.push(['最後一個再往下', [W.move('1101', 1), W.order()]]);
out.push(['不在清單裡的', W.move('9999', -1)]);

/* 取消再加回來，要排到最後面——不是回到原本的位置。使用者按的是「移除」，
   加回來是一個新的動作。 */
W.toggle('2330'); W.toggle('2330');
out.push(['取消再加回來', W.order()]);

/* 上一頁回來：順序要原封不動讀回來。 */
seed(JSON.stringify(['6811', '2412', '1101']));
W.reload();
out.push(['reload 的順序', W.order()]);
out.push(['reload 之後 index', [W.index('6811'), W.index('1101'), W.index('9999')]]);

/* 同一個代號在存檔裡出現兩次（手動改過、或兩個分頁同時寫）——去重，
   而且以第一次出現的位置為準。 */
seed(JSON.stringify(['1101', '2330', '1101']));
W.reload();
out.push(['重複的代號', [W.order(), W.count()]]);

/* ── 置頂 ───────────────────────────────────────────────────────────
 *
 * 「把這一檔提到最上面」是實際最常做的動作（今天要盯它），而用上移做那件事
 * 要按到第十幾次，中間每一次都存一次 localStorage、重排一次表格。
 *
 * 它是**插入**，不是交換：中間那幾檔要整批往後退一格。寫成交換的話
 * ['a','b','c','d'] 置頂 d 會得到 ['d','b','c','a']——第一個和最後一個
 * 對調，而中間兩個沒動。畫面上「d 到最前面了」是對的，所以不會有人發現
 * a 被丟到最後面去了。 */
seed(JSON.stringify(['a', 'b', 'c', 'd']));
W.reload();
out.push(['置頂最後一個', [W.top('d'), W.order()]]);
out.push(['置頂之後存起來的', store.get('twsix.watchlist')]);
out.push(['已經在第一個再置頂', [W.top('d'), W.order()]]);
out.push(['不在清單裡的置頂', W.top('9999')]);
out.push(['置頂中間那個', [W.top('c'), W.order()]]);

/* ── 子群組（2026-10-05） ───────────────────────────────────────────── */
seed(JSON.stringify(['2330', '1101']));
W.reload();
out.push(['舊清單變成第一個群組', [W.groups(), W.current().id]]);
const g2 = W.addGroup('  半導體 ');
out.push(['新增之後切過去', [W.current().name, W.count(), W.has('2330')]]);
W.toggle('2454'); W.toggle('3034');
out.push(['新群組自己的清單', W.order()]);
out.push(['聯集寫回舊鍵', JSON.parse(store.get('twsix.watchlist'))]);
W.paint(page); out.push(['星號跟著目前群組', snap(page)]);
W.select('main');
out.push(['切回我的自選', [W.order(), W.has('2454')]]);
out.push(['改名', [W.renameGroup(g2, '晶片'), W.renameGroup(g2, '  '), W.groups().map(g => g.name)]]);
out.push(['往前挪', [W.moveGroup(g2, -1), W.groups().map(g => g.id)]]);
out.push(['第一個再往前', W.moveGroup(g2, -1)]);
out.push(['拖到最後', [W.placeGroup(g2, null), W.groups().map(g => g.id)]]);
const r1 = W.importGroup('trend', '趨勢×六大×報酬', ['2330', '2330', '6669', ' ']);
out.push(['第一次匯入', [r1, W.current().name, W.order()]]);
W.renameGroup(W.current().id, '我的趨勢');
const r2 = W.importGroup('trend', '趨勢×六大×報酬', ['3017']);
out.push(['同來源再匯入是換掉', [r2, W.groups().length, W.order(), W.sourceGroup('trend')]]);
W.reload();
out.push(['reload 讀得回群組', [W.groups().map(g => [g.name, g.n]), W.current().name]]);
out.push(['刪掉目前的群組', [W.removeGroup(W.current().id), W.current().id, W.groups().length]]);
W.removeGroup(g2);
out.push(['最後一個不能刪', [W.removeGroup('main'), W.groups().length]]);
/* 總交集清單：所有非空群組的交集，跟著各群組自動變；不能直接加減、不能排序。 */
seed(JSON.stringify(['2330', '2454', '3034', '1101']));
W.reload();
const ga = W.addGroup('甲'); ['3034', '2330', '9999'].forEach(c => W.toggle(c));
W.addGroup('空的');
W.select('__all');
out.push(['總交集', [W.current(), W.order(), W.groups().slice(-1)[0]]]);
out.push(['總交集不能加減', [W.toggle('2330'), W.toggle('5555'), W.move('3034', 1), W.top('3034'), W.order()]]);
W.paint(page); out.push(['總交集的星號說明', snap(page).title]);
W.select(ga); W.toggle('3034'); W.select('__all');
out.push(['群組改了總交集跟著變', W.order()]);
W.reload();
out.push(['reload 之後還在總交集', W.current().id]);
/* 隱藏：不參與總交集、藏起目前這一頁會跳走、reload 讀得回來。 */
const gb = W.addGroup('乙'); ['9999'].forEach(c => W.toggle(c));
W.select('__all'); out.push(['乙加入後總交集', W.order()]);
out.push(['隱藏乙', [W.hideGroup(gb, true), W.hideGroup(gb, true)]]);
W.select('__all'); out.push(['隱藏後總交集', W.order()]);
W.select(gb); W.hideGroup(gb, false); W.hideGroup(gb, true);
out.push(['藏起目前這頁會跳走', W.current().id !== gb]);
W.reload(); out.push(['reload 還是隱藏', W.groups().filter(g => g.id === gb)[0].hidden]);
W.hideGroup(gb, false); W.select('__all'); out.push(['取消隱藏又回來', W.order()]);
/* 另存新群組：不帶 src、原來源群組不動；同名檢查。 */
W.importGroup('trend', '趨勢', ['2330', '3034']);
const before = W.sourceGroup('trend');
const cp = W.importGroup('trend', '趨勢', ['1101'], '趨勢 10/05');
out.push(['另存新群組', [cp.copy, cp.name, W.current().name, W.order(), W.sourceGroup('trend').n === before.n,
  W.groups().filter(g => g.name === '趨勢 10/05')[0].src]]);
out.push(['同名檢查', [W.nameTaken('趨勢'), W.nameTaken(' 趨勢 10/05 '), W.nameTaken('沒這個')]]);
out.push(['空名稱不存', W.importGroup('trend', '趨勢', ['1101'], '  ')]);
W.hideGroup(W.sourceGroup('trend').id, true);
W.importGroup('trend', '趨勢', ['2330']);
out.push(['匯入會取消隱藏', W.groups().filter(g => g.src === 'trend')[0].hidden]);
store.set('twsix.wgroups', '{壞掉');
W.reload();
out.push(['群組存檔壞掉', [W.groups().length, W.current().name]]);

console.log(JSON.stringify(out));
