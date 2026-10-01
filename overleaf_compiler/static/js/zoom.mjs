// 拡大・縮小（VS Code と同じキー）。Ctrl+Shift+ー（= Ctrl+=）・Ctrl++ で拡大、Ctrl+ー で縮小、Ctrl+0 で元に戻す。
// 画面全体ではなく、今さわっている所（PDF・エディタ・チャット欄・一覧）だけを変える。
// 画面全体に CSS の zoom をかけると、エディタのカーソルや PDF のクリック位置がずれるため
import { $, store, showToast } from "./util.mjs";
import { fontSize } from "./editor.mjs";
import { fitWidth } from "./pdf.mjs";

let area = "editor";   // 最後にさわった所
function areaOf(el) {
  if (!(el instanceof Element)) return area;
  if (el.closest("#preview")) return "pdf";
  if (el.closest("#claude, .ccpop")) return "chat";
  if (el.closest("#editor, #side")) return "editor";
  if (el.closest("#home")) return "home";
  return area;
}
document.addEventListener("pointerdown", (e) => { area = areaOf(e.target); }, true);
document.addEventListener("focusin", (e) => { area = areaOf(e.target); }, true);

// チャット欄と一覧は、倍率（CSS の変数）で大きくする
const SCALE = { chat: ["oc.ccZoom", "--cc-zoom", "#claude"], home: ["oc.homeZoom", "--home-zoom", "#home"] };
function applyScale(kind, v) {
  const [key, prop, sel] = SCALE[kind];
  v = Math.round(Math.max(0.6, Math.min(2, v)) * 10) / 10;
  store.set(key, String(v));
  document.querySelector(sel).style.setProperty(prop, v);
  return v;
}
for (const k of Object.keys(SCALE)) applyScale(k, parseFloat(store.get(SCALE[k][0], "1")) || 1);
export const chatZoom = () => parseFloat(store.get("oc.ccZoom", "1")) || 1;

function zoom(dir) {   // dir: 1 拡大, -1 縮小, 0 元に戻す
  const where = document.body.className === "home" ? "home" : area === "home" ? "editor" : area;
  if (where === "pdf") {
    if (dir === 0) fitWidth(); else $(dir > 0 ? "zin" : "zout").click();
    return;
  }
  if (where === "editor") {
    const now = parseInt(store.get("oc.editorFontSize", 12));
    fontSize(dir === 0 ? 12 - now : dir);
    showToast(`エディタの文字 ${store.get("oc.editorFontSize", 12)}px`, "", 1200);
    return;
  }
  const now = parseFloat(store.get(SCALE[where][0], "1")) || 1;
  const v = applyScale(where, dir === 0 ? 1 : now + dir * 0.1);
  showToast(`${where === "chat" ? "チャット欄" : "一覧"} ${Math.round(v * 100)}%`, "", 1200);
}
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const k = e.key, c = e.code;
  // 日本語キーボードの Ctrl+Shift+ー は key が "="。テンキーの＋－０も同じに扱う
  const dir = k === "+" || k === "=" || c === "NumpadAdd" ? 1
    : (k === "-" && !e.shiftKey) || c === "NumpadSubtract" ? -1
    : k === "0" || c === "Numpad0" ? 0 : null;
  if (dir === null) return;
  e.preventDefault(); e.stopPropagation();   // ブラウザのページ全体の拡大は使わない
  zoom(dir);
}, true);
