/* 名稱旁的〔概況〕：在籌碼雷達以外的頁面打開〈基本面與籌碼概況〉右側面板。
   insight.js（跟籌碼雷達同一份）包在這個函式裡，下面這幾個名字只在裡面有效，不會蓋到頁面自己的同名函式。 */
(function(){
  "use strict";
  if (window.CFI) return;
  var REL = (window.TWSIX && window.TWSIX.rel) || "";
  var BASE = REL + "chipflow/";
  var OPT = {cache: "no-cache"};
  var cache = {}, R = null, ROWS = {};
  function $(id){ return document.getElementById(id) || {getBoundingClientRect: function(){ return {top: 0}; }}; }
  function getJSON(name){
    if (!cache[name]) {
      cache[name] = fetch(BASE + name, OPT).then(function(r){ if (!r.ok) throw new Error(name + " " + r.status); return r.json(); });
      cache[name].catch(function(){ delete cache[name]; });
    }
    return cache[name];
  }
  function stock(code){
    var name = "stock/" + code + ".json";
    if (!cache[name]) {
      cache[name] = window.TWSIXgz(BASE + name, OPT);
      cache[name].catch(function(){ delete cache[name]; });
    }
    return cache[name];
  }
  // 面板裡的 ①②③：到籌碼雷達的那一個工具（另開分頁）
  function open(tab, code){ window.open(REL + "radar.html#" + tab + "-" + encodeURIComponent(code || ""), "_blank", "noopener"); }
  function rows(){
    return getJSON("radar.json").then(function(doc){
      if (R) return R;
      if (doc.cols) {
        var keys = Object.keys(doc.cols), out = new Array(doc.nrows);
        for (var i = 0; i < doc.nrows; i++) {
          var r = {};
          for (var k = 0; k < keys.length; k++) { var v = doc.cols[keys[k]][i]; if (v != null) r[keys[k]] = v; }
          out[i] = r;
        }
        doc = {asof: doc.asof, rows: out};
      }
      R = doc;
      (R.rows || []).forEach(function(r){ ROWS[r.c] = r; });
      return R;
    });
  }
/*@@INSIGHT@@*/
  window.CFI = CFI;
  window.CFI_ROWS = rows;
})();
