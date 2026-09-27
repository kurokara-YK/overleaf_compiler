// コメントを付ける窓（PDF の文字を選んで 💬 コメント）。コメント・削除の提案・置換の提案
import { $, post, fail } from "../util.mjs";
import { selInfo, hideSel, tidySel, openNear } from "../select.mjs";
import { needAuthor, loadComments } from "./model.mjs";
import { focusComment } from "./panel.mjs";

let cKind = "highlight";
export function hideCompose() { $("cbox").classList.remove("open"); }
function setKind(k) {
  cKind = k;
  $("cbox").querySelectorAll(".kinds button").forEach((b) => b.classList.toggle("on", b.dataset.k === k));
  $("cSuggest").hidden = k !== "replace";
  $("cText").placeholder = k === "highlight" ? "コメント" : "コメント（書かなくてもよい）";
}
$("cbox").querySelector(".kinds").onclick = (e) => {
  const b = e.target.closest("button[data-k]");
  if (!b) return;
  setKind(b.dataset.k);
  (b.dataset.k === "replace" ? $("cSuggest") : $("cText")).focus();
};
$("selComment").onclick = () => {
  if (!selInfo) return;
  hideSel();
  const box = $("cbox"), si = selInfo;
  box._sel = si;
  setKind("highlight");
  $("cQuote").textContent = tidySel(si.text);
  $("cSuggest").value = tidySel(si.text); $("cText").value = "";
  openNear(box, si);
  $("cText").focus();
};
$("cCancel").onclick = hideCompose;
for (const id of ["cText", "cSuggest"]) $(id).addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey || id === "cSuggest") && !e.isComposing) { e.preventDefault(); $("cOk").click(); }
  else if (e.key === "Escape") { e.preventDefault(); hideCompose(); }
});
$("cOk").onclick = async () => {
  const si = $("cbox")._sel, text = $("cText").value.trim(), suggest = cKind === "replace" ? $("cSuggest").value : "";
  if (!si) return;
  if (cKind === "highlight" && !text) return $("cText").focus();
  const author = await needAuthor();
  if (!author) return;
  try {
    const r = await post("/api/comment", { action: "add", page: si.page, x: si.x, y: si.y, quote: si.text, rects: si.rects,
                                           kind: cKind, text, suggest, author });
    hideCompose(); getSelection().removeAllRanges();
    await loadComments();
    focusComment(r.comment.id, true);
  } catch (e) { fail(e); }
};
