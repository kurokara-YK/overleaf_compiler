// 会話の表示（VS Code の拡張と同じ、左に点の付いた縦の並び）。発言・返答・考えた内容・道具の呼び出しと結果・許可の問い合わせ
import { Marked } from "/static/marked/marked.esm.js";
import { $, escapeHtml, fail } from "../util.mjs";
import { openTab } from "../editor.mjs";
import { revealEditor } from "../panels.mjs";
import { st, icon, logo, isCodex, NAME } from "./core.mjs";

const log = () => $("ccLog");
// 返答の Markdown。HTML はそのまま出さず文字にする
const md = new Marked({ gfm: true, breaks: false, renderer: { html: (t) => escapeHtml(typeof t === "string" ? t : t.text) } });
const VERBS = ["Thinking", "Pondering", "Crafting", "Brewing", "Computing", "Cooking", "Creating", "Forging", "Honking",
  "Mulling", "Noodling", "Percolating", "Puzzling", "Reticulating", "Simmering", "Synthesizing", "Tinkering", "Working"];

let cur = null;           // 書いている途中の返答 { el, raw }
const tools = new Map();  // 道具の呼び出しの id → その表示
let lastUser = null;      // 最後の発言の表示（uuid を後から付ける）
export const users = [];  // 発言（Rewind の一覧に使う）{ el, text, uuid, t }
const transcript = [];    // 書き出し用（Export conversation）

export function clearLog() {
  away = false;
  log().replaceChildren(welcome()); cur = null; tools.clear(); lastUser = null; users.length = 0; transcript.length = 0;
  spinner(false);
}
function welcome() {
  const d = document.createElement("div");
  d.id = "ccWelcome";
  d.innerHTML = isCodex() ? `<div class="wt cx">${logo()}<span>Codex</span></div>
    <div class="ws">Ask Codex anything. @ to use plugins or mention files<br>`
    : `<img class="clawd" src="/claude-asset/clawd.svg" alt="" onerror="this.remove()">
    <div class="wt">${logo()}<span>Claude Code</span></div>
    <div class="ws">What to do first? Ask about this document, or ask Claude to fix something.<br>
    開いているファイルとカーソルの位置（選んでいれば選んだ行）を添えて送ります。直したファイルは自動で組み直されます。</div>`;
  return d;
}
function add(cls, html = "", before = null) {
  $("ccWelcome")?.remove();
  const d = document.createElement("div");
  d.className = cls; d.innerHTML = html;
  log().insertBefore(d, before || $("ccSpin"));
  return d;
}

