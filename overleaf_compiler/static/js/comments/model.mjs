// コメント（Acrobat の注釈に当たる）の状態と読み込み。
// コメントはソースの文字列に結びつけて、原稿のフォルダの .<主文書>.comments.json に残る（comments.py）。
// PDF は組み直すたびに位置が変わるので、描くたびに PDF の文字の層から、選んだ文字（quote）を探し直す（marks.mjs）。
import { $, api, store, ask, fail, bus } from "../util.mjs";
import { info } from "../state.mjs";

export const KIND = { highlight: "コメント", strike: "削除の提案", replace: "置換の提案", insert: "挿入の提案", note: "付箋" };
export const PIN_KINDS = new Set(["note", "insert"]);   // 文字に線を引かず、印を1つ置くもの

export let comments = [];          // サーバの一覧。_rects・_pin・_inPdf は今の PDF 上の位置（marks.mjs が付ける）
export let cmtMtime = null;        // 読んだときのファイルの更新時刻。変わったら（CLI が解決・返信した）読み直す
export let cmtActive = null;       // 選んでいるコメントの id
export let cmtFilter = "open";     // 一覧の絞り込み（open・resolved・all）
export function setActive(id) { cmtActive = id; }
export function setFilter(f) { cmtFilter = f; }
export function resetComments() { comments = []; cmtMtime = null; cmtActive = null; bus.emit("comments"); }
export const isResolved = (c) => c.status === "resolved";
// 絞り込みに合うか
export const inFilter = (c, f = cmtFilter) => f === "all" || (f === "resolved") === isResolved(c);

// ---- 書いた人の名前（このブラウザに覚える）----
const authorName = () => store.get("oc.author", "");
function showAuthor() { $("cmtAuthor").textContent = authorName() || "（未設定）"; }
export async function needAuthor(force = false) {
  let a = authorName();
  if (!a || force) {
    a = await ask("名前", "コメントに付ける名前（このブラウザに覚えておく）", a);
    if (!a) return null;
    store.set("oc.author", a); showAuthor();
  }
  return a;
}
$("cmtAuthorEdit").onclick = () => needAuthor(true);
showAuthor();

// ---- 読み込み ----
// 1つずつ順に行う。待っている読み込みがあれば、それに相乗りする（それが最新の内容を読む）
let chain = Promise.resolve(), queued = null;
export function loadComments() {
  if (queued) return queued;
  const p = chain.then(() => { queued = null; return fetchComments(); });
  queued = p; chain = p.catch(() => {});
  return p;
}
async function fetchComments() {
  if (!info || !info.main) return;
  try {
    const r = await api("/api/comments");
    comments = r.comments;
    cmtMtime = r.mtime;
    bus.emit("comments");
  } catch (e) { fail(e); }
}
