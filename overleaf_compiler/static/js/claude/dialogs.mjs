// ／メニューの項目（VS Code の拡張と同じ並び）と、それぞれが開く画面。
// 使用量・状態・MCP・フック・許可・メモリ・巻き戻し・会話の一覧・書き出し
import { $, api, post, escapeHtml, modal, closeBtn, showToast, fail, ago, store } from "../util.mjs";
import { openTab } from "../editor.mjs";
import { revealEditor } from "../panels.mjs";
import { st, cc, ccGet, icon, modelLabel, EFFORTS, EFFORT_LABEL, renderData, showPop, closePop, popOpen, isCodex, modes, effortLabel } from "./core.mjs";
import { exportText, users } from "./view.mjs";

let mod = null;   // composer.mjs（循環するので後から読む）
const composer = async () => (mod ||= await import("./composer.mjs"));
const toggle = (on) => `<span class="sw${on ? " on" : ""}"><span></span></span>`;

// ---- ／メニューの項目 ----
export function actions() {
  if (isCodex()) return codexActions();
  const A = [];
  const add = (section, label, desc, run, extra = {}) => A.push({ section, label, desc, run, ...extra });
  add("Context", "Attach file…", "Upload a file to include in conversation", () => $("ccFileInput").click());
  add("Context", "Mention file from this project…", "Reference a project file with @mention", async () => (await composer()).insertAt("@"));
  add("Context", "Clear conversation", "Start a new conversation", newConversation);
  add("Context", "Rewind", "Restore code and conversation to an earlier point", rewindList);
  add("Context", "Export conversation", "Copy the conversation as plain text or save it to a file", exportConversation);
  add("Context", "New conversation", "Open a new conversation in a new tab", () => import("./index.mjs").then((m) => m.newTab()), { filterOnly: true });
  add("Context", "Resume conversation", "Continue a previous conversation", () => openHistory(), { filterOnly: true });
  add("Model", "Switch model…", "Change the AI model", async () => (await composer()).openModelMenu(), { right: () => `<span class="dim">${escapeHtml(modelLabel())}</span>` });
  add("Model", "Account & usage…", "View account info and usage", accountUsage);
  add("Model", "Thinking", "Toggle extended thinking mode", async () => (await composer()).setOpt({ thinking: !st.opts.thinking }),
    { keepOpen: true, right: () => toggle(st.opts.thinking) });
  add("Model", "Effort", "Set how hard the model tries", async () => {
    const i = EFFORTS.indexOf(st.opts.effort);
    (await composer()).setOpt({ effort: EFFORTS[(i + 1) % EFFORTS.length] });
  }, { keepOpen: true, hint: `(${EFFORT_LABEL[st.opts.effort]})`,
       right: () => `<span class="slider">${EFFORTS.map((e, k) => `<span class="dot${k <= EFFORTS.indexOf(st.opts.effort) ? " fill" : ""}${e === st.opts.effort ? " knob" : ""}"></span>`).join("")}</span>` });
  add("Model", "Toggle fast mode", "Toggle fast mode for faster responses (Opus only)", fastMode);
  add("Customize", "MCP servers", "Configure Model Context Protocol servers", mcpServers);
  add("Customize", "Hooks", "View and edit hooks", () => dataDialog("Hooks", "get_hooks_listing"));
  add("Customize", "Permissions", "View and edit permission rules", () => dataDialog("Permissions", "list_permission_rules"));
  add("Customize", "Status", "Version, session, account, model and server details", status);
  add("Customize", "Sandbox", "View and change how commands are sandboxed", () => dataDialog("Sandbox", "get_sandbox_dialog"));
  add("Customize", "Slash commands", "Browse slash commands", slashCommands);
  add("Customize", "Memory", "View and manage what Claude remembers about this project", () => dataDialog("Memory", "get_memory_dialog"));
  add("Customize", "Instructions", "Edit CLAUDE.md files", instructions);
  add("Customize", "Manage plugins", "Install, enable, or disable plugins", () => sendSlash("/plugin"));
  add("Customize", "Output styles", "Change response formatting style", () => sendSlash("/output-style"));
  add("Customize", "Open Claude in Terminal", "Open a new Claude instance in the Terminal", () => cc("terminal").catch(fail));
  add("Settings", "General config…", "Open Claude Code configuration", () => dataDialog("Settings", "get_settings"));
  add("Settings", "Focus view", "Show only your prompts and Claude's responses", () => {
    const on = !$("claude").classList.contains("focus");
    $("claude").classList.toggle("focus", on); store.set("oc.ccFocus", on ? "1" : "0");
  }, { keepOpen: true, right: () => toggle($("claude").classList.contains("focus")) });
  add("Support", "View help docs", "Open help documentation", () => window.open("https://code.claude.com/docs", "_blank", "noopener"));
  for (const c of st.commands) {
    add("Slash Commands", `/${c.name}`, c.description, () => insertSlash(`/${c.name} `), { hint: c.argumentHint || "" });
  }
  return A;
}
// Codex の拡張のスラッシュコマンド（この画面で使えるもの）
function codexActions() {
  composer();   // Compact の「% full」を出すために読んでおく
  const A = [];
  const add = (label, desc, run, extra = {}) => A.push({ section: "Commands", label, desc, run, ...extra });
  add("New chat", "Start a blank chat in the same workspace", newConversation);
  add("Resume", "Resume a recent chat", () => openHistory());
  add("Fork chat", "Fork this chat in the current workspace", () => cc("fork").catch(fail));
  add("Compact", "Compact this chat's context", async () => (await composer()).compact(),
    { right: () => { const u = mod?.usedPct; return u ? `<span class="dim">${u}% full</span>` : ""; } });
  add("Model", "Choose the model", async () => (await composer()).openModelMenu(), { right: () => `<span class="dim">${escapeHtml(modelLabel())}</span>` });
  add("Reasoning", "Choose how much the model thinks", async () => (await composer()).openModelMenu(),
    { right: () => `<span class="dim">${escapeHtml(effortLabel())}</span>` });
  add("Permissions", "How should Codex actions be approved?", async () => (await composer()).openModeMenu(),
    { right: () => `<span class="dim">${escapeHtml((modes()[st.opts.mode] || {}).label || "")}</span>` });
  add("Status", "Show chat ID, context usage, and rate limits", codexStatus);
  add("MCP", "Show MCP server status", codexMcp);
  add("Init", "Create an AGENTS.md file with instructions for Codex", async () => {
    $("ccText").value = "Generate a file named AGENTS.md in this folder that serves as a contributor guide for this LaTeX document: "
      + "its structure, how it is built (overleaf-compiler rebuilds automatically), and writing conventions you can infer. Keep it concise.";
    (await composer()).send();
  });
  add("Rewind", "Revert the chat and files to before a message", rewindList);
  add("Export conversation", "Copy the conversation as plain text or save it to a file", exportConversation);
  add("Open Codex in Terminal", "Continue this chat in the Codex CLI", () => cc("terminal").catch(fail));
  return A;
}
let limits = {};   // 最後に届いた利用枠（Status に出す）
export function setLimits(e) { limits = e; }
async function codexStatus() {
  const m = st.models.find((x) => x.value === st.opts.model);
  const pct = (v) => v == null ? "—" : `${Math.round(v * 100)}% used`;
  const rows = [["Chat ID", st.session || "(new chat)"], ["Model", modelLabel() + (m ? "" : st.opts.model === "default" ? " (default)" : "")],
    ["Reasoning", effortLabel() || "default"], ["Permissions", (modes()[st.opts.mode] || {}).label || st.opts.mode],
    ["Context", mod?.usedPct != null ? `${mod.usedPct}% full` : "—"], ["5h limit", pct(limits.five_hour)], ["Weekly limit", pct(limits.seven_day)]];
  modal("Status", `<table class="ccdata">${rows.map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join("")}</table>`, closeBtn);
}
async function codexMcp() {
  let r;
  try { r = await cc("control", { method: "mcpServerStatus/list", params: {} }); } catch (e) { return fail(e); }
  const html = `<div class="ccmcp">${(r.data || []).map((s) => `<div class="srv"><span class="st ${s.status === "ready" || s.authStatus ? "connected" : ""}"></span>
    <div class="t"><b>${escapeHtml(s.name)}</b><div class="dim">${Object.keys(s.tools || {}).length} tools</div></div></div>`).join("") || '<div class="dim">No MCP servers</div>'}</div>`;
  modal("MCP", html, closeBtn);
}

