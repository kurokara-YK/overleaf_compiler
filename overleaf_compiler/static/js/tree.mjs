// 左のパネルのファイルツリー（Overleaf と同じ）。新規ファイル・新規フォルダ・アップロードと、各ファイルの ⋮ の操作
import { $, api, post, enc, escapeHtml, dirname, store, ask, confirmBox, showToast, fail, bus, url } from "./util.mjs";
import { info } from "./state.mjs";
import { tabs, active, openTab, save, renderTabs, dropTabs } from "./editor.mjs";
import { openMenu } from "./menu.mjs";
import { showHistory } from "./history.mjs";

let treeFiles = [], itemPath = null;
const openDirs = new Set(JSON.parse(store.get("oc.openDirs", '["chapter","chapters","sections","figures","img","images"]')));
export async function loadTree() { try { treeFiles = (await api("/api/tree")).files; renderTree(); } catch (e) { fail(e); } }
function fileIcon(f) {
  if (f.dir) return openDirs.has(f.path) ? "📂" : "📁";
  if (/\.(png|jpe?g|gif|svg|eps|pdf)$/i.test(f.path)) return "🖼";
  if (/\.bib$/i.test(f.path)) return "📚";
  if (/\.md$/i.test(f.path)) return "📝";
  if (/\.(cls|sty|bst|bbx|cbx)$|latexmkrc$/i.test(f.path)) return "⚙";
  return f.editable ? "📄" : "📦";
}
function renderTree() {
  const list = $("treeList");
  list.replaceChildren();
  for (const f of treeFiles) {
    const parts = f.path.split("/");
    let shown = true;
    for (let i = 1; i < parts.length; i++) if (!openDirs.has(parts.slice(0, i).join("/"))) { shown = false; break; }
    if (!shown) continue;
    const depth = parts.length - 1;
    const d = document.createElement("div");
    d.className = "titem" + (f.path === info.main ? " main" : "");
    d.style.paddingLeft = `${4 + depth * 16}px`;
    d.dataset.path = f.path; d.dataset.dir = f.dir ? "1" : "";
    d.title = f.path + (f.path === info.main ? "（主文書）" : "");
    const guides = Array.from({ length: depth }, (_, i) => `<span class="guide" style="left:${11 + i * 16}px"></span>`).join("");
    d.innerHTML = `${guides}<span class="chev">${f.dir ? (openDirs.has(f.path) ? "▾" : "▸") : ""}</span>
      <span class="fi">${fileIcon(f)}</span><span class="tn">${escapeHtml(parts[parts.length - 1])}</span>
      <button class="dots" title="メニュー">⋮</button>`;
    d.onclick = (e) => {
      if (e.target.closest(".dots")) {
        e.stopPropagation(); itemPath = f.path;
        const r = e.target.getBoundingClientRect(); openMenu("mItem", r.left, r.bottom + 2); return;
      }
      if (f.dir) {
        openDirs.has(f.path) ? openDirs.delete(f.path) : openDirs.add(f.path);
        store.set("oc.openDirs", JSON.stringify([...openDirs])); renderTree();
      } else if (f.editable) openTab(f.path).catch(fail);
      else window.open(url(`/raw?path=${enc(f.path)}`), "_blank");   // 画像などは別のタブで見る
    };
    list.appendChild(d);
  }
  markTree();
}
export function markTree() { for (const el of document.querySelectorAll(".titem")) el.classList.toggle("active", !!active && el.dataset.path === active.path); }
// 新しく作る場所：開いているファイルのフォルダ
const hereDir = () => (active ? dirname(active.path) : "");
export async function newFile() {
  const d = hereDir();
  const name = await ask("新規ファイル", "ファイル名（フォルダも書ける。例: chapter/09_付録.tex）", d ? `${d}/` : "");
  if (!name || name.endsWith("/")) return;
  try { const r = await post("/api/newfile", { path: name }); await loadTree(); await openTab(r.path); } catch (e) { fail(e); }
}
export async function newFolder() {
  const d = hereDir();
  const name = await ask("新規フォルダ", "フォルダ名", d ? `${d}/` : "");
  if (!name || name.endsWith("/")) return;
  try { const r = await post("/api/newfolder", { path: name }); openDirs.add(r.path); await loadTree(); } catch (e) { fail(e); }
}
async function uploadFiles(files, dir) {
  for (const f of files) {
    const url = (ow) => `/api/upload?dir=${enc(dir)}&name=${enc(f.name)}${ow ? "&overwrite=1" : ""}`;
    try { await api(url(false), { method: "POST", body: await f.arrayBuffer() }); }
    catch (e) {
      if (e.message !== "EXISTS") { fail(e); continue; }
      if (!(await confirmBox("同じ名前のファイルがある", `${escapeHtml((dir ? dir + "/" : "") + f.name)} を上書きする？<br><span class="kbd">前の中身は変更履歴に残る</span>`, "上書き", true))) continue;
      try { await api(url(true), { method: "POST", body: await f.arrayBuffer() }); } catch (e2) { fail(e2); continue; }
    }
    showToast(`${escapeHtml(f.name)} をアップロードした`, "ok", 2500);
  }
  if (dir) openDirs.add(dir);
  await loadTree();
}
$("tNewFile").onclick = newFile; $("tNewFolder").onclick = newFolder;
$("tUpload").onclick = () => { $("fileInput").dataset.dir = hereDir(); $("fileInput").click(); };
$("fileInput").onchange = () => { const fs = [...$("fileInput").files]; $("fileInput").value = ""; if (fs.length) uploadFiles(fs, $("fileInput").dataset.dir || ""); };
// ツリーにファイルを落とすとアップロード（フォルダの上ならその中へ）
const tl = $("treeList");
tl.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); tl.classList.add("dropping"); } });
tl.addEventListener("dragleave", () => tl.classList.remove("dropping"));
tl.addEventListener("drop", (e) => {
  e.preventDefault(); tl.classList.remove("dropping");
  const it = e.target.closest(".titem");
  const dir = it ? (it.dataset.dir ? it.dataset.path : dirname(it.dataset.path)) : "";
  uploadFiles([...e.dataTransfer.files], dir);
});
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); }
  catch {   // クリップボードの API が使えないとき
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta);
    ta.select(); document.execCommand("copy"); ta.remove();
  }
  showToast(`コピーした：${escapeHtml(text)}`, "ok", 2500);
}
export async function itemAct(a) {
  const p = itemPath;
  if (!p) return;
  if (a === "download") return window.open(url(`/raw?path=${enc(p)}&download=1`), "_blank");
  if (a === "history") return showHistory("path:" + p);
  if (a.startsWith("copy")) {   // VS Code の「パスのコピー」「相対パスのコピー」と同じ
    const proj = dirname(info.rel || "");
    const text = a === "copyRel" ? p : a === "copyData" ? `data/${proj ? proj + "/" : ""}${p}` : `${info.vscode_dir}/${p}`;
    return copyText(text);
  }
  if (a === "rename") {
    const to = await ask("名前を変更", "新しい名前（フォルダも変えられる）", p);
    if (!to || to === p) return;
    try {
      const t = tabs.get(p);
      if (t) { await save(t); tabs.delete(p); }
      const r = await post("/api/rename", { from: p, to });
      await loadTree();
      if (t) await openTab(r.path); else renderTabs();
    } catch (e) { fail(e); }
  }
  if (a === "delete") {
    const f = treeFiles.find((x) => x.path === p);
    if (!(await confirmBox("削除", `<b>${escapeHtml(p)}</b>${f && f.dir ? " とその中のファイル" : ""} を消す？<br>
        <span class="kbd">中身は変更履歴に残るので、履歴から戻せる</span>`, "削除", true))) return;
    try {
      await post("/api/delete", { path: p });
      dropTabs((k) => k === p || k.startsWith(p + "/"));
      await loadTree(); showToast(`${escapeHtml(p)} を消した（変更履歴から戻せる）`, "ok");
    } catch (e) { fail(e); }
  }
}
bus.on("activate", markTree);
bus.on("files", loadTree);
