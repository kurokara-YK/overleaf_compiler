// Git の画面（ヘッダの ⎇ Git）。サーバ側は gitops.py（Git）と ghauth.py（GitHub との連携）。
//   原稿（既定）：data の中のフォルダを、選んだ GitHub のアカウント・リポジトリ・ブランチへ上げる
//   本体　　　　：overleaf-compiler 自身のリポジトリ
// GitHub へは、デバイスコードでログインする（gh が覚えるので、アプリを閉じても連携は続く。「連携をやめる」で外す）
import { $, api, post, enc, escapeHtml, modal, ask, confirmBox, closeBtn, showToast, store, ago } from "./util.mjs";
import { info } from "./state.mjs";
import { showHist } from "./githist.mjs";

let prev = null;                // Git の画面を開く前の画面（home / editing）
let mode = store.get("oc.gitMode", "data");
let view = store.get("oc.gitView", "commit");   // commit（変更とコミット）か hist（編集履歴）
let dir = "";                   // 原稿のフォルダ（data からの相対パス）
let st = null;                  // /api/git/status
let accounts = [];              // 連携している GitHub のアカウント
let sel = null;                 // 差分を出しているファイル
const unchecked = new Set();    // 入れないことにしたファイル

const P = () => ({ mode, dir });
const qs = (extra = {}) => "?" + new URLSearchParams({ ...P(), ...extra }).toString();
const gget = (name, extra) => api(`/api/git/${name}${qs(extra)}`);
const gpost = (name, body = {}) => post(`/api/git/${name}`, { ...P(), ...body });

// 編集中の原稿のフォルダ（主文書のあるフォルダ）
const openDir = () => info && info.rel ? info.rel.split("/").slice(0, -1).join("/") : "";

export async function openGit(opts = {}) {
  if (opts.mode) mode = opts.mode;
  if (opts.dir != null) dir = opts.dir;
  if (!dir) dir = openDir() || store.get("oc.gitDir", "");
  if (document.body.className !== "git") { prev = document.body.className; document.body.className = "git"; }
  setMode(mode);
  engines();
}
function closeGit() { document.body.className = prev || "home"; prev = null; }
$("gitBtn").onclick = () => document.body.className === "git" ? closeGit() : openGit();
$("gpBack").onclick = closeGit;
$("gpMode").onclick = (e) => { const b = e.target.closest("button[data-m]"); if (b) setMode(b.dataset.m); };
$("gpView").onclick = (e) => { const b = e.target.closest("button[data-v]"); if (b) { setView(b.dataset.v); refresh(); } };
function setView(v) {
  view = v; store.set("oc.gitView", v);
  for (const b of $("gpView").querySelectorAll("button")) b.classList.toggle("on", b.dataset.v === v);
  $("gitpage").dataset.view = v;
}
setView(view);
function setMode(m) {
  mode = m; store.set("oc.gitMode", m);
  for (const b of $("gpMode").querySelectorAll("button")) b.classList.toggle("on", b.dataset.m === m);
  $("gitpage").dataset.mode = m;
  sel = null; unchecked.clear(); $("gpDiff").textContent = ""; $("gpDiffHead").textContent = "ファイルを選ぶと、変更（足した行は緑、消した行は赤）が出る";
  refresh();
}

function line(text, cls = "") { const m = $("gpMsgLine"); m.className = `msgline ${cls}`; m.textContent = text; }
const busy = async (btn, label, fn) => {
  const old = btn.textContent; btn.disabled = true; btn.textContent = label;
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = old; }
};

// ---- 状態 ----
async function refresh(r) {
  if (mode === "data") await renderFolders();
  if (mode === "data" && !dir) { showSetup(false); st = null; await renderTarget(); line("GitHub に上げるフォルダを「選ぶ…」で選ぶ"); hist(false); return; }
  try { st = r || await gget("status"); } catch (e) { line(e.message, "err"); return; }
  if (mode === "data") store.set("oc.gitDir", dir);
  hist(st.is_repo !== false);
  if (mode === "data" && !st.is_repo) { showSetup(true); await renderTarget(); return; }
  showSetup(false);
  const sync = (st.upstream ? `${st.upstream} より ${st.ahead ? `↑${st.ahead}（まだ送っていない）` : ""}${st.behind && mode === "data" ? ` ↓${st.behind}（取り込める）` : ""}${!st.ahead && !(st.behind && mode === "data") ? "同じ" : ""}`
    : st.remote_url ? `まだ送っていない（${st.ahead} 件）` : mode === "data" ? "送り先が決まっていない" : "送り先（自分の GitHub）が決まっていない")
    + (mode === "tool" && st.updates ? `・元のリポジトリに新しい版 ${st.updates} 件` : "");
  $("gpSync").textContent = sync;
  $("gpSync").title = st.remote_url || "";
  $("gpPush").textContent = `⤒ push${st.ahead ? `（${st.ahead} 件）` : ""}`;
  $("gpUndo").disabled = !st.has_head || !!st.op || st.head_pushed;
  $("gpUndo").title = !st.has_head ? "まだコミットが無い" : st.head_pushed ? "直前のコミットはもう GitHub に送ってあるので、取り消せない"
    : `直前のコミット「${st.last}」と git add を取り消し、変更を一覧に戻す（ファイルの中身はそのまま）`;
  renderOp();
  await renderTarget();
  $("gpPull").textContent = mode === "tool" ? "⤓ 最新版に更新" : "⤓ 最新を取り込む";
  $("gpPull").title = mode === "tool" ? `元のリポジトリ（${st.origin_url || "origin"}）の新しい版を取り込む` : "GitHub の新しいコミットを取り込む（fast-forward のみ）";
  $("gpRepoLab").textContent = mode === "tool" ? "自分のリポジトリ" : "リポジトリ";
  renderFiles();
  await renderBranches();
  if (sel && !st.files.some((f) => f.path === sel)) { sel = null; $("gpDiff").textContent = ""; }
}
function hist(isRepo) { if (view === "hist") showHist(P(), isRepo); }
function showSetup(on) {
  $("gpSetup").style.display = on ? "block" : "none";
  $("gpBody").style.display = on ? "none" : "flex";
  $("gpSetupName").textContent = dir;
}
$("gpInit").onclick = () => busy($("gpInit"), "準備中…", async () => {
  try { await refresh(await gpost("init", { include_pdf: $("gpInclPdf").checked })); line("Git で管理するようにした。次に、アカウントとリポジトリを選ぶ", "ok"); }
  catch (e) { line(e.message, "err"); }
});

