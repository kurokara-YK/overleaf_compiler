// コメント付きでダウンロード。今の PDF にコメントを PDF の注釈として書き込む（pdf-lib）。
// Acrobat・ブラウザ・プレビューなどでコメントとして見える。返信と解決は Acrobat と同じく元の注釈への返信（IRT）にする
import { $, showToast, fail } from "../util.mjs";
import { info } from "../state.mjs";
import { openMenu } from "../menu.mjs";
import { comments, loadComments, isResolved, KIND, PIN_KINDS } from "./model.mjs";

$("cDownload").onclick = (e) => { e.stopPropagation(); const r = e.target.getBoundingClientRect(); openMenu("mCmtDl", r.left, r.bottom + 2); };

const COLOR = { highlight: [1, 0.83, 0], strike: [0.9, 0.15, 0.15], replace: [0.9, 0.15, 0.15], insert: [0.2, 0.45, 1], note: [1, 0.83, 0] };
const SUBTYPE = { highlight: "Highlight", strike: "StrikeOut", replace: "StrikeOut", insert: "Caret", note: "Text" };

function pdfDateOf(iso) {   // D:YYYYMMDDHHmmSS+09'00'
  const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d+)?(Z|([+-])(\d\d):(\d\d))?/.exec(iso || "");
  if (!m) return null;
  const tz = !m[7] ? "" : m[7] === "Z" ? "Z" : `${m[8]}${m[9]}'${m[10]}'`;
  return `D:${m[1]}${m[2]}${m[3]}${m[4]}${m[5]}${m[6]}${tz}`;
}

// 1件のコメントを注釈にする。書けなければ（ページが無い）false
function writeAnnotation(lib, doc, c) {
  const { PDFString, PDFHexString } = lib;
  const ctx = doc.context, pages = doc.getPages();
  const txt = (s) => PDFHexString.fromText(s || "");
  const date = (iso) => { const d = pdfDateOf(iso); return d ? PDFString.of(d) : PDFString.fromDate(new Date()); };
  // 対象の文字が直されて本文に無いものは、線を引くと別の文字に掛かるので、元の位置に付箋として書く
  const gone = !PIN_KINDS.has(c.kind) && !c._rects;
  const kind = gone ? "note" : c.kind;
  const pin = (PIN_KINDS.has(c.kind) && (c._pin || (c._rects && c._rects[0]) || c.pin)) || (gone && c.rects && c.rects[0]);
  const rects = c._rects || c.rects || [];
  const pageNo = pin ? pin[0] : rects.length ? rects[0][0] : null;
  const page = pageNo && pages[pageNo - 1];
  if (!page) return false;
  // 画面の座標（pt、左上が原点）→ PDF の座標（左下が原点）
  const cb = page.getCropBox();
  const X = (x) => cb.x + x, Y = (y) => cb.y + cb.height - y;
  let Rect, quads = null;
  if (pin) {
    const [px, py] = [X(pin[1]), Y(pin[2])];
    Rect = kind === "insert" ? [px - 5, py - 4, px + 5, py + 10] : [px, py, px + 20, py + 20];
  } else {
    const rs = rects.filter((r) => r[0] === pageNo);
    quads = rs.flatMap(([, x, y, w, h]) => [X(x), Y(y), X(x + w), Y(y), X(x), Y(y + h), X(x + w), Y(y + h)]);
    Rect = [Math.min(...rs.map((r) => X(r[1]))), Math.min(...rs.map((r) => Y(r[2] + r[4]))),
            Math.max(...rs.map((r) => X(r[1] + r[3]))), Math.max(...rs.map((r) => Y(r[2])))];
  }
  // 置換・挿入の提案は、本文の先頭に提案の文字を書く（Acrobat 以外でも読めるように）
  const head = c.kind === "replace" ? `置換: ${c.suggest}` : c.kind === "insert" ? `挿入: ${c.suggest}` : c.kind === "strike" ? "削除" : "";
  const contents = [head, c.text, gone && c.quote ? `（指摘した文字は直されて、今の本文には無い: ${c.quote}）` : ""]
    .filter(Boolean).join("\n");
  const dict = { Type: "Annot", Subtype: SUBTYPE[kind], Rect, F: 4, C: COLOR[kind], CA: 1,
                 T: txt(c.author), Contents: txt(contents), NM: txt(c.id), Subj: txt(KIND[c.kind]),
                 M: date(c.edited || c.created), CreationDate: date(c.created) };
  if (quads) dict.QuadPoints = quads;
  if (kind === "note") dict.Name = "Comment";
  const ref = ctx.register(ctx.obj(dict));
  page.node.addAnnot(ref);
  const reply = (extra) => page.node.addAnnot(ctx.register(ctx.obj({ Type: "Annot", Subtype: "Text", Rect, F: 28, Open: false,
                                                                     IRT: ref, RT: "R", Name: "Comment", ...extra })));
  for (const r of c.replies || []) reply({ T: txt(r.author), Contents: txt(r.text), M: date(r.created), CreationDate: date(r.created) });
  if (isResolved(c)) {
    // 状態は ASCII の文字列で書く（UTF-16 で書くと pdf.js がデコードせずに返し、取り込み直すときに読めない）
    reply({ T: txt(c.resolved_by || ""), Contents: txt(`${c.resolved_by ? `${c.resolved_by} が` : ""}状態を設定しました: 完了`),
            State: PDFString.of("Completed"), StateModel: PDFString.of("Review"), M: date(c.resolved_at) });
  }
  return true;
}

export async function downloadAnnotated() {
  await loadComments();
  if (!comments.length) return showToast("コメントが無い", "", 2500);
  showToast("コメント付きの PDF を作っている…", "", 0);
  try {
    const lib = await import("/static/pdflib/pdf-lib.esm.min.js");
    const bytes = await (await fetch(`/pdf?t=${Date.now()}`)).arrayBuffer();
    const doc = await lib.PDFDocument.load(bytes, { updateMetadata: false });
    const n = comments.filter((c) => writeAnnotation(lib, doc, c)).length;
    const out = await doc.save();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([out], { type: "application/pdf" }));
    a.download = `${info.main.replace(/\.tex$/, "")}_コメント付き.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    showToast(`コメント ${n} 件を書き込んだ PDF をダウンロードした`, "ok", 3500);
  } catch (e) { fail(e); }
}
