// アウトライン（開いているファイルの \section などの一覧。ファイルツリーの下）
import { $, bus } from "./util.mjs";
import { cm, active, modeOf, jumpTo } from "./editor.mjs";

const LEVEL = { part: 0, chapter: 0, section: 1, subsection: 2, subsubsection: 3, paragraph: 4 };
let outlineItems = [], outlineTimer = null;
function outlineSoon() { clearTimeout(outlineTimer); outlineTimer = setTimeout(renderOutline, 400); }
function renderOutline() {
  const list = $("outlineList");
  outlineItems = [];
  if (active && modeOf(active.path) === "stex") {
    active.doc.eachLine((lh) => {
      const m = lh.text.match(/^\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\{(.*)\}/);
      if (m) outlineItems.push({ line: active.doc.getLineNumber(lh), level: LEVEL[m[1]], title: m[2].replace(/\\label\{[^}]*\}/, "") });
    });
  }
  list.replaceChildren(...outlineItems.map((o) => {
    const d = document.createElement("div");
    d.className = "oitem"; d.style.paddingLeft = `${12 + o.level * 14}px`;
    d.textContent = o.title; d.title = `${o.line + 1} 行`;
    d.onclick = () => jumpTo(o.line + 1);
    return d;
  }));
  if (!outlineItems.length) list.innerHTML = '<div class="oitem" style="color:var(--hint);cursor:default">見出し（\\section など）が無い</div>';
  markOutline();
}
function markOutline() {
  if (!outlineItems.length) return;
  const l = cm.getCursor().line;
  let cur = -1;
  outlineItems.forEach((o, i) => { if (o.line <= l) cur = i; });
  [...$("outlineList").children].forEach((el, i) => el.classList.toggle("cur", i === cur));
}
$("outlineHead").onclick = () => {
  const l = $("outlineList"); l.hidden = !l.hidden;
  $("outlineHead").querySelector("span").textContent = `${l.hidden ? "▸" : "▾"} アウトライン`;
};
bus.on("activate", renderOutline);
bus.on("edit", outlineSoon);   // 入力が止まって 0.4 秒で作り直す
bus.on("cursor", markOutline);
