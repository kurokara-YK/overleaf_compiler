// 画面のテーマ（Overleaf と同じく、ライト・ダーク・システムに合わせる）。html の data-theme を切り替える。
// 最初の描画でちらつかないよう、index.html の <head> でも同じ判定をしている
import { store } from "./util.mjs";

const media = matchMedia("(prefers-color-scheme: light)");
export const themeSetting = () => store.get("oc.theme", "system");   // system / light / dark

function apply() {
  const t = themeSetting();
  document.documentElement.dataset.theme = t === "system" ? (media.matches ? "light" : "dark") : t;
  document.querySelectorAll(".mi[data-act^='theme:']").forEach((m) =>
    m.classList.toggle("checked", m.dataset.act === `theme:${t}`));
}
export function setTheme(t) { store.set("oc.theme", t); apply(); }
media.addEventListener("change", apply);   // システムの設定が変わったら、合わせている場合だけ変わる
apply();
