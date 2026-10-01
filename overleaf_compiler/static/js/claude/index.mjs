// 右のチャット欄（Claude Code と Codex）の入口。エディタ | PDF | チャット欄の開閉と幅、上のタブ（会話ごと。
// Claude と Codex を混ぜて並べられ、同時に動く）、出来事の受け取り
import { $, api, post, store, fail, bus, tab, escapeHtml, confirmBox } from "../util.mjs";
import { cm } from "../editor.mjs";
import { refit } from "../pdf.mjs";
import { st, cc, icon, closePop, isCodex, optKey, defaultOpts } from "./core.mjs";
import { show, clearLog, spinner } from "./view.mjs";
import { renderBar, fitInput, clearPerms, refreshUsage } from "./composer.mjs";
import { openHistory } from "./dialogs.mjs";

const ide = $("ide");
$("ccHistoryBtn").innerHTML = icon("history");
$("ccNewBtn").innerHTML = icon("newchat");
$("ccCloseBtn").innerHTML = icon("close");
$("ccPlus").innerHTML = icon("plus");
$("ccSlash").innerHTML = icon("slash");
$("ccMic").innerHTML = icon("mic");

// ---- 前回のモデル・深さ・モード（Claude と Codex で別々に覚える）----
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
}

// ---- タブ（会話ごと）----
let tabs = [];                 // サーバの /api/chat/tabs（{ id, engine, title, busy, count }）
const unread = new Set();      // 裏で返答が終わったタブ（開くまで印を付ける）
const drafts = new Map();      // タブごとの書きかけの入力
const tabKey = () => `oc.ccTab:${tab.p}`;
const logoOf = (eng) => eng === "codex" ? '<img class="tlogo cx" src="/claude-asset/codex-logo.svg" alt="">'
  : '<img class="tlogo" src="/claude-asset/claude-logo.svg" alt="">';