export function runAction(a) { Promise.resolve(a.run()).catch(fail); }
if (store.get("oc.ccFocus", "0") === "1") $("claude").classList.add("focus");

async function insertSlash(s) { const t = $("ccText"); t.value = s; t.focus(); (await composer()).fitInput(); }
async function sendSlash(s) { $("ccText").value = s; (await composer()).send(); }

// ---- 会話 ----
export async function newConversation() {
  if (st.busy) await cc("stop").catch(() => {});
  try { await cc("reset"); } catch (e) { fail(e); }
  $("ccText").focus();
}
export async function openHistory(anchor = $("ccHistoryBtn")) {
  if (popOpen()?.key === "history") return closePop();
  const el = document.createElement("div");
  el.className = "menu2 history";
  el.innerHTML = '<input class="filter" placeholder="Search sessions…"><div class="list"><div class="empty">Loading…</div></div>';
  showPop(el, anchor, { key: "history" });
  el.style.bottom = ""; el.style.top = `${$("ccHead").getBoundingClientRect().bottom - $("claude").getBoundingClientRect().top + 4}px`;
  el.style.left = "8px"; el.style.right = "8px";
  let all = [];
  try { all = (await ccGet("sessions")).sessions; } catch (e) { fail(e); }
  const draw = () => {
    const q = el.querySelector(".filter").value.toLowerCase();
    const day = (t) => { const d = (Date.now() / 1000 - t) / 86400; return d < 1 && new Date(t * 1000).getDate() === new Date().getDate() ? "Today" : d < 2 ? "Yesterday" : d < 7 ? "Past week" : "Older"; };
    let last = "";
    el.querySelector(".list").innerHTML = all.filter((s) => s.title.toLowerCase().includes(q)).map((s) => {
      const g = day(s.mtime), head = g !== last ? `<div class="sh">${g}</div>` : ""; last = g;
      return `${head}<div class="it ri${s.current ? " sel" : ""}" data-id="${s.id}"><span class="l">${escapeHtml(s.title)}</span><span class="r dim">${ago(s.mtime)}</span></div>`;
    }).join("") || '<div class="empty">No conversations yet</div>';
  };
  draw();
  el.querySelector(".filter").oninput = draw;
  el.querySelector(".filter").focus();
  el.querySelector(".list").onclick = async (e) => {
    const it = e.target.closest(".it"); if (!it) return;
    closePop();
    try { await cc("resume", { id: it.dataset.id }); } catch (er) { fail(er); }
  };
}

