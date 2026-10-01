// 一覧画面（data のフォルダをたどる）と、上のパンくず（data からの相対パス）
import { $, api, post, enc, escapeHtml, basename, dirname, ago, confirmBox, ask, modal, fail, bus, tab, setTabProject, pushUrl } from "./util.mjs";
import { openMenu } from "./menu.mjs";
import { info } from "./state.mjs";
import { saveAll, dirty } from "./editor.mjs";

// 一覧で開いているフォルダ。null はまだ選んでいない（起動したときのフォルダを開く）。"" は data の直下。
// URL の ?dir= に書くので、ブラウザの戻るで前のフォルダへ戻れる
let browsePath = new URLSearchParams(location.search).get("dir"), entries = [];
let found = null;      // 絞り込みの結果（下の階層まで探したもの）。null なら絞り込んでいない
let menuItem = null;   // ⋮ を押した項目
export function setBrowsePath(p) { browsePath = p; }

// ---- パンくず ----
function crumbHtml(parts, lastBold) {
  const out = [`<a data-go="">data</a>`];
  parts.forEach((p, i) => {
    const path = parts.slice(0, i + 1).join("/");
    out.push(i === parts.length - 1 && lastBold ? `<b>${escapeHtml(p)}</b>` : `<a data-go="${escapeHtml(path)}">${escapeHtml(p)}</a>`);
  });
  return out.join('<span class="sep">/</span>');
}
export function setCrumb() {
  if (info && info.main) $("crumb").innerHTML = crumbHtml(info.rel.split("/"), true);
  else $("crumb").innerHTML = crumbHtml(browsePath ? browsePath.split("/") : [], true);
}
$("crumb").addEventListener("click", (e) => { const a = e.target.closest("a[data-go]"); if (a) goHome(a.dataset.go); });
$("brand").onclick = () => goHome(info && info.main ? dirname(dirname(info.rel)) : "");

// 一覧へ戻る。原稿を開いていれば閉じる（ほかのタブが見ていなければ、サーバが組版を止める）
export async function goHome(path) {
  await saveAll();
  if (dirty() && !(await confirmBox("保存できていない変更がある", "破棄して一覧へ戻る？", "戻る", true))) return;
  try { if (info && info.main) await post("/api/close"); } catch (e) { fail(e); }
  setTabProject(null, true, path);
  browsePath = path;
  await bus.emit("reopen");
}

