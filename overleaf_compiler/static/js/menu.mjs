// メニュー（ファイル・編集・表示・ヘルプ、ファイルツリーの ⋮）。項目を押すと data-act を runAct に渡す
import { $ } from "./util.mjs";

export function closeMenus() {
  document.querySelectorAll(".menu.open, .mtop.open, .mi.sub.open").forEach((m) => m.classList.remove("open"));
}
export function openMenu(id, x, y) {
  const m = $(id);
  m.classList.add("open");
  m.style.left = `${Math.min(x, innerWidth - m.offsetWidth - 8)}px`;
  m.style.top = `${Math.min(y, innerHeight - m.offsetHeight - 8)}px`;
  return m;
}
export function initMenus(runAct) {
  document.querySelectorAll(".mtop").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const was = b.classList.contains("open");
      closeMenus();
      if (was) return;
      b.classList.add("open");
      const r = b.getBoundingClientRect();
      openMenu(b.dataset.menu, r.left, r.bottom + 4);
    };
    b.onmouseenter = () => { if (document.querySelector(".mtop.open") && !b.classList.contains("open")) b.click(); };
  });
  document.querySelectorAll(".mi.sub").forEach((mi) => {
    const show = () => {
      mi.classList.add("open");
      const r = mi.getBoundingClientRect();
      openMenu(mi.dataset.sub, r.right + 2, r.top - 5);
    };
    mi.onmouseenter = show; mi.onclick = (e) => { e.stopPropagation(); show(); };
  });
  document.querySelectorAll(".menu").forEach((m) => m.addEventListener("click", (e) => {
    const mi = e.target.closest(".mi[data-act]");
    if (!mi) return;
    e.stopPropagation(); closeMenus(); runAct(mi.dataset.act);
  }));
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu")) closeMenus(); });
}
