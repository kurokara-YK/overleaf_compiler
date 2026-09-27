// コメントの一覧（左のパネル）。カード・返信・解決・編集・削除と、PDF・ソースの該当箇所へ移る操作
import { $, post, escapeHtml, ago, confirmBox, modal, closeBtn, showToast, fail } from "../util.mjs";
import { info } from "../state.mjs";
import { openTab, jumpTo } from "../editor.mjs";
import { viewShown, setView, revealEditor } from "../panels.mjs";
import { viewer, pagesEl, scale, pageSizes, showBoxes } from "../pdf.mjs";
import { comments, cmtActive, cmtFilter, setActive, setFilter, inFilter, isResolved, needAuthor, loadComments,
         KIND, PIN_KINDS } from "./model.mjs";
import { drawMarks, markEditorComments, pinOf } from "./marks.mjs";

const FILTER_LABEL = { open: "未解決", resolved: "解決済み", all: "すべて" };
function hue(s) { let h = 0; for (const ch of s) h = (h * 31 + ch.codePointAt(0)) % 360; return h; }
const agoIso = (iso) => ago(Date.parse(iso) / 1000);
function readingKey(c) {   // PDF の読む順（ページ → 段 → 上から）
  const r = (c._rects && c._rects[0]) || c._pin || (c.rects && c.rects[0]) || c.pin || [c.page, 0, 0];
  const w = (pageSizes[r[0] - 1] || { w: 600 }).w;
  return [r[0], r[1] > w / 2 ? 1 : 0, r[2]];
}

export function renderComments() {
  const open = comments.filter((c) => !isResolved(c)).length;
  $("cmtBadge").textContent = open || "";
  const counts = { open, resolved: comments.length - open, all: comments.length };
  for (const b of $("vComments").querySelectorAll(".cfilter button")) {
    b.classList.toggle("on", b.dataset.f === cmtFilter);
    b.textContent = `${FILTER_LABEL[b.dataset.f]} ${counts[b.dataset.f]}`;
  }
  if (!viewShown("comments")) return;
  const list = $("cmtList");
  const shown = comments.filter((c) => inFilter(c))
    .map((c) => [readingKey(c), c]).sort(([a], [b]) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]).map(([, c]) => c);
  if (!shown.length) {
    list.innerHTML = `<div class="empty">${comments.length ? "この絞り込みでは無い" :
      "コメントは無い。<br>PDF の文字を選んで <b>💬 コメント</b> で付ける。<br>Acrobat などでコメントを付けた PDF は、上の ⤒ かここへのドロップで取り込める"}</div>`;
    return;
  }
  const open0 = list.querySelector(".rbox textarea");   // 書きかけの返信は消さない
  const draft = open0 ? { id: open0.closest(".ccard").dataset.id, mode: open0.dataset.mode, text: open0.value } : null;
  list.replaceChildren(...shown.map((c) => cardEl(c)));
  if (draft) { const card = list.querySelector(`.ccard[data-id="${draft.id}"]`); if (card) openRbox(card, comments.find((c) => c.id === draft.id), draft.mode, draft.text); }
}
function cardEl(c) {
  const d = document.createElement("div");
  d.className = `ccard k-${c.kind}${c.id === cmtActive ? " on" : ""}${isResolved(c) ? " resolved" : ""}`;
  d.dataset.id = c.id;
  const who = c.author || "名無し";
  const warn = isResolved(c) ? `<div class="warn" style="color:var(--ok)">✓ 解決済み（${escapeHtml(c.resolved_by || "")}）</div>`
    : c.found === false ? '<div class="warn">⚠ 対象の文字がソースに無い（直された可能性がある）</div>'
    : c._inPdf === false && c.quote ? '<div class="warn">⚠ PDF の上では文字を探せないので、付けたときの位置に出している</div>' : "";
  d.innerHTML = `<div class="c1"><span class="av" style="background:hsl(${hue(who)} 45% 42%)">${escapeHtml([...who.trim()][0] || "?")}</span>
      <span class="who">${escapeHtml(who)}</span><span class="when">${agoIso(c.created)}</span></div>
    ${c.kind !== "highlight" ? `<span class="kind">${KIND[c.kind] || c.kind}</span>` : ""}
    ${c.quote && !PIN_KINDS.has(c.kind) ? `<div class="cq"><span>${escapeHtml(c.quote)}</span></div>` : ""}
    ${c.suggest ? `<div class="sug">→ ${escapeHtml(c.suggest)}</div>` : ""}
    ${c.text ? `<div class="ct">${escapeHtml(c.text)}</div>` : ""}
    ${(c.replies || []).map((r) => `<div class="rp"><b>${escapeHtml(r.author)}</b><span class="when">${agoIso(r.created)}</span>
      <div class="t">${escapeHtml(r.text)}</div></div>`).join("")}
    ${warn}
    <div class="loc">${c.file ? `<a data-src title="ソースのこの行を開く">📄 ${escapeHtml(c.file)}:${c.line}</a>` : "ソースの場所が分からない"}・${(c._rects || c.rects || [[c.page]])[0][0]} ページ</div>
    <div class="cacts"><button data-a="reply">返信</button>
      <button data-a="${isResolved(c) ? "reopen" : "resolve"}">${isResolved(c) ? "未解決に戻す" : "✓ 解決"}</button>
      <button data-a="edit">編集</button><button data-a="delete">削除</button></div>`;
  d.onclick = (e) => {
    if (e.target.closest(".rbox")) return;
    const a = e.target.closest("[data-a]"), src = e.target.closest("[data-src]");
    if (src) { e.stopPropagation(); return openCommentSource(c); }
    if (a) { e.stopPropagation(); return cardAct(c, a.dataset.a, d); }
    if (cmtActive !== c.id) focusComment(c.id);
    else scrollToComment(c);
  };
  return d;
}
document.querySelectorAll("#vComments .cfilter button").forEach((b) => b.onclick = () => { setFilter(b.dataset.f); renderComments(); });