// ---- 下へ追いかける（VS Code の Claude Code と同じ仕組み）----
// 一番下から MD px 以内なら、中身が増えるたびに一番下へ移る。人が上へスクロールしたら（ホイール・キー・スクロールバー）
// 「離れた」として追いかけるのをやめ、また一番下の近くまで戻したら追いかける。送ったときは必ず一番下へ戻る
const MD = 50;
let away = false;
const dist = (l) => l.scrollHeight - l.scrollTop - l.clientHeight;
function follow() { const l = log(); if (!away && dist(l) > 0) l.scrollTop = l.scrollHeight; }
export function toBottom() { away = false; const l = log(); l.scrollTop = l.scrollHeight; }
// ホイールを回した所が、内側でスクロールできる箱（長い出力・差分）なら、そちらのスクロールとみなす
function innerScrolls(target, up) {
  for (let el = target instanceof Element ? target : null; el && el !== log(); el = el.parentElement) {
    if (el.scrollHeight > el.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(el).overflowY)
        && (up ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1)) return true;
  }
  return false;
}
(() => {
  const l = log();
  let lastTop = l.scrollTop, lastH = l.scrollHeight, dir = null, dirAt = 0, touchY = null;
  const up = () => { if (l.scrollTop > 0) { away = true; dir = "up"; dirAt = Date.now(); } };
  const down = () => { dir = "down"; dirAt = Date.now(); if (dist(l) < MD) away = false; };
  l.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.shiftKey || Math.abs(e.deltaY) <= Math.abs(e.deltaX) || innerScrolls(e.target, e.deltaY < 0)) return;
    if (e.deltaY < 0) up(); else down();
  }, { passive: true });
  l.addEventListener("touchstart", (e) => { touchY = e.touches[0]?.clientY ?? null; }, { passive: true });
  l.addEventListener("touchmove", (e) => {
    const y = e.touches[0]?.clientY;
    if (y === undefined || touchY === null || y === touchY) return;
    const goingUp = y > touchY; touchY = y;
    if (!innerScrolls(e.target, goingUp)) { if (goingUp) up(); else down(); }
  }, { passive: true });
  l.addEventListener("keydown", (e) => {
    if (["ArrowUp", "PageUp", "Home"].includes(e.key)) up();
    else if (["ArrowDown", "PageDown", "End"].includes(e.key)) down();
  });
  l.addEventListener("scroll", () => {   // スクロールバーを動かしたとき
    const top = l.scrollTop, d = dist(l), grew = l.scrollHeight - lastH;
    const recent = Date.now() - dirAt < 300 ? dir : null;
    const byContent = recent === null && grew > 0 && Math.abs(top - lastTop - grew) <= 1;   // 追いかけて動いただけ
    const wentUp = top < lastTop, wentDown = top > lastTop;
    lastTop = top; lastH = l.scrollHeight; dir = null;
    if (wentUp) { if (grew < 0 && d > 1 && recent !== "up") return; away = d > 1 || recent === "up"; }
    else if (wentDown && d < MD && recent !== "up" && !byContent) away = false;
  }, { passive: true });
  // 中身が変わったら（返答が伸びた・道具の結果が出た・たたんだ箱を開いた）、離れていなければ一番下へ
  new MutationObserver(() => requestAnimationFrame(follow)).observe(l, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class", "open"] });
  new ResizeObserver(() => follow()).observe(l);
})();

// ---- 返答中の表示（✻ Thinking… esc to interrupt）----
let verbTimer = 0;
export function spinner(on, text) {
  let s = $("ccSpin");
  if (!s) { s = document.createElement("div"); s.id = "ccSpin"; log().append(s); }
  s.classList.toggle("on", on);
  if (!on) { clearInterval(verbTimer); verbTimer = 0; return; }
  if (text) { s.innerHTML = `<span class="star">✻</span><span class="v">${escapeHtml(text)}…</span>`; return; }
  if (isCodex()) {   // Codex の拡張と同じく「Working」
    s.innerHTML = '<span class="v shimmer">Working</span><span class="k">esc to interrupt</span>';
    log().append(s); follow(); return;
  }
  if (!verbTimer) {
    const pick = () => { s.innerHTML = `<span class="star">✻</span><span class="v">${VERBS[Math.floor(Math.random() * VERBS.length)]}…</span><span class="k">esc to interrupt</span>`; };
    pick(); verbTimer = setInterval(pick, 4000);
  }
  log().append(s); follow();
}

function paint(c) {
  c.el.querySelector(".md").innerHTML = md.parse(c.raw);
  c.el.querySelectorAll(".md a").forEach((a) => { a.target = "_blank"; a.rel = "noopener"; });
  follow();
}
// 書いている途中は、次の描画のときにまとめて描く
let raf = 0;
function renderCur() {
  if (raf) return;
  const c = cur;
  raf = requestAnimationFrame(() => { raf = 0; paint(c); });
}
const newText = () => ({ el: add("ccm text", '<div class="md"></div>'), raw: "" });

