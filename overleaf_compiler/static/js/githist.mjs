// Git の画面の「編集履歴」。左にブランチのコミットを push ごとに（今回・前回・前々回…）、中央にその版の PDF、
// 右に変わったところの一覧。PDF の上では、変わった文字に赤い下線、変わった行の左の余白に赤い線を引く。
// サーバ側は gitview.py。PDF の上の場所は、変わった行を地の文にした切れ端（frags）を PDF の文字から探して決める
import { $, api, post, enc, escapeHtml, ago, store, url, showToast, fail } from "./util.mjs";
import { pdfjs, PDFJS_OPTS } from "./pdf.mjs";

const EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904";
const WT = "WORKTREE";        // 作業中（まだコミットしていない今のファイル）
let P = null;                 // { mode, dir }
let lg = null;                // /api/git/log
let sel = null;               // { to, from, label }
let kind = "pdf";               // pdf か text。本体はコードなので、既定は text
let mainTex = "";
let changes = [], cur = -1, token = 0;
const KIND = { add: "追加", chg: "書き換え", del: "削除" };

const qs = (extra = {}) => "?" + new URLSearchParams({ ...P, ...extra }).toString();
const gget = (name, extra) => api(`/api/git/${name}${qs(extra)}`);
const msg = (html) => { $("ghMsg").innerHTML = html; $("ghMsg").style.display = html ? "block" : "none"; };

// Git の画面から呼ぶ。p はどのリポジトリか。repo が無ければ案内だけ
export async function showHist(p, isRepo) {
  const same = P && P.mode === p.mode && P.dir === p.dir;
  P = { mode: p.mode, dir: p.dir };
  kind = store.get(`oc.ghMode.${P.mode}`, P.mode === "tool" ? "text" : "pdf");
  if (!same) lg = null;
  if (!isRepo) {
    $("ghRef").innerHTML = ""; $("ghList").innerHTML = '<div class="empty">まだ Git で管理していない（「変更とコミット」から始める）</div>';
    clearView(); msg("履歴はまだ無い"); return;
  }
  await loadRefs(same);
}

