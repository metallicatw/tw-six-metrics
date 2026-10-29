

(function(){
  var box=document.getElementById('find'); if(!box) return;
  var list=document.getElementById('find-list');
  var data=null, hits=[], cur=-1, base=TWSIX.rel;

  function load(){
    if(data) return Promise.resolve(data);

    var v = (window.TWSIX && TWSIX.built) ? ('?v=' + encodeURIComponent(TWSIX.built)) : '';
    return fetch(base+'search.json'+v).then(function(r){return r.json();})
      .then(function(j){ data=j; return j; })
      .catch(function(){ data=[]; return data; });
  }

  function score(row, q){
    if(row[0].indexOf(q)===0) return 0;
    if(row[1].toLowerCase().indexOf(q)>-1) return 1;
    if(row[0].indexOf(q)>-1) return 2;
    if(row[2].toLowerCase().indexOf(q)>-1) return 3;
    return -1;
  }

  function search(q){
    var out=[], i, s;
    for(i=0;i<data.length;i++){
      s=score(data[i], q);
      if(s>=0) out.push([s, data[i]]);
    }
    out.sort(function(a,b){ return a[0]-b[0] || (a[1][0]<b[1][0]?-1:1); });
    return out.slice(0,12).map(function(x){return x[1];});
  }

  function draw(){
    list.innerHTML='';
    refreshOffer();
    if(!hits.length){ close(); return; }
    hits.forEach(function(r,i){
      var li=document.createElement('li');
      li.id='find-o'+i;
      li.setAttribute('role','option');
      li.setAttribute('aria-selected', i===cur ? 'true':'false');
      if(i===cur) li.className='on';
      var b=document.createElement('b'); b.textContent=r[0];
      var nm=document.createElement('span'); nm.className='nm'; nm.textContent=r[1];
      var ind=document.createElement('span'); ind.className='ind'; ind.textContent=r[2];
      var sc=document.createElement('span'); sc.className='sc'; sc.textContent=r[3];
      li.appendChild(b); li.appendChild(nm); li.appendChild(ind); li.appendChild(sc);

      if(r[6]){
        var dl=document.createElement('span');
        dl.className='tag gone'; dl.textContent='已下市';
        dl.title='已不在證交所／櫃買的公司名單上，評等停在下市前那一期';
        li.appendChild(dl);
      }

      if(r[4]){
        var t=document.createElement('span');
        var d=String(r[4]);
        t.className = d.length===10 ? 'tag when' : 'tag full';
        t.textContent = d.length===10 ? d.slice(5).replace('-','/') : '完整';
        t.title = d.length===10 ? ('報表更新於 '+d) : '已抓取完整資料';
        li.appendChild(t);
      }
      if(live || repo){
        var g=document.createElement('span'); g.className='tag grabbtn';
        g.textContent = r[4] ? '更新' : '抓這一檔';
        g.addEventListener('mousedown', function(e){
          e.preventDefault(); e.stopPropagation();
          grabNow(r[0]);
        });
        li.appendChild(g);
      }
      li.addEventListener('mousedown', function(e){ e.preventDefault(); go(r); });
      list.appendChild(li);
    });
    list.hidden=false;
    box.setAttribute('aria-expanded','true');
    if(cur>=0) box.setAttribute('aria-activedescendant','find-o'+cur);
    else box.removeAttribute('aria-activedescendant');
  }

  function close(){
    list.hidden=true; list.innerHTML='';
    box.setAttribute('aria-expanded','false');
    box.removeAttribute('aria-activedescendant');
    cur=-1;
  }

  function go(r){ location.href = base+'stock/'+r[0]+'.html'; }

  function run(){
    var q=box.value.trim().toLowerCase();
    if(!q){ hits=[]; close(); refreshOffer(); return; }
    load().then(function(){
      if(box.value.trim().toLowerCase()!==q) return;
      hits=search(q); cur=hits.length?0:-1; draw();
    });
  }

  var live=false, grab=document.getElementById('grab');

  var repo = '';
  try{ localStorage.removeItem('twsix.token'); }catch(e){}
  fetch(base+'api/ping').then(function(r){return r.ok?r.json():null;})
    .then(function(j){ live = !!(j && j.service==='twsix'); refreshOffer(); })
    .catch(function(){ live=false; refreshOffer(); });

  var btn = document.getElementById('grabnow');
  var pageCode = document.body.getAttribute('data-grab') || '';
  var pageFull = document.body.getAttribute('data-full') === '1';
  var target = '';

  function canGrab(){ return live || !!repo; }
  function offer(code, full){
    target = (code && canGrab()) ? code : '';
    if(!btn) return;
    if(target){ btn.textContent = label(target, full); btn.hidden = false; }
    else btn.hidden = true;
  }

  function label(code, full){ return (full ? '立即更新 ' : '抓取 ') + code; }

  function refreshOffer(){
    var q = box.value.trim();
    if(q && hits.length){
      var h = hits[cur > -1 ? cur : 0];
      offer(h ? h[0] : '', h && h[4]);
    } else if(!q){
      offer(pageCode, pageFull);
    } else {
      offer('');
    }
  }
  function grabNow(code){
    if(!code) return;
    if(live) fetchStock(code); else if(repo) askGithub(code);
  }
  if(btn){

    btn.addEventListener('mousedown', function(e){ e.preventDefault(); });
    btn.addEventListener('click', function(){ grabNow(target); });
  }
  var grabX = document.getElementById('grab-x');
  if(grabX){
    grabX.addEventListener('mousedown', function(e){ e.preventDefault(); });

    grabX.addEventListener('click', function(){
      clearInterval(ticker); ticker = null; watching = null; forget();
      grab.hidden = true;
    });
  }

  var TOKEN_KEY = 'twsix.token';
  var WORKFLOW = 'stock.yml';
  var API = 'https://api.github.com/repos/' + repo;

  function token(){
    try{ return localStorage.getItem(TOKEN_KEY) || ''; }catch(e){ return ''; }
  }
  function setToken(v){
    try{ v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); }
    catch(e){}
  }
  function gh(path, opts){
    opts = opts || {};
    opts.headers = Object.assign({
      'Accept': 'application/vnd.github+json',
      'Authorization': 'Bearer ' + token(),
      'X-GitHub-Api-Version': '2022-11-28'
    }, opts.headers || {});
    return fetch(API + path, opts);
  }

  var started = 0, ticker = null, steps = [], phaseAt = -1, phaseNote = '';
  var grabCode = '';

  function elapsed(){
    var s = Math.round((Date.now() - started) / 1000);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  var PHASES = [
    { key: 'send',   cells: 1, label: '送出給 GitHub Actions' },
    { key: 'queue',  cells: 3, label: '等 GitHub 派 runner（排隊，不算在 workflow 的執行時間裡）' },
    { key: 'run',    cells: 7, label: '抓報表 → 補集保股權歷史 → 產生報告 → 建站 → 發布' },
    { key: 'cdn',    cells: 3, label: 'workflow 完成，等 Pages CDN 換上新的一份' }
  ];
  var CELLS = PHASES.reduce(function(n, p){ return n + p.cells; }, 0);

  function phaseIndex(key){
    for(var i = 0; i < PHASES.length; i++) if(PHASES[i].key === key) return i;
    return -1;
  }

  function phase(key){
    var i = phaseIndex(key);
    if(i > phaseAt){ phaseAt = i; phaseNote = ''; }
  }

  function bar(done, failed){
    var html = '', filled = 0, i, j;
    for(i = 0; i < PHASES.length; i++){
      for(j = 0; j < PHASES[i].cells; j++){
        var cls = '';
        if(done) cls = failed ? 'bad' : 'on';
        else if(i < phaseAt) cls = 'on';
        else if(i === phaseAt) cls = 'now';

        var delay = cls === 'now' ? ' style="animation-delay:' + (j * 0.13) + 's"' : '';
        html += '<i class="' + cls + '"' + delay + '></i>';
        filled++;
      }
    }
    return html;
  }

  function step(text, key){
    if(key) phase(key);
    var last = steps[steps.length - 1];
    if(!last || last.text !== text){
      steps.push({ at: elapsed(), since: Date.now(), text: text });
    }
    phaseNote = text;
    paint();
  }

  function lines(){
    return steps.map(function(s, i){
      var held = '';

      if(i === steps.length - 1 && ticker){
        var n = Math.round((Date.now() - s.since) / 1000);
        if(n >= 5) held = '（已 ' + n + ' 秒）';
      }
      return s.at + '　' + s.text + held;
    }).join('\n');
  }

  function paint(){
    if(!grab || !started) return;
    grab.hidden = false;

    grab.querySelector('.head').innerHTML =
      '<b>立即更新' + (grabCode ? ' ' + grabCode : '') + '</b>' +
      '<span class="t">' + elapsed() + '</span>';
    var cur = PHASES[phaseAt];
    grab.querySelector('.stage').textContent = cur ? cur.label : (phaseNote || '準備中…');
    grab.querySelector('.bar').innerHTML = bar(false, false);
    grab.querySelector('.log').textContent = lines();
  }

  function beginPanel(code){
    started = Date.now(); steps = []; phaseAt = -1; phaseNote = '';
    grabCode = code || '';
    clearInterval(ticker);
    var d = grab && grab.querySelector('.detail');
    if(d) d.open = false;
    ticker = setInterval(paint, 1000);
    paint();
  }

  function endPanel(head, note, ok, action){
    clearInterval(ticker); ticker = null;
    if(!grab) return;
    grab.hidden = false;
    grab.querySelector('.head').innerHTML =
      '<b>' + head + '</b><span class="t">' + elapsed() + '</span>';
    var stage = grab.querySelector('.stage');
    stage.textContent = note || '';
    if(action){
      var again = document.createElement('button');
      again.type = 'button';
      again.className = 'again';
      again.textContent = action.label;
      again.addEventListener('click', action.run);
      stage.appendChild(document.createTextNode(' '));
      stage.appendChild(again);
    }
    grab.querySelector('.bar').innerHTML = bar(true, ok === false);
    if(note) steps.push({ at: elapsed(), since: Date.now(), text: note });
    grab.querySelector('.log').textContent = lines();

    var d = grab.querySelector('.detail');
    if(d && ok === false) d.open = true;
  }

  var PENDING = 'twsix.pending';

  function remember(code, was){
    try{ sessionStorage.setItem(PENDING, JSON.stringify(
      {code: code, was: was === undefined ? null : was,
       until: Date.now() + 8*60*1000})); }catch(e){}
  }
  function currentMark(code){
    if(!data) return null;
    for(var i=0;i<data.length;i++) if(data[i][0] === code) return data[i][4];
    return null;
  }
  function forget(){ try{ sessionStorage.removeItem(PENDING); }catch(e){} }
  function pendingJob(){
    try{
      var j = JSON.parse(sessionStorage.getItem(PENDING) || 'null');
      if(!j || !j.code || Date.now() > j.until){ forget(); return null; }
      return j;
    }catch(e){ return null; }
  }

  var watching = null;
  function arrive(code, built){
    forget();
    step('網站已換上新版，開啟報告', 'cdn');
    endPanel(code + ' 好了', '正在開啟報告…', true);

    if(location.pathname.replace(/^.*\//, '') === code + '.html'){ location.reload(); }
    else {
      var fresh = built || TWSIX.built;
      var v = fresh ? ('?v=' + encodeURIComponent(fresh)) : '';
      location.href = base + 'stock/' + code + '.html' + v;
    }
  }

  var WATCH_MS = 1000;

  var SETTLE_MS = 45000;
  function watch(code, tries, was, deadline){
    if(watching && watching !== code) return;
    watching = code;
    var mine = TWSIX.built || '';
    fetch(base + 'build.json?t=' + Date.now(), {cache:'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(j){

        if(j && j.built && mine && j.built !== mine){ arrive(code, j.built); return; }
        if(j && j.built) { nextWatch(code, tries, was, deadline); return; }
        return fallback(code, tries, was, deadline);
      })
      .catch(function(){ return fallback(code, tries, was, deadline); });
  }

  function fallback(code, tries, was, deadline){
    return fetch(base + 'search.json?t=' + Date.now(), {cache:'no-store'})
      .then(function(r){ return r.json(); })
      .then(function(rows){
        for(var i=0;i<rows.length;i++){
          if(rows[i][0] !== code) continue;
          var now = rows[i][4];
          if(was === null || was === undefined ? !!now : now !== was){
            arrive(code); return;
          }
          break;
        }
        if(deadline && Date.now() > deadline){ arrive(code); return; }
        nextWatch(code, tries, was, deadline);
      })
      .catch(function(){ nextWatch(code, tries, was, deadline); });
  }
  function nextWatch(code, tries, was, deadline){
    if(tries <= 0){
      forget(); watching = null;
      endPanel('等太久了，' + code + ' 還沒出現',
               '到 Actions 看一下「加一檔個股」跑完了沒；跑完了重新整理這一頁。', false);
      return;
    }
    setTimeout(function(){ watch(code, tries - 1, was, deadline); }, WATCH_MS);
  }

  function dataEpoch(){
    var tp = new Date(Date.now() + 8*3600000);
    var y = tp.getUTCFullYear(), m = tp.getUTCMonth(), d = tp.getUTCDate();
    if(tp.getUTCHours() < 17) d -= 1;
    var e = new Date(Date.UTC(y, m, d, 9, 0, 0));
    while(e.getUTCDay() === 0 || e.getUTCDay() === 6){ e.setUTCDate(e.getUTCDate() - 1); }
    return e.getTime();
  }
  function stampOf(code){
    if(!data) return '';
    for(var i=0;i<data.length;i++) if(data[i][0] === code) return data[i][5] || '';
    return '';
  }

  function stampFromServer(code){
    return fetch(base + 'search.json?t=' + Date.now(), {cache: 'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(rows){
        if(!rows) return stampOf(code);
        data = rows;
        return stampOf(code);
      })
      .catch(function(){ return stampOf(code); });
  }
  function isFresh(stamp){
    if(!stamp || stamp.indexOf('T') < 0) return false;
    var t = Date.parse(stamp);
    return !isNaN(t) && t >= dataEpoch();
  }
  function prettyStamp(stamp){
    return stamp.slice(0, 10) + ' ' + stamp.slice(11, 16);
  }

  var forced = {};

  function runOnGithub(code){

    if(!data){ load().then(function(){ runOnGithub(code); }); return; }
    close();
    beginPanel(code);
    step('先確認 ' + code + ' 需不需要抓…', 'send');
    stampFromServer(code).then(function(stamp){ dispatch(code, stamp); });
  }

  function dispatch(code, stamp){
    if(isFresh(stamp) && !forced[code]){
      endPanel(code + ' 已經是最新的',
               '最後抓取 ' + prettyStamp(stamp) + '，之後沒有任何一個來源更新過'
               + '（收盤行情與三大法人下午才上站，界線抓在 17:00）。'
               + '這次沒有派 runner。',
               true,
               {label: '仍要重抓', run: function(){
                 forced[code] = true;
                 runOnGithub(code);
               }});
      return;
    }
    var force = !!forced[code] && isFresh(stamp);

    delete forced[code];
    var was = currentMark(code);
    remember(code, was);
    step('送出 ' + code + ' 給 GitHub Actions…', 'send');
    var since = new Date(Date.now() - 60000).toISOString();
    gh('/actions/workflows/' + WORKFLOW + '/dispatches', {
      method: 'POST',
      body: JSON.stringify({ref: 'main',
                            inputs: {stock: code, force: force ? 'true' : 'false'}})
    }).then(function(r){
      if(r.status === 204){
        step('已送出。等 GitHub 派 runner（這一段是排隊，不算在 workflow 的執行時間裡）', 'queue');
        pollRun(code, since, 180, was); return;
      }
      if(r.status === 401 || r.status === 403){
        setToken('');
        endPanel('權杖無效或權限不足',
                 '請重新設定一把 fine-grained PAT，勾選這個 repo 的 Actions 讀寫。', false);
        return;
      }
      return r.text().then(function(t){
        endPanel('送出失敗（HTTP ' + r.status + '）', t.slice(0, 300), false);
      });
    }).catch(function(e){
      endPanel('送不出去', String(e), false);
    });
  }

  function pollRun(code, since, tries, was){
    if(tries <= 0){ step('狀態查不到了，改用網站本身判斷…', 'run'); watch(code, 180, was, 0); return; }
    gh('/actions/workflows/' + WORKFLOW + '/runs?per_page=5&created=%3E' +
       encodeURIComponent(since))
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(j){
        var run = j && j.workflow_runs && j.workflow_runs[0];
        if(!run){ setTimeout(function(){ pollRun(code, since, tries - 1, was); }, 2000); return; }
        if(run.status === 'queued') step('GitHub 已建立這次執行，還在排隊', 'queue');
        else if(run.status === 'in_progress') step(
          'runner 開始跑：抓報表 → 補集保股權歷史 → 產生報告 → 建站 → 發布', 'run');
        else if(run.status === 'completed'){
          if(run.conclusion === 'success'){

            afterRun(run, code, was);
          } else {
            forget();
            endPanel('抓取失敗（' + run.conclusion + '）',
                     '執行紀錄：' + run.html_url, false);
          }
          return;
        }
        setTimeout(function(){ pollRun(code, since, tries - 1, was); }, 2000);
      })
      .catch(function(){ setTimeout(function(){ pollRun(code, since, tries - 1, was); }, 2000); });
  }

  function afterRun(run, code, was){
    function keepWaiting(){
      step('workflow 完成。剩下的是 Pages CDN 換檔', 'cdn');
      watch(code, 180, was, Date.now() + SETTLE_MS);
    }
    gh('/actions/runs/' + run.id + '/jobs')
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(j){
        var jobs = (j && j.jobs) || [];
        var built = null;
        for(var i = 0; i < jobs.length; i++){
          var steps = jobs[i].steps || [];
          for(var k = 0; k < steps.length; k++){
            if(String(steps[k].name).indexOf('建站') > -1){ built = steps[k]; }
          }
        }
        if(built && built.conclusion === 'skipped'){
          forget();
          endPanel(code + ' 已經是最新的',
                   'workflow 判斷這一檔的資料沒有變，所以沒有重抓、也沒有重新發布'
                   + '——網站上這一份就是最新的。',
                   true,
                   {label: '仍要重抓', run: function(){
                     forced[code] = true;
                     runOnGithub(code);
                   }});
          return;
        }
        keepWaiting();
      })
      .catch(keepWaiting);
  }

  function askToken(){
    var now = token();
    var msg = now
      ? '目前已設定權杖。貼上新的可以更換，留空並按確定則清除。'
      : '貼上 GitHub fine-grained PAT（只勾這一個 repo、Actions 讀寫）。\n'
        + '它只存在這台瀏覽器，不會進 repo，也只會送到 api.github.com。';
    var v = window.prompt(msg, '');
    if(v === null) return false;
    setToken(v.trim());
    return !!v.trim();
  }

  function askGithub(code){
    if(token()) return runOnGithub(code);
    if(askToken()) return runOnGithub(code);

    close(); beginPanel(code);
    endPanel('還沒設定抓取權杖',
             '線上抓取要一把 GitHub fine-grained PAT（只勾這個 repo、Actions 讀寫）。\n'
             + '按頁首的「設定抓取權杖」貼上，之後就不用再貼。', false);
    return;
  }
  window.twsixAskGithub = askGithub;
  window.twsixSetToken = askToken;
  window.twsixHasToken = function(){ return !!token(); };
  window.twsixCanAsk = function(){ return !live && !!repo; };

  function pollLocal(code){
    fetch(base + 'api/job/' + code).then(function(r){ return r.json(); })
      .then(function(j){
        if(j.error){ endPanel('抓取失敗', j.error, false); return; }
        if(!j.done){

          steps = j.lines.slice(); paint();
          setTimeout(function(){ pollLocal(code); }, 800);
          return;
        }
        steps = j.lines.slice();
        if(j.ok) arrive(code);
        else endPanel('抓取失敗', '八個鏡像站都拒絕通常代表 IP 被擋，換個網路再試。', false);
      })
      .catch(function(){ endPanel('抓取中斷', '連不上本機服務', false); });
  }
  function fetchStock(code){
    close(); beginPanel(code); remember(code, currentMark(code));
    step('正在抓取 ' + code + '…', 'run');
    fetch(base + 'api/fetch/' + code, {method: 'POST'})
      .then(function(r){ return r.json(); })
      .then(function(j){
        if(j.error){ endPanel('抓取失敗', j.error, false); return; }
        pollLocal(code);
      })
      .catch(function(){ endPanel('抓取中斷', '連不上本機服務', false); });
  }
  window.twsixFetch = fetchStock;
  window.twsixLive = function(){ return live; };

  (function resume(){
    var j = pendingJob();
    if(!j) return;
    setTimeout(function(){
      beginPanel(j.code);
      step('等 ' + j.code + ' 的資料進到網站…', 'cdn');
      watch(j.code, 180, j.was, Date.now() + 90000);
    }, 1200);
  })();

  var tl = document.getElementById('tokenlink');
  if(tl){
    setTimeout(function(){
      if(live || !repo) return;
      tl.hidden = false;
      var mark = function(){ tl.textContent = token() ? '抓取權杖 ✓' : '設定抓取權杖'; };
      mark();
      tl.addEventListener('click', function(e){ e.preventDefault(); askToken(); mark(); });
    }, 1000);
  }

  box.addEventListener('focus', load);
  box.addEventListener('input', run);
  box.addEventListener('blur', function(){ setTimeout(close, 150); });
  box.addEventListener('keydown', function(e){
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){
      if(!hits.length) return;
      e.preventDefault();
      cur=(cur + (e.key==='ArrowDown'?1:hits.length-1)) % hits.length;
      draw();
    } else if(e.key==='Enter'){

      if(cur>-1 && hits[cur]){
        e.preventDefault();

        if(hits[cur][4]) go(hits[cur]);
        else if(live || repo) grabNow(hits[cur][0]);
        else go(hits[cur]);
      }
    } else if(e.key==='Escape'){ close(); box.blur(); }
  });
  document.addEventListener('keydown', function(e){
    var el=document.activeElement;
    if(e.key==='/' && el!==box && !/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)){
      e.preventDefault(); box.focus(); box.select();
    }
  });
})();

