/**
 * 相互評価レーダー — Service Worker
 *
 * 目的は2つだけです。
 *   1. ホーム画面から起動したとき、電波がなくても開けるようにする
 *   2. オンラインのときは常に最新のファイルを使う
 *
 * そのため、ページ本体はネットワーク優先（取れなければキャッシュ）、
 * アイコンなどの変わらないファイルはキャッシュ優先にしています。
 * 回答の送受信（Apps Script への通信）は一切キャッシュしません。
 */

var VERSION = "pr2-v1";
var CACHE = "soukan-hyouka-" + VERSION;

var SHELL = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/icon-maskable-512.png",
  "./icons/apple-touch-icon.png"
];

self.addEventListener("install", function(e){
  e.waitUntil(
    caches.open(CACHE).then(function(c){
      /* 1つ失敗しても install 全体を落とさない */
      return Promise.all(SHELL.map(function(u){
        return c.add(new Request(u, { cache: "reload" })).catch(function(){});
      }));
    }).then(function(){ return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function(e){
  e.waitUntil(
    caches.keys().then(function(keys){
      return Promise.all(keys.map(function(k){
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function(e){
  var req = e.request;

  /* 回答の送受信や、別ドメインへの通信には触らない */
  if(req.method !== "GET") return;
  var url;
  try{ url = new URL(req.url); }catch(err){ return; }
  if(url.origin !== self.location.origin) return;

  /* ページ本体はネットワーク優先。更新をすぐ反映させるため */
  if(req.mode === "navigate" || (req.headers.get("accept") || "").indexOf("text/html") >= 0){
    e.respondWith(
      fetch(req).then(function(res){
        var copy = res.clone();
        caches.open(CACHE).then(function(c){ c.put("./index.html", copy); }).catch(function(){});
        return res;
      }).catch(function(){
        return caches.match("./index.html").then(function(hit){
          return hit || caches.match("./");
        });
      })
    );
    return;
  }

  /* それ以外（アイコン等）はキャッシュ優先 */
  e.respondWith(
    caches.match(req).then(function(hit){
      return hit || fetch(req).then(function(res){
        if(res && res.status === 200 && res.type === "basic"){
          var copy = res.clone();
          caches.open(CACHE).then(function(c){ c.put(req, copy); }).catch(function(){});
        }
        return res;
      });
    })
  );
});
