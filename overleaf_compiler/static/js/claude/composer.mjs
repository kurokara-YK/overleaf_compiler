// 入力欄（VS Code の拡張と同じ並び）。＋（添付）・／（操作の一覧）・モデル・モード・送る／止める・音声入力・@ でファイル・
// 添付（画像・PDF・文字のファイル）・エディタで見ている場所・許可の問い合わせ
import { $, api, escapeHtml, store, showToast, fail, bus } from "../util.mjs";
import { cm, active, saveAll } from "../editor.mjs";
import { st, cc, icon, modelInfo, modelLabel, MODES, showPop, closePop, popOpen, isCodex, NAME, optKey,
         modes, modeOrder, efforts, effortNow, effortLabel } from "./core.mjs";
import { actions, runAction } from "./dialogs.mjs";

const ta = () => $("ccText");
export const attach = [];   // { name, kind: image|pdf|text, media, data, text, dims }

// ---- 下の並びの表示 ----
export function renderBar() {
  const m = modelInfo();
  const noEffort = isCodex() ? !effortNow() : m && !m.supportsEffort;
  const eff = noEffort ? "" : ` <span class="dim">${escapeHtml(effortLabel())}</span>`;
  $("ccModelBtn").innerHTML = `${escapeHtml(modelLabel())}${eff}`;
  const md = modes()[st.opts.mode] || Object.values(modes())[0];
  $("ccModeBtn").innerHTML = `${icon(md.icon)}<span>${md.short || md.label}</span>`;
  // 入力欄の案内（Codex は拡張と同じく、最初とその後で変える）
  ta().placeholder = !isCodex() ? "Ctrl Esc to focus or unfocus Claude"
    : st.busy ? "Working…" : st.session ? "Ask for follow-up changes" : "Ask Codex anything. @ to use plugins or mention files";
  $("ccModeBtn").dataset.mode = st.opts.mode;
  $("ccInput").dataset.mode = st.opts.mode;
  $("ccSend").innerHTML = icon(st.busy ? "stop" : "send");
  $("ccSend").title = st.busy ? "Stop (Esc)" : "Send (Enter)";
  $("ccSend").classList.toggle("stop", st.busy);
  renderCtx();
}

// ---- エディタで見ている場所（ファイル名の札。目のアイコンで添えるかどうかを切り替える）----
let ctxOn = store.get("oc.ccCtx", "1") === "1";
function context() {
  if (!active || !ctxOn) return null;
  const sel = cm.getSelection(), from = cm.getCursor("from"), to = cm.getCursor("to");
  if (sel) {
    const range = from.line === to.line ? `${from.line + 1}` : `${from.line + 1}-${to.line + 1}`;
    const n = to.line - from.line + 1;
    return { label: `${active.path}#${range}`, chip: `${n} line${n > 1 ? "s" : ""} selected`,
             text: `［エディタ］${active.path} の ${range.replace("-", "〜")} 行目を選んでいる:\n\`\`\`\n${sel.slice(0, 12000)}\n\`\`\`` };
  }
  const line = cm.getCursor().line + 1;
  return { label: `${active.path}#${line}`, chip: active.path.split("/").pop(),
           text: `［エディタ］${active.path} の ${line} 行目を見ている` };
}
function renderCtx() {
  const b = $("ccCtxBtn");
  if (!active) { b.hidden = true; return; }
  b.hidden = false;
  const c = ctxOn ? context() : null;
  b.innerHTML = `${icon(ctxOn ? "eye" : "eyeoff")}<span>${escapeHtml(c ? c.chip : active.path.split("/").pop())}</span>`;
  b.classList.toggle("off", !ctxOn);
  b.title = ctxOn ? `${c ? c.label : ""} を添えて送る（クリックで添えない）` : "エディタの場所を添えない（クリックで添える）";
}
bus.on("cursor", renderCtx); bus.on("activate", renderCtx);
$("ccCtxBtn").onclick = () => { ctxOn = !ctxOn; store.set("oc.ccCtx", ctxOn ? "1" : "0"); renderCtx(); };

