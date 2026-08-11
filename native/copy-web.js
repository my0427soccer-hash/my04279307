/**
 * 親フォルダのウェブ版を native/www へコピーします。
 * index.html を編集したら `npm run sync` を実行してください。
 *
 * Service Worker はアプリ内では使わない（ファイルは端末内にあるため）ので
 * コピーしません。index.html 側でも登録をスキップしています。
 */
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..");
const DST = path.join(__dirname, "www");
const ITEMS = ["index.html", "manifest.webmanifest", "icons"];

function copy(src, dst) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dst, { recursive: true });
    for (const name of fs.readdirSync(src)) copy(path.join(src, name), path.join(dst, name));
  } else {
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
  }
}

fs.rmSync(DST, { recursive: true, force: true });
fs.mkdirSync(DST, { recursive: true });
for (const item of ITEMS) {
  const from = path.join(SRC, item);
  if (!fs.existsSync(from)) throw new Error("見つかりません: " + from);
  copy(from, path.join(DST, item));
  console.log("copied", item);
}
console.log("→ native/www を更新しました。続けて `npx cap sync ios` を実行してください。");
