// 画面の入口。原稿の開き直し（refreshInfo）、サーバの状態の監視（poll）、キー操作、起動
import { $, api, post, enc, store, fail, bus, tab, setTabProject } from "./util.mjs";
import { info, setInfo } from "./state.mjs";
import { initMenus, closeMenus } from "./menu.mjs";
import { setCrumb, showStartHome } from "./home.mjs";
import { tabs, lastSave, dirty, openTab, closeAllTabs, pullOuter, saveAll, toggleMd } from "./editor.mjs";
import { sideView, viewShown, setLayout, setSide } from "./panels.mjs";
import { loadTree } from "./tree.mjs";
import "./outline.mjs";
import { loadHistory } from "./history.mjs";
import { openSearch } from "./search.mjs";
import { version, rendering, setVersion, resetPdf, loadPdf } from "./pdf.mjs";
import "./synctex.mjs";
import { hideSel, hideInline } from "./select.mjs";
import { recompile, hidePops, showBuildStatus } from "./compile.mjs";
import { loadComments, resetComments, cmtMtime, hideCompose } from "./comments/index.mjs";
import { runAct } from "./actions.mjs";
import "./theme.mjs";
import "./visual.mjs";
import "./zoom.mjs";
import "./gitpage.mjs";
import "./appmode.mjs";
import "./toolbar.mjs";
import "./figtab.mjs";
import "./pagefit.mjs";
import { openHistory, closeHistory } from "./histpage.mjs";
import { setBrowsePath, showHomeAt } from "./home.mjs";

let session = -1;   // このタブの原稿をサーバが開くたびに変わる番号。変わったら画面を作り直す

// 原稿を開いた・閉じた（一覧画面・編集画面を作り直す）
async function refreshInfo() {
  let i = await api("/api/info");
  if (tab.p && !i.main) {
    // このタブの原稿をサーバが開いていない（サーバを起動し直した・複製したタブ）。開き直す
    try { i = await post("/api/open", { tex: tab.p, t: tab.t }); }
    catch (e) { fail(e); setTabProject(null, false); }
  }
  setInfo(i);
  session = info.session;
  closeAllTabs(); hidePops(); closeMenus(); hideSel(); hideInline(); hideCompose();
  resetPdf(); resetComments();
  if (!info.main) { await showStartHome(); return; }
  document.body.className = "editing";
  setCrumb();
  $("ptname").textContent = info.rel.split("/").slice(-2, -1)[0] || info.main;
  document.title = `${info.main} — overleaf-compiler`;
  document.querySelectorAll(".mi.pandoc").forEach((m) => m.classList.toggle("dis", !info.has_pandoc));
  $("empty").style.display = "block"; $("empty").textContent = "コンパイル中…";
  await loadTree();
  try { await openTab(info.main); } catch (e) { fail(e); }
  if (sideView === "history") loadHistory();
  bus.emit("opened");   // 右のチャット欄などが、この原稿に合わせて作り直す
}

bus.on("reopen", refreshInfo);

// ---- 状態の監視 ----
let fast = false;
async function poll() {
  try {
    const s = await api("/api/status" + (tabs.size ? `?files=${enc([...tabs.keys()].join("\n"))}` : ""));
    if (s.session !== session) await refreshInfo();
    else if (s.open) {
      await pullOuter(s.mtimes);
      if (s.comments_mtime !== cmtMtime && !rendering) loadComments();   // CLI（Claude Code）が解決・返信した
      showBuildStatus(s);
      fast = s.building;
      if (s.version !== version && !s.building) {
        setVersion(s.version);
        loadTree();   // 外でファイルが増えていれば、ツリーにも出す
        if (viewShown("history")) loadHistory();
        if (s.has_pdf) await loadPdf();
        else $("empty").textContent = s.ok ? "PDF がまだ無い" : "コンパイルに失敗した。「ログ」を見ること";
      }
    }
  } catch { $("recompile").textContent = "サーバに接続できない"; }
  // 組版中と保存の直後は細かく確かめ、PDF をすぐ読み直す
  setTimeout(poll, fast || Date.now() - lastSave < 3000 ? 200 : 700);
}

// ---- キー操作 ----
document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey, editing = document.body.className === "editing";
  if (mod && !e.shiftKey && e.key.toLowerCase() === "s") { e.preventDefault(); saveAll(); }
  else if (mod && e.key === "Enter" && editing) { e.preventDefault(); recompile(); }
  else if (mod && e.shiftKey && e.key.toLowerCase() === "f" && editing) { e.preventDefault(); openSearch(); }
  else if (mod && e.shiftKey && e.key.toLowerCase() === "v" && editing) { e.preventDefault(); toggleMd(); }
  else if (e.key === "Escape") { closeMenus(); hidePops(); hideSel(); }
});
window.addEventListener("beforeunload", (e) => { if (dirty()) e.preventDefault(); });
// ブラウザの戻る・進む。URL（?p= ?view= ?dir=）の画面へ移る
window.addEventListener("popstate", async () => {
  const q = new URLSearchParams(location.search), p = q.get("p"), view = q.get("view"), dir = q.get("dir") || "";
  if (p !== tab.p) {
    await saveAll();
    try { if (tab.p && info && info.main) await post("/api/close"); } catch {}
    tab.p = p;
    if (!p) setBrowsePath(dir);
    await refreshInfo();
  } else if (!p) { await showHomeAt(dir); return; }
  if (p && view === "history") await openHistory(false);
  else if (p) closeHistory(false);
});

// ---- 起動 ----
initMenus(runAct);
setLayout(store.get("oc.layout", "both"));
if (store.get("oc.side", "1") !== "1") setSide(false);
await refreshInfo();
if (tab.p && new URLSearchParams(location.search).get("view") === "history") await openHistory(false);
poll();
