// コメントの PDF 上の印（ハイライト・取り消し線・付箋の印）。組み直した PDF の文字の層から、選んだ文字を探し直して描く
import { active } from "../editor.mjs";
import { pagesEl, scale, rangeRects } from "../pdf.mjs";
import { comments, cmtActive, PIN_KINDS, KIND, isResolved } from "./model.mjs";

// ---- PDF の文字の層から、文字列を探す ----
export const isSpace = (c) => /\s/.test(c);
function squeeze(s) {   // 空白を除き NFKC でそろえる（comments.py・sync.py と同じ考え方）
  let o = "";
  for (const ch of s) if (!isSpace(ch)) for (const c of ch.normalize("NFKC")) if (!isSpace(c)) o += c;
  return o;
}
function buildTextIndex() {
  let str = ""; const map = [];
  for (const pg of pagesEl.children) {
    const layer = pg.querySelector(".textLayer");
    if (!layer) continue;
    const tw = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const t = n.data;
      for (let i = 0; i < t.length; i++) {
        if (isSpace(t[i])) continue;
        for (const c of t[i].normalize("NFKC")) if (!isSpace(c)) { str += c; map.push([n, i]); }
      }
    }
  }
  return { str, map };
}
// quote を探す。同じ文字列が複数あれば、付けたときの位置（near）に一番近いもの
function findQuote(idx, quote, near) {
  const q = squeeze(quote);
  if (!q) return null;
  let best = -1, bestScore = Infinity, n = 0;
  for (let pos = idx.str.indexOf(q); pos !== -1 && n < 300; pos = idx.str.indexOf(q, pos + 1), n++) {
    if (!near) { best = pos; break; }
    const el = idx.map[pos][0].parentElement, pg = el.closest(".page");
    const er = el.getBoundingClientRect(), pr = pg.getBoundingClientRect();
    const score = Math.abs(+pg.dataset.page - near.page) * 1e5 + Math.abs((er.top - pr.top) / scale - near.y)
                + Math.abs((er.left - pr.left) / scale - near.x) * 0.5;
    if (score < bestScore) { bestScore = score; best = pos; }
  }
  if (best < 0) return null;
  const [n1, o1] = idx.map[best], [n2, o2] = idx.map[best + q.length - 1];
  const rg = document.createRange();
  rg.setStart(n1, o1); rg.setEnd(n2, Math.min(n2.length, o2 + 1));
  const rs = rangeRects(rg);
  return rs.length ? rs : null;
}
export function placeComments() {
  if (!pagesEl.children.length) { drawMarks(); return; }
  const idx = buildTextIndex();
  for (const c of comments) {
    const r0 = c.rects && c.rects[0];
    const near = r0 ? { page: r0[0], x: r0[1], y: r0[2] } : { page: c.page, x: 0, y: 0 };
    const hit = c.quote ? findQuote(idx, c.quote, near) : null;
    c._inPdf = !!hit;
    // 文字で探せない（数式や \cite を含む）ときは、付けたときの位置に描く。直されて消えた文字には描かない
    c._rects = hit || (c.found !== false && c.rects && c.rects.length ? c.rects : null);
    c._pin = null;
    if (c.pin) {   // 付箋・挿入の印は、近くの文字が動いた分だけ動かす
      const f = hit && hit[0];
      c._pin = f && r0 ? [f[0], c.pin[1] + f[1] - r0[1], c.pin[2] + f[2] - r0[2]] : c.pin;
    }
  }
  drawMarks();
}
export function drawMarks() {
  pagesEl.querySelectorAll(".cmark, .cpin").forEach((e) => e.remove());
  const pageEl = (n) => pagesEl.querySelector(`.page[data-page="${n}"]`);
  for (const c of comments) {
    if (!shown(c)) continue;
    const on = c.id === cmtActive ? " on" : "";
    if (PIN_KINDS.has(c.kind)) {
      const p = pinOf(c);
      const pg = p && pageEl(p[0]);
      if (!pg) continue;
      const d = document.createElement("div");
      d.className = `cpin k-${c.kind}${on}`; d.textContent = c.kind === "insert" ? "‸" : "💬";
      Object.assign(d.style, { left: `${p[1] * scale - (c.kind === "insert" ? 9 : 2)}px`, top: `${p[2] * scale - (c.kind === "insert" ? 4 : 18)}px` });
      pg.appendChild(d);
      continue;
    }
    for (const [page, x, y, w, h] of c._rects || []) {
      const pg = pageEl(page);
      if (!pg) continue;
      const d = document.createElement("div");
      d.className = `cmark k-${c.kind}${on}`;
      Object.assign(d.style, { left: `${x * scale}px`, top: `${y * scale}px`, width: `${w * scale}px`, height: `${h * scale}px` });
      pg.appendChild(d);
    }
  }
}

// 描くもの。解決済みは、選んでいるときだけ
const shown = (c) => !isResolved(c) || c.id === cmtActive;
// 付箋・挿入の印の位置 [ページ, x, y]
export const pinOf = (c) => PIN_KINDS.has(c.kind) && (c._pin || (c._rects && c._rects[0]));

// PDF 上の点（pt）にあるコメント。重なっていれば小さい方
export function commentAt(page, x, y) {
  let hit = null, area = Infinity;
  for (const c of comments) {
    if (!shown(c)) continue;
    const p = pinOf(c);
    if (p) {
      if (p[0] === page && Math.abs(x - p[1]) < 12 / scale && y > p[2] - 20 / scale && y < p[2] + 4 / scale) return c;
      continue;
    }
    for (const [pn, rx, ry, rw, rh] of c._rects || []) {
      if (pn === page && x >= rx - 1 && x <= rx + rw + 1 && y >= ry - 1 && y <= ry + rh + 1 && rw * rh < area) { hit = c; area = rw * rh; }
    }
  }
  return hit;
}

// ---- エディタでも、コメントの付いた文字に印を付ける ----
let cmMarks = [];
export function markEditorComments() {
  cmMarks.forEach((m) => m.clear()); cmMarks = [];
  if (!active) return;
  for (const c of comments) {
    if (isResolved(c) || !c.found || c.file !== active.path || !c.range) continue;
    const [l1, c1, l2, c2] = c.range;
    cmMarks.push(active.doc.markText({ line: l1, ch: c1 }, { line: l2, ch: c2 },
      { className: `cm-cmt${c.id === cmtActive ? " on" : ""}`, attributes: { title: `${c.author}: ${c.text || KIND[c.kind]}` } }));
  }
}
