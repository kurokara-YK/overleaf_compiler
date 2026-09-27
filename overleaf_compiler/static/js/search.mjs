// 原稿の全ファイルの検索（左のパネル）。大文字小文字・正規表現・単語単位
import { $, api, enc, escapeHtml, fail, bus } from "./util.mjs";
import { cm, openTab, jumpTo } from "./editor.mjs";
import { setView } from "./panels.mjs";

const sopt = { case: false, regex: false, word: false };
[["sCase", "case"], ["sRegex", "regex"], ["sWord", "word"]].forEach(([id, k]) => {
  $(id).onclick = () => { sopt[k] = !sopt[k]; $(id).classList.toggle("on", sopt[k]); if ($("sq").value) doSearch(); };
});
async function doSearch() {
  const q = $("sq").value;
  if (!q) return;
  try {
    const r = await api(`/api/search?q=${enc(q)}&case=${+sopt.case}&regex=${+sopt.regex}&word=${+sopt.word}`);
    $("searchInfo").textContent = r.total ? `${r.total} 件（${r.files.length} ファイル）${r.truncated ? "・多すぎるので途中まで" : ""}` : "見つからない";
    const list = $("searchList");
    list.replaceChildren();
    for (const f of r.files) {
      const head = document.createElement("div");
      head.className = "sfile";
      head.innerHTML = `▾ ${escapeHtml(f.path)}<span class="cnt">${f.hits.reduce((a, h) => a + h.spans.length, 0)}</span>`;
      const box = document.createElement("div");
      head.onclick = () => { box.hidden = !box.hidden; head.firstChild.textContent = box.hidden ? "▸ " : "▾ "; };
      for (const h of f.hits) {
        const d = document.createElement("div");
        d.className = "shit";
        let html = "", pos = 0;
        for (const [a, b] of h.spans) { html += escapeHtml(h.text.slice(pos, a)) + `<mark>${escapeHtml(h.text.slice(a, b))}</mark>`; pos = b; }
        html += escapeHtml(h.text.slice(pos));
        d.innerHTML = `<span class="ln">${h.line}</span><span class="tx">${html.trimStart()}</span>`;
        d.onclick = async () => {
          try { await openTab(f.path); jumpTo(h.line, h.spans[0][0], h.spans[0][1] - h.spans[0][0]); } catch (e) { fail(e); }
        };
        box.appendChild(d);
      }
      list.append(head, box);
    }
  } catch (e) { $("searchInfo").textContent = e.message; }
}
$("sgo").onclick = doSearch;
$("sq").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) doSearch(); });

bus.on("view", (v) => { if (v === "search") setTimeout(() => $("sq").focus(), 0); });

// Ctrl+Shift+F。エディタで選んでいる文字があれば、それで探す
export function openSearch() {
  const sel = cm.getSelection();
  setView("search");
  if (sel && !sel.includes("\n")) { $("sq").value = sel; doSearch(); }
}
