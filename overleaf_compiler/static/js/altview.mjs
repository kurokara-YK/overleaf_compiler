// 右のプレビューの形式。PDF のほかに、Word（.docx）・Markdown（.md）・HTML（.html）で書き出したときの見え方を出す。
// Word・Markdown・HTML では段落をそのまま書き換えられる。書き換えた文字は、前後の文字といっしょに .tex から探して
// 同じように直す（PDF の上の「ここで直す」と同じ考え方）。数式や \cite のように、ソースと文字が違う所は直せない。
// 変換は pandoc（pandoc.py の preview）。原稿が組み直されたら描き直す（書いている途中は待つ）
import { marked } from "/static/marked/marked.esm.js";
import { $, api, post, escapeHtml, store, showToast, bus, url, ask } from "./util.mjs";
import { openMenu } from "./menu.mjs";
import { setLayout } from "./panels.mjs";
import { refit, pdfjs, PDFJS_OPTS } from "./pdf.mjs";

const NAMES = { pdf: "PDF", docx: "Word", md: "Markdown", html: "HTML" };
const EDITABLE = "p, li, h1, h2, h3, h4, h5, h6, td, th, figcaption, dt, dd, blockquote";
let fmt = NAMES[store.get("oc.pview", "pdf")] ? store.get("oc.pview", "pdf") : "pdf";
let loaded = "", pending = false, loading = false;

$("layoutFmt").onclick = (e) => { e.stopPropagation(); const r = $("layoutFmt").getBoundingClientRect(); openMenu("mPview", r.left - 120, r.bottom + 4); };
export function setPreviewFmt(f) {
  fmt = NAMES[f] ? f : "pdf";
  store.set("oc.pview", fmt);
  apply();
  if ($("ide").classList.contains("only-editor")) setLayout("pdf");
  if (fmt !== "pdf") load(true); else setTimeout(refit, 0);   // 隠れていた PDF の幅を合わせ直す
}
function apply() {
  $("layoutPdf").textContent = NAMES[fmt];
  $("preview").classList.toggle("alt", fmt !== "pdf");
  $("altview").className = `alt-${fmt}`;
  $("altInfo").textContent = fmt === "pdf" ? "" : fmt === "docx" ? "Word で開いたときの見え方・文字を選んで「✎ ここで直す」"
    : `${NAMES[fmt]} で書き出したときの見え方・段落を押して直接直せる`;
  $("altDl").href = url(`/export?format=${fmt}`);
}
const visible = () => fmt !== "pdf" && !$("ide").classList.contains("only-editor") && document.body.className === "editing";
const editing = () => $("altbody").contains(document.activeElement);

async function load(force = false) {
  if (!visible()) return;
  if (editing()) { pending = true; return; }   // 書いている途中は描き直さない（離れたら描き直す）
  if (loading) { pending = true; return; }
  loading = true;
  const box = $("altview"), y = box.scrollTop;
  if (force || loaded !== fmt) $("altbody").innerHTML = `<div class="alt-wait">${fmt === "docx"
    ? "Word の見え方を作っている…（初めては図や表を LaTeX で組むので 20 秒ほどかかる。次からはすぐ出る）" : "変換している…"}</div>`;
  try {
    if (fmt === "docx") { await loadWord(); loaded = fmt; box.scrollTop = y; return; }
    const r = await api(`/api/preview?format=${fmt}`);
    let html;
    if (fmt === "md") html = marked.parse(r.markdown || "");
    else html = new DOMParser().parseFromString(r.html || "", "text/html").body.innerHTML;
    $("altbody").innerHTML = html || '<div class="alt-wait">中身が無い</div>';
    $("altbody").querySelectorAll("script, style, link").forEach((x) => x.remove());
    makeEditable();
    loaded = fmt;
    box.scrollTop = y;
  } catch (e) {
    $("altbody").innerHTML = `<div class="alt-wait">${escapeHtml(e.message)}</div>`;
  } finally {
    loading = false;
    if (pending) { pending = false; if (!editing()) setTimeout(() => load(), 0); else pending = true; }
  }
}

// ---- 直接書き換える ----
function makeEditable() {
  const all = [...$("altbody").querySelectorAll(EDITABLE)];
  for (const el of all) {
    if (el.querySelector(EDITABLE)) continue;   // 中にさらに段落がある（li の中の p など）なら、中のほうを直す
    el.contentEditable = "true"; el.spellcheck = false;
    el._orig = el.innerText;
  }
}
const timers = new WeakMap();
$("altbody").addEventListener("input", (e) => {
  const el = e.target.closest("[contenteditable=true]"); if (!el || e.isComposing) return;
  clearTimeout(timers.get(el));
  timers.set(el, setTimeout(() => commit(el), 1200));
});
$("altbody").addEventListener("focusout", (e) => {
  const el = e.target.closest?.("[contenteditable=true]"); if (!el) return;
  clearTimeout(timers.get(el));
  commit(el).then(() => { if (pending && !editing()) { pending = false; load(); } });
});
$("altbody").addEventListener("keydown", (e) => {   // 段落の中で Enter は改行を入れない（段落を分けるのはエディタで）
  if (e.key === "Enter" && !e.isComposing && e.target.closest("[contenteditable=true]")) { e.preventDefault(); e.target.closest("[contenteditable=true]").blur(); }
});
async function commit(el) {
  const orig = el._orig, cur = el.innerText;
  if (cur === orig || el._busy) return;
  let p = 0;
  while (p < orig.length && p < cur.length && orig[p] === cur[p]) p++;
  let s = 0;
  while (s < orig.length - p && s < cur.length - p && orig[orig.length - 1 - s] === cur[cur.length - 1 - s]) s++;
  const old = orig.slice(p, orig.length - s), neu = cur.slice(p, cur.length - s);
  const before = orig.slice(Math.max(0, p - 12), p), after = orig.slice(orig.length - s, orig.length - s + 12);
  el._busy = true;
  try {
    const r = await post("/api/text_replace", { old, new: neu, before, after });
    el._orig = cur;
    showToast(`${escapeHtml(r.path)} の ${r.line} 行目を直した`, "ok", 2500);
  } catch (e) {
    el.innerText = orig;
    showToast(e.message === "NOT_FOUND" ? "ソースの中で同じ文字が見つからない（数式・参照・命令で書かれた所など）。エディタで直す。元に戻した"
      : escapeHtml(e.message), "err", 6000);
  } finally { el._busy = false; }
}

