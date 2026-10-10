/* 全站共用的腳本。抽出的理由同 site.css。
   兩個原本由 Jinja 填的值（rel、repo）改由每頁一行的 window.TWSIX 帶進來——
   那一行 60 個位元組，換掉 20 KB 的複本。 */
/* 全站個股搜尋。
 *
 * search.json 是 [代號, 名稱, 產業, 綜合評分, 完整頁的更新日期, 抓取時間戳] 的陣列，順序固定，
 * 只有這裡讀它。索引是延後載入的：訪客多半只是看清單頁，不該為了一個可能
 * 不會用到的搜尋框先付 85 KB。第一次聚焦才抓，抓過就留著。
 *
 * 排序刻意分三段而不是算一個相似度分數：使用者打「23」時要的是 2330 那一類，
 * 不是名字裡有 23 的公司。代號開頭 > 名稱 > 代號中間 > 產業，段內照代號排。
 */
(function(){
  var box=document.getElementById('find'); if(!box) return;
  var list=document.getElementById('find-list');
  var data=null, hits=[], cur=-1, base=TWSIX.rel;

  function load(){
    if(data) return Promise.resolve(data);
    /* 掛上這一次建站的編號。GitHub Pages 給 JSON 的是 max-age=600，所以不掛的
       話，剛重建完的十分鐘內瀏覽器會拿自己快取裡的舊索引——而那份索引正是「這
       一檔幾點抓的」的來源。它一舊，「已經是最新的就別抓」就擋不住。 */
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
      /* 第七欄：已下市。清單上不會有這一列，但搜尋仍然找得到——所以這裡必須先
         說一聲，否則點進去才發現，會讀成「這個網站的資料是錯的」。 */
      if(r[6]){
        var dl=document.createElement('span');
        dl.className='tag gone'; dl.textContent='已下市';
        dl.title='已不在證交所／櫃買的公司名單上，評等停在下市前那一期';
        li.appendChild(dl);
      }
      /* 第五欄是更新日期（沒有完整頁時是空字串，所以真假值判斷照舊）。
         舊資料可能是數字 1——那時沒有日期可印，退回「完整」。 */
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
      if(box.value.trim().toLowerCase()!==q) return;  /* 打字比抓索引快 */
      hits=search(q); cur=hits.length?0:-1; draw();
    });
  }

  /* ---- 本機抓取 -------------------------------------------------------
   * 靜態站台抓不到券商鏡像站（瀏覽器的同源政策，不是缺功能），所以抓取這件事
   * 只在 `twsix serve` 底下才成立。頁面載入時問一次 /api/ping：問得到就把
   * 「立即抓取」放進搜尋結果，問不到就當作沒有這回事。
   */
  var live=false, grab=document.getElementById('grab');
  /* 線上抓取（GitHub Actions＋瀏覽器裡的權杖）2026-10-04 退役：所有資料都由排程
     自動更新，網頁上不再需要「立即更新」，也不再需要在瀏覽器存 GitHub 權杖。
     repo 留空，下面每一條線上抓取的路就都不會出現；本機 `twsix serve`（live）照舊。
     以前存過的權杖順手清掉——它已經沒有用途，留在瀏覽器裡只是風險。 */
  var repo = '';
  try{ localStorage.removeItem('twsix.token'); }catch(e){}
  fetch(base+'api/ping').then(function(r){return r.ok?r.json():null;})
    .then(function(j){ live = !!(j && j.service==='twsix'); refreshOffer(); })
    .catch(function(){ live=false; refreshOffer(); });

  /* ---- 頁首那顆「抓取 XXXX」 -------------------------------------------
   * 一顆按鈕，一個對象：搜尋框裡選中的那一檔；框是空的就退回這一頁的股票。
   * 已經有完整報告、或這台機器根本抓不了（沒有本機服務也沒有設 repo），
   * 按鈕就不出現。
   */
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
  /* 「已經完整」不等於「不必再抓」。
   *
   * 上一版把有完整報告的那一檔當成沒有對象，按鈕就消失了——於是一檔股票只要成功
   * 抓過一次，就再也沒有辦法重抓：資料放到過期、或是後來新增了區塊（大戶持股、
   * 董監持股就是這樣加進來的），舊的那些檔反而是唯一補不到的。
   *
   * 所以按鈕永遠在，只換字。第一次是「抓取」（這一檔還沒有資料），之後是
   * 「立即更新」——按鈕上該寫的是按下去會發生什麼事，而不是重複一次動作的名字。
   * 已經有報告的時候，讀者要的是「把它換成最新的」，那件事就叫更新。
   */
  function label(code, full){ return (full ? '立即更新 ' : '抓取 ') + code; }

  function refreshOffer(){
    var q = box.value.trim();
    if(q && hits.length){
      var h = hits[cur > -1 ? cur : 0];
      offer(h ? h[0] : '', h && h[4]);
    } else if(!q){
      offer(pageCode, pageFull);
    } else {
      offer('');   /* 打了字卻找不到這一檔：沒有對象可抓 */
    }
  }
  function grabNow(code){
    if(!code) return;
    if(live) fetchStock(code); else if(repo) askGithub(code);
  }
  if(btn){
    /* mousedown 先於 blur，preventDefault 讓搜尋框不失焦——否則清單一關，
       按鈕的對象就在 click 抵達之前被換掉了。 */
    btn.addEventListener('mousedown', function(e){ e.preventDefault(); });
    btn.addEventListener('click', function(){ grabNow(target); });
  }
  var grabX = document.getElementById('grab-x');
  if(grabX){
    grabX.addEventListener('mousedown', function(e){ e.preventDefault(); });
    /* 關掉面板只是不再看它，不是取消——runner 那邊照跑。等待也一併放掉，
       否則下一頁又會把同一個面板叫回來。 */
    grabX.addEventListener('click', function(){
      clearInterval(ticker); ticker = null; watching = null; forget();
      grab.hidden = true;
    });
  }

  /* 線上版的抓取路徑：按下去就跑，不換頁。
   *
   * 靜態網站沒辦法自己抓券商鏡像站，但它可以**直接叫 GitHub Actions 去跑**——
   * REST API 支援跨域，所以 workflow_dispatch 一個 POST 就送得出去，再輪詢
   * 執行狀態把進度畫在同一頁上。這就是桌機版那個面板，只是背後換成 runner。
   *
   * 代價是那個 POST 要一把權杖，而靜態網站沒有地方藏秘密。所以權杖由使用者
   * 自己貼一次，存在**這台瀏覽器的 localStorage**：不進 repo、不進產生出來的
   * HTML、不經過任何第三方，只會送到 api.github.com。別人打開這個網站沒有
   * 權杖，就沒有按鈕，也就按不到任何東西——這比開放 issue 更關得住。
   *
   * 建議用 fine-grained PAT，只勾這一個 repo、只給 Actions 讀寫。那把權杖能做
   * 的事就只有「在這個 repo 跑 workflow」。
   *
   * 沒有權杖時退回開 issue 那條路，一次點擊加一次送出，手機上也能用。
   */
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

  /* ---- 進度面板 ------------------------------------------------------- */
  var started = 0, ticker = null, steps = [], phaseAt = -1, phaseNote = '';
  var grabCode = '';

  function elapsed(){
    var s = Math.round((Date.now() - started) / 1000);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  /* 這條路上的四段，以及各自大概佔多少格。
     格數不是隨便給的，是照實測的時間比例：排隊 10~30 秒、workflow 本身約一分鐘、
     CDN 換檔十幾二十秒。所以條子走到一半的時候，「大概還有一半」這句話是真的
     ——一條會騙人的進度條比沒有進度條糟。 */
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

  /* 段只會往前，不會往後。輪詢會重複看到同一個狀態，而 GitHub 偶爾會在
     in_progress 之後又回報一次 queued——讓條子倒退回去，看起來就是壞了。 */
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
        /* 同一段裡的方塊依序亮，看起來才像在跑而不是在閃。 */
        var delay = cls === 'now' ? ' style="animation-delay:' + (j * 0.13) + 's"' : '';
        html += '<i class="' + cls + '"' + delay + '></i>';
        filled++;
      }
    }
    return html;
  }

  /* 記的是**狀態改變**，不是輪詢次數。
     去重原本比對「時間戳＋文字」，而時間戳每兩秒就不一樣——於是 runner 跑一分鐘
     會印出三十行一模一樣的「runner 開始跑：…」，把面板撐得比它要說的事還長。
     現在只比文字：同一個狀態只佔一行，時間戳留第一次進入那一刻（那才是有意義的
     時間點），後面掛上「已 34 秒」讓人看得出它還在那一段。 */
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
      /* 只有最後一行需要「還在這裡待著」——前面那些的停留時間，看下一行的
         時間戳就知道了。 */
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
    /* 每秒重畫一次，讀者才看得出它還活著。一分半沒有任何動靜，看起來就是當掉
       ——那正是這個計時器存在的唯一理由。 */
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

  /* `action` 是一顆真的按鈕：{label, run}。
   *
   * 原本這裡沒有它，「我知道，我就是要重抓」的辦法是**再按一次同一顆按鈕**——
   * 一個看不見的模式。同一顆按鈕在第一次和第二次做不同的事，而唯一的說明是面板
   * 上一句要人再按一次的提示；讀者按下去之後也分不清剛才那一次到底算不算數。
   * 要保留的能力是對的（新增區塊、快取半份、鏡像更正過，都得靠重抓），說法不對
   * ——所以改成明講：需要它的人看得到一顆寫著「仍要重抓」的按鈕。 */
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
    /* 出事的時候把細節攤開。這時候「每一步第幾秒」正好是唯一有用的東西，
       而要求一個剛看到「抓取失敗」的人再多按一下才看得到，是多餘的一步。 */
    var d = grab.querySelector('.detail');
    if(d && ok === false) d.open = true;
  }

  /* ---- 站內輪詢：資料進網站了沒 --------------------------------------- */
  var PENDING = 'twsix.pending';
  /* `was` 是按下按鈕當下那一檔的第五欄（更新日期，沒有完整頁時是 0）。
     判斷「好了沒」要看它**變了沒有**，不是看它有沒有值——對一檔已經有完整報告
     的股票按「立即更新」，有沒有值從頭到尾都是真，於是輪詢在第一次就以為完成，
     把還沒發布的舊頁面重新載入一次。那正是「按完看起來沒變、要自己再重整一次」
     的來源。 */
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
    /* 停在同一頁時用 reload——它會帶 max-age=0，一定跟伺服器對過再顯示。
       換頁就不會：GitHub Pages 給 HTML 的是 Cache-Control: max-age=600，所以
       十分鐘內看過那一頁的瀏覽器會直接拿自己的快取，看起來就像「抓完了但沒變」。
       掛上這一次建站的號碼，等於換一個網址，快取就繞不過去了。 */
    if(location.pathname.replace(/^.*\//, '') === code + '.html'){ location.reload(); }
    else {
      var fresh = built || TWSIX.built;
      var v = fresh ? ('?v=' + encodeURIComponent(fresh)) : '';
      location.href = base + 'stock/' + code + '.html' + v;
    }
  }
  /* deploy 綠燈之後還要等 Pages 的 CDN 把新檔換上去，通常十幾二十秒。這一段
     沒有辦法縮短，但可以**問得夠密、而且問對東西**，在它一換好的那一秒就重整。

     問的是 build.json：六十個位元組，每建一次站就換一個號碼。以前問的是
     search.json 的第五欄——那一欄只在**資料**變了才動，所以同一天對同一檔按第二次
     「立即更新」，日期一模一樣，頁面就沒有任何訊號可以等，只能空等一個計時器。
     build.json 不會有這個問題：它每次都變。

     一秒問一次。六十個位元組的請求，比一秒的空等便宜得多。 */
  var WATCH_MS = 1000;
  /* 只有在 build.json 拿不到（舊版網站、或 CDN 給了奇怪的東西）時才會用到的
     保底：Actions 都回報成功了，等滿這段時間就直接重整。 */
  var SETTLE_MS = 45000;
  function watch(code, tries, was, deadline){
    if(watching && watching !== code) return;
    watching = code;
    var mine = TWSIX.built || '';
    fetch(base + 'build.json?t=' + Date.now(), {cache:'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(j){
        /* 這一頁自己是哪一次建的，寫在 window.TWSIX.built 裡。線上的號碼跟它
           不一樣，就代表 CDN 已經換上新的一份了——不必再去猜資料變了沒。 */
        if(j && j.built && mine && j.built !== mine){ arrive(code, j.built); return; }
        if(j && j.built) { nextWatch(code, tries, was, deadline); return; }
        return fallback(code, tries, was, deadline);
      })
      .catch(function(){ return fallback(code, tries, was, deadline); });
  }
  /* build.json 不在（例如網站還是上一版建的）就退回舊辦法：看那一檔在
     search.json 裡的更新日期變了沒。 */
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

  /* ---- 還需要抓嗎 ------------------------------------------------------
     剛更新完再按一次，換回來的是一模一樣的資料——13 個請求、一分半鐘，而那一分
     半鐘裡使用者是盯著螢幕在等的。所以在**送出之前**就先判斷。

     界線是「最近一個交易日的 17:00（台北）」：收盤 13:30，但收盤行情約 14:00、
     三大法人約 16:00 才上站，17:00 是安全的。上一次抓取晚於那個時刻，就代表中間
     沒有任何一個來源更新過。

     瀏覽器可能在任何時區，所以一律換算成絕對時刻比較：17:00 台北 = 09:00 UTC。
     國定假日沒有處理（這份靜態網站裡沒有交易日曆），代價是假日按第二次會多抓
     一次——那比漏掉一天的新資料安全。 */
  function dataEpoch(){
    var tp = new Date(Date.now() + 8*3600000);   /* 用 UTC getter 讀就是台北時間 */
    var y = tp.getUTCFullYear(), m = tp.getUTCMonth(), d = tp.getUTCDate();
    if(tp.getUTCHours() < 17) d -= 1;
    var e = new Date(Date.UTC(y, m, d, 9, 0, 0));  /* 09:00 UTC = 17:00 台北 */
    while(e.getUTCDay() === 0 || e.getUTCDay() === 6){ e.setUTCDate(e.getUTCDate() - 1); }
    return e.getTime();
  }
  function stampOf(code){
    if(!data) return '';
    for(var i=0;i<data.length;i++) if(data[i][0] === code) return data[i][5] || '';
    return '';
  }
  /* 送出之前再問伺服器一次。
     瀏覽器手上那份索引可能是這一頁載入時抓的，而中間也許有別人更新過這一檔、
     或是剛重建過站。一個 80 KB 的請求，換掉一整台 runner 加一分鐘——這筆帳無論
     怎麼算都划算。問不到就用手上那份，不會比原本更糟。 */
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
  /* 「已經是最新的」那個判斷是**啟發式**的：17:00 那條界線、每個來源各自的上站
     時間。它會錯——後來新增的區塊（大戶持股、董監持股就是這樣加進來的）只能靠
     重抓補上，快取存到半份的也是，鏡像站更正過數字的也是。所以「不管怎樣都去抓
     一次」這個能力必須留著。
     
     留法改了：不再是「再按一次」那個看不見的模式，而是面板上一顆寫著「仍要重抓」
     的按鈕。按過之後就清掉，下一次照樣先問。 */
  var forced = {};

  /* ---- 直接跑 workflow ------------------------------------------------ */
  function runOnGithub(code){
    /* 索引是延後載入的，而頁首那顆按鈕不必先打字就能按——所以這裡可能還沒有
       index。先確定拿到手，才知道「按之前長什麼樣」，也才判斷得出好了沒。 */
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
    /* 用掉就清掉：這一次是使用者明講的，下一次要重新問過。 */
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

  /* runner 排隊、跑測試、抓資料、補股權歷史、建站，加起來約三到四分鐘——新加
     的一檔要向集保逐週問滿 51 週，那是〔大戶持股〕有沒有走勢的差別。每 4 秒問
     一次狀態，把 GitHub 自己的字串翻成人看得懂的一行，讀者才知道它在哪一步。 */
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
            /* 「成功」有兩種：真的抓了並發布了，還有**什麼都沒做**——workflow 自己
               判斷這一檔已經是最新的，於是抓取、commit、建站、發布四步一起跳過。

               後者的網站不會換，所以再怎麼等 build.json 都不會變：面板會停在
               「等 Pages CDN 換檔」直到六分鐘後放棄，然後說「等太久了，還沒出
               現」——一次完全正常的判斷，看起來像當掉。實際踩到過。

               所以問一句 workflow 到底做了什麼：建站那一步被跳過，就代表沒有新
               的一份要等。 */
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

  /* workflow 完成之後：它到底抓了沒？

     問 jobs API 拿每一步的結論。建站那一步是 `skipped`，就代表這一次什麼都沒
     發布——不必等 CDN，直接告訴讀者「已經是最新的」。問不到（權限、改版、網路）
     就照舊等，那是原本的行為，最壞情況只是回到六分鐘後放棄。 */
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

  /* 曾經有一條「沒權杖就開一張 issue」的退路，已經拿掉。它把一次點擊變成換頁、
     核對標題、按 Submit，而那一頁上還有別的按鈕可以按錯、有預填的股號可以改壞；
     跑完也不會自己關。權杖貼一次就一勞永逸，兩條路並存只是留著壞的那條。 */

  /* ---- 設定權杖 ------------------------------------------------------- */
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
    /* 取消了設定權杖。什麼都不做會變成「按了沒反應」——說一聲它為什麼沒動。 */
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
  /* ---- 本機服務（twsix serve）：同一個面板，不同的後端 ---------------- */
  function pollLocal(code){
    fetch(base + 'api/job/' + code).then(function(r){ return r.json(); })
      .then(function(j){
        if(j.error){ endPanel('抓取失敗', j.error, false); return; }
        if(!j.done){
          /* 本機那條路每一行都是 twsix report 自己印的，直接照抄。 */
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

  /* 換頁之後把等待接回來。計時器從零重新起算——真正的起點已經不在這一頁上，
     顯示一個假的總時間比顯示這一頁等了多久更誤導。 */
  (function resume(){
    var j = pendingJob();
    if(!j) return;
    setTimeout(function(){
      beginPanel(j.code);
      step('等 ' + j.code + ' 的資料進到網站…', 'cdn');
      watch(j.code, 180, j.was, Date.now() + 90000);
    }, 1200);
  })();

  /* 權杖入口。放在導覽列而不是藏在按鈕裡，因為換一把、清掉都要找得到。 */
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
      /* 有選中就跳轉；沒有就讓 form 送到清單頁，那是無 JS 時走的同一條路。 */
      if(cur>-1 && hits[cur]){
        e.preventDefault();
        /* 有完整報告就跳過去；沒有而且本機服務在跑，Enter 就是「去抓」——
           那才是「輸入代號就跑出完整報告」的意思。 */
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


/* =========================================================================
 * 觀察清單：全站唯一一份
 *
 * 兩個地方會動它——〔評等清單〕每一列的☆，以及個股頁標題旁邊那一顆。兩邊各寫
 * 一份的話，遲早會出現「清單上是亮的、點進去卻是暗的」，而那種不一致沒有任何
 * 錯誤訊息，只會讓人以為星號沒存到。
 *
 * 存在 localStorage，只在這台瀏覽器裡。這是一份靜態網站——沒有伺服器可以放你的
 * 私人清單，也不該有。換一台機器要重加，那是這個取捨的代價。
 * ========================================================================= */
var TWSIXWatch = (function(){
  /* 2026-10-05 起觀察清單分成數個**子群組**（分頁）：
   *
   *   twsix.wgroups = {v:1, cur:"main", groups:[{id, name, codes:[…], src?, hidden?}]}
   *
   * - 每個群組自己的 codes 陣列就是那一頁的順序（置頂／上移／下移只動它）。
   * - cur 是「目前的群組」：觀察清單頁顯示它，〔評等清單〕每一列的☆與個股頁的☆
   *   也是加進／移出它——按下去之前，星號的說明會寫出是哪一個群組。
   * - 從各頁「匯入觀察清單」建立的群組帶著 src（例如 "trend"、"sc-fin"），同一個
   *   來源再匯入一次就**換掉**那個群組的內容，不會一直多出新分頁；改過名字也認得。
   * - 第一次載入時，舊的 twsix.watchlist 整份變成第一個群組〔我的自選〕（id 固定為
   *   main，兩台裝置登入同一個帳號時才合併得起來）。之後 twsix.watchlist 仍然寫一份
   *   「所有群組的聯集」，給還沒更新的舊頁面與雲端同步的舊版本看。
   *
   * 舊版的說明（順序為什麼存陣列、reload 為什麼每次重建去重表）仍然成立，只是對象
   * 從整份清單換成「目前的群組」。 */
  var KEY = 'twsix.wgroups', OLD = 'twsix.watchlist';
  /* 〔總交集清單〕（2026-10-05）：永遠排在最後的一個**自動算出來**的分頁——所有（非空的）
     群組都有的那幾檔。它不存在 groups 裡，不能改名、刪除、排序，也不能直接加減股票
     （☆ 在它底下按了不會動），要改它就去改各個群組。空的群組不算，否則剛新增一個空群組，
     總交集就瞬間變成零檔。 */
  var ALL = '__all', ALL_NAME = '總交集清單';
  /* 〔隱藏〕（2026-10-05）：hidden 的群組不出現在分頁列（〔管理〕裡才看得到），也**不參與**
     總交集——留著備查、但暫時不想讓它卡住交集的清單，就把它藏起來。資料完全不動。 */
  var doc = null, cur = null, order = [], set = {};

  function clean(codes){
    var seen = {}, out = [];
    (codes || []).forEach(function(c){
      c = String(c || '').trim();
      if(c && !seen[c]){ seen[c] = 1; out.push(c); }   /* 以第一次出現為準 */
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
    if(cur.virtual) return !!set[code];      /* 總交集清單不能直接加減 */
    if(set[code]) order.splice(order.indexOf(code), 1);
    else order.push(code);                  /* 新加的排在最後面，不是插進中間 */
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
  /* ☆ 亮不亮（2026-10-05 起）：
     - 〔台股觀察清單〕頁上：這一檔在不在**目前這個群組**（表格列的就是目前群組）。
     - 其他頁（評等清單、個股頁）：在不在**任何一個**群組。按下去打開群組選單勾選。 */
  /* 「這一頁是不是觀察清單」整頁只問一次（2026-10-06）。原本每一顆☆都問一次
     document.querySelector——評等清單上找不到那張表，於是每問一次就把整份
     DOM（1,943 列、十萬個節點）從頭掃到尾，1,943 顆星 × 載入時三輪，手機上要
     卡十幾秒。這一句就是「網頁跑太慢」的主因。 */
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

  /* ---- 群組 ---------------------------------------------------------- */
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
    if(!keepCur) doc.cur = g.id;      /* 從☆選單裡新增時不切換目前的群組 */
    save(); changed();
    return g.id;
  }
  /* ☆ 選單（2026-10-05）：一檔可以同時在好幾個群組裡。 */
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
    if(doc.groups.length <= 1) return false;         /* 最後一個群組不能刪 */
    var i = -1;
    doc.groups.forEach(function(g, k){ if(g.id === id) i = k; });
    if(i < 0) return false;
    doc.groups.splice(i, 1);
    if(doc.cur === id) doc.cur = doc.groups[Math.max(0, i - 1)].id;
    save(); changed();
    return true;
  }
  /* 隱藏／顯示。藏起目前這一頁時，跳到下一個看得到的群組（都藏光了就到總交集）。 */
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
  /* 把 id 那個群組挪到 before 前面（before 為空＝挪到最後）。拖曳與 ◀ ▶ 都走這一條。 */
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
  /* 從其他頁一鍵匯入：同一個來源（src）只有一個群組，再匯入就換掉它的內容。
     asName（2026-10-05）：不覆蓋，另存成一個新群組。新群組**不帶 src**——它是這一刻的
     快照，下次再從同一頁匯入，換掉的仍然是原本那個來源群組，不會動到這份快照。 */
  function nameTaken(name){
    name = String(name || '').trim();
    return doc.groups.some(function(g){ return g.name === name; });
  }
  function importGroup(src, name, codes, asName){
    codes = clean(codes);
    if(asName !== undefined && asName !== null){
      asName = String(asName).trim();
      if(!asName) return null;
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
    delete g.hidden;                         /* 剛匯入的要看得到 */
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
          hideGroup: hideGroup, nameTaken: function(n){ return nameTaken(n); },
          groupsOf: groupsOf, inAny: inAny, setIn: setIn};
})();


/* =========================================================================
 * ☆ 的群組選單（2026-10-05）
 *
 * 一檔股票可以同時在好幾個群組裡。按☆打開一張小選單：每個群組一個勾選框（勾了
 * 就在、取消就移出，立刻生效），最下面〔＋ 新增群組〕直接把這一檔放進新的群組。
 * 只有一個群組的時候不開選單，直接加入／移出那一個——那是最常見的情形，不該多
 * 點一下。點選單外面或按 Esc 收起。
 * ========================================================================= */
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
    if(gs.length === 1){                       /* 只有一個群組：直接加入／移出 */
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
  /* 群組在別處變了（例如另一顆☆、匯入）：選單開著就照新的狀態重畫。 */
  document.addEventListener('twsix:wgroup', function(){ if(box && anchor) render(anchor.getAttribute('data-star')); });
  return {open: open, close: close};
})();


/* =========================================================================
 * 個股頁標題旁邊那一顆☆
 *
 * 清單上加得了、個股頁上加不了，是一個奇怪的不對稱：真正決定「要不要追蹤這一
 * 檔」的時刻，是讀完它那一頁的時候，不是掃清單的時候。
 * ========================================================================= */
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
  /* 上一頁回來、或在別的分頁改過清單，回到這一頁要重畫。 */
  window.addEventListener('pageshow', function(){
    TWSIXWatch.reload();
    TWSIXWatch.paint(btn);
  });
})();


/* =========================================================================
 * 評等清單：排序、篩選、觀察清單
 *
 * 三件事放在一起，因為它們操作的是同一張表的同一批 <tr>，而且順序有相依：
 * 排序會重排 DOM，篩選只切換 display，觀察清單同時是一個篩選條件和一個狀態。
 * 分開寫就會出現「排序之後星號跑掉」「篩選之後排序失效」那一類的 bug。
 * ========================================================================= */
(function(){
  var table = document.getElementById('t');
  if(!table) return;
  var body = table.tBodies[0];
  var rows = [].slice.call(body.rows);

  /* ---- 觀察清單 --------------------------------------------------------
   * 狀態由 TWSIXWatch 保管（全站唯一一份，個股頁那一顆星也用它）。這裡只多做
   * 一件表格才需要的事：把亮暗寫進那一格的 data-s，讓「依觀察清單排序」有東西
   * 可以比大小。 */
  function paintStar(btn){
    var on = TWSIXWatch.paint(btn);
    var cell = btn.closest('td');
    if(cell) cell.setAttribute('data-s', on ? '1' : '0');
  }
  [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);

  table.addEventListener('click', function(e){
    var btn = e.target.closest('button[data-star]');
    if(!btn) return;
    if(window.TWSIXStarMenu){ TWSIXStarMenu.open(btn); return; }   /* 變動之後由 twsix:wgroup 重畫 */
    TWSIXWatch.toggle(btn.getAttribute('data-star'));
    paintStar(btn);
    /* 取消一檔之後，剩下那幾列的「第一個／最後一個」變了——不重畫的話，
       原本的最後一列會留著一顆按不動的「下移」。 */
    applyCustomOrder();
    apply();
    count();
  });

  /* ---- 排序 ------------------------------------------------------------
   * 比大小看 data-s，不看畫面上的字。「+0.50」「—」「AA」照字串排會排出胡說，
   * 而每一欄的型別是在產生 HTML 的時候就知道的——那時候寫下來，比在瀏覽器裡
   * 一欄一欄猜可靠。 */
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
      return a[1] - b[1];             /* 同分維持原本的順序，排序才是穩定的 */
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

  /* ---- 自訂順序（只有〔觀察清單〕那一頁） ------------------------------
   *
   * 順序存在 TWSIXWatch 的那個陣列裡，這裡只做兩件事：照它排一次 DOM，以及
   * 把兩顆鈕接上去。
   *
   * 和「點欄位排序」怎麼共存：按上移／下移**先把表格切回自訂順序**再動。
   * 理由是，照〔綜合評分〕排的時候按「上移」沒有任何一個答案是對的——是要改
   * 自訂順序（但畫面不會動，因為畫面照的是評分），還是要改畫面（但那不是一個
   * 存得起來的東西）。兩個都不對，所以不給那個狀態存在：按了就回到自訂順序。
   * 那也是為什麼那兩顆鈕在別的排序下不會變灰——沒有死掉的按鈕要解釋。 */
  var watchOrder = table.getAttribute('data-watchlist') === '1';
  function applyCustomOrder(){
    if(!watchOrder) return;
    var pos = {};
    TWSIXWatch.order().forEach(function(code, i){ pos[code] = i; });
    var decorated = rows.map(function(tr, i){
      var p = pos[tr.getAttribute('data-code')];
      /* 不在清單裡的排在後面（它們本來就會被篩掉，但 DOM 順序仍然要確定，
         否則每次重排的結果會隨瀏覽器的排序實作而不同）。 */
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
  /* 第一個的「上移」和最後一個的「下移」按了不會有事——所以不要讓它們看起來
     可以按。`disabled` 而不是藏起來：藏起來會讓那一格的寬度在第一列和其他列
     之間跳動，整欄看起來是歪的。 */
  function paintMoves(){
    if(!watchOrder) return;
    /* 「第一個／最後一個」要照**自訂順序**數，不是照 `rows`。
     *
     * `rows` 是載入時抓下來的那一份 DOM 順序（建站時照綜合評分排的），它從頭
     * 到尾不會變——所以拿它數出來的最後一列，是評分最低的那一檔，不是清單最
     * 下面那一檔。第一版就是這樣，症狀是**第二列的「下移」變成灰的**，而第一
     * 列和最後一列看起來都正常。
     *
     * 照 TWSIXWatch 的陣列數，那份陣列就是畫面上的順序。 */
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
      /* 〔置頂〕和〔上移〕在第一列是同一件「按了不會有事」，所以一起變灰。 */
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
      /* 先回到自訂順序——見上面那段。已經是自訂順序的話這一步不花什麼。 */
      applyCustomOrder();
      /* `delta === 'top'` 是〔置頂〕。走同一個處理器而不是另外掛一個：
         「先切回自訂順序、動完再重排、焦點跟著走」這三步兩者完全一樣，
         分開寫的話改了一邊就會有一邊沒改到。 */
      var moved_ok = (delta === 'top') ? TWSIXWatch.top(code)
                                       : TWSIXWatch.move(code, +delta);
      if(!moved_ok) return;
      applyCustomOrder();
      /* 焦點跟著那一列走。不跟的話，用鍵盤連按兩次「上移」，第二次按到的是
         剛剛被換下來的那一檔——而畫面上看起來完全正常。 */
      var moved = body.querySelector('tr[data-code="' + code + '"] button[data-delta="' +
                                     (delta === 'top' ? 'top' : (+delta < 0 ? '-1' : '1')) + '"]');
      if(moved && !moved.disabled) moved.focus();
      else if(moved) (moved.parentNode.querySelector('button:not([disabled])') || moved).focus();
    });
  }

  /* ---- 篩選 ------------------------------------------------------------ */
  var q = document.getElementById('q');
  var onlyWatched = document.getElementById('only-watched');
  var onlyPicks = document.getElementById('only-picks');
  var tally = document.getElementById('tally');
  var watchOnlyPage = table.getAttribute('data-watchlist') === '1';
  var QF = [
            ['ai', document.getElementById('f-ai')], ['cf', document.getElementById('f-cf')], ['gf', document.getElementById('f-gf')]];
  var qfReset = document.getElementById('f-reset');
  /* 產業（複選）與綜合評分（範圍），2026-09-29。 */
  var indBtn = document.getElementById('f-indbtn'), indPanel = document.getElementById('f-indpanel');
  var indBoxes = indPanel ? [].slice.call(indPanel.querySelectorAll('input[type=checkbox]')) : [];
  var sMin = document.getElementById('f-smin'), sMax = document.getElementById('f-smax');
  var INDS = null;   // null＝全部產業（不篩）
  function syncInds(){
    var on = indBoxes.filter(function(c){ return c.checked; }).map(function(c){ return c.value; });
    INDS = on.length === indBoxes.length ? null : new Set(on);
    if(indBtn) indBtn.textContent = (INDS === null ? '全部產業' : (on.length ? '已選 ' + on.length + ' 個產業' : '未選產業')) + ' ▾';
  }
  /* 報酬風險比（複選面板，2026-09-30）：勾了的任一成立就列。 */
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
    if(st.free) parts.push('無風險'); if(st.bear) parts.push('空頭'); if(st.na) parts.push('—');
    rrBtn.textContent = (parts.length ? parts.join('、') : '全部') + ' ▾';
  }
  function rrPass(tr){
    var st = rrState(); if(!st.active) return true;
    var cat = tr.getAttribute('data-f-rr') || '', v = tr.getAttribute('data-f-rrv');
    if(st.free && cat === 'free') return true;
    if(st.bear && cat === 'bear') return true;
    if(st.na && cat === 'na') return true;
    if(st.range){
      if(cat === 'free') return st.hi === null;          // 無風險＝∞：只設下限時一定篩到
      if(v){ v = parseFloat(v); if((st.lo === null || v >= st.lo - 1e-9) && (st.hi === null || v <= st.hi + 1e-9)) return true; }
    }
    return false;
  }
  function num(el){ if(!el || el.value === '') return null; var v = parseFloat(el.value); return isFinite(v) ? v : null; }

  function visible(tr){
    if(watchOnlyPage || (onlyWatched && onlyWatched.checked)){
      if(!TWSIXWatch.has(tr.getAttribute('data-code'))) return false;
    }
    /* 用 class 找，不數第幾格。這兩個數字原本是 13 和 2，而清單前面加一欄
       流水號就整排位移——那種錯不會報錯，只會讓「只看具投資價值」開始篩錯欄。 */
    var pick = tr.querySelector('td.pick-cell');
    var when = tr.querySelector('td.when-cell');
    /* 快速篩選（2026-09-29）：比對列上的 data-f-*（見 _macros.html.j2 的 row）。
       〔具投資價值〕原本是勾選框，現在是下拉（全部／具投資價值／不具）；舊的勾選框
       寫法也還認得。 */
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
      /* data-f-* 可以是空白分隔的好幾個記號（〔貪婪恐懼〕同時有 20 與 60 日的），選的那一個在裡面就算 */
      if(want === 'any' ? !got : (' ' + got + ' ').indexOf(' ' + want + ' ') < 0) return false;
    }
    var v = q ? q.value.trim().toLowerCase() : '';
    return !v || tr.textContent.toLowerCase().indexOf(v) > -1;
  }
  /* 篩選條件記在瀏覽器（2026-10-03）：下次打開還是上次設的那一組。鍵是
     `twsix.form.*`——有雲端登入時會跟著帳號同步（見 scripts/site_gate.py），
     沒有的話就只是這台瀏覽器記得。搜尋框不記：那是當下找一檔用的，不是設定。 */
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
    /* 觀察清單那一頁上，分母是「全市場 1,741 檔」——那個數字在那裡沒有意義，
       只會讓人以為自己漏掉了什麼。 */
    /* 數字上色（2026-10-05）：篩出幾檔、分子分母一起用強調色。 */
    var txt = watchOnlyPage || n === rows.length
      ? ('<b class="cnt">' + n + '</b> 檔') : ('<b class="cnt">' + n + ' / ' + rows.length + '</b> 檔');
    /* 觀察清單：群組裡有、表格上卻沒有那一列的代號（2026-10-05）。表格現在收了評等表
       以外的上市櫃公司，正常不會再有；真的有（例如 ETF、已經不在交易所名單上的），
       就把代號寫出來，而不是讓分頁上的檔數和表格默默對不起來。被篩選條件藏起來的
       不算在這裡——那是「篩掉了」，不是「沒有」。 */
    if(watchOnlyPage && typeof TWSIXWatch !== 'undefined'){
      var have = {};
      rows.forEach(function(tr){ have[tr.getAttribute('data-code')] = 1; });
      var lost = TWSIXWatch.order().filter(function(c){ return !have[c]; });
      var hid = 0;
      rows.forEach(function(tr){ if(tr.hidden && TWSIXWatch.has(tr.getAttribute('data-code'))) hid++; });
      if(hid) txt += '（另有 <b class="cnt">' + hid + '</b> 檔被上面的篩選條件藏起來）';
      if(lost.length) txt += '（<b class="cnt">' + lost.length + '</b> 檔查無資料：' + lost.slice(0, 8).join('、') + (lost.length > 8 ? '…' : '') + '）';
    }
    tally.innerHTML = txt;   /* 內容全是數字與代號（data-code），沒有使用者輸入 */
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

  /* 上一頁回來的時候要再篩一次。
   *
   * 實際踩到的症狀：桌機 Chrome 勾了「只看觀察清單」→ 點進個股頁 → 上一頁，
   * 回來以後**勾勾還在，表格卻是全部 1,769 列**。手機版正常。
   *
   * 原因是兩件事撞在一起。瀏覽器自己會還原表單控制項的狀態（那是 session
   * history 的一部分，不是我們寫的），但它**不會**發 change 事件——而還原的
   * 時機在腳本跑完之後。所以 apply() 是拿著「還沒還原、全部未勾」的狀態跑的，
   * 跑完瀏覽器才把 checked 設回 true：畫面於是自相矛盾。手機版之所以正常，是
   * 因為那一次上一頁走的是 bfcache，整份已經篩好的 DOM 原封不動被搬回來，
   * 根本沒有重跑。
   *
   * 兩個事件都掛：pageshow 收 bfcache 那條路（persisted 為真，此時再篩一次是
   * 無害的），load 收「重新解析」那條路——它在表單還原之後才發生。另外重讀一次
   * 觀察清單，因為使用者很可能就是在剛才那一頁按了☆。 */
  function resync(){
    syncInds(); rrLabel();
    TWSIXWatch.reload();
    [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);
    applyCustomOrder();
    apply();
  }
  window.addEventListener('pageshow', resync);
  window.addEventListener('load', resync);

  /* 觀察清單那一頁：一檔都沒加的時候要說話，不要給一張空表讓人以為壞了。 */
  var empty = document.getElementById('watch-empty');
  var show = function(){ if(empty) empty.hidden = TWSIXWatch.count() > 0; };
  show();
  if(empty) table.addEventListener('click', show);
  /* 換了子群組（或新增、刪除、匯入）：星號、自訂順序、篩選、檔數全部照新的群組重來。 */
  document.addEventListener('twsix:wgroup', function(){
    [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);
    applyCustomOrder(); apply(); count(); show();
  });
})();


/* =========================================================================
 * 〔市場監控〕的報告：iframe 長到跟內容一樣高
 *
 * 之前是「撐到剛好填滿視窗剩下的高度」。那樣只有一條捲軸沒錯，但捲的是
 * **iframe 自己**——於是外層頁面幾乎不動，右下角那顆「回到最上方」永遠不出現
 * （它看的是 window 的捲動量），而且滑鼠移出 iframe 之後滾輪就不再捲報告。
 *
 * 改成量內容、把 iframe 拉到那麼高：內層不再有捲軸，捲的是整個頁面，回到最上方
 * 那顆按鈕也就跟站上其他頁一樣可用。
 *
 * **只對 .embed.fit 生效，不是所有的 iframe.embed。** 這一條是後來補的，代價很大：
 * 兩份報告的版面模型根本不同。市場監控那份是一份會流動的文件（body 只有 padding，
 * 高度由內容決定），量它的 body 再去設 iframe 高度是單向的，會收斂。趨勢選股那份
 * 是一個釘死在視窗裡的應用程式——`html,body{height:100%;overflow:hidden}`、
 * `#main{height:calc(100vh - …)}`、`.plot{flex:1 1 auto}`——它的高度**來自 iframe
 * 的高度**。對它做同一件事就變成一個環：A 決定 B、B 又決定 A，中間任何一次進位
 * （手機的小數 device pixel、Plotly resize 之後自己寫回去的整數高度）都會讓它每
 * 一輪長一點點，畫面上就是那份報告被無止盡地往下拉長。所以這種頁面本來就該維持
 * CSS 裡的固定高度，用它自己的內部捲動。
 *
 * 另外兩件事情要小心：
 *
 * 1. **量的是 body 不是 documentElement。** `documentElement.scrollHeight` 會取
 *    「內容」與「視窗」的較大值——iframe 已經被我們拉高之後，它回的是 iframe 的
 *    高度，於是只會越量越高、收合卡片之後留下一大片空白。body 是一般的區塊盒，
 *    高度就是內容高度，收合之後會跟著縮回來。
 *
 * 2. **報告的內容高度會變。** 那份報告是可以展開／收合的，所以不能只在載入時量
 *    一次。用 ResizeObserver 盯著它的 body，展一張卡片就重量一次。
 *
 * 同源（就在這個網站上），所以直接讀得到 contentDocument，不需要 postMessage。
 * 讀不到就退回 CSS 裡那個固定高度——那時候會有內層捲軸，但至少讀得到。
 * ========================================================================= */
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

  /* iframe 在還沒載入前先有一份 about:blank 文件，而且它**有 body**。所以
     「有沒有 body」不能拿來判斷報告到了沒有——會量到空文件，也會把
     ResizeObserver 綁到那個等一下就被丟掉的 body 上。 */
  function realDoc(frame){
    var doc;
    try{ doc = frame.contentDocument; }catch(e){ return null; }   /* 跨來源就放棄 */
    if(!doc || !doc.body) return null;
    var href = doc.location && doc.location.href;
    if(!href || href === 'about:blank') return null;
    return doc;
  }

  /* 每一格 iframe 自己的「有沒有在失控地長高」計數。就算版面模型看起來安全，
     還是留一個煞車：連續 40 次都只增不減，就認定它是一個環，放手讓 CSS 的固定
     高度接管。壞掉的樣子是有一條內層捲軸，不是一份被拉到幾萬像素的報告。 */
  var GROW_LIMIT = 40;

  function fit(frame, state){
    var doc = realDoc(frame);
    if(!doc) return;
    if(state.bailed) return;
    var h = contentHeight(doc);
    if(!(h > 0)) return;
    var target = Math.ceil(h) + 2;                 /* +2 擋四捨五入 */
    var now = parseFloat(frame.style.height) || 0;
    /* 差不到 4px 就不寫。手機的 device pixel 是小數，量出來的值會在整數之間
       抖動；每抖一次就寫一次，等於自己餵自己一次進位。 */
    if(Math.abs(target - now) <= 4) { state.grow = 0; return; }
    if(target > now){
      if(++state.grow > GROW_LIMIT){
        state.bailed = true;
        if(state.ro) state.ro.disconnect();
        frame.style.height = '';                   /* 退回 CSS 的固定高度 */
        return;
      }
    } else {
      state.grow = 0;
    }
    frame.style.height = target + 'px';
  }

  frames.forEach(function(frame){
    var state = { grow: 0, bailed: false, ro: null };
    /* 記的是「現在盯著哪一個 body」而不是一個 observed 旗標。
       原本用旗標，於是報告載得比 site.js 慢的時候（1 MB 的 HTML，冷啟動很常
       發生），第一次 attach 綁到 about:blank 的 body 就把旗標鎖住了：之後高度
       只在載入當下量對一次，展開任何一張卡片都不會再重量——內層捲軸就是這樣
       跑出來的，而且因為外層頁面不長，右下角那顆「回到最上方」也一起消失。 */
    var watching = null;

    function attach(){
      var doc = realDoc(frame);
      if(!doc || state.bailed) return;
      /* 換了文件就重新開始算，舊文件的成長次數跟新的沒有關係。 */
      if(watching && watching !== doc.body) state.grow = 0;
      fit(frame, state);
      if(typeof ResizeObserver === 'undefined') return;
      if(watching === doc.body) return;           /* 已經在盯同一個了 */
      if(state.ro) state.ro.disconnect();         /* 換文件了，舊的丟掉 */
      state.ro = new ResizeObserver(function(){ fit(frame, state); });
      state.ro.observe(doc.body);
      watching = doc.body;
    }

    frame.addEventListener('load', attach);
    attach();                                   /* 已經載好的情況 */
    /* 視窗變寬變窄會改變報告的排版，所以要重量；但這是使用者的動作，不是那個
       環，所以順便把成長計數歸零。 */
    window.addEventListener('resize', function(){ state.grow = 0; fit(frame, state); });
    /* 字體晚一點載入會改變內容高度，所以再量一次。 */
    if(document.fonts && document.fonts.ready) document.fonts.ready.then(attach);
    /* 最後一道保險：報告載入的時機不受我們控制（快取、網速、瀏覽器怎麼排
       iframe 的載入都會變），所以在頭幾秒再試幾次。attach 本身是冪等的，
       綁對了就不會重綁。 */
    [200, 800, 2000, 5000].forEach(function(ms){ setTimeout(attach, ms); });
  });
})();


/* =========================================================================
 * 目標價試算盤
 *
 * 一條公式，三個維度：營收成長率 × 淨利率 → 預估 EPS，再乘上每一個預估 PE →
 * 目標價。頁面上其他地方給的是「引擎依規則算出的一個答案」，這裡給的是「你的
 * 假設會得到什麼答案」。
 *
 * 顏色刻意不照數字大小塗。坊間工具把高價塗紅、低價塗綠，但對看的人來說，一個
 * 目標價是好是壞不在於它大不大，而在於它離現價多遠——所以這裡塗的是**相對現價
 * 的上檔空間**：綠色是現價之上，紅色是現價之下。圖表沒有義務讓人猜它在說什麼。
 * ========================================================================= */
(function(){
  var box = document.getElementById('calc');
  if(!box) return;

  var seed = {};
  try{ seed = JSON.parse(box.getAttribute('data-seed') || '{}'); }catch(e){ return; }
  var market = parseFloat(box.getAttribute('data-price'));
  if(isNaN(market) || market <= 0) market = null;
  /* 現價是哪一天的收盤價。矩陣裡每一格的報酬與風險都是拿它算的，所以每一次
     提到它都要帶日期——一個沒有日期的股價看起來永遠像今天的。 */
  var priceDate = box.getAttribute('data-price-date') || '';

  /* ---- 進場成本價位 ------------------------------------------------------
   * 每一格第二行的「預期報酬（＋）／預期風險（−）」拿誰當基準。預設是現價；
   * 讀者填了自己的成本就改用成本——已經買了的人要問的是「相對我買的價錢還有
   * 多少空間」，不是相對今天的收盤。
   *
   * `price` 這個名字保留給「現在拿來比的那個價格」，下面 delta()／legend()
   * 照舊讀它，所以兩種基準走的是同一條算式，不是兩份。
   *
   * 填過的數字記在這台瀏覽器（每一檔一個鍵）。localStorage 在無痕視窗、被
   * 封鎖的網站資料裡會丟例外——那時候就只是不記，照樣能算。 */
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
    /* 悲觀／中性／樂觀。成長率用這一檔自己的月營收年增率——最近一個月是「現在
       的溫度」，近六個月平均是「這一段的趨勢」，兩者之間差很多的時候，那個差
       本身就是最誠實的樂觀／悲觀區間。 */
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

  /* 顏色的意思。
     原本塗的是「離現價多遠」，現在改塗「這一格在這張表裡有多大」——淺到深就是
     小到大。離現價多遠沒有被丟掉，它變成每一格的第二行，那是一個數字，不必再
     用顏色講第二次；而顏色一旦讓出來，就能拿去做另一件顏色比較擅長的事：讓三
     張本益比矩陣一眼分得出來。

     階數是相對這張表自己的極值算的，不是絕對門檻。一張表裡九個值可能只差 10%，
     絕對門檻會把它們塗成同一塊；相對極值則永遠用滿五階，而「最深的是最大的」
     這句話在每一張表上都成立。 */
  function stepper(values){
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    var span = hi - lo;
    return function(v){
      if(!isFinite(v)) return 0;
      return span <= 0 ? 2 : Math.round((v - lo) / span * 4);
    };
  }

  /* 相對現價的漲跌，寫在格子第二行。
     正的是預期報酬，負的是預期風險——同一條算式，符號決定它叫什麼。 */
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

  /* 表頭左上角是兩個座標軸，不是一個標題。「淨利率＼成長率」要讀者自己猜哪個
     是橫的哪個是直的，而猜錯的代價是整張表都看反——所以把這一格切成兩塊三角，
     軸名各站一邊：右上是欄（淨利率），左下是列（成長率）。 */
  var CORNER = '<th class="corner">' +
    '<span class="ax-col">淨利率 →</span>' +
    '<span class="ax-row">↓ 成長率</span></th>';

  /* fam 是色相家族（mn 中性／ma 藍／mb 綠／mc 橘），tone 是標題與表框的色調。
     withDelta 為真時每格加上相對現價的第二行——預估 EPS 那張沒有，因為 EPS
     不是價格，拿它跟股價比是把兩個單位相除。 */
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
    /* 年營收（百萬元）× (1+成長率) × 淨利率 ÷ 股數（億股）
       百萬元 ÷ 億股 = 百萬元 / 一億股 -> 元/股 要再除以 100。 */
    function eps(gv, mv){ return rev * (1 + gv / 100) * (mv / 100) / (sh * 100); }
    function money(v){ return Math.round(v).toLocaleString(); }

    var html = matrix('預估 EPS（元）', eps,
      function(v){ return v.toFixed(2); }, 'n', 0, false);

    /* 本益比由低到高，三張表三個色相：藍 → 綠 → 橘。捲動時分得出自己在看哪
       一張，而不必回頭找標題。超過三個 PE 就從頭輪——色相是標籤，不是刻度。 */
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
  /* 成本改了只要重畫矩陣——同一條 run()，基準換掉而已。`input` 而不是
     `change`：邊打邊看那一行數字跟著動，才知道自己打的是不是想要的那個價位。 */
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


/* =========================================================================
 * 回到最上方，與電腦版／手機版切換
 *
 * 兩顆按鈕放在一起，因為它們是同一件事的兩面：這個站在小螢幕上要能讀，在大
 * 螢幕上要能一次看完一張寬表，而讀者比我們更清楚自己現在要哪一種。
 * ========================================================================= */
(function(){
  var top = document.getElementById('totop');
  if(top){
    /* 市場監控那一頁（唯一會把 iframe 拉到跟內容一樣高的），「最上方」指的是報告的開頭那一列
       ——也就是 iframe 上面那個 <h2> 的位置，不是整個網站的頁首。捲了一萬多
       像素之後想回去的是報告的頭，不是導覽列；真的要導覽列，再往上滑一下就到。
       趨勢選股與其他頁面沒有 .embed.fit，target() 回 0，行為跟原本一樣。 */
    var embed = document.querySelector('iframe.embed.fit');
    var anchor = null;
    if(embed){
      anchor = embed.previousElementSibling;
      while(anchor && anchor.nodeType !== 1) anchor = anchor.previousElementSibling;
      if(!anchor) anchor = embed;
      /* 按鈕做的事變了，說明文字就得跟著變——螢幕閱讀器唸的是這一句。 */
      top.setAttribute('aria-label', '回到報告最上方');
      top.setAttribute('title', '回到報告最上方');
    }
    var target = function(){
      if(!anchor) return 0;
      /* 每次點的時候才量。iframe 的高度會隨著報告展開／收合改變，位置也跟著變，
         載入時算一次存起來的值撐不到第二次點擊。 */
      var y = anchor.getBoundingClientRect().top +
              (window.pageYOffset || document.documentElement.scrollTop) - 12;
      return y > 0 ? y : 0;
    };

    /* 只在真的捲下去之後才出現。一直掛在那裡的話，它在沒捲的畫面上只是一塊
       擋住內容的東西。 */
    var show = function(){
      var y = window.pageYOffset || document.documentElement.scrollTop;
      /* 有 iframe 的頁面用「離報告開頭多遠」當門檻——報告開頭本身可能就在
         400px 以下，用絕對位置判斷會讓按鈕在剛好回到定位時還賴著不走。 */
      top.hidden = (y - target()) < 400;
    };
    window.addEventListener('scroll', show, { passive: true });
    window.addEventListener('resize', show);
    show();
    top.addEventListener('click', function(){
      /* 尊重「減少動態效果」的系統設定：平滑捲動對前庭敏感的人是不舒服的。 */
      var soft = !window.matchMedia ||
                 !matchMedia('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: target(), behavior: soft ? 'smooth' : 'auto' });
    });
  }

  /* 〔切換手機版〕按鈕 2026-10-06 拿掉。以前按過的人瀏覽器裡還記著「手機版」——清掉，
     不然版面會一直被釘在 430px 寬，而且再也沒有按鈕可以切回來。 */
  try{ localStorage.removeItem('twsix.viewmode'); }catch(e){}
  try{ document.documentElement.removeAttribute('data-view'); }catch(e){}
})();


/* =========================================================================
 * 附註的燈泡
 *
 * 一次只開一個。兩塊說明同時攤在畫面上，讀者要自己判斷哪一塊是剛剛按的那一顆
 * 的——而它們長得一模一樣。
 *
 * 關掉的三種方式，缺一個都會讓人覺得卡住：點說明以外的地方、按 Esc、再按一次
 * 同一顆燈泡。點在說明**裡面**不關，因為裡面有連結，也因為有人會想選取文字。
 * ========================================================================= */
(function(){
  /* 先宣告「這一頁有 JavaScript」。沒有這一行，CSS 那邊會把每一塊說明直接攤開
     ——那是沒有 JS 時該有的樣子，但有 JS 的時候會在燈泡還沒接上前閃一下。 */
  document.documentElement.classList.add('js');

  var open = null;

  function close(){
    if(!open) return;
    open.classList.remove('open','flip');
    var box = open.querySelector('.tipbox');
    if(box) box.style.transform = '';    /* 見 show()：那是推回畫面內的位移 */
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
    /* 靠右邊界的那幾顆要往左展開。量出來再決定，不能照 class 猜：同一顆燈泡
       在桌機上離右邊很遠，在手機上就貼著邊。 */
    var box = tip.querySelector('.tipbox');
    if(!box) return;
    box.style.transform = '';
    if(box.getBoundingClientRect().right > window.innerWidth - 8){
      tip.classList.add('flip');
    }
    /* 翻面之後還是出界的話，直接推回來。
       會發生這件事的是**在橫向捲動的表格裡**的那幾顆：`right:0` 是相對於那顆
       燈泡的，而那一欄本身可能已經被捲到畫面外了——翻面只是換一個出界的方向。
       〔報酬風險比〕是清單最右邊那一欄，正好是這個情形。
       推完再檢查左邊，免得把它推出左邊界（說明比視窗還寬的時候會發生）。 */
    var r = box.getBoundingClientRect();
    var shift = 0;
    var over = r.right - (window.innerWidth - 8);
    if(over > 0) shift = -over;
    if(r.left + shift < 8) shift = 8 - r.left;
    /* `transform` 而不是 `margin-left`：翻面之後這個盒子是 `left:auto;right:0`，
       而絕對定位在那個組合下解的是 left——margin 被吃進那條方程式裡，推不動它
       （實測 -145px 下去，量到的位置一個像素都沒變）。transform 不管定位方式
       都會動。 */
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
    /* 點在說明裡面不關——裡面有連結，也有人會想選字。 */
    if(open && e.target.closest && e.target.closest('.tipbox')) return;
    close();
  });

  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape' && open){
      var b = open.querySelector('button.bulb');
      close();
      /* 焦點送回剛剛那顆燈泡。用鍵盤關掉之後焦點如果留在原地，下一次 Tab 會
         從頁面開頭重新走一遍。 */
      if(b) b.focus();
    }
  });
})();


/* =========================================================================
 * 子分頁（〔財務健診〕裡的〔財務地雷〕〔成長力分析〕）
 *
 * 用 hidden 屬性切換：.subpanel 沒有自己的 display，所以 [hidden] 不會被別的
 * 規則蓋掉（這個專案踩過三次那個坑）。
 * ========================================================================= */
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


/* =========================================================================
 * 自己畫的折線圖（SVG）
 *
 * 個股頁一直是零相依的（河流圖、季節性都是自己畫的 SVG），這兩張也一樣：不為了
 * 兩張圖多載一個上百 KB 的圖表函式庫，而且深色模式跟著 CSS 變數走。
 *
 *   TWSIXChart(el, {
 *     x: ['2026-09-22', ...],                 // 日期
 *     series: [{name, color, values, width, dash, step, area}],
 *     hlines: [{value, color, label}],        // 水平虛線（目標價）
 *     range: [i0, i1],                        // 只畫這一段（含）
 *     yMin, yMax, fmt, height, title
 *   })
 *
 * 滑鼠（或手指）移到圖上：一條直線加一個小框列出那一天每一條線的值。
 * ========================================================================= */
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
    /* 2026-10-10：s.bar（以 0 為基準的長條，正負兩色 s.up／s.down）與 s.axis2（右邊另一個
       刻度，例如疊在法人買賣超上的股價）。axis2 的序列不參與左邊刻度的高低。 */
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
    /* o.xTicks(W)：呼叫端可以依寬度指定日期標籤數（AI 選股頁的完整日期在手機上擺 4 個會疊在一起）。
       沒給就是原本的 4／7，其他頁面不受影響。 */
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
        /* 漸層對著**座標軸**（userSpaceOnUse），不是對著這一塊面積自己的外框：
           否則分數一直在 4～5 之間的那一段，4 會被塗成最底下的顏色。 */
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

/* =========================================================================
 * 〔外資投信〕縮放區間（2026-10-10）
 *
 * 建站時畫好的兩張圖只有近 120 日。打開這個分頁時下載 stock/<代號>.i.json（外資
 * 買賣超與持股比率，和 px-hist 的每日收盤逐日對齊），改畫成可以縮放、拉滑桿的圖，
 * 最長到行情檔的全長（約三年）。讀不到就留著原本那兩張。
 * ========================================================================= */
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
    fetch(stat.getAttribute('data-src'), {cache: 'no-cache'}).then(function(r){
      if(!r.ok) throw new Error(r.status); return r.json();
    }).then(function(j){
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
        /* 外資持股比重：每日檔從 2026-04 起才齊，更早只有每月一天。往回找到第一段連續缺 5 天以上的地方，
           那之後才是「每天都有」。 */
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
    }).catch(function(){ /* 留著建站時畫的那兩張 */ });
  }
  if(tab) tab.addEventListener('click', function(){ setTimeout(start, 0); });
  if(location.hash === '#inst') setTimeout(start, 300);
})();

