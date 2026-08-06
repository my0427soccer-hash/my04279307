/**
 * 相互評価レーダー — 参加者名簿と回答を預かるサーバー
 *
 * Google スプレッドシートに紐づけた Apps Script として動かします。
 * 設定手順は README.md の「自動集計をセットアップする」を見てください。
 *
 * submissions シート（1行 = 1人）:
 *   A: rosterId  名簿の識別子（名簿を変えると変わる）
 *   B: person    回答者の番号
 *   C: code      回答コード
 *   D: auth      本人パスワードのハッシュ（パスワードそのものは保存しません）
 *   E: at        最終更新日時
 *
 * roster シート:
 *   A1: rosterId  B1: scale  C1以降: 参加者名
 */

/* index.html の PASSWORD と同じ値にしてください。
   名簿の登録・結果の取得・リセットの認証に使います。 */
var RESULT_PASSWORD = 'My04279307';

var SUB_SHEET = 'submissions';
var ROSTER_SHEET = 'roster';
var MAX_PEOPLE = 12;
var CODE_RE = /^PR2[A-HJ-NP-Z]{6,900}$/;

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
      case 'getRoster': return handleGetRoster();
      case 'setRoster': return handleSetRoster(req);
      case 'submit':    return handleSubmit(req);
      case 'check':     return handleCheck(req);
      case 'status':    return handleStatus(req);
      case 'list':      return handleList(req);
      case 'reset':     return handleReset(req);
      default:          return json({ ok: false, error: 'unknown_action' });
    }
  } catch (err) {
    return json({ ok: false, error: 'bad_request' });
  } finally {
    lock.releaseLock();
  }
}

/* ブラウザで URL を直接開いたときの動作確認用 */
function doGet() {
  var r = readRoster();
  return json({
    ok: true,
    service: 'pr2',
    people: r ? r.names.length : 0,
    rows: dataRows().length
  });
}

/* ---------- 名簿 ---------- */

function handleGetRoster() {
  var r = readRoster();
  if (!r) return json({ ok: true, names: [], scale: 'double', rosterId: '' });
  return json({ ok: true, names: r.names, scale: r.scale, rosterId: r.rosterId });
}

function handleSetRoster(req) {
  if (!checkKey(req.key)) return json({ ok: false, error: 'bad_key' });

  var names = req.names;
  if (!Array.isArray(names) || names.length < 3 || names.length > MAX_PEOPLE) {
    return json({ ok: false, error: 'bad_roster' });
  }
  var clean = names.map(function (n) { return String(n).trim(); });
  if (clean.some(function (n) { return !n; })) return json({ ok: false, error: 'bad_roster' });

  var scale = (req.scale === 'linear') ? 'linear' : 'double';
  var rosterId = String(req.rosterId || '');
  if (!/^[A-HJ-NP-Z]{4}$/.test(rosterId)) return json({ ok: false, error: 'bad_roster' });

  var prev = readRoster();
  writeRoster(rosterId, scale, clean);

  // 名簿が変わると回答コードの形式も変わるので、古い回答は破棄する
  if (!prev || prev.rosterId !== rosterId) clearSubmissions();

  return json({ ok: true, rosterId: rosterId });
}

/* ---------- 回答 ---------- */

function handleSubmit(req) {
  var r = readRoster();
  if (!r) return json({ ok: false, error: 'no_roster' });
  if (String(req.rosterId) !== r.rosterId) return json({ ok: false, error: 'roster_mismatch' });

  var person = normPerson(req.person, r.names.length);
  var code = String(req.code || '').toUpperCase();
  var auth = String(req.auth || '');

  if (person === null) return json({ ok: false, error: 'bad_person' });
  if (!CODE_RE.test(code)) return json({ ok: false, error: 'bad_code' });
  if (code.substr(3, 4) !== r.rosterId) return json({ ok: false, error: 'roster_mismatch' });
  if (!/^[0-9a-f]{64}$/.test(auth)) return json({ ok: false, error: 'bad_auth' });

  var sheet = getSubSheet();
  var row = findRow(sheet, r.rosterId, person);

  if (row > 0) {
    // 登録済みなら、同じパスワードでないと上書きさせない
    if (String(sheet.getRange(row, 4).getValue()) !== auth) {
      return json({ ok: false, error: 'auth_mismatch' });
    }
    sheet.getRange(row, 3).setValue(code);
    sheet.getRange(row, 5).setValue(new Date());
  } else {
    sheet.appendRow([r.rosterId, person, code, auth, new Date()]);
  }
  return json({ ok: true });
}

