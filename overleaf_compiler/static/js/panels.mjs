// 画面の並び（アイコンの列 | 左のパネル | エディタ | PDF）。左のパネルの切り替え・表示の切り替え・境目のドラッグ
import { $, store, bus } from "./util.mjs";
import { cm } from "./editor.mjs";
import { refit } from "./pdf.mjs";

const ide = $("ide");
const VIEWS = { files: "vFiles", search: "vSearch", history: "vHistory", comments: "vComments" };
export let sideView = "files";   // 左のパネルに出しているもの

// ---- 左のパネル（ファイル・検索・履歴・コメント）----
export function setView(v) {
  sideView = v;
  if (ide.classList.contains("no-side")) setSide(true);
  document.querySelectorAll("#rail button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  for (const [k, id] of Object.entries(VIEWS)) $(id).classList.toggle("on", v === k);
  bus.emit("view", v);
}
// そのパネルが今見えているか
export const viewShown = (v) => sideView === v && !ide.classList.contains("no-side");
$("rail").onclick = (e) => {
  const b = e.target.closest("button[data-view]");
  if (!b) return;
  if (viewShown(b.dataset.view)) setSide(false); else setView(b.dataset.view);
};
export function setSide(show) {
  ide.classList.toggle("no-side", !show);
  if (!show) document.querySelectorAll("#rail button").forEach((b) => b.classList.remove("on"));
  else document.querySelector(`#rail button[data-view="${sideView}"]`).classList.add("on");
  store.set("oc.side", show ? "1" : "0"); setTimeout(() => { cm.refresh(); refit(); }, 0);
}
export const toggleSide = () => setSide(ide.classList.contains("no-side"));
document.querySelectorAll(".sideClose").forEach((b) => b.onclick = () => setSide(false));

// ---- 表示（エディタ・両方・PDF）----
export function setLayout(l) {
  ide.classList.toggle("only-editor", l === "editor");
  ide.classList.toggle("only-pdf", l === "pdf");
  for (const b of $("layout").querySelectorAll("button")) b.classList.toggle("on", b.dataset.l === l);
  store.set("oc.layout", l);
  setTimeout(() => { cm.refresh(); refit(); }, 0);
}
// ソースへ移るとき、PDF だけの表示ならエディタも出す
export function revealEditor() { if (ide.classList.contains("only-pdf")) setLayout("both"); }
$("layout").onclick = (e) => { const b = e.target.closest("button"); if (b) setLayout(b.dataset.l); };

// ---- 境目のドラッグで幅を変える（次回も同じ）----
$("side").style.width = `${store.get("oc.sideW", 250)}px`;
$("editor").style.width = `${store.get("oc.editorW", Math.round(innerWidth * 0.4))}px`;
function drag(handle, onMove, onDone) {
  handle.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault(); handle.classList.add("drag");
    const up = () => { handle.classList.remove("drag"); removeEventListener("mousemove", onMove); removeEventListener("mouseup", up); onDone(); };
    addEventListener("mousemove", onMove); addEventListener("mouseup", up);
  });
}
drag($("sideGrip"), (e) => { $("side").style.width = `${Math.max(160, Math.min(520, e.clientX - $("side").getBoundingClientRect().left))}px`; },
     () => { store.set("oc.sideW", parseInt($("side").style.width)); cm.refresh(); refit(); });
drag($("split"), (e) => {
  const left = $("editor").getBoundingClientRect().left;
  $("editor").style.width = `${Math.max(200, Math.min(innerWidth - left - 240, e.clientX - left))}px`;
}, () => { store.set("oc.editorW", parseInt($("editor").style.width)); cm.refresh(); refit(); });