// ---- 添付 ----
function renderAttach() {
  const box = $("ccAttach");
  box.hidden = !attach.length;
  box.replaceChildren(...attach.map((a, i) => {
    const d = document.createElement("span");
    d.className = "achip";
    d.innerHTML = `${a.kind === "image" ? `<img src="data:${a.media};base64,${a.data}">` : icon("file")}<span class="n">${escapeHtml(a.name)}</span>${a.dims ? `<span class="dim">${a.dims}</span>` : ""}<button title="Remove">${icon("close")}</button>`;
    d.querySelector("button").onclick = () => { attach.splice(i, 1); renderAttach(); };
    return d;
  }));
}
const readAs = (file, how) => new Promise((ok, ng) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = ng; r[how](file); });
export async function addFiles(files) {
  for (const f of files) {
    try {
      if (f.type.startsWith("image/")) {
        const url = await readAs(f, "readAsDataURL");
        const img = new Image(); img.src = url; await img.decode().catch(() => {});
        attach.push({ name: f.name || "image.png", kind: "image", media: f.type, data: url.split(",")[1], dims: img.naturalWidth ? `${img.naturalWidth}×${img.naturalHeight}` : "" });
      } else if (f.type === "application/pdf") {
        const url = await readAs(f, "readAsDataURL");
        attach.push({ name: f.name, kind: "pdf", media: f.type, data: url.split(",")[1] });
      } else if (f.size < 2e6) {
        attach.push({ name: f.name, kind: "text", text: await readAs(f, "readAsText") });
      } else showToast(`${escapeHtml(f.name)} は大きすぎる（2 MB まで）`, "err");
    } catch (e) { fail(e); }
  }
  renderAttach(); ta().focus();
}
$("ccFileInput").onchange = (e) => { addFiles([...e.target.files]); e.target.value = ""; };
ta().addEventListener("paste", (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) { e.preventDefault(); addFiles(files); }
});
$("claude").addEventListener("dragover", (e) => { if (e.dataTransfer?.types.includes("Files")) { e.preventDefault(); $("ccInput").classList.add("drop"); } });
$("claude").addEventListener("dragleave", () => $("ccInput").classList.remove("drop"));
$("claude").addEventListener("drop", (e) => {
  $("ccInput").classList.remove("drop");
  if (e.dataTransfer?.files.length) { e.preventDefault(); addFiles([...e.dataTransfer.files]); }
});

// ---- 送る ----
export async function send() {
  const text = ta().value.trim();
  if (st.busy) return;
  if (!text && !attach.length) return;
  closePop();
  await saveAll();   // 直しかけの文面を Claude・Codex が読めるように先に保存する
  const slash = !isCodex() && text.startsWith("/");
  const c = slash ? null : context();
  const content = [];
  for (const a of attach) {
    if (a.kind === "image") content.push({ type: "image", source: { type: "base64", media_type: a.media, data: a.data } });
    else if (a.kind === "pdf") content.push({ type: "document", source: { type: "base64", media_type: a.media, data: a.data }, title: a.name });
    else content.push({ type: "text", text: `<file name="${a.name}">\n${a.text}\n</file>` });
  }
  content.push({ type: "text", text: c ? `${c.text}\n\n${text}` : text || "（添付を見て）" });
  const files = attach.map((a) => ({ name: a.name + (a.dims ? ` ${a.dims}` : "") }));
  st.busy = true; renderBar();
  try {
    await cc("send", { content, show: text, ctx: c ? c.label : "", files });
    ta().value = ""; attach.length = 0; renderAttach(); fitInput();
  } catch (e) { st.busy = false; renderBar(); fail(e); }
}
$("ccSend").onclick = () => st.busy ? cc("stop").catch(fail) : send();
export function fitInput() { const t = ta(); t.style.height = "auto"; t.style.height = `${Math.min(300, Math.max(44, t.scrollHeight))}px`; }

