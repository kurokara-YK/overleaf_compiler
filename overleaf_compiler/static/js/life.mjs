// この画面が開いていることをサーバに知らせる。アプリとして動いているサーバは、画面（アプリのウィンドウ・Web のタブ）が
// 全部閉じたら止まる（server.py の PAGES）。閉じるときは sendBeacon で「閉じた」を送る
import { tab } from "./util.mjs";

const hello = () => fetch(`/api/hello?t=${tab.t}`, { method: "POST", keepalive: true }).catch(() => {});
hello();
setInterval(hello, 20000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) hello(); });
addEventListener("pagehide", () => navigator.sendBeacon(`/api/bye?t=${tab.t}`));
addEventListener("pageshow", (e) => { if (e.persisted) hello(); });   // 戻る・進むで戻ってきた