/* 每日收盤：還原 `report/health.py` 的 encode_history。
   d0 是第一天，g 是「每一天和前一天差幾個日曆天」（一個字元一天，'1' = 1 天）。 */
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
/* 簡單移動平均；前 n-1 天沒有值（null），不是用不足 n 天的平均湊。 */
function pxSMA(c, n){
  var out = new Array(c.length), s = 0;
  for(var i = 0; i < c.length; i++){
    s += c[i];
    if(i >= n) s -= c[i - n];
    out[i] = i >= n - 1 ? s / n : null;
  }
  return out;
}


/* 股價健診的六項，某一天（第 i 天）。純函式——node 測試直接呼叫它
   （tests/pxhealth_harness.mjs）。C 是收盤、MA 是 {20:[], 60:[], 240:[]}。
   回傳 [{label, ok(true 正常／false 警示／null 資料不足), text}]。 */
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

/* =========================================================================
 * 股價健診
 *
 * 六條檢查，每一天都算一次；「正常」的數目就是那一天的總評分（0～6）。
 *
 *   1. N 個月內從高檔下跌 ≥ X%     跌幅達到就「警示」
 *   2. N 個月內從低檔上漲 ≥ X%     漲幅**沒有**達到就「警示」（強勢股的反彈力道）
 *   3. 股價低於前 D 個交易日低點   跌破就「警示」
 *   4～6. 股價低於月線／季線／年線  低於就「警示」
 *
 * 一個月以 21 個交易日計。資料不夠長的那一項是「資料不足」，不算正常也不算
 * 警示——那一天的評分也就不畫（畫出來會是一個被少算的分數）。
 * ========================================================================= */
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
    /* 分數越高越健康；顏色沿用台股慣例，強（高分）是紅、弱（低分）是綠。
       評分要六項都算得出來才有值——年線要 240 個交易日，所以最前面將近一年
       是空的。這張圖的左端從第一個有分數的那一天開始，不跟著上面那張留白；
       縮放到比那一天更早的區間時照原樣畫（那一段本來就沒有分數）。 */
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
  /* 分頁一開始是 hidden 的，那時候量到的寬度是 0。第一次切到這一頁才畫。 */
  var tab = document.getElementById('tab-pxhealth');
  var drawn = false;
  function first(){ if(drawn || root.offsetWidth === 0) return; drawn = true; run(); }
  if(tab) tab.addEventListener('click', function(){ setTimeout(first, 0); });
  /* 直接帶 #pxhealth 開進來的時候，分頁是由頁面最後那段腳本打開的——可能比這裡
     晚。盯著它的寬度，一變成非零就畫。 */
  if(typeof ResizeObserver !== 'undefined'){
    new ResizeObserver(function(){ first(); }).observe(root);
  }
  setTimeout(first, 0);
})();