/* 別の端末から入るときのパスワード確認。ハッシュ自体は返さない */
function handleCheck(req) {
  var r = readRoster();
  if (!r) return json({ ok: true, exists: false, match: false });

  var person = normPerson(req.person, r.names.length);
  if (person === null) return json({ ok: false, error: 'bad_person' });

  var sheet = getSubSheet();
  var row = findRow(sheet, r.rosterId, person);
  if (row <= 0) return json({ ok: true, exists: false, match: false });
  return json({
    ok: true,
    exists: true,
    match: String(sheet.getRange(row, 4).getValue()) === String(req.auth || '')
  });
}

/* 誰が提出済みかだけ。回答の中身は返さない */
function handleStatus(req) {
  var r = readRoster();
  if (!r) return json({ ok: true, submitted: [] });
  var submitted = dataRows()
    .filter(function (row) { return String(row[0]) === r.rosterId; })
    .map(function (row) { return Number(row[1]); });
  return json({ ok: true, submitted: submitted });
}

/* 回答の中身。結果パスワードを知っている人だけが取れる */
function handleList(req) {
  if (!checkKey(req.key)) return json({ ok: false, error: 'bad_key' });
  var r = readRoster();
  if (!r) return json({ ok: true, rows: [] });
  var rows = dataRows()
    .filter(function (row) { return String(row[0]) === r.rosterId; })
    .map(function (row) { return { person: Number(row[1]), code: String(row[2]), at: row[4] }; });
  return json({ ok: true, rows: rows });
}

/* パスワードを忘れた人の登録を消す */
function handleReset(req) {
  if (!checkKey(req.key)) return json({ ok: false, error: 'bad_key' });
  var r = readRoster();
  if (!r) return json({ ok: true });

  var person = normPerson(req.person, r.names.length);
  if (person === null) return json({ ok: false, error: 'bad_person' });

  var sheet = getSubSheet();
  var row = findRow(sheet, r.rosterId, person);
  if (row > 0) sheet.deleteRow(row);
  return json({ ok: true });
}

/* ---------- 補助 ---------- */

function checkKey(key) {
  return String(key || '') === sha256Hex('pr2|read|' + RESULT_PASSWORD);
}

function normPerson(v, count) {
  var n = Number(v);
  return (Number.isInteger(n) && n >= 0 && n < count) ? n : null;
}

function ss() { return SpreadsheetApp.getActiveSpreadsheet(); }

function getSubSheet() {
  var sheet = ss().getSheetByName(SUB_SHEET);
  if (!sheet) {
    sheet = ss().insertSheet(SUB_SHEET);
    sheet.appendRow(['rosterId', 'person', 'code', 'auth', 'at']);
  }
  return sheet;
}

function getRosterSheet() {
  var sheet = ss().getSheetByName(ROSTER_SHEET);
  if (!sheet) sheet = ss().insertSheet(ROSTER_SHEET);
  return sheet;
}

function readRoster() {
  var sheet = getRosterSheet();
  if (sheet.getLastColumn() < 3 || sheet.getLastRow() < 1) return null;
  var row = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var rosterId = String(row[0] || '');
  if (!rosterId) return null;
  var names = row.slice(2).map(function (n) { return String(n).trim(); }).filter(Boolean);
  if (!names.length) return null;
  return { rosterId: rosterId, scale: String(row[1] || 'double'), names: names };
}

function writeRoster(rosterId, scale, names) {
  var sheet = getRosterSheet();
  sheet.clear();
  sheet.getRange(1, 1, 1, names.length + 2).setValues([[rosterId, scale].concat(names)]);
}

function dataRows() {
  var sheet = getSubSheet();
  if (sheet.getLastRow() < 2) return [];
  return sheet.getRange(2, 1, sheet.getLastRow() - 1, 5).getValues();
}

function clearSubmissions() {
  var sheet = getSubSheet();
  if (sheet.getLastRow() >= 2) {
    sheet.deleteRows(2, sheet.getLastRow() - 1);
  }
}

function findRow(sheet, rosterId, person) {
  if (sheet.getLastRow() < 2) return -1;
  var vals = sheet.getRange(2, 1, sheet.getLastRow() - 1, 2).getValues();
  for (var i = 0; i < vals.length; i++) {
    if (String(vals[i][0]) === rosterId && Number(vals[i][1]) === person) return i + 2;
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
