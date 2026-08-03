/**
 * 相互評価レーダー — 回答受け取り用のサーバー
 *
 * Google スプレッドシートに紐づけた Apps Script として動かします。
 * 設定手順は README.md の「自動集計をセットアップする」を見てください。
 *
 * 保存されるもの（シート1行 = 1人）:
 *   A: person  回答者の番号 0〜4
 *   B: code    66文字の回答コード
 *   C: auth    本人パスワードのハッシュ（パスワードそのものは保存しません）
 *   D: at      最終更新日時
 */

/* index.html の PASSWORD と同じ値にしてください。
   結果の取得（list）とリセットに使います。 */
var RESULT_PASSWORD = 'My04279307';

var SHEET_NAME = 'submissions';
var PEOPLE_COUNT = 5;
var CODE_RE = /^PR1[0-4][A-HJ-NP-Z]{62}$/;

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
  } catch (err) {
    return json({ ok: false, error: 'busy' });
  }
  try {
    var req = JSON.parse(e.postData.contents);
    switch (req.action) {
      case 'submit': return handleSubmit(req);
      case 'check':  return handleCheck(req);
      case 'status': return handleStatus();
      case 'list':   return handleList(req);
      case 'reset':  return handleReset(req);
      default:       return json({ ok: false, error: 'unknown_action' });
    }
  } catch (err) {
    return json({ ok: false, error: 'bad_request' });
  } finally {
    lock.releaseLock();
  }
}

/* ブラウザで URL を直接開いたときの動作確認用 */
function doGet() {
  return json({ ok: true, service: 'pr1', rows: countRows() });
}

/* ---------- 各アクション ---------- */

function handleSubmit(req) {
  var person = normPerson(req.person);
  var code = String(req.code || '').toUpperCase();
  var auth = String(req.auth || '');

  if (person === null) return json({ ok: false, error: 'bad_person' });
  if (!CODE_RE.test(code)) return json({ ok: false, error: 'bad_code' });
  if (!/^[0-9a-f]{64}$/.test(auth)) return json({ ok: false, error: 'bad_auth' });

  var sheet = getSheet();
  var row = findRow(sheet, person);

  if (row > 0) {
    // すでに登録がある場合、同じパスワードでないと上書きさせない
    var existing = String(sheet.getRange(row, 3).getValue());
    if (existing !== auth) return json({ ok: false, error: 'auth_mismatch' });
    sheet.getRange(row, 2).setValue(code);
    sheet.getRange(row, 4).setValue(new Date());
  } else {
    sheet.appendRow([person, code, auth, new Date()]);
  }
  return json({ ok: true });
}

/* 別の端末から入るときのパスワード確認。ハッシュ自体は返さない */
function handleCheck(req) {
  var person = normPerson(req.person);
  var auth = String(req.auth || '');
  if (person === null) return json({ ok: false, error: 'bad_person' });

  var sheet = getSheet();
  var row = findRow(sheet, person);
  if (row <= 0) return json({ ok: true, exists: false, match: false });
  return json({
    ok: true,
    exists: true,
    match: String(sheet.getRange(row, 3).getValue()) === auth
  });
}

/* 誰が提出済みかだけ。回答の中身は返さない */
function handleStatus() {
  var rows = dataRows();
  var submitted = rows.map(function (r) { return Number(r[0]); })
                      .filter(function (p) { return p >= 0 && p < PEOPLE_COUNT; });
  return json({ ok: true, submitted: submitted });
}

/* 回答の中身。結果パスワードを知っている人だけが取れる */
function handleList(req) {
  if (!checkKey(req.key)) return json({ ok: false, error: 'bad_key' });
  var rows = dataRows().map(function (r) {
    return { person: Number(r[0]), code: String(r[1]), at: r[3] };
  });
  return json({ ok: true, rows: rows });
}

/* パスワードを忘れた人の登録を消す */
function handleReset(req) {
  if (!checkKey(req.key)) return json({ ok: false, error: 'bad_key' });
  var person = normPerson(req.person);
  if (person === null) return json({ ok: false, error: 'bad_person' });

  var sheet = getSheet();
  var row = findRow(sheet, person);
  if (row > 0) sheet.deleteRow(row);
  return json({ ok: true });
}

/* ---------- 補助 ---------- */

function checkKey(key) {
  return String(key || '') === sha256Hex('pr1|read|' + RESULT_PASSWORD);
}

function normPerson(v) {
  var n = Number(v);
  return (Number.isInteger(n) && n >= 0 && n < PEOPLE_COUNT) ? n : null;
}

function getSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['person', 'code', 'auth', 'at']);
  }
  return sheet;
}

function dataRows() {
  var sheet = getSheet();
  if (sheet.getLastRow() < 2) return [];
  return sheet.getRange(2, 1, sheet.getLastRow() - 1, 4).getValues();
}

function countRows() {
  return dataRows().length;
}

function findRow(sheet, person) {
  if (sheet.getLastRow() < 2) return -1;
  var col = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getValues();
  for (var i = 0; i < col.length; i++) {
    if (Number(col[i][0]) === person) return i + 2;
  }
  return -1;
}

function sha256Hex(str) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, str, Utilities.Charset.UTF_8);
  return bytes.map(function (b) {
    return ('0' + (b & 0xff).toString(16)).slice(-2);
  }).join('');
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
                       .setMimeType(ContentService.MimeType.JSON);
}
