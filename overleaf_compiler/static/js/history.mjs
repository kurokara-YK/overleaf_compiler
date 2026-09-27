// 変更履歴（左のパネル）。版の一覧・差分・前の版に戻す
import { $, api, post, enc, escapeHtml, basename, confirmBox, showToast, fail, bus } from "./util.mjs";
import { active, openTab, showBody } from "./editor.mjs";
import { sideView, setView } from "./panels.mjs";

// 絞り込み。all（すべて）・this（開いているファイル）・path:<パス>（ファイルツリーの ⋮ から）
let histFilter = "all", histSel = null;
export function showHistory(filter = "all") { histFilter = filter; setView("history"); }
bus.on("view", (v) => { if (v === "history") loadHistory(); });
bus.on("activate", () => { if (sideView === "history" && histFilter === "this") loadHistory(); });
$("hAll").onclick = () => { histFilter = "all"; loadHistory(); };
$("hThis").onclick = () => { histFilter = "this"; loadHistory(); };
export async function loadHistory() {
  const path = histFilter === "this" ? (active && active.path) : histFilter.startsWith("path:") ? histFilter.slice(5) : "";
  $("hAll").classList.toggle("on", !path); $("hThis").classList.toggle("on", !!path);
  $("hThis").textContent = path ? basename(path) : "開いているファイル";
  const list = $("historyList");
  try {
    const r = await api(`/api/history?path=${enc(path || "")}`);
    list.replaceChildren();
    if (!r.entries.length) { list.innerHTML = '<div class="empty" style="padding:10px 12px">まだ履歴が無い（保存や変更のたびに残る）</div>'; return; }
    let day = "";
    for (const e of r.entries) {
      const dt = new Date(e.time * 1000), d = dt.toLocaleDateString("ja-JP", { month: "long", day: "numeric", weekday: "short" });
      if (d !== day) { day = d; const h = document.createElement("div"); h.className = "hday"; h.textContent = d; list.appendChild(h); }
      const it = document.createElement("div");
      it.className = "hitem" + (histSel === e.id ? " on" : "");
      it.innerHTML = `<div class="h1"><span>${dt.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" })}</span>
        <span>${escapeHtml(e.label)}</span><span class="add">+${e.add}</span><span class="del">−${e.del}</span></div>
        <div class="h2">${escapeHtml(e.path)}</div>`;
      it.onclick = () => { histSel = e.id; list.querySelectorAll(".hitem").forEach((x) => x.classList.remove("on")); it.classList.add("on"); showDiff(e.id); };
      list.appendChild(it);
    }
  } catch (e) { list.innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`; }
}
let diffId = null;
async function showDiff(id) {
  try {
    const r = await api(`/api/history_diff?id=${enc(id)}`);
    diffId = id;
    const e = r.entry, dt = new Date(e.time * 1000).toLocaleString("ja-JP");
    $("dtitle").textContent = `${e.path} — ${dt}・${e.label}${r.has_prev ? "（1つ前の版との差）" : "（最初の版）"}`;
    $("dRestore").hidden = !e.sha;
    $("dUndo").hidden = !r.has_prev;
    const body = $("dbody");
    if (r.binary) body.innerHTML = '<div class="dl gap"><span class="s">画像などの文字でないファイル。差分は出せない（「この版に戻す」はできる）</span></div>';
    else body.innerHTML = r.lines.map((l) => {
      const cls = l.t === "+" ? "add" : l.t === "-" ? "del" : l.t === "…" ? "gap" : "";
      return `<div class="dl ${cls}"><span class="n">${l.t === "-" ? l.a : l.b || ""}</span><span class="s">${escapeHtml(l.s)}</span></div>`;
    }).join("") || '<div class="dl gap"><span class="s">中身の変化は無い</span></div>';
    showBody("diff");
  } catch (e) { fail(e); }
}
$("dClose").onclick = () => { showBody(active && active.preview ? "md" : "cm"); histSel = null; loadHistory(); };
async function restore(before) {
  if (!diffId) return;
  const what = before ? "この変更をする前の中身" : "この版の中身";
  if (!(await confirmBox(before ? "この変更の前に戻す" : "この版に戻す", `ファイルを${what}に戻す？<br><span class="kbd">今の中身も履歴に残るので、戻したことも取り消せる</span>`, "戻す"))) return;
  try {
    const r = await post("/api/history_restore", { id: diffId, before });
    showToast(`${escapeHtml(r.path)} を戻した`, "ok");
    await bus.emit("files"); $("dClose").click();
    await openTab(r.path);
  } catch (e) { fail(e); }
}
$("dRestore").onclick = () => restore(false);
$("dUndo").onclick = () => restore(true);
