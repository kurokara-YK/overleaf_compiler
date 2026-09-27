// コンパイル（リコンパイルのボタン）と、ログ（エラーの一覧）。状態はサーバの /api/status から受け取る
import { $, post, escapeHtml, basename, fail } from "./util.mjs";
import { saveAll, openTab } from "./editor.mjs";
import { revealEditor } from "./panels.mjs";

export async function recompile() {
  await saveAll();
  $("recompile").classList.add("busy"); $("recompile").textContent = "コンパイル中…";
  try { await post("/api/recompile"); } catch (e) { fail(e); }
}
$("recompile").onclick = recompile;
let lastErrors = [];
export function hidePops() { document.querySelectorAll(".pop.open").forEach((p) => p.classList.remove("open")); }
function renderErrors() {
  const box = $("errors");
  if (!lastErrors.length) { box.innerHTML = '<div class="none">エラーは無い</div>'; return; }
  box.replaceChildren(...lastErrors.map((e) => {
    const d = document.createElement("div");
    if (e.file) { d.dataset.file = e.file; d.dataset.line = e.line; }
    d.innerHTML = e.file ? `<b>${escapeHtml(basename(e.file))}:${e.line}</b>${escapeHtml(e.msg)}` : escapeHtml(e.msg);
    return d;
  }));
}
$("logBtn").onclick = (e) => {
  e.stopPropagation();
  const box = $("errors"), r = $("logBtn").getBoundingClientRect();
  renderErrors();
  box.classList.toggle("open");
  box.style.left = `${Math.max(8, Math.min(innerWidth - box.offsetWidth - 8, r.left))}px`;
  box.style.top = `${r.bottom + 6}px`;
};
$("errors").addEventListener("click", async (ev) => {
  const d = ev.target.closest("div[data-file]");
  if (!d) return;
  hidePops();
  revealEditor();
  try { await openTab(d.dataset.file, parseInt(d.dataset.line)); } catch (e) { fail(e); }
});
document.addEventListener("click", (e) => { if (!e.target.closest(".pop, #logBtn")) hidePops(); });
// 組版の状態（/api/status）をボタンとログに出す
export function showBuildStatus(s) {
  const rb = $("recompile");
  rb.classList.toggle("busy", s.building); rb.textContent = s.building ? "コンパイル中…" : "リコンパイル";
  lastErrors = s.errors;
  const lb = $("logBtn");
  lb.querySelector(".n").textContent = s.errors.length;
  lb.classList.toggle("err", !s.ok); lb.classList.toggle("ok", s.ok);
  if ($("errors").classList.contains("open")) renderErrors();
  if (!s.building && s.seconds) $("compileInfo").textContent = `${s.seconds} 秒（${s.mode}）`;
}