// ---- フォルダ（data の中）----
async function renderFolders() {
  let list = [];
  try { list = (await gget("folders")).folders; } catch {}
  const cand = [...new Set([dir, openDir(), ...list].filter(Boolean))];
  $("gpFolder").innerHTML = cand.map((d) => `<option value="${escapeHtml(d)}" ${d === dir ? "selected" : ""}>${escapeHtml(d)}${list.includes(d) ? "" : "（未管理）"}</option>`).join("")
    || '<option value="">（選んでいない）</option>';
}
$("gpFolder").onchange = () => { dir = $("gpFolder").value; sel = null; unchecked.clear(); refresh(); };
$("gpPickFolder").onclick = async () => {
  // data の中をたどって、上げるフォルダを選ぶ（/api/browse を使う）
  let at = dir ? dir.split("/").slice(0, -1).join("/") : "", pick = null;
  const p = modal("GitHub に上げるフォルダを選ぶ", '<div class="kbd">原稿1つでも、まとまり（いくつかの原稿の入ったフォルダ）でもよい</div><div id="gpfPath" class="gp-path"></div><div id="gpfList" class="ccrw"></div>',
    [{ label: "やめる", value: null }, { label: "このフォルダにする", value: "go", cls: "primary" }]);
  async function load(path) {
    at = path;
    $("gpfPath").innerHTML = `<a data-p="">data</a>` + path.split("/").filter(Boolean).map((x, i, a) => ` / <a data-p="${escapeHtml(a.slice(0, i + 1).join("/"))}">${escapeHtml(x)}</a>`).join("");
    const r = await api(`/api/browse?path=${enc(path)}`);
    $("gpfList").innerHTML = r.entries.map((e) => `<div class="it" data-d="${escapeHtml(e.dir)}" data-k="${e.kind}">
        <div class="l">${e.kind === "folder" ? "📁" : "📄"} ${escapeHtml(e.name)}</div><div class="dim">${e.kind === "folder" ? `原稿 ${e.count} 件・ダブルクリックで中へ` : "原稿"}</div></div>`).join("")
      || '<div class="dim">空のフォルダ</div>';
    pick = null;
  }
  $("gpfPath").onclick = (e) => { const a = e.target.closest("a[data-p]"); if (a) load(a.dataset.p); };
  $("gpfList").onclick = (e) => { const it = e.target.closest(".it"); if (!it) return; pick = it.dataset.d; $("gpfList").querySelectorAll(".it").forEach((x) => x.classList.toggle("on", x === it)); };
  $("gpfList").ondblclick = (e) => { const it = e.target.closest(".it"); if (it && it.dataset.k === "folder") load(it.dataset.d); };
  await load(at);
  if (await p === "go" && (pick || at)) { dir = pick || at; sel = null; unchecked.clear(); refresh(); }
};

// ---- GitHub のアカウント（デバイスコードでのログイン・連携をやめる）----
async function loadAccounts() {
  try {
    const r = await api("/api/gh/accounts");
    accounts = r.accounts;
    $("gpLogin").textContent = r.gh ? (accounts.length ? "＋ 別のアカウント" : "GitHub にログイン") : "GitHub と連携する（gh を入れる）";
    $("gpLogin").dataset.gh = r.gh ? "1" : "0";
  } catch (e) { accounts = []; line(e.message, "err"); }
}
async function renderTarget() {
  await loadAccounts();
  const cur = st?.account || accounts.find((a) => a.active)?.login || accounts[0]?.login || "";
  $("gpAccount").innerHTML = accounts.map((a) => `<option ${a.login === cur ? "selected" : ""}>${escapeHtml(a.login)}</option>`).join("") || '<option value="">（連携していない）</option>';
  $("gpLogout").style.display = accounts.length ? "" : "none";
  $("gpRepoBtn").textContent = st?.remote ? `${st.remote} ▾` : "選ぶ…";
  $("gpVis").textContent = st?.remote ? (st.private ? "非公開" : "公開") : "";
  $("gpVis").className = "badge" + (st?.remote && !st.private ? " warn" : "");
  $("gpCollab").style.display = st?.remote ? "" : "none";
}
$("gpAccount").onchange = () => { if (st?.remote) connect({ account: $("gpAccount").value, repo: st.remote, branch: st.target, private: st.private }); };
$("gpLogin").onclick = async () => {
  if ($("gpLogin").dataset.gh === "0") {
    return busy($("gpLogin"), "gh を入れている…", async () => {
      try { await post("/api/gh/install"); await loadAccounts(); line("gh（GitHub CLI）を入れた。続けて GitHub にログインする", "ok"); }
      catch (e) { line(e.message, "err"); }
    });
  }
  if (!(await deviceFlow("/api/gh/login", {}, "GitHub にログイン"))) return;
  await loadAccounts(); await renderTarget(); await refresh();   // 連携したアカウントを、すぐ欄に出す
  line("GitHub と連携した。アプリを閉じても覚えている", "ok");
};
// デバイスコードの手続き（ログイン・権限の追加）。許可されたら true
export async function deviceFlow(endpoint, body, title, note = "") {
  let r;
  try { r = await post(endpoint, body); } catch (e) { line(e.message, "err"); return false; }
  if (!r.code) { line(r.error || "始められなかった", "err"); return false; }
  let done = false;
  const p = modal(title, `<div class="gp-login">${note ? `<div class="kbd">${note}</div>` : ""}
      <div>1. 下のコードを写す</div><div class="code" id="gpCode">${escapeHtml(r.code)}</div>
      <div class="gp-row"><button id="gpCopy">コードをコピー</button><button id="gpOpen" class="primary">GitHub を開く</button></div>
      <div>2. 開いたページにコードを入れて、「Authorize」を押す（GitHub のいつものログイン方法で入る）</div>
      <div class="kbd" id="gpWait">許可されるのを待っている…</div></div>`, [{ label: "やめる", value: null }]);
  $("gpCopy").onclick = () => navigator.clipboard.writeText(r.code).then(() => showToast("コピーした", "ok", 1500));
  $("gpOpen").onclick = () => post("/api/open_url", { url: r.url || "https://github.com/login/device" });
  const poll = setInterval(async () => {   // 許可されたら、すぐ窓を閉じて先へ進む
    try {
      const a = await api("/api/gh/accounts");
      if (a.login.state === "done") { done = true; clearInterval(poll); document.querySelector("#mFoot button").click(); }
      else if (a.login.state === "error") { $("gpWait").textContent = `うまくいかなかった: ${a.login.error}`; clearInterval(poll); }
    } catch {}
  }, 1000);
  await p; clearInterval(poll);
  if (!done) post("/api/gh/login_cancel").catch(() => {});
  return done;
}
$("gpLogout").onclick = async () => {
  const user = $("gpAccount").value;
  if (!user) return;
  if (!(await confirmBox("連携をやめる", `GitHub のアカウント <b>${escapeHtml(user)}</b> との連携をやめる？<br>
      <span class="kbd">このパソコンに保存された権限を消す（gh auth logout）。GitHub の中身は消えない。端末の gh も同じ連携を使っていればそちらも外れる</span>`, "連携をやめる", true))) return;
  try { await post("/api/gh/logout", { user }); await refresh(); line(`${user} との連携をやめた`, "ok"); }
  catch (e) { line(e.message, "err"); }
};