// ---- コンテキストの使用量（／の右の円。VS Code と同じく、残りが半分を切ったら出す。押すと /compact）----
export let usedPct = 0;   // コンテキストの使用量（%）。Codex の Compact の説明にも出す
export async function refreshUsage() {
  if (isCodex()) return;   // Codex は返答のたびに usage の出来事で届く（setUsage）
  if (!st.session) { $("ccUsageHost").hidden = true; return; }
  let r;
  try { r = await cc("control", { subtype: "get_context_usage" }); } catch { return; }
  setUsage(r.totalTokens, r.maxTokens);
}
export function setUsage(tokens, max) {
  const used = max > 0 ? Math.min(100, (tokens / max) * 100) : 0;
  usedPct = Math.round(used);
  const host = $("ccUsageHost");
  host.hidden = !max || used < 50;
  if (host.hidden) return;
  const R = 5, len = 2 * Math.PI * R;
  $("ccUsage").innerHTML = `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="${R}" stroke="currentColor" stroke-opacity=".15" stroke-width="1.5"/>
    <circle cx="10" cy="10" r="${R}" stroke="var(--c-clay)" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="${(len * used / 100).toFixed(2)} ${len.toFixed(2)}" transform="rotate(-90 10 10)"/></svg>`;
  $("ccUsage").setAttribute("aria-label", `${Math.round(used)}% context used — click to compact`);
  $("ccUsageTip").innerHTML = `${Math.round(100 - used)}% of context remaining until auto-compact.<span class="dim">Click to compact now.</span>`;
}
export function compact() {
  if (st.busy) return;
  $("ccUsageHost").hidden = true;
  if (isCodex()) return cc("compact").catch(fail);
  ta().value = "/compact"; send();
}
$("ccUsage").onclick = compact;

// ---- モデル・深さ・モード ----
export async function setOpt(o) {
  Object.assign(st.opts, o);
  for (const [k, v] of Object.entries(o)) store.set(optKey(k), String(v));
  renderBar();
  try { await cc("set", o); } catch (e) { fail(e); }
}
function effortRow() {
  const m = modelInfo(), list = efforts();
  const ok = isCodex() ? list.length > 0 : !m || !!m.supportsEffort;
  const d = document.createElement("div");
  d.className = "effort" + (ok ? "" : " dis");
  const i = list.indexOf(effortNow());
  d.innerHTML = `${icon("dumbbell")}<span>${isCodex() ? "Reasoning" : "Effort"} <span class="dim">(${ok ? effortLabel() : "Not supported"})</span></span>
    <span class="slider" title="${list.map((e) => effortLabel(e)).join(" / ")}">${list.map((e, k) =>
      `<span class="dot${k <= i ? " fill" : ""}${k === i ? " knob" : ""}" data-e="${e}"></span>`).join("")}</span>`;
  if (ok) d.querySelector(".slider").onclick = (ev) => {
    const e = ev.target.closest("[data-e]")?.dataset.e;
    if (e) { setOpt({ effort: e }); d.replaceWith(effortRow()); }
  };
  return d;
}
export function openModelMenu() {
  const el = document.createElement("div");
  el.className = "menu2 models";
  const list = document.createElement("div"); list.className = "list";
  // Codex は拡張と同じく「Select model」の見出しと、config.toml の既定（Default）を先頭に出す
  const items = isCodex() ? [{ value: "default", displayName: "Default", description: "Recommended set of models" }, ...st.models] : st.models;
  list.innerHTML = (isCodex() ? '<div class="sh">Select model</div>' : "") + items.map((m) => `<div class="it${m.value === st.opts.model ? " sel" : ""}" data-v="${escapeHtml(m.value)}">
      <div class="t"><div class="l">${escapeHtml(m.displayName)}</div><div class="d">${escapeHtml(m.description || "")}</div></div>
      ${m.value === st.opts.model ? icon("check", "ck") : ""}</div>`).join("") || '<div class="empty">Loading models…</div>';
  list.onclick = (e) => {
    const it = e.target.closest(".it"); if (!it) return;
    // Codex はモデルごとに選べる深さが違うので、選び直したら深さはそのモデルの既定に戻す
    setOpt(isCodex() ? { model: it.dataset.v, effort: "" } : { model: it.dataset.v }); closePop();
  };
  el.append(list, Object.assign(document.createElement("hr")), effortRow());
  showPop(el, $("ccModelBtn"), { align: "full", key: "model" });
  list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
}
export function openModeMenu() {
  const el = document.createElement("div");
  el.className = "menu2 modes";
  el.innerHTML = `<div class="hd"><span>${isCodex() ? "How should Codex actions be approved?" : "Modes"}</span><span class="kb"><kbd>⇧</kbd> + <kbd>tab</kbd> to switch</span></div>`;
  const order = st.opts.mode === "bypassPermissions" ? [...modeOrder(), "bypassPermissions"] : modeOrder();
  for (const k of order) {
    const m = modes()[k], it = document.createElement("div");
    it.className = "it" + (k === st.opts.mode ? " sel" : "");
    it.innerHTML = `<span class="mi">${icon(m.icon)}</span><div class="t"><div class="l">${m.label}</div><div class="d">${m.desc}</div></div>${k === st.opts.mode ? icon("check", "ck") : ""}`;
    it.onclick = () => { setOpt({ mode: k }); closePop(); };
    el.append(it);
  }
  if (!isCodex()) el.append(document.createElement("hr"), effortRow());
  showPop(el, $("ccModeBtn"), { align: "right", key: "mode" });
}
$("ccModelBtn").onclick = () => popOpen()?.key === "model" ? closePop() : openModelMenu();
$("ccModeBtn").onclick = () => popOpen()?.key === "mode" ? closePop() : openModeMenu();
export function cycleMode() {
  const order = modeOrder(), i = order.indexOf(st.opts.mode);
  setOpt({ mode: order[(i + 1) % order.length] });
}