// ---- 一覧 ----
// 原稿を開いていないときの画面。前に見ていたフォルダか、起動したときのフォルダを出す
export function showStartHome() {
  $("q").value = "";
  return showHome(browsePath ?? info.start ?? "", false);
}
export const showHomeAt = (path) => showHome(path, false);
function msg(text, cls = "") { const m = $("homeMsg"); m.className = `msgline ${cls}`; m.textContent = text; }
async function showHome(path, push = true) {
  if (push && (path || "") !== (browsePath || "")) pushUrl({ dir: path });
  document.body.className = "home";
  document.title = "overleaf-compiler";
  browsePath = path || "";
  $("q").value = ""; found = null;
  setCrumb();
  const parts = browsePath ? browsePath.split("/") : [];
  $("homeTitle").textContent = parts.length ? parts[parts.length - 1] : "data";
  $("dropWhere").textContent = parts.length ? `「${parts[parts.length - 1]}」の中` : "data の直下（新しいワークスペース）";
  try {
    const r = await api(`/api/browse?path=${enc(browsePath)}`);
    entries = r.entries;
    const nf = entries.filter((e) => e.kind === "folder").length, np = entries.length - nf;
    $("homeSub").textContent = `data${browsePath ? "/" + browsePath : ""}　フォルダ ${nf}・原稿 ${np}`;
    renderList();
  } catch (e) { msg(e.message, "err"); }
}
function renderList() {
  const q = $("q").value.trim();
  const items = q && found ? found : q ? [] : entries;
  const list = $("list");
  list.replaceChildren();
  if (!items.length) {
    list.innerHTML = `<div class="empty">${q ? (found ? "一致するものが無い" : "探している…") : "空のフォルダ。上に zip をドロップして取り込むか、フォルダを作る"}</div>`;
    return;
  }
  const dots = '<button class="dots" title="メニュー（ダウンロード・名前の変更・削除）">⋮</button>';
  // 絞り込みの結果は、どのフォルダにあるかも出す
  const where = (f) => q && f.where != null ? `<div class="where">data${f.where ? "/" + escapeHtml(f.where) : ""}</div>` : "";
  for (const f of items) {
    const d = document.createElement("div");
    if (f.kind === "folder") {
      d.className = "card";
      d.innerHTML = `<span class="ic">📁</span><div class="t"><div class="n">${escapeHtml(f.name)}</div>${where(f)}
        <div class="d">原稿 ${f.count} 件</div></div><span class="when">${ago(f.mtime)}</span>${dots}`;
      d.onclick = (e) => { if (!itemMenu(e, f)) showHome(f.dir); };
    } else {
      d.className = "card" + (f.default ? "" : " nodefault");
      let body = "";
      if (f.mains.length > 1) {
        body = `<div class="mains">${f.mains.map((m) => `<button class="main" data-tex="${escapeHtml(m.tex)}">${escapeHtml(m.name)}</button>`).join("")}</div>
          <div class="kbd">主文書が ${f.mains.length} つある。開くものを選ぶ</div>`;
      } else if (!f.mains.length && f.not_tex.length) {
        body = `<div class="d">.tex が無い。${f.not_tex.map((x) => escapeHtml(x.name)).join("、")} の中身は LaTeX の文書</div>
          <div class="mains">${f.not_tex.map((x) => `<button class="rename" data-file="${escapeHtml(x.file)}" data-name="${escapeHtml(x.name)}">
            ${escapeHtml(x.name.replace(/\.[^.]+$/, ".tex"))} に名前を変えて開く</button>`).join("")}</div>`;
      }
      const one = f.mains.length === 1 ? f.mains[0] : null;
      d.innerHTML = `<span class="ic">📄</span><div class="t"><div class="n">${escapeHtml(f.name)}</div>${where(f)}
          ${one ? `<div class="d">${escapeHtml(one.name)}</div>` : ""}${body}</div>
        ${f.mains.length ? `<span class="badge">${escapeHtml(f.mains[0].engine)}</span>` : ""}
        <span class="when">${ago(f.mtime)}</span>${dots}`;
      d.onclick = (e) => {
        if (itemMenu(e, f)) return;
        const main = e.target.closest("button.main"), ren = e.target.closest("button.rename");
        if (main) return openProject(main.dataset.tex);
        if (ren) return renameAndOpen(ren.dataset.file, ren.dataset.name);
        if (f.default) return openProject(f.default);
        d.classList.remove("pulse"); void d.offsetWidth; d.classList.add("pulse");
      };
    }
    list.appendChild(d);
  }
}
// ---- 絞り込み：入力が止まったら、開いているフォルダの下の階層をすべて探す（サーバの search_tree）----
let searchTimer = 0, searchSeq = 0;
function search() {
  clearTimeout(searchTimer);
  const q = $("q").value.trim();
  if (!q) { found = null; renderList(); return; }
  searchTimer = setTimeout(async () => {
    const my = ++searchSeq;
    try {
      const r = await api(`/api/browse?path=${enc(browsePath)}&q=${enc(q)}`);
      if (my === searchSeq) { found = r.entries; renderList(); }
    } catch (e) { msg(e.message, "err"); }
  }, 200);
}
$("q").addEventListener("input", () => { found = null; renderList(); search(); });
// 今の画面（絞り込んでいれば、その結果）を読み直す
export async function refresh() {
  if (document.body.className !== "home") return;
  const q = $("q").value, y = $("home").scrollTop;
  await showHome(browsePath, false);
  $("home").scrollTop = y;
  if (q) { $("q").value = q; search(); }
}
// ヘッダ右端の ⟳ と、ウィンドウに戻ってきたとき（外でダウンロード・展開・削除したものを出す）
$("reloadBtn").onclick = async () => {
  $("reloadBtn").classList.add("spin");
  try { await refresh(); msg("読み直した", "ok"); } finally { $("reloadBtn").classList.remove("spin"); }
};
let lastAuto = 0;
function autoRefresh() {
  if (document.visibilityState !== "visible" || $("modalBack").classList.contains("open")) return;
  if (Date.now() - lastAuto < 1500) return;   // focus と visibilitychange が続けて来ても1回だけ
  lastAuto = Date.now();
  refresh();
}
addEventListener("focus", autoRefresh);
document.addEventListener("visibilitychange", autoRefresh);