// ---- 巻き戻し（Rewind）----
async function rewindList() {
  const list = users.filter((u) => u.uuid).slice().reverse();
  if (!list.length) return showToast("Nothing to rewind yet", "", 3000);
  const html = `<div class="ccrw">${list.map((u, i) => `<div class="it" data-i="${i}"><div class="l">${escapeHtml(u.text.slice(0, 200) || "(attachment)")}</div><div class="dim">${u.t ? ago(u.t) : ""}</div></div>`).join("")}</div>`;
  const p = modal("Rewind", `<div class="dim" style="margin-bottom:8px">Choose the message to rewind to. The conversation and/or code go back to just before it.</div>${html}`, [{ label: "Cancel", value: null }]);
  document.querySelectorAll(".ccrw .it").forEach((d) => d.onclick = () => { document.querySelector("#mFoot button").click(); rewindAt(list[+d.dataset.i]); });
  await p;
}
export async function rewindAt(u) {
  if (st.busy) return showToast("Stop Claude before rewinding", "", 3000);
  if (!u.uuid) return showToast("この発言はまだ巻き戻せない（返答が始まってから）", "", 3000);
  const what = isCodex()
    ? await modal("Revert", `<div class="ccq">${escapeHtml(u.text)}</div>
      <div class="dim" style="margin-top:8px">Revert the chat and the files Codex changed to the point before this message.</div>`,
      [{ label: "Cancel", value: null }, { label: "Revert", value: "both", cls: "primary" }])
    : await modal("Rewind", `<div class="ccq">${escapeHtml(u.text)}</div>
    <div class="dim" style="margin-top:8px">Restore to the point before this message.</div>`,
    [{ label: "Never mind", value: null }, { label: "Restore code", value: "code" },
     { label: "Restore conversation", value: "conversation" }, { label: "Restore code and conversation", value: "both", cls: "primary" }]);
  if (!what) return;
  try {
    const r = await cc("rewind", { uuid: u.uuid, what });
    if (what !== "code") { $("ccText").value = r.prompt || u.text; (await composer()).fitInput(); $("ccText").focus(); }
    showToast(what === "conversation" ? "Conversation restored" : `Restored ${r.files?.length || 0} file(s)`, "ok", 3000);
  } catch (e) { fail(e); }
}