// コメントを選ぶ。一覧を開いてそのカードを見せ、PDF の印を強調する（fromPdf でなければ PDF もその場所へ）
export function focusComment(id, fromPdf = false) {
  setActive(id);
  const c = comments.find((x) => x.id === id);
  if (c && !inFilter(c)) setFilter("all");
  if (!viewShown("comments")) setView("comments"); else renderComments();
  drawMarks(); markEditorComments();
  const card = $("cmtList").querySelector(`.ccard[data-id="${id}"]`);
  if (card) card.scrollIntoView({ block: "nearest" });
  if (!fromPdf && c) scrollToComment(c);
}
function scrollToComment(c) {
  const r = pinOf(c) || (c._rects && c._rects[0]);
  if (!r) {   // 直されて PDF に無い。付けたときの位置を一瞬示す
    if (c.rects && c.rects.length) showBoxes(c.rects.map(([page, x, y, w, h]) => ({ page, x, y, w, h })));
    return;
  }
  const pg = pagesEl.querySelector(`.page[data-page="${r[0]}"]`);
  if (pg) viewer.scrollTop = pg.offsetTop + r[2] * scale - viewer.clientHeight / 3;
}
async function openCommentSource(c) {
  if (!c.file) return;
  revealEditor();
  try {
    await openTab(c.file);
    if (c.found && c.range) jumpTo(c.range[0] + 1, c.range[1], c.range[0] === c.range[2] ? c.range[3] - c.range[1] : 0);
    else jumpTo(c.line || 1);
  } catch (e) { fail(e); }
}

// ---- 返信・編集の欄（カードの中）----
function openRbox(card, c, mode, text) {
  card.querySelector(".rbox")?.remove();
  const box = document.createElement("div");
  box.className = "rbox";
  box.innerHTML = `${mode === "edit" && c.kind === "replace" ? `<input class="sg" value="${escapeHtml(c.suggest || "")}" placeholder="置き換える文字">` : ""}
    <textarea rows="3" data-mode="${mode}" placeholder="${mode === "reply" ? "返信" : "コメント"}"></textarea>
    <div class="r"><span class="kbd" style="flex:1">Ctrl+Enter で送る</span><button data-x>やめる</button><button class="primary" data-ok>${mode === "reply" ? "返信" : "保存"}</button></div>`;
  card.appendChild(box);
  const ta = box.querySelector("textarea");
  ta.value = text ?? (mode === "edit" ? c.text || "" : "");
  const close = () => box.remove();
  const ok = async () => {
    const t = ta.value.trim();
    try {
      if (mode === "reply") {
        if (!t) return ta.focus();
        const a = await needAuthor(); if (!a) return;
        await post("/api/comment", { action: "reply", id: c.id, author: a, text: t });
      } else {
        const sg = box.querySelector(".sg");
        await post("/api/comment", { action: "edit", id: c.id, text: t, ...(sg ? { suggest: sg.value } : {}) });
      }
      close(); await loadComments();
    } catch (e) { fail(e); }
  };
  box.querySelector("[data-x]").onclick = close;
  box.querySelector("[data-ok]").onclick = ok;
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); ok(); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });
  ta.focus();
}
async function cardAct(c, a, card) {
  if (a === "reply" || a === "edit") return openRbox(card, c, a);
  try {
    if (a === "delete") {
      if (!(await confirmBox("コメントを削除", `${escapeHtml(c.author)} のコメントを消す？（返信も消える）`, "削除", true))) return;
      await post("/api/comment", { action: "delete", id: c.id });
      if (cmtActive === c.id) setActive(null);
    } else {   // resolve・reopen
      const who = await needAuthor(); if (!who) return;
      await post("/api/comment", { action: a, id: c.id, author: who });
    }
    await loadComments();
  } catch (e) { fail(e); }
}

// ---- AI（Claude Code）に頼む ----
$("cAi").onclick = async () => {
  const n = comments.filter((c) => !isResolved(c)).length;
  if (!n) return showToast("未解決のコメントは無い", "", 2500);
  const doc = `data/${info.rel}`;
  const text = `${doc} の PDF に付いた未解決のコメント（${n} 件）を直して。\n` +
    `一覧は overleaf-compiler comments "${doc}" で出る（file:line 付き）。\n` +
    `1件ずつ直し、overleaf-compiler check "${doc}" で確かめてから、overleaf-compiler comments "${doc}" --resolve <ID> -m "何をどう直したか" で解決済みにすること。\n` +
    `判断に迷うコメント（内容の書き足しや方針の変更が要るもの）は直さずに、何が要るかを返信で残すこと。`;
  try { await navigator.clipboard.writeText(text); showToast("依頼文をコピーした。Claude Code に貼り付ける", "ok", 3500); }
  catch { await modal("AI への依頼文", `<pre style="white-space:pre-wrap">${escapeHtml(text)}</pre>`, closeBtn); }
};
