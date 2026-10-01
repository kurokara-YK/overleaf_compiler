// 開き方（ヘッダ右端のボタン）。アプリのウィンドウなら「Web で開く」「アプリを閉じて Web で開く」、
// ブラウザのタブなら「アプリで開く」。どちらもサーバに頼んで開く（アプリのウィンドウからは、ふつうのブラウザを開けないため）
import { $, post, fail, showToast } from "./util.mjs";
import { openMenu } from "./menu.mjs";

// アプリのウィンドウは、開くときの URL に app=1 が付く（launcher.py）。読み直しても分かるよう、このウィンドウに覚える
const q = new URLSearchParams(location.search);
let isApp = false;
try { isApp = q.get("app") === "1" || sessionStorage.getItem("oc.app") === "1"; if (isApp) sessionStorage.setItem("oc.app", "1"); } catch {}
if (q.has("app")) { q.delete("app"); history.replaceState(history.state, "", location.pathname + (q.toString() ? `?${q}` : "")); }
document.body.dataset.app = isApp ? "1" : "0";
document.documentElement.dataset.app = isApp ? "1" : "0";
$("webBtn").textContent = isApp ? "🌐 Web で開く ▾" : "🖥 アプリで開く";
$("webBtn").onclick = (e) => {
  if (!isApp) return webAct("app");
  e.stopPropagation();
  const r = $("webBtn").getBoundingClientRect();
  openMenu("mWeb", r.right - 260, r.bottom + 4);
};
export async function webAct(v) {
  // 今の画面（原稿・フォルダ・履歴）と同じ所を開く
  const search = location.search.replace(/^\?/, "");
  try {
    if (v === "app") {
      await post("/api/open_app", { search });
      showToast("アプリのウィンドウで開いた。このタブは閉じてよい", "ok", 5000);
    } else {
      const r = await post("/api/open_web", { search, close: v === "close" });
      if (!r.opened) showToast("ブラウザを開けなかった。端末に出た URL を開くこと", "err", 6000);
    }
  } catch (e) { fail(e); }
}
