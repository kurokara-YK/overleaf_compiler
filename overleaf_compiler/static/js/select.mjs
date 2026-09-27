// PDF の文字を選んだときのツールバー（💬 コメント・✎ ここで直す・← ソースへ・コピー）と、その場で書き換える欄
import { $, post, escapeHtml, showToast, fail } from "./util.mjs";
import { saveAll } from "./editor.mjs";
import { pagesEl, scale, rangeRects } from "./pdf.mjs";
import { gotoSource } from "./synctex.mjs";

// 選んだ文字 { page, x, y（ソースを引く位置 pt）, text, first, last（画面の四角形）, rects（PDF 上の四角形）}
export let selInfo = null;
export function hideSel() { $("seltool").classList.remove("open"); }
export function hideInline() { $("inline").classList.remove("open"); }
function checkSel() {
  if ($("inline").classList.contains("open")) return;
  const sel = getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return hideSel();
  const range = sel.getRangeAt(0);
  const node = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
  const pg = node && node.closest(".page");
  const text = sel.toString();
  if (!pg || !pagesEl.contains(pg) || !text.trim()) return hideSel();
  const rects = [...range.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
  if (!rects.length) return hideSel();
  const first = rects[0], last = rects[rects.length - 1], pr = pg.getBoundingClientRect();
  selInfo = { page: +pg.dataset.page, x: (first.left - pr.left + Math.min(4, first.width / 2)) / scale,
              y: (first.top - pr.top + first.height / 2) / scale, text, first, last, rects: rangeRects(range) };
  const tool = $("seltool");
  tool.classList.add("open");
  const w = tool.offsetWidth, h = tool.offsetHeight;
  tool.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, last.right - w / 2))}px`;
  tool.style.top = `${last.bottom + 8 + h > innerHeight ? first.top - h - 8 : last.bottom + 8}px`;
}
pagesEl.addEventListener("mouseup", (e) => { if (e.detail < 2) setTimeout(checkSel, 0); });
document.addEventListener("mousedown", (e) => { if (!e.target.closest("#seltool, #inline, #cbox")) hideSel(); });
// PDF から選んだ文字の改行を戻す（行末のハイフン、和文の途中の改行、欧文の改行は空白に）
export function tidySel(t) {
  return t.replace(/-\n/g, "")
          .replace(/([　-鿿＀-￯])\s*\n\s*(?=[　-鿿＀-￯])/g, "$1")
          .replace(/\s*\n\s*/g, " ");
}
$("selEdit").onclick = () => {
  if (!selInfo) return;
  hideSel();
  const box = $("inline"), ta = $("inlineText"), si = selInfo;
  box._sel = si; ta.value = tidySel(si.text);
  box.style.width = `${Math.max(360, Math.min(640, si.last.right - si.first.left + 40))}px`;
  openNear(box, si);
  ta.style.height = "auto"; ta.style.height = `${Math.min(240, ta.scrollHeight + 4)}px`;
  ta.focus(); ta.select();
};
// 選んだ文字のすぐ下（入らなければ上）に窓を開く
export function openNear(box, si) {
  box.classList.add("open");
  const w = box.offsetWidth;
  box.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, si.first.left - 8))}px`;
  const top = si.last.bottom + 8;
  box.style.top = `${top + box.offsetHeight > innerHeight ? Math.max(8, si.first.top - box.offsetHeight - 8) : top}px`;
}
$("inlineCancel").onclick = hideInline;
$("inlineText").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("inlineOk").click(); }
  else if (e.key === "Escape") { e.preventDefault(); hideInline(); }
});
$("inlineOk").onclick = async () => {
  const si = $("inline")._sel, text = $("inlineText").value;
  if (!si) return;
  if (text === tidySel(si.text)) return hideInline();
  await saveAll();   // 書き換える前に、エディタの未保存の入力をファイルへ
  try {
    const r = await post("/api/replace", { page: si.page, x: si.x, y: si.y, old: si.text, new: text });
    hideInline(); getSelection().removeAllRanges();
    showToast(`直した（${escapeHtml(r.path)} ${r.line} 行）。コンパイル中…`, "ok");
  } catch (e) {
    if (e.message === "NOT_FOUND") {
      showToast('選んだ部分は LaTeX のコマンドや数式を含むので、PDF の上では直せない。<button id="toSource">ソースで直す</button>', "err", 8000);
      $("toSource").onclick = () => { $("toast").classList.remove("open"); hideInline(); gotoSource(si.page, si.x, si.y, si.text.slice(0, 12)); };
    } else fail(e);
  }
};
$("selSource").onclick = () => { if (selInfo) { hideSel(); gotoSource(selInfo.page, selInfo.x, selInfo.y, selInfo.text.slice(0, 12)); } };
$("selCopy").onclick = async () => {
  if (!selInfo) return;
  try { await navigator.clipboard.writeText(tidySel(selInfo.text)); } catch { document.execCommand("copy"); }
  hideSel(); showToast("コピーした", "ok", 1500);
};
