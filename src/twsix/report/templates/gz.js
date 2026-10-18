(function(){
  if (window.TWSIXgz) return;
  function Tree(){ this.t = new Uint16Array(16); this.s = new Uint16Array(288); }
  var LT = new Tree(), DT = new Tree(), LB = new Uint8Array(30), LBase = new Uint16Array(30),
      DB = new Uint8Array(30), DBase = new Uint16Array(30),
      CLO = new Uint8Array([16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]),
      CLT = new Tree(), LENS = new Uint8Array(320), OFFS = new Uint16Array(16);
  function bits(b, base, delta, first){
    var i, s;
    for (i = 0; i < delta; i++) b[i] = 0;
    for (i = 0; i < 30 - delta; i++) b[i + delta] = (i / delta) | 0;
    for (s = first, i = 0; i < 30; i++){ base[i] = s; s += 1 << b[i]; }
  }
  function build(t, lens, off, num){
    var i, sum;
    for (i = 0; i < 16; i++) t.t[i] = 0;
    for (i = 0; i < num; i++) t.t[lens[off + i]]++;
    t.t[0] = 0;
    for (sum = 0, i = 0; i < 16; i++){ OFFS[i] = sum; sum += t.t[i]; }
    for (i = 0; i < num; i++) if (lens[off + i]) t.s[OFFS[lens[off + i]]++] = i;
  }
  (function(){
    var i;
    for (i = 0; i < 7; i++) LT.t[i] = 0;
    LT.t[7] = 24; LT.t[8] = 152; LT.t[9] = 112;
    for (i = 0; i < 24; i++) LT.s[i] = 256 + i;
    for (i = 0; i < 144; i++) LT.s[24 + i] = i;
    for (i = 0; i < 8; i++) LT.s[168 + i] = 280 + i;
    for (i = 0; i < 112; i++) LT.s[176 + i] = 144 + i;
    for (i = 0; i < 5; i++) DT.t[i] = 0;
    DT.t[5] = 32;
    for (i = 0; i < 32; i++) DT.s[i] = i;
    bits(LB, LBase, 4, 3); bits(DB, DBase, 2, 1);
    LB[28] = 0; LBase[28] = 258;
  })();
  function inflate(src){
    var pos = 0, tag = 0, cnt = 0, out = new Uint8Array(src.length * 4 + 1024), olen = 0;
    function grow(n){
      if (olen + n <= out.length) return;
      var o = new Uint8Array(Math.max(out.length * 2, olen + n)); o.set(out.subarray(0, olen)); out = o;
    }
    function bit(){
      if (!cnt--){ if (pos >= src.length) throw new Error("gz eof"); tag = src[pos++]; cnt = 7; }
      var b = tag & 1; tag >>>= 1; return b;
    }
    function rb(num, base){
      if (!num) return base;
      var v = 0, i;
      for (i = 0; i < num; i++) v |= bit() << i;
      return v + base;
    }
    function sym(t){
      var sum = 0, cur = 0, len = 0;
      do { cur = 2 * cur + bit(); ++len; sum += t.t[len]; cur -= t.t[len]; } while (cur >= 0);
      return t.s[sum + cur];
    }
    function dyn(lt, dt){
      var hlit = rb(5, 257), hdist = rb(5, 1), hclen = rb(4, 4), i, num, len;
      for (i = 0; i < 19; i++) LENS[i] = 0;
      for (i = 0; i < hclen; i++) LENS[CLO[i]] = rb(3, 0);
      build(CLT, LENS, 0, 19);
      for (num = 0; num < hlit + hdist;){
        var s = sym(CLT);
        if (s === 16){ var prev = LENS[num - 1]; for (len = rb(2, 3); len; --len) LENS[num++] = prev; }
        else if (s === 17){ for (len = rb(3, 3); len; --len) LENS[num++] = 0; }
        else if (s === 18){ for (len = rb(7, 11); len; --len) LENS[num++] = 0; }
        else LENS[num++] = s;
      }
      build(lt, LENS, 0, hlit); build(dt, LENS, hlit, hdist);
    }
    function block(lt, dt){
      for (;;){
        var s = sym(lt);
        if (s === 256) return;
        if (s < 256){ grow(1); out[olen++] = s; }
        else {
          s -= 257;
          var len = rb(LB[s], LBase[s]), ds = sym(dt), d = olen - rb(DB[ds], DBase[ds]);
          if (d < 0) throw new Error("gz bad distance");
          grow(len);
          for (var i = d; i < d + len; i++) out[olen++] = out[i];
        }
      }
    }
    var last, type, lt = new Tree(), dt = new Tree();
    do {
      last = bit(); type = rb(2, 0);
      if (type === 0){
        cnt = 0;
        var l = src[pos] | (src[pos + 1] << 8); pos += 4;
        grow(l); out.set(src.subarray(pos, pos + l), olen); olen += l; pos += l;
      } else if (type === 1) block(LT, DT);
      else if (type === 2){ dyn(lt, dt); block(lt, dt); }
      else throw new Error("gz bad block");
    } while (!last);
    return out.subarray(0, olen);
  }
  function gunzipSync(u){
    var flg = u[3], p = 10;
    if (flg & 4) p += 2 + (u[10] | (u[11] << 8));
    if (flg & 8) while (u[p++]);
    if (flg & 16) while (u[p++]);
    if (flg & 2) p += 2;
    return inflate(u.subarray(p));
  }
  function gunzip(buf){
    var u = new Uint8Array(buf);
    if (u.length < 2 || u[0] !== 0x1f || u[1] !== 0x8b) return Promise.resolve(u);
    if (typeof DecompressionStream !== "undefined" && !window.TWSIX_NO_DS){
      return new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream("gzip")))
        .arrayBuffer().then(function(b){ return new Uint8Array(b); }, function(){ return gunzipSync(u); });
    }
    try { return Promise.resolve(gunzipSync(u)); } catch (e) { return Promise.reject(e); }
  }
  function text(u){
    if (typeof TextDecoder !== "undefined") return new TextDecoder("utf-8").decode(u);
    var s = "", i;
    for (i = 0; i < u.length; i += 8192) s += String.fromCharCode.apply(null, u.subarray(i, i + 8192));
    return decodeURIComponent(escape(s));
  }
  function q(url, suffix){
    var i = url.indexOf("?");
    return i < 0 ? url + suffix : url.slice(0, i) + suffix + url.slice(i);
  }
  window.TWSIXgunzip = gunzip;
  window.TWSIXgz = function(url, opt){
    return fetch(q(url, ".gz"), opt).then(function(r){
      if (!r.ok) throw new Error(r.status);
      return r.arrayBuffer().then(gunzip).then(function(u){ return JSON.parse(text(u)); });
    }).catch(function(){
      return fetch(url, opt).then(function(r){
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
    });
  };
})();