/* 第一個不是 null 的位置；全部是 null 回 -1。 */
function pxFirstValid(a){
  for(var i = 0; i < a.length; i++){ if(a[i] !== null && a[i] !== undefined) return i; }
  return -1;
}

/* 三年 EPS：逐年累乘營收，乘該年淨利率，除以股數。
   rev 百萬元、sh 億股、g／m 是百分比的三元素陣列。百萬 ÷ 億股 ＝ 元 ÷ 100。 */
function y3Eps(rev, sh, g, m){
  var eps = [], r = rev;
  for(var y = 0; y < 3; y++){ r = r * (1 + g[y] / 100); eps.push(r * (m[y] / 100) / (sh * 100)); }
  return eps;
}

/* =========================================================================
 * 推估三年目標價
 *
 * 逐年累乘：今年營收 ＝ 年營收 ×（1＋今年成長率），明年 ＝ 今年 ×（1＋明年成長
 * 率）……該年 EPS ＝ 該年營收 × 該年淨利率 ÷ 股數（百萬元 ÷ 億股要再除以 100），
 * 目標價 ＝ 該年 EPS × 本益比。
 *
 * 目標價表格的樣式與配色和〔估值方式二〕的矩陣同一套（每個本益比一個色相、五階
 * 深淺）；三張圖上的虛線用那一列的色調，對得起來。
 * ========================================================================= */
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
    /* 樣式與配色照〔估值方式二〕的目標價矩陣（2026-10-07 使用者要求）：格子分開、
       圓角、兩行（金額＋相對現價的預期報酬／風險）。每一個本益比一個色相，和試算盤
       同一套：由低到高 藍 → 綠 → 橘（超過三個從頭輪）；同一色相裡五階深淺，九格
       一起排——深淺可以跨列比大小，色相告訴你這是哪一個本益比。預估 EPS 用灰階。
       圖上的虛線用同一列的色調，對得起來。 */
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
    /* 圖上的虛線：那一列的色調（--t1／--t2／--t3），和表頭同色。 */
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
  /* 〔EPS預估與估價〕一開始是 hidden 的：寬度 0 的時候不畫圖，切過去再畫。 */
  function first(){ if(box.offsetWidth === 0 || box._drawn) return; box._drawn = true; run(); }
  var tab = document.getElementById('tab-eps');
  if(tab) tab.addEventListener('click', function(){ setTimeout(first, 0); });
  if(typeof ResizeObserver !== 'undefined'){
    new ResizeObserver(function(){ first(); }).observe(box);
  }
  setTimeout(first, 0);
})();


