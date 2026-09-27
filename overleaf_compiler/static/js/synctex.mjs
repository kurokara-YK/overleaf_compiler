// ソースと PDF の行き来（SyncTeX）。→ でカーソル行を PDF に示し、PDF のダブルクリックや ← でソースの行へ
import { $, api, enc, escapeHtml, showToast } from "./util.mjs";
import { cm, active, openTab } from "./editor.mjs";
import { revealEditor } from "./panels.mjs";
import { viewer, pagesEl, pointIn, showBoxes } from "./pdf.mjs";

$("toPdf").onclick = async () => {   // カーソルのある行を PDF で示す
  if (!active) return;
  try { showBoxes((await api(`/api/goto_pdf?path=${enc(active.path)}&line=${cm.getCursor().line + 1}`)).boxes); }
  catch (e) { showToast(escapeHtml(e.message), "err"); }
};
export async function gotoSource(page, x, y, text = "") {
  try {
    const r = await api(`/api/goto_source?page=${page}&x=${x}&y=${y}&text=${enc(text)}`);
    revealEditor();
    await openTab(r.path, r.line);
  } catch (e) { showToast(escapeHtml(e.message), "err"); }
}
// クリックした場所の前後の文字。SyncTeX が返す行（段落の終わりになりやすい）を合わせ直すのに使う
function textAround(cx, cy) {
  const r = document.caretRangeFromPoint ? document.caretRangeFromPoint(cx, cy) : null;
  if (!r || r.startContainer.nodeType !== 3) return "";
  const t = r.startContainer.textContent, o = r.startOffset;
  return t.slice(Math.max(0, o - 6), o + 6);
}
pagesEl.addEventListener("dblclick", (e) => {   // Overleaf と同じ。PDF をダブルクリックするとソースの該当行へ
  const pg = e.target.closest(".page");
  if (pg) gotoSource(...pointIn(pg, e.clientX, e.clientY), textAround(e.clientX, e.clientY));
});
$("toSrc").onclick = () => {   // 選んだ文字があればその場所、無ければ PDF の画面の中央
  const sel = getSelection();
  if (sel.rangeCount && !sel.isCollapsed) {
    const range = sel.getRangeAt(0);
    const node = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
    const pg = node && node.closest(".page");
    const r = [...range.getClientRects()].find((x) => x.width > 0);
    if (pg && r) return gotoSource(...pointIn(pg, r.left + 2, r.top + r.height / 2), sel.toString().slice(0, 12));
  }
  const vr = viewer.getBoundingClientRect(), cx = vr.left + vr.width / 2, cy = vr.top + vr.height / 2;
  const pg = [...pagesEl.children].find((p) => { const r = p.getBoundingClientRect(); return r.top <= cy && cy <= r.bottom; });
  if (pg) gotoSource(...pointIn(pg, cx, cy));
};
