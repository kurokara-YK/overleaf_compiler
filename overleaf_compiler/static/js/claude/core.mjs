// 右のチャット欄（Claude Code と Codex）の共通部分。状態・サーバとのやり取り・小さな部品（アイコン・浮かぶメニュー）
// st.engine が claude なら /api/claude/…（claude.py）、codex なら /api/codex/…（codex.py）と話す
import { $, api, post, escapeHtml, store } from "../util.mjs";

// サーバ（claude.py）の Chat と同じ内容を持つ。start の答えで埋まる
export const st = {
  engine: store.get("oc.engine", "claude") === "codex" ? "codex" : "claude",
  chat: null,   // 今のタブの番号（index.mjs）
  opts: { model: "default", effort: "medium", mode: "auto", thinking: true },
  models: [], commands: [], account: {}, fast: null,
  busy: false, session: null, title: "", epoch: -1, started: false,
};
// 今のタブ（st.chat）の会話に話す。サーバの chats.py がタブごとの Claude・Codex の会話へ振り分ける
export const cc = (name, body) => post(`/api/chat/${name}?c=${encodeURIComponent(st.chat || "")}`, body);
export const ccGet = (name, q = "") => api(`/api/chat/${name}?c=${encodeURIComponent(st.chat || "")}${q}`);
export const isCodex = () => st.engine === "codex";
export const NAME = () => isCodex() ? "Codex" : "Claude";
// 前回の選択を覚えておく名前（Claude は oc.cc.〜、Codex は oc.cx.〜）と、それぞれの最初の値
export const optKey = (k) => `${isCodex() ? "oc.cx" : "oc.cc"}.${k}`;
export const defaultOpts = () => isCodex() ? { model: "default", effort: "", mode: "ask", thinking: true }
  : { model: "default", effort: "medium", mode: "auto", thinking: true };

// 選んでいるモデルの表示名（Default のときは中のモデル名）
export function modelInfo(v = st.opts.model) {
  if (isCodex() && v === "default") return st.models.find((m) => m.isDefault) || st.models[0] || null;
  return st.models.find((m) => m.value === v) || null;
}
export function modelLabel() {
  if (isCodex()) return modelInfo()?.displayName || "Default";
  const m = modelInfo();
  if (!m) return st.opts.model === "default" ? "Default" : st.opts.model;
  if (m.value === "default") return (m.description || "").split("·")[0].trim() || "Default";
  return m.displayName;
}
export const EFFORT_LABEL = { low: "Low", medium: "Medium", high: "High", xhigh: "XHigh", max: "Max" };
export const EFFORTS = ["low", "medium", "high", "xhigh", "max"];
export const MODES = {
  default: { label: "Manual", desc: "Claude will ask for approval before making each edit", icon: "hand" },
  acceptEdits: { label: "Edit automatically", desc: "Claude will edit your selected text or the whole file", icon: "code" },
  plan: { label: "Plan", desc: "Claude will explore the code and present a plan before editing", icon: "plan" },
  auto: { label: "Auto", desc: "Claude will approve actions that pass a safety check and pause for anything risky", icon: "bolt" },
  bypassPermissions: { label: "Bypass permissions", desc: "Claude will not ask for approval before running potentially dangerous commands", icon: "bolt" },
};
export const MODE_ORDER = ["default", "acceptEdits", "plan", "auto"];

// ---- Codex（VS Code の Codex 拡張と同じ文言）----
export const CX_EFFORT_LABEL = { none: "None", minimal: "Minimal", low: "Light", medium: "Medium", high: "High",
  xhigh: "Extra High", max: "Max", ultra: "Ultra" };
export const CX_MODES = {
  ask: { label: "Ask for approval", desc: "Always ask to edit external files and use the internet", icon: "hand" },
  auto: { label: "Approve for me", desc: "Only ask for actions detected as potentially unsafe", icon: "bolt" },
  full: { label: "Full access", desc: "Unrestricted access to the internet and any file on your computer", icon: "globe" },
  custom: { label: "Custom (config.toml)", short: "Custom", desc: "Uses permissions defined in config.toml", icon: "code" },
};
export const CX_MODE_ORDER = ["ask", "auto", "full", "custom"];
export const modes = () => isCodex() ? CX_MODES : MODES;
export const modeOrder = () => isCodex() ? CX_MODE_ORDER : MODE_ORDER;
// 考える深さ：選べるもの・今の値・表示の名前
export function efforts() { return isCodex() ? (modelInfo()?.efforts || []) : EFFORTS; }
export function effortNow() { return isCodex() ? (st.opts.effort || modelInfo()?.defaultEffort || "") : st.opts.effort; }
export function effortLabel(e = effortNow()) { return (isCodex() ? CX_EFFORT_LABEL : EFFORT_LABEL)[e] || e; }