var TWSIXWatch = (function(){

  var KEY = 'twsix.wgroups', OLD = 'twsix.watchlist';

  var ALL = '__all', ALL_NAME = '總交集清單';

  var doc = null, cur = null, order = [], set = {};

  function clean(codes){
    var seen = {}, out = [];
    (codes || []).forEach(function(c){
      c = String(c || '').trim();
      if(c && !seen[c]){ seen[c] = 1; out.push(c); }
    });
    return out;
  }
  function fresh(){
    var old = [];
    try{ old = JSON.parse(localStorage.getItem(OLD) || '[]') || []; }catch(e){}
    return {v: 1, cur: 'main', groups: [{id: 'main', name: '我的自選', codes: clean(old)}]};
  }
  function find(id){
    for(var i = 0; i < doc.groups.length; i++) if(doc.groups[i].id === id) return doc.groups[i];
    return null;
  }
  function intersect(){
    var full = doc.groups.filter(function(g){ return g.codes.length && !g.hidden; });
    if(!full.length) return [];
    return full[0].codes.filter(function(c){
      return full.every(function(g){ return g.codes.indexOf(c) >= 0; });
    });
  }
  function bind(){
    if(doc.cur === ALL) cur = {id: ALL, name: ALL_NAME, codes: intersect(), virtual: true};
    else cur = find(doc.cur) || doc.groups[0];
    doc.cur = cur.id;
    order = cur.codes;
    set = {};
    order.forEach(function(c){ set[c] = 1; });
  }
  function reload(){
    var d = null;
    try{ d = JSON.parse(localStorage.getItem(KEY) || 'null'); }catch(e){ d = null; }
    if(!d || !d.groups || !d.groups.length) d = fresh();
    d.groups = d.groups.filter(function(g){ return g && g.id; }).map(function(g){
      var o = {id: String(g.id), name: String(g.name || '未命名'), codes: clean(g.codes)};
      if(g.src) o.src = String(g.src);
      if(g.hidden) o.hidden = true;
      return o;
    });
    if(!d.groups.length) d = fresh();
    doc = d;
    bind();
    return set;
  }
  function save(){
    bind();
    var all = [];
    doc.groups.forEach(function(g){ all = all.concat(g.codes); });
    try{
      localStorage.setItem(KEY, JSON.stringify(doc));
      localStorage.setItem(OLD, JSON.stringify(clean(all)));
    }catch(e){}
  }
  function has(code){ return !!set[code]; }
  function toggle(code){
    if(cur.virtual) return !!set[code];
    if(set[code]) order.splice(order.indexOf(code), 1);
    else order.push(code);
    save();
    return !!set[code];
  }
  function move(code, delta){
    if(cur.virtual) return false;
    var i = order.indexOf(code), j = i + delta;
    if(i < 0 || j < 0 || j >= order.length) return false;
    order[i] = order[j]; order[j] = code;
    save();
    return true;
  }
  function top(code){
    if(cur.virtual) return false;
    var i = order.indexOf(code);
    if(i <= 0) return false;
    order.splice(i, 1); order.unshift(code);
    save();
    return true;
  }
  function index(code){ return order.indexOf(code); }

  var watchPageMemo = null;
  function isWatchPage(){
    if(watchPageMemo === null) watchPageMemo = !!document.querySelector('table[data-watchlist="1"]');
    return watchPageMemo;
  }
  function paint(btn){
    var code = btn.getAttribute('data-star');
    var watchPage = isWatchPage();
    var on = watchPage ? has(code) : inAny(code);
    var where = doc.groups.filter(function(g){ return g.codes.indexOf(code) >= 0; })
                          .map(function(g){ return '〔' + g.name + '〕'; }).join('');
    btn.textContent = on ? '★' : '☆';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.setAttribute('aria-haspopup', 'true');
    btn.classList.toggle('on', on);
    btn.title = where ? '已在觀察清單' + where + '——點一下調整要放進哪些群組' : '加入觀察清單（點一下選群組）';
    btn.setAttribute('aria-label', '把 ' + code + ' 加入或移出觀察清單的群組' + (where ? '，目前在' + where : ''));
    return on;
  }

  function changed(){
    try{ document.dispatchEvent(new CustomEvent('twsix:wgroup')); }catch(e){}
  }
  function groups(){
    var out = doc.groups.map(function(g){ return {id: g.id, name: g.name, n: g.codes.length, src: g.src || '', hidden: !!g.hidden}; });
    out.push({id: ALL, name: ALL_NAME, n: intersect().length, src: '', virtual: true});
    return out;
  }
  function select(id){
    if((id !== ALL && !find(id)) || doc.cur === id) return false;
    doc.cur = id; save(); changed();
    return true;
  }
  function uid(){ return 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }
  function addGroup(name, keepCur){
    var g = {id: uid(), name: String(name || '新群組').trim() || '新群組', codes: []};
    doc.groups.push(g);
    if(!keepCur) doc.cur = g.id;
    save(); changed();
    return g.id;
  }

  function groupsOf(code){
    return doc.groups.filter(function(g){ return g.codes.indexOf(code) >= 0; }).map(function(g){ return g.id; });
  }
  function inAny(code){ return doc.groups.some(function(g){ return g.codes.indexOf(code) >= 0; }); }
  function setIn(id, code, on){
    var g = find(id); code = String(code || '').trim();
    if(!g || !code) return false;
    var i = g.codes.indexOf(code);
    if(on && i < 0) g.codes.push(code);
    else if(!on && i >= 0) g.codes.splice(i, 1);
    else return false;
    save(); changed();
    return true;
  }
  function renameGroup(id, name){
    var g = find(id); name = String(name || '').trim();
    if(!g || !name || g.name === name) return false;
    g.name = name; save(); changed();
    return true;
  }
  function removeGroup(id){
    if(doc.groups.length <= 1) return false;
    var i = -1;
    doc.groups.forEach(function(g, k){ if(g.id === id) i = k; });
    if(i < 0) return false;
    doc.groups.splice(i, 1);
    if(doc.cur === id) doc.cur = doc.groups[Math.max(0, i - 1)].id;
    save(); changed();
    return true;
  }

  function hideGroup(id, on){
    var g = find(id); on = !!on;
    if(!g || !!g.hidden === on) return false;
    if(on) g.hidden = true; else delete g.hidden;
    if(on && doc.cur === id){
      var i = doc.groups.indexOf(g), next = null;
      doc.groups.slice(i + 1).concat(doc.groups.slice(0, i).reverse()).forEach(function(x){
        if(!next && !x.hidden) next = x;
      });
      doc.cur = next ? next.id : ALL;
    }
    save(); changed();
    return true;
  }

  function hideAll(on){
    on = !!on;
    var n = 0;
    doc.groups.forEach(function(g){
      if(!!g.hidden === on) return;
      if(on) g.hidden = true; else delete g.hidden;
      n++;
    });
    if(!n) return false;
    if(on) doc.cur = ALL;
    save(); changed();
    return true;
  }

  function placeGroup(id, before){
    var g = find(id);
    if(!g || id === before) return false;
    var list = doc.groups.filter(function(x){ return x.id !== id; });
    var at = list.length;
    list.forEach(function(x, k){ if(x.id === before) at = k; });
    list.splice(at, 0, g);
    if(list.map(function(x){ return x.id; }).join() === doc.groups.map(function(x){ return x.id; }).join()) return false;
    doc.groups = list; save(); changed();
    return true;
  }
  function moveGroup(id, delta){
    var ids = doc.groups.map(function(x){ return x.id; }), i = ids.indexOf(id), j = i + delta;
    if(i < 0 || j < 0 || j >= ids.length) return false;
    return placeGroup(id, delta < 0 ? ids[j] : (ids[j + 1] || null));
  }

  function nameTaken(name){
    name = String(name || '').trim();
    return doc.groups.some(function(g){ return g.name === name; });
  }
  function importGroup(src, name, codes, asName){
    codes = clean(codes);
    if(asName !== undefined && asName !== null){
      asName = String(asName).trim();
      if(!asName) return null;
      var same = null;
      doc.groups.forEach(function(x){ if(x.name === asName) same = x; });
      if(same){
        var before = same.codes.length;
        same.codes = codes; delete same.hidden; doc.cur = same.id;
        save(); changed();
        return {name: same.name, n: codes.length, prev: before, existed: true, copy: true, replaced: true};
      }
      var ng = {id: uid(), name: asName, codes: codes};
      doc.groups.push(ng); doc.cur = ng.id;
      save(); changed();
      return {name: ng.name, n: codes.length, prev: 0, existed: false, copy: true};
    }
    var g = null;
    doc.groups.forEach(function(x){ if(x.src === src) g = x; });
    var prev = g ? g.codes.length : 0, had = !!g;
    if(!g){
      g = {id: 'src-' + src, name: name, codes: [], src: src};
      if(find(g.id)) g.id = uid();
      doc.groups.push(g);
    }
    g.codes = codes;
    delete g.hidden;
    doc.cur = g.id;
    save(); changed();
    return {name: g.name, n: codes.length, prev: prev, existed: had};
  }
  function sourceGroup(src){
    var out = null;
    doc.groups.forEach(function(x){ if(x.src === src) out = {id: x.id, name: x.name, n: x.codes.length}; });
    return out;
  }

  reload();
  return {reload: reload, has: has, toggle: toggle, paint: paint,
          move: move, top: top, index: index,
          count: function(){ return order.length; },
          order: function(){ return order.slice(); },
          all: function(){ return set; },
          groups: groups, current: function(){ return {id: cur.id, name: cur.name, n: order.length, virtual: !!cur.virtual}; },
          select: select, addGroup: addGroup, renameGroup: renameGroup, removeGroup: removeGroup,
          placeGroup: placeGroup, moveGroup: moveGroup, importGroup: importGroup, sourceGroup: sourceGroup,
          hideGroup: hideGroup, hideAll: hideAll, nameTaken: function(n){ return nameTaken(n); },
          groupsOf: groupsOf, inAny: inAny, setIn: setIn};
})();

