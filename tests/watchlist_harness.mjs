

import fs from 'fs';

const store = new Map();
const doc = {
  getElementById: () => null, querySelector: () => null,
  querySelectorAll: () => [], addEventListener: () => {},
  body: { getAttribute: () => null },

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

seed('[]');
W.reload();
['2330', '1101', '6811'].forEach(c => W.toggle(c));
out.push(['按星號的先後', W.order()]);

out.push(['往上移一格', (W.move('6811', -1), W.order())]);
out.push(['移完存起來的', store.get('twsix.watchlist')]);
out.push(['第一個再往上', [W.move('2330', -1), W.order()]]);
out.push(['最後一個再往下', [W.move('1101', 1), W.order()]]);
out.push(['不在清單裡的', W.move('9999', -1)]);

W.toggle('2330'); W.toggle('2330');
out.push(['取消再加回來', W.order()]);

seed(JSON.stringify(['6811', '2412', '1101']));
W.reload();
out.push(['reload 的順序', W.order()]);
out.push(['reload 之後 index', [W.index('6811'), W.index('1101'), W.index('9999')]]);

seed(JSON.stringify(['1101', '2330', '1101']));
W.reload();
out.push(['重複的代號', [W.order(), W.count()]]);

seed(JSON.stringify(['a', 'b', 'c', 'd']));
W.reload();
out.push(['置頂最後一個', [W.top('d'), W.order()]]);
out.push(['置頂之後存起來的', store.get('twsix.watchlist')]);
out.push(['已經在第一個再置頂', [W.top('d'), W.order()]]);
out.push(['不在清單裡的置頂', W.top('9999')]);
out.push(['置頂中間那個', [W.top('c'), W.order()]]);

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

seed(JSON.stringify(['2330', '2454', '3034', '1101']));
W.reload();
const ga = W.addGroup('甲'); ['3034', '2330', '9999'].forEach(c => W.toggle(c));
W.addGroup('空的');
W.select('__all');
out.push(['總交集', [W.current(), W.order(), W.groups().slice(-1)[0]]]);
out.push(['總交集不能加減', [W.toggle('2330'), W.toggle('5555'), W.move('3034', 1), W.top('3034'), W.order()]]);
W.paint(page); out.push(['總交集的星號說明', snap(page).title]);
{
  W.select('main');
  const before = W.current().id;
  const id = W.addGroup('選單新增', true);
  const ok = W.setIn(id, '2330', true);
  const gs = W.groupsOf('2330').map(x => x === id ? 'g9' : x).filter(x => x === 'main' || x === 'g9');
  out.push(['多群組', [ok, gs, W.inAny('2330'), W.setIn(id, '2330', true), W.current().id === before ? 'main' : W.current().id,
                      W.setIn(id, '2330', false), W.groupsOf('2330').filter(x => x === 'main' || x === id)]]);
}
W.select(ga); W.toggle('3034'); W.select('__all');
out.push(['群組改了總交集跟著變', W.order()]);
W.reload();
out.push(['reload 之後還在總交集', W.current().id]);

const gb = W.addGroup('乙'); ['9999'].forEach(c => W.toggle(c));
W.select('__all'); out.push(['乙加入後總交集', W.order()]);
out.push(['隱藏乙', [W.hideGroup(gb, true), W.hideGroup(gb, true)]]);
W.select('__all'); out.push(['隱藏後總交集', W.order()]);
W.select(gb); W.hideGroup(gb, false); W.hideGroup(gb, true);
out.push(['藏起目前這頁會跳走', W.current().id !== gb]);
W.reload(); out.push(['reload 還是隱藏', W.groups().filter(g => g.id === gb)[0].hidden]);
W.hideGroup(gb, false); W.select('__all'); out.push(['取消隱藏又回來', W.order()]);

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
