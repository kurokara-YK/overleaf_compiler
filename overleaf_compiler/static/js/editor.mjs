// エディタ（CodeMirror 5）。タブ・自動保存・外での変更の取り込み・Markdown のプレビュー
import { marked } from "/static/marked/marked.esm.js";
import { $, api, post, enc, escapeHtml, basename, dirname, store, showToast, bus, url } from "./util.mjs";
import { info } from "./state.mjs";

export const cm = CodeMirror($("cmhost"), { mode: "stex", lineNumbers: true, lineWrapping: true, styleActiveLine: true,
  theme: "discord", indentUnit: 2, tabSize: 2 });
const EMPTY = () => CodeMirror.Doc("", "stex");
cm.swapDoc(EMPTY());
export const tabs = new Map();   // 原稿のフォルダからの相対パス → { path, doc, saved, mtime, timer, saving, conflict, preview }
export let active = null;        // いま表に出ているタブ
export let lastSave = 0;         // ブラウザから最後に保存した時刻（保存の直後は PDF の更新を細かく確かめる）
let quiet = false;               // 外の変更で文面を置き換えている間は、自動保存しない
const AUTOSAVE_MS = 700;
const isDirty = (t) => t.doc.getValue() !== t.saved;
export const dirty = () => [...tabs.values()].some(isDirty);
export const modeOf = (p) => /\.md$/i.test(p) ? "markdown" : /\.(tex|sty|cls|bib|bst|bbx|cbx|cfg|def|clo|ltx)$/i.test(p) ? "stex" : null;

export async function openTab(path, line) {
  let t = tabs.get(path);
  if (!t) {
    const r = await api(`/api/read?path=${enc(path)}`);
    t = tabs.get(r.path);
    if (!t) {
      t = { path: r.path, doc: CodeMirror.Doc(r.text, modeOf(r.path)), saved: r.text, mtime: r.mtime,
            timer: null, saving: false, conflict: null, preview: false };
      t.doc.on("change", () => { if (!quiet) { scheduleSave(t); renderTabs(); bus.emit("edit"); } });
      tabs.set(r.path, t);
    }
  }
  activate(t);
  if (line) jumpTo(line);
  return t;
}
export function activate(t) {
  active = t;
  cm.swapDoc(t ? t.doc : EMPTY());
  showBody(t && t.preview ? "md" : "cm");
  renderTabs(); showConflict(); updateCursor();
  bus.emit("activate", t);   // ツリー・アウトライン・コメントの印・変更履歴が合わせる
}
export function renderTabs() {
  const bar = $("tabs");
  bar.replaceChildren(...[...tabs.values()].map((t) => {
    const d = document.createElement("div");
    d.className = "tab" + (t === active ? " active" : "") + (isDirty(t) ? " dirty" : "");
    d.title = t.path;
    d.innerHTML = `<span class="dot"></span><span>${escapeHtml(basename(t.path))}</span><button class="x" title="閉じる">×</button>`;
    d.onclick = (e) => { if (e.target.closest(".x")) closeTab(t); else activate(t); };
    return d;
  }));
}
async function closeTab(t) {
  if (isDirty(t)) await save(t);
  tabs.delete(t.path);
  if (active === t) activate([...tabs.values()].pop() || null); else renderTabs();
}
export function closeAllTabs() { tabs.clear(); activate(null); }
// 消したファイルのタブを閉じる（保存はしない）。表のタブが消えたら、残りの最後のタブを出す
export function dropTabs(match) {
  for (const k of [...tabs.keys()]) if (match(k)) { tabs.delete(k); if (active && active.path === k) active = null; }
  if (!active) activate([...tabs.values()].pop() || null); else renderTabs();
}