// ---- リポジトリ（もうあるものから選ぶ／新しく作る、をページで分ける。新しく作るときは既定で非公開）----
async function connect(body) {
  try { await refresh(await gpost("connect", body)); line(`送り先を ${body.repo}（${body.branch}）にした`, "ok"); }
  catch (e) { line(e.message, "err"); }
}
let repoTab = "pick";
$("gpRepoBtn").onclick = async () => {
  const user = $("gpAccount").value;
  if (!user) return line("先に GitHub にログインする", "err");
  const base = mode === "tool" ? "overleaf_compiler"
    : dir.split("/").pop().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "latex-paper";
  const p = modal("上げる先のリポジトリ", `<div class="seg gpr-tabs" id="gprTabs">
        <button data-t="pick">もうあるリポジトリから選ぶ</button><button data-t="new">新しく作る</button></div>
      <div id="gprPick">
        <div class="gpr-cur">${st?.remote ? `今の送り先：<b>${escapeHtml(st.remote)}</b>` : "まだ送り先を決めていない"}</div>
        <input id="gprQ" placeholder="絞り込む" style="width:100%">
        <div id="gprList" class="ccrw" style="max-height:46vh"><div class="dim">読み込み中…</div></div>
      </div>
      <div id="gprNew">
        <div class="kbd" style="margin-bottom:6px">GitHub に新しいリポジトリを作り、送り先にする</div>
        <div class="gpr-name"><select id="gprOwner"></select><span>/</span><input id="gprName" value="${escapeHtml(base)}" placeholder="名前"></div>
        <div class="kbd" style="margin-top:4px">名前に使えるのは英数字と - _ .</div>
        <div class="gpr-vis">
          <label><input type="radio" name="gprVis" value="private" checked><div><b>🔒 非公開（Private）</b>
            <div class="kbd">自分と、招いた人だけが見られる。原稿はふつうこちら</div></div></label>
          <label><input type="radio" name="gprVis" value="public"><div><b>🌐 公開（Public）</b>
            <div class="kbd">インターネットの誰でも見られる</div></div></label>
        </div>
        <div class="gp-row"><span class="gp-grow"></span><button id="gprCreate" class="primary" style="flex:none">リポジトリを作る</button></div>
      </div>`,
    [{ label: "やめる", value: null }]);
  const tabTo = (t) => {
    repoTab = t;
    for (const b of $("gprTabs").querySelectorAll("button")) b.classList.toggle("on", b.dataset.t === t);
    $("gprPick").style.display = t === "pick" ? "" : "none";
    $("gprNew").style.display = t === "new" ? "" : "none";
    (t === "pick" ? $("gprQ") : $("gprName")).focus();
  };
  $("gprTabs").onclick = (e) => { const b = e.target.closest("button[data-t]"); if (b) tabTo(b.dataset.t); };
  tabTo(repoTab);
  let repos = [], chosen = null;
  const draw = () => {
    const q = $("gprQ").value.toLowerCase();
    $("gprList").innerHTML = repos.filter((r) => r.full_name.toLowerCase().includes(q)).map((r) => `<div class="it${r.full_name === st?.remote ? " now" : ""}" data-n="${escapeHtml(r.full_name)}">
        <div class="l">${escapeHtml(r.full_name)} <span class="badge${r.private ? "" : " warn"}">${r.private ? "非公開" : "公開"}</span>
          ${r.full_name === st?.remote ? '<span class="badge">今の送り先</span>' : ""}
          <button class="gear" data-set="${escapeHtml(r.full_name)}" title="設定（名前・公開範囲・ブランチ・削除）">⚙ 設定</button></div>
        <div class="dim">${escapeHtml(r.description || "")} ${r.updated_at ? "・" + ago(Date.parse(r.updated_at) / 1000) : ""}</div></div>`).join("") || '<div class="dim">リポジトリが無い</div>';
  };
  const close = () => document.querySelector("#mFoot button").click();
  api(`/api/gh/repos?user=${enc(user)}`).then((r) => { repos = r.repos; draw(); }).catch((e) => { $("gprList").innerHTML = `<div class="dim">${escapeHtml(e.message)}</div>`; });
  api(`/api/gh/owners?user=${enc(user)}`).then((r) => { $("gprOwner").innerHTML = r.owners.map((o) => `<option>${escapeHtml(o)}</option>`).join(""); }).catch(() => {
    $("gprOwner").innerHTML = `<option>${escapeHtml(user)}</option>`; });
  $("gprQ").oninput = draw;
  let settings = null, create = null;
  $("gprList").onclick = (e) => {
    const g = e.target.closest(".gear");
    if (g) { settings = g.dataset.set; close(); return; }
    const it = e.target.closest(".it"); if (it) { chosen = repos.find((r) => r.full_name === it.dataset.n); close(); }
  };
  $("gprCreate").onclick = () => {
    const name = $("gprName").value.trim();
    if (!name) return $("gprName").focus();
    create = { owner: $("gprOwner").value, name, private: document.querySelector('input[name="gprVis"]:checked').value === "private" };
    close();
  };
  await p;
  if (settings) { await repoSettings(user, settings); return $("gpRepoBtn").click(); }   // 設定を閉じたら一覧へ戻る
  if (create) {   // 窓を閉じてから作る（公開なら、もう一度確かめる）
    const full = `${create.owner}/${create.name}`;
    if (!create.private && !(await confirmBox("公開リポジトリを作る", `<b>${escapeHtml(full)}</b> を<b>公開</b>で作る。中身は誰でも見られるようになる。作る？`, "公開で作る", true))) return;
    try {
      const r = await post("/api/gh/create", { user, ...create });
      chosen = { full_name: r.full_name, private: r.private, default_branch: r.default_branch, created: true };
      showToast(`${escapeHtml(r.full_name)} を作った（${r.private ? "非公開" : "公開"}）`, "ok", 4000);
    } catch (e) { showToast(escapeHtml(e.message), "err", 6000); return; }
  }
  if (!chosen) return;
  if (!chosen.private && !chosen.created && !(await confirmBox("公開リポジトリ", `<b>${escapeHtml(chosen.full_name)}</b> は<b>公開</b>されている。中身が誰でも見られるようになる。送り先にする？`, "公開のまま使う", true))) return;
  let branch = chosen.default_branch || "main";
  try { const b = await api(`/api/gh/branches?user=${enc(user)}&repo=${enc(chosen.full_name)}`); branch = b.default || branch; } catch {}
  connect({ account: user, repo: chosen.full_name, branch, private: chosen.private });
};

