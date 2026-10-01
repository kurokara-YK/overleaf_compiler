// 図と表を楽に入れる。
//   図：画像をエディタか PDF に落とす（または画像を貼り付ける）と、画像のフォルダ（img/ など）に保存して、
//       figure 環境と \label の雛形を、落とした段落の後ろに差し込む。PDF に落としたときは SyncTeX でその場所のソースへ
//   表：Excel・スプレッドシート・Web の表を貼り付けると、booktabs の table 環境にする（CSV のファイルを落としても同じ）。
//       「そのまま貼る」で元の文字に戻せる
// 使うパッケージ（graphicx・booktabs）がプリアンブルに無ければ、足すかを聞く
import { $, api, enc, escapeHtml, showToast, fail, bus } from "./util.mjs";
import { info } from "./state.mjs";
import { cm, active, openTab, activate } from "./editor.mjs";
import { pagesEl, pointIn } from "./pdf.mjs";

const IMG_OK = /\.(png|jpe?g|pdf|eps)$/i;            // LaTeX でそのまま使える
const IMG_CONV = /\.(webp|gif|bmp|avif|svg)$/i;      // PNG にして保存する
const IMG_DIRS = ["img", "images", "image", "figures", "figure", "figs", "fig"];
const isTex = () => active && /\.(tex|ltx)$/i.test(active.path);