// ---- Word：.docx をページに組んだもの（pandoc.word_pdf）を、PDF と同じように出す ----
async function loadWord() {
  const res = await fetch(url(`/api/wordpdf?n=${Date.now()}`));
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
  const doc = await pdfjs.getDocument({ data: await res.arrayBuffer(), ...PDFJS_OPTS }).promise;
  const stamp = res.headers.get("X-Version") || Date.now();
  const box = $("altview"), dpr = window.devicePixelRatio || 1;
  const w = (await doc.getPage(1)).getViewport({ scale: 1 }).width;
  const scale = Math.min(3, Math.max(0.4, (box.clientWidth - 40) / w));
  const out = [], jobs = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i), vp = page.getViewport({ scale }), vpx = page.getViewport({ scale: scale * dpr });
    const div = document.createElement("div");
    div.className = "page wpage"; div.style.width = `${vp.width}px`; div.style.height = `${vp.height}px`;
    for (const v of ["--scale-factor", "--total-scale-factor"]) div.style.setProperty(v, scale);
    div.style.setProperty("--user-unit", 1);
    // 絵はサーバ（poppler）が描いたもの。pdf.js では日本語の字が化けるので、pdf.js は文字を選ぶ層だけに使う
    const img = new Image(); img.className = "wimg"; img.alt = ""; img.draggable = false;
    img.src = url(`/api/wordpage?page=${i}&w=${Math.round(vpx.width)}&n=${stamp}`);
    jobs.push(img.decode().catch(() => {}));
    const tl = document.createElement("div"); tl.className = "textLayer";
    div.append(img, tl); out.push(div);
    jobs.push(new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: tl, viewport: vp }).render());
  }
  await Promise.all(jobs);
  $("altbody").replaceChildren(...out);
}
// 文字を選ぶと「✎ ここで直す」。前後の文字といっしょに .tex から探して直す
const wbtn = document.createElement("button");
wbtn.id = "wEdit"; wbtn.textContent = "✎ ここで直す"; wbtn.hidden = true;
document.body.append(wbtn);
$("altbody").addEventListener("mouseup", () => setTimeout(() => {
  const sel = getSelection();
  if (fmt !== "docx" || !sel.rangeCount || sel.isCollapsed || !sel.toString().trim()) { wbtn.hidden = true; return; }
  const r = sel.getRangeAt(0).getBoundingClientRect();
  wbtn.style.left = `${r.left}px`; wbtn.style.top = `${r.bottom + 6}px`; wbtn.hidden = false;
}, 0));
document.addEventListener("mousedown", (e) => { if (e.target !== wbtn) wbtn.hidden = true; });
wbtn.onmousedown = (e) => e.preventDefault();   // 選んだ範囲を消さない
wbtn.onclick = async () => {
  wbtn.hidden = true;
  const sel = getSelection(); if (!sel.rangeCount) return;
  const range = sel.getRangeAt(0), old = sel.toString();
  const tl = (range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement)?.closest(".textLayer");
  let before = "", after = "";
  if (tl) {   // 選んだ所の前後の文字（同じ文字が何か所にもあるとき、場所を決める）
    const pre = document.createRange(); pre.setStart(tl, 0); pre.setEnd(range.startContainer, range.startOffset);
    const all = tl.textContent, at = pre.toString().length;
    before = all.slice(Math.max(0, at - 12), at); after = all.slice(at + old.length, at + old.length + 12);
  }
  const neu = await ask("ここで直す", `「${escapeHtml(old.slice(0, 80))}」を、次のように直す`, old);
  if (neu == null || neu === old) return;
  try {
    const r = await post("/api/text_replace", { old, new: neu, before, after });
    showToast(`${escapeHtml(r.path)} の ${r.line} 行目を直した（組み直すと Word の表示も変わる）`, "ok", 3500);
  } catch (e) {
    showToast(e.message === "NOT_FOUND" ? "ソースの中で同じ文字が見つからない（数式・参照・命令で書かれた所など）。エディタで直す" : escapeHtml(e.message), "err", 6000);
  }
};

bus.on("rendered", () => load());       // 組み直したら（ソースが変わったら）描き直す
bus.on("reopen", () => { loaded = ""; load(true); });
new MutationObserver(() => { if (visible() && loaded !== fmt) load(true); }).observe($("ide"), { attributes: true, attributeFilter: ["class"] });
apply();
setTimeout(() => load(true), 0);