// ---- ブランチ ----
async function renderBranches() {
  let local = [], current = "";
  try { const b = await gget("branches"); local = b.local; current = b.current; } catch {}
  const target = mode === "data" ? (st?.target || current) : current;
  const names = [...new Set([target, ...local].filter(Boolean))];
  $("gpBranch").innerHTML = names.map((n) => `<option ${n === target ? "selected" : ""}>${escapeHtml(n)}</option>`).join("");
}
$("gpBranch").onchange = async () => {
  try { await refresh(await gpost("checkout", { branch: $("gpBranch").value })); line(`「${$("gpBranch").value}」にした`, "ok"); }
  catch (e) { line(e.message, "err"); refresh(); }
};
$("gpNewBranch").onclick = async () => {
  const name = await ask("新しいブランチ", "名前（英数字と - _ . /）", "");
  if (!name) return;
  try { await refresh(await gpost("checkout", { branch: name, create: true })); line(`「${name}」を作って切り替えた`, "ok"); }
  catch (e) { line(e.message, "err"); }
};
$("gpFetch").onclick = () => busy($("gpFetch"), "確認中…", async () => {
  try { await refresh(await gpost("fetch")); line("GitHub の最新を確かめた", "ok"); } catch (e) { line(e.message, "err"); }
});
$("gpPull").onclick = () => busy($("gpPull"), "取り込み中…", async () => {
  try {
    const r = await gpost("pull"); await refresh(r); line(r.message, "ok");
    if (mode === "tool") showToast("最新版にした。新しいコードを使うには、アプリを閉じて開き直す", "ok", 7000);
  } catch (e) { line(e.message, "err"); }
});

// ---- 変わったファイルと差分 ----
const KIND = { M: "変更", A: "追加", D: "削除", R: "名前の変更", "?": "新しい" };
function renderFiles() {
  const files = st.files;
  $("gpCount").textContent = files.length ? `${files.length} 件` : "";
  $("gpFiles").innerHTML = files.map((f, i) => `<div class="gp-file${f.path === sel ? " sel" : ""}${f.forbidden ? " no" : ""}" data-i="${i}"
      title="${escapeHtml(f.forbidden ? "原稿（data/ の下）なので本体には入れられない" : f.path)}">
      <input type="checkbox" ${f.forbidden ? "disabled" : unchecked.has(f.path) ? "" : "checked"}>
      <span class="k k${escapeHtml(f.kind === "?" ? "N" : f.kind)}">${f.kind === "?" ? "U" : f.kind}</span>
      <span class="n">${escapeHtml(f.path.split("/").pop())}</span><span class="d">${escapeHtml(f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : "")}</span>
    </div>`).join("") || '<div class="empty">変更は無い</div>';
}
const chosen = () => st.files.filter((f) => !f.forbidden && !unchecked.has(f.path)).map((f) => f.path);
$("gpFiles").onclick = async (e) => {
  const row = e.target.closest(".gp-file"); if (!row) return;
  const f = st.files[+row.dataset.i];
  if (e.target.matches("input[type=checkbox]")) {
    e.target.checked ? unchecked.delete(f.path) : unchecked.add(f.path);
    $("gpAll").checked = !unchecked.size; return;
  }
  sel = f.path; renderFiles();
  $("gpDiffHead").textContent = `${f.path}（${KIND[f.kind] || f.kind}）`;
  try {
    const r = await gget("diff", { path: f.path });
    $("gpDiff").innerHTML = r.diff.split("\n").map((l) => {
      const c = l.startsWith("+") && !l.startsWith("+++") ? "ins" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : "";
      return `<span class="${c}">${escapeHtml(l) || " "}</span>`;
    }).join("\n") || "（中身の変更は無い）";
  } catch (er) { $("gpDiff").textContent = er.message; }
};
$("gpAll").onchange = () => {
  unchecked.clear();
  if (!$("gpAll").checked) st.files.forEach((f) => unchecked.add(f.path));
  renderFiles();
};

