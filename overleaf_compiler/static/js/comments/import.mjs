// コメント付きの PDF（Acrobat など）から取り込む。注釈は pdf.js で読み、対象の文字は取り込む PDF 自身の文字から拾う。
// ソースの場所への結びつけはサーバ（comments.import_items）が行う
import { $, post, escapeHtml, showToast, fail } from "../util.mjs";
import { info } from "../state.mjs";
import { setView } from "../panels.mjs";
import { pdfjs, PDFJS_OPTS } from "../pdf.mjs";
import { loadComments } from "./model.mjs";
import { isSpace } from "./marks.mjs";

$("cImport").onclick = () => $("cmtInput").click();
$("cmtInput").onchange = () => { const f = $("cmtInput").files[0]; $("cmtInput").value = ""; if (f) importAnnotated(f); };
const cl = $("cmtList");
cl.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); cl.classList.add("dropping"); } });
cl.addEventListener("dragleave", () => cl.classList.remove("dropping"));
cl.addEventListener("drop", (e) => { e.preventDefault(); cl.classList.remove("dropping"); const f = e.dataTransfer.files[0]; if (f) importAnnotated(f); });
// 取り込む注釈の種類。Popup・Link・Widget（フォーム）は取り込まない
const TAKE = { Highlight: "highlight", Underline: "highlight", Squiggly: "highlight", StrikeOut: "strike", Caret: "insert",
               Text: "note", FreeText: "note", Square: "note", Circle: "note", Ink: "note", Line: "note", Polygon: "note",
               PolyLine: "note", Stamp: "note" };
