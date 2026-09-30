// エディタのビジュアル表示（Overleaf の Visual Editor に当たる）。文面は書き換えず、見え方だけを変える。
// 見出しは大きな太字、\textbf などは太字・斜体、\cite・\ref・\label は小さな札、\item は「•」、プリアンブルは折りたたむ。
// カーソル（選択範囲）がかかったところは元のコードに戻すので、そのまま編集できる。.tex 以外のファイルでは何もしない
import { $, store, bus } from "./util.mjs";
import { cm, active, modeOf } from "./editor.mjs";

export let edMode = store.get("oc.editorMode", "code");   // code / visual
let marks = [], timer = null;
const shownPreamble = new WeakSet();   // プリアンブルを開いた文書（CodeMirror の Doc）

const HEAD = { title: 0, part: 1, chapter: 1, section: 1, subsection: 2, subsubsection: 3, paragraph: 4 };
const STYLE = { textbf: "vis-b", textit: "vis-i", emph: "vis-i", textsl: "vis-i", underline: "vis-u", texttt: "vis-tt" };
const CHIP = { cite: (a) => `[${a}]`, ref: (a) => `→${a}`, eqref: (a) => `(→${a})`, label: (a) => `🏷 ${a}`,
               url: (a) => a, input: (a) => `📄 ${a}`, include: (a) => `📄 ${a}` };
const CMD = /\\([a-zA-Z]+)\*?/g;

// text[i] が "{" のとき、対応する "}" の次の位置。無ければ -1
function argEnd(text, i) {
  let d = 0;
  for (let j = i; j < text.length; j++) {
    const c = text[j];
    if (c === "\\") { j++; continue; }
    if (c === "{") d++;
    else if (c === "}" && --d === 0) return j + 1;
    else if (c === "\n" && text[j + 1] === "\n") return -1;   // 段落をまたぐ引数は扱わない
  }
  return -1;
}
// 行ごとの、コメント（エスケープしていない %）が始まる位置
function commentStarts(text) {
  const out = [];
  let lineStart = 0;
  for (const line of text.split("\n")) {
    const m = line.match(/(^|[^\\])%/);
    out.push(m ? lineStart + m.index + m[1].length : Infinity);
    lineStart += line.length + 1;
  }
  return out;
}

function el(tag, cls, text) { const e = document.createElement(tag); e.className = cls; e.textContent = text; return e; }

// 置き換える範囲を集める（位置は文書の先頭からの文字数）
function collect(text, doc) {
  const items = [], cstart = commentStarts(text);
  let line = 0, lineEnd = text.indexOf("\n");
  const inComment = (i) => {
    while (lineEnd !== -1 && i > lineEnd) { line++; lineEnd = text.indexOf("\n", lineEnd + 1); }
    return i >= cstart[line];
  };
  const docBegin = text.indexOf("\\begin{document}");
  if (docBegin > 0 && !shownPreamble.has(doc)) {
    items.push({ from: 0, to: docBegin + "\\begin{document}".length, kind: "preamble" });
  }
  const bodyFrom = docBegin > 0 ? docBegin : 0;
  CMD.lastIndex = bodyFrom;
  for (let m; (m = CMD.exec(text));) {
    const name = m[1], s = m.index;
    if (inComment(s)) continue;
    let p = CMD.lastIndex;
    if (name === "item") { items.push({ from: s, to: p, kind: "item" }); continue; }
    if (!(name in HEAD || name in STYLE || name in CHIP || name === "begin" || name === "end")) continue;
    if (text[p] === "[") { const q = text.indexOf("]", p); if (q < 0) continue; p = q + 1; }
    if (text[p] !== "{") continue;
    const e = argEnd(text, p);
    if (e < 0) continue;
    const arg = text.slice(p + 1, e - 1);
    if (name === "begin" || name === "end") {
      if (arg !== "document") items.push({ from: s, to: e, kind: "chip", cls: "vis-env", label: `${name === "begin" ? "▾" : "▴"} ${arg}` });
    } else if (name in CHIP) items.push({ from: s, to: e, kind: "chip", cls: `vis-chip vis-${name}`, label: CHIP[name](arg) });
    else items.push({ from: s, to: e, kind: "wrap", open: p + 1, close: e - 1,
                      cls: name in HEAD ? `vis-h vis-h${HEAD[name]}` : STYLE[name] });
    if (name in STYLE || name in HEAD) CMD.lastIndex = p + 1;   // 引数の中の \cite なども見る
  }
  return items;
}

function clear() { for (const m of marks) m.clear(); marks = []; }

function render() {
  clear();
  const on = edMode === "visual" && active && modeOf(active.path) === "stex";
  $("cmhost").classList.toggle("visual", !!on);
  if (!on) return;
  const doc = cm.getDoc(), text = doc.getValue();
  const sels = doc.listSelections().map((r) => {
    const a = doc.indexFromPos(r.anchor), b = doc.indexFromPos(r.head);
    return [Math.min(a, b), Math.max(a, b)];
  });
  const touched = (f, t) => sels.some(([a, b]) => a <= t && b >= f);   // 端にカーソルがあっても元に戻す
  const pos = (i) => doc.posFromIndex(i);
  cm.operation(() => {
    for (const it of collect(text, doc)) {
      if (it.kind !== "preamble" && touched(it.from, it.to)) continue;
      if (it.kind === "preamble") {
        if (touched(it.from, it.to)) continue;
        const w = el("span", "vis-pre", "▸ プリアンブル（押すと表示）");
        w.onmousedown = (e) => { e.preventDefault(); shownPreamble.add(doc); render(); };
        marks.push(doc.markText(pos(it.from), pos(it.to), { replacedWith: w, clearOnEnter: false }));
      } else if (it.kind === "item") {
        marks.push(doc.markText(pos(it.from), pos(it.to), { replacedWith: el("span", "vis-item", "•") }));
      } else if (it.kind === "chip") {
        const w = el("span", it.cls, it.label);
        const at = pos(it.from + 1);
        w.onmousedown = (e) => { e.preventDefault(); cm.focus(); doc.setCursor(at); };   // 押すと元のコードに戻して編集
        marks.push(doc.markText(pos(it.from), pos(it.to), { replacedWith: w }));
      } else {   // \section{…} など。コマンドと括弧を隠し、中身に見た目を付ける
        marks.push(doc.markText(pos(it.from), pos(it.open), { collapsed: true }));
        marks.push(doc.markText(pos(it.close), pos(it.to), { collapsed: true }));
        marks.push(doc.markText(pos(it.open), pos(it.close), { className: it.cls }));
      }
    }
  });
}
function later(ms) { clearTimeout(timer); timer = setTimeout(render, ms); }

export function setEdMode(m) {
  edMode = m;
  store.set("oc.editorMode", m);
  document.querySelectorAll("#edmode button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
  document.querySelectorAll(".mi[data-act^='edmode:']").forEach((b) => b.classList.toggle("checked", b.dataset.act === `edmode:${m}`));
  render();
}
$("edmode").onclick = (e) => { const b = e.target.closest("button[data-m]"); if (b) setEdMode(b.dataset.m); };
cm.on("changes", () => later(150));
cm.on("cursorActivity", () => later(30));
bus.on("activate", () => later(0));
setEdMode(edMode);