// ---- 出来事を1つ出す ----
export function show(e) {
  switch (e.k) {
    case "user": {
      cur = null;
      const files = (e.files || []).map((f) => `<span class="chip">${icon("file")}${escapeHtml(f.name || "")}</span>`).join("");
      const d = add("ccm user", `${e.ctx ? `<div class="ctx">${icon("file")}${escapeHtml(e.ctx)}</div>` : ""}${files ? `<div class="files">${files}</div>` : ""}<div class="bubble">${escapeHtml(e.text)}</div>`);
      d.title = "Click to rewind to here";
      const u = { el: d, text: e.text, uuid: e.uuid || null, t: e.t };
      d.onclick = () => import("./dialogs.mjs").then((m) => m.rewindAt(u));
      users.push(u); lastUser = u; transcript.push(`## User\n\n${e.text}\n`);
      toBottom();   // 送ったら必ず一番下へ
      break;
    }
    case "uuid": if (lastUser && !lastUser.uuid) lastUser.uuid = e.uuid; break;
    case "block":
      if (e.kind === "text") cur = newText();
      break;
    case "delta":
      if (!cur) cur = newText();
      cur.raw += e.text; renderCur();
      break;
    case "text":   // 1つのまとまりが書き終わった。途中の表示を完成した文で置き換える
      if (!cur) cur = newText();
      cur.raw = e.text; paint(cur); cur = null; transcript.push(`## ${NAME()}\n\n${e.text}\n`);
      break;
    case "thinking": {
      cur = null;
      const d = add("ccm thinking", `<details><summary>Thinking</summary><div class="md"></div></details>`);
      d.querySelector(".md").innerHTML = md.parse(e.text);
      break;
    }
    case "tool": cur = null; showTool(e); break;
    case "result": showResult(e); break;
    case "permission": cur = null; import("./composer.mjs").then((m) => m.askPermission(e)); break;
    case "permission_done": {
      import("./composer.mjs").then((m) => m.permissionDone(e.id));
      if (e.behavior === "deny") add("ccm note warn", escapeHtml(e.message ? `Denied: ${e.message}` : "Denied by user"));
      break;
    }
    case "done":
      cur = null;
      if (!e.stop && e.subtype === "error_during_execution") add("ccm note warn", "Interrupted by user");
      else if (e.error) add("ccm note err", escapeHtml(e.result || `Error: ${e.subtype}`));
      break;
    case "note": add("ccm note", escapeHtml(e.text)); break;
    case "commands": st.commands = e.commands || []; break;   // Skill を除いたスラッシュコマンド（会話の始めで分かる）
    case "usage": import("./composer.mjs").then((m) => m.setUsage(e.used, e.window)); break;
    case "limits": import("./dialogs.mjs").then((m) => m.setLimits(e)); break;
    case "error": cur = null; add("ccm note err", escapeHtml(e.text)); break;
  }
}

