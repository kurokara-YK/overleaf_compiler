// コメント（Acrobat の注釈に当たる）の入口。各部品を読み込み、画面の出来事につなぐ
//   model.mjs    状態と読み込み        marks.mjs   PDF とエディタの印
//   panel.mjs    一覧（左のパネル）    compose.mjs 付ける窓
//   export.mjs   コメント付き PDF      import.mjs  コメント付き PDF の取り込み
import { $, bus } from "../util.mjs";
import { pointIn } from "../pdf.mjs";
import { loadComments } from "./model.mjs";
import { placeComments, markEditorComments, commentAt } from "./marks.mjs";
import { renderComments, focusComment } from "./panel.mjs";
import "./compose.mjs";
import "./import.mjs";

export { loadComments, resetComments, cmtMtime } from "./model.mjs";
export { hideCompose } from "./compose.mjs";
export { downloadAnnotated } from "./export.mjs";

// 読み直したら、PDF 上の位置を探し直してから一覧と印を出す（一覧は探した結果を使う）
bus.on("comments", () => { placeComments(); renderComments(); markEditorComments(); });
// PDF を組み直したら、今の一覧で描き直してから読み直す（ソースの行が変わっている）
bus.on("rendered", () => { placeComments(); loadComments(); });
bus.on("activate", markEditorComments);
bus.on("view", (v) => { if (v === "comments") renderComments(); });

// PDF 上のコメントの印を押すと、一覧でそのコメントを開く
$("pages").addEventListener("click", (e) => {
  if (e.detail > 1 || !getSelection().isCollapsed) return;
  const pg = e.target.closest(".page");
  if (!pg) return;
  const hit = commentAt(...pointIn(pg, e.clientX, e.clientY));
  if (hit) focusComment(hit.id, true);
});