/* =========================================================================
 * 〔AI 選股〕的圖：資料在 <script id="ai-charts">（見 report/ai_page.py）。
 * 市場寬度、影子帳戶 vs 0050，以及回測的每一張淨值圖（C.list）。都用 TWSIXChart。
 * 包在 try 裡——圖畫不出來，表格與文字照樣在。
 * 收在 <details> 裡的圖等展開才畫：收起來時寬度是 0，畫出來會是預設的 600px，
 * 在手機上撐破版面。
 * ========================================================================= */
(function(){
  var el = document.getElementById('ai-charts');
  if(!el || typeof TWSIXChart === 'undefined') return;
  var C;
  try{ C = JSON.parse(el.textContent); }catch(e){ return; }
  function pct(v){ return v === null || v === undefined ? '—' : ((v - 1) * 100).toFixed(1) + '%'; }
  function box(id){ return document.getElementById(id); }
  function safe(fn){ try{ fn(); }catch(e){ if(window.console) console.warn('AI 選股圖表', e); } }
  function xt(W){ return W < 440 ? 3 : 0; }
  /* 等圖真的看得到才畫：收在沒選中的分頁、或收起來的 <details> 裡的圖，寬度是 0，
     畫出來會是預設的 600px，在手機上撐破版面。分頁一切過來、<details> 一打開就畫。 */
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
  // 回測的淨值圖：一張一個設定（見 report/ai_page.py 的 _chart），這裡照著畫
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

/* =========================================================================
 * 〔AI 選股〕頁的分頁（2026-09-24）：一次只顯示一段。網址 #regime、#backtest…
 * 直接開到那一段；方向鍵左右切換。和個股頁的分頁同一套行為。
 * ========================================================================= */
/* 橫向捲的分頁列：把 el 捲進 bar 的可見範圍，捲最少。已經整顆看得到就一動也不動。 */
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
    // 手機上分頁列是橫向捲的：選中的那一顆被切到一半才捲，而且只捲到剛好露出來
    // ——點了一顆就把整列拉回最左邊（或把那顆拉到最左邊），剛才捲到的位置就沒了。
    // 網址 #journal 直接開的時候它在最右邊，這時才會真的捲。
    var cur = document.getElementById('aitab-' + name);
    if(cur) reveal(bar, cur);
    // 切過去之後停在分頁列上，不是停在上一段捲到的位置（那個位置在新的一段裡沒有意義）
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
  if(want === 'picks') want = 'a';   /* 舊網址：〔今日候選〕2026-10-06 拆成 A／B／D 三頁 */
  if(want && document.getElementById('aitab-' + want)) show(want, false, false);
})();

