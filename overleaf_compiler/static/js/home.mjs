// 一覧画面（data のフォルダをたどる）と、上のパンくず（data からの相対パス）
import { $, api, post, enc, escapeHtml, basename, dirname, ago, confirmBox, fail, bus } from "./util.mjs";
import { info } from "./state.mjs";
import { saveAll, dirty } from "./editor.mjs";

// 一覧で開いているフォルダ。null はまだ選んでいない（起動したときのフォルダを開く）。"" は data の直下
let browsePath = null, entries = [];

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

// 一覧へ戻る。原稿を開いていれば閉じる（組版を止める）
export async function goHome(path) {
  await saveAll();
  if (dirty() && !(await confirmBox("保存できていない変更がある", "破棄して一覧へ戻る？", "戻る", true))) return;
  try { if (info && info.main) await post("/api/close"); } catch (e) { fail(e); }
  browsePath = path;
  await bus.emit("reopen");
}

// ---- 一覧 ----
// 原稿を開いていないときの画面。前に見ていたフォルダか、起動したときのフォルダを出す
export function showStartHome() {
  $("q").value = "";
  return showHome(browsePath ?? info.start ?? "");
}
function msg(text, cls = "") { const m = $("homeMsg"); m.className = `msgline ${cls}`; m.textContent = text; }
async function showHome(path) {
  document.body.className = "home";
  document.title = "overleaf-compiler";
  browsePath = path || "";
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
  const q = $("q").value.trim().toLowerCase();
  const items = entries.filter((f) => !q || f.name.toLowerCase().includes(q) || f.mains.some((m) => m.name.toLowerCase().includes(q)));
  const list = $("list");
  list.replaceChildren();
  if (!items.length) {
    list.innerHTML = `<div class="empty">${entries.length ? "一致するものが無い" : "空のフォルダ。上に zip をドロップして取り込むか、フォルダを作る"}</div>`;
    return;
  }
  for (const f of items) {
    const d = document.createElement("div");
    if (f.kind === "folder") {
      d.className = "card";
      d.innerHTML = `<span class="ic">📁</span><div class="t"><div class="n">${escapeHtml(f.name)}</div>
        <div class="d">原稿 ${f.count} 件</div></div><span class="when">${ago(f.mtime)}</span>`;
      d.onclick = () => showHome(f.dir);
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
      d.innerHTML = `<span class="ic">📄</span><div class="t"><div class="n">${escapeHtml(f.name)}</div>
          ${one ? `<div class="d">${escapeHtml(one.name)}</div>` : ""}${body}</div>
        ${f.mains.length ? `<span class="badge">${escapeHtml(f.mains[0].engine)}</span>` : ""}
        <span class="when">${ago(f.mtime)}</span>`;
      d.onclick = (e) => {
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
$("q").addEventListener("input", renderList);
async function openProject(tex) {
  try { await post("/api/open", { tex }); await bus.emit("reopen"); } catch (e) { msg(e.message, "err"); }
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
drop.onclick = () => $("zipInput").click();
$("zipInput").onchange = () => { const f = $("zipInput").files[0]; $("zipInput").value = ""; if (f) importZip(f); };
for (const t of ["dragenter", "dragover"]) drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); });
for (const t of ["dragleave", "drop"]) drop.addEventListener(t, () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) importZip(f); });
async function importZip(f) {
  if (!f.name.toLowerCase().endsWith(".zip")) return msg("zip ではない", "err");
  msg(`${f.name} を展開中…`);
  try {
    const r = await api(`/api/import?path=${enc(browsePath)}&name=${enc(f.name)}`, { method: "POST", body: await f.arrayBuffer() });
    await showHome(browsePath);
    msg(`「${basename(r.dir)}」に展開した（主文書 ${r.mains} 件）`, "ok");
  } catch (e) { msg(e.message, "err"); }
}
