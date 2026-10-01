// 画面のどこからでも使う小道具（サーバとのやり取り・表示・小さな窓）と、モジュールどうしの連絡（bus）
export const $ = (id) => document.getElementById(id);
export const enc = encodeURIComponent;

// このタブの原稿（data からの主文書の相対パス。URL の ?p=）と、タブの番号（サーバが見ているタブを数える）。
// タブごとに別の原稿を開けるよう、サーバへの要求にはすべて p と t を付ける
export const tab = { p: new URLSearchParams(location.search).get("p"), t: Math.random().toString(36).slice(2) };
export function url(path) {
  if (!tab.p) return path;
  return `${path}${path.includes("?") ? "&" : "?"}p=${enc(tab.p)}&t=${tab.t}`;
}
// 画面の場所を URL に書く。p（原稿）・view（history なら履歴の画面）・dir（一覧で開いているフォルダ）。
// 画面を移るたびに履歴に積むので、ブラウザの戻る・進むで1つ前の画面へ戻れる（main.mjs の popstate）
export function pushUrl(q, push = true) {
  const u = new URLSearchParams();
  for (const k of ["p", "view", "dir"]) if (q[k]) u.set(k, q[k]);
  const s = u.toString().replace(/%2F/g, "/"), next = "/" + (s ? `?${s}` : "");
  if (location.pathname + location.search !== next) history[push ? "pushState" : "replaceState"](null, "", next);
}
// タブの原稿を変える（URL も変える。複製したタブ・再読み込みでも同じ原稿が開く）
export function setTabProject(p, push = true, dir = "") {
  tab.p = p;
  pushUrl(p ? { p } : { dir }, push);
}

export async function api(path, opts) {
  const r = await fetch(url(path), opts);
  // 画面だけ新しく、サーバが古いまま（更新したのに起動し直していない）だと、新しい窓口が 404 になる
  if (r.status === 404 && path.startsWith("/api/"))
    throw new Error("この操作は、動いているサーバがまだ古いので使えない。アプリを閉じて開き直すこと（ドックのアイコンを右クリック →「サーバーを止める」→ もう一度開く）");
  const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
export const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
export function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
export const store = { get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
                       set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
export const dirname = (p) => p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "";
export const basename = (p) => p.slice(p.lastIndexOf("/") + 1);
export function showToast(html, cls = "", ms = 4000) {
  const t = $("toast");
  t.className = `open ${cls}`; t.innerHTML = html;
  clearTimeout(t._timer);
  if (ms) t._timer = setTimeout(() => t.classList.remove("open"), ms);
}
export const fail = (e) => showToast(escapeHtml(e.message), "err", 6000);
export function ago(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} 分前`;
  if (s < 86400) return `${Math.round(s / 3600)} 時間前`;
  return new Date(t * 1000).toLocaleDateString("ja-JP");
}

// ---- 小さな窓（入力・確認・表示）----
export function modal(title, html, buttons) {
  return new Promise((resolve) => {
    $("mTitle").textContent = title;
    $("mBody").innerHTML = html;
    $("mFoot").replaceChildren(...buttons.map((b) => {
      const el = document.createElement("button");
      el.textContent = b.label; if (b.cls) el.className = b.cls;
      el.onclick = () => done(b.value);
      return el;
    }));
    const back = $("modalBack");
    back.classList.add("open");
    const input = $("mBody").querySelector("input");
    const primary = buttons.find((b) => b.cls === "primary" || b.cls === "danger");
    const key = (e) => {
      if (e.key === "Escape") done(null);
      else if (e.key === "Enter" && !e.isComposing && primary) { e.preventDefault(); done(primary.value); }
    };
    function done(v) {
      back.classList.remove("open"); removeEventListener("keydown", key, true);
      resolve(v === "__input" ? input.value.trim() : v);
    }
    addEventListener("keydown", key, true);
    setTimeout(() => (input || $("mFoot").lastChild).focus(), 0);
    if (input) { input.select(); }
  });
}
export const ask = (title, label, value = "") =>
  modal(title, `<div>${label}</div><input value="${escapeHtml(value)}">`,
        [{ label: "やめる", value: null }, { label: "決定", value: "__input", cls: "primary" }]);
export const confirmBox = (title, html, ok = "OK", danger = false) =>
  modal(title, html, [{ label: "やめる", value: false }, { label: ok, value: true, cls: danger ? "danger" : "primary" }]);
export const closeBtn = [{ label: "閉じる", value: 1, cls: "primary" }];

// ---- モジュールどうしの連絡 ----
// 直接呼び合うと循環するものは、出来事を知らせて、知りたいモジュールが受け取る。
//   activate  エディタのタブが変わった（t: タブか null）
//   edit      エディタの文面が変わった
//   cursor    エディタのカーソルが動いた
//   view      左のパネルが変わった（v: files / search / history / comments）
//   rendered  PDF を描き終えた
//   comments  コメントを読み直した
//   files     ファイルが増えた・消えた（ツリーを読み直す）
//   reopen    原稿を開いた・閉じた（画面を作り直す。待てる）
//   opened    原稿を開き終えた（右のチャット欄が作り直す）
const listeners = new Map();
export const bus = {
  on(name, fn) { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(fn); },
  // 受け取った側が async なら、全部終わるのを待てる
  emit(name, ...args) { return Promise.all((listeners.get(name) || []).map((fn) => fn(...args))); },
};