// ---- 書き出し ----
async function exportConversation() {
  const text = exportText();
  const v = await modal("Export conversation", `<pre class="ccexport">${escapeHtml(text.slice(0, 20000))}</pre>`,
    [{ label: "Cancel", value: null }, { label: "Save to file", value: "file" }, { label: "Copy to clipboard", value: "copy", cls: "primary" }]);
  if (v === "copy") { await navigator.clipboard.writeText(text); showToast("Copied", "ok", 2000); }
  else if (v === "file") {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    a.download = `${(st.title || "conversation").replace(/[\\/:*?"<>|]/g, "_")}.md`; a.click();
  }
}

// ---- アカウント・使用量 ----
async function accountUsage() {
  let u;
  try { u = await cc("control", { subtype: "get_usage" }); } catch (e) { return fail(e); }
  const name = { session: "Current session", weekly_all: "Current week (all models)", weekly_opus: "Current week (Opus)", weekly_sonnet: "Current week (Sonnet)" };
  const bars = (u.limits || []).map((l) => `<div class="ccbar-row"><div class="t"><b>${escapeHtml(name[l.kind] || l.kind)}</b><span>${l.percent}% used</span></div>
    <div class="bar"><span style="width:${Math.min(100, l.percent)}%" class="${l.severity}"></span></div>
    <div class="dim">${l.resets_at ? `Resets ${new Date(l.resets_at).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : ""}</div></div>`).join("");
  const s = u.session || {};
  modal("Account & usage", `<div class="ccusage"><div class="plan">Plan: <b>${escapeHtml(u.subscription_type || "—")}</b></div>${bars}
    <div class="dim" style="margin-top:10px">This session: $${(s.total_cost_usd || 0).toFixed(3)} · ${s.total_lines_added || 0} lines added · ${s.total_lines_removed || 0} removed</div></div>`, closeBtn);
}
async function status() {
  let r;
  try { r = await cc("control", { subtype: "get_status" }); } catch (e) { return fail(e); }
  modal("Status", (r.sections || []).map((s) => `<h4 class="cch">${escapeHtml(s.title)}</h4><table class="ccdata">${(s.rows || []).map((x) => `<tr><td>${escapeHtml(x.label)}</td><td>${escapeHtml(x.value)}</td></tr>`).join("")}</table>`).join("") || renderData(r), closeBtn);
}
async function fastMode() {
  if (st.fast && st.fast !== "off" && st.fast !== "on") return showToast(`Fast mode is unavailable (${escapeHtml(st.fast)})`, "", 4000);
  try {
    await cc("control", { subtype: "apply_flag_settings", settings: { fastMode: st.fast !== "on" } });
    st.fast = st.fast === "on" ? "off" : "on"; showToast(`Fast mode ${st.fast}`, "ok", 2500);
  } catch (e) { showToast(`Fast mode is unavailable: ${escapeHtml(e.message)}`, "err", 5000); }
}
async function mcpServers() {
  const draw = async () => {
    let r;
    try { r = await cc("control", { subtype: "mcp_status" }); } catch (e) { return fail(e); }
    const html = `<div class="ccmcp">${(r.mcpServers || []).map((s) => `<div class="srv" data-n="${escapeHtml(s.name)}">
      <span class="st ${s.status}"></span><div class="t"><b>${escapeHtml(s.name)}</b><div class="dim">${escapeHtml(s.status)} · ${(s.tools || []).length} tools · ${escapeHtml(s.scope || "")}</div></div>
      <button data-a="reconnect">Reconnect</button><button data-a="toggle">${s.status === "disabled" ? "Enable" : "Disable"}</button></div>`).join("") || '<div class="dim">No MCP servers</div>'}</div>`;
    const p = modal("MCP servers", html, closeBtn);
    document.querySelectorAll(".ccmcp .srv button").forEach((b) => b.onclick = async () => {
      const n = b.closest(".srv").dataset.n;
      try {
        if (b.dataset.a === "reconnect") await cc("control", { subtype: "mcp_reconnect", serverName: n });
        else await cc("control", { subtype: "mcp_toggle", serverName: n, enabled: b.textContent === "Enable" });
        document.querySelector("#mFoot button").click(); draw();
      } catch (e) { fail(e); }
    });
    await p;
  };
  draw();
}
async function dataDialog(title, subtype) {
  let r;
  try { r = await cc("control", { subtype }); } catch (e) { return fail(e); }
  modal(title, `<div class="ccdatawrap">${renderData(r)}</div>`, closeBtn);
}
async function slashCommands() {
  const html = `<div class="ccrw">${st.commands.map((c) => `<div class="it" data-n="${escapeHtml(c.name)}"><div class="l">/${escapeHtml(c.name)} <span class="dim">${escapeHtml(c.argumentHint || "")}</span></div><div class="dim">${escapeHtml((c.description || "").slice(0, 160))}</div></div>`).join("")}</div>`;
  const p = modal("Slash commands", html, closeBtn);
  document.querySelectorAll(".ccrw .it").forEach((d) => d.onclick = () => { document.querySelector("#mFoot button").click(); insertSlash(`/${d.dataset.n} `); });
  await p;
}
async function instructions() {
  const files = ["CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", ".claude/CLAUDE.md"];
  let have = [];
  try { have = (await api("/api/tree")).files.map((f) => f.path); } catch {}
  const html = `<div class="dim" style="margin-bottom:8px">Claude reads these files when a session starts (in the document's folder). ~/.claude/CLAUDE.md applies to every project.</div>
    <div class="ccrw">${files.map((f) => `<div class="it" data-f="${f}"><div class="l">${icon("file")} ${f}</div><div class="dim">${have.includes(f) ? "Open" : "Create"}</div></div>`).join("")}</div>`;
  const p = modal("Instructions", html, closeBtn);
  document.querySelectorAll(".ccrw .it").forEach((d) => d.onclick = async () => {
    document.querySelector("#mFoot button").click();
    const f = d.dataset.f;
    try {
      if (!have.includes(f)) await post("/api/newfile", { path: f });
      revealEditor(); await openTab(f);
      showToast("After editing, start a new conversation to apply the changes", "", 4000);
    } catch (e) { fail(e); }
  });
  await p;
}