// ---- ＋（Upload from computer / Add context / Browse the web）----
$("ccPlus").onclick = () => {
  if (popOpen()?.key === "plus") return closePop();
  const el = document.createElement("div");
  el.className = "menu2 plus";
  el.innerHTML = (isCodex()
    ? [["files", "file", "Files and folders", "Add files and more (@)"],
       ["upload", "upload", "Upload image", "Attach images from your computer"]]
    : [["upload", "upload", "Upload from computer", "Attach files from your computer"],
       ["files", "file", "Add context", "Add files or folders to the conversation"],
       ["browser", "globe", "Browse the web", "Ask Claude to look something up on the web"]])
    .map(([id, ic, l, t]) => `<div class="it ri" data-id="${id}" title="${t}">${icon(ic)}<span class="l">${l}</span></div>`).join("");
  el.onclick = (e) => {
    const id = e.target.closest(".it")?.dataset.id; if (!id) return;
    closePop();
    if (id === "upload") $("ccFileInput").click();
    else if (id === "files") insertAt("@");
    else { insertText("Search the web: "); }
  };
  showPop(el, $("ccPlus"), { key: "plus" });
};
function insertText(s) { const t = ta(); t.focus(); t.setRangeText(s, t.selectionStart, t.selectionEnd, "end"); fitInput(); }
export function insertAt(ch) { insertText(ch); trigger(); }