// ---- コミットメッセージの自動作成 ----
async function engines() {
  try {
    const r = await api("/api/git/engines");
    for (const o of $("gpEngine").options) { o.disabled = !r[o.value]; o.textContent = o.textContent.replace(/（入っていない）$/, "") + (r[o.value] ? "" : "（入っていない）"); }
    const saved = store.get("oc.gitEngine", "claude");
    $("gpEngine").value = r[saved] ? saved : r.claude ? "claude" : r.codex ? "codex" : saved;
  } catch {}
}
$("gpEngine").onchange = () => store.set("oc.gitEngine", $("gpEngine").value);
$("gpGen").onclick = () => busy($("gpGen"), "✨ 作成中…", async () => {
  const paths = chosen();
  if (!paths.length) return line("入れるファイルを選ぶ", "err");
  try { $("gpMsg").value = (await gpost("generate", { engine: $("gpEngine").value, paths })).message; line("コミットメッセージを作成した。直してからコミットできる", "ok"); }
  catch (e) { line(e.message, "err"); }
});

// ---- コミット・push ----
async function doCommit() {
  const paths = chosen(), message = $("gpMsg").value.trim();
  if (!paths.length) { line("入れるファイルを選ぶ", "err"); return false; }
  if (!message) { line("コミットメッセージを書く（✨ で自動でも作成できる）", "err"); return false; }
  let r = await gpost("commit", { paths, message });
  if (r.private) {   // 公開リポジトリに、個人名などが入りそう
    const html = `<div class="kbd" style="margin-bottom:8px">公開リポジトリに入る変更に、調べる言葉かメールアドレスが入っている。</div>
      <div class="gp-hits">${r.private.map((h) => `<div><b>${escapeHtml(h.path)}:${h.line}</b>　${escapeHtml(h.words.join("、"))}<br><code>${escapeHtml(h.text)}</code></div>`).join("")}</div>`;
    const go = await modal("個人情報などが入っている", html, [{ label: "やめる（直す）", value: false, cls: "primary" }, { label: "それでもコミットする", value: true, cls: "danger" }]);
    if (!go) { line("コミットをやめた。上の箇所を直してから、もう一度", "err"); return false; }
    r = await gpost("commit", { paths, message, force_private: true });
  }
  if (r.nothing) {   // 一覧が古かった（もうコミットしてある）。一覧を新しくして、送るものがあれば知らせる
    await refresh(r);
    line(r.ahead ? `その変更はもうコミットしてある（${r.last}）。⤒ push で GitHub へ送れる（${r.ahead} 件）` : "入れる変更は無い", r.ahead ? "ok" : "err");
    return r.ahead > 0;
  }
  $("gpMsg").value = ""; unchecked.clear(); $("gpAll").checked = true;
  await refresh(r);
  line(`コミットした: ${r.committed}`, "ok");
  return true;
}
async function doPush() {
  if (!st.remote_url) { line(mode === "tool" ? "先に送り先（自分の GitHub のリポジトリ）を選ぶ" : "先にリポジトリ（送り先）を選ぶ", "err"); return; }
  const o = await gget("outgoing", { branch: $("gpBranch").value || "" });
  if (!o.commits.length) { line("送るコミットは無い", "ok"); return; }
  const vis = o.private ? "非公開" : "公開";
  const html = `<table class="ccdata">${o.account ? `<tr><td>アカウント</td><td>${escapeHtml(o.account)}</td></tr>` : ""}
      <tr><td>送り先</td><td>${escapeHtml(o.remote_url)}（${vis}）</td></tr>
      <tr><td>ブランチ</td><td>${escapeHtml(o.branch)}${o.new_branch ? "（新しく作る）" : ""}</td></tr></table>
    <div style="margin:10px 0 4px">送るコミット（${o.commits.length} 件）</div>
    <pre class="gp-out">${o.commits.map(escapeHtml).join("\n")}</pre>
    <div class="kbd">${vis === "公開" ? "<b>公開</b>リポジトリなので、誰でも見られるようになる。" : ""}強制 push はしない</div>`;
  if (!(await confirmBox("GitHub へ push", html, "push する", vis === "公開"))) return;
  try { await refresh(await gpost("push", { branch: o.branch })); line(`${o.branch} に push した`, "ok"); }
  catch (e) { line(e.message, "err"); }
}
$("gpCommit").onclick = () => busy($("gpCommit"), "コミット中…", () => doCommit().catch(async (e) => { await refresh(); line(e.message, "err"); }));
$("gpPush").onclick = () => busy($("gpPush"), "push 中…", () => doPush().catch((e) => line(e.message, "err")));