/* =========================================================================
 * 個股頁〔AI 選股〕分頁：點開時才抓 ai/stock/<代號>.json（見 report/ai_page.py 的
 * write_stock_json），畫成六個小區塊。抓不到（本機直接開檔、或 AI 還沒跑過）就寫
 * 一句「還沒有 AI 資料」，不影響其他分頁。所有文字都經過 esc()——資料來自重大
 * 訊息與 LLM 的摘要，不能直接當 HTML 塞進去。
 * ========================================================================= */
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
    // E
    var e = d.e;
    out.push(card('E', 'ai-tag-e', '財報品質',
      e ? ('<p>' + esc(e.quarter) + ' 財報：紅旗 <b class="' + (e.veto ? 'down' : '') + '">' + esc(e.score) + '</b> 面' +
           (e.veto ? '（三面以上，<b>否決</b>）' : '（三面以上才否決）') + '</p>' +
           (e.details && e.details.length ? '<ul class="ai-list">' + e.details.map(function(x){ return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '<p class="muted">沒有紅旗。</p>'))
        : '<p class="muted">沒有看得到的財報。</p>'));
    // A
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
    // B
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
    // C
    var c = d.c;
    out.push(card('C', 'ai-tag-t', '法說轉折',
      c && c.length ? '<ul class="ai-list">' + c.map(function(t){
        var k = t.kind === '負轉折' ? 'down' : (t.kind === '正轉折' ? 'up' : 'muted');
        return '<li><b>' + esc(t.date) + '</b> <span class="' + k + '">' + esc(t.kind) + '（' + (t.score > 0 ? '+' : '') + t.score.toFixed(1) + '）</span>' +
          ' <span class="muted">' + (t.method === 'llm' ? 'LLM' : '規則') + (t.prev_date ? '，對比 ' + esc(t.prev_date) : '，第一次，沒有可比') + '</span>' +
          (t.summary ? '<br>' + esc(t.summary) : '') +
          (t.highlights && t.highlights.length ? '<br><span class="muted">重點：</span>' + t.highlights.map(esc).join('；') : '') +
          (t.risks && t.risks.length ? '<br><span class="muted">風險：</span>' + t.risks.map(esc).join('；') : '') + '</li>';
      }).join('') + '</ul>' : '<p class="muted">還沒有讀過這一檔的法說簡報（從上線那天起累積，持股與候選優先）。</p>'));
    // D
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
  // 分頁可以用滑鼠點、也可以用方向鍵切或網址 #ai 直接開：看的是面板本身有沒有露出來
  if(window.MutationObserver){
    new MutationObserver(function(){ if(!panel.hidden) load(); })
      .observe(panel, {attributes: true, attributeFilter: ['hidden']});
  }
  var tab = document.getElementById('tab-ai');
  if(tab) tab.addEventListener('click', load);
  if(!panel.hidden) load();
})();