// ---- 図 ----
async function imageDir() {
  try {
    const t = await api("/api/tree");
    const dirs = new Set(t.files.filter((f) => f.dir).map((f) => f.path));
    return IMG_DIRS.find((d) => dirs.has(d)) || "img";
  } catch { return "img"; }
}
const stamp = () => { const d = new Date(), z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${z(d.getMonth() + 1)}${z(d.getDate())}-${z(d.getHours())}${z(d.getMinutes())}${z(d.getSeconds())}`; };
// LaTeX でそのまま読める名前（空白や日本語は避ける）
function safeName(name) {
  const m = /^(.*?)(\.[^.]+)?$/.exec(name);
  const stem = (m[1] || "image").normalize("NFKC").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || `image-${stamp()}`;
  return stem + (m[2] || ".png").toLowerCase();
}
async function toPng(file) {
  const img = new Image();
  img.src = URL.createObjectURL(file);
  await img.decode();
  const c = document.createElement("canvas");
  c.width = img.naturalWidth || 800; c.height = img.naturalHeight || 600;
  c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
  URL.revokeObjectURL(img.src);
  return new Promise((r) => c.toBlob(r, "image/png"));
}
async function upload(dir, name, blob) {
  // 同じ名前があれば -2, -3 … を付ける（上書きしない）
  const [stem, ext] = [name.replace(/\.[^.]+$/, ""), name.slice(name.lastIndexOf("."))];
  for (let i = 1; i < 100; i++) {
    const n = i === 1 ? name : `${stem}-${i}${ext}`;
    try { return (await api(`/api/upload?dir=${enc(dir)}&name=${enc(n)}`, { method: "POST", body: await blob.arrayBuffer() })).path; }
    catch (e) { if (e.message !== "EXISTS") throw e; }
  }
  throw new Error("同じ名前のファイルが多すぎる");
}
// 段落の終わり（次の空行・見出し・環境の始まりの手前）の行
function paragraphEnd(doc, line) {
  let l = line;
  while (l < doc.lastLine()) {
    const next = doc.getLine(l + 1);
    if (!next.trim() || /^\s*\\(begin|end|section|subsection|subsubsection|chapter|paragraph|item)\b/.test(next)) break;
    l++;
  }
  return l;
}
function figureCode(path) {
  const label = "fig:" + path.split("/").pop().replace(/\.[^.]+$/, "");
  return ["\\begin{figure}[t]", "  \\centering", `  \\includegraphics[width=\\linewidth]{${path}}`,
          "  \\caption{ここに図の説明}", `  \\label{${label}}`, "\\end{figure}"];
}
// 行 line の段落の後ろに、ブロック（行の配列）を差し込む。placeholder があれば選んだ状態にする
function insertBlock(line, lines, placeholder) {
  const doc = cm.getDoc();
  // プリアンブル（\begin{document} より前）には入れない。本文の始まり（\maketitle の後など）に入れる
  for (let i = 0; i < doc.lineCount(); i++) if (/^\s*\\begin\{document\}/.test(doc.getLine(i))) { if (line < i) line = i; break; }
  const at = paragraphEnd(doc, line);
  const end = doc.getLine(at).length;
  doc.replaceRange("\n\n" + lines.join("\n") + "\n", { line: at, ch: end });
  const start = at + 2;
  if (placeholder) {
    const i = lines.findIndex((l) => l.includes(placeholder));
    if (i >= 0) { const ch = lines[i].indexOf(placeholder); doc.setSelection({ line: start + i, ch }, { line: start + i, ch: ch + placeholder.length }); }
  }
  cm.focus();
  cm.scrollIntoView({ line: start, ch: 0 }, 120);
}
async function addImages(files, line) {
  if (!isTex()) return showToast("図は .tex のファイルを開いているときに入れられる", "", 3000);
  const dir = await imageDir();
  for (const f of files) {
    try {
      let blob = f, name = safeName(f.name || `image-${stamp()}.png`);
      if (IMG_CONV.test(f.name || "") || (!IMG_OK.test(name) && f.type.startsWith("image/"))) {
        blob = await toPng(f); name = name.replace(/\.[^.]+$/, ".png");
      } else if (!IMG_OK.test(name)) { showToast(`${escapeHtml(f.name)} は図にできない（画像・PDF・EPS を落とす）`, "err", 4000); continue; }
      const path = await upload(dir, name, blob);
      insertBlock(line, figureCode(path), "ここに図の説明");
      showToast(`${escapeHtml(path)} に保存して、図を入れた（説明を書く）`, "ok", 4000);
    } catch (e) { fail(e); }
  }
  bus.emit("files");
  ensurePackage("graphicx", /\\usepackage(\[[^\]]*\])?\{[^}]*\bgraphicx?\b/);
}

// ---- 表 ----
function escTex(s) {
  return s.replace(/\\/g, "\\textbackslash{}").replace(/([&%$#_{}])/g, "\\$1").replace(/~/g, "\\textasciitilde{}").replace(/\^/g, "\\textasciicircum{}");
}
const isNum = (s) => /^[-+−]?[\d,]*\.?\d+%?$/.test(s.trim().replace(/\s/g, "")) && s.trim() !== "";
function tableCode(rows, label) {
  const n = Math.max(...rows.map((r) => r.length));
  rows = rows.map((r) => [...r, ...Array(n - r.length).fill("")].map((c) => c.trim()));
  // 見出しを除いて、数ばかりの列は右寄せ
  const body = rows.slice(1);
  const spec = [...Array(n)].map((_, j) => body.length && body.every((r) => !r[j] || isNum(r[j])) && body.some((r) => r[j]) ? "r" : "l").join("");
  const line = (r) => "    " + r.map(escTex).join(" & ") + " \\\\";
  return ["\\begin{table}[t]", "  \\centering", "  \\caption{ここに表の説明}", `  \\label{${label}}`, `  \\begin{tabular}{${spec}}`,
          "    \\toprule", line(rows[0]), "    \\midrule", ...body.map(line), "    \\bottomrule", "  \\end{tabular}", "\\end{table}"];
}
// Excel・スプレッドシートの貼り付け（タブ区切り）。2行2列以上で、列の数がそろっていれば表とみなす
function parseTsv(text) {
  const lines = text.replace(/\r\n?/g, "\n").replace(/\n+$/, "").split("\n");
  if (lines.length < 2 || !lines.every((l) => l.includes("\t"))) return null;
  const rows = lines.map((l) => l.split("\t"));
  const n = rows[0].length;
  return n >= 2 && rows.filter((r) => r.length === n).length >= rows.length * 0.8 ? rows : null;
}
function parseHtmlTable(html) {
  if (!/<table/i.test(html)) return null;
  const t = new DOMParser().parseFromString(html, "text/html").querySelector("table");
  const rows = t ? [...t.rows].map((tr) => [...tr.cells].map((c) => c.innerText ?? c.textContent).map((s) => s.replace(/\s+/g, " ").trim())) : [];
  return rows.length >= 2 && Math.max(...rows.map((r) => r.length)) >= 2 ? rows : null;
}
function parseCsv(text) {
  const rows = [[]];
  let cell = "", q = false;
  const sep = (text.split("\n")[0].match(/;/g) || []).length > (text.split("\n")[0].match(/,/g) || []).length ? ";" : ",";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (ch === '"') q = false; else cell += ch; }
    else if (ch === '"') q = true;
    else if (ch === sep) { rows.at(-1).push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; rows.at(-1).push(cell); cell = ""; rows.push([]); }
    else cell += ch;
  }
  if (cell || rows.at(-1).length) rows.at(-1).push(cell);
  return rows.filter((r) => r.some((c) => c.trim()));
}
function nextTableLabel() {
  const used = new Set((cm.getValue().match(/\\label\{tab:table(\d+)\}/g) || []).map((s) => +s.match(/\d+/)[0]));
  let n = 1; while (used.has(n)) n++;
  return `tab:table${n}`;
}
function insertTable(rows, raw) {
  const doc = cm.getDoc(), line = doc.getCursor().line;
  const before = doc.changeGeneration();
  insertBlock(line, tableCode(rows, nextTableLabel()), "ここに表の説明");
  const t = $("toast");
  showToast(`表（${rows.length} 行 × ${Math.max(...rows.map((r) => r.length))} 列）にした。1行目を見出しにした
    ${raw != null ? ' <button id="tabRaw">そのまま貼る</button>' : ""}`, "ok", 8000);
  if (raw != null) t.querySelector("#tabRaw").onclick = () => {
    while (!doc.isClean(before) && doc.historySize().undo) doc.undo();
    doc.replaceSelection(raw);
    t.classList.remove("open");
  };
  ensurePackage("booktabs", /\\usepackage(\[[^\]]*\])?\{[^}]*\bbooktabs\b/);
}

// ---- パッケージ（プリアンブル）----
async function ensurePackage(name, re) {
  const main = info && info.main;
  if (!main) return;
  let text;
  try { text = (await api(`/api/read?path=${enc(main)}`)).text; } catch { return; }
  const pre = text.split(/\\begin\{document\}/)[0];
  if (re.test(pre) || (name === "graphicx" && /\\documentclass(\[[^\]]*\])?\{(beamer|jsarticle|ltjsarticle|jlreq)\}/.test(pre) && /graphic/.test(pre))) return;
  const t = $("toast");
  showToast(`プリアンブルに <code>\\usepackage{${name}}</code> が無い <button id="pkgAdd">足す</button>`, "", 10000);
  t.querySelector("#pkgAdd").onclick = async () => {
    t.classList.remove("open");
    const back = active;
    try {
      const m = await openTab(main);
      const d = m.doc, n = d.lineCount();
      let at = -1;
      for (let i = 0; i < n; i++) if (/^\s*\\usepackage/.test(d.getLine(i))) at = i;
      for (let i = 0; i < n; i++) if (/^\s*\\usepackage(\[[^\]]*\])?\{hyperref\}/.test(d.getLine(i))) { at = i - 1; break; }   // hyperref は最後に読む
      if (at < 0) for (let i = 0; i < n; i++) if (/\\begin\{document\}/.test(d.getLine(i))) { at = i - 1; break; }
      d.replaceRange(`\\usepackage{${name}}\n`, { line: at + 1, ch: 0 });
      if (back && back !== m) activate(back);
      showToast(`${escapeHtml(main)} に \\usepackage{${name}} を足した`, "ok", 3000);
    } catch (e) { fail(e); }
  };
}

// ---- エディタ：落とす・貼り付ける ----
cm.on("drop", (_cm, e) => {
  const files = [...(e.dataTransfer?.files || [])];
  if (!files.length) return;
  e.preventDefault();
  const pos = cm.coordsChar({ left: e.clientX, top: e.clientY }, "window");
  const csv = files.filter((f) => /\.(csv|tsv)$/i.test(f.name));
  const imgs = files.filter((f) => !/\.(csv|tsv)$/i.test(f.name));
  if (csv.length && isTex()) {
    cm.setCursor(pos);
    csv.forEach(async (f) => { const t = await f.text(); const rows = /\.tsv$/i.test(f.name) ? parseTsv(t) || [] : parseCsv(t); if (rows.length) insertTable(rows); });
  }
  if (imgs.length) addImages(imgs, pos.line);
});
cm.on("paste", (_cm, e) => {
  if (!isTex()) return;
  const cd = e.clipboardData; if (!cd) return;
  const text = cd.getData("text/plain"), html = cd.getData("text/html");
  const files = [...cd.files].filter((f) => f.type.startsWith("image/"));
  if (files.length && !text) {   // スクリーンショットなどの画像
    e.preventDefault();
    return addImages(files.map((f) => new File([f], `image-${stamp()}.png`, { type: f.type })), cm.getCursor().line);
  }
  const rows = parseTsv(text) || (html && parseHtmlTable(html));
  if (!rows) return;
  e.preventDefault();
  insertTable(rows, text);
});

// ---- PDF に画像を落とす：その場所のソースの段落の後ろに入れる ----
pagesEl.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
pagesEl.addEventListener("drop", async (e) => {
  const files = [...(e.dataTransfer?.files || [])];
  const pg = e.target.closest(".page");
  if (!files.length || !pg) return;
  e.preventDefault();
  try {
    const [page, x, y] = pointIn(pg, e.clientX, e.clientY);
    const r = await api(`/api/goto_source?page=${page}&x=${x}&y=${y}`);
    await openTab(r.path, r.line);
    addImages(files, r.line - 1);
  } catch (er) { showToast(`落とした場所のソースが分からない（本文の上に落とす）: ${escapeHtml(er.message)}`, "err", 5000); }
});