async function loadTabs() {
  const was = new Map(tabs.map((t) => [t.id, t.busy]));
  try { tabs = (await api("/api/chat/tabs")).tabs; } catch { return tabs; }
  for (const t of tabs) if (was.get(t.id) && !t.busy && t.id !== st.chat) unread.add(t.id);
  renderTabs();
  return tabs;
}
function renderTabs() {
  const box = $("ccTabs");
  box.replaceChildren(...tabs.map((t) => {
    const d = document.createElement("div");
    const title = t.id === st.chat ? (st.title || t.title) : t.title;
    d.className = "cctab" + (t.id === st.chat ? " on" : "") + (t.busy ? " busy" : "") + (unread.has(t.id) ? " unread" : "");
    d.title = title || (t.engine === "codex" ? "New chat" : "Untitled");
    d.innerHTML = `${logoOf(t.engine)}<span class="tt">${escapeHtml(d.title)}</span><span class="st"></span><button class="tx" title="Close">${icon("close")}</button>`;
    d.onclick = (e) => { if (e.target.closest(".tx")) closeTab(t.id); else if (t.id !== st.chat) selectTab(t.id); };
    d.onauxclick = (e) => { if (e.button === 1) { e.preventDefault(); closeTab(t.id); } };   // 中クリックで閉じる
    return d;
  }));
  box.querySelector(".cctab.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
export async function newTab(engine = st.engine) {
  try {
    const r = await post("/api/chat/new", { engine });
    await loadTabs();
    await selectTab(r.id);
  } catch (e) { fail(e); }
}
async function selectTab(id) {
  const t = tabs.find((x) => x.id === id);
  if (!t) return;
  if (st.chat) drafts.set(st.chat, $("ccText").value);
  closePop();
  st.chat = id; store.set(tabKey(), id);
  if (st.engine !== t.engine) { st.engine = t.engine; store.set("oc.engine", t.engine); loadOpts(); }
  Object.assign(st, { models: [], commands: [], session: null, title: "", busy: false });
  unread.delete(id);
  $("ccText").value = drafts.get(id) || ""; fitInput();
  applyEngine(); renderTabs();
  if (claudeShown()) await restart();
}
async function closeTab(id) {
  const t = tabs.find((x) => x.id === id);
  if (!t) return;
  if (t.busy && !await confirmBox("Close this tab?", "This conversation is still running. Closing the tab stops it.", "Close", true)) return;
  const i = tabs.indexOf(t);
  try { await post("/api/chat/close", { id }); } catch (e) { return fail(e); }
  drafts.delete(id); unread.delete(id);
  await loadTabs();
  if (st.chat !== id) return;
  st.chat = null;
  const next = tabs[i] || tabs[i - 1];
  if (next) selectTab(next.id);
  else toggleClaude(false);   // 最後のタブを閉じたら欄を閉じる（VS Code と同じ）
}
// engine の会話を出す。前に開いていたタブ → その種類の一番新しいタブ → 無ければ新しく作る
async function openPanel(engine) {
  await loadTabs();
  const saved = store.get(tabKey(), null);
  const pick = (engine ? null : tabs.find((t) => t.id === st.chat || t.id === saved))
    || tabs.find((t) => t.id === saved && t.engine === engine)
    || [...tabs].reverse().find((t) => t.engine === (engine || st.engine))
    || (engine ? null : tabs[tabs.length - 1]);
  if (pick) { st.chat = null; await selectTab(pick.id); }
  else await newTab(engine || st.engine);
}

// ---- 表示する・隠す ----
export const claudeShown = () => ide.classList.contains("with-claude");
export function toggleClaude(show = !claudeShown(), engine = null) {
  const was = claudeShown();
  ide.classList.toggle("with-claude", show);
  store.set("oc.claude", show ? "1" : "0");
  applyEngine();
  if (show !== was) setTimeout(() => { cm.refresh(); refit(); }, 0);
  if (show && opened) {
    if (!was || (engine && engine !== st.engine) || !st.chat) openPanel(engine || (st.chat ? null : st.engine));
    setTimeout(() => $("ccText").focus(), 0);
  } else if (!show) { gen++; closePop(); }
}
// ✳ Claude・Codex：同じ種類の会話を見ているときに押すと閉じる。違う種類なら、その種類のタブへ切り替える
$("claudeBtn").onclick = () => toggleClaude(!(claudeShown() && !isCodex()), "claude");
$("codexBtn").onclick = () => toggleClaude(!(claudeShown() && isCodex()), "codex");
$("ccCloseBtn").onclick = () => toggleClaude(false);
$("ccHistoryBtn").onclick = () => openHistory();
$("ccNewBtn").onclick = () => newTab(st.engine);   // ⊕ は新しいタブで新しい会話（VS Code と同じ）
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
loadOpts();

// ---- 起動と出来事の受け取り（今のタブだけ長いポーリング。ほかのタブは一覧で返答中かどうかだけ見る）----
let after = 0, gen = 0;
export async function restart() {
  const my = ++gen;
  st.epoch = -1; after = 0; clearLog(); clearPerms(); renderBar();
  if (!tab.p || !st.chat) return;
  loop(my);
  try {
    await cc("set", st.opts);   // 前回の選択をサーバの側にも伝える
    const r = await cc("start");
    if (my !== gen) return;
    Object.assign(st, { models: r.models || [], commands: r.commands || [], account: r.account || {}, fast: r.fast,
                        settings: r.settings || {}, remote: r.remote || {} });
    renderBar();
  } catch (e) { if (my === gen) fail(e); }
}
async function loop(my) {
  while (my === gen) {
    try {
      const r = await api(`/api/chat/events?c=${encodeURIComponent(st.chat)}&after=${after}&epoch=${st.epoch}`);
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
  const was = st.busy, wasTitle = st.title;
  Object.assign(st, { busy: r.busy, session: r.session, title: r.title });
  if (r.opts) Object.assign(st.opts, r.opts);
  const t = tabs.find((x) => x.id === st.chat);
  if (t) { t.busy = r.busy; t.title = r.title; }
  if (was !== r.busy || wasTitle !== r.title) renderTabs();
  spinner(r.busy);
  if (was !== r.busy || r.opts) renderBar();
}
// ほかのタブの返答中・返答が終わった印のために、欄を開いている間は一覧を見直す
setInterval(() => { if (claudeShown() && opened && document.visibilityState === "visible") loadTabs(); }, 2500);

// 原稿を開き終えたら（main.mjs の refreshInfo）、その原稿のタブを読み直す
let opened = false;
bus.on("opened", () => {
  opened = true; st.chat = null; tabs = []; drafts.clear(); unread.clear(); renderTabs();
  if (claudeShown()) openPanel(null);
});

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