// VS Code の拡張と同じ形の線のアイコン（16px）
const P = {
  plus: '<path d="M8 3v10M3 8h10"/>',
  slash: '<rect x="2.5" y="2.5" width="11" height="11" rx="2"/><path d="M9.5 5l-3 6"/>',
  send: '<path d="M8 13V3M3.5 7.5L8 3l4.5 4.5"/>',
  stop: '<rect x="4" y="4" width="8" height="8" rx="1.2" fill="currentColor" stroke="none"/>',
  mic: '<rect x="6" y="2" width="4" height="8" rx="2"/><path d="M3.5 7.5a4.5 4.5 0 009 0M8 12v2.5"/>',
  hand: '<path d="M5 8V3.8a1 1 0 012 0V7m0-3.7V2.8a1 1 0 012 0V7m0-3.2a1 1 0 012 0V7.5m0-2a1 1 0 012 0v3.5c0 3-2 5-4.8 5C6.8 14 5.6 13 4.7 11.7L3 9a1 1 0 011.6-1.2L5 8.3"/>',
  code: '<path d="M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5"/>',
  plan: '<rect x="3" y="2.5" width="10" height="11" rx="1.5"/><path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3"/>',
  bolt: '<path d="M9 1.8L3.5 9h4l-.5 5.2L12.5 7h-4z"/>',
  history: '<circle cx="8" cy="8" r="5.8"/><path d="M8 4.8V8l2.2 1.6"/>',
  newchat: '<circle cx="8" cy="8" r="5.8"/><path d="M8 5.3v5.4M5.3 8h5.4"/>',
  close: '<path d="M4 4l8 8M12 4l-8 8"/>',
  upload: '<path d="M8 11V2.8M4.5 6.2L8 2.8l3.5 3.4M2.5 10.5v2.2h11v-2.2"/>',
  file: '<path d="M4 1.8h5.2L12.5 5v9.2H4z"/><path d="M9 1.8V5.2h3.5"/>',
  globe: '<circle cx="8" cy="8" r="5.8"/><path d="M2.2 8h11.6M8 2.2c1.8 2 1.8 9.6 0 11.6M8 2.2c-1.8 2-1.8 9.6 0 11.6"/>',
  eye: '<path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>',
  eyeoff: '<path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><path d="M2.5 13.5l11-11"/>',
  check: '<path d="M3 8.5l3 3 7-7"/>',
  chev: '<path d="M6 4l4 4-4 4"/>',
  brain: '<path d="M6 13.5V3a2 2 0 00-3.5 1.3A2.3 2.3 0 002 8.5a2.3 2.3 0 001.3 3.3A2 2 0 006 13.5zM10 13.5V3a2 2 0 013.5 1.3A2.3 2.3 0 0114 8.5a2.3 2.3 0 01-1.3 3.3A2 2 0 0110 13.5z"/>',
  dumbbell: '<path d="M1.5 8h13M3.5 5v6M5.5 4v8M10.5 4v8M12.5 5v6"/>',
  copy: '<rect x="5" y="5" width="8.5" height="8.5" rx="1.2"/><path d="M3 10.5V3.2A1.2 1.2 0 014.2 2h6.3"/>',
  terminal: '<rect x="1.8" y="2.5" width="12.4" height="11" rx="1.5"/><path d="M4.5 6l2.2 2-2.2 2M8.5 10.5h3"/>',
};
export const icon = (name, cls = "") =>
  `<svg class="ico ${cls}" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">${P[name] || ""}</svg>`;
export const logo = () => isCodex() ? '<img class="cclogo cx" src="/claude-asset/codex-logo.svg" alt="">'
  : '<img class="cclogo" src="/claude-asset/claude-logo.svg" alt="" onerror="this.replaceWith(Object.assign(document.createElement(\'span\'),{className:\'cclogo t\',textContent:\'✳\'}))">';

// ---- 浮かぶメニュー（入力欄の上に出す。1つだけ開く）----
let openPop = null;
export function closePop() { if (openPop) { openPop.el.remove(); openPop.onClose?.(); openPop = null; } }
export const popOpen = () => openPop;
// anchor の上に出す。align: left / right / full（入力欄の幅）
export function showPop(el, anchor, { align = "left", onClose, key } = {}) {
  closePop();
  el.classList.add("ccpop");
  $("claude").append(el);
  const box = $("claude").getBoundingClientRect(), r = anchor.getBoundingClientRect();
  const inBox = $("ccInput").getBoundingClientRect();
  // チャット欄を拡大しているとき（zoom.mjs）、浮かぶメニューも同じ倍率なので、位置を倍率で割る
  const z = parseFloat(getComputedStyle($("claude")).getPropertyValue("--cc-zoom")) || 1;
  el.style.bottom = `${(box.bottom - inBox.top + 6) / z}px`;
  if (align === "full") { el.style.left = `${(inBox.left - box.left) / z}px`; el.style.right = `${(box.right - inBox.right) / z}px`; }
  else if (align === "right") el.style.right = `${Math.max(8, box.right - r.right) / z}px`;
  else el.style.left = `${Math.max(8, r.left - box.left) / z}px`;
  openPop = { el, onClose, key };
  return el;
}
document.addEventListener("mousedown", (e) => {
  if (openPop && !openPop.el.contains(e.target) && !e.target.closest("[data-pop]")) closePop();
});

// ---- 設定の答えを画面に出す（Status・Hooks などの共通）----
export function renderData(v, depth = 0) {
  if (v == null || v === "") return '<span class="dim">—</span>';
  if (typeof v !== "object") return escapeHtml(String(v));
  if (Array.isArray(v)) {
    if (!v.length) return '<span class="dim">なし</span>';
    return `<ul class="ccdata">${v.map((x) => `<li>${renderData(x, depth + 1)}</li>`).join("")}</ul>`;
  }
  const rows = Object.entries(v).filter(([, x]) => x != null && !(Array.isArray(x) && !x.length) && x !== "");
  return `<table class="ccdata">${rows.map(([k, x]) => `<tr><td>${escapeHtml(k)}</td><td>${renderData(x, depth + 1)}</td></tr>`).join("")}</table>`;
}
