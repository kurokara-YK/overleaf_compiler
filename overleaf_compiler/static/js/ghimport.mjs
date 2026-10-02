// 一覧の「⤓ GitHub から取り込む」。共同編集者として招待されたリポジトリに参加し、data の今のフォルダに取り込む（clone）。
// 取り込んだフォルダは、送り先（アカウント・リポジトリ・ブランチ）が決まった状態になるので、すぐ Git の画面で push できる
import { $, api, post, enc, escapeHtml, modal, showToast, ago } from "./util.mjs";
import { deviceFlow } from "./gitpage.mjs";
import { browseDir, refresh } from "./home.mjs";

async function accounts() {
  const r = await api("/api/gh/accounts");
  return { gh: r.gh, list: r.accounts.map((a) => a.login), active: r.accounts.find((a) => a.active)?.login };
}
// 届いている招待の数を、ボタンの横に出す
export async function inviteBadge() {
  const b = $("ghInvBadge");
  try {
    const a = await accounts();
    let n = 0;
    for (const u of a.list) n += (await api(`/api/gh/invitations?user=${enc(u)}`)).invites.length;
    b.textContent = n ? `招待 ${n}` : ""; b.hidden = !n;
  } catch { b.hidden = true; }
}

$("ghCloneBtn").onclick = async () => {
  let a;
  try { a = await accounts(); } catch (e) { return showToast(escapeHtml(e.message), "err", 5000); }
  if (!a.gh) {
    try { showToast("gh（GitHub CLI）を入れている…", "", 0); await post("/api/gh/install"); a = await accounts(); showToast("gh を入れた", "ok", 2000); }
    catch (e) { return showToast(escapeHtml(e.message), "err", 6000); }
  }
  if (!a.list.length) {   // まだ GitHub と連携していない
    if (!(await deviceFlow("/api/gh/login", {}, "GitHub にログイン", "取り込むには、自分の GitHub のアカウントでログインする（アプリを閉じても覚えている）"))) return;
    a = await accounts();
    if (!a.list.length) return;
  }
  openDialog(a);
};

async function openDialog(a) {
  const where = browseDir();
  let user = a.active || a.list[0], repos = [], invites = [], done = null;
  const p = modal("GitHub から取り込む", `<div class="gi">
      <div class="gp-row"><span class="gp-lab">アカウント</span><select id="giUser">${a.list.map((u) => `<option ${u === user ? "selected" : ""}>${escapeHtml(u)}</option>`).join("")}</select>
        <span class="gp-grow"></span><span class="kbd">取り込む先：data/${escapeHtml(where ? where + "/" : "")}</span></div>
      <h4>届いている招待</h4><div id="giInv" class="gc-list"><div class="dim">読み込み中…</div></div>
      <h4>取り込めるリポジトリ</h4>
      <input id="giQ" placeholder="絞り込む" style="width:100%" autocomplete="off">
      <div id="giRepos" class="ccrw" style="max-height:34vh"><div class="dim">読み込み中…</div></div></div>`,
    [{ label: "閉じる", value: null }]);
  const close = () => document.querySelector("#mFoot button").click();
  const drawInv = () => {
    $("giInv").innerHTML = invites.map((i) => `<div class="gc-it"><div style="flex:1;min-width:0"><b>${escapeHtml(i.repo)}</b>
        <span class="badge${i.private ? "" : " warn"}">${i.private ? "非公開" : "公開"}</span>
        <div class="dim">${escapeHtml(i.from)} さんから・${i.created ? ago(Date.parse(i.created) / 1000) : ""} ${escapeHtml(i.description)}</div></div>
        <button data-accept="${i.id}" data-repo="${escapeHtml(i.repo)}" class="primary">参加して取り込む</button>
        <button data-decline="${i.id}">断る</button></div>`).join("") || '<div class="dim">招待は届いていない（招待してもらうときは、自分の GitHub のユーザー名を伝える：<b>' + escapeHtml(user) + "</b>）</div>";
  };
  const drawRepos = () => {
    const q = $("giQ").value.toLowerCase();
    $("giRepos").innerHTML = repos.filter((r) => r.full_name.toLowerCase().includes(q)).map((r) => `<div class="it" data-n="${escapeHtml(r.full_name)}">
        <div class="l">${escapeHtml(r.full_name)} <span class="badge${r.private ? "" : " warn"}">${r.private ? "非公開" : "公開"}</span>
          ${r.full_name.split("/")[0] !== user ? '<span class="badge">共同編集</span>' : ""}</div>
        <div class="dim">${escapeHtml(r.description || "")} ${r.updated_at ? "・" + ago(Date.parse(r.updated_at) / 1000) : ""}</div></div>`).join("")
      || '<div class="dim">リポジトリが無い</div>';
  };
  const load = async () => {
    api(`/api/gh/invitations?user=${enc(user)}`).then((r) => { invites = r.invites; drawInv(); }).catch((e) => { $("giInv").innerHTML = `<div class="dim">${escapeHtml(e.message)}</div>`; });
    api(`/api/gh/repos?user=${enc(user)}`).then((r) => { repos = r.repos; drawRepos(); }).catch((e) => { $("giRepos").innerHTML = `<div class="dim">${escapeHtml(e.message)}</div>`; });
  };
  load();
  $("giUser").onchange = () => { user = $("giUser").value; load(); };
  $("giQ").oninput = drawRepos;
  $("giRepos").onclick = (e) => { const it = e.target.closest(".it"); if (it) { done = { repo: it.dataset.n }; close(); } };
  $("giInv").onclick = async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    b.disabled = true;
    try {
      if (b.dataset.accept) { await post("/api/gh/answer", { user, id: b.dataset.accept, accept: true }); done = { repo: b.dataset.repo }; close(); }
      else if (b.dataset.decline) { invites = (await post("/api/gh/answer", { user, id: b.dataset.decline, accept: false })).invites; drawInv(); }
    } catch (er) { showToast(escapeHtml(er.message), "err", 6000); b.disabled = false; }
  };
  await p;
  inviteBadge();
  if (!done) return;
  // 取り込むフォルダの名前を決めて clone する
  const name = await modal("取り込む", `<div><b>${escapeHtml(done.repo)}</b> を data/${escapeHtml(where ? where + "/" : "")} に取り込む</div>
      <div style="margin-top:8px">フォルダの名前</div><input value="${escapeHtml(done.repo.split("/")[1])}">`,
    [{ label: "やめる", value: null }, { label: "取り込む", value: "__input", cls: "primary" }]);
  if (!name) return;
  showToast(`${escapeHtml(done.repo)} を取り込んでいる…`, "", 0);
  try {
    const r = await post("/api/git/clone", { account: user, repo: done.repo, parent: where, name });
    await refresh();
    showToast(`data/${escapeHtml(r.dir)} に取り込んだ${r.empty ? "（まだ中身が無いリポジトリ）" : ""}。直したら ⎇ Git からコミットと push をする`, "ok", 7000);
  } catch (e) { showToast(escapeHtml(e.message), "err", 8000); }
}

inviteBadge();