// ---- 道具の呼び出し ----
const LABEL = { TodoWrite: "Update Todos", Task: "Agent", AskUserQuestion: "Ask", ExitPlanMode: "Plan" };
function showTool(e) {
  const name = LABEL[e.name] || e.name;
  const target = e.path ? `<a class="file" data-path="${escapeHtml(e.path)}">${escapeHtml(e.path)}</a>`
    : e.what ? `<span class="arg">${escapeHtml(e.what)}</span>` : "";
  const d = add("ccm tool", `<div class="th"><b>${escapeHtml(name)}</b> ${target}</div>`);
  d.dataset.name = e.name;
  const i = e.input || {};
  if (e.name === "Bash") {   // 長いコマンド（Codex に多い）は、押すと開く形にたたむ
    d.append(box([["IN", i.command || ""]], String(i.command || "").split("\n").length > 4));
  } else if (e.diff != null) {   // Codex のファイル変更（統一形式の差分）
    import("./composer.mjs").then((m) => {
      const w = document.createElement("div"); w.innerHTML = m.udiffHtml(e.diff);
      const dd = w.firstChild; if (dd.children.length > 14) { dd.classList.add("fold"); dd.onclick = () => dd.classList.toggle("fold"); }
      d.append(dd); follow();
    });
  } else if (e.old != null || e.new != null) {
    d.append(diffBox(e.old ?? "", e.new ?? "", e.name === "Write"));
  } else if (e.name === "TodoWrite") {
    const ul = document.createElement("ul"); ul.className = "todos";
    ul.innerHTML = (i.todos || []).map((t) => `<li class="${t.status}"><span class="cb">${t.status === "completed" ? "☑" : t.status === "in_progress" ? "◐" : "☐"}</span>${escapeHtml(t.content || "")}</li>`).join("");
    d.append(ul);
  } else if (e.name === "ExitPlanMode" && i.plan) {
    const p = document.createElement("div"); p.className = "plan md"; p.innerHTML = md.parse(i.plan); d.append(p);
  } else if ((e.name === "Task" || e.name === "Agent") && i.prompt) {
    d.append(box([["IN", i.prompt]], true));
  }
  tools.set(e.id, d);
  transcript.push(`> ${name} ${e.path || e.what || ""}\n`);
}
function showResult(e) {
  const d = tools.get(e.id);
  if (!d) return;
  d.classList.add(e.error ? "err" : "ok");
  const name = d.dataset.name;
  if (name === "Bash") {
    d.querySelector(".io").append(ioRow("OUT", e.text || "(No output)", e.error));
  } else if (e.error || /^(Grep|Glob|WebFetch|WebSearch|Task|Agent|Skill)$/.test(name) || name.startsWith("mcp__")) {
    const b = box([[e.error ? "ERR" : "OUT", e.text || "(No output)"]], true);
    if (e.error) b.classList.add("errbox");
    d.append(b);
  } else if (name === "Read") {
    const n = (e.text.match(/\n/g) || []).length;
    d.querySelector(".th").insertAdjacentHTML("beforeend", `<span class="meta">${n ? `Read ${n} lines` : ""}</span>`);
  }
  follow();
}
function ioRow(label, text, err) {
  const r = document.createElement("div"); r.className = "iorow" + (err ? " err" : "");
  r.innerHTML = `<span class="l">${label}</span><pre></pre>`; r.querySelector("pre").textContent = text;
  return r;
}
function box(rows, collapsed = false) {
  const b = document.createElement("div"); b.className = "io" + (collapsed ? " fold" : "");
  rows.forEach(([l, t]) => b.append(ioRow(l, t)));
  if (collapsed) b.onclick = () => b.classList.toggle("fold");
  return b;
}
// 前後の同じ行は省いて、消した行（赤）と足した行（緑）を出す。行番号付き
function diffBox(a, b, whole) {
  const x = a ? a.split("\n") : [], y = b.split("\n");
  let s = 0; while (!whole && s < x.length && s < y.length && x[s] === y[s]) s++;
  let t = 0; while (!whole && t < x.length - s && t < y.length - s && x[x.length - 1 - t] === y[y.length - 1 - t]) t++;
  const rows = [...x.slice(s, x.length - t).map((l) => ["del", "-", l]), ...y.slice(s, y.length - t).map((l) => ["ins", "+", l])];
  const d = document.createElement("div"); d.className = "diff" + (rows.length > 14 ? " fold" : "");
  d.innerHTML = rows.map(([c, m, l]) => `<div class="${c}"><span class="m">${m}</span>${escapeHtml(l) || " "}</div>`).join("")
    || '<div class="same">(no changes)</div>';
  if (rows.length > 14) d.onclick = () => d.classList.toggle("fold");
  return d;
}
document.addEventListener("click", async (ev) => {
  const a = ev.target.closest("#ccLog a.file, #ccPerm a.file");
  if (!a) return;
  ev.preventDefault();
  revealEditor();
  try { await openTab(a.dataset.path); } catch (e) { fail(e); }
});

// 会話を Markdown にする（Export conversation）
export function exportText() {
  return [`# ${st.title || `${isCodex() ? "Codex" : "Claude Code"} conversation`}`, "", ...transcript].join("\n");
}