async function loadRefs(keep) {
  const was = keep ? $("ghRef").value : "", wasSel = keep && sel ? sel : null;
  let r;
  try { r = await gget("refs"); } catch (e) { $("ghList").innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`; return; }
  const opt = (b, label) => `<option value="${escapeHtml(b)}">${escapeHtml(label)}</option>`;
  $("ghRef").innerHTML = (r.local.length ? `<optgroup label="このパソコン">${r.local.map((b) => opt(b, b)).join("")}</optgroup>` : "")
    + (r.remote.length ? `<optgroup label="GitHub（${escapeHtml(r.remote_name)}）">${r.remote.map((b) => opt(b, `${b}（GitHub）`)).join("")}</optgroup>` : "");
  $("ghRef").value = r.current || r.local[0] || r.remote[0] || "";
  if (was && [...$("ghRef").options].some((o) => o.value === was)) $("ghRef").value = was;
  await loadLog(wasSel);
}
$("ghRef").onchange = () => loadLog();

function groupLabel(g, nth) {
  if (g.kind === "unsent") return "まだ送っていない";
  if (g.kind === "push") return nth === 0 ? "今回の push" : nth === 1 ? "前回の push" : nth === 2 ? "前々回の push" : `${nth} 回前の push`;
  if (g.kind === "fetch") return "GitHub から取り込んだ";
  if (g.kind === "older") return "それより前";
  return "GitHub にある";
}
async function loadLog(keepSel) {
  try { lg = await gget("log", { ref: $("ghRef").value }); }
  catch (e) { $("ghList").innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`; return; }
  if (!lg.commits.length) { $("ghList").innerHTML = '<div class="empty">まだコミットが無い</div>'; clearView(); msg("コミットするとここに出る"); return; }
  const by = Object.fromEntries(lg.commits.map((c) => [c.sha, c]));
  let nth = 0, html = lg.dirty ? `<div class="ghg wt" data-wt="1"><div class="t">作業中（まだコミットしていない）</div>
      <div class="dim">今のファイル。押すと、最後のコミットからの変更を見る（比べる相手を変えると、前回の push などと比べられる）</div></div>` : "";
  lg.groups.forEach((g, gi) => {
    const label = groupLabel(g, nth);
    if (g.kind === "push") nth++;
    g.label = label;
    const when = g.time ? new Date(g.time * 1000).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
    html += `<div class="ghg" data-g="${gi}"><div class="t">${escapeHtml(label)}<span class="gp-grow"></span><span class="dim">${when}</span></div>
      <div class="dim">${g.commits.length} 件のコミット・押すとまとめて見る</div></div>`;
    for (const s of g.commits) {
      const c = by[s];
      html += `<div class="ghc${c.pushed ? "" : " unsent"}" data-s="${c.sha}" title="${escapeHtml(c.subject)}\n${c.sha}">
        <div class="t"><span class="ico">${c.pushed ? "☁" : "⬆"}</span><span class="s">${escapeHtml(c.subject)}</span></div>
        <div class="dim">${escapeHtml(c.short)}・${escapeHtml(c.author)}・${ago(c.time)}・<span class="pa">+${c.add}</span> <span class="pd">−${c.del}</span>・${c.nfiles} ファイル</div></div>`;
    }
  });
  $("ghList").innerHTML = html;
  // 開き直したとき（コミットした後など）は、同じものを見続ける。版が変わっていなければ PDF も描き直さない
  if (keepSel && lg.commits.some((c) => c.sha === keepSel.to)) {
    const gi = lg.groups.findIndex((g) => g.commits[0] === keepSel.to && parentOf(g.commits.at(-1)) === keepSel.from);
    mark(gi >= 0 ? `.ghg[data-g="${gi}"]` : `.ghc[data-s="${keepSel.to}"]`);
    return;
  }
  const first = lg.groups.findIndex((g) => g.kind === "push");
  pickGroup(first >= 0 ? first : 0);
}
$("ghList").onclick = (e) => {
  const g = e.target.closest(".ghg");
  if (g && g.dataset.wt) { mark(".ghg.wt"); return select({ to: WT, from: lg.commits[0]?.sha || EMPTY_TREE, label: "作業中（まだコミットしていない）" }); }
  if (g) return pickGroup(+g.dataset.g);
  const c = e.target.closest(".ghc"); if (c) pickCommit(c.dataset.s);
};
const parentOf = (sha) => lg.commits.find((c) => c.sha === sha)?.parent || EMPTY_TREE;
function pickGroup(gi) {
  const g = lg.groups[gi]; if (!g) return;
  mark(`.ghg[data-g="${gi}"]`);
  select({ to: g.commits[0], from: parentOf(g.commits[g.commits.length - 1]), label: `${g.label}（${g.commits.length} 件）` });
}
function pickCommit(sha) {
  const c = lg.commits.find((x) => x.sha === sha);
  mark(`.ghc[data-s="${sha}"]`);
  select({ to: sha, from: parentOf(sha), label: c.subject });
}
function mark(q) { $("ghList").querySelectorAll(".on").forEach((x) => x.classList.remove("on")); $("ghList").querySelector(q)?.classList.add("on"); }

function select(s) {
  sel = s;
  // 比べる相手：選んだ版より前のコミット
  const i = lg.commits.findIndex((c) => c.sha === s.to);
  const older = lg.commits.slice(i + 1);
  $("ghFrom").innerHTML = older.map((c) => `<option value="${c.sha}">${escapeHtml(c.short)} ${escapeHtml(c.subject.slice(0, 40))}${c.sha === s.from ? "（1つ前）" : ""}</option>`).join("")
    + `<option value="${EMPTY_TREE}">何も無い状態（全部を新しいものとして見る）</option>`;
  $("ghFrom").value = s.from;
  show();
}
$("ghFrom").onchange = () => { sel.from = $("ghFrom").value; show(); };
$("ghMode").onclick = (e) => {
  const b = e.target.closest("button[data-k]"); if (!b) return;
  kind = b.dataset.k; store.set(`oc.ghMode.${P.mode}`, kind); show();
};
$("ghTex").onchange = () => { mainTex = $("ghTex").value; show(); };