// ---- 公開前に調べる言葉（リポジトリの外の設定に置く）----
$("gpPrivate").onclick = async () => {
  const r = await api("/api/git/private");
  const v = await modal("公開前に調べる言葉", `<div class="kbd">公開リポジトリにコミットする前に、入る変更（足した行）にこれらの言葉が無いか調べる（大文字小文字は区別しない）。
      メールアドレスも調べる。非公開の原稿のリポジトリでは調べない。設定は ${escapeHtml(r.where)} に置き、リポジトリには入らない。</div>
    <div style="margin-top:8px">調べる言葉（1行に1つ。名前・学籍番号・所属など）</div><textarea id="gpWords" rows="6" style="width:100%">${escapeHtml(r.words.join("\n"))}</textarea>
    <div style="margin-top:8px">出てきても良い書き方（1行に1つ。例：github.com/アカウント名）</div><textarea id="gpAllow" rows="3" style="width:100%">${escapeHtml(r.allow.join("\n"))}</textarea>`,
    [{ label: "やめる", value: null }, { label: "保存", value: "save", cls: "primary" }]);
  if (v !== "save") return;   // 窓を閉じても中身は残っているので、閉じたあとに読む
  try { await post("/api/git/private", { words: $("gpWords").value, allow: $("gpAllow").value }); line("調べる言葉を保存した", "ok"); }
  catch (e) { line(e.message, "err"); }
};

// ---- リポジトリの設定（名前・公開範囲・既定のブランチ・ブランチ・削除）----
// 小さな窓は1つずつしか出せないので、ボタンを押したら設定の窓を閉じ、確かめてから設定の窓を開き直す
async function repoSettings(user, full) {
  while (full) {
    let info;
    try { info = await api(`/api/gh/repo?user=${enc(user)}&repo=${enc(full)}`); } catch (e) { line(e.message, "err"); return; }
    let act = null;
    const admin = info.can_admin;
    const p = modal(`${full} の設定`, `<div class="gp-set">
      ${admin ? "" : '<div class="kbd" style="color:var(--warn)">このアカウントには、このリポジトリの管理の権限が無い（変えられない）</div>'}
      <h4>名前</h4><div class="gp-row"><code>${escapeHtml(full)}</code><span class="gp-grow"></span><button data-act="rename">名前を変える</button></div>
      <h4>公開範囲</h4><div class="gp-row"><span class="badge${info.private ? "" : " warn"}">${info.private ? "非公開" : "公開"}</span>
        <span class="gp-grow"></span><button data-act="vis">${info.private ? "公開にする" : "非公開にする"}</button></div>
      <h4>共同編集者</h4><div class="gp-row"><span class="kbd">一緒に直す人を GitHub のユーザー名で招待する</span><span class="gp-grow"></span>
        <button data-act="collab" class="primary">👥 共同編集者…</button></div>
      <h4>ブランチ</h4><div class="gp-branches">${info.branches.map((b) => `<div class="gp-row"><span>${escapeHtml(b)}</span>
          ${b === info.default_branch ? '<span class="badge">既定</span>' : ""}<span class="gp-grow"></span>
          ${b === info.default_branch ? "" : `<button data-act="default" data-b="${escapeHtml(b)}">既定にする</button>`}
          <button data-act="brename" data-b="${escapeHtml(b)}">名前を変える</button>
          ${b === info.default_branch ? "" : `<button data-act="bdel" data-b="${escapeHtml(b)}" class="danger">削除</button>`}</div>`).join("")
          || '<div class="kbd">まだブランチが無い（最初の push で作られる）</div>'}</div>
        <div class="gp-row"><span class="gp-grow"></span><button data-act="bnew"${info.branches.length ? "" : " disabled"}>＋ 新しいブランチ</button></div>
      <div class="gp-danger"><h4>危険な操作</h4><div class="gp-row"><div><b>このリポジトリを削除</b><div class="kbd">一度消すと元に戻せない。慎重に</div></div>
        <span class="gp-grow"></span><button data-act="delete" class="danger">このリポジトリを削除</button></div></div></div>`,
      [{ label: "閉じる", value: null }]);
    if (!admin) $("mBody").querySelectorAll("button[data-act]:not([data-act=collab])").forEach((b) => { b.disabled = true; });
    $("mBody").onclick = (e) => {
      const b = e.target.closest("button[data-act]");
      if (b && !b.disabled) { act = { k: b.dataset.act, b: b.dataset.b }; document.querySelector("#mFoot button").click(); }
    };
    await p;
    $("mBody").onclick = null;
    if (!act) return;
    try { full = await repoAct(user, full, info, act); }
    catch (e) { showToast(escapeHtml(e.message), "err", 7000); }
  }
}
const isMine = (full) => st?.remote === full;   // 今のフォルダ（本体）の送り先か
async function repoAct(user, full, info, { k, b }) {
  const owner = full.split("/")[0], name = full.split("/")[1];
  if (k === "collab") { await collabDialog(user, full, info.can_admin); return full; }
  if (k === "rename") {
    const nn = await ask("リポジトリの名前を変える", "新しい名前（英数字と - _ .）。古い URL からも、しばらくは GitHub が案内してくれる", name);
    if (!nn || nn === name) return full;
    const r = await post("/api/gh/update", { user, repo: full, name: nn });
    if (isMine(full)) await connect({ account: user, repo: r.full_name, branch: st.target, private: st.private });
    showToast(`${escapeHtml(r.full_name)} に名前を変えた`, "ok", 4000);
    return r.full_name;
  }
  if (k === "vis") {
    const toPublic = info.private;
    const ok = toPublic
      ? await typedConfirm("公開にする", `<b>${escapeHtml(full)}</b> を<b>公開</b>にすると、誰でも中身（原稿・履歴）を見られるようになる。`, full, "公開にする")
      : await confirmBox("非公開にする", `<b>${escapeHtml(full)}</b> を非公開にする？`, "非公開にする");
    if (!ok) return full;
    await post("/api/gh/update", { user, repo: full, private: !toPublic });
    if (isMine(full)) await connect({ account: user, repo: full, branch: st.target, private: !toPublic });
    showToast(toPublic ? "公開にした" : "非公開にした", "ok", 4000);
    return full;
  }
  if (k === "default") {
    if (!(await confirmBox("既定のブランチ", `既定のブランチを <b>${escapeHtml(b)}</b> にする？`, "既定にする"))) return full;
    await post("/api/gh/update", { user, repo: full, default_branch: b });
    return full;
  }
  if (k === "brename") {
    const nn = await ask("ブランチの名前を変える", `「${escapeHtml(b)}」の新しい名前（英数字と - _ . /）`, b);
    if (!nn || nn === b) return full;
    await post("/api/gh/branch_rename", { user, repo: full, branch: b, name: nn });
    if (isMine(full) && st.target === b) await connect({ account: user, repo: full, branch: nn, private: st.private });
    return full;
  }
  if (k === "bnew") {
    const nn = await ask("新しいブランチ", `名前（英数字と - _ . /）。既定のブランチ「${escapeHtml(info.default_branch)}」から作る`, "");
    if (!nn) return full;
    await post("/api/gh/branch_create", { user, repo: full, name: nn, from: info.default_branch });
    return full;
  }
  if (k === "bdel") {
    if (!(await confirmBox("ブランチを削除", `GitHub のブランチ <b>${escapeHtml(b)}</b> を削除する？<br><span class="kbd">そのブランチだけにあるコミットは見えなくなる</span>`, "削除する", true))) return full;
    await post("/api/gh/branch_delete", { user, repo: full, branch: b });
    return full;
  }
  if (k === "delete") {   // GitHub と同じく、2段階で確かめる
    const step1 = await modal("このリポジトリを削除", `<div class="gp-danger"><b>${escapeHtml(full)}</b> を削除しようとしている。<br><br>
        この操作は<b>取り消せない</b>。リポジトリの中身・履歴・Issue・設定がすべて完全に消える。<br>
        ほかの人と使っているリポジトリなら、その人たちも使えなくなる。</div>`,
      [{ label: "やめる", value: false }, { label: "このリポジトリを削除したい", value: true, cls: "danger" }]);
    if (!step1) return full;
    if (!(await typedConfirm("削除の確認", "確認のため、下の欄にリポジトリの名前を入れる。", full, "このリポジトリを削除する"))) return full;
    const del = () => post("/api/gh/delete", { user, repo: full, confirm: full });
    try { await del(); }
    catch (e) {
      if (!String(e.message).includes("NEED_DELETE_SCOPE")) throw e;
      // 削除には、GitHub の決まりで特別な権限（delete_repo）が要る。もう一度だけ許可してもらう
      const ok = await deviceFlow("/api/gh/refresh", { user, scopes: "delete_repo" }, "削除の権限を許可する",
        "リポジトリの削除には、GitHub の決まりで「削除の権限」が別に要る。もう一度コードを入れて許可すると、削除できるようになる。");
      if (!ok) return full;
      await del();
    }
    if (isMine(full)) await refresh(await gpost("disconnect"));
    showToast(`${escapeHtml(full)} を削除した`, "ok", 5000);
    return null;
  }
  return full;
}
// GitHub と同じ、名前を正確に打ち込んで確かめる窓
async function typedConfirm(title, html, expect, label) {
  const p = modal(title, `<div>${html}</div><div style="margin-top:10px">確認のため <b><code>${escapeHtml(expect)}</code></b> と入れる</div>
      <input id="gpTyped" autocomplete="off" spellcheck="false">`,
    [{ label: "やめる", value: null }, { label, value: "__input", cls: "danger" }]);
  const btn = [...$("mFoot").children].pop();   // 名前が一致するまで押せない（GitHub と同じ）
  btn.disabled = true;
  $("gpTyped").oninput = () => { btn.disabled = $("gpTyped").value.trim() !== expect; };
  const v = await p;
  if (v === null) return false;
  if (v !== expect) { showToast("名前が一致しないので、やめた", "err", 4000); return false; }
  return true;
}