/* =========================================================================
 * 個股頁的週期切換（河流圖、大戶持股，2026-10-07）
 *
 * 預設那一張建站時就畫在頁面上；其他區間的圖在同一個資料夾的 `<代號>.r.json`
 * （見 build.write_range_figures），第一次按其他區間時才下載，之後留在記憶體。
 * 切回預設就放回原本那一張，不必再下載。這一段要排在下面「滑鼠移過的即時資訊」
 * 之前：那一段會改動 svg（包一層、加十字線），存下來的原圖必須是改動前的。
 * ========================================================================= */
(function(){
  var bars = document.querySelectorAll('.rng[data-rng]');
  if(!bars.length) return;
  var code = (location.pathname.split('/').pop() || '').replace(/\.html?$/, '');
  var cache = null;
  function load(){
    if(!cache){
      cache = fetch(code + '.r.json', {cache: 'no-cache'}).then(function(r){
        if(!r.ok) throw new Error(r.status);
        return r.json();
      });
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

/* 伺服器端畫的圖（charts.py：〈個股資訊〉的長條、折線、組合圖、河流圖）滑鼠移過／
   手指滑過的即時資訊。和〔股價健診〕那幾張 JS 圖同一個樣子（.pxtip）：一條垂直
   十字線，旁邊一個小窗列出那一期每一個序列的值——包含右軸的收盤價。
   資料在 <svg data-hover>（見 charts._hover_attr），x 是 viewBox 座標。 */
(function(){
  var NS = 'http://www.w3.org/2000/svg';
  function esc(t){ return String(t).replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function fmt(v, d){ return Number(v).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}); }
  var open = [];
  /* 週期切換換進來的新圖也要接上（2026-10-07）：所以「接一張圖」是一個函式，
     window.TWSIXHover(根節點) 把那裡面還沒接過的圖接上。 */
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
      /* 跟著游標的高度、放在它上方（手機上手指會擋住下方）。圖的上緣可能被凍結的
         頁首蓋住，固定貼在圖頂的話，往下捲一點資訊窗就看不見了。 */
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
  // 手機上沒有 mouseleave：點圖以外的地方就收起來。
  document.addEventListener('touchstart', function(e){
    if(e.target.closest && e.target.closest('.chart-hover')) return;
    open.forEach(function(f){ f(); }); open = [];
  }, {passive: true});
})();

/* 凍結的頁首有多高：寫進 --head-h，給股名列與錨點跳轉讓位（見 site.css 的 header.top）。 */
(function(){
  var h = document.querySelector('header.top');
  if(!h) return;
  function set(){ document.documentElement.style.setProperty('--head-h', h.offsetHeight + 'px'); }
  set();
  if(window.ResizeObserver) new ResizeObserver(set).observe(h);
  else window.addEventListener('resize', set);
})();

/* =========================================================================
 * 觀察清單的子群組分頁（只在〔台股觀察清單〕那一頁）
 *
 * 一列左右滑動的膠囊按鈕，點一下切換群組。右邊釘著〔＋〕與〔管理 ▾〕。
 * 〔管理 ▾〕（2026-10-05 改成下拉選單）：一張直式清單，每一列是一個群組——
 *   ▲ ▼ 排序（桌機也能直接拖曳整列）、✎ 改名、〔隱藏／顯示〕、✕ 刪除；
 *   點群組名稱就切過去（隱藏的群組只能從這裡點進去）。底下有〔＋ 新增群組〕。
 *   點選單外面或按 Esc 收起來。
 * 分頁列上的膠囊仍可拖曳排序、點兩下改名（桌機）。
 * ========================================================================= */
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
    var h = '<div class="wg-menu" role="dialog" aria-label="管理群組">' +
      '<div class="wg-mh"><b>管理群組</b><span>拖曳或 ▲▼ 排序・隱藏的不在分頁列、也不算進總交集</span></div><ul class="wg-rows">';
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
    /* 一列左右滑動：群組一多，換行排成好幾列在手機上會佔掉半個螢幕。重畫時保留捲動
       位置；只有剛載入時把選中的那一顆捲進畫面，之後不自動挪。 */
    var old = host.querySelector('.wg-tabs'), keep = old ? old.scrollLeft : 0;
    var oldRows = host.querySelector('.wg-rows'), keepY = oldRows ? oldRows.scrollTop : 0;
    var h = '<div class="wg-bar"><div class="wg-tabs" role="tablist" aria-label="觀察清單群組">', nHid = 0;
    gs.forEach(function(g, i){
      var on = g.id === cur;
      if(g.hidden){ nHid++; if(!on) return; }      /* 隱藏的不上分頁列（除非正在看它） */
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
    /* 只在剛打開頁面時把選中的那一顆捲進畫面；之後使用者點哪一顆、滑到哪裡，列都不自己動。 */
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
  /* 左右兩端還有東西時淡出一點，提示「可以滑」。 */
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
  /* 點選單外面就收起來。用捕捉階段：選單裡按下去會重畫，冒泡到 document 時
     e.target 已經不在畫面上，判斷不出它原本在不在選單裡。 */
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
  /* 拖曳排序（桌機）：分頁列上看左右半邊，選單裡看上下半邊——放在前半＝插到它前面。 */
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
        /* 插到它後面＝插到資料順序裡它的下一個前面（分頁列上看不到隱藏的，所以照資料算） */
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

/* =========================================================================
 * 〔台股觀察清單〕加入自選股（2026-10-05）：打代號或名稱，加進目前的群組。
 * 候選就是這張表的每一列（評等清單＋評等表不收的上市櫃公司＋ETF）。
 * ========================================================================= */
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

/* =========================================================================
 * 一鍵匯入觀察清單（〔趨勢×六大×報酬〕〔選股功能〕〔AI 選股〕〔籌碼雷達〕）
 *
 * 任何一顆 <button data-wg-src="來源" data-wg-name="預設群組名">：代號清單取自
 * data-wg-codes（建站時就寫好的，例如 AI 選股的候選），沒有的話問
 * window.TWSIXImport[來源]()（篩選結果是畫面上算出來的，例如選股功能、籌碼雷達）。
 * 同一個來源只有一個群組：再匯入一次是**換成這一次的結果**，不是再多一個分頁。
 * ========================================================================= */
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
          (r.copy ? '（新群組，原本的〔' + esc(old.name) + '〕沒動）' : old && old.n ? '（取代原本的 ' + old.n + ' 檔）' : '') +
          '　<a href="' + rel + 'watchlist.html">去看 →</a>');
    }
    if(old && old.n) ask(old, codes.length, done);
    else done();
  });

  /* 已經有同來源的群組時：〔覆蓋〕或〔另存新群組〕。名稱欄預先帶出原本的名字，
     改幾個字就能存（例如加上日期）；跟現有群組同名時不給存，免得分不出哪個是哪個。 */
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
      var v = inp.value.trim();
      var bad = !v ? '請輸入名稱' : TWSIXWatch.nameTaken(v) ? '已經有叫〔' + v + '〕的群組，改一下名字' : '';
      warn.textContent = bad; bc.disabled = !!bad;
    }
    inp.oninput = check; check();
    inp.onkeydown = function(e){
      if(e.key === 'Enter'){ e.preventDefault(); if(!bc.disabled) dlg.close('copy'); }
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