function isoOfPdfDate(s) {
  const m = /^D:(\d{4})(\d\d)?(\d\d)?(\d\d)?(\d\d)?(\d\d)?([Z+-])?(\d\d)?'?(\d\d)?/.exec(s || "");
  if (!m) return null;
  const tz = !m[7] || m[7] === "Z" ? (m[7] ? "Z" : "") : `${m[7]}${m[8] || "00"}:${m[9] || "00"}`;
  return `${m[1]}-${m[2] || "01"}-${m[3] || "01"}T${m[4] || "00"}:${m[5] || "00"}:${m[6] || "00"}${tz}`;
}
// 取り込む PDF のページの文字を、1文字ずつの位置（左上が原点の pt）にする。見えない所に文字の層を作って測る
async function pageChars(page) {
  const vp = page.getViewport({ scale: 1 });
  const holder = document.createElement("div");
  holder.style.cssText = `position:fixed;left:-20000px;top:0;width:${vp.width}px;height:${vp.height}px;visibility:hidden`;
  for (const v of ["--scale-factor", "--total-scale-factor", "--user-unit"]) holder.style.setProperty(v, 1);
  const layer = document.createElement("div");
  layer.className = "textLayer";
  holder.appendChild(layer); document.body.appendChild(holder);
  try {
    await new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: layer, viewport: vp }).render();
    const hb = holder.getBoundingClientRect(), rg = document.createRange(), chars = [];
    const tw = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      for (let i = 0; i < n.length; i++) {
        rg.setStart(n, i); rg.setEnd(n, i + 1);
        const r = rg.getBoundingClientRect();
        chars.push({ ch: n.data[i], x: r.left - hb.left, y: r.top - hb.top, w: r.width, h: r.height });
      }
    }
    return { chars, vp };
  } finally { holder.remove(); }
}
function annotToItem(a, pageNo, pc) {
  const kind = TAKE[a.subtype];
  const toView = (x, y) => pc.vp.convertToViewportPoint(x, y);
  const item = { kind, author: a.titleObj?.str || "名無し", text: a.contentsObj?.str || "", suggest: "", quote: "",
                 page: pageNo, rects: [], replies: [], created: isoOfPdfDate(a.creationDate || a.modificationDate) };
  const q = a.quadPoints;
  if (q && q.length >= 8 && kind !== "note") {
    const boxes = [];
    for (let i = 0; i + 8 <= q.length; i += 8) {
      const pts = [0, 2, 4, 6].map((k) => toView(q[i + k], q[i + k + 1]));
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      boxes.push([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
    }
    item.rects = boxes.map(([x1, y1, x2, y2]) => [pageNo, x1, y1, x2 - x1, y2 - y1]);
    const inside = (ch) => {
      const cx = ch.x + ch.w / 2, cy = ch.y + ch.h / 2;
      return boxes.some(([x1, y1, x2, y2]) => cx >= x1 && cx <= x2 && cy >= y1 - (y2 - y1) * 0.2 && cy <= y2 + (y2 - y1) * 0.2);
    };
    const got = pc.chars.filter(inside);
    item.quote = got.map((c) => c.ch).join("").replace(/\s+/g, " ").trim();
    const f = got.find((c) => !isSpace(c.ch)) || { x: boxes[0][0], y: boxes[0][1], w: 2, h: boxes[0][3] - boxes[0][1] };
    item.x = f.x + Math.min(2, f.w / 2); item.y = f.y + f.h / 2;
    return item;
  }
  // 付箋・挿入・図形などは点で持つ。近くの文字を目印（quote）にしておき、組み直しても付いていくようにする
  const [x1, y1] = toView(a.rect[0], a.rect[3]), [x2, y2] = toView(a.rect[2], a.rect[1]);
  const px = kind === "insert" ? (x1 + x2) / 2 : Math.min(x1, x2), py = kind === "insert" ? Math.max(y1, y2) - 2 : Math.min(y1, y2) + 18;
  item.pin = [pageNo, px, py];
  const txt = pc.chars.map((c, i) => [c, i]).filter(([c]) => !isSpace(c.ch) && c.w > 0);
  if (txt.length) {
    const [near, k] = txt.reduce((b, cur) => {
      const d = (c) => Math.hypot(c.x + c.w / 2 - px, c.y + c.h / 2 - py);
      return d(cur[0]) < d(b[0]) ? cur : b;
    });
    const before = kind === "insert" && px < near.x + near.w / 2;   // 挿入は印の直前の文字を目印にする
    const from = kind === "insert" ? Math.max(0, (before ? k : k + 1) - 8) : k, to = kind === "insert" ? (before ? k : k + 1) : k + 10;
    const pick = pc.chars.slice(from, to).filter((c) => c.w > 0);
    item.quote = pick.map((c) => c.ch).join("").replace(/\s+/g, " ").trim();
    if (pick.length) {
      const p0 = pick[0];
      item.rects = [[pageNo, p0.x, p0.y, pick.reduce((m, c) => Math.max(m, c.x + c.w), 0) - p0.x, p0.h]];
      item.x = p0.x + Math.min(2, p0.w / 2); item.y = p0.y + p0.h / 2;
    }
  }
  if (item.x === undefined) { item.x = px; item.y = py; }
  if (!item.text && kind === "note" && a.subtype !== "Text") item.text = `（${a.subtype} の書き込み。本文は無い）`;
  return item;
}
// 返信（IRT）を元のコメントにまとめる。member は返信を annotToItem したもの（まとめる種類のときだけ使う）
function mergeReply(root, a, member) {
  const text = a.contentsObj?.str || "";
  if (a.replyType === "Group") {   // Acrobat の「テキストを置換」は、挿入の印と取り消し線を1組にしている
    // pdf.js はまとめられた側にも親の本文を入れて返すので、同じ文は本文に重ねない
    if (root.kind === "insert" && member.kind === "strike") {   // 挿入の印が親（本文が置き換える文字）
      Object.assign(root, { kind: "replace", suggest: root.text, text: member.text === root.text ? "" : member.text,
                            quote: member.quote, rects: member.rects, x: member.x, y: member.y });
      delete root.pin;
    } else if (root.kind === "strike" && member.kind === "insert") {
      root.kind = "replace"; root.suggest = member.text;
      if (root.text === member.text) root.text = "";
    } else if (text) root.text = [root.text, text].filter(Boolean).join("\n");
  } else if (a.state) {   // 完了などの状態。UTF-16 で書かれていると、pdf.js はデコードせずに返す
    if (["Completed", "Accepted"].includes(String(a.state).replace(/[\u0000\u00fe\u00ff]/g, ""))) {
      root.status = "resolved"; root.resolved_by = a.titleObj?.str || "";
      root.resolved_at = isoOfPdfDate(a.modificationDate || a.creationDate);
    }
  } else if (text) root.replies.push({ author: a.titleObj?.str || "名無し", text, created: isoOfPdfDate(a.creationDate || a.modificationDate) });
}
async function importAnnotated(file) {
  if (!info || !info.main) return;
  if (!/\.pdf$/i.test(file.name)) return showToast("PDF ではない", "err");
  showToast(`${escapeHtml(file.name)} のコメントを読んでいる…`, "", 0);
  try {
    const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()), ...PDFJS_OPTS }).promise;
    const all = [];
    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i);
      for (const a of await page.getAnnotations()) if (TAKE[a.subtype]) all.push({ a, i, page });
    }
    const byId = new Map(all.map((x) => [x.a.id, x]));
    const rootOf = (x) => { let r = x; for (let n = 0; r.a.inReplyTo && byId.has(r.a.inReplyTo) && n < 20; n++) r = byId.get(r.a.inReplyTo); return r; };
    const charsCache = new Map(), items = new Map();
    const itemOf = async (x) => {
      if (!charsCache.has(x.i)) charsCache.set(x.i, await pageChars(x.page));
      return annotToItem(x.a, x.i, charsCache.get(x.i));
    };
    for (const x of all.filter((x) => !x.a.inReplyTo || !byId.has(x.a.inReplyTo))) items.set(x, await itemOf(x));
    for (const x of all.filter((x) => x.a.inReplyTo && byId.has(x.a.inReplyTo))) {
      const root = items.get(rootOf(x));
      if (root) mergeReply(root, x.a, x.a.replyType === "Group" ? await itemOf(x) : null);
    }
    const list = [...items.values()].filter((it) => it.text || it.suggest || it.quote || it.replies.length);
    if (!list.length) return showToast("この PDF には取り込めるコメントが無い", "err", 5000);
    const r = await post("/api/comment", { action: "import", items: list });
    await loadComments();
    setView("comments");
    showToast(`${r.added} 件取り込んだ${r.skipped ? `（同じものが既にある ${r.skipped} 件は飛ばした）` : ""}` +
              `${r.unplaced ? `。${r.unplaced} 件はソースの場所が分からない` : ""}`, "ok", 5000);
  } catch (e) { fail(e); }
}