// ---- 取り消し・途中で止まった操作をやめる ----
$("gpUndo").onclick = async () => {
  if (!st?.has_head || st.head_pushed) return;
  let c;
  try { c = await gget("last_commit"); } catch (e) { return line(e.message, "err"); }
  const html = `<div>直前のコミット <b>${escapeHtml(c.sha)}</b> と、そのときの git add を取り消す。<br>
      <b>ファイルの中身には触らない</b>。入れた変更は一覧（add する前の状態）に戻る。</div>
    <div style="margin:10px 0 4px">コミットしたメッセージ</div><pre class="gp-out">${escapeHtml(c.message)}</pre>
    <div style="margin:10px 0 4px">入っているファイル（${c.nfiles} 件）</div><pre class="gp-out">${escapeHtml(c.files.join("\n"))}</pre>
    <div class="kbd">メッセージは下の欄に戻すので、直してコミットし直せる</div>`;
  if (!(await confirmBox("コミットを取り消す", html, "取り消す"))) return;
  try {
    const r = await gpost("undo");
    $("gpMsg").value = r.undone;
    await refresh(r);
    line(`コミット ${c.sha} を取り消した。変更 ${r.files.length} 件を一覧に戻した（ファイルの中身はそのまま）`, "ok");
  } catch (e) { await refresh(); line(e.message, "err"); }
};
function renderOp() {
  const box = $("gpOp");
  if (!st?.op) { box.style.display = "none"; return; }
  box.style.display = "block";
  box.innerHTML = `<div><b>${escapeHtml(st.op.label)}の途中で止まっている</b>${st.conflicts.length ? `（コンフリクト ${st.conflicts.length} 件）` : ""}</div>
    ${st.conflicts.length ? `<div class="kbd">${st.conflicts.map(escapeHtml).join("、")}</div>` : ""}
    <div class="gp-row"><button id="gpAbort" class="danger">やめて元に戻す</button></div>`;
  $("gpAbort").onclick = async () => {
    if (!(await confirmBox("やめて元に戻す", `${escapeHtml(st.op.label)}をやめて、始める前の状態に戻す？<br><span class="kbd">途中で直した分も消える</span>`, "元に戻す", true))) return;
    try { const r = await gpost("abort"); await refresh(r); line(`${r.aborted}をやめて元に戻した`, "ok"); }
    catch (e) { line(e.message, "err"); }
  };
}