// ---- 項目の ⋮（ダウンロード・名前の変更・削除）----
function itemMenu(e, f) {
  if (!e.target.closest(".dots")) return false;
  e.stopPropagation();
  menuItem = f;
  $("mHomeZipNote").textContent = f.kind === "project" ? "Overleaf 用の .zip" : ".zip";
  const r = e.target.getBoundingClientRect();
  openMenu("mHomeItem", r.left - 180, r.bottom + 2);
  return true;
}
export async function homeItemAct(v) {
  const f = menuItem;
  if (!f) return;
  if (v === "download") { location.href = `/api/item_zip?path=${enc(f.dir)}`; return; }
  if (v === "rename") {
    const name = await ask("名前を変更", `「${escapeHtml(f.name)}」の新しい名前（変更履歴は引き継ぐ）`, f.name);
    if (!name || name === f.name) return;
    try { await post("/api/item_rename", { path: f.dir, name }); await refresh(); msg(`「${name}」に名前を変えた`, "ok"); }
    catch (e) { msg(e.message, "err"); }
  } else if (v === "delete") {
    if (!(await confirmBox("削除", `「${escapeHtml(f.name)}」をごみ箱へ移す？<br>
        <span class="kbd">ファイルマネージャのごみ箱から戻せる。変更履歴は残る</span>`, "ごみ箱へ移す", true))) return;
    try { await post("/api/item_delete", { path: f.dir }); await refresh(); msg(`「${f.name}」をごみ箱へ移した`, "ok"); }
    catch (e) { msg(e.message, "err"); }
  }
}
// このタブで原稿を開く（ほかのタブの原稿はそのまま）
async function openProject(tex) {
  try {
    const r = await post("/api/open", { tex, t: tab.t });
    setTabProject(r.rel);
    await bus.emit("reopen");
  } catch (e) { msg(e.message, "err"); }
}
async function renameAndOpen(file, name) {
  const to = name.replace(/\.[^.]+$/, ".tex");
  if (!(await confirmBox("名前を変えて開く", `${escapeHtml(name)} を <b>${escapeHtml(to)}</b> に名前を変えて開く？<br>
      <span class="kbd">Overleaf でも主文書は .tex である必要がある</span>`, "名前を変えて開く"))) return;
  try { const r = await post("/api/rename_txt", { file }); await openProject(r.tex); } catch (e) { msg(e.message, "err"); }
}
$("newBtn").onclick = async () => {
  const name = $("newName").value.trim();
  if (!name) return;
  try { await post("/api/mkdir", { path: browsePath, name }); $("newName").value = ""; await showHome(browsePath); msg(`「${name}」を作った`, "ok"); }
  catch (e) { msg(e.message, "err"); }
};
$("newName").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) $("newBtn").click(); });
const drop = $("drop");
drop.onclick = () => openPicker();
$("zipInput").onchange = () => { const f = $("zipInput").files[0]; $("zipInput").value = ""; if (f) importZip(f); };
for (const t of ["dragenter", "dragover"]) drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); });
for (const t of ["dragleave", "drop"]) drop.addEventListener(t, () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) importZip(f); });
// ---- 取り込むものを選ぶ窓。最初はダウンロードを開き、zip か展開済みのフォルダを選ぶ（サーバの fs_list・fs_import）----
async function openPicker() {
  let sel = null;
  $("modal").classList.add("wide");
  const done = modal("取り込むものを選ぶ", `<div class="picker">
      <div class="pk-bar"><button data-go="dl">⤓ ダウンロード</button><button data-go="home">⌂ ホーム</button>
        <button data-go="up">↑ 上へ</button><span class="pk-path"></span></div>
      <div class="pk-list"><div class="empty">読み込み中…</div></div>
      <div class="pk-hint">zip（Overleaf の Download as source）か、展開済みの原稿のフォルダを選ぶ。ダブルクリックでフォルダの中へ</div>
      <a class="pk-native">ブラウザの窓で選ぶ…</a></div>`,
    [{ label: "やめる", value: null }, { label: "取り込む", value: "go", cls: "primary" }]);
  const body = $("mBody"), list = body.querySelector(".pk-list"), ok = [...$("mFoot").children].pop();
  let cur = null;
  const choose = (e) => { sel = e; ok.disabled = !e; list.querySelectorAll(".pk-it").forEach((x) => x.classList.toggle("sel", x.dataset.path === e?.path)); };
  async function load(dir) {
    try { cur = await api(`/api/fs_list?dir=${enc(dir)}`); } catch (e) { list.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`; return; }
    body.querySelector(".pk-path").textContent = cur.label;
    body.querySelector('[data-go="up"]').disabled = !cur.parent;
    choose(null);
    const kb = (n) => n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
    list.innerHTML = cur.entries.map((e, i) => `<div class="pk-it" data-i="${i}" data-path="${escapeHtml(e.path)}">
        <span class="ic">${e.kind === "zip" ? "📦" : e.project ? "📄" : "📁"}</span>
        <div class="t"><div class="n">${escapeHtml(e.name)}</div>
          <div class="d">${e.kind === "zip" ? `zip・${kb(e.size)}` : e.project ? `原稿（${escapeHtml(e.main)}）` : "フォルダ"}</div></div>
        <span class="when">${ago(e.mtime)}</span></div>`).join("") || '<div class="empty">zip もフォルダも無い</div>';
  }
  list.onclick = (ev) => { const it = ev.target.closest(".pk-it"); if (it) choose(cur.entries[+it.dataset.i]); };
  list.ondblclick = (ev) => {
    const it = ev.target.closest(".pk-it"); if (!it) return;
    const e = cur.entries[+it.dataset.i];
    if (e.kind === "dir" && !e.project) load(e.path); else { choose(e); ok.click(); }
  };
  body.querySelector(".pk-bar").onclick = (ev) => {
    const g = ev.target.closest("button")?.dataset.go;
    if (g === "dl") load(cur?.downloads || ""); else if (g === "home") load(cur?.home || "~"); else if (g === "up" && cur?.parent) load(cur.parent);
  };
  body.querySelector(".pk-native").onclick = () => { [...$("mFoot").children][0].click(); $("zipInput").click(); };
  ok.disabled = true;
  load("");
  const v = await done;
  $("modal").classList.remove("wide");
  if (v === "go" && sel) importPath(sel);
}
async function importPath(e) {
  msg(`${e.name} を取り込み中…`);
  try {
    const r = await post("/api/fs_import", { src: e.path, path: browsePath });
    await showHome(browsePath);
    msg(`「${basename(r.dir)}」に取り込んだ（主文書 ${r.mains} 件）`, "ok");
  } catch (er) { msg(er.message, "err"); }
}
async function importZip(f) {
  if (!f.name.toLowerCase().endsWith(".zip")) return msg("zip ではない", "err");
  msg(`${f.name} を展開中…`);
  try {
    const r = await api(`/api/import?path=${enc(browsePath)}&name=${enc(f.name)}`, { method: "POST", body: await f.arrayBuffer() });
    await showHome(browsePath);
    msg(`「${basename(r.dir)}」に展開した（主文書 ${r.mains} 件）`, "ok");
  } catch (e) { msg(e.message, "err"); }
}