window.TWSIXStarMenu = (function(){
  if(typeof TWSIXWatch === 'undefined') return null;
  var box = null, anchor = null;
  function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function close(){
    if(box){ box.remove(); box = null; }
    if(anchor){ try{ anchor.focus(); }catch(e){} anchor = null; }
  }
  function render(code){
    var gs = TWSIXWatch.groups().filter(function(g){ return !g.virtual; });
    var mine = TWSIXWatch.groupsOf(code);
    var h = '<div class="sm-h">把 <b>' + esc(code) + '</b> 放進哪些群組</div><ul class="sm-l">';
    gs.forEach(function(g){
      h += '<li><label><input type="checkbox" data-g="' + esc(g.id) + '"' + (mine.indexOf(g.id) >= 0 ? ' checked' : '') + '> ' +
           esc(g.name) + (g.hidden ? ' <span class="muted">（已隱藏）</span>' : '') + ' <span class="sm-n">' + g.n + '</span></label></li>';
    });
    h += '</ul><div class="sm-f"><button type="button" data-sm="new">＋ 新增群組</button><button type="button" data-sm="done">完成</button></div>';
    box.innerHTML = h;
  }
  function place(){
    var r = anchor.getBoundingClientRect(), w = box.offsetWidth, vw = document.documentElement.clientWidth;
    var left = Math.min(Math.max(8, r.left + window.pageXOffset), window.pageXOffset + vw - w - 8);
    box.style.left = left + 'px';
    box.style.top = (r.bottom + window.pageYOffset + 4) + 'px';
  }
  function open(btn){
    var code = btn.getAttribute('data-star');
    var gs = TWSIXWatch.groups().filter(function(g){ return !g.virtual; });
    if(gs.length === 1){
      TWSIXWatch.setIn(gs[0].id, code, TWSIXWatch.groupsOf(code).indexOf(gs[0].id) < 0);
      return;
    }
    if(box && anchor === btn){ close(); return; }
    close();
    anchor = btn;
    box = document.createElement('div');
    box.className = 'star-menu'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', '選擇群組');
    document.body.appendChild(box);
    render(code); place();
    box.addEventListener('change', function(e){
      var c = e.target.closest('input[data-g]');
      if(c) TWSIXWatch.setIn(c.getAttribute('data-g'), code, c.checked);
    });
    box.addEventListener('click', function(e){
      var b = e.target.closest('button[data-sm]');
      if(!b) return;
      if(b.getAttribute('data-sm') === 'done'){ close(); return; }
      var name = window.prompt('新群組的名稱', '新群組');
      if(name === null) return;
      var id = TWSIXWatch.addGroup(name, true);
      TWSIXWatch.setIn(id, code, true);
      render(code);
    });
    var f = box.querySelector('input'); if(f) f.focus();
  }
  document.addEventListener('click', function(e){
    if(!box) return;
    if(box.contains(e.target) || (anchor && anchor.contains(e.target))) return;
    close();
  }, true);
  document.addEventListener('keydown', function(e){ if(box && e.key === 'Escape') close(); });
  window.addEventListener('resize', function(){ if(box) place(); });

  document.addEventListener('twsix:wgroup', function(){ if(box && anchor) render(anchor.getAttribute('data-star')); });
  return {open: open, close: close};
})();

(function(){
  var btn = document.querySelector('.ident button[data-star], h2 button[data-star]');
  if(!btn) return;
  TWSIXWatch.paint(btn);
  btn.addEventListener('click', function(){
    if(window.TWSIXStarMenu) TWSIXStarMenu.open(btn);
    else TWSIXWatch.toggle(btn.getAttribute('data-star'));
    TWSIXWatch.paint(btn);
  });
  document.addEventListener('twsix:wgroup', function(){ TWSIXWatch.paint(btn); });

  window.addEventListener('pageshow', function(){
    TWSIXWatch.reload();
    TWSIXWatch.paint(btn);
  });
})();

