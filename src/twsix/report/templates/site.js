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
  var repo = TWSIX.repo;
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

  function endPanel(head, note, ok){
    clearInterval(ticker); ticker = null;
    if(!grab) return;
    grab.hidden = false;
    grab.querySelector('.head').innerHTML =
      '<b>' + head + '</b><span class="t">' + elapsed() + '</span>';
    grab.querySelector('.stage').textContent = note || '';
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
  /* 第一次按告訴他「已經是最新的」，第二次按就照做。那顆按鈕不必多一個選項，
     而「我知道，我就是要重抓」也不必跑去 Actions 分頁。 */
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
      forced[code] = true;
      endPanel(code + ' 已經是最新的',
               '最後抓取 ' + prettyStamp(stamp) + '，之後沒有任何一個來源更新過'
               + '（收盤行情與三大法人下午才上站，界線抓在 17:00）。'
               + '這次沒有派 runner。真的要重抓的話，再按一次。', true);
      return;
    }
    var force = !!forced[code] && isFresh(stamp);
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
                   + '——網站上這一份就是最新的。真的要重抓的話，再按一次。', true);
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
   * 存在 localStorage，只在這台瀏覽器裡。這是一份靜態網站——沒有伺服器可以放
   * 你的私人清單，也不該有。換一台機器要重加，那是這個取捨的代價。 */
  var KEY = 'twsix.watchlist';
  function load(){
    try{ return JSON.parse(localStorage.getItem(KEY) || '[]') || []; }catch(e){ return []; }
  }
  function save(list){
    try{ localStorage.setItem(KEY, JSON.stringify(list)); }catch(e){}
  }
  var watched = {};
  load().forEach(function(c){ watched[c] = 1; });

  function paintStar(btn){
    var on = !!watched[btn.getAttribute('data-star')];
    btn.textContent = on ? '★' : '☆';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.classList.toggle('on', on);
    var cell = btn.closest('td');
    if(cell) cell.setAttribute('data-s', on ? '1' : '0');
  }
  [].forEach.call(table.querySelectorAll('button[data-star]'), paintStar);

  table.addEventListener('click', function(e){
    var btn = e.target.closest('button[data-star]');
    if(!btn) return;
    var code = btn.getAttribute('data-star');
    if(watched[code]) delete watched[code]; else watched[code] = 1;
    save(Object.keys(watched));
    paintStar(btn);
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

  /* ---- 篩選 ------------------------------------------------------------ */
  var q = document.getElementById('q');
  var onlyWatched = document.getElementById('only-watched');
  var onlyPicks = document.getElementById('only-picks');
  var onlyFull = document.getElementById('only-full');
  var tally = document.getElementById('tally');
  var watchOnlyPage = table.getAttribute('data-watchlist') === '1';

  function visible(tr){
    if(watchOnlyPage || (onlyWatched && onlyWatched.checked)){
      if(!watched[tr.getAttribute('data-code')]) return false;
    }
    if(onlyPicks && onlyPicks.checked && tr.cells[13].getAttribute('data-s') !== '1') return false;
    if(onlyFull && onlyFull.checked && !tr.cells[2].getAttribute('data-s')) return false;
    var v = q ? q.value.trim().toLowerCase() : '';
    return !v || tr.textContent.toLowerCase().indexOf(v) > -1;
  }
  function apply(){
    rows.forEach(function(tr){ tr.hidden = !visible(tr); });
    count();
  }
  function count(){
    if(!tally) return;
    var n = 0;
    rows.forEach(function(tr){ if(!tr.hidden) n++; });
    /* 觀察清單那一頁上，分母是「全市場 1,741 檔」——那個數字在那裡沒有意義，
       只會讓人以為自己漏掉了什麼。 */
    tally.textContent = watchOnlyPage || n === rows.length
      ? (n + ' 檔') : (n + ' / ' + rows.length + ' 檔');
  }
  [q, onlyWatched, onlyPicks, onlyFull].forEach(function(el){
    if(el) el.addEventListener(el.tagName === 'INPUT' && el.type === 'search' ? 'input' : 'change', apply);
  });
  apply();

  /* 觀察清單那一頁：一檔都沒加的時候要說話，不要給一張空表讓人以為壞了。 */
  var empty = document.getElementById('watch-empty');
  if(empty){
    var show = function(){ empty.hidden = Object.keys(watched).length > 0; };
    show();
    table.addEventListener('click', show);
  }
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
  var price = parseFloat(box.getAttribute('data-price'));
  if(isNaN(price)) price = null;
  /* 現價是哪一天的收盤價。矩陣裡每一格的報酬與風險都是拿它算的，所以每一次
     提到它都要帶日期——一個沒有日期的股價看起來永遠像今天的。 */
  var priceDate = box.getAttribute('data-price-date') || '';
  function priceLabel(){
    return price.toFixed(2) + (priceDate ? '（' + priceDate + ' 收盤）' : '');
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
             '（相對現價 ' + priceLabel() + '）' };
  }

  function legend(fam, lo, hi, fmt){
    return '<p class="mlegend"><b>顏色</b>　數值由小到大、由淺至深' +
      '<span class="ramp">' + [0,1,2,3,4].map(function(i){
        return '<span class="sw" style="background:var(--m' + fam + i + ')"></span>';
      }).join('') + '</span>' +
      '<span>' + fmt(lo) + ' → ' + fmt(hi) + '</span>' +
      (price === null ? '' :
       '<span>　每格第二行是相對現價 ' + priceLabel() +
       ' 的預期報酬（＋）或預期風險（−）</span>') + '</p>';
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
    /* 只在真的捲下去之後才出現。一直掛在那裡的話，它在沒捲的畫面上只是一塊
       擋住內容的東西。 */
    var show = function(){
      top.hidden = (window.pageYOffset || document.documentElement.scrollTop) < 400;
    };
    window.addEventListener('scroll', show, { passive: true });
    show();
    top.addEventListener('click', function(){
      /* 尊重「減少動態效果」的系統設定：平滑捲動對前庭敏感的人是不舒服的。 */
      var soft = !window.matchMedia ||
                 !matchMedia('(prefers-reduced-motion: reduce)').matches;
      window.scrollTo({ top: 0, behavior: soft ? 'smooth' : 'auto' });
    });
  }

  var vm = document.getElementById('viewmode');
  if(vm){
    var KEY = 'twsix.viewmode';
    var read = function(){
      try{ return localStorage.getItem(KEY) || ''; }catch(e){ return ''; }
    };
    var write = function(v){
      try{ v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); }
      catch(e){}
    };
    /* 「手機版」不是另一份 HTML，是把版面寬度釘成窄的——同一份頁面、同一組
       樣式，只是走 CSS 裡本來就有的那條窄螢幕分支。維護兩份版面才是真正會
       壞掉的做法。 */
    var apply = function(mode){
      document.documentElement.setAttribute('data-view', mode || 'auto');
      var narrow = mode === 'mobile';
      vm.textContent = narrow ? '切換電腦版' : '切換手機版';
      vm.setAttribute('aria-pressed', narrow ? 'true' : 'false');
    };
    apply(read());
    vm.addEventListener('click', function(){
      var next = read() === 'mobile' ? '' : 'mobile';
      write(next); apply(next);
    });
  }
})();
