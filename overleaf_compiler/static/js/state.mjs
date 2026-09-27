// いま開いている原稿（/api/info）。main.mjs の refreshInfo だけが書き換える
export let info = null;
export function setInfo(i) { info = i; }