// 送り先のリポジトリの横の「👥 共同編集者」
$("gpCollab").onclick = async () => {
  const user = $("gpAccount").value;
  if (!st?.remote || !user) return;
  let admin = false;
  try { admin = (await api(`/api/gh/repo?user=${enc(user)}&repo=${enc(st.remote)}`)).can_admin; } catch (e) { return line(e.message, "err"); }
  collabDialog(user, st.remote, admin);
};
// ---- 共同編集者（招待する・招待中・参加している人・外す）----
// 窓の中で操作が完結する（窓を閉じずに一覧を描き直す）
async function collabDialog(user, full, admin) {
  const p = modal(`${full} の共同編集者`, `<div class="gp-collab">
      ${admin ? `<div class="kbd">相手の GitHub のユーザー名で招待する。相手は overleaf-compiler の一覧の「⤓ GitHub から取り込む」で参加して取り込める
        （GitHub からのメールや通知からでも参加できる）。非公開のリポジトリは、招待された人しか見られない</div>
      <div class="gp-row" style="margin-top:8px"><input id="gcQ" placeholder="GitHub のユーザー名" autocomplete="off" spellcheck="false" style="flex:1">
        <select id="gcPerm"><option value="push">編集できる</option><option value="pull">見るだけ</option></select>
        <button id="gcInvite" class="primary" style="flex:none">招待する</button></div>
      <div id="gcFound" class="gc-found"></div>`
      : '<div class="kbd" style="color:var(--warn)">このアカウントには管理の権限が無いので、見るだけ（招待はリポジトリの持ち主がする）</div>'}
      <h4>参加している人</h4><div id="gcPeople" class="gc-list"><div class="dim">読み込み中…</div></div>
      <h4>招待中（まだ参加していない）</h4><div id="gcInvites" class="gc-list"></div>
      <div class="gp-row" style="margin-top:10px"><span class="kbd">アプリを使わない人には、GitHub の招待のページを送る</span><span class="gp-grow"></span>
        <button id="gcCopy" style="flex:none">招待のページの URL をコピー</button></div></div>`,
    [{ label: "閉じる", value: null }]);
  let data = null;
  const av = (u) => u.avatar ? `<img src="${escapeHtml(u.avatar)}&s=40" alt="">` : "";
  const draw = () => {
    $("gcPeople").innerHTML = data.people.map((u) => `<div class="gc-it">${av(u)}<b>${escapeHtml(u.login)}</b>
        <span class="badge">${u.admin ? "持ち主・管理" : u.perm}</span><span class="gp-grow"></span>
        ${admin && !u.admin && u.login !== user ? `<button data-rm="${escapeHtml(u.login)}" class="danger">外す</button>` : ""}</div>`).join("") || '<div class="dim">いない</div>';
    $("gcInvites").innerHTML = data.invites.map((i) => `<div class="gc-it">${av(i)}<b>${escapeHtml(i.login)}</b>
        <span class="badge warn">${i.perm}・招待中</span><span class="dim">${i.created ? ago(Date.parse(i.created) / 1000) : ""}</span><span class="gp-grow"></span>
        ${admin ? `<button data-cancel="${i.id}">招待を取り消す</button>` : ""}</div>`).join("") || '<div class="dim">いない</div>';
  };
  const load = async (r) => { try { data = r || await api(`/api/gh/collaborators?user=${enc(user)}&repo=${enc(full)}`); draw(); } catch (e) { $("gcPeople").innerHTML = `<div class="dim">${escapeHtml(e.message)}</div>`; } };
  load();
  $("gcCopy").onclick = () => navigator.clipboard.writeText(`https://github.com/${full}/invitations`).then(() => showToast("コピーした", "ok", 1500));
  if (admin) {
    let timer = null;
    $("gcQ").oninput = () => {   // 名前で探して、候補から選べる
      clearTimeout(timer);
      const q = $("gcQ").value.trim();
      if (q.length < 2) { $("gcFound").innerHTML = ""; return; }
      timer = setTimeout(async () => {
        try {
          const r = await api(`/api/gh/users?user=${enc(user)}&q=${enc(q)}`);
          $("gcFound").innerHTML = r.users.map((u) => `<div class="gc-it pick" data-login="${escapeHtml(u.login)}">${av(u)}<b>${escapeHtml(u.login)}</b> <span class="dim">${escapeHtml(u.name)}</span></div>`).join("");
        } catch {}
      }, 350);
    };
    $("gcFound").onclick = (e) => { const it = e.target.closest("[data-login]"); if (it) { $("gcQ").value = it.dataset.login; $("gcFound").innerHTML = ""; } };
    $("gcInvite").onclick = async () => {
      const login = $("gcQ").value.trim().replace(/^@/, "");
      if (!login) return $("gcQ").focus();
      $("gcInvite").disabled = true;
      try { await load(await post("/api/gh/invite", { user, repo: full, login, perm: $("gcPerm").value })); $("gcQ").value = ""; $("gcFound").innerHTML = "";
            showToast(`${escapeHtml(login)} を招待した`, "ok", 3000); }
      catch (e) { showToast(escapeHtml(e.message), "err", 6000); }
      finally { $("gcInvite").disabled = false; }
    };
  }
  $("mBody").onclick = async (e) => {
    const b = e.target.closest("button[data-rm], button[data-cancel]"); if (!b) return;
    if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "本当に？ もう一度押す"; return; }   // 窓を重ねられないので、2回押して確かめる
    b.disabled = true;
    try { await load(await post("/api/gh/uninvite", { user, repo: full, login: b.dataset.rm || "", invite_id: b.dataset.cancel || "" })); }
    catch (er) { showToast(escapeHtml(er.message), "err", 6000); b.disabled = false; }
  };
  await p;
  $("mBody").onclick = null;
}