function clearView() { $("ghPages").replaceChildren(); $("ghText").textContent = ""; $("ghChanges").innerHTML = ""; $("ghCount").textContent = ""; $("ghWhat").textContent = ""; changes = []; cur = -1; }

async function show() {
  const my = ++token;
  for (const b of $("ghMode").querySelectorAll("button")) b.classList.toggle("on", b.dataset.k === kind);
  $("ghHist").dataset.k = kind;
  const short = (s) => s === EMPTY_TREE ? "（空）" : s === WT ? "作業中" : s.slice(0, 7);
  $("ghWhat").innerHTML = `<b>${escapeHtml(sel.label)}</b>　<span class="dim">${short(sel.from)} → ${short(sel.to)}</span>`;
  $("ghPages").replaceChildren(); $("ghChanges").innerHTML = ""; $("ghCount").textContent = ""; changes = []; cur = -1; drawn = [];
  $("ghExport").disabled = true;
  if (kind === "text") return showText(my);
  msg("この版の PDF を用意している…");
  let b;
  try {
    for (;;) {   // 初めての版は裏で組む。組み終わるまで1秒ごとに見る
      b = await post("/api/git/build", { ...P, to: sel.to, main: mainTex });
      if (my !== token) return;
      if (b.state !== "building") break;
      msg("この版の PDF を組んでいる…（その版で1回だけ。次からはすぐ出る）");
      await new Promise((r) => setTimeout(r, 1000));
    }
  } catch (e) { if (my === token) msg(escapeHtml(e.message)); return; }
  $("ghTexWrap").style.display = b.mains && b.mains.length > 1 ? "" : "none";
  $("ghTex").innerHTML = (b.mains || []).map((m) => `<option ${m === b.main ? "selected" : ""}>${escapeHtml(m)}</option>`).join("");
  if (b.state === "none") { msg("この版には LaTeX の原稿（\\documentclass のある .tex）が無い。「文字」で違いを見る"); return showSide(my, null); }
  if (b.state === "error") { msg(`この版は組めなかった。「文字」で違いを見る<pre class="gp-out">${escapeHtml(b.error)}</pre>`); return; }
  mainTex = b.main;
  let m;
  try {
    [m] = await Promise.all([gget("marks", { from: sel.from, to: sel.to, main: b.main }), renderPdf(my, b)]);
  } catch (e) { if (my === token) msg(escapeHtml(e.message)); return; }
  if (my !== token) return;
  msg(b.error ? `<span class="dim">${escapeHtml(b.error)}</span>` : "");
  changes = m.changes;
  paint();
  showSide(my, m);
  $("ghExport").disabled = !changes.some((h) => h.located);
}

// ---- その版の PDF ----
let pages = [];   // { div, vp, idx: { s, map, items } }
let drawn = [];   // 描いた印（画面の px）。赤線つき PDF に焼き込むのに使う
async function renderPdf(my, b) {
  const url = `/api/gitpdf${qs({ to: sel.to, main: b.main })}`;
  const doc = await pdfjs.getDocument({ url, ...PDFJS_OPTS }).promise;
  const box = $("ghPdf"), dpr = window.devicePixelRatio || 1;
  const first = (await doc.getPage(1)).getViewport({ scale: 1 });
  const scale = Math.min(2.2, Math.max(0.4, (box.clientWidth - 48) / first.width));
  const out = [], jobs = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const vp = page.getViewport({ scale }), vpx = page.getViewport({ scale: scale * dpr });
    const div = document.createElement("div");
    div.className = "ghpage"; div.style.width = `${vp.width}px`; div.style.height = `${vp.height}px`;
    const c = document.createElement("canvas");
    c.width = Math.floor(vpx.width); c.height = Math.floor(vpx.height);
    div.append(c);
    jobs.push(page.render({ canvas: c, canvasContext: c.getContext("2d"), viewport: vpx }).promise);
    const tc = await page.getTextContent();
    out.push({ div, vp, idx: indexText(tc.items) });
  }
  await Promise.all(jobs);
  if (my !== token) return;
  pages = out;
  $("ghPages").replaceChildren(...out.map((p) => p.div));
}