// ---- ／（Filter actions…）と、入力の先頭の / ・途中の @ ----
let menuState = null;   // { kind: cmd|mention, items, idx, fromText }
function cmdItems(filter) {
  const f = filter.toLowerCase();
  const groups = {};
  for (const a of actions()) {
    if (a.filterOnly && !f) continue;
    if (f && !(`${a.label} ${a.desc || ""}`.toLowerCase().includes(f))) continue;
    (groups[a.section] ||= []).push(a);
  }
  return groups;
}
function renderCmd(el, filter) {
  const groups = cmdItems(filter);
  const list = el.querySelector(".list");
  const flat = [];
  list.innerHTML = Object.entries(groups).map(([sec, items], gi) =>
    `${gi ? '<div class="sep"></div>' : ""}<div class="sh">${escapeHtml(sec)}</div>` + items.map((a) => {
      flat.push(a);
      return `<div class="it ri" data-i="${flat.length - 1}" title="${escapeHtml(a.desc || "")}"><span class="l">${escapeHtml(a.label)}${a.hint ? ` <span class="dim">${escapeHtml(a.hint)}</span>` : ""}</span>${a.right ? `<span class="r">${a.right()}</span>` : ""}</div>`;
    }).join("")).join("") || '<div class="empty">No matching commands</div>';
  menuState.items = flat; menuState.idx = Math.min(menuState.idx, Math.max(0, flat.length - 1));
  highlight(el);
}
function highlight(el) {
  el.querySelectorAll(".it").forEach((it) => it.classList.toggle("hi", +it.dataset.i === menuState.idx));
  el.querySelector(".it.hi")?.scrollIntoView({ block: "nearest" });
}
export function openCmdMenu(fromText = false) {
  const el = document.createElement("div");
  el.className = "menu2 cmd";
  el.innerHTML = `${fromText ? "" : `<input class="filter" placeholder="${isCodex() ? "Search" : "Filter actions…"}">`}<div class="list"></div>`;
  // 前のメニューを閉じると menuState が消えるので、出してから入れる
  showPop(el, $("ccSlash"), { align: "full", key: "cmd", onClose: () => { menuState = null; } });
  menuState = { kind: "cmd", items: [], idx: 0, fromText };
  const input = el.querySelector(".filter");
  renderCmd(el, fromText ? ta().value.slice(1) : "");
  el.querySelector(".list").onclick = (e) => { const it = e.target.closest(".it"); if (it) pick(+it.dataset.i); };
  el.querySelector(".list").onmousemove = (e) => { const it = e.target.closest(".it"); if (it && +it.dataset.i !== menuState.idx) { menuState.idx = +it.dataset.i; highlight(el); } };
  if (input) {
    input.oninput = () => { menuState.idx = 0; renderCmd(el, input.value); };
    input.onkeydown = (e) => navKey(e);
    setTimeout(() => input.focus(), 0);
  }
}
$("ccSlash").onclick = () => popOpen()?.key === "cmd" ? closePop() : openCmdMenu(false);

// @ のあとの文字でファイルを絞り込む
let treeCache = null;
async function projectFiles() {
  if (!treeCache) { try { treeCache = (await api("/api/tree")).files.map((f) => f.path + (f.dir ? "/" : "")); } catch { treeCache = []; } setTimeout(() => { treeCache = null; }, 15000); }
  return treeCache;
}
async function openMention(q) {
  const files = (await projectFiles()).filter((p) => p.toLowerCase().includes(q.toLowerCase())).slice(0, 50);
  let el = popOpen()?.key === "mention" ? popOpen().el : null;
  if (!el) {
    el = document.createElement("div"); el.className = "menu2 cmd mention";
    el.innerHTML = '<div class="list"></div>';
    showPop(el, $("ccSlash"), { align: "full", key: "mention", onClose: () => { menuState = null; } });
    menuState = { kind: "mention", items: [], idx: 0, fromText: true };
    el.querySelector(".list").onclick = (e) => { const it = e.target.closest(".it"); if (it) pick(+it.dataset.i); };
  }
  menuState.items = files.map((p) => ({ path: p })); menuState.idx = 0;
  el.querySelector(".list").innerHTML = files.map((p, i) => `<div class="it ri" data-i="${i}">${icon(p.endsWith("/") ? "plan" : "file")}<span class="l">${escapeHtml(p.split("/").filter(Boolean).pop())}</span><span class="r dim">${escapeHtml(p)}</span></div>`).join("")
    || '<div class="empty">No matching files</div>';
  highlight(el);
}
function mentionQuery() {
  const t = ta(), before = t.value.slice(0, t.selectionStart);
  const m = before.match(/(?:^|\s)@([^\s@]*)$/);
  return m ? m[1] : null;
}
function trigger() {
  const t = ta(), q = mentionQuery();
  if (q != null) return openMention(q);
  if (/^\/\S*$/.test(t.value) && t.selectionStart === t.value.length) {
    if (popOpen()?.key === "cmd" && menuState?.fromText) { menuState.idx = 0; renderCmd(popOpen().el, t.value.slice(1)); }
    else openCmdMenu(true);
    return;
  }
  if (menuState?.fromText) closePop();
}
function pick(i) {
  const s = menuState; if (!s) return;
  const it = s.items[i]; if (!it) return;
  if (s.kind === "mention") {
    const t = ta(), before = t.value.slice(0, t.selectionStart), q = mentionQuery() ?? "";
    t.setRangeText(`@${it.path} `, before.length - q.length - 1, t.selectionStart, "end");
    closePop(); t.focus(); fitInput(); return;
  }
  if (s.fromText) { ta().value = ""; }
  if (!it.keepOpen) closePop();
  runAction(it);
  if (it.keepOpen && popOpen()?.key === "cmd") renderCmd(popOpen().el, popOpen().el.querySelector(".filter")?.value || "");
}
function navKey(e) {
  if (!menuState) return false;
  const n = menuState.items.length;
  if (e.key === "ArrowDown") { menuState.idx = (menuState.idx + 1) % Math.max(1, n); }
  else if (e.key === "ArrowUp") { menuState.idx = (menuState.idx - 1 + n) % Math.max(1, n); }
  else if ((e.key === "Enter" || e.key === "Tab") && !e.isComposing && n) { e.preventDefault(); pick(menuState.idx); return true; }
  else if (e.key === "Escape") { e.preventDefault(); closePop(); ta().focus(); return true; }
  else return false;
  e.preventDefault(); highlight(popOpen().el); return true;
}
ta().addEventListener("input", () => { fitInput(); trigger(); });
ta().addEventListener("keydown", (e) => {
  if (menuState && navKey(e)) return;
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); send(); }
  else if (e.key === "Tab" && e.shiftKey) { e.preventDefault(); cycleMode(); }
  else if (e.key === "Escape" && st.busy) { e.preventDefault(); cc("stop").catch(fail); }
});