(function(){
  var table = document.getElementById('t');
  if(!table) return;
  var body = table.tBodies[0];
  var rows = [].slice.call(body.rows);

  function paintStar(btn){
    var on = TWSIXWatch.paint(btn);
    var cell = btn.closest('td');
    if(cell) cell.setAttribute('data-s', on ? '1' : '0');
  }
  [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);

  table.addEventListener('click', function(e){
    var btn = e.target.closest('button[data-star]');
    if(!btn) return;
    if(window.TWSIXStarMenu){ TWSIXStarMenu.open(btn); return; }
    TWSIXWatch.toggle(btn.getAttribute('data-star'));
    paintStar(btn);

    applyCustomOrder();
    apply();
    count();
  });

  var sortCol = -1, sortDir = 1;
  function key(tr, col){
    var td = tr.cells[col];
    var raw = td ? (td.getAttribute('data-s') || td.textContent) : '';
    var num = parseFloat(raw);
    return (raw !== '' && !isNaN(num) && /^[-+]?[0-9.]+$/.test(raw.trim())) ? num : raw;
  }
  function sortBy(col){
    if(sortCol === col){ sortDir = -sortDir; } else { sortCol = col; sortDir = -1; }
    var decorated = rows.map(function(tr, i){ return [key(tr, col), i, tr]; });
    decorated.sort(function(a, b){
      if(a[0] < b[0]) return -sortDir;
      if(a[0] > b[0]) return sortDir;
      return a[1] - b[1];
    });
    var frag = document.createDocumentFragment();
    decorated.forEach(function(d){ frag.appendChild(d[2]); });
    body.appendChild(frag);
    [].forEach.call(table.querySelectorAll('th button.sortable'), function(b){
      var mine = +b.getAttribute('data-col') === col;
      b.classList.toggle('asc', mine && sortDir === 1);
      b.classList.toggle('desc', mine && sortDir === -1);
      b.setAttribute('aria-sort', mine ? (sortDir === 1 ? 'ascending' : 'descending') : 'none');
    });
  }
  table.addEventListener('click', function(e){
    var b = e.target.closest('th button.sortable');
    if(b) sortBy(+b.getAttribute('data-col'));
  });

  var watchOrder = table.getAttribute('data-watchlist') === '1';
  function applyCustomOrder(){
    if(!watchOrder) return;
    var pos = {};
    TWSIXWatch.order().forEach(function(code, i){ pos[code] = i; });
    var decorated = rows.map(function(tr, i){
      var p = pos[tr.getAttribute('data-code')];

      return [p === undefined ? Infinity : p, i, tr];
    });
    decorated.sort(function(a, b){ return a[0] - b[0] || a[1] - b[1]; });
    var frag = document.createDocumentFragment();
    decorated.forEach(function(d){ frag.appendChild(d[2]); });
    body.appendChild(frag);
    sortCol = -1;
    [].forEach.call(table.querySelectorAll('th button.sortable'), function(b){
      b.classList.remove('asc', 'desc');
      b.setAttribute('aria-sort', 'none');
    });
    paintMoves();
  }

  function paintMoves(){
    if(!watchOrder) return;

    var byCode = {};
    rows.forEach(function(tr){ byCode[tr.getAttribute('data-code')] = tr; });
    var live = TWSIXWatch.order().filter(function(c){ return byCode[c]; });
    live.forEach(function(code, i){
      var tr = byCode[code];
      var up = tr.querySelector('button.mv-up');
      var dn = tr.querySelector('button.mv-dn');
      var tp = tr.querySelector('button.mv-top');
      if(up) up.disabled = i === 0;
      if(dn) dn.disabled = i === live.length - 1;

      if(tp) tp.disabled = i === 0;
    });
    [].forEach.call(table.querySelectorAll('td.star-cell .mv'), function(el){
      el.hidden = false;
    });
  }
  if(watchOrder){
    table.addEventListener('click', function(e){
      var btn = e.target.closest('button[data-move]');
      if(!btn || btn.disabled) return;
      var code = btn.getAttribute('data-move');
      var delta = btn.getAttribute('data-delta');

      applyCustomOrder();

      var moved_ok = (delta === 'top') ? TWSIXWatch.top(code)
                                       : TWSIXWatch.move(code, +delta);
      if(!moved_ok) return;
      applyCustomOrder();

      var moved = body.querySelector('tr[data-code="' + code + '"] button[data-delta="' +
                                     (delta === 'top' ? 'top' : (+delta < 0 ? '-1' : '1')) + '"]');
      if(moved && !moved.disabled) moved.focus();
      else if(moved) (moved.parentNode.querySelector('button:not([disabled])') || moved).focus();
    });
  }

  var q = document.getElementById('q');
  var onlyWatched = document.getElementById('only-watched');
  var onlyPicks = document.getElementById('only-picks');
  var tally = document.getElementById('tally');
  var watchOnlyPage = table.getAttribute('data-watchlist') === '1';
  var QF = [
            ['ai', document.getElementById('f-ai')], ['cf', document.getElementById('f-cf')], ['gf', document.getElementById('f-gf')]];
  var qfReset = document.getElementById('f-reset');

  var indBtn = document.getElementById('f-indbtn'), indPanel = document.getElementById('f-indpanel');
  var indBoxes = indPanel ? [].slice.call(indPanel.querySelectorAll('input[type=checkbox]')) : [];
  var sMin = document.getElementById('f-smin'), sMax = document.getElementById('f-smax');
  var INDS = null;
  function syncInds(){
    var on = indBoxes.filter(function(c){ return c.checked; }).map(function(c){ return c.value; });
    INDS = on.length === indBoxes.length ? null : new Set(on);
    if(indBtn) indBtn.textContent = (INDS === null ? '全部產業' : (on.length ? '已選 ' + on.length + ' 個產業' : '未選產業')) + ' ▾';
  }

  var rrBtn = document.getElementById('f-rrbtn'), rrPanel = document.getElementById('f-rrpanel');
  var rrBoxes = rrPanel ? [].slice.call(rrPanel.querySelectorAll('input[data-rr]')) : [];
  var rrMin = document.getElementById('f-rrmin'), rrMax = document.getElementById('f-rrmax');
  function rrState(){
    var on = {}; rrBoxes.forEach(function(c){ on[c.getAttribute('data-rr')] = c.checked; });
    var lo = num(rrMin), hi = num(rrMax);
    var useRange = on.range && (lo !== null || hi !== null);
    return {range: useRange, lo: lo, hi: hi, free: on.free, bear: on.bear, na: on.na,
            active: useRange || on.free || on.bear || on.na};
  }
  function rrLabel(){
    if(!rrBtn) return;
    var st = rrState(), parts = [];
    if(st.range) parts.push(st.lo !== null && st.hi !== null ? st.lo + '～' + st.hi : st.lo !== null ? '≥ ' + st.lo : '≤ ' + st.hi);
    if(st.free) parts.push('無風險'); if(st.bear) parts.push('價格高估'); if(st.na) parts.push('—');
    rrBtn.textContent = (parts.length ? parts.join('、') : '全部') + ' ▾';
  }
  function rrPass(tr){
    var st = rrState(); if(!st.active) return true;
    var cat = tr.getAttribute('data-f-rr') || '', v = tr.getAttribute('data-f-rrv');
    if(st.free && cat === 'free') return true;
    if(st.bear && cat === 'bear') return true;
    if(st.na && cat === 'na') return true;
    if(st.range){
      if(cat === 'free') return st.hi === null;
      if(v){ v = parseFloat(v); if((st.lo === null || v >= st.lo - 1e-9) && (st.hi === null || v <= st.hi + 1e-9)) return true; }
    }
    return false;
  }
  function num(el){ if(!el || el.value === '') return null; var v = parseFloat(el.value); return isFinite(v) ? v : null; }

  function visible(tr){
    if(watchOnlyPage || (onlyWatched && onlyWatched.checked)){
      if(!TWSIXWatch.has(tr.getAttribute('data-code'))) return false;
    }

    var pick = tr.querySelector('td.pick-cell');
    var when = tr.querySelector('td.when-cell');

    if(onlyPicks){
      var pv = onlyPicks.type === 'checkbox' ? (onlyPicks.checked ? '1' : '') : onlyPicks.value;
      if(pv && tr.getAttribute('data-f-pick') !== pv) return false;
    }
    if(INDS && !INDS.has(tr.getAttribute('data-f-ind') || '')) return false;
    if(!rrPass(tr)) return false;
    var lo = num(sMin), hi = num(sMax);
    if(lo !== null || hi !== null){
      var sv = tr.getAttribute('data-f-score');
      if(!sv) return false;
      sv = parseFloat(sv);
      if((lo !== null && sv < lo - 1e-9) || (hi !== null && sv > hi + 1e-9)) return false;
    }
    for(var fi = 0; fi < QF.length; fi++){
      var sel = QF[fi][1], want = sel && sel.value;
      if(!want) continue;
      var got = tr.getAttribute('data-f-' + QF[fi][0]) || '';

      if(want === 'any' ? !got : (' ' + got + ' ').indexOf(' ' + want + ' ') < 0) return false;
    }
    var v = q ? q.value.trim().toLowerCase() : '';
    return !v || tr.textContent.toLowerCase().indexOf(v) > -1;
  }

  var FORM_KEY = 'twsix.form.' + (watchOnlyPage ? 'watch' : 'list');
  var restoring = false;
  function formState(){
    var st = {pick: onlyPicks ? (onlyPicks.type === 'checkbox' ? (onlyPicks.checked ? '1' : '') : onlyPicks.value) : '',
              watched: !!(onlyWatched && onlyWatched.checked),
              off: indBoxes.filter(function(c){ return !c.checked; }).map(function(c){ return c.value; }),
              smin: sMin ? sMin.value : '', smax: sMax ? sMax.value : '',
              rr: {}, rrmin: rrMin ? rrMin.value : '', rrmax: rrMax ? rrMax.value : '', qf: {}};
    rrBoxes.forEach(function(c){ st.rr[c.getAttribute('data-rr')] = c.checked; });
    QF.forEach(function(x){ if(x[1]) st.qf[x[0]] = x[1].value; });
    return st;
  }
  function saveForm(){
    if(restoring) return;
    try{ localStorage.setItem(FORM_KEY, JSON.stringify(formState())); }catch(e){}
  }
  function loadForm(){
    var st = null;
    try{ st = JSON.parse(localStorage.getItem(FORM_KEY) || 'null'); }catch(e){}
    if(!st || typeof st !== 'object') return;
    restoring = true;
    if(onlyPicks){ if(onlyPicks.type === 'checkbox') onlyPicks.checked = st.pick === '1'; else onlyPicks.value = st.pick || ''; }
    if(onlyWatched) onlyWatched.checked = !!st.watched;
    var off = new Set(st.off || []);
    indBoxes.forEach(function(c){ c.checked = !off.has(c.value); });
    if(sMin) sMin.value = st.smin || ''; if(sMax) sMax.value = st.smax || '';
    rrBoxes.forEach(function(c){ var k = c.getAttribute('data-rr'); if(st.rr && k in st.rr) c.checked = !!st.rr[k]; });
    if(rrMin) rrMin.value = st.rrmin || ''; if(rrMax) rrMax.value = st.rrmax || '';
    QF.forEach(function(x){ if(x[1] && st.qf && x[0] in st.qf) x[1].value = st.qf[x[0]] || ''; });
    restoring = false;
  }

  function apply(){
    rows.forEach(function(tr){ tr.hidden = !visible(tr); });
    count();
    saveForm();
  }
  function count(){
    if(!tally) return;
    var n = 0;
    rows.forEach(function(tr){ if(!tr.hidden) n++; });

    var txt = watchOnlyPage || n === rows.length
      ? ('<b class="cnt">' + n + '</b> 檔') : ('<b class="cnt">' + n + ' / ' + rows.length + '</b> 檔');

    if(watchOnlyPage && typeof TWSIXWatch !== 'undefined'){
      var have = {};
      rows.forEach(function(tr){ have[tr.getAttribute('data-code')] = 1; });
      var lost = TWSIXWatch.order().filter(function(c){ return !have[c]; });
      var hid = 0;
      rows.forEach(function(tr){ if(tr.hidden && TWSIXWatch.has(tr.getAttribute('data-code'))) hid++; });
      if(hid) txt += '（另有 <b class="cnt">' + hid + '</b> 檔被上面的篩選條件藏起來）';
      if(lost.length) txt += '（<b class="cnt">' + lost.length + '</b> 檔查無資料：' + lost.slice(0, 8).join('、') + (lost.length > 8 ? '…' : '') + '）';
    }
    tally.innerHTML = txt;
  }
  [q, onlyWatched, onlyPicks, sMin, sMax].concat(QF.map(function(x){ return x[1]; })).forEach(function(el){
    if(el) el.addEventListener(el.tagName === 'INPUT' && (el.type === 'search' || el.type === 'number') ? 'input' : 'change', apply);
  });
  indBoxes.forEach(function(c){ c.addEventListener('change', function(){ syncInds(); apply(); }); });
  rrBoxes.forEach(function(c){ c.addEventListener('change', function(){ rrLabel(); apply(); }); });
  [rrMin, rrMax].forEach(function(el){ if(el) el.addEventListener('input', function(){
    var box = rrPanel.querySelector('input[data-rr=range]'); if(box && el.value !== '') box.checked = true;
    rrLabel(); apply(); }); });
  if(rrBtn && rrPanel){
    rrBtn.addEventListener('click', function(e){
      e.stopPropagation(); rrPanel.hidden = !rrPanel.hidden;
      rrBtn.setAttribute('aria-expanded', rrPanel.hidden ? 'false' : 'true');
    });
    document.addEventListener('click', function(e){
      if(!rrPanel.hidden && !rrPanel.contains(e.target) && e.target !== rrBtn){
        rrPanel.hidden = true; rrBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }
  if(indPanel) [].forEach.call(indPanel.querySelectorAll('button[data-inds]'), function(b){
    b.addEventListener('click', function(){
      var all = b.getAttribute('data-inds') === 'all';
      indBoxes.forEach(function(c){ c.checked = all; }); syncInds(); apply();
    });
  });
  if(indBtn && indPanel){
    indBtn.addEventListener('click', function(e){
      e.stopPropagation(); indPanel.hidden = !indPanel.hidden;
      indBtn.setAttribute('aria-expanded', indPanel.hidden ? 'false' : 'true');
    });
    document.addEventListener('click', function(e){
      if(!indPanel.hidden && !indPanel.contains(e.target) && e.target !== indBtn){
        indPanel.hidden = true; indBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }
  if(qfReset) qfReset.addEventListener('click', function(){
    QF.forEach(function(x){ if(x[1]) x[1].value = ''; });
    if(onlyPicks){ if(onlyPicks.type === 'checkbox') onlyPicks.checked = false; else onlyPicks.value = ''; }
    if(q) q.value = '';
    indBoxes.forEach(function(c){ c.checked = true; }); syncInds();
    if(sMin) sMin.value = ''; if(sMax) sMax.value = '';
    rrBoxes.forEach(function(c){ c.checked = c.getAttribute('data-rr') === 'range'; });
    if(rrMin) rrMin.value = ''; if(rrMax) rrMax.value = ''; rrLabel();
    apply();
  });
  loadForm();
  syncInds(); rrLabel();
  applyCustomOrder();
  apply();

  function resync(){
    syncInds(); rrLabel();
    TWSIXWatch.reload();
    [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);
    applyCustomOrder();
    apply();
  }
  window.addEventListener('pageshow', resync);
  window.addEventListener('load', resync);

  var empty = document.getElementById('watch-empty');
  var show = function(){ if(empty) empty.hidden = TWSIXWatch.count() > 0; };
  show();
  if(empty) table.addEventListener('click', show);

  document.addEventListener('twsix:wgroup', function(){
    [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);
    applyCustomOrder(); apply(); count(); show();
  });
})();

(function(){
  var frames = document.querySelectorAll('iframe.embed.fit');
  if(!frames.length) return;

  function contentHeight(doc){
    var body = doc && doc.body;
    if(!body) return 0;
    var cs = doc.defaultView.getComputedStyle(body);
    return body.getBoundingClientRect().height +
           parseFloat(cs.marginTop || 0) + parseFloat(cs.marginBottom || 0);
  }

  function realDoc(frame){
    var doc;
    try{ doc = frame.contentDocument; }catch(e){ return null; }
    if(!doc || !doc.body) return null;
    var href = doc.location && doc.location.href;
    if(!href || href === 'about:blank') return null;
    return doc;
  }

  var GROW_LIMIT = 40;

  function fit(frame, state){
    var doc = realDoc(frame);
    if(!doc) return;
    if(state.bailed) return;
    var h = contentHeight(doc);
    if(!(h > 0)) return;
    var target = Math.ceil(h) + 2;
    var now = parseFloat(frame.style.height) || 0;

    if(Math.abs(target - now) <= 4) { state.grow = 0; return; }
    if(target > now){
      if(++state.grow > GROW_LIMIT){
        state.bailed = true;
        if(state.ro) state.ro.disconnect();
        frame.style.height = '';
        return;
      }
    } else {
      state.grow = 0;
    }
    frame.style.height = target + 'px';
  }

  frames.forEach(function(frame){
    var state = { grow: 0, bailed: false, ro: null };

    var watching = null;

    function attach(){
      var doc = realDoc(frame);
      if(!doc || state.bailed) return;

      if(watching && watching !== doc.body) state.grow = 0;
      fit(frame, state);
      if(typeof ResizeObserver === 'undefined') return;
      if(watching === doc.body) return;
      if(state.ro) state.ro.disconnect();
      state.ro = new ResizeObserver(function(){ fit(frame, state); });
      state.ro.observe(doc.body);
      watching = doc.body;
    }

    frame.addEventListener('load', attach);
    attach();

    window.addEventListener('resize', function(){ state.grow = 0; fit(frame, state); });

    if(document.fonts && document.fonts.ready) document.fonts.ready.then(attach);

    [200, 800, 2000, 5000].forEach(function(ms){ setTimeout(attach, ms); });
  });
})();

(function(){
  var box = document.getElementById('calc');
  if(!box) return;

  var seed = {};
  try{ seed = JSON.parse(box.getAttribute('data-seed') || '{}'); }catch(e){ return; }
  var market = parseFloat(box.getAttribute('data-price'));
  if(isNaN(market) || market <= 0) market = null;

  var priceDate = box.getAttribute('data-price-date') || '';

  var costKey = 'twsix.cost.' + (box.getAttribute('data-code') || '');
  var costIn = document.getElementById('c-cost');
  var costReset = document.getElementById('c-cost-reset');
  var costNote = document.getElementById('c-cost-note');
  var cost = null;
  var price = market;
  function readCost(){
    var v = costIn ? parseFloat(costIn.value) : NaN;
    return (isNaN(v) || v <= 0) ? null : v;
  }
  function applyCost(){
    cost = readCost();
    price = cost !== null ? cost : market;
    try{
      if(cost !== null) localStorage.setItem(costKey, String(cost));
      else localStorage.removeItem(costKey);
    }catch(e){}
    if(costReset) costReset.hidden = cost === null;
    if(costNote){
      costNote.textContent = cost !== null
        ? (market !== null ? '現價 ' + market.toFixed(2) + '，相對成本 ' +
           (market >= cost ? '+' : '−') + (Math.abs(market / cost - 1) * 100).toFixed(1) + '%' : '')
        : (market !== null ? '空白＝用現價 ' + market.toFixed(2) +
           (priceDate ? '（' + priceDate + ' 收盤）' : '') : '這一檔還沒有收盤價，填了成本才算得出報酬與風險');
    }
  }
  if(costIn){
    try{
      var saved = parseFloat(localStorage.getItem(costKey));
      if(!isNaN(saved) && saved > 0) costIn.value = String(saved);
    }catch(e){}
  }
  applyCost();
  function priceLabel(){
    if(cost !== null) return '進場成本 ' + cost.toFixed(2);
    return '現價 ' + price.toFixed(2) + (priceDate ? '（' + priceDate + ' 收盤）' : '');
  }

  var el = {
    rev: document.getElementById('c-rev'), sh: document.getElementById('c-sh'),
    g: document.getElementById('c-g'), m: document.getElementById('c-m'),
    pe: document.getElementById('c-pe'), out: document.getElementById('calc-out'),
    basis: document.getElementById('calc-basis')
  };

  function pct(x){ return x === null || x === undefined ? null : x * 100; }
  function r1(x){ return x === null || x === undefined ? '' : Math.round(x * 10) / 10; }

  function defaults(){
    var g = seed.growth || {}, m = seed.margin || {}, pe = seed.pe || {};
    var mid = pct(m.avg), sd = pct(m.sigma) || 0;

    var lo = pct(g.latest), hi = pct(g.recent6);
    if(lo === null && hi === null){ lo = 0; hi = 10; }
    if(lo === null) lo = hi; if(hi === null) hi = lo;
    var a = Math.min(lo, hi), b = Math.max(lo, hi);
    return {
      rev: seed.revenue ? Math.round(seed.revenue) : '',
      sh: seed.shares ? Math.round(seed.shares * 100) / 100 : '',
      g: [r1(a), r1((a + b) / 2), r1(b)].join(', '),
      m: mid === null ? '' : [r1(mid - sd), r1(mid), r1(mid + sd)].join(', '),
      pe: [pe.low, pe.mid, pe.high].map(function(v){ return v ? Math.round(v * 10) / 10 : ''; })
            .filter(function(v){ return v !== ''; }).join(', ') || '15, 20, 25'
    };
  }

  function fill(d){
    el.rev.value = d.rev; el.sh.value = d.sh;
    el.g.value = d.g; el.m.value = d.m; el.pe.value = d.pe;
  }

  function basis(){
    var g = seed.growth || {}, m = seed.margin || {}, pe = seed.pe || {};
    var bits = [];
    if(g.latest !== undefined && g.latest !== null) bits.push('最近月 ' + r1(pct(g.latest)) + '%');
    if(g.recent6 !== undefined && g.recent6 !== null) bits.push('近六月均 ' + r1(pct(g.recent6)) + '%');
    var out = [];
    if(bits.length) out.push('營收成長率參考：' + bits.join('、') + '（月營收年增率）');
    if(m.avg !== undefined && m.avg !== null){
      out.push('淨利率：中性 ' + r1(pct(m.avg)) + '%（近四季平均）± σ ' +
               r1(pct(m.sigma)) + '%（近四季樣本標準差）');
    }
    if(pe.low) out.push('本益比：' + r1(pe.low) + ' / ' + r1(pe.mid) + ' / ' + r1(pe.high) +
                        '（本益比估價區間的低／中／高）');
    out.push('年營收採去年全年；股數為加權平均股數。以上是預設值的出處，改動之後就是你自己的假設。');
    el.basis.innerHTML = '<b>預設值怎麼來的。</b>　' + out.join('；');
  }

  function nums(text){
    return String(text || '').split(/[,，\s]+/)
      .map(function(t){ return parseFloat(t); })
      .filter(function(v){ return !isNaN(v); });
  }

  function stepper(values){
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    var span = hi - lo;
    return function(v){
      if(!isFinite(v)) return 0;
      return span <= 0 ? 2 : Math.round((v - lo) / span * 4);
    };
  }

  function delta(target){
    if(price === null || !target) return null;
    var up = target / price - 1;
    var txt = (up >= 0 ? '+' : '−') + (Math.abs(up) * 100).toFixed(1) + '%';
    return { text: txt, title: (up >= 0 ? '預期報酬 ' : '預期風險 ') + txt +
             '（相對' + priceLabel() + '）' };
  }

  function legend(fam, lo, hi, fmt){
    return '<p class="mlegend"><b>顏色</b>　數值由小到大、由淺至深' +
      '<span class="ramp">' + [0,1,2,3,4].map(function(i){
        return '<span class="sw" style="background:var(--m' + fam + i + ')"></span>';
      }).join('') + '</span>' +
      '<span>' + fmt(lo) + ' → ' + fmt(hi) + '</span>' +
      (price === null ? '' :
       '<span' + (cost !== null ? ' class="bycost"' : '') + '>　每格第二行是相對' +
       priceLabel() + ' 的預期報酬（＋）或預期風險（−）</span>') + '</p>';
  }

  var CORNER = '<th class="corner">' +
    '<span class="ax-col">淨利率 →</span>' +
    '<span class="ax-row">↓ 成長率</span></th>';

  function matrix(title, values, fmt, fam, tone, withDelta){
    var g = nums(el.g.value), m = nums(el.m.value);
    var rows = g.slice().reverse();
    var flat = [];
    rows.forEach(function(gv){ m.forEach(function(mv){ flat.push(values(gv, mv)); }); });
    if(!flat.length) return '';
    var step = stepper(flat);
    var t = ' mt' + (tone || 0);

    var h = '<h5 class="mtitle' + t + '">' + title + '</h5>';
    h += legend(fam, Math.min.apply(null, flat), Math.max.apply(null, flat), fmt);
    h += '<div class="scroll mwrap' + t + '"><table class="matrix' + t + '"><thead><tr>' +
         CORNER;
    m.forEach(function(v){ h += '<th class="num">' + v + '%</th>'; });
    h += '</tr></thead><tbody>';
    rows.forEach(function(gv){
      h += '<tr><th scope="row">' + gv + '%</th>';
      m.forEach(function(mv){
        var v = values(gv, mv);
        var d = withDelta ? delta(v) : null;
        h += '<td class="num m' + fam + step(v) + '"' +
             (d ? ' title="' + d.title + '"' : '') + '>' +
             '<span class="v">' + fmt(v) + '</span>' +
             (d ? '<span class="d">' + d.text + '</span>' : '') + '</td>';
      });
      h += '</tr>';
    });
    return h + '</tbody></table></div>';
  }

  function run(){
    var rev = parseFloat(el.rev.value), sh = parseFloat(el.sh.value);
    if(isNaN(rev) || isNaN(sh) || !sh){
      el.out.innerHTML = '<p class="stale">年營收與股數都要填，而且股數不能是 0。</p>';
      return;
    }

    function eps(gv, mv){ return rev * (1 + gv / 100) * (mv / 100) / (sh * 100); }
    function money(v){ return Math.round(v).toLocaleString(); }

    var html = matrix('預估 EPS（元）', eps,
      function(v){ return v.toFixed(2); }, 'n', 0, false);

    var fams = ['a', 'b', 'c'];
    nums(el.pe.value).slice().sort(function(a, b){ return a - b; })
      .forEach(function(pe, i){
        html += matrix('預估目標價（元）　本益比 ' + pe,
          function(gv, mv){ return eps(gv, mv) * pe; },
          money, fams[i % 3], i % 3 + 1, true);
      });
    el.out.innerHTML = html;
  }

  document.getElementById('c-run').addEventListener('click', run);
  document.getElementById('c-reset').addEventListener('click', function(){
    fill(defaults()); run();
  });

  if(costIn){
    costIn.addEventListener('input', function(){ applyCost(); run(); });
    costIn.addEventListener('keydown', function(e){ if(e.key === 'Enter') run(); });
  }
  if(costReset){
    costReset.addEventListener('click', function(){
      costIn.value = ''; applyCost(); run(); costIn.focus();
    });
  }
  [el.rev, el.sh, el.g, el.m, el.pe].forEach(function(i){
    i.addEventListener('change', run);
    i.addEventListener('keydown', function(e){ if(e.key === 'Enter') run(); });
  });

  fill(defaults());
  basis();
  run();
})();

(function(){
  var top = document.getElementById('totop');
  if(top){

    var embed = document.querySelector('iframe.embed.fit');
    var anchor = null;
    if(embed){
      anchor = embed.previousElementSibling;
      while(anchor && anchor.nodeType !== 1) anchor = anchor.previousElementSibling;
      if(!anchor) anchor = embed;

      top.setAttribute('aria-label', '回到報告最上方');
      top.setAttribute('title', '回到報告最上方');
    }
    var target = function(){
      if(!anchor) return 0;

      var y = anchor.getBoundingClientRect().top +
              (window.pageYOffset || document.documentElement.scrollTop) - 12;
      return y > 0 ? y : 0;
    };

    var show = function(){
      var y = window.pageYOffset || document.documentElement.scrollTop;

      top.hidden = (y - target()) < 400;
    };
    window.addEventListener('scroll', show, { passive: true });
    window.addEventListener('resize', show);
    show();
    top.addEventListener('click', function(){

      var soft = !window.matchMedia ||
                 !matchMedia('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: target(), behavior: soft ? 'smooth' : 'auto' });
    });
  }

  try{ localStorage.removeItem('twsix.viewmode'); }catch(e){}
  try{ document.documentElement.removeAttribute('data-view'); }catch(e){}
})();

(function(){

  document.documentElement.classList.add('js');

  var open = null;

  function close(){
    if(!open) return;
    open.classList.remove('open','flip');
    var box = open.querySelector('.tipbox');
    if(box) box.style.transform = '';
    var b = open.querySelector('button.bulb');
    if(b) b.setAttribute('aria-expanded','false');
    open = null;
  }

  function show(tip){
    close();
    tip.classList.add('open');
    var b = tip.querySelector('button.bulb');
    if(b) b.setAttribute('aria-expanded','true');
    open = tip;

    var box = tip.querySelector('.tipbox');
    if(!box) return;
    box.style.transform = '';
    if(box.getBoundingClientRect().right > window.innerWidth - 8){
      tip.classList.add('flip');
    }

    var r = box.getBoundingClientRect();
    var shift = 0;
    var over = r.right - (window.innerWidth - 8);
    if(over > 0) shift = -over;
    if(r.left + shift < 8) shift = 8 - r.left;

    if(shift) box.style.transform = 'translateX(' + Math.round(shift) + 'px)';
  }

  document.addEventListener('click', function(e){
    var b = e.target.closest ? e.target.closest('button.bulb') : null;
    if(b){
      var tip = b.parentNode;
      if(tip === open) close(); else show(tip);
      e.preventDefault();
      return;
    }

    if(open && e.target.closest && e.target.closest('.tipbox')) return;
    close();
  });

  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape' && open){
      var b = open.querySelector('button.bulb');
      close();

      if(b) b.focus();
    }
  });
})();

(function(){
  [].forEach.call(document.querySelectorAll('.subtabs'), function(bar){
    var btns = [].slice.call(bar.querySelectorAll('[data-sub]'));
    function show(id){
      btns.forEach(function(b){
        var on = b.getAttribute('data-sub') === id;
        b.setAttribute('aria-selected', on ? 'true' : 'false');
        var panel = document.getElementById(b.getAttribute('data-sub'));
        if(panel) panel.hidden = !on;
      });
    }
    btns.forEach(function(b){
      b.addEventListener('click', function(){ show(b.getAttribute('data-sub')); });
    });
  });
})();

var TWSIXChart = (function(){
  var NS = 'http://www.w3.org/2000/svg';
  function cssVar(name, fallback){
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }
  function el(tag, attrs){
    var e = document.createElementNS(NS, tag);
    for(var k in attrs) if(attrs.hasOwnProperty(k)) e.setAttribute(k, attrs[k]);
    return e;
  }
  function nice(lo, hi, n){
    if(!(hi > lo)){ hi = lo + 1; lo = lo - 1; }
    var span = hi - lo, raw = span / n;
    var p = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var step = [1, 2, 2.5, 5, 10].map(function(m){ return m * p; })
      .filter(function(s){ return s >= raw; })[0] || raw;
    var a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, out = [];
    for(var v = a; v <= b + step / 2; v += step) out.push(Math.round(v * 1e6) / 1e6);
    return out;
  }
  function fmtNum(v){
    if(v === null || v === undefined || isNaN(v)) return '—';
    var a = Math.abs(v);
    return v.toLocaleString(undefined, {maximumFractionDigits: a >= 1000 ? 0 : 2});
  }

  function draw(box, o){
    box.innerHTML = '';
    var W = Math.max(280, box.clientWidth || 600);
    var H = o.height || (W < 560 ? 230 : 300);
    var m = {l: 50, r: 12, t: o.title ? 26 : 10, b: 26};
    var i0 = o.range ? o.range[0] : 0, i1 = o.range ? o.range[1] : o.x.length - 1;
    if(i1 < i0){ var t = i0; i0 = i1; i1 = t; }
    var n = i1 - i0 + 1;
    var lo = Infinity, hi = -Infinity;

    var main = o.series.filter(function(s){ return !s.axis2; }), sec = o.series.filter(function(s){ return s.axis2; });
    if(main.some(function(s){ return s.bar; })){ lo = 0; hi = 0; }
    main.forEach(function(s){
      for(var i = i0; i <= i1; i++){
        var v = s.values[i];
        if(v === null || v === undefined || isNaN(v)) continue;
        if(v < lo) lo = v; if(v > hi) hi = v;
      }
    });
    (o.hlines || []).forEach(function(h){ if(h.value < lo) lo = h.value; if(h.value > hi) hi = h.value; });
    if(o.yMin !== undefined) lo = o.yMin;
    if(o.yMax !== undefined) hi = o.yMax;
    if(!isFinite(lo)){ box.innerHTML = '<p class="stale">這一段沒有資料。</p>'; return; }
    var pad = (hi - lo) * 0.04;
    var ticks = (o.yMin !== undefined && o.yMax !== undefined)
      ? (function(){ var a = []; for(var v = o.yMin; v <= o.yMax; v++) a.push(v); return a; })()
      : nice(lo - pad, hi + pad, 5);
    var y0 = ticks[0], y1 = ticks[ticks.length - 1];
    if(sec.length) m.r = 52;
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var lo2 = Infinity, hi2 = -Infinity;
    sec.forEach(function(s){
      for(var i = i0; i <= i1; i++){ var v = s.values[i]; if(v === null || v === undefined || isNaN(v)) continue; if(v < lo2) lo2 = v; if(v > hi2) hi2 = v; }
    });
    var t2 = isFinite(lo2) ? nice(lo2 - (hi2 - lo2) * 0.04, hi2 + (hi2 - lo2) * 0.04, 4) : null;
    function X(i){ return m.l + (n <= 1 ? pw / 2 : (i - i0) / (n - 1) * pw); }
    function Y(v){ return m.t + ph - (v - y0) / (y1 - y0) * ph; }
    function Y2(v){ return m.t + ph - (v - t2[0]) / (t2[t2.length - 1] - t2[0]) * ph; }
    var ink = cssVar('--ink', '#111'), muted = cssVar('--muted', '#777'), rule = cssVar('--rule', '#ddd');
    var svg = el('svg', {viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, class: 'pxsvg', role: 'img'});
    if(o.title){
      var tt = el('text', {x: W / 2, y: 16, 'text-anchor': 'middle', class: 'pxt'});
      tt.textContent = o.title; svg.appendChild(tt);
    }
    ticks.forEach(function(v){
      svg.appendChild(el('line', {x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), stroke: rule, 'stroke-width': 1}));
      var tx = el('text', {x: m.l - 6, y: Y(v) + 4, 'text-anchor': 'end', class: 'pxa'});
      tx.textContent = fmtNum(v); svg.appendChild(tx);
    });

    var nx = (typeof o.xTicks === 'function' && o.xTicks(W)) || (W < 560 ? 4 : 7);
    for(var k = 0; k < nx; k++){
      var i = Math.round(i0 + (n - 1) * k / (nx - 1));
      var lx = el('text', {x: X(i), y: H - 8, 'text-anchor': k === 0 ? 'start' : (k === nx - 1 ? 'end' : 'middle'), class: 'pxa'});
      lx.textContent = o.x[i]; svg.appendChild(lx);
      svg.appendChild(el('line', {x1: X(i), x2: X(i), y1: m.t, y2: m.t + ph, stroke: rule, 'stroke-width': 1, opacity: .6}));
    }
    if(t2) t2.forEach(function(v){
      var tx2 = el('text', {x: W - m.r + 6, y: Y2(v) + 4, 'text-anchor': 'start', class: 'pxa'});
      tx2.textContent = fmtNum(v); svg.appendChild(tx2);
    });
    (o.hlines || []).forEach(function(h){
      svg.appendChild(el('line', {x1: m.l, x2: W - m.r, y1: Y(h.value), y2: Y(h.value),
        stroke: h.color, 'stroke-width': 1.4, 'stroke-dasharray': '6 4'}));
    });
    main.filter(function(s){ return s.bar; }).forEach(function(s){
      var bw = Math.max(1, pw / n * 0.7), base = Y(0);
      for(var i = i0; i <= i1; i++){
        var v = s.values[i];
        if(v === null || v === undefined || isNaN(v) || v === 0) continue;
        var yv = Y(v);
        svg.appendChild(el('rect', {x: (X(i) - bw / 2).toFixed(1), y: Math.min(yv, base).toFixed(1), width: bw.toFixed(1),
          height: Math.max(0.5, Math.abs(base - yv)).toFixed(1), fill: v > 0 ? (s.up || s.color) : (s.down || s.color)}));
      }
    });
    o.series.forEach(function(s, si){
      if(s.bar) return;
      var YY = s.axis2 && t2 ? Y2 : Y;
      var d = '', started = false, prevY = null;
      for(var i = i0; i <= i1; i++){
        var v = s.values[i];
        if(v === null || v === undefined || isNaN(v)){ started = false; continue; }
        if(!started){ d += 'M' + X(i).toFixed(1) + ' ' + YY(v).toFixed(1); started = true; }
        else if(s.step){ d += 'H' + X(i).toFixed(1) + 'V' + YY(v).toFixed(1); }
        else d += 'L' + X(i).toFixed(1) + ' ' + YY(v).toFixed(1);
        prevY = v;
      }
      if(s.area && d){
        var gid = 'g' + Math.random().toString(36).slice(2);

        var grad = el('linearGradient', {id: gid, gradientUnits: 'userSpaceOnUse',
          x1: 0, y1: m.t, x2: 0, y2: m.t + ph});
        s.area.forEach(function(st){ grad.appendChild(el('stop', {offset: st[0], 'stop-color': st[1], 'stop-opacity': st[2]})); });
        var defs = el('defs', {}); defs.appendChild(grad); svg.appendChild(defs);
        var first = s.values.slice(i0, i1 + 1).findIndex(function(v){ return v !== null && v !== undefined; });
        if(first >= 0){
          var fa = d + 'V' + (m.t + ph) + 'H' + X(i0 + first).toFixed(1) + 'Z';
          svg.appendChild(el('path', {d: fa, fill: 'url(#' + gid + ')', stroke: 'none'}));
        }
      }
      svg.appendChild(el('path', {d: d, fill: 'none', stroke: s.color === 'ink' ? ink : s.color,
        'stroke-width': s.width || 1.4, 'stroke-dasharray': s.dash || '', 'stroke-linejoin': 'round'}));
    });
    var cross = el('line', {y1: m.t, y2: m.t + ph, stroke: muted, 'stroke-dasharray': '3 3', visibility: 'hidden'});
    svg.appendChild(cross);
    var hit = el('rect', {x: m.l, y: m.t, width: pw, height: ph, fill: 'transparent'});
    svg.appendChild(hit);
    box.appendChild(svg);
    var tip = document.createElement('div');
    tip.className = 'pxtip'; tip.hidden = true; box.appendChild(tip);
    function move(ev){
      var r = svg.getBoundingClientRect();
      var cx = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
      var i = Math.round(i0 + (cx * W / r.width - m.l) / pw * (n - 1));
      i = Math.max(i0, Math.min(i1, i));
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i));
      cross.setAttribute('visibility', 'visible');
      var h = '<b>' + o.x[i] + '</b>';
      o.series.forEach(function(s){
        h += '<span><i style="background:' + (s.color === 'ink' ? ink : s.color) + '"></i>' + s.name +
             '<em>' + (s.fmt ? s.fmt(s.values[i]) : o.fmt ? o.fmt(s.values[i]) : fmtNum(s.values[i])) + '</em></span>';
      });
      tip.innerHTML = h; tip.hidden = false;
      var px = X(i) * r.width / W;
      tip.style.left = Math.min(Math.max(4, px + 12), r.width - tip.offsetWidth - 4) + 'px';
      tip.style.top = (m.t + 6) + 'px';
    }
    function leave(){ cross.setAttribute('visibility', 'hidden'); tip.hidden = true; }
    hit.addEventListener('mousemove', move);
    hit.addEventListener('touchstart', move, {passive: true});
    hit.addEventListener('touchmove', move, {passive: true});
    hit.addEventListener('mouseleave', leave);
    var legend = document.createElement('div');
    legend.className = 'pxlegend';
    o.series.concat(o.hlines || []).forEach(function(s){
      if(!s.name && !s.label) return;
      var c = s.color === 'ink' ? ink : s.color;
      legend.innerHTML += '<span><i class="' + (s.value !== undefined || s.dash ? 'dash' : '') +
        '" style="border-color:' + c + ';background:' + (s.value !== undefined || s.dash ? 'transparent' : c) +
        '"></i>' + (s.name || s.label) + '</span>';
    });
    box.appendChild(legend);
  }

  return function(box, opts){
    box._pxOpts = opts;
    draw(box, opts);
    if(!box._pxObs && typeof ResizeObserver !== 'undefined'){
      var last = box.clientWidth;
      box._pxObs = new ResizeObserver(function(){
        if(Math.abs(box.clientWidth - last) < 4) return;
        last = box.clientWidth;
        draw(box, box._pxOpts);
      });
      box._pxObs.observe(box);
    }
  };
})();

(function(){
  var stat = document.getElementById('inst-static'), live = document.getElementById('inst-live');
  if(!stat || !live) return;
  var tab = document.getElementById('tab-inst'), started = false;
  function $(id){ return document.getElementById(id); }
  function start(){
    if(started || live.offsetParent === null && stat.offsetParent === null) return;
    started = true;
    var H = typeof pxHistory === 'function' ? pxHistory() : null;
    if(!H) return;
    window.TWSIXgz(stat.getAttribute('data-src'), {cache: 'no-cache'}).then(function(j){
      if(!j || j.d0 !== H.d[0] || j.n !== H.d.length) return;
      var D = H.d, C = H.c, N = D.length, F = j.f, S = j.s;
      var r0 = $('inst-r0'), r1 = $('inst-r1'), view = [Math.max(0, N - 120), N - 1];
      var fmtLot = function(v){ return v === null || v === undefined ? '—' : Math.round(v).toLocaleString() + ' 張'; };
      var fmtPx = function(v){ return v === null || v === undefined ? '—' : v.toLocaleString(); };
      function draw(){
        TWSIXChart($('inst-c1'), {x: D, range: view, height: 240, series: [
          {name: '外資買賣超', color: '#e0582a', up: '#e5484d', down: '#2fa86b', bar: true, values: F, fmt: fmtLot},
          {name: '收盤價', color: '#8a929b', values: C, axis2: true, width: 1.3, dash: '4 3', fmt: fmtPx}]});
        TWSIXChart($('inst-c2'), {x: D, range: view, height: 240, series: [
          {name: '外資持股比重', color: '#2563eb', values: S, width: 1.6, fmt: function(v){ return v === null || v === undefined ? '—' : v.toFixed(2) + '%'; }},
          {name: '收盤價', color: '#8a929b', values: C, axis2: true, width: 1.3, dash: '4 3', fmt: fmtPx}]});

        var dense = view[0], miss = 0;
        for(var k = view[1]; k >= view[0]; k--){
          if(S[k] === null || S[k] === undefined){ if(++miss >= 5){ dense = k + miss; break; } } else miss = 0;
        }
        $('inst-span').textContent = D[view[0]] + ' ～ ' + D[view[1]] + '（' + (view[1] - view[0] + 1) + ' 個交易日）' +
          (dense > view[0] + 5 && dense <= view[1] ? '；外資持股比重從 ' + D[dense] + ' 起每天都有，更早只有零星幾天（圖上是斷的）' : '');
      }
      function setView(a, b){ view = [Math.max(0, Math.min(a, b)), Math.min(N - 1, Math.max(a, b))]; r0.value = view[0]; r1.value = view[1]; draw(); }
      r0.max = r1.max = N - 1; r0.value = view[0]; r1.value = view[1];
      var pend = 0;
      function slide(){ if(pend) return; pend = requestAnimationFrame(function(){ pend = 0; setView(+r0.value, +r1.value); }); }
      r0.addEventListener('input', slide); r1.addEventListener('input', slide);
      [].forEach.call(live.querySelectorAll('[data-zoom]'), function(b){
        b.addEventListener('click', function(){
          [].forEach.call(live.querySelectorAll('[data-zoom]'), function(x){ x.classList.toggle('on', x === b); });
          var n = +b.getAttribute('data-zoom'); setView(n ? N - n : 0, N - 1);
        });
      });
      stat.hidden = true; live.hidden = false;
      draw();
    }).catch(function(){   });
  }
  if(tab) tab.addEventListener('click', function(){ setTimeout(start, 0); });
  if(location.hash === '#inst') setTimeout(start, 300);
})();

function pxDecode(raw){
  if(!raw || !raw.d0 || !raw.c) return null;
  var p = raw.d0.split('-');
  var t = Date.UTC(+p[0], +p[1] - 1, +p[2]);
  var dates = [raw.d0];
  for(var i = 0; i < (raw.g || '').length; i++){
    t += (raw.g.charCodeAt(i) - 48) * 86400000;
    dates.push(new Date(t).toISOString().slice(0, 10));
  }
  return {d: dates, c: raw.c.slice()};
}
function pxHistory(){
  var node = document.getElementById('px-hist');
  if(!node) return null;
  try{ return pxDecode(JSON.parse(node.textContent)); }catch(e){ return null; }
}

function pxSMA(c, n){
  var out = new Array(c.length), s = 0;
  for(var i = 0; i < c.length; i++){
    s += c[i];
    if(i >= n) s -= c[i - n];
    out[i] = i >= n - 1 ? s / n : null;
  }
  return out;
}

function pxChecks(C, MA, i, P){
  function winMax(i, n){ var m = -Infinity; for(var k = Math.max(0, i - n + 1); k <= i; k++) if(C[k] > m) m = C[k]; return m; }
  function winMin(i, n){ var m = Infinity; for(var k = Math.max(0, i - n + 1); k <= i; k++) if(C[k] < m) m = C[k]; return m; }
  function f2(v){ return v.toFixed(2); }
  var w1 = Math.round(P.m1 * 21), w2 = Math.round(P.m2 * 21), c = C[i], rows = [];
  if(i >= w1 - 1){
    var hi = winMax(i, w1), dd = (1 - c / hi) * 100;
    rows.push({label: P.m1 + ' 個月內從高檔下跌 ≥ ' + P.p1 + '%', ok: dd < P.p1,
      text: '區間高點 ' + f2(hi) + '，目前 ' + f2(c) + '，回檔 ' + dd.toFixed(1) + '%'});
  } else rows.push({label: P.m1 + ' 個月內從高檔下跌 ≥ ' + P.p1 + '%', ok: null, text: '資料不足'});
  if(i >= w2 - 1){
    var lo = winMin(i, w2), up = (c / lo - 1) * 100;
    rows.push({label: P.m2 + ' 個月內從低檔上漲 ≥ ' + P.p2 + '%', ok: up >= P.p2,
      text: '區間低點 ' + f2(lo) + '，目前 ' + f2(c) + '，自低點 ' + (up >= 0 ? '+' : '') + up.toFixed(1) + '%' +
            (up >= P.p2 ? '' : '（未達 ' + P.p2 + '%）')});
  } else rows.push({label: P.m2 + ' 個月內從低檔上漲 ≥ ' + P.p2 + '%', ok: null, text: '資料不足'});
  if(i >= P.d3){
    var pl = winMin(i - 1, P.d3);
    rows.push({label: '股價低於前 ' + P.d3 + ' 個交易日低點', ok: c >= pl,
      text: '前 ' + P.d3 + ' 日低點 ' + f2(pl) + '，目前 ' + f2(c)});
  } else rows.push({label: '股價低於前 ' + P.d3 + ' 個交易日低點', ok: null, text: '資料不足'});
  [[20, '月線'], [60, '季線'], [240, '年線']].forEach(function(p){
    var v = MA[p[0]][i];
    rows.push({label: '股價低於' + p[1] + '(' + p[0] + 'MA)', ok: v === null ? null : c >= v,
      text: v === null ? '資料不足（要 ' + p[0] + ' 個交易日）' : p[1] + '(' + p[0] + 'MA) ' + f2(v) + '，目前 ' + f2(c)});
  });
  return rows;

}

(function(){
  var root = document.getElementById('pxh');
  if(!root) return;
  var H = pxHistory();
  var out = document.getElementById('pxh-out');
  if(!H || H.c.length < 2){ out.innerHTML = '<p class="stale">每日收盤不足，無法健診。</p>'; return; }
  var C = H.c, D = H.d, N = C.length;
  var MA = {20: pxSMA(C, 20), 60: pxSMA(C, 60), 240: pxSMA(C, 240)};
  var $ = function(id){ return document.getElementById(id); };
  var inputs = {m1: $('pxh-m1'), p1: $('pxh-p1'), m2: $('pxh-m2'), p2: $('pxh-p2'), d3: $('pxh-d3')};
  var PRESETS = {short: [1, 10, 1, 10, 20], mid: [3, 20, 3, 20, 60]};
  var r0 = $('pxh-r0'), r1 = $('pxh-r1');
  var view = [0, N - 1], score = [];

  function params(){
    function v(k, d){ var x = parseFloat(inputs[k].value); return isNaN(x) || x <= 0 ? d : x; }
    return {m1: v('m1', 3), p1: v('p1', 20), m2: v('m2', 3), p2: v('p2', 20), d3: Math.round(v('d3', 60))};
  }
  function run(){
    var P = params();
    score = new Array(N);
    for(var i = 0; i < N; i++){
      var rs = pxChecks(C, MA, i, P);
      score[i] = rs.some(function(r){ return r.ok === null; }) ? null
        : rs.filter(function(r){ return r.ok; }).length;
    }
    var last = N - 1, rows = pxChecks(C, MA, last, P);
    var s = score[last];
    var h = '<div class="pxh-sum"><b>' + D[last] + '</b>' +
      '<span>收盤價 <b>' + C[last].toLocaleString() + '</b></span>' +
      ['20', '60', '240'].map(function(k){
        var v = MA[k][last], nm = {20: '月線', 60: '季線', 240: '年線'}[k];
        return '<span>' + nm + '(' + k + 'MA) <b>' + (v === null ? '—' : v.toFixed(2)) + '</b></span>';
      }).join('') +
      '<span>股價健診總評分 <b>' + (s === null ? rows.filter(function(r){ return r.ok; }).length + '（部分項目資料不足）' : s) + '</b></span></div>' +
      '<div class="scroll"><table class="hl-t"><thead><tr><th>健診項目</th><th class="st">狀態</th><th>說明</th></tr></thead><tbody>' +
      rows.map(function(r){
        return '<tr><td>' + r.label + '</td><td class="st">' +
          (r.ok === null ? '<span class="hl-na">— 資料不足</span>' : r.ok ? '<span class="hl-ok">✅ 正常</span>' : '<span class="hl-hit">⚠️ 警示</span>') +
          '</td><td>' + r.text + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="note-s">註：每個項目「警示」代表偏弱訊號；越多警示代表股價越弱。</p>';
    out.innerHTML = h;
    charts();
  }

  function charts(){
    var rng = [view[0], view[1]];
    TWSIXChart($('pxh-c1'), {x: D, range: rng, series: [
      {name: '收盤價', color: 'ink', values: C, width: 1.5},
      {name: '月線(20MA)', color: '#2563eb', values: MA[20], width: 1.2},
      {name: '季線(60MA)', color: '#ea7c0c', values: MA[60], width: 1.2},
      {name: '年線(240MA)', color: '#dc2626', values: MA[240], width: 1.2}
    ]});

    var f0 = pxFirstValid(score);
    var rng2 = (f0 >= 0 && f0 > rng[0] && f0 < rng[1]) ? [f0, rng[1]] : rng;
    TWSIXChart($('pxh-c2'), {x: D, range: rng2, yMin: 0, yMax: 6, height: 200,
      fmt: function(v){ return v === null || v === undefined ? '資料不足' : String(v); },
      series: [{name: '總評分', color: '#e0582a', values: score, step: true, width: 1.6,
        area: [[0, '#ef4444', .32], [.5, '#f59e0b', .22], [1, '#10b981', .28]]}]});
    $('pxh-span').textContent = D[view[0]] + ' ～ ' + D[view[1]] + '（' + (view[1] - view[0] + 1) + ' 個交易日）' +
      (f0 > view[0] ? '；總評分從 ' + D[f0] + ' 起才有（年線要累積 240 個交易日，之前的評分算不出來）' : '');
  }

  function setView(a, b){
    view = [Math.max(0, Math.min(a, b)), Math.min(N - 1, Math.max(a, b))];
    r0.value = view[0]; r1.value = view[1];
    charts();
  }
  r0.max = r1.max = N - 1; r0.value = 0; r1.value = N - 1;
  r0.addEventListener('input', function(){ setView(+r0.value, +r1.value); });
  r1.addEventListener('input', function(){ setView(+r0.value, +r1.value); });
  [].forEach.call(root.querySelectorAll('[data-zoom]'), function(b){
    b.addEventListener('click', function(){
      [].forEach.call(root.querySelectorAll('[data-zoom]'), function(x){ x.classList.toggle('on', x === b); });
      var n = +b.getAttribute('data-zoom');
      setView(n ? N - n : 0, N - 1);
    });
  });
  function preset(k){
    var v = PRESETS[k];
    inputs.m1.value = v[0]; inputs.p1.value = v[1]; inputs.m2.value = v[2]; inputs.p2.value = v[3]; inputs.d3.value = v[4];
    run();
  }
  $('pxh-run').addEventListener('click', run);
  $('pxh-short').addEventListener('click', function(){ preset('short'); });
  $('pxh-mid').addEventListener('click', function(){ preset('mid'); });
  Object.keys(inputs).forEach(function(k){
    inputs[k].addEventListener('keydown', function(e){ if(e.key === 'Enter') run(); });
  });

  var tab = document.getElementById('tab-pxhealth');
  var drawn = false;
  function first(){ if(drawn || root.offsetWidth === 0) return; drawn = true; run(); }
  if(tab) tab.addEventListener('click', function(){ setTimeout(first, 0); });

  if(typeof ResizeObserver !== 'undefined'){
    new ResizeObserver(function(){ first(); }).observe(root);
  }
  setTimeout(first, 0);
})();

function pxFirstValid(a){
  for(var i = 0; i < a.length; i++){ if(a[i] !== null && a[i] !== undefined) return i; }
  return -1;
}

function y3Eps(rev, sh, g, m){
  var eps = [], r = rev;
  for(var y = 0; y < 3; y++){ r = r * (1 + g[y] / 100); eps.push(r * (m[y] / 100) / (sh * 100)); }
  return eps;
}

(function(){
  var box = document.getElementById('y3');
  if(!box) return;
  var seed = {};
  try{ seed = JSON.parse(box.getAttribute('data-seed') || '{}'); }catch(e){ return; }
  var $ = function(id){ return document.getElementById(id); };
  var el = {rev: $('y3-rev'), sh: $('y3-sh'), g: $('y3-g'), m: $('y3-m'), pe: $('y3-pe'), out: $('y3-out')};
  var H = pxHistory();
  var price = parseFloat(box.getAttribute('data-price'));
  if(!isFinite(price) || price <= 0) price = null;
  var priceDate = box.getAttribute('data-price-date') || '';

  function nums(t){
    return String(t || '').split(/[,，\s]+/).map(parseFloat).filter(function(v){ return !isNaN(v); });
  }
  function three(list, d){
    var a = list.slice(0, 3);
    while(a.length < 3) a.push(a.length ? a[a.length - 1] : d);
    return a;
  }
  function defaults(){
    var g = seed.growth === null || seed.growth === undefined ? 10 : seed.growth;
    var m = seed.margin === null || seed.margin === undefined ? 10 : seed.margin;
    el.rev.value = Math.round(seed.revenue);
    el.sh.value = Math.round(seed.shares * 100) / 100;
    el.g.value = [g, g, g].join(', ');
    el.m.value = [m, m, m].join(', ');
    el.pe.value = (seed.pe || [15, 20, 25]).join(', ');
  }
  function money(v){ return Math.round(v).toLocaleString(); }
  function signCls(v){ return v > 0 ? 'up' : (v < 0 ? 'down' : ''); }

  function run(){
    var rev = parseFloat(el.rev.value), sh = parseFloat(el.sh.value);
    if(isNaN(rev) || isNaN(sh) || !sh){
      el.out.innerHTML = '<p class="stale">年營收與股數都要填，而且股數不能是 0。</p>'; return;
    }
    var g = three(nums(el.g.value), 0), m = three(nums(el.m.value), 10);
    var pes = nums(el.pe.value).sort(function(a, b){ return a - b; });
    if(!pes.length) pes = [15, 20, 25];
    var eps = y3Eps(rev, sh, g, m);
    var all = [];
    pes.forEach(function(pe){ eps.forEach(function(e){ all.push(e * pe); }); });
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);

    var fams = ['a', 'b', 'c'];
    var step9 = function(v){ return hi > lo ? Math.round((v - lo) / (hi - lo) * 4) : 2; };
    var eLo = Math.min.apply(null, eps), eHi = Math.max.apply(null, eps);
    var stepE = function(v){ return eHi > eLo ? Math.round((v - eLo) / (eHi - eLo) * 4) : 2; };
    function delta(v){
      if(!price || !v) return null;
      var up = v / price - 1, txt = (up >= 0 ? '+' : '−') + (Math.abs(up) * 100).toFixed(1) + '%';
      return {text: txt, title: (up >= 0 ? '預期報酬 ' : '預期風險 ') + txt + '（相對現價 ' + price.toFixed(2) + '）'};
    }
    var base = seed.base_year || new Date().getFullYear() - 1;
    var names = ['今年（' + (base + 1) + '）', '明年（' + (base + 2) + '）', '後年（' + (base + 3) + '）'];
    var sw = function(f){ return '<span class="sw" style="background:var(--m' + f + '3)"></span>'; };
    var h = '<h5 class="mtitle mt0 y3-h">預估未來三年 EPS 與目標價</h5>' +
      '<p class="mlegend"><b>顏色</b>　數值由小到大、由淺至深　目標價：' +
      pes.slice(0, 3).map(function(pe, k){ return sw(fams[k]) + '<span>PE ' + pe + '</span>'; }).join('　') +
      '<span>（九格一起比，' + money(lo) + ' → ' + money(hi) + '）</span>' +
      (price ? '<span>　每格第二行是相對現價 ' + price.toFixed(2) + (priceDate ? '（' + priceDate + ' 收盤）' : '') +
               ' 的預期報酬（＋）或預期風險（−）</span>' : '') + '</p>' +
      '<div class="scroll mwrap mt0"><table class="matrix mt0 y3-t"><thead><tr><th>項目</th>' +
      names.map(function(n){ return '<th class="num">' + n + '</th>'; }).join('') + '</tr></thead><tbody>' +
      '<tr class="in"><th scope="row">營收成長率</th>' + g.map(function(v){ return '<td class="' + signCls(v) + '"><span class="v">' + (v > 0 ? '▲ ' : v < 0 ? '▼ ' : '') + Math.abs(v).toFixed(2) + '%</span></td>'; }).join('') + '</tr>' +
      '<tr class="in"><th scope="row">淨利率（歸母）</th>' + m.map(function(v){ return '<td class="' + signCls(v) + '"><span class="v">' + v.toFixed(2) + '%</span></td>'; }).join('') + '</tr>' +
      '<tr class="eps"><th scope="row">預估 EPS（元）</th>' + eps.map(function(v){ return '<td class="num mn' + stepE(v) + '"><span class="v">' + v.toFixed(2) + '</span></td>'; }).join('') + '</tr>' +
      pes.map(function(pe, k){
        return '<tr class="tp rt' + (k % 3 + 1) + '"><th scope="row">預估目標價<br>PE＝' + pe + '</th>' + eps.map(function(e){
          var v = e * pe, d = delta(v);
          return '<td class="num m' + fams[k % 3] + step9(v) + '"' + (d ? ' title="' + d.title + '"' : '') + '>' +
            '<span class="v">' + money(v) + '</span>' + (d ? '<span class="d">' + d.text + '</span>' : '') + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>' +
      '<p class="note-s">營收成長率：<span class="up">紅 ▲ 成長</span>、<span class="down">綠 ▼ 衰退</span>。' +
      '淨利率（歸母）＝ 歸屬母公司稅後淨利 ÷ 營收。</p>';

    var tones = [1, 2, 3].map(function(k){
      var c = ''; try{ c = getComputedStyle(box).getPropertyValue('--t' + k).trim(); }catch(e){}
      return c || ['#23619f', '#1f7a55', '#b8610d'][k - 1];
    });
    var charts = [];
    if(H && H.c.length > 1){
      var start = Math.max(0, H.c.length - 500);
      names.forEach(function(n, y){
        var id = 'y3-c' + y;
        h += '<h5 class="y3-h">股價走勢 vs ' + n.replace(/（.*/, '') + '目標價</h5><div class="pxc" id="' + id + '"></div>';
        charts.push([id, y]);
      });
    }
    el.out.innerHTML = h;
    var labels = ['保守', '中性', '樂觀'];
    charts.forEach(function(c){
      var y = c[1];
      TWSIXChart($(c[0]), {x: H.d, range: [Math.max(0, H.c.length - 500), H.c.length - 1],
        title: (box.getAttribute('data-code') || '') + ' ' + names[y].replace(/（.*/, '') + '：股價走勢 vs 目標價',
        series: [{name: '收盤價', color: 'ink', values: H.c, width: 1.4}],
        hlines: pes.map(function(pe, k){
          var v = eps[y] * pe;
          return {value: v, color: tones[k % 3],
                  label: (pes.length === 3 ? labels[k] : '') + '(PE=' + pe + ') ' + money(v)};
        })});
    });
  }
  $('y3-run').addEventListener('click', run);
  $('y3-reset').addEventListener('click', function(){ defaults(); run(); });
  [el.rev, el.sh, el.g, el.m, el.pe].forEach(function(i){
    i.addEventListener('keydown', function(e){ if(e.key === 'Enter') run(); });
    i.addEventListener('change', run);
  });
  defaults();

  function first(){ if(box.offsetWidth === 0 || box._drawn) return; box._drawn = true; run(); }
  var tab = document.getElementById('tab-eps');
  if(tab) tab.addEventListener('click', function(){ setTimeout(first, 0); });
  if(typeof ResizeObserver !== 'undefined'){
    new ResizeObserver(function(){ first(); }).observe(box);
  }
  setTimeout(first, 0);
})();

(function(){
  var el = document.getElementById('ai-charts');
  if(!el || typeof TWSIXChart === 'undefined') return;
  var C;
  try{ C = JSON.parse(el.textContent); }catch(e){ return; }
  function pct(v){ return v === null || v === undefined ? '—' : ((v - 1) * 100).toFixed(1) + '%'; }
  function box(id){ return document.getElementById(id); }
  function safe(fn){ try{ fn(); }catch(e){ if(window.console) console.warn('AI 選股圖表', e); } }
  function xt(W){ return W < 440 ? 3 : 0; }

  function whenShown(el, fn){
    function shown(){ return el.getClientRects().length > 0; }
    if(shown()){ fn(); return; }
    var done = false, obs = null;
    function check(){
      if(done || !shown()) return;
      done = true;
      if(obs) obs.disconnect();
      fn();
    }
    if(window.MutationObserver) obs = new MutationObserver(check);
    for(var p = el.parentElement; p; p = p.parentElement){
      if(obs && p.getAttribute('role') === 'tabpanel')
        obs.observe(p, {attributes: true, attributeFilter: ['hidden']});
      if(p.tagName === 'DETAILS') p.addEventListener('toggle', check);
    }
  }
  var bEl = box('ai-breadth-chart'), b = C.breadth || {};
  if(bEl && (b.dates || []).length > 1) whenShown(bEl, function(){ safe(function(){
    TWSIXChart(bEl, {x: b.dates, xTicks: xt, height: 200,
      title: '市場寬度（站上 60 日線的比例，近一年）',
      fmt: function(v){ return v === null || v === undefined ? '—' : v.toFixed(0) + '%'; },
      hlines: [{value: 50, color: '#cf3327', label: '50% 擴張'}, {value: 20, color: '#0d7c4f', label: '20% 恐慌'}],
      series: [{name: '市場寬度', color: '#1c62b8', values: b.values, width: 1.6}]});
  }); });
  var pEl = box('ai-paper-chart'), pp = C.port || {};
  if(pEl && (pp.x || []).length > 1) whenShown(pEl, function(){ safe(function(){
    TWSIXChart(pEl, {x: pp.x, xTicks: xt, height: 220,
      series: [{name: '影子帳戶', color: '#c2255c', values: pp.equity, width: 2},
               {name: '0050', color: 'ink', values: pp.bench, width: 1.2, dash: '4 3'}]});
  }); });

  (C.list || []).forEach(function(ch){
    var el2 = box(ch.id);
    if(!el2 || (ch.x || []).length < 2) return;
    whenShown(el2, function(){ safe(function(){
      TWSIXChart(el2, {x: ch.x, fmt: pct, xTicks: xt, title: ch.title,
        series: ch.series.map(function(s){
          return {name: s.name, color: s.color, values: s.values, width: s.width || 1.4, dash: s.dash};
        })});
    }); });
  });
})();

function reveal(bar, el){
  var b = bar.getBoundingClientRect(), e = el.getBoundingClientRect();
  if(e.left < b.left) bar.scrollLeft -= (b.left - e.left) + 8;
  else if(e.right > b.right) bar.scrollLeft += (e.right - b.right) + 8;
}
(function(){
  var bar = document.querySelector('.ai-tabs');
  if(!bar) return;
  var tabs = [].slice.call(bar.querySelectorAll('[role=tab]'));
  function key(t){ return t.id.replace(/^aitab-/, ''); }
  function show(name, push, scroll){
    tabs.forEach(function(t){
      var on = key(t) === name;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(t.getAttribute('aria-controls'));
      if(panel) panel.hidden = !on;
    });
    if(push && history.replaceState) history.replaceState(null, '', '#' + name);

    var cur = document.getElementById('aitab-' + name);
    if(cur) reveal(bar, cur);

    if(scroll && bar.getBoundingClientRect().top < 0)
      window.scrollTo({top: window.pageYOffset + bar.getBoundingClientRect().top - 8, behavior: 'auto'});
  }
  tabs.forEach(function(t){
    t.addEventListener('click', function(){ show(key(t), true, true); t.focus(); });
    t.addEventListener('keydown', function(e){
      var i = tabs.indexOf(t), n = tabs.length, j = null;
      if(e.key === 'ArrowRight') j = (i + 1) % n;
      else if(e.key === 'ArrowLeft') j = (i + n - 1) % n;
      else if(e.key === 'Home') j = 0;
      else if(e.key === 'End') j = n - 1;
      if(j === null) return;
      e.preventDefault();
      tabs[j].focus(); show(key(tabs[j]), true, true);
    });
  });
  var want = (location.hash || '').slice(1).replace(/^ai-/, '');
  if(want === 'picks') want = 'a';
  if(want && document.getElementById('aitab-' + want)) show(want, false, false);
})();

(function(){
  var panel = document.getElementById('panel-ai');
  if(!panel) return;
  var box = panel.querySelector('.ai-stock');
  var loaded = false;
  function esc(s){
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function pct(v, d){ return v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + (v * 100).toFixed(d === undefined ? 1 : d) + '%'; }
  function tone(v){ return v > 0 ? 'up' : (v < 0 ? 'down' : ''); }
  var stockHref = function(code){ return esc(code) + '.html'; };
  function card(tag, cls, title, body){
    return '<div class="ai-card"><h4><span class="ai-tag ' + cls + '">' + tag + '</span>' + title + '</h4>' + body + '</div>';
  }
  function render(d){
    var S = d.strategy_text || {};
    var F = d.feature_text || {};
    var out = [];
    var chips = [];
    if(d.held) chips.push('<span class="ai-chip ai-chip-held">影子帳戶持有中：' + esc(S[d.held.strategy] || d.held.strategy) +
      '，' + esc(d.held.entry_date) + ' 以 ' + esc(d.held.entry_price) + ' 進場</span>');
    (d.candidate || []).forEach(function(k){ chips.push('<span class="ai-s ai-s-' + esc(k) + '">本期候選：' + esc(S[k] || k) + '</span>'); });
    if(d.e && d.e.veto) chips.push('<span class="ai-chip ai-chip-veto">財報品質否決（' + esc(d.e.score) + ' 面紅旗）</span>');
    out.push('<p class="muted">資料日 ' + esc(d.asof) + '。' + (chips.length ? '' : '這一檔目前不在任何一套的候選名單上。') + '</p>');
    if(chips.length) out.push('<p class="ai-chips">' + chips.join(' ') + '</p>');

    var e = d.e;
    out.push(card('E', 'ai-tag-e', '財報品質',
      e ? ('<p>' + esc(e.quarter) + ' 財報：紅旗 <b class="' + (e.veto ? 'down' : '') + '">' + esc(e.score) + '</b> 面' +
           (e.veto ? '（三面以上，<b>否決</b>）' : '（三面以上才否決）') + '</p>' +
           (e.details && e.details.length ? '<ul class="ai-list">' + e.details.map(function(x){ return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<p class="muted">沒有紅旗。</p>'))
        : '<p class="muted">沒有看得到的財報。</p>'));

    var a = d.a;
    if(a && a.history && a.history.length){
      var rows = a.history.slice().reverse().map(function(h){
        return '<tr><td>' + esc(h.month) + '</td><td class="num ' + tone(h.sue) + '">' + (h.sue > 0 ? '+' : '') + h.sue.toFixed(1) +
          '</td><td class="num ' + tone(h.yoy) + '">' + pct(h.yoy, 0) + '</td></tr>';
      }).join('');
      out.push(card('A', 'ai-tag-a', '營收驚喜',
        '<p>' + (a.pct !== null && a.pct !== undefined ? esc(a.month) + ' 營收 SUE 位於全市場第 <b>' + Math.round(a.pct * 100) + '</b> 百分位（前 10% 才可能成為候選）。' : '最近一個月沒有評分。') +
        '<span class="muted">SUE ＝ 比「去年同月 × 最近成長速度」多出來的部分，除以這家公司自己的預測誤差。</span></p>' +
        '<div class="scroll"><table class="ai-t"><thead><tr><th>月份</th><th class="num">SUE</th><th class="num">年增</th></tr></thead><tbody>' + rows + '</tbody></table></div>'));
    }

    var b = d.b;
    if(b && b.neighbors && b.neighbors.length){
      out.push(card('B', 'ai-tag-bb', '供應鏈連動：股價一起動的公司',
        '<p class="muted">扣掉大盤之後，過去兩年週報酬相關最高的幾家（連動圖建於 ' + esc(b.graph_day) + '）。關係說明是 LLM 註解，只供參考。</p><ul class="ai-list">' +
        b.neighbors.map(function(n){
          return '<li><a href="' + stockHref(n.code) + '">' + esc(n.code) + ' ' + esc(n.name) + '</a> <span class="muted">相關 ' +
            (n.corr === null || n.corr === undefined ? '—' : n.corr.toFixed(2)) + '</span>' +
            (n.relation ? '　<b>' + esc(n.relation) + '</b>' + (n.note ? '：' + esc(n.note) : '') +
              (n.confidence !== null && n.confidence !== undefined ? ' <span class="muted">（信心 ' + Math.round(n.confidence * 100) + '%）</span>' : '') : '') + '</li>';
        }).join('') + '</ul>'));
    }

    var c = d.c;
    out.push(card('C', 'ai-tag-t', '法說轉折',
      c && c.length ? '<ul class="ai-list">' + c.map(function(t){
        var k = t.kind === '負轉折' ? 'down' : (t.kind === '正轉折' ? 'up' : 'muted');
        return '<li><b>' + esc(t.date) + '</b> <span class="' + k + '">' + esc(t.kind) + '（' + (t.score > 0 ? '+' : '') + t.score.toFixed(1) + '）</span>' +
          ' <span class="muted">' + (t.method === 'llm' ? 'LLM' : '規則') + (t.prev_date ? '，對比 ' + esc(t.prev_date) : '，第一次，沒有可比') + '</span>' +
          (t.why ? '<br><span class="ai-turnwhy ' + k + '">' + esc(t.why) + '</span>' : '') +
          (t.summary ? '<br>' + esc(t.summary) : (!t.why && t.note ? '<br><span class="muted">公司公告：</span>' + esc(t.note) : '')) +
          (t.highlights && t.highlights.length ? '<br><span class="muted">重點：</span>' + t.highlights.map(esc).join('；') : '') +
          (t.risks && t.risks.length ? '<br><span class="muted">風險：</span>' + t.risks.map(esc).join('；') : '') + '</li>';
      }).join('') + '</ul>' : '<p class="muted">還沒有讀過這一檔的法說簡報（從上線那天起累積，持股與候選優先）。</p>'));

    var dd = d.d;
    if(dd){
      var fs = Object.keys(dd.features || {}).map(function(k){
        var v = dd.features[k];
        if(v === null || v === undefined) return '';
        var txt = k === 'big4z' ? (v > 0 ? '+' : '') + v.toFixed(1) + ' σ' : pct(v, 2);
        return '<li><span>' + esc(F[k] || k) + '</span><b class="' + tone(v) + '">' + txt + '</b></li>';
      }).join('');
      out.push(card('D', 'ai-tag-d', '籌碼共振',
        '<p>集保 ' + esc(dd.week) + '：共振分數第 <b>' + Math.round(dd.pct * 100) + '</b> 百分位（前 5% 且股價還沒動才是候選）。</p>' +
        (fs ? '<ul class="ai-ic">' + fs + '</ul>' : '')));
    }
    out.push('<p class="muted">市場狀態（F）、影子帳戶與回測見 <a href="' + esc(panel.getAttribute('data-ai-page')) + '">AI 選股</a> 頁。這不是投資建議。</p>');
    box.innerHTML = out.join('');
  }
  function load(){
    if(loaded) return;
    loaded = true;
    var src = panel.getAttribute('data-src');
    if(!window.fetch){ box.innerHTML = '<p class="stale">這個瀏覽器不支援讀取 AI 資料。</p>'; return; }
    fetch(src, {cache: 'no-cache'}).then(function(r){
      if(!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function(d){
      try{ render(d); }catch(err){ box.innerHTML = '<p class="stale">AI 資料的格式看不懂，這一個分頁暫時無法顯示。</p>'; }
    }).catch(function(){
      box.innerHTML = '<p class="muted">還沒有這一檔的 AI 資料（每天的排程跑完之後才會有；已下市或太新的股票不會有）。</p>';
    });
  }

  if(window.MutationObserver){
    new MutationObserver(function(){ if(!panel.hidden) load(); })
      .observe(panel, {attributes: true, attributeFilter: ['hidden']});
  }
  var tab = document.getElementById('tab-ai');
  if(tab) tab.addEventListener('click', load);
  if(!panel.hidden) load();
})();

(function(){
  var bars = document.querySelectorAll('.rng[data-rng]');
  if(!bars.length) return;
  var code = (location.pathname.split('/').pop() || '').replace(/\.html?$/, '');
  var cache = null;
  function load(){
    if(!cache){
      cache = window.TWSIXgz(code + '.r.json', {cache: 'no-cache'});
      cache.catch(function(){ cache = null; });
    }
    return cache;
  }
  Array.prototype.forEach.call(bars, function(bar){
    var fig = bar.getAttribute('data-rng');
    var boxes = document.querySelectorAll('.rng-fig[data-rng-fig="' + fig + '"]');
    var first = bar.querySelector('button.on');
    var def = first ? first.getAttribute('data-r') : '';
    var orig = [].map.call(boxes, function(b){ return b.innerHTML; });
    function mark(r){
      [].forEach.call(bar.querySelectorAll('button'), function(b){
        var on = b.getAttribute('data-r') === r;
        b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    function put(r, data){
      [].forEach.call(boxes, function(b, i){
        if(r === def){ b.innerHTML = orig[i]; }
        else{
          var v = data && data[fig] && data[fig][r];
          var part = b.getAttribute('data-part');
          var svg = part ? (v && v[part]) : v;
          if(!svg) return;
          b.innerHTML = svg;
        }
        if(window.TWSIXHover) window.TWSIXHover(b);
      });
      mark(r);
    }
    bar.addEventListener('click', function(e){
      var btn = e.target.closest ? e.target.closest('button[data-r]') : null;
      if(!btn || btn.classList.contains('on')) return;
      var r = btn.getAttribute('data-r');
      if(r === def){ put(r, null); return; }
      bar.classList.add('busy');
      load().then(function(d){ put(r, d); }, function(){
        btn.title = '這一段的圖還沒產生（下一次建站後就有）';
      }).then(function(){ bar.classList.remove('busy'); });
    });
  });
})();

(function(){
  var NS = 'http://www.w3.org/2000/svg';
  function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function fmt(v, d){ return Number(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}); }
  var open = [];

  function wire(svg){
    if(svg._hover) return;
    svg._hover = true;
    var o;
    try{ o = JSON.parse(svg.getAttribute('data-hover')); }catch(e){ return; }
    var n = o.x.length;
    if(!n || !svg.viewBox || !svg.viewBox.baseVal) return;
    var W = svg.viewBox.baseVal.width, slot = o.w / n;
    var wrap = document.createElement('div');
    wrap.className = 'chart-hover';
    svg.parentNode.insertBefore(wrap, svg);
    wrap.appendChild(svg);
    var cross = document.createElementNS(NS, 'line');
    cross.setAttribute('y1', o.t); cross.setAttribute('y2', o.t + o.h);
    cross.setAttribute('stroke', 'var(--muted)'); cross.setAttribute('stroke-dasharray', '3 3');
    cross.setAttribute('pointer-events', 'none'); cross.setAttribute('visibility', 'hidden');
    svg.appendChild(cross);
    var tip = document.createElement('div');
    tip.className = 'pxtip'; tip.hidden = true;
    wrap.appendChild(tip);
    function show(clientX, clientY){
      var r = svg.getBoundingClientRect();
      if(!r.width) return;
      var x = (clientX - r.left) * W / r.width;
      var i = Math.max(0, Math.min(n - 1, Math.floor((x - o.l) / slot)));
      var X = o.l + slot * (i + 0.5);
      cross.setAttribute('x1', X); cross.setAttribute('x2', X);
      cross.setAttribute('visibility', 'visible');
      var h = '<b>' + esc(o.x[i]) + '</b>', any = false;
      o.s.forEach(function(s){
        var v = s[4][i];
        if(v === null || v === undefined) return;
        any = true;
        h += '<span><i style="background:' + esc(s[1]) + '"></i>' + esc(s[0]) +
             '<em>' + fmt(v, s[3]) + esc(s[2] || '') + '</em></span>';
      });
      if(!any) h += '<span>這一期沒有資料</span>';
      tip.innerHTML = h; tip.hidden = false;
      var px = X * r.width / W, left = px + 12;
      if(left + tip.offsetWidth > r.width - 4) left = px - 12 - tip.offsetWidth;
      tip.style.left = Math.max(4, left) + 'px';

      var y = clientY - r.top, top = y - tip.offsetHeight - 14;
      if(top < 4) top = Math.min(y + 18, r.height - tip.offsetHeight - 4);
      tip.style.top = Math.max(4, top) + 'px';
      if(open.indexOf(hide) < 0) open.push(hide);
    }
    function hide(){ cross.setAttribute('visibility', 'hidden'); tip.hidden = true; }
    svg.addEventListener('mousemove', function(e){ show(e.clientX, e.clientY); });
    svg.addEventListener('mouseleave', hide);
    function touch(e){ var t = e.touches[0]; if(t) show(t.clientX, t.clientY); }
    svg.addEventListener('touchstart', touch, {passive: true});
    svg.addEventListener('touchmove', touch, {passive: true});
  }
  window.TWSIXHover = function(root){
    Array.prototype.forEach.call((root || document).querySelectorAll('svg.chart[data-hover]'), wire);
  };
  window.TWSIXHover(document);

  document.addEventListener('touchstart', function(e){
    if(e.target.closest && e.target.closest('.chart-hover')) return;
    open.forEach(function(f){ f(); }); open = [];
  }, {passive: true});
})();

(function(){
  var h = document.querySelector('header.top');
  if(!h) return;
  function set(){ document.documentElement.style.setProperty('--head-h', h.offsetHeight + 'px'); }
  set();
  if(window.ResizeObserver) new ResizeObserver(set).observe(h);
  else window.addEventListener('resize', set);
})();

(function(){
  var host = document.getElementById('wg');
  if(!host || typeof TWSIXWatch === 'undefined') return;
  var open = false, dragId = null, lastCur = null;
  function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function mini(act, label, txt, dis, extra){
    return '<button type="button" class="wg-mini' + (extra || '') + '" data-act="' + act + '" title="' + label + '" aria-label="' + label + '"' +
      (dis ? ' disabled' : '') + '>' + txt + '</button>';
  }
  function menu(gs, cur){
    var real = gs.filter(function(g){ return !g.virtual; }), last = real.length - 1;
    var nHid = real.filter(function(g){ return g.hidden; }).length;
    var h = '<div class="wg-menu" role="dialog" aria-label="管理群組">' +
      '<div class="wg-mh"><div class="wg-mt"><b>管理群組</b><span class="wg-bulk">' +
      '<button type="button" class="wg-mini wg-eye" data-act="hideall" title="把所有群組藏起來（只剩總交集）"' +
        (nHid === real.length ? ' disabled' : '') + '>全部隱藏</button>' +
      '<button type="button" class="wg-mini wg-eye" data-act="showall" title="把所有隱藏的群組放回分頁列"' +
        (nHid ? '' : ' disabled') + '>全部顯示</button></span></div>' +
      '<span>拖曳或 ▲▼ 排序・隱藏的不在分頁列、也不算進總交集</span></div><ul class="wg-rows">';
    real.forEach(function(g, i){
      var nm = esc(g.name);
      h += '<li class="wg-row wg-dr' + (g.hidden ? ' wg-hid' : '') + (g.id === cur ? ' on' : '') + '" data-id="' + esc(g.id) + '" draggable="true">' +
        '<span class="wg-grip" aria-hidden="true">⠿</span>' +
        '<span class="wg-dot wg-c' + (gs.indexOf(g) % 8) + '" aria-hidden="true"></span>' +
        '<button type="button" class="wg-rname" data-act="pick" title="切換到這個群組">' + nm + ' <span class="wg-n">' + g.n + '</span></button>' +
        '<span class="wg-ops">' +
        mini('up', '把 ' + nm + ' 往前移', '▲', i === 0) +
        mini('down', '把 ' + nm + ' 往後移', '▼', i === last) +
        mini('rename', '把 ' + nm + ' 改名', '✎') +
        mini('hide', (g.hidden ? '顯示 ' : '隱藏 ') + nm, g.hidden ? '顯示' : '隱藏', false, ' wg-eye" aria-pressed="' + !!g.hidden) +
        mini('del', '刪除 ' + nm, '✕', real.length < 2) +
        '</span></li>';
    });
    return h + '</ul><div class="wg-mf">' +
      '<button type="button" class="wg-tool" data-act="add">＋ 新增群組</button>' +
      '<button type="button" class="wg-tool wg-done" data-act="close">完成</button></div></div>';
  }
  function render(){
    var gs = TWSIXWatch.groups(), cur = TWSIXWatch.current().id;

    var old = host.querySelector('.wg-tabs'), keep = old ? old.scrollLeft : 0;
    var oldRows = host.querySelector('.wg-rows'), keepY = oldRows ? oldRows.scrollTop : 0;
    var h = '<div class="wg-bar"><div class="wg-tabs" role="tablist" aria-label="觀察清單群組">', nHid = 0;
    gs.forEach(function(g, i){
      var on = g.id === cur;
      if(g.hidden){ nHid++; if(!on) return; }
      if(g.virtual){
        h += '<span class="wg-item wg-allitem" data-id="' + esc(g.id) + '">' +
          '<button type="button" role="tab" class="wg-tab wg-all" aria-selected="' + on + '" data-act="pick" ' +
          'title="所有（非空、未隱藏的）群組都有的股票，自動算出">' + esc(g.name) + ' <span class="wg-n">' + g.n + '</span></button></span>';
        return;
      }
      h += '<span class="wg-item wg-dr' + (g.hidden ? ' wg-hid' : '') + '" data-id="' + esc(g.id) + '" draggable="true">' +
        '<button type="button" role="tab" class="wg-tab wg-c' + (i % 8) + '" aria-selected="' + on + '" data-act="pick" title="' +
          (g.hidden ? '已隱藏：不在分頁列、不參與總交集' : '點兩下改名；拖曳排序') + '">' +
        esc(g.name) + ' <span class="wg-n">' + g.n + '</span></button></span>';
    });
    h += '</div><div class="wg-tools">' +
         '<button type="button" class="wg-tool" data-act="add" title="新增群組" aria-label="新增群組">＋<span class="wg-tl"> 新增</span></button>' +
         '<button type="button" class="wg-tool wg-mgr" data-act="edit" aria-haspopup="true" aria-expanded="' + open + '">管理' +
           (nHid ? '<span class="wg-tl">（隱藏 ' + nHid + '）</span>' : '') + ' ▾</button>' +
         (open ? menu(gs, cur) : '') + '</div></div>';
    host.innerHTML = h;
    var strip = host.querySelector('.wg-tabs');
    strip.scrollLeft = keep;
    var rows = host.querySelector('.wg-rows');
    if(rows) rows.scrollTop = keepY;

    if(lastCur === null){
      var sel = strip.querySelector('[aria-selected="true"]');
      if(sel){
        var a = sel.closest('.wg-item') || sel, L = a.offsetLeft - strip.offsetLeft, R = L + a.offsetWidth;
        if(L < strip.scrollLeft) strip.scrollLeft = Math.max(0, L - 24);
        else if(R > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = R - strip.clientWidth + 24;
      }
      lastCur = cur;
    }
    edges();
  }

  function edges(){
    var st = host.querySelector('.wg-tabs');
    if(!st) return;
    st.classList.toggle('more-l', st.scrollLeft > 2);
    st.classList.toggle('more-r', st.scrollLeft + st.clientWidth < st.scrollWidth - 2);
  }
  host.addEventListener('scroll', edges, true);
  window.addEventListener('resize', edges);
  function setOpen(v){
    if(open === v) return;
    open = v; render();
    if(open){ var f = host.querySelector('.wg-menu .wg-rname'); if(f) f.focus(); }
    else{ var m = host.querySelector('.wg-mgr'); if(m) m.focus(); }
  }
  function rename(id){
    var g = TWSIXWatch.groups().filter(function(x){ return x.id === id; })[0];
    if(!g) return;
    var name = window.prompt('群組名稱', g.name);
    if(name !== null) TWSIXWatch.renameGroup(id, name);
  }

  document.addEventListener('click', function(e){
    if(!open || !e.target.closest) return;
    if(e.target.closest('.wg-menu, .wg-mgr')) return;
    open = false; render();
  }, true);
  document.addEventListener('keydown', function(e){
    if(open && e.key === 'Escape') setOpen(false);
  });
  host.addEventListener('click', function(e){
    var b = e.target.closest('button[data-act]');
    if(!b || b.disabled) return;
    var item = b.closest('[data-id]'), id = item && item.getAttribute('data-id'), act = b.getAttribute('data-act');
    if(act === 'pick') TWSIXWatch.select(id);
    else if(act === 'add'){
      var name = window.prompt('新群組的名稱', '新群組');
      if(name !== null) TWSIXWatch.addGroup(name);
    }else if(act === 'edit') setOpen(!open);
    else if(act === 'close') setOpen(false);
    else if(act === 'rename') rename(id);
    else if(act === 'hideall') TWSIXWatch.hideAll(true);
    else if(act === 'showall') TWSIXWatch.hideAll(false);
    else if(act === 'hide') TWSIXWatch.hideGroup(id, b.getAttribute('aria-pressed') !== 'true');
    else if(act === 'del'){
      var g = TWSIXWatch.groups().filter(function(x){ return x.id === id; })[0];
      if(g && window.confirm('刪除群組〔' + g.name + '〕？' + (g.n ? '裡面的 ' + g.n + ' 檔會一起移除（其他群組不受影響）。' : '')))
        TWSIXWatch.removeGroup(id);
    }else if(act === 'up') TWSIXWatch.moveGroup(id, -1);
    else if(act === 'down') TWSIXWatch.moveGroup(id, +1);
  });
  host.addEventListener('dblclick', function(e){
    var b = e.target.closest('.wg-tabs button[data-act="pick"]');
    var it = b && b.closest('.wg-item');
    if(it && !it.classList.contains('wg-allitem')) rename(it.getAttribute('data-id'));
  });

  function vertical(el){ return el.classList.contains('wg-row'); }
  function firstHalf(el, e){
    var r = el.getBoundingClientRect();
    return vertical(el) ? e.clientY < r.top + r.height / 2 : e.clientX < r.left + r.width / 2;
  }
  host.addEventListener('dragstart', function(e){
    var it = e.target.closest && e.target.closest('.wg-dr');
    if(!it) return;
    dragId = it.getAttribute('data-id');
    it.classList.add('drag');
    try{ e.dataTransfer.setData('text/plain', dragId); e.dataTransfer.effectAllowed = 'move'; }catch(err){}
  });
  host.addEventListener('dragover', function(e){
    if(!dragId) return;
    var it = e.target.closest && e.target.closest('.wg-dr, .wg-allitem');
    if(!it) return;
    e.preventDefault();
    [].forEach.call(host.querySelectorAll('.to-l, .to-r'), function(x){ x.classList.remove('to-l', 'to-r'); });
    it.classList.add(firstHalf(it, e) ? 'to-l' : 'to-r');
  });
  host.addEventListener('drop', function(e){
    if(!dragId) return;
    e.preventDefault();
    var it = e.target.closest && e.target.closest('.wg-dr, .wg-allitem');
    if(it){
      var id = it.getAttribute('data-id'), before = id === '__all' ? null : id;
      if(id !== '__all' && !firstHalf(it, e)){

        var ids = TWSIXWatch.groups().filter(function(g){ return !g.virtual; }).map(function(g){ return g.id; });
        before = ids[ids.indexOf(id) + 1] || null;
      }
      TWSIXWatch.placeGroup(dragId, before);
    }
    dragId = null; render();
  });
  host.addEventListener('dragend', function(){ dragId = null; render(); });
  document.addEventListener('twsix:wgroup', render);
  window.addEventListener('pageshow', function(){ TWSIXWatch.reload(); render(); });
  render();
})();

(function(){
  var wrap = document.getElementById('wg-add'), q = document.getElementById('wg-add-q');
  var go = document.getElementById('wg-add-go'), dl = document.getElementById('wg-add-dl');
  var msg = document.getElementById('wg-add-msg'), table = document.getElementById('t');
  if(!wrap || !q || !table || typeof TWSIXWatch === 'undefined') return;
  var names = {}, html = [];
  [].forEach.call(table.tBodies[0].rows, function(tr){
    var c = tr.getAttribute('data-code'), nm = tr.querySelector('td.nm');
    var n = nm ? (nm.getAttribute('data-s') || nm.textContent).trim() : '';
    names[c] = n;
    html.push('<option value="' + c + ' ' + n.replace(/"/g, '&quot;') + '">');
  });
  dl.innerHTML = html.join('');
  wrap.hidden = false;
  function find(text){
    text = String(text || '').trim();
    if(!text) return null;
    var c = text.split(/\s+/)[0];
    if(names[c] !== undefined) return c;
    for(var k in names) if(names[k] === text) return k;
    var hit = Object.keys(names).filter(function(k){ return names[k].indexOf(text) >= 0; });
    return hit.length === 1 ? hit[0] : null;
  }
  function sync(){
    var v = TWSIXWatch.current().virtual;
    q.disabled = go.disabled = !!v;
    q.placeholder = v ? '總交集清單不能直接加，請到各群組' : '加入自選股：代號或名稱';
  }
  function add(){
    var c = find(q.value), cur = TWSIXWatch.current();
    if(cur.virtual) return;
    if(!c){ msg.textContent = '找不到「' + q.value.trim() + '」，請輸入代號或完整名稱'; return; }
    if(TWSIXWatch.has(c)){ msg.textContent = c + ' ' + names[c] + ' 已經在〔' + cur.name + '〕裡'; q.select(); return; }
    TWSIXWatch.setIn(cur.id, c, true);
    msg.textContent = '已加入 ' + c + ' ' + names[c] + ' →〔' + cur.name + '〕';
    q.value = '';
  }
  go.addEventListener('click', add);
  q.addEventListener('keydown', function(e){ if(e.key === 'Enter'){ e.preventDefault(); add(); } });
  q.addEventListener('input', function(){ msg.textContent = ''; });
  document.addEventListener('twsix:wgroup', sync);
  sync();
})();

window.TWSIXImport = window.TWSIXImport || {};
(function(){
  if(typeof TWSIXWatch === 'undefined') return;
  var toast = null, timer = null;
  function say(html){
    if(!toast){
      toast = document.createElement('div');
      toast.className = 'wg-toast'; toast.setAttribute('role', 'status');
      document.body.appendChild(toast);
    }
    toast.innerHTML = html; toast.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(function(){ toast.hidden = true; }, 6000);
  }
  function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  document.addEventListener('click', function(e){
    var b = e.target.closest && e.target.closest('button[data-wg-src]');
    if(!b) return;
    var src = b.getAttribute('data-wg-src'), name = b.getAttribute('data-wg-name') || src;
    var raw = b.getAttribute('data-wg-codes'), codes = [];
    if(raw !== null) codes = raw.split(',');
    else if(typeof window.TWSIXImport[src] === 'function'){
      try{ codes = window.TWSIXImport[src]() || []; }catch(err){ codes = []; }
    }
    codes = codes.map(function(c){ return String(c).trim(); }).filter(Boolean);
    if(!codes.length){ say('目前沒有符合條件的股票可以匯入——先篩出結果再按一次。'); return; }
    TWSIXWatch.reload();
    var old = TWSIXWatch.sourceGroup(src);
    function done(asName){
      var r = TWSIXWatch.importGroup(src, name, codes, asName);
      if(!r) return;
      var rel = (window.TWSIX && TWSIX.rel) || '';
      say('已把 <b>' + r.n + '</b> 檔匯入觀察清單〔' + esc(r.name) + '〕' +
          (r.replaced ? '（覆蓋原本的 ' + r.prev + ' 檔）' : r.copy ? '（新群組，原本的〔' + esc(old.name) + '〕沒動）' : old && old.n ? '（取代原本的 ' + old.n + ' 檔）' : '') +
          '　<a href="' + rel + 'watchlist.html">去看 →</a>');
    }
    if(old && old.n) ask(old, codes.length, done);
    else done();
  });

  var dlg = null;
  function ask(old, n, cb){
    if(typeof HTMLDialogElement === 'undefined'){
      var nm = window.prompt('觀察清單〔' + old.name + '〕已經有 ' + old.n + ' 檔。\n' +
        '・直接按確定＝覆蓋成這一次的 ' + n + ' 檔\n・改個名字再按確定＝另存成新群組', old.name);
      if(nm === null) return;
      nm = nm.trim();
      cb(!nm || nm === old.name ? undefined : nm);
      return;
    }
    if(!dlg){
      dlg = document.createElement('dialog');
      dlg.className = 'wg-dlg';
      dlg.innerHTML =
        '<form method="dialog">' +
        '<h3 class="wg-dlg-h"></h3><p class="wg-dlg-p"></p>' +
        '<label class="wg-dlg-l">另存新群組的名稱<input type="text" name="nm" maxlength="40" autocomplete="off"></label>' +
        '<p class="wg-dlg-warn" aria-live="polite"></p>' +
        '<div class="wg-dlg-b">' +
        '<button value="cancel" class="wg-dlg-x">取消</button>' +
        '<button value="copy" class="wg-dlg-copy">另存新群組</button>' +
        '<button value="over" class="wg-dlg-over">覆蓋</button>' +
        '</div></form>';
      document.body.appendChild(dlg);
    }
    var inp = dlg.querySelector('input'), warn = dlg.querySelector('.wg-dlg-warn'), bc = dlg.querySelector('.wg-dlg-copy');
    dlg.querySelector('.wg-dlg-h').textContent = '觀察清單〔' + old.name + '〕已經有 ' + old.n + ' 檔';
    dlg.querySelector('.wg-dlg-p').textContent = '這一次有 ' + n + ' 檔。要覆蓋原本的群組，還是另存成一個新群組？';
    dlg.querySelector('.wg-dlg-over').textContent = '覆蓋〔' + old.name + '〕';
    inp.value = old.name;
    function check(){
      var v = inp.value.trim(), taken = !!v && TWSIXWatch.nameTaken(v), self = v === old.name;
      warn.textContent = !v ? '請輸入名稱' : self ? '' :
        taken ? '已經有叫〔' + v + '〕的群組——按〔覆蓋〔' + v + '〕〕會用這一次的 ' + n + ' 檔換掉它的內容' : '';
      bc.disabled = !v;
      bc.hidden = self;
      bc.textContent = taken && !self ? '覆蓋〔' + v + '〕' : '另存新群組';
      warn.classList.toggle('wg-dlg-info', taken && !self);
    }
    inp.oninput = check; check();
    inp.onkeydown = function(e){
      if(e.key === 'Enter'){ e.preventDefault(); if(!bc.disabled) dlg.close(bc.hidden ? 'over' : 'copy'); }
    };
    dlg.onclose = function(){
      var v = dlg.returnValue; dlg.onclose = null;
      if(v === 'over') cb();
      else if(v === 'copy') cb(inp.value.trim());
    };
    dlg.returnValue = 'cancel';
    dlg.showModal();
    inp.focus();
    var L = inp.value.length; try{ inp.setSelectionRange(L, L); }catch(e){}
  }
})();