function scheduleSave(t) { clearTimeout(t.timer); t.timer = setTimeout(() => save(t), AUTOSAVE_MS); saveState("未保存の変更…"); }
// ブラウザ → ローカルのファイル。開いたとき（前に保存したとき）の更新時刻と違えば、書かずに選ばせる
export async function save(t) {
  clearTimeout(t.timer);
  if (!tabs.has(t.path) || !isDirty(t) || t.conflict) return;
  if (t.saving) { t.timer = setTimeout(() => save(t), AUTOSAVE_MS); return; }
  t.saving = true;
  const sent = t.doc.getValue();
  saveState("保存中…");
  try {
    const r = await post("/api/write", { path: t.path, text: sent, mtime: t.mtime });
    if (r.conflict) { t.conflict = r; showConflict(); saveState("外でも変更された", true); return; }
    t.mtime = r.mtime; t.saved = sent; lastSave = Date.now();
    saveState("保存した");
  } catch (e) { saveState(e.message, true); }
  finally {
    t.saving = false; renderTabs();
    if (tabs.has(t.path) && isDirty(t) && !t.conflict) scheduleSave(t);
  }
}
export async function saveAll() { await Promise.all([...tabs.values()].filter(isDirty).map(save)); }
function saveState(text, err = false) { const s = $("saveState"); s.textContent = text; s.style.color = err ? "var(--err)" : ""; }
function setDocText(t, text) {
  const c = t.doc.getCursor(), s = t === active ? cm.getScrollInfo() : null;
  quiet = true; t.doc.setValue(text); quiet = false;
  t.doc.setCursor(c);
  if (s) cm.scrollTo(s.left, s.top);
  if (t === active && t.preview) renderMd();
  renderTabs(); if (t === active) bus.emit("edit");
}
function showConflict() {
  const c = $("conflict");
  if (active && active.conflict) {
    c.querySelector("span").textContent = `${active.path} は外（VS Code など）でも変更された。どちらを残すか選ぶ`;
    c.classList.add("open");
  } else c.classList.remove("open");
}
$("takeOuter").onclick = () => {
  const t = active, r = t.conflict;
  t.conflict = null; setDocText(t, r.text); t.saved = r.text; t.mtime = r.mtime;
  showConflict(); saveState("外の内容を読み込んだ");
};
$("keepMine").onclick = () => { const t = active; t.mtime = t.conflict.mtime; t.conflict = null; showConflict(); save(t); };
// ローカル（VS Code・Claude Code）での変更を取り込む。未保存の入力が無ければそのまま置き換える
export async function pullOuter(mtimes) {
  for (const [p, m] of Object.entries(mtimes || {})) {
    const t = tabs.get(p);
    if (!t || t.saving || t.conflict || m === t.mtime) continue;
    const r = await api(`/api/read?path=${enc(p)}`);
    if (!tabs.has(p) || r.mtime === t.mtime) continue;
    if (isDirty(t)) { t.conflict = { text: r.text, mtime: r.mtime }; showConflict(); }
    else { setDocText(t, r.text); t.saved = r.text; t.mtime = r.mtime; saveState(`${p} を外の変更で更新した`); }
  }
}
export function jumpTo(line, ch = 0, len = 0) {
  showBody("cm");
  if (active) active.preview = false;
  const l = Math.max(0, Math.min(cm.lastLine(), line - 1));
  cm.focus(); cm.setCursor({ line: l, ch });
  cm.scrollIntoView({ line: l, ch }, Math.round(cm.getScrollInfo().clientHeight / 2));
  const h = cm.addLineClass(l, "background", "cm-jump");
  setTimeout(() => cm.removeLineClass(h, "background", "cm-jump"), 1600);
  if (len) { const mk = cm.markText({ line: l, ch }, { line: l, ch: ch + len }, { className: "cm-found" }); setTimeout(() => mk.clear(), 2500); }
}
function updateCursor() { $("cursorPos").textContent = active ? `${cm.getCursor().line + 1} 行` : ""; bus.emit("cursor"); }
cm.on("cursorActivity", updateCursor);
$("cmhost").style.setProperty("--code-size", `${store.get("oc.editorFontSize", 12)}px`);
export function fontSize(d) {
  const v = Math.max(9, Math.min(28, parseInt(store.get("oc.editorFontSize", 12)) + d));
  store.set("oc.editorFontSize", v); $("cmhost").style.setProperty("--code-size", `${v}px`); cm.refresh();
}
$("fsDown").onclick = () => fontSize(-1);
$("fsUp").onclick = () => fontSize(1);
$("vscode").onclick = () => { if (active) location.href = `vscode://file${encodeURI(info.vscode_dir + "/" + active.path)}:${cm.getCursor().line + 1}`; };

// エディタの場所に出すもの：エディタ・Markdown のプレビュー・履歴の差分
export function showBody(which) {
  $("mdview").classList.toggle("on", which === "md");
  $("diffview").classList.toggle("on", which === "diff");
  if (which === "cm") setTimeout(() => cm.refresh(), 0);
}
// ---- Markdown のプレビュー（VS Code と同じく Ctrl+Shift+V）----
function renderMd() {
  const body = $("mdbody");
  body.innerHTML = marked.parse(active.doc.getValue());
  const dir = dirname(active.path);
  body.querySelectorAll("img").forEach((img) => {
    const src = img.getAttribute("src") || "";
    if (!/^(https?:|data:|\/)/.test(src)) img.src = url(`/raw?path=${enc((dir ? dir + "/" : "") + src)}`);
  });
  body.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener"; });
}
export function toggleMd() {
  if (!active || !/\.md$/i.test(active.path)) return showToast("Markdown のファイル（.md）を開いているときに使える", "", 3000);
  active.preview = !active.preview;
  if (active.preview) renderMd();
  showBody(active.preview ? "md" : "cm");
}
