// メニューの項目（data-act）の操作。ファイル・編集・表示・ヘルプ、ファイルツリーの ⋮、コメントのダウンロード
import { $, api, escapeHtml, modal, closeBtn, showToast, fail, url } from "./util.mjs";
import { cm, saveAll, toggleMd, fontSize } from "./editor.mjs";
import { setView, setLayout, toggleSide } from "./panels.mjs";
import { toggleClaude } from "./claude/index.mjs";
import { newFile, newFolder, itemAct } from "./tree.mjs";
import { showHistory } from "./history.mjs";
import { openSearch } from "./search.mjs";
import { fitWidth } from "./pdf.mjs";
import { recompile } from "./compile.mjs";
import { downloadAnnotated } from "./comments/index.mjs";
import { setTheme } from "./theme.mjs";
import { setEdMode } from "./visual.mjs";
import { headingAct } from "./toolbar.mjs";
import { openHistory } from "./histpage.mjs";
import { ask, post, tab, setTabProject, bus } from "./util.mjs";
import { openMenu } from "./menu.mjs";
import { homeItemAct } from "./home.mjs";
import { webAct } from "./appmode.mjs";
import { info } from "./state.mjs";

// 原稿のメニュー（ヘッダの原稿名）。Overleaf のプロジェクト名のメニューと同じ
$("ptitle").onclick = (e) => { e.stopPropagation(); const r = $("ptitle").getBoundingClientRect(); openMenu("mProject", r.left, r.bottom + 4); };
async function copyProject() {
  const name = await ask("複製を作る", "新しい原稿のフォルダ名", `${$("ptname").textContent}_コピー`);
  if (!name) return;
  try {
    const r = await post("/api/copy", { name });
    const o = await post("/api/open", { tex: r.tex, t: tab.t });
    setTabProject(o.rel); await bus.emit("reopen");
    showToast(`「${escapeHtml(name)}」を作って開いた`, "ok");
  } catch (e) { fail(e); }
}
async function renameProject() {
  const name = await ask("名前を変更", "原稿のフォルダの新しい名前（Overleaf 側の名前は変わらない）", $("ptname").textContent);
  if (!name || name === $("ptname").textContent) return;
  try {
    await saveAll();
    const o = await post("/api/rename_project", { name });
    setTabProject(o.rel, false); await bus.emit("reopen");
    showToast(`「${escapeHtml(name)}」に名前を変えた`, "ok");
  } catch (e) { fail(e); }
}

async function wordCount() {
  try {
    const r = await api("/api/wordcount");
    const rows = (r.text.match(/^(Words in text|Words in headers|Words outside text.*|Number of headers|Number of floats.*|Number of math inlines|Number of math displayed): (\d+)/gm) || [])
      .map((l) => l.split(": "));
    const ja = { "Words in text": "本文", "Words in headers": "見出し", "Number of headers": "見出しの数",
                 "Number of math inlines": "文中の数式", "Number of math displayed": "別行の数式" };
    const jaOf = (k) => ja[k] || (k.startsWith("Words outside text") ? "キャプションなど" : k.startsWith("Number of floats") ? "図表の数" : k);
    await modal("文字数（texcount）", `<table><tr><td>合計</td><td><b>${r.sum ?? "?"}</b>（和文は1字＝1語として数える）</td></tr>
      ${rows.map(([k, v]) => `<tr><td>${escapeHtml(jaOf(k))}</td><td>${v}</td></tr>`).join("")}</table>
      <details style="margin-top:10px"><summary class="kbd">詳しい出力</summary><pre>${escapeHtml(r.text)}</pre></details>`,
      closeBtn);
  } catch (e) { fail(e); }
}
function download(fmt) {
  if (fmt === "pdf") { location.href = url("/pdf?download=1"); return; }
  if (fmt === "annotated") return downloadAnnotated();
  if (fmt === "comments") { location.href = url("/export?format=comments"); return; }
  if (fmt !== "zip") showToast(`${fmt.toUpperCase()} に書き出している…（pandoc。数式や表は崩れることがある）`, "", 5000);
  location.href = url(`/export?format=${fmt}`);
}
function shortcuts() {
  const rows = [["Ctrl+S", "今すぐ保存（入力は自動でも保存される）"], ["Ctrl+Enter", "リコンパイル"],
    ["Ctrl+Shift+F", "原稿の中を検索"], ["Ctrl+Shift+V", "Markdown のプレビュー"], ["Ctrl+Z / Ctrl+Y", "元に戻す／やり直す"],
    ["PDF をダブルクリック", "ソースの該当行へ"], ["PDF の文字を選ぶ", "💬 コメント・✎ ここで直す・コピー・ソースへ"],
    ["PDF のコメントをクリック", "コメントの一覧で開く"],
    ["→ / ←（境目）", "カーソル行を PDF で示す／PDF の位置のソースへ"], ["Ctrl+ホイール（PDF）", "拡大・縮小"], ["Esc", "メニューや窓を閉じる"]];
  modal("キーボードショートカット", `<table>${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>`,
        closeBtn);
}
export async function runAct(a) {
  const [k, v] = a.split(":");
  switch (k) {
    case "newFile": return newFile();
    case "newFolder": return newFolder();
    case "upload": return $("tUpload").click();
    case "history": return openHistory();
    case "copyProject": return copyProject();
    case "renameProject": return renameProject();
    case "head": return headingAct(v);
    case "wordcount": return wordCount();
    case "dl": return download(v);
    case "recompile": return recompile();
    case "home": return $("brand").click();
    case "undo": return cm.undo();
    case "redo": return cm.redo();
    case "selectAll": cm.focus(); return cm.execCommand("selectAll");
    case "search": return openSearch();
    case "save": return saveAll();
    case "layout": return setLayout(v);
    case "theme": return setTheme(v);
    case "edmode": return setEdMode(v);
    case "toggleSide": return toggleSide();
    case "claude": return toggleClaude();
    case "comments": return setView("comments");
    case "mdPreview": return toggleMd();
    case "fit": return fitWidth();
    case "fontUp": return fontSize(1);
    case "fontDown": return fontSize(-1);
    case "shortcuts": return shortcuts();
    case "about": return modal("この画面について", `Overleaf からダウンロードした原稿を、ローカルで組んで直すための画面。<br>
        Overleaf には触らない。Overleaf へ戻すときは「ファイル → ダウンロード → ソース (.zip)」で作った zip を、
        Overleaf の New Project → Upload Project に入れる。<br><br>
        <span class="kbd">ファイルの前の版は、原稿のフォルダの外（~/.local/share/overleaf-compiler/）に残している</span>`,
        closeBtn);
    case "item": return itemAct(v);
    case "hitem": return homeItemAct(v);
    case "web": return webAct(v);   // 一覧の項目の ⋮（"home" はファイル →「一覧に戻る」で使っている）
  }
}
