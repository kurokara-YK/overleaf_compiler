"""Git の画面の「編集履歴」。ブランチのコミットを push ごとにまとめて並べ、選んだ範囲で何が変わったかを、
その版の PDF の上に赤い印で示す（SyncTeX で、変わった .tex の行が PDF のどこに出ているかを引く）。

  - push の区切りは、送り先の追跡ブランチ（origin/main など）の reflog から読む（このパソコンから push・取り込みした記録）
  - その版の PDF は、コミットの中身を ~/.cache/overleaf-compiler/gitpdf/ に取り出して組む（原稿のフォルダは触らない）。
    組んだものはコミットごとに残すので、2回目からはすぐ出る
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

from . import sync
from .builder import CACHE, build_once
from .gitops import Ctx, GitError
from .project import ProjectError, _default_main, ensure_texlive, is_main

PDF_CACHE = CACHE / "gitpdf"
KEEP = 40            # リポジトリごとに残す版の数
MAX_LINES = 1500     # PDF の上で探す行の数の上限（最初のコミットなど、全部が新しいとき）
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
WT = "WORKTREE"      # 作業中（まだコミットしていない今のファイル）を版として扱うときの名前
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_build_lock = threading.Lock()   # 組版は1つずつ（CPU を取り合わない）


def _rev(c: Ctx, rev: str) -> str:
    if not rev:
        raise GitError("版を選ぶ")
    if rev in (EMPTY_TREE, WT):
        return rev
    sha = c.git("rev-parse", "--verify", "-q", f"{rev}^{{commit}}", check=False).strip()
    if not sha:
        raise GitError(f"{rev} という版は無い")
    return sha


def _has_head(c: Ctx) -> bool:
    return c.is_repo() and bool(c.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip())


# ---- ブランチとコミットの一覧 ----
def refs(q: dict) -> dict:
    """見られるブランチ。このパソコンのブランチと、GitHub（送り先）のブランチ。"""
    c = Ctx(q)
    if not c.is_repo():
        return {"current": "", "local": [], "remote": []}
    each = lambda pat: [b for b in c.git("for-each-ref", "--format=%(refname:short)", pat).split("\n") if b]
    remote = [b for b in each(f"refs/remotes/{c.remote}") + (each("refs/remotes/origin") if c.mode == "tool" else [])
              if not b.endswith("/HEAD") and b != c.remote and b != "origin"]
    return {"current": c.git("branch", "--show-current").strip(), "local": each("refs/heads"),
            "remote": remote, "remote_name": c.remote}


def _pushes(c: Ctx, track: str) -> list[dict]:
    """送り先の追跡ブランチの記録（reflog）。新しい順に、そのとき GitHub にあった版と、何で変わったか。"""
    out = c.git("reflog", "show", "--format=%H%x1f%gs%x1f%gd", "--date=unix", f"refs/remotes/{track}", check=False)
    res = []
    for l in out.splitlines():
        p = l.split("\x1f")
        if len(p) == 3:
            m = re.search(r"\{(\d+)\}", p[2])
            res.append({"sha": p[0], "why": p[1], "time": int(m.group(1)) if m else 0})
    return res


def log(q: dict) -> dict:
    """ブランチのコミットを新しい順に。push ごとの区切り（groups）と、GitHub にあるかどうか（pushed）を付ける。"""
    c = Ctx(q)
    if not _has_head(c):
        return {"commits": [], "groups": [], "ref": "", "track": ""}
    ref = q.get("ref") or c.git("branch", "--show-current").strip() or "HEAD"
    _rev(c, ref)
    remote_ref = ref.startswith((f"{c.remote}/", "origin/"))
    has = lambda t: bool(c.git("rev-parse", "--verify", "-q", f"refs/remotes/{t}", check=False).strip())
    track = ref if remote_ref else f"{c.remote}/{ref}"
    if not remote_ref and not has(track) and c.mode == "tool" and has(f"origin/{ref}"):
        track = f"origin/{ref}"   # 本体で、自分の GitHub（mine）にまだ送っていない。元のリポジトリと比べる
    has_track = has(track)
    out = c.git("log", ref, "-n", "300", "--format=%x1e%H%x1f%h%x1f%an%x1f%at%x1f%P%x1f%s", "--numstat")
    commits = []
    for rec in out.split("\x1e")[1:]:
        lines = rec.strip("\n").split("\n")
        h = lines[0].split("\x1f")
        add = dele = 0
        files = []
        for l in lines[1:]:
            p = l.split("\t")
            if len(p) == 3:
                add += int(p[0]) if p[0].isdigit() else 0
                dele += int(p[1]) if p[1].isdigit() else 0
                files.append(p[2])
        commits.append({"sha": h[0], "short": h[1], "author": h[2], "time": int(h[3]), "parent": (h[4].split() or [""])[0],
                        "subject": h[5], "add": add, "del": dele, "files": files[:50], "nfiles": len(files)})
    pushed = set()
    if has_track:
        pushed = set(c.git("rev-list", "-n", "2000", f"refs/remotes/{track}").split())
    for x in commits:
        x["pushed"] = remote_ref or x["sha"] in pushed
    # push ごとにまとめる。reflog の各記録（新しい順）が指す版から、1つ前の記録の版までが、その回に送ったコミット
    groups, index = [], {x["sha"]: i for i, x in enumerate(commits)}
    unsent = [x["sha"] for x in commits if not x["pushed"]]
    if unsent:
        groups.append({"kind": "unsent", "commits": unsent, "time": commits[0]["time"]})
    if has_track:
        tips, assigned = [], set(unsent)
        for p in _pushes(c, track):
            if p["sha"] in index and all(t["sha"] != p["sha"] for t in tips):
                tips.append(p)
        for k, p in enumerate(tips):
            start = index[p["sha"]]
            end = index[tips[k + 1]["sha"]] if k + 1 < len(tips) else len(commits)
            members = [x["sha"] for x in commits[start:max(start, end)] if x["sha"] not in assigned and x["pushed"]]
            assigned.update(members)
            if members:
                kind = "push" if "push" in p["why"] else "fetch" if p["why"].startswith(("fetch", "pull", "clone")) else "other"
                groups.append({"kind": kind, "commits": members, "time": p["time"], "why": p["why"]})
    rest = [x["sha"] for x in commits if not any(x["sha"] in g["commits"] for g in groups)]
    if rest:   # 記録の無い古いコミット（clone したときより前、別のパソコンから送ったものなど）
        groups.append({"kind": "older", "commits": rest, "time": 0})
    # 作業中の変更（コミットしていない）。今のブランチを見ているときだけ
    dirty = ref == c.git("branch", "--show-current").strip() and bool(c.git("status", "--porcelain", "--untracked-files=no").strip())
    return {"commits": commits, "groups": groups, "ref": ref, "track": track if has_track else "", "dirty": dirty}


# ---- 2つの版の違い（文字）----
def _range(c: Ctx, q: dict) -> tuple[str, str]:
    to = _rev(c, q.get("to", ""))
    frm = q.get("from") or ""
    if not frm:
        frm = c.git("rev-parse", "--verify", "-q", "HEAD" if to == WT else f"{to}^", check=False).strip() or EMPTY_TREE
    return _rev(c, frm), to


def _two(frm: str, to: str) -> list[str]:
    """git diff に渡す版。作業中なら今のファイルと比べる（コミットしていないファイルは入らない）。"""
    return [frm] if to == WT else [frm, to]


def changes(q: dict) -> dict:
    """from から to までに変わったファイルの一覧（足した行・消した行の数）。"""
    c = Ctx(q)
    frm, to = _range(c, q)
    st = {}
    for l in c.git("diff", "--name-status", "-M", *_two(frm, to)).splitlines():
        p = l.split("\t")
        st[p[-1]] = p[0][0]
    files = []
    for l in c.git("diff", "--numstat", "-M", *_two(frm, to)).splitlines():
        p = l.split("\t")
        if len(p) == 3:
            path = re.sub(r"\{[^{}]* => ([^{}]*)\}", r"\1", p[2]).replace("//", "/")
            path = path.split(" => ")[-1]
            files.append({"path": path, "kind": st.get(path, "M"), "add": int(p[0]) if p[0].isdigit() else 0,
                          "del": int(p[1]) if p[1].isdigit() else 0, "binary": p[0] == "-"})
    return {"from": frm, "to": to, "files": files}


def cdiff(q: dict) -> dict:
    c = Ctx(q)
    frm, to = _range(c, q)
    path = q.get("path", "")
    text = c.git("diff", "-M", *_two(frm, to), "--", path) if path else c.git("diff", "-M", *_two(frm, to))
    return {"diff": text[:300000]}


# ---- その版の PDF ----
def _repo_key(c: Ctx) -> str:
    return hashlib.sha1(str(c.root).encode()).hexdigest()[:12]


def _wt_files(c: Ctx):
    """作業中のファイル（.git と組版の中間生成物を除く）。"""
    from .builder import _GENERATED
    for f in sorted(c.root.rglob("*")):
        rel = f.relative_to(c.root)
        if f.is_file() and rel.parts[0] != ".git" and not f.name.endswith(_GENERATED) and not f.name.endswith(".pdf"):
            yield f, rel


def _vdir(c: Ctx, sha: str) -> Path:
    """その版を取り出す場所。作業中は、ファイルの更新時刻と大きさで名前を変える（変わったら組み直す）。"""
    if sha != WT:
        return PDF_CACHE / _repo_key(c) / sha
    h = hashlib.sha1()
    for f, rel in _wt_files(c):
        st = f.stat()
        h.update(f"{rel}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
    return PDF_CACHE / _repo_key(c) / f"wt-{h.hexdigest()[:16]}"


def _export(c: Ctx, sha: str) -> Path:
    """コミットの中身をキャッシュに取り出す（一度取り出したら使い回す）。作業中なら今のファイルを写す。"""
    base = PDF_CACHE / _repo_key(c)
    d = _vdir(c, sha)
    if (d / ".oc-ok").exists():
        d.touch()
        return d
    if sha == WT:
        tmp = base / f".{d.name}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        for f, rel in _wt_files(c):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, tmp / rel)
        tmp.mkdir(parents=True, exist_ok=True)
        (tmp / ".oc-ok").write_text("")
        shutil.rmtree(d, ignore_errors=True)
        tmp.rename(d)
        _prune(base)
        return d
    r = subprocess.run(["git", "-C", str(c.root), "archive", "--format=tar", sha], capture_output=True, timeout=120)
    if r.returncode:
        raise GitError(r.stderr.decode(errors="replace").strip()[:500] or "その版を取り出せなかった")
    tmp = base / f".{sha}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(tmp, filter="data")
    (tmp / ".oc-ok").write_text("")
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    _prune(base)
    return d


def _prune(base: Path) -> None:
    olds = sorted((p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.stat().st_mtime)
    for p in olds[:-KEEP]:
        shutil.rmtree(p, ignore_errors=True)


def _mains(root: Path) -> list[str]:
    """その版の中の主文書（\\documentclass を含む .tex）。原稿のフォルダごとに既定の1つを先に。"""
    found: dict[Path, list[Path]] = {}
    for t in sorted(root.rglob("*.tex")):
        rel = t.relative_to(root)
        if any(x.startswith((".", "_")) or x in ("node_modules", "__pycache__") for x in rel.parts) or t.name.startswith("_"):
            continue
        if is_main(t):
            found.setdefault(t.parent, []).append(t)
    out = []
    for d, ms in sorted(found.items()):
        first = _default_main(d, ms)
        out += [str(m.relative_to(root)) for m in ([first] if first else []) + [m for m in ms if m != first]]
    return out


def mains(q: dict) -> dict:
    c = Ctx(q)
    return {"mains": _mains(_export(c, _rev(c, q.get("to", ""))))}


def build(body: dict) -> dict:
    """その版の PDF を組む（裏で）。組み終わったかは state で返す。"""
    c = Ctx(body)
    sha = _rev(c, body.get("to", ""))
    root = _export(c, sha)
    ms = _mains(root)
    main = body.get("main") or ""
    if main not in ms:
        if not ms:
            return {"state": "none", "mains": []}
        main = ms[0]
    key = f"{root}/{main}"
    tex = root / main
    pdf = tex.with_suffix(".pdf")
    with _jobs_lock:
        job = _jobs.get(key)
        if not job:
            done = pdf.exists() and tex.with_suffix(".synctex.gz").exists()
            job = _jobs[key] = {"state": "done" if done else "building", "error": "", "started": time.time()}
            if not done:
                threading.Thread(target=_run, args=(key, tex), daemon=True).start()
    return {"state": job["state"], "error": job["error"], "main": main, "mains": ms, "to": sha}


def _run(key: str, tex: Path) -> None:
    job = _jobs[key]
    try:
        ensure_texlive()
        with _build_lock:
            code, out = build_once(tex, quiet=True)
        if tex.with_suffix(".pdf").exists():
            job["state"] = "done"
            if code:
                job["error"] = "エラーがあったが PDF はできた"
        else:
            job.update(state="error", error="\n".join(l for l in out.splitlines() if l.startswith(("!", "./")) or ".tex:" in l)[-1500:]
                       or "組めなかった")
    except (ProjectError, OSError) as e:
        job.update(state="error", error=str(e))


def pdf_file(q: dict) -> Path:
    c = Ctx(q)
    sha = _rev(c, q.get("to", ""))
    root = _vdir(c, sha)
    pdf = (root / q.get("main", "")).with_suffix(".pdf").resolve()
    if root.resolve() not in pdf.parents or not pdf.is_file():
        raise GitError("その版の PDF はまだ無い")
    return pdf


# ---- 変わった行が PDF のどこに出ているか ----
# 画面は、変わった行を地の文にしたもの（frags）を PDF の文字の中から探して、変わった文字に赤い線を引く。
# SyncTeX は空行や段落の終わりの行で近くの別の行を返すことがあるので、ページとおおよその高さ（hint）を決めるのにだけ使う
SEP = "\x00"
_DROP = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|ref|eqref|autoref|[cC]ref|pageref|label|url|includegraphics|input|include|"
                   r"bibliography|bibliographystyle|usepackage|documentclass|newcommand|renewcommand|providecommand|"
                   r"begin|end|vspace|hspace|setlength|addtolength)\*?(?:\s*(?:\[[^\]]*\]|\{[^{}]*\}))*")
_MATH = re.compile(r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]")
_MATHY = re.compile(r"(?<!\\)[&^_]|\\(?:frac|sum|int|left|right|mathrm|mathbf|times|cdot|alpha|beta)\b")


def plain(line: str) -> str:
    """LaTeX の1行を、PDF に出る文字に近いものにする。出ない部分（数式・参照・命令）は SEP で区切る。"""
    s = re.sub(r"(?<!\\)%.*", "", line)
    if _MATHY.search(_MATH.sub("", s)):   # 数式の環境の中の行（align など）。PDF の文字と合わない
        return SEP
    s = _MATH.sub(SEP, s)
    s = _DROP.sub(SEP, s)
    s = re.sub(r"\\(?:footnote|caption|marginpar)\*?", SEP, s)   # 本文とは別の場所に出る
    s = s.replace("\\\\", SEP).replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”").replace("~", " ")
    s = re.sub(r"\\([%&#_${}])", r"\1", s)
    s = re.sub(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?", "", s)   # \textbf などの命令の名前（中身は残す）
    s = re.sub(r"\\.", "", s).replace("{", "").replace("}", "")
    return s


def _frags(old: list[str], new: list[str], kind: str) -> list[dict]:
    """新しい行の地の文の切れ端。chg は変わった文字の範囲、cut は文字が消えた位置（どちらも切れ端の中の位置）。"""
    po, pn = SEP.join(plain(l) for l in old), SEP.join(plain(l) for l in new)
    changed, cuts = [], []
    if kind == "add" or not po.strip(SEP + " \t"):
        changed = [(0, len(pn))]
    else:
        for tag, _i1, _i2, j1, j2 in SequenceMatcher(None, po, pn, autojunk=False).get_opcodes():
            if tag in ("replace", "insert"):
                changed.append((j1, j2))
            elif tag == "delete":
                cuts.append(j1)
    out, pos = [], 0
    for part in pn.split(SEP):
        a, b = pos, pos + len(part)
        pos = b + 1
        lead = len(part) - len(part.lstrip())
        text = part.strip()
        if len(re.sub(r"\s", "", text)) < 3:
            continue
        a += lead
        b = a + len(text)
        chg = [[max(x, a) - a, min(y, b) - a] for x, y in changed if x < b and y > a]
        cut = [x - a for x in cuts if a < x < b]
        out.append({"t": text, "chg": chg, "cut": cut})
    return out


def marks(q: dict) -> dict:
    """from → to で変わった .tex の行。変わったところ（hunk）ごとに、地の文の切れ端と、PDF の上のおおよその場所。

    kind は add（足した）・chg（書き換えた）・del（消した。消した場所の直前の行を ctx として返す）。
    """
    c = Ctx(q)
    frm, to = _range(c, q)
    root = _vdir(c, to)
    pdf = pdf_file(q)
    diff = c.git("diff", "-U0", "-M", "--no-color", *_two(frm, to), "--", "*.tex", "*.ltx")
    hunks, path = [], None
    for l in diff.splitlines():
        if l.startswith("+++ "):
            path = None if l[4:] == "/dev/null" else l[6:] if l.startswith("+++ b/") else l[4:]
        elif (m := _HUNK.match(l)) and path:
            b = int(m.group(2)) if m.group(2) is not None else 1   # 行の数。省かれていれば1
            s, n = int(m.group(3)), int(m.group(4)) if m.group(4) is not None else 1
            kind = "del" if n == 0 else "add" if b == 0 else "chg"
            hunks.append({"file": path, "line": max(1, s), "n": n, "kind": kind, "old": [], "new": []})
        elif hunks and l.startswith("-") and not l.startswith("---"):
            hunks[-1]["old"].append(l[1:])
        elif hunks and l.startswith("+") and not l.startswith("+++"):
            hunks[-1]["new"].append(l[1:])
    texts: dict[str, list[str]] = {}

    def text_of(f: str) -> list[str]:
        if f not in texts:
            try:
                texts[f] = (root / f).read_text(errors="replace").split("\n")
            except OSError:
                texts[f] = []
        return texts[f]

    budget = MAX_LINES
    for h in hunks:
        lines = text_of(h["file"])
        if h["kind"] == "del":   # 消した場所の手前の、中身のある行
            ln = h["line"]
            while ln > 1 and ln <= len(lines) and not plain(lines[ln - 1]).strip(SEP + " \t"):
                ln -= 1
            h["ctx"] = [f["t"] for f in _frags([], [lines[ln - 1]], "add")] if 0 < ln <= len(lines) else []
            h["hint_line"] = ln
        else:
            first = next((i for i, x in enumerate(h["new"]) if plain(x).strip(SEP + " \t")), 0)
            h["hint_line"] = h["line"] + first
        h["frags"] = _frags(h["old"], h["new"], h["kind"]) if budget > 0 else []
        budget -= len(h["new"])

    def where(h):
        src = (root / h["file"]).resolve()
        for ln in range(h["hint_line"], max(0, h["hint_line"] - 8), -1):   # 位置の記録が無い行なら、手前の行で
            try:
                boxes = sync.source_to_pdf(pdf, src, ln) if src.is_file() else []
            except (OSError, sync.SyncError):
                boxes = []
            if boxes:
                return {"page": boxes[0]["page"], "y": boxes[0]["y"]}
        return None

    with ThreadPoolExecutor(8) as ex:
        for h, hint in zip(hunks, ex.map(where, hunks)):
            h["hint"] = hint
    for h in hunks:   # 長すぎる中身は画面に出さない
        h["old"], h["new"] = h["old"][:40], h["new"][:40]
        del h["hint_line"]
    return {"from": frm, "to": to, "changes": hunks, "truncated": budget < 0}


# ---- 画面とのやり取り（server.py から呼ぶ）----
GET = {"refs": refs, "log": log, "changes": changes, "cdiff": cdiff, "mains": mains, "marks": marks}
POST = {"build": build}
