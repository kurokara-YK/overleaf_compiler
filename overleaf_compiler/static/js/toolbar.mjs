// エディタのツールバー（Overleaf と同じ並び）。元に戻す・見出し・太字・斜体・数式・記号・リンク・参照・ラベル・引用・
// コメント・図・表・箇条書き・検索。.tex を開いているときだけ出す
import { $, api, enc, escapeHtml, ask, modal, showToast, bus } from "./util.mjs";
import { cm, active, modeOf } from "./editor.mjs";
import { openMenu, closeMenus } from "./menu.mjs";
import { openSearch } from "./search.mjs";

// 選んだ文字を pre と post で囲む。既に囲まれていれば外す。選んでいなければ、カーソルを間に置く
function wrap(pre, post) {
  cm.focus();
  const s = cm.getSelection();
  if (s.startsWith(pre) && s.endsWith(post) && s.length >= pre.length + post.length) {
    return cm.replaceSelection(s.slice(pre.length, s.length - post.length), "around");
  }
  const from = cm.getCursor("from");
  cm.replaceSelection(pre + s + post);
  if (!s) cm.setCursor({ line: from.line, ch: from.ch + pre.length });
}
// 行を丸ごと入れる。text の § の位置にカーソルを置く。カーソルの行に文字があれば、次の行に入れる
function insertBlock(text) {
  cm.focus();
  const cur = cm.getCursor(), line = cm.getLine(cur.line);
  const at = line.trim() ? { line: cur.line, ch: line.length } : { line: cur.line, ch: 0 };
  const body = (line.trim() ? "\n" : "") + text;
  const i = body.indexOf("§"), clean = body.replace("§", "");
  cm.replaceRange(clean, at);
  cm.setCursor(cm.posFromIndex(cm.indexFromPos(at) + (i < 0 ? clean.length : i)));
}
// 見出しの種類を変える。カーソルの行の \section{…} などを付け替える（標準の文なら外す）
const HEAD_RE = /^(\s*)\\(section|subsection|subsubsection|paragraph)\*?\{(.*)\}\s*$/;
function heading(kind) {
  const l = cm.getCursor().line, text = cm.getLine(l);
  const m = text.match(HEAD_RE), body = m ? m[3] : text.trim(), indent = m ? m[1] : text.match(/^\s*/)[0];
  const next = kind === "normal" ? indent + body : `${indent}\\${kind}{${body}}`;
  cm.replaceRange(next, { line: l, ch: 0 }, { line: l, ch: text.length });
  cm.focus(); cm.setCursor({ line: l, ch: next.length - (kind === "normal" ? 0 : 1) });
}
// 選んだ行を箇条書きにする。選んでいなければ空の箇条書きを入れる
function list(env) {
  const s = cm.getSelection();
  if (!s.trim()) return insertBlock(`\\begin{${env}}\n  \\item §\n\\end{${env}}\n`);
  const items = s.split("\n").filter((x) => x.trim()).map((x) => `  \\item ${x.trim().replace(/^\\item\s*/, "")}`);
  cm.replaceSelection(`\\begin{${env}}\n${items.join("\n")}\n\\end{${env}}`);
}
// 選んだ行（無ければカーソルの行）を % でコメントにする。全部コメントなら外す
function toggleComment() {
  const from = cm.getCursor("from").line, to = cm.getCursor("to").line;
  const lines = []; for (let l = from; l <= to; l++) lines.push(cm.getLine(l));
  const all = lines.every((x) => !x.trim() || /^\s*%/.test(x));
  cm.operation(() => lines.forEach((x, k) => {
    const next = all ? x.replace(/^(\s*)% ?/, "$1") : x.trim() ? x.replace(/^(\s*)/, "$1% ") : x;
    cm.replaceRange(next, { line: from + k, ch: 0 }, { line: from + k, ch: x.length });
  }));
  cm.focus();
}
// 原稿の中から \label や .bib の文献キーを集める（検索 API を使う）
async function collect(re, pick) {
  const r = await api(`/api/search?q=${enc(re)}&regex=1`);
  const out = new Set();
  for (const f of r.files) for (const h of f.hits) for (const m of h.text.matchAll(new RegExp(re, "g"))) out.add(pick(m));
  return [...out].filter(Boolean).sort();
}
// 候補から選ぶ小さな窓。候補を押すか、入力して決める
function choose(title, items, hint) {
  const list = items.length ? `<div class="pick">${items.map((x) => `<button class="pk">${escapeHtml(x)}</button>`).join("")}</div>`
                            : `<div class="kbd">${hint}</div>`;
  const p = modal(title, `${list}<div style="margin-top:8px">直接入れる</div><input value="">`,
                  [{ label: "やめる", value: null }, { label: "入れる", value: "__input", cls: "primary" }]);
  setTimeout(() => document.querySelectorAll("#mBody .pk").forEach((b) => b.onclick = () => {
    $("mBody").querySelector("input").value = b.textContent; $("mFoot").lastChild.click();
  }), 0);
  return p;
}
const SYMBOLS = [["α", "\\alpha"], ["β", "\\beta"], ["γ", "\\gamma"], ["δ", "\\delta"], ["ε", "\\epsilon"], ["θ", "\\theta"],
  ["λ", "\\lambda"], ["μ", "\\mu"], ["π", "\\pi"], ["σ", "\\sigma"], ["φ", "\\phi"], ["ω", "\\omega"], ["Δ", "\\Delta"],
  ["Σ", "\\Sigma"], ["Ω", "\\Omega"], ["±", "\\pm"], ["×", "\\times"], ["÷", "\\div"], ["·", "\\cdot"], ["≤", "\\leq"],
  ["≥", "\\geq"], ["≠", "\\neq"], ["≈", "\\approx"], ["∞", "\\infty"], ["→", "\\rightarrow"], ["←", "\\leftarrow"],
  ["⇒", "\\Rightarrow"], ["∈", "\\in"], ["∑", "\\sum"], ["∫", "\\int"], ["√", "\\sqrt{}"], ["°", "^\\circ"], ["∂", "\\partial"]];