// ---- 音声入力（ブラウザの音声認識）----
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;
$("ccMic").onclick = () => {
  if (rec) { rec.stop(); return; }
  if (!SR) return showToast("このブラウザは音声入力（Web Speech API）に対応していない", "err", 5000);
  rec = new SR();
  rec.lang = "ja-JP"; rec.interimResults = true; rec.continuous = true;
  const base = ta().value;
  rec.onresult = (ev) => { let s = ""; for (const r of ev.results) s += r[0].transcript; ta().value = base + s; fitInput(); };
  rec.onerror = (ev) => showToast(ev.error === "network" ? "音声認識のサーバにつながらない（Vivaldi では使えないことがある。Chrome なら使える）"
    : ev.error === "not-allowed" ? "マイクが許可されていない" : `音声入力のエラー: ${ev.error}`, "err", 7000);
  rec.onend = () => { rec = null; $("ccMic").classList.remove("on"); ta().focus(); };
  rec.start(); $("ccMic").classList.add("on");
};

// ---- 許可の問い合わせ（入力欄の代わりに出す）----
const perms = [];   // まだ答えていない問い合わせ
export function askPermission(e) { if (!perms.some((p) => p.id === e.id)) { perms.push(e); renderPerm(); } }
export function permissionDone(id) { const i = perms.findIndex((p) => p.id === id); if (i >= 0) perms.splice(i, 1); renderPerm(); }
async function answer(p, body) {
  try { await cc("permission", { id: p.id, ...body }); } catch (e) { fail(e); }
  permissionDone(p.id);
}
function renderPerm() {
  const box = $("ccPerm"), p = perms[0];
  box.hidden = !p; $("ccInput").hidden = !!p;
  if (!p) { box.replaceChildren(); ta().focus(); return; }
  const i = p.input || {};
  const target = p.path ? `<a class="file" data-path="${escapeHtml(p.path)}">${escapeHtml(p.path)}</a>` : "";
  let body = "", opts;
  if (p.name === "AskUserQuestion") return renderQuestions(p);
  if (p.options) return renderCodexPerm(p);
  if (p.name === "ExitPlanMode") {
    box.innerHTML = `<div class="q">Ready to code?</div><div class="pbody md plan"></div><div class="opts"></div>
      <input class="tell" placeholder="Tell ${NAME()} what to change">`;
    import("/static/marked/marked.esm.js").then(({ marked }) => { box.querySelector(".plan").innerHTML = marked.parse(escapeHtml(i.plan || "")); });
    opts = [["Yes, and auto-accept edits", async () => { await setOpt({ mode: "acceptEdits" }); answer(p, { behavior: "allow" }); }],
            ["Yes, and manually approve edits", async () => { await setOpt({ mode: "default" }); answer(p, { behavior: "allow" }); }],
            ["No, keep planning", () => answer(p, { behavior: "deny", message: box.querySelector(".tell").value || "Keep planning" })]];
  } else {
    if (p.name === "Bash") body = `<div class="io"><div class="iorow"><span class="l">IN</span><pre>${escapeHtml(i.command || "")}</pre></div></div>${i.description ? `<div class="pd">${escapeHtml(i.description)}</div>` : ""}`;
    else if (p.old != null || p.new != null) body = diffHtml(p.old ?? "", p.new ?? "");
    else if (p.what && !p.path) body = `<div class="pd">${escapeHtml(p.what)}</div>`;
    const sug = (p.suggestions || [])[0];
    const always = sug?.type === "setMode" && sug.mode === "acceptEdits" ? "Yes, allow all edits during this session"
      : sug?.type === "addRules" ? `Yes, and don't ask again for ${escapeHtml((sug.rules || []).map((r) => r.ruleContent || r.toolName).join(", ") || p.name)}`
      : sug ? "Yes, and don't ask again this session" : null;
    box.innerHTML = `<div class="q">Allow Claude to <b>${escapeHtml(p.title || p.name)}</b> ${target}?</div>
      <div class="pbody">${body}</div><div class="opts"></div><input class="tell" placeholder="Tell Claude what to do instead">`;
    opts = [["Yes", () => answer(p, { behavior: "allow" })],
            ...(always ? [[always, () => { if (sug?.type === "setMode") st.opts.mode = sug.mode; answer(p, { behavior: "allow", always: true }); }]] : []),
            ["No", () => answer(p, { behavior: "deny", message: box.querySelector(".tell").value })]];
  }
  const o = box.querySelector(".opts");
  opts.forEach(([label, fn], k) => {
    const b = document.createElement("button");
    b.className = "opt" + (k === 0 ? " first" : "");
    b.innerHTML = `<span class="n">${k + 1}</span><span>${label}</span>`;
    b.onclick = fn; o.append(b);
  });
  const tell = box.querySelector(".tell");
  tell.onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing && tell.value.trim()) { e.preventDefault(); o.lastChild.click(); } };
  box.onkeydown = (e) => {
    if (e.target === tell) return;
    const k = parseInt(e.key); if (k >= 1 && k <= opts.length) { e.preventDefault(); o.children[k - 1].click(); }
    if (e.key === "Escape") { e.preventDefault(); o.lastChild.click(); }
  };
  box.tabIndex = -1; setTimeout(() => box.querySelector(".opt")?.focus(), 0);
}
function renderQuestions(p) {
  const box = $("ccPerm"), qs = p.input.questions || [];
  const picked = qs.map(() => new Set());
  box.innerHTML = qs.map((q, qi) => `<div class="qq" data-q="${qi}"><div class="qh">${escapeHtml(q.header || "")}</div><div class="q">${escapeHtml(q.question)}</div>
    <div class="opts">${(q.options || []).map((o, oi) => `<button class="opt" data-o="${oi}"><span class="n">${oi + 1}</span><span><b>${escapeHtml(o.label)}</b>${o.description ? `<br><span class="dim">${escapeHtml(o.description)}</span>` : ""}</span></button>`).join("")}</div>
    <input class="other" placeholder="Other…"></div>`).join("") + '<div class="qfoot"><button class="skip">Skip</button><button class="submit">Submit</button></div>';
  box.querySelectorAll(".qq").forEach((qd) => {
    const qi = +qd.dataset.q, multi = qs[qi].multiSelect;
    qd.querySelectorAll(".opt").forEach((b) => b.onclick = () => {
      const oi = +b.dataset.o;
      if (!multi) picked[qi].clear();
      picked[qi].has(oi) ? picked[qi].delete(oi) : picked[qi].add(oi);
      qd.querySelectorAll(".opt").forEach((x) => x.classList.toggle("on", picked[qi].has(+x.dataset.o)));
    });
  });
  box.querySelector(".submit").onclick = () => {
    const answers = {};
    qs.forEach((q, qi) => {
      const other = box.querySelector(`.qq[data-q="${qi}"] .other`).value.trim();
      const labels = [...picked[qi]].map((oi) => q.options[oi].label);
      if (other) labels.push(other);
      answers[q.question] = labels.join(", ");
    });
    answer(p, { behavior: "allow", input: { ...p.input, answers } });
  };
  box.querySelector(".skip").onclick = () => answer(p, { behavior: "deny", message: "The user skipped the question" });
}
function diffHtml(a, b) {
  const x = a ? a.split("\n") : [], y = b.split("\n");
  let s = 0; while (s < x.length && s < y.length && x[s] === y[s]) s++;
  let t = 0; while (t < x.length - s && t < y.length - s && x[x.length - 1 - t] === y[y.length - 1 - t]) t++;
  return `<div class="diff">${[...x.slice(s, x.length - t).map((l) => `<div class="del"><span class="m">-</span>${escapeHtml(l) || " "}</div>`),
    ...y.slice(s, y.length - t).map((l) => `<div class="ins"><span class="m">+</span>${escapeHtml(l) || " "}</div>`)].join("")}</div>`;
}
// Codex の承認（拡張と同じく「Yes / Yes, and don't ask again this session / No, and tell Codex what to do differently」）
function renderCodexPerm(p) {
  const box = $("ccPerm"), i = p.input || {};
  const target = p.path ? ` <a class="file" data-path="${escapeHtml(p.path)}">${escapeHtml(p.path)}</a>` : "";
  const q = p.name === "Bash" ? "Allow Codex to run this command?" : p.name === "Edit" ? `Allow Codex to edit${target}?` : "Allow Codex to continue?";
  const body = p.name === "Bash" ? `<div class="io"><div class="iorow"><span class="l">IN</span><pre>${escapeHtml(i.command || "")}</pre></div></div>`
    : p.diff ? udiffHtml(p.diff) : p.what ? `<div class="pd">${escapeHtml(p.what)}</div>` : "";
  box.innerHTML = `<div class="q">${q}</div><div class="pbody">${body}${p.description ? `<div class="pd">${escapeHtml(p.description)}</div>` : ""}</div>
    <div class="opts"></div><input class="tell" placeholder="Tell Codex what to do differently">`;
  const o = box.querySelector(".opts"), tell = box.querySelector(".tell");
  p.options.forEach(([label, decision], k) => {
    const b = document.createElement("button");
    b.className = "opt" + (k === 0 ? " first" : "");
    b.innerHTML = `<span class="n">${k + 1}</span><span>${escapeHtml(label)}</span>`;
    b.onclick = () => answer(p, { decision, behavior: decision.startsWith("accept") ? "allow" : "deny", message: decision === "decline" ? tell.value : "" });
    o.append(b);
  });
  tell.onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing && tell.value.trim()) { e.preventDefault(); o.lastChild.click(); } };
  box.onkeydown = (e) => {
    if (e.target === tell) return;
    const k = parseInt(e.key); if (k >= 1 && k <= p.options.length) { e.preventDefault(); o.children[k - 1].click(); }
    if (e.key === "Escape") { e.preventDefault(); o.lastChild.click(); }
  };
  box.tabIndex = -1; setTimeout(() => box.querySelector(".opt")?.focus(), 0);
}
// 統一形式の差分（Codex のファイル変更）を、消した行は赤・足した行は緑で出す
export function udiffHtml(diff) {
  const lines = String(diff || "").split("\n").filter((l) => !/^(---|\+\+\+|diff |index )/.test(l));
  return `<div class="diff">${lines.map((l) => {
    const c = l.startsWith("+") ? "ins" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "same" : "";
    return `<div class="${c}"><span class="m">${c === "ins" ? "+" : c === "del" ? "-" : " "}</span>${escapeHtml(c && c !== "same" ? l.slice(1) : l) || " "}</div>`;
  }).join("") || '<div class="same">(no changes)</div>'}</div>`;
}
export function clearPerms() { perms.length = 0; renderPerm(); }
