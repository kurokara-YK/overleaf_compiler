// PDF の表示（pdf.js）。描画・拡大縮小・ページ番号と、画面の位置と PDF の座標（pt、左上が原点）の変換
import * as pdfjs from "/static/pdfjs/pdf.min.mjs";
import { $, bus } from "./util.mjs";

pdfjs.GlobalWorkerOptions.workerSrc = "/static/pdfjs/pdf.worker.min.mjs";
export { pdfjs };
export const PDFJS_OPTS = { cMapUrl: "/static/pdfjs/cmaps/", cMapPacked: true,
                            standardFontDataUrl: "/static/pdfjs/standard_fonts/", wasmUrl: "/static/pdfjs/wasm/" };
export const viewer = $("viewer"), pagesEl = $("pages");
export let scale = null;          // 1pt が何 px か
export let version = -1;          // 表示している PDF の版（サーバの組版の回数）
export let rendering = false;
export let pageSizes = [];        // 各ページの大きさ（pt）
let pendingReload = false, zoomMode = "fit", zoomRatio = 1;
export function setVersion(v) { version = v; }
// 原稿を閉じた・開き直した
export function resetPdf() { version = -1; scale = null; pageSizes = []; pagesEl.replaceChildren(); }

export async function loadPdf() {
  if (rendering) { pendingReload = true; return; }
  rendering = true;
  try {
    const doc = await pdfjs.getDocument({ url: `/pdf?v=${version}&t=${Date.now()}`, ...PDFJS_OPTS }).promise;
    const sizes = [];
    for (let i = 1; i <= doc.numPages; i++) {
      const v = (await doc.getPage(i)).getViewport({ scale: 1 });
      sizes.push({ w: v.width, h: v.height });
    }
    pageSizes = sizes;
    if (zoomMode === "fit" || scale === null) scale = fitScale();
    const top = viewer.scrollTop, left = viewer.scrollLeft;
    const frag = document.createElement("div");
    const dpr = window.devicePixelRatio || 1;
    const jobs = [];
    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i);
      const vp = page.getViewport({ scale: scale * dpr });
      const div = document.createElement("div");
      div.className = "page"; div.dataset.page = i;
      div.style.width = `${sizes[i - 1].w * scale}px`; div.style.height = `${sizes[i - 1].h * scale}px`;
      for (const v of ["--scale-factor", "--total-scale-factor"]) div.style.setProperty(v, scale);
      div.style.setProperty("--user-unit", 1);
      const c = document.createElement("canvas");
      c.width = Math.floor(vp.width); c.height = Math.floor(vp.height);
      const tl = document.createElement("div");
      tl.className = "textLayer";
      div.append(c, tl); frag.appendChild(div);
      jobs.push(page.render({ canvas: c, canvasContext: c.getContext("2d"), viewport: vp }).promise);
      jobs.push(new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: tl,
                                      viewport: page.getViewport({ scale }) }).render());
    }
    await Promise.all(jobs);           // 全ページを描き終えてから差し替える（ちらつかない）
    pagesEl.replaceChildren(...frag.children);
    viewer.scrollTop = top * zoomRatio; viewer.scrollLeft = left * zoomRatio;
    zoomRatio = 1;
    $("empty").style.display = "none";
    $("pageCount").textContent = `/ ${doc.numPages}`;
    showZoom(); updatePageNo();
    bus.emit("rendered");   // コメントが、組み直した PDF の上で文字を探し直す
  } catch (e) {
    $("empty").style.display = "block";
    $("empty").textContent = `PDF を読めない: ${e.message}`;
  } finally {
    rendering = false;
    if (pendingReload) { pendingReload = false; loadPdf(); }
  }
}
function fitScale() {
  const w = Math.max(...pageSizes.map((p) => p.w), 1);
  return Math.min(3, Math.max(0.3, (viewer.clientWidth - 36) / w));
}
function setScale(s, mode = "custom") {
  s = Math.min(4, Math.max(0.3, s));
  zoomMode = mode; zoomRatio = scale ? s / scale : 1; scale = s; loadPdf();
}
function showZoom() {
  const sel = $("zoomSel"), pct = `${Math.round(scale * 100)}%`;
  const opt = sel.querySelector('option[value="custom"]');
  if (zoomMode === "fit") { sel.value = "fit"; sel.options[0].textContent = `幅に合わせる（${pct}）`; return; }
  sel.options[0].textContent = "幅に合わせる";
  const hit = [...sel.options].find((o) => Math.abs(parseFloat(o.value) - scale) < 0.001);
  if (hit) sel.value = hit.value; else { opt.hidden = false; opt.textContent = pct; sel.value = "custom"; }
}
export function fitWidth() { $("zoomSel").value = "fit"; $("zoomSel").onchange(); }
$("zoomSel").onchange = () => {
  const v = $("zoomSel").value;
  if (v === "fit") { zoomMode = "fit"; const s = fitScale(); zoomRatio = scale ? s / scale : 1; scale = s; loadPdf(); }
  else if (v !== "custom") setScale(parseFloat(v), "fixed");
};
$("zin").onclick = () => setScale(scale * 1.1);
$("zout").onclick = () => setScale(scale / 1.1);
let wheelTimer = null, wheelScale = null;
viewer.addEventListener("wheel", (e) => {
  if (!e.ctrlKey) return;
  e.preventDefault();
  wheelScale = (wheelScale || scale) * (e.deltaY < 0 ? 1.1 : 1 / 1.1);
  clearTimeout(wheelTimer);
  wheelTimer = setTimeout(() => { setScale(wheelScale); wheelScale = null; }, 150);
}, { passive: false });
let refitTimer = null;
export function refit() {   // 幅に合わせている間は、枠の幅が変わったら組み直す
  if (zoomMode !== "fit" || !pageSizes.length) return;
  clearTimeout(refitTimer);
  refitTimer = setTimeout(() => {
    const s = fitScale();
    if (Math.abs(s - scale) > 0.01) { zoomRatio = s / scale; scale = s; loadPdf(); }
  }, 120);
}
addEventListener("resize", refit);

