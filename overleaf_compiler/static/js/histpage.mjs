// 変更履歴の画面（Overleaf の History）。左にファイル、中央に選んだ版の中身と1つ前の版との違い、右に版の一覧とラベル。
// 画面の URL は ?p=…&view=history。ブラウザの戻るでエディタへ戻れる
import { $, api, post, enc, escapeHtml, basename, ask, confirmBox, showToast, fail, bus, tab, pushUrl } from "./util.mjs";
import { info } from "./state.mjs";
import { openTab } from "./editor.mjs";

let entries = [], files = [], selId = null, fileFilter = null, listTab = "all";
const WHO = { browser: "あなた（ブラウザ）", outside: "ローカル（VS Code・Claude Code）", restore: "あなた（前の版に戻した）",
              upload: "あなた（アップロード）", new: "あなた（新規作成）", rename: "あなた（名前を変更）", delete: "あなた（削除）",
              first: "最初の版" };

export async function openHistory(push = true) {
  if (!info || !info.main) return;
  if (push) pushUrl({ p: tab.p, view: "history" });
  document.body.className = "history";
  $("hpTitle").textContent = info.rel ? info.rel.split("/").slice(-2, -1)[0] || info.main : info.main;
  await load();
}
export function closeHistory(push = true) {
  if (document.body.className !== "history") return;
  if (push) pushUrl({ p: tab.p });
  document.body.className = "editing";
  bus.emit("files");
}
$("hpBack").onclick = () => closeHistory();
$("histBtn").onclick = () => openHistory();

async function load() {
  try {
    const [h, t] = await Promise.all([api("/api/history"), api("/api/tree")]);
    entries = h.entries; files = t.files.filter((f) => !f.dir).map((f) => f.path);
    if (!entries.find((e) => e.id === selId)) selId = null;
    renderFiles(); renderList();
    const first = shown()[0];
    if (!selId && first) select(first.id);
    else if (selId) select(selId);
    else { $("hpText").innerHTML = '<div class="empty" style="padding:16px">まだ履歴が無い（保存や変更のたびに残る）</div>'; }
  } catch (e) { fail(e); }
}
const shown = () => entries.filter((e) => (!fileFilter || e.path === fileFilter) && (listTab === "all" || (e.labels && e.labels.length)));

function renderFiles() {
  const cur = entries.find((e) => e.id === selId);
  $("hpFiles").innerHTML = `<div class="hpf${fileFilter ? "" : " on"}" data-f="">すべてのファイル</div>` + files.map((f) =>
    `<div class="hpf${fileFilter === f ? " on" : ""}" data-f="${escapeHtml(f)}" title="${escapeHtml(f)}">📄 ${escapeHtml(f)}
      ${cur && cur.path === f ? '<span class="badge">変更</span>' : ""}</div>`).join("");
}
$("hpFiles").onclick = (e) => {
  const d = e.target.closest(".hpf"); if (!d) return;
  fileFilter = d.dataset.f || null; selId = null;
  renderFiles(); renderList();
  const first = shown()[0]; if (first) select(first.id); else $("hpText").innerHTML = '<div class="empty" style="padding:16px">このファイルの履歴は無い</div>';
};

function dayOf(t) {
  const d = new Date(t * 1000), today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
  return diff === 0 ? "今日" : diff === 1 ? "昨日" : d.toLocaleDateString("ja-JP", { month: "long", day: "numeric", weekday: "short" });
}
function renderList() {
  const box = $("hpEntries"), list = shown();
  if (!list.length) { box.innerHTML = `<div class="empty" style="padding:14px">${listTab === "labels" ? "ラベルを付けた版は無い（版の ⋮ から付ける）" : "履歴が無い"}</div>`; return; }
  let day = "", html = "";
  for (const e of list) {
    const d = dayOf(e.time);
    if (d !== day) { day = d; html += `<div class="hpday">${d}</div>`; }
    const t = new Date(e.time * 1000).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
    html += `<div class="hpe${e.id === selId ? " on" : ""}" data-id="${e.id}">
      <div class="t">${t}</div><div class="k">${escapeHtml(e.label)}　+${e.add} −${e.del}</div>
      <div class="k">${escapeHtml(e.path)}</div><div class="k who">${escapeHtml(WHO[e.kind] || e.kind)}</div>
      ${(e.labels || []).map((l) => `<span class="lab" data-l="${escapeHtml(l)}" title="押すとラベルを外す">🏷 ${escapeHtml(l)}</span>`).join("")}
      <button class="dots" title="ラベルを付ける">⋮</button></div>`;
  }
  box.innerHTML = html;
}
$("hpEntries").onclick = async (e) => {
  const it = e.target.closest(".hpe"); if (!it) return;
  if (e.target.closest(".dots")) {
    const name = await ask("ラベルを付ける", "この版に付ける名前（例：先生に提出した版）");
    if (name) { try { await post("/api/history_label", { id: it.dataset.id, name }); await load(); } catch (x) { fail(x); } }
    return;
  }
  const lab = e.target.closest(".lab");
  if (lab) {
    if (await confirmBox("ラベルを外す", `「${escapeHtml(lab.dataset.l)}」を外す？`, "外す")) {
      try { await post("/api/history_label", { id: it.dataset.id, name: "" }); await load(); } catch (x) { fail(x); }
    }
    return;
  }
  select(it.dataset.id);
};
$("hpTabs").onclick = (e) => {
  const b = e.target.closest("button[data-h]"); if (!b) return;
  listTab = b.dataset.h;
  $("hpTabs").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
  renderList();
};

function segs(l) {
  if (!l.segs) return escapeHtml(l.s);
  return l.segs.map(([k, s]) => k === " " ? escapeHtml(s) : `<span class="${k === "+" ? "sa" : "sd"}">${escapeHtml(s)}</span>`).join("");
}
async function select(id) {
  selId = id;
  document.querySelectorAll("#hpEntries .hpe").forEach((x) => x.classList.toggle("on", x.dataset.id === id));
  renderFiles();
  try {
    const r = await api(`/api/history_view?id=${enc(id)}`);
    const e = r.entry, when = new Date(e.time * 1000).toLocaleString("ja-JP", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
    $("hpWhat").textContent = `表示中：${when}・${e.label}`;
    $("hpCount").textContent = r.has_prev ? `${e.path} の変更 ${r.changes} か所` : `${e.path}（最初の版）`;
    $("hpRestore").hidden = !e.sha;
    $("hpText").innerHTML = r.binary ? '<div class="empty" style="padding:16px">画像などの文字でないファイル。中身は表示できない（「この版に戻す」はできる）</div>'
      : r.lines.map((l) => `<div class="hpl${l.t === "+" ? " add" : l.t === "-" ? " del" : ""}"><span class="n">${l.n || ""}</span><span class="s">${segs(l) || " "}</span></div>`).join("");
    const firstChange = $("hpText").querySelector(".hpl.add, .hpl.del");
    if (firstChange) firstChange.scrollIntoView({ block: "center" });
  } catch (x) { fail(x); }
}
$("hpRestore").onclick = async () => {
  const e = entries.find((x) => x.id === selId); if (!e) return;
  if (!(await confirmBox("この版に戻す", `${escapeHtml(e.path)} をこの版の中身に戻す？<br><span class="kbd">今の中身も履歴に残るので、戻したことも取り消せる</span>`, "戻す"))) return;
  try {
    const r = await post("/api/history_restore", { id: selId });
    showToast(`${escapeHtml(r.path)} を戻した`, "ok");
    closeHistory(); await openTab(r.path);
  } catch (x) { fail(x); }
};
