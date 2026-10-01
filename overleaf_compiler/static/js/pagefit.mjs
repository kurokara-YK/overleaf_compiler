// 文字数とページの見張り。組み直すたびに、最後のページにあと何行入るか（上限のページ数を決めればそこまで何行か）を
// エディタの下の欄に出す。PDF の文字の位置から測る目安（図だけの場所は数えない）。
//   本文の文字の大きさ = いちばん多く使われている大きさ、行の間隔 = 本文の行の高さの差でいちばん多いもの
//   本文の下の端 = いっぱいに詰まったページ（最後から2ページ目）の一番下の本文の行。1ページだけなら上の余白と同じとみなす
import { $, ask, store, bus } from "./util.mjs";
import { info } from "./state.mjs";
import { pdfDoc } from "./pdf.mjs";

const key = () => `oc.pageLimit.${info?.rel || ""}`;
let last = null;

async function lines(page) {
  const vp = page.getViewport({ scale: 1 }), tc = await page.getTextContent();
  const items = tc.items.filter((it) => it.str && it.str.trim()).map((it) => ({
    x: it.transform[4] - vp.viewBox[0], y: it.transform[5] - vp.viewBox[1], size: Math.round(Math.hypot(it.transform[2], it.transform[3]) * 2) / 2,
    n: it.str.trim().length, s: it.str.trim() }));
  return { W: vp.viewBox[2] - vp.viewBox[0], H: vp.viewBox[3] - vp.viewBox[1], items };
}
function mode(vals) {
  const c = new Map(); let best = null;
  for (const [v, w] of vals) { c.set(v, (c.get(v) || 0) + w); if (best === null || c.get(v) > c.get(best)) best = v; }
  return best;
}
async function measure() {
  const doc = pdfDoc; if (!doc) return null;
  const n = doc.numPages;
  const L = await lines(await doc.getPage(n));
  const R = n > 1 ? await lines(await doc.getPage(n - 1)) : L;
  const size = mode([...R.items, ...L.items].map((i) => [i.size, i.n]));
  // 本文の行だけ（ページ番号など下の余白の数字は除く）
  const body = (P) => P.items.filter((i) => Math.abs(i.size - size) <= size * 0.15 && !(i.y < P.H * 0.1 && /^[-–—\s\d]+$/.test(i.s)));
  const rb = body(R), lb = body(L);
  if (!rb.length) return null;
  const ys = [...new Set(rb.map((i) => Math.round(i.y * 2) / 2))].sort((a, b) => b - a);
  const gaps = ys.slice(1).map((y, i) => Math.round((ys[i] - y) * 2) / 2).filter((g) => g >= size * 0.9 && g <= size * 2.2);
  const pitch = mode(gaps.map((g) => [g, 1])) || size * 1.5;
  const top = Math.max(...rb.map((i) => i.y));
  const bottom = n > 1 ? Math.min(...rb.map((i) => i.y)) : R.H - top - size;   // 本文の一番下の行の高さ
  // 2段組か：前のページの本文の行が、左右の半分に分かれている
  const mid = R.W / 2;
  const two = rb.filter((i) => i.x > mid + 5).length > rb.length * 0.25 && rb.filter((i) => i.x < mid - 20).length > rb.length * 0.25;
  const perCol = Math.max(1, Math.round((top - bottom) / pitch) + 1), perPage = perCol * (two ? 2 : 1);
  const low = (arr) => arr.length ? Math.min(...arr.map((i) => i.y)) : null;
  let left;
  if (two) {
    const r = low(lb.filter((i) => i.x > mid + 5)), l = low(lb.filter((i) => i.x <= mid + 5));
    left = r !== null ? Math.floor((r - bottom) / pitch + 0.25) : (l !== null ? Math.floor((l - bottom) / pitch + 0.25) : perCol) + perCol;
  } else {
    const l = low(lb);
    left = l !== null ? Math.floor((l - bottom) / pitch + 0.25) : perPage;
  }
  return { pages: n, left: Math.max(0, left), perPage, two };
}
function show() {
  const el = $("pageFit");
  if (!last) { el.textContent = ""; return; }
  const lim = parseInt(store.get(key(), ""), 10) || 0, { pages, left, perPage, two } = last;
  let text, cls = "";
  if (!lim) { text = `${pages} ページ・最後のページにあと約 ${left} 行`; cls = left <= 3 ? "warn" : ""; }
  else if (pages <= lim) {
    const rest = (lim - pages) * perPage + left;
    text = `上限 ${lim} ページまであと約 ${rest} 行`; cls = rest <= 3 ? "warn" : "ok";
  } else {
    const over = (pages - lim - 1) * perPage + (perPage - left);
    text = `上限 ${lim} ページを約 ${over} 行こえている`; cls = "err";
  }
  el.textContent = `📄 ${text}`;
  el.className = cls;
  el.title = `最後のページにあと何行入るかの目安（1ページ ${perPage} 行${two ? "・2段組" : ""}。図だけの場所は数えない）。押すと上限のページ数を決める`;
}
async function update() {
  try { last = await measure(); } catch { last = null; }
  show();
}
bus.on("rendered", update);
$("pageFit").onclick = async () => {
  const v = await ask("ページ数の上限", "上限のページ数（例：2）。空にすると上限なし。原稿ごとに覚える", store.get(key(), ""));
  if (v === null || v === undefined) return;
  store.set(key(), String(parseInt(v, 10) || ""));
  show();
};