// ページの文字を、空白を除き NFKC で揃えた1本の文字列にする。map は各文字が元のどの item の何文字目か
function indexText(items) {
  let s = ""; const map = [];
  items.forEach((it, ii) => {
    const str = it.str || "";
    for (let k = 0; k < str.length; k++) {
      if (it.hasEOL && k === str.length - 1 && str[k] === "-") continue;   // 行末のハイフン
      for (const ch of str[k].normalize("NFKC").replace(/\s+/g, "")) { s += ch; map.push([ii, k]); }
    }
  });
  return { s, map, items };
}
// 切れ端の文字列を同じように揃える。cmap は揃えた文字が元の何文字目か
function squeeze(t) {
  let s = ""; const cmap = [];
  [...t].forEach((ch, i) => { for (const c of ch.normalize("NFKC").replace(/\s+/g, "")) { s += c; cmap.push(i); } });
  return { s, cmap };
}
const topOf = (pi, si) => { const p = pages[pi], it = p.idx.items[p.idx.map[si][0]]; return p.vp.height / p.vp.scale - it.transform[5]; };
// cs を PDF の中から探す。hint（ページと高さ）に一番近いもの。見つからなければ半分ずつに分けて探す
function locate(cs, off, hint, out) {
  if (cs.length < 3) return;
  let best = null;
  pages.forEach((p, pi) => {
    for (let at = p.idx.s.indexOf(cs); at >= 0; at = p.idx.s.indexOf(cs, at + 1)) {
      const score = hint ? Math.abs(pi + 1 - hint.page) * 1e5 + Math.abs(topOf(pi, at) - hint.y) : pi * 1e5 + at / 1e3;
      if (!best || score < best.score) best = { pi, at, score };
    }
  });
  if (best) { out.push({ pi: best.pi, at: best.at, len: cs.length, off }); return; }
  if (cs.length < 8) return;
  const mid = Math.floor(cs.length / 2);
  locate(cs.slice(0, mid), off, hint, out);
  locate(cs.slice(mid), off + mid, hint, out);
}
// ページの中の文字 [a, b) の矩形（画面の px）。item ごとに1つ
function rects(pi, a, b) {
  const p = pages[pi], res = [];
  let run = null;
  const flush = () => {
    if (!run) return;
    const it = p.idx.items[run.ii], t = it.transform, n = Math.max(1, it.str.length);
    const h = it.height || Math.hypot(t[2], t[3]) || 10;
    const x1 = t[4] + it.width * run.k1 / n, x2 = t[4] + it.width * (run.k2 + 1) / n;
    const [X1, Y1] = p.vp.convertToViewportPoint(x1, t[5] - h * 0.2), [X2, Y2] = p.vp.convertToViewportPoint(x2, t[5] + h * 0.85);
    res.push({ x: Math.min(X1, X2), y: Math.min(Y1, Y2), w: Math.abs(X2 - X1), h: Math.abs(Y2 - Y1) });
    run = null;
  };
  for (let i = a; i < b; i++) {
    const [ii, k] = p.idx.map[i];
    if (run && run.ii === ii && k === run.k2 + 1) { run.k2 = k; continue; }
    flush(); run = { ii, k1: k, k2: k };
  }
  flush();
  return res;
}
function box(pi, r, cls, ci, title) {
  drawn.push({ pi, ...r, cls, ci });
  const d = document.createElement("div");
  d.className = cls; d.dataset.c = ci;
  Object.assign(d.style, { left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
  if (title) d.title = title;
  pages[pi].div.append(d);
  return d;
}

// 変わったところを PDF の上に描く
function paint() {
  changes.forEach((h, ci) => {
    h.at = [];   // 描いた場所（ページ・上端）。一覧から飛ぶのに使う
    const title = `${h.file}:${h.line}（${KIND[h.kind]}）` + (h.old.length ? `\n前: ${h.old.join("\n")}` : "") + (h.new.length ? `\n後: ${h.new.join("\n")}` : "");
    const spans = {};   // ページごとの縦の範囲（左の余白の線）
    const add = (pi, r) => { const s = spans[pi] ||= { y1: r.y, y2: r.y + r.h }; s.y1 = Math.min(s.y1, r.y); s.y2 = Math.max(s.y2, r.y + r.h); };
    if (h.kind === "del") {   // 消した場所：手前の行の終わりに印
      const found = [];
      const last = (h.ctx || []).at(-1);
      if (last) { const q = squeeze(last); locate(q.s, 0, h.hint, found); }
      const f = found.at(-1);
      if (f) {
        const r = rects(f.pi, f.at + f.len - 1, f.at + f.len).at(-1);
        if (r) { const c = { x: r.x + r.w, y: r.y, w: 3, h: r.h }; box(f.pi, c, "ghcut", ci, title); add(f.pi, c); }
      } else if (h.hint) {
        const pi = h.hint.page - 1, sc = pages[pi]?.vp.scale;
        if (sc) add(pi, { x: 0, y: h.hint.y * sc, w: 0, h: 12 * sc });
      }
    }
    for (const fr of h.frags || []) {
      const q = squeeze(fr.t), found = [];
      locate(q.s, 0, h.hint, found);
      for (const f of found) {
        // 揃えた文字ごとに、変わった文字かどうか
        const isChg = (j) => { const o = q.cmap[f.off + j]; return fr.chg.some(([a, b]) => o >= a && o < b); };
        let j = 0;
        while (j < f.len) {
          const c = isChg(j); let k = j;
          while (k < f.len && isChg(k) === c) k++;
          for (const r of rects(f.pi, f.at + j, f.at + k)) { box(f.pi, r, c ? "ghx" : "ghu", ci, title); add(f.pi, r); }
          j = k;
        }
        for (const cut of fr.cut) {   // 書き換えで文字が消えた位置
          const j2 = q.cmap.findIndex((o) => o >= cut) - f.off;
          if (j2 >= 0 && j2 < f.len) { const r = rects(f.pi, f.at + j2, f.at + j2 + 1)[0]; if (r) box(f.pi, { x: r.x - 1.5, y: r.y, w: 3, h: r.h }, "ghcut", ci, title); }
        }
      }
    }
    for (const [pi, s] of Object.entries(spans)) {
      const pad = 2;
      box(+pi, { x: 10, y: s.y1 - pad, w: 4, h: s.y2 - s.y1 + pad * 2 }, `ghbar ${h.kind}`, ci, title);
      const n = box(+pi, { x: 16, y: s.y1 - pad, w: 22, h: 12 }, "ghnum", ci, title);   // 一覧と同じ番号
      n.textContent = h.no = ci + 1;
      h.at.push({ pi: +pi, y: s.y1 });
    }
    h.located = h.at.length > 0;
  });
  $("ghPages").onclick = (e) => { const d = e.target.closest("[data-c]"); if (d) go(+d.dataset.c, false); };
}

// ---- 右の一覧 ----
function fragHtml(fr) {
  let out = "", i = 0;
  const t = fr.t;
  const pts = [...fr.chg].sort((a, b) => a[0] - b[0]);
  for (const [a, b] of pts) { out += escapeHtml(t.slice(i, a)) + `<mark>${escapeHtml(t.slice(a, b))}</mark>`; i = b; }
  return out + escapeHtml(t.slice(i));
}
async function showSide(my, m) {
  if (!m) {
    try { m = { changes: (await gget("marks", { from: sel.from, to: sel.to, main: mainTex })).changes }; } catch { m = { changes: [] }; }
    if (my !== token) return;
    changes = m.changes;
  }
  const located = changes.filter((h) => h.located).length;
  $("ghCount").textContent = changes.length ? `${changes.length} か所` : "";
  $("ghChanges").innerHTML = changes.map((h, ci) => `<div class="ghx-it${h.located ? "" : " lost"}" data-c="${ci}">
      <div class="h"><span class="no">${ci + 1}</span><span class="k ${h.kind}">${KIND[h.kind]}</span><span class="f">${escapeHtml(h.file)}:${h.line}</span>
        ${h.located ? "" : '<span class="dim">PDF の上では場所が分からない</span>'}</div>
      ${h.old.length ? `<div class="old">${h.old.map(escapeHtml).join("<br>")}</div>` : ""}
      ${(h.frags || []).length ? `<div class="new">${h.frags.map(fragHtml).join(" … ")}</div>`
        : h.new.length ? `<div class="new raw">${h.new.map(escapeHtml).join("<br>")}</div>` : ""}</div>`).join("")
    || `<div class="empty">.tex の変更は無い${kind === "pdf" ? "（画像などの変更は「文字」で見る）" : ""}</div>`;
  if (kind === "pdf" && changes.length && !located) msg("変わったところを PDF の上で見つけられなかった（右の一覧で中身を見る）");
}
$("ghChanges").onclick = (e) => { const it = e.target.closest(".ghx-it"); if (it) go(+it.dataset.c, true); };
function go(ci, scroll) {
  if (!changes.length) return;
  cur = (ci + changes.length) % changes.length;
  $("ghChanges").querySelectorAll(".ghx-it").forEach((x) => x.classList.toggle("on", +x.dataset.c === cur));
  $("ghChanges").querySelector(`.ghx-it[data-c="${cur}"]`)?.scrollIntoView({ block: "nearest" });
  document.querySelectorAll("#ghPages .cur").forEach((x) => x.classList.remove("cur"));
  document.querySelectorAll(`#ghPages [data-c="${cur}"]`).forEach((x) => x.classList.add("cur"));
  const h = changes[cur];
  if (scroll && kind === "pdf" && h.at && h.at[0]) {
    const { pi, y } = h.at[0], pdf = $("ghPdf");
    pdf.scrollTo({ top: pages[pi].div.offsetTop + y - pdf.clientHeight / 3, behavior: "smooth" });
  }
  if (kind === "text") $("ghText").querySelector(`[data-f="${CSS.escape(h.file)}"]`)?.scrollIntoView({ block: "start" });
}
$("ghPrev").onclick = () => go(cur < 0 ? changes.length - 1 : cur - 1, true);
$("ghNext").onclick = () => go(cur + 1, true);

// ---- 文字で見る ----
async function showText(my) {
  msg("");
  let r, d;
  try { [r, d] = await Promise.all([gget("changes", { from: sel.from, to: sel.to }), gget("cdiff", { from: sel.from, to: sel.to })]); }
  catch (e) { if (my === token) $("ghText").textContent = e.message; return; }
  if (my !== token) return;
  let file = "";
  $("ghText").innerHTML = d.diff.split("\n").map((l) => {
    if (l.startsWith("diff --git")) { file = l.split(" b/").pop(); return `<span class="file" data-f="${escapeHtml(file)}">${escapeHtml(file)}</span>`; }
    if (/^(index |--- |\+\+\+ |similarity|rename |new file|deleted file)/.test(l)) return null;
    const c = l.startsWith("+") ? "ins" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "";
    return `<span class="${c}">${escapeHtml(l) || " "}</span>`;
  }).filter((x) => x !== null).join("\n") || "（違いは無い）";
  $("ghCount").textContent = `${r.files.length} ファイル`;
  $("ghChanges").innerHTML = r.files.map((f) => `<div class="ghx-it" data-f="${escapeHtml(f.path)}"><div class="h">
      <span class="k ${f.kind === "A" ? "add" : f.kind === "D" ? "del" : "chg"}">${{ A: "追加", D: "削除", R: "名前の変更" }[f.kind] || "変更"}</span>
      <span class="f">${escapeHtml(f.path)}</span></div><div class="dim">${f.binary ? "文字でないファイル" : `<span class="pa">+${f.add}</span> <span class="pd">−${f.del}</span>`}</div></div>`).join("")
    || '<div class="empty">違いは無い</div>';
  $("ghChanges").onclick = (e) => {
    const it = e.target.closest(".ghx-it"); if (!it) return;
    if (it.dataset.f) return $("ghText").querySelector(`[data-f="${CSS.escape(it.dataset.f)}"]`)?.scrollIntoView({ block: "start" });
    go(+it.dataset.c, true);
  };
}

// ---- 赤線つきの PDF を書き出す（先生に送る「前回からの修正箇所」）----
// 画面に描いた印をそのまま PDF に焼き込む（印刷しても見える）。印の横に番号を書き、
// 最後に「修正箇所の一覧」（番号ごとの前と後の文）のページを足す。日本語は PDF にフォントを埋めずに済むよう、画像にして貼る
$("ghExport").onclick = async () => {
  if (kind !== "pdf" || !drawn.length) return showToast("PDF の表示で、変わったところがあるときに使える", "", 3000);
  showToast("赤線つきの PDF を作っている…", "", 0);
  try {
    const lib = await import("/static/pdflib/pdf-lib.esm.min.js");
    const bytes = await (await fetch(url(`/api/gitpdf${qs({ to: sel.to, main: mainTex })}`))).arrayBuffer();
    const doc = await lib.PDFDocument.load(bytes, { updateMetadata: false });
    const pp = doc.getPages(), red = lib.rgb(0.9, 0.15, 0.16);
    const font = await doc.embedFont(lib.StandardFonts.HelveticaBold);
    const toPdf = (d) => {   // 画面の px → PDF の座標（左下が原点）
      const vp = pages[d.pi].vp;
      const [x1, y1] = vp.convertToPdfPoint(d.x, d.y + d.h), [x2, y2] = vp.convertToPdfPoint(d.x + d.w, d.y);
      return { x: Math.min(x1, x2), y: Math.min(y1, y2), width: Math.abs(x2 - x1), height: Math.abs(y2 - y1) };
    };
    for (const d of drawn) {
      const page = pp[d.pi]; if (!page) continue;
      const r = toPdf(d);
      if (d.cls === "ghu") page.drawRectangle({ ...r, color: red, opacity: 0.10 });
      else if (d.cls === "ghx") {
        page.drawRectangle({ ...r, color: red, opacity: 0.20 });
        page.drawLine({ start: { x: r.x, y: r.y + 0.4 }, end: { x: r.x + r.width, y: r.y + 0.4 }, thickness: 1.1, color: red });
      } else if (d.cls === "ghcut") page.drawRectangle({ ...r, color: red });
      else if (d.cls.startsWith("ghbar")) {
        if (d.cls.endsWith("del")) for (let y = r.y + r.height; y > r.y; y -= 3.5) page.drawRectangle({ x: r.x, y: Math.max(r.y, y - 2), width: r.width, height: Math.min(2, y - r.y), color: red });
        else page.drawRectangle({ ...r, color: red });
      } else if (d.cls === "ghnum") page.drawText(String(changes[d.ci].no), { x: r.x + 1, y: r.y + 2, size: 7, font, color: red });
    }
    // 1ページ目の上の余白に、何と比べた赤線かを書く
    const p1 = pp[0], { width: W, height: H } = p1.getSize();
    const what = `赤線：${verLabel(sel.from)} からの修正箇所（${changes.filter((h) => h.located).length} か所）　${new Date().toLocaleDateString("ja-JP")}`;
    const ban = await textPng(doc, [[what, "#e5252a", 600]], W * 0.9, 9);
    p1.drawImage(ban.img, { x: (W - ban.w) / 2, y: H - 6 - ban.h, width: ban.w, height: ban.h });
    // 最後に、修正箇所の一覧のページ
    await summaryPages(doc, W, H);
    const out = await doc.save();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([out], { type: "application/pdf" }));
    a.download = `${basename(mainTex).replace(/\.tex$/, "")}_修正箇所_${verLabel(sel.from, true)}から${verLabel(sel.to, true)}.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    showToast("赤線つきの PDF をダウンロードした（最後のページに修正箇所の一覧）", "ok", 4000);
  } catch (e) { fail(e); }
};
const basename = (p) => p.slice(p.lastIndexOf("/") + 1);
function verLabel(s, file = false) {
  if (s === WT) return file ? "作業中" : "作業中の原稿";
  if (s === EMPTY_TREE) return file ? "空" : "何も無い状態";
  const c = lg.commits.find((x) => x.sha === s);
  return file ? s.slice(0, 7) : c ? `${c.short}「${c.subject}」` : s.slice(0, 7);
}
// 文字を画像にして PDF に貼る。lines は [文字, 色, 太さ]。幅 maxW（pt）で折り返す
async function textPng(doc, lines, maxW, size) {
  const k = 4, c = document.createElement("canvas"), g = c.getContext("2d");
  const fontOf = (wt) => `${wt} ${size * k}px "Noto Sans JP", "Noto Sans CJK JP", sans-serif`;
  const rows = [];
  for (const [t, color, wt] of lines) {
    g.font = fontOf(wt);
    let row = "";
    for (const ch of t) {
      if (g.measureText(row + ch).width > maxW * k && row) { rows.push([row, color, wt]); row = ""; }
      row += ch;
    }
    rows.push([row, color, wt]);
  }
  const lh = size * 1.45;
  let w = 0;
  for (const [t, , wt] of rows) { g.font = fontOf(wt); w = Math.max(w, g.measureText(t).width / k); }
  c.width = Math.ceil((w + 2) * k); c.height = Math.ceil(rows.length * lh * k + 4);
  rows.forEach(([t, color, wt], i) => { g.font = fontOf(wt); g.fillStyle = color; g.textBaseline = "top"; g.fillText(t, k, (i * lh + (lh - size) / 2) * k); });
  const png = await new Promise((r) => c.toBlob(r, "image/png"));
  return { img: await doc.embedPng(await png.arrayBuffer()), w: c.width / k, h: c.height / k };
}
async function summaryPages(doc, W, H) {
  const M = 50, maxW = W - M * 2, items = [];
  items.push([["修正箇所の一覧", "#111", 700]], [[`${verLabel(sel.from)} → ${verLabel(sel.to)}`, "#555", 400], [" ", "#000", 400]]);
  changes.forEach((h, ci) => {
    const where = h.at && h.at[0] ? `${h.at[0].pi + 1} ページ` : "PDF の上では場所が分からない";
    const blk = [[`${ci + 1}. ${KIND[h.kind]}　${h.file}:${h.line}　（${where}）`, "#e5252a", 700]];
    if (h.old.length) blk.push([`前：${h.old.join(" ").trim()}`, "#777", 400]);
    if (h.new.length) blk.push([`後：${(h.frags || []).length ? h.frags.map((f) => f.t).join(" … ") : h.new.join(" ").trim()}`, "#111", 400]);
    blk.push([" ", "#000", 400]);
    items.push(blk);
  });
  let page = null, y = 0;
  for (const blk of items) {
    const im = await textPng(doc, blk, maxW, blk[0][2] === 700 && blk === items[0] ? 14 : 9.5);
    if (!page || y - im.h < M) { page = doc.addPage([W, H]); y = H - M; }
    page.drawImage(im.img, { x: M, y: y - im.h, width: im.w, height: im.h });
    y -= im.h;
  }
}
