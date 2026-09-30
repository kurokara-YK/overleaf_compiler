// 右のチャット欄（Claude Code と Codex）の入口。エディタ | PDF | チャット欄の開閉と幅、Claude と Codex の切り替え、
// 出来事の受け取り、上の見出し（会話の名前・履歴・新規）
import { $, api, store, fail, bus, tab } from "../util.mjs";
import { cm } from "../editor.mjs";
import { refit } from "../pdf.mjs";
import { st, cc, icon, closePop, isCodex, optKey, defaultOpts } from "./core.mjs";
import { show, clearLog, spinner } from "./view.mjs";
import { renderBar, fitInput, clearPerms, refreshUsage } from "./composer.mjs";
import { openHistory, newConversation } from "./dialogs.mjs";

const ide = $("ide");
$("ccHistoryBtn").innerHTML = icon("history");
$("ccNewBtn").innerHTML = icon("newchat");
$("ccCloseBtn").innerHTML = icon("close");
$("ccPlus").innerHTML = icon("plus");
$("ccSlash").innerHTML = icon("slash");
$("ccMic").innerHTML = icon("mic");

// ---- Claude と Codex の切り替え（ヘッダの ✳ Claude と Codex のボタン）----
function loadOpts() {
  st.opts = defaultOpts();
  for (const k of ["model", "effort", "mode", "thinking"]) {
    const v = store.get(optKey(k), null);
    if (v != null) st.opts[k] = k === "thinking" ? v === "true" : v;
  }
}
function applyEngine() {
  const shown = claudeShown();
  $("claude").classList.toggle("codex", isCodex());
  $("claudeBtn").classList.toggle("on", shown && !isCodex());
  $("codexBtn").classList.toggle("on", shown && isCodex());
  $("ccLogo").src = isCodex() ? "/claude-asset/codex-logo.svg" : "/claude-asset/claude-logo.svg";
  $("ccLogo").classList.toggle("cx", isCodex());
}
function setEngine(e) {
  if (st.engine === e) return;
  closePop();
  st.engine = e; store.set("oc.engine", e);
  Object.assign(st, { models: [], commands: [], session: null, title: "", busy: false });
  loadOpts();
}

// ---- 表示する・隠す ----
export const claudeShown = () => ide.classList.contains("with-claude");
export function toggleClaude(show = !claudeShown(), engine = st.engine) {
  const switched = engine !== st.engine;
  setEngine(engine);
  const was = claudeShown();
  ide.classList.toggle("with-claude", show);
  store.set("oc.claude", show ? "1" : "0");
  applyEngine();
  if (show !== was) setTimeout(() => { cm.refresh(); refit(); }, 0);
  if (show && opened && (switched || !was)) { restart(); setTimeout(() => $("ccText").focus(), 0); }
  else if (!show) { gen++; closePop(); }
}
// 同じ方をもう一度押すと閉じる。違う方を押すと、開いたまま切り替える
$("claudeBtn").onclick = () => toggleClaude(!(claudeShown() && !isCodex()), "claude");
$("codexBtn").onclick = () => toggleClaude(!(claudeShown() && isCodex()), "codex");
$("ccCloseBtn").onclick = () => toggleClaude(false);
$("ccHistoryBtn").onclick = () => openHistory();
$("ccNewBtn").onclick = () => newConversation();
$("claude").style.width = `${store.get("oc.claudeW", 420)}px`;
$("claudeGrip").addEventListener("mousedown", (e) => {
  e.preventDefault(); $("claudeGrip").classList.add("drag");
  const move = (ev) => { $("claude").style.width = `${Math.max(300, Math.min(innerWidth * 0.6, innerWidth - ev.clientX))}px`; };
  const up = () => {
    $("claudeGrip").classList.remove("drag"); removeEventListener("mousemove", move); removeEventListener("mouseup", up);
    store.set("oc.claudeW", parseInt($("claude").style.width)); cm.refresh(); refit();
  };
  addEventListener("mousemove", move); addEventListener("mouseup", up);
});

// ---- 前回のモデル・深さ・モード ----
loadOpts();

// ---- 起動と出来事の受け取り（長いポーリング）。原稿を開き直したら最初から ----
let after = 0, gen = 0;
export async function restart() {
  const my = ++gen;
  st.epoch = -1; after = 0; clearLog(); clearPerms(); renderBar();
  if (!tab.p) return;
  loop(my);
  try {
    await cc("set", st.opts);   // 前回の選択をサーバの側にも伝える
    const r = await cc("start");
    if (my !== gen) return;
    Object.assign(st, { models: r.models || [], commands: r.commands || [], account: r.account || {}, fast: r.fast });
    renderBar();
  } catch (e) { if (my === gen) fail(e); }
}
async function loop(my) {
  while (my === gen) {
    try {
      const r = await api(`/api/${st.engine}/events?after=${after}&epoch=${st.epoch}`);
      if (my !== gen) return;
      const renewed = r.epoch !== st.epoch;
      if (renewed) { st.epoch = r.epoch; clearLog(); clearPerms(); }
      r.events.forEach(show);
      after = r.next;
      setState(r);
      // 返答が終わったとき・会話を開き直したときに、コンテキストの使用量を取り直す
      if (renewed || r.events.some((e) => e.k === "done")) refreshUsage();
    } catch { await new Promise((ok) => setTimeout(ok, 2000)); }
  }
}
function setState(r) {
  const was = st.busy;
  Object.assign(st, { busy: r.busy, session: r.session, title: r.title });
  if (r.opts) Object.assign(st.opts, r.opts);
  $("ccTitle").textContent = r.title || (isCodex() ? "New chat" : "Untitled");
  spinner(r.busy);
  if (was !== r.busy || r.opts) renderBar();
}
// 原稿を開き終えたら（main.mjs の refreshInfo）、その原稿の会話を受け取り直す
let opened = false;
bus.on("opened", () => { opened = true; if (claudeShown()) restart(); });

// ---- キー操作・起動 ----
document.addEventListener("keydown", (e) => {
  if (document.body.className !== "editing") return;
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "l") { e.preventDefault(); toggleClaude(); }
  else if ((e.ctrlKey || e.metaKey) && e.key === "Escape") {   // VS Code と同じく Ctrl+Esc でチャット欄へ／から
    e.preventDefault();
    if (!claudeShown()) toggleClaude(true);
    else if (document.activeElement === $("ccText")) cm.focus(); else $("ccText").focus();
  }
});
fitInput();
applyEngine();
if (store.get("oc.claude", "0") === "1") toggleClaude(true);