// ---- ページ番号 ----
function updatePageNo() {
  const mid = viewer.scrollTop + viewer.clientHeight * 0.3;
  let n = 1;
  for (const p of pagesEl.children) if (p.offsetTop <= mid) n = +p.dataset.page;
  if (document.activeElement !== $("pageNo")) $("pageNo").value = n;
}
viewer.addEventListener("scroll", updatePageNo);
$("pageNo").addEventListener("change", () => {
  const p = pagesEl.querySelector(`.page[data-page="${parseInt($("pageNo").value)}"]`);
  if (p) viewer.scrollTop = p.offsetTop - 8;
});
// ---- 画面の位置と PDF の座標 ----
export function pointIn(pg, cx, cy) { const r = pg.getBoundingClientRect(); return [+pg.dataset.page, (cx - r.left) / scale, (cy - r.top) / scale]; }
export function pageOfPoint(cx, cy) {
  return [...pagesEl.children].find((p) => { const b = p.getBoundingClientRect(); return cx >= b.left && cx <= b.right && cy >= b.top && cy <= b.bottom; });
}
// 選んだ範囲の四角形を、ページ上の座標 [ページ, x, y, 幅, 高さ]（pt、左上が原点）にする。同じ行は1つにまとめる
export function rangeRects(range) {
  const rs = [];
  for (const r of range.getClientRects()) {
    if (r.width < 0.5 || r.height < 0.5) continue;
    const pg = pageOfPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!pg) continue;
    const b = pg.getBoundingClientRect();
    rs.push([+pg.dataset.page, (r.left - b.left) / scale, (r.top - b.top) / scale, r.width / scale, r.height / scale]);
  }
  rs.sort((a, b) => a[0] - b[0] || a[2] - b[2] || a[1] - b[1]);
  const out = [];
  for (const r of rs) {
    const l = out[out.length - 1];
    if (l && l[0] === r[0]) {
      const overlap = Math.min(l[2] + l[4], r[2] + r[4]) - Math.max(l[2], r[2]);
      const gap = Math.max(r[1] - (l[1] + l[3]), l[1] - (r[1] + r[3]));
      if (overlap > Math.min(l[4], r[4]) * 0.5 && gap < Math.max(l[4], r[4])) {
        const x1 = Math.min(l[1], r[1]), y1 = Math.min(l[2], r[2]);
        const x2 = Math.max(l[1] + l[3], r[1] + r[3]), y2 = Math.max(l[2] + l[4], r[2] + r[4]);
        l.splice(1, 4, x1, y1, x2 - x1, y2 - y1);
        continue;
      }
    }
    out.push(r.slice());
  }
  return out;
}
// SyncTeX の箱（ソースの行が PDF 上のどこか）を一瞬示す
export function showBoxes(boxes) {
  document.querySelectorAll(".hl").forEach((e) => e.remove());
  let first = null;
  for (const b of boxes) {
    const pg = pagesEl.querySelector(`.page[data-page="${b.page}"]`);
    if (!pg) continue;
    const d = document.createElement("div");
    d.className = "hl";
    Object.assign(d.style, { left: `${b.x * scale - 2}px`, top: `${b.y * scale - 1}px`,
      width: `${b.w * scale + 4}px`, height: `${b.h * scale + 3}px` });
    pg.appendChild(d);
    if (!first) first = { pg, y: b.y };
  }
  if (first) viewer.scrollTop = first.pg.offsetTop + first.y * scale - viewer.clientHeight / 3;
  setTimeout(() => document.querySelectorAll(".hl").forEach((e) => e.classList.add("fade")), 1500);
  setTimeout(() => document.querySelectorAll(".hl.fade").forEach((e) => e.remove()), 3000);
}