function symbol() {
  const p = modal("記号を入れる", `<div class="pick sym">${SYMBOLS.map(([c, t]) => `<button class="pk" title="${t}" data-t="${escapeHtml(t)}">${c}</button>`).join("")}</div>`,
                  [{ label: "閉じる", value: null }]);
  setTimeout(() => document.querySelectorAll("#mBody .pk").forEach((b) => b.onclick = () => {
    $("mFoot").lastChild.click();
    const before = cm.getLine(cm.getCursor().line).slice(0, cm.getCursor().ch);
    const inMath = ((before.match(/(?<!\\)\$/g) || []).length % 2) === 1;   // 数式の中なら $ で囲まない
    cm.focus(); cm.replaceSelection(inMath ? b.dataset.t + " " : `$${b.dataset.t}$`);
  }), 0);
  return p;
}
async function figure() {
  const tree = (await api("/api/tree")).files.filter((f) => !f.dir && /\.(png|jpe?g|pdf|eps)$/i.test(f.path)).map((f) => f.path);
  const img = tree.length ? await choose("図を入れる（画像を選ぶ）", tree, "") : "";
  if (img === null) return;
  insertBlock(`\\begin{figure}[tb]\n  \\centering\n  \\includegraphics[width=\\linewidth]{${img}}\n  \\caption{§}\n  \\label{fig:}\n\\end{figure}\n`);
}
async function table() {
  const v = await ask("表を入れる", "列の数と行の数（例：3x4）", "3x3");
  const m = v && v.match(/(\d+)\s*[x×*,]\s*(\d+)/);
  if (!m) return;
  const cols = Math.min(+m[1], 20), rows = Math.min(+m[2], 50);
  const row = Array(cols).fill("").join(" & ") + " \\\\";
  const body = Array(rows).fill(`    ${row}`).join("\n");
  insertBlock(`\\begin{table}[tb]\n  \\centering\n  \\caption{§}\n  \\label{tab:}\n  \\begin{tabular}{${"c".repeat(cols)}}\n    \\hline\n${body}\n    \\hline\n  \\end{tabular}\n\\end{table}\n`);
}
async function run(t) {
  switch (t) {
    case "undo": return cm.undo();
    case "redo": return cm.redo();
    case "heading": { const r = $("edtool").querySelector('[data-t="heading"]').getBoundingClientRect(); return openMenu("mHeading", r.left, r.bottom + 2); }
    case "bold": return wrap("\\textbf{", "}");
    case "italic": return wrap("\\textit{", "}");
    case "math": return wrap("$", "$");
    case "symbol": return symbol();
    case "link": { const u = await ask("リンクを入れる", "URL", "https://"); if (u) wrap(`\\href{${u}}{`, "}"); return; }
    case "ref": { const k = await choose("参照を入れる（\\ref）", await collect("\\\\label\\{([^}]*)\\}", (m) => m[1]), "原稿に \\label が無い"); if (k) { cm.focus(); cm.replaceSelection(`\\ref{${k}}`); } return; }
    case "label": return wrap("\\label{", "}");
    case "cite": { const k = await choose("文献を引用する（\\cite）", await collect("@\\w+\\{\\s*([^,\\s]+)\\s*,", (m) => m[1]), ".bib に文献が無い"); if (k) { cm.focus(); cm.replaceSelection(`\\cite{${k}}`); } return; }
    case "comment": return toggleComment();
    case "figure": return figure();
    case "table": return table();
    case "itemize": case "enumerate": return list(t);
    case "search": return openSearch();
  }
}
$("edtool").addEventListener("click", (e) => { const b = e.target.closest("button[data-t]"); if (b) run(b.dataset.t).catch((x) => showToast(escapeHtml(x.message), "err")); });
export const headingAct = (kind) => heading(kind);
cm.addKeyMap({ "Ctrl-B": () => wrap("\\textbf{", "}"), "Ctrl-I": () => wrap("\\textit{", "}"),
               "Cmd-B": () => wrap("\\textbf{", "}"), "Cmd-I": () => wrap("\\textit{", "}") });
// .tex を開いているときだけ出す
bus.on("activate", (t) => { $("edtool").classList.toggle("off", !t || modeOf(t.path) !== "stex" || /\.(bib|sty|cls|bst)$/i.test(t.path)); });
