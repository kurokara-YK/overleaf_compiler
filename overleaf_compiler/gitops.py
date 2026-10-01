"""Git の画面（ヘッダの ⎇ Git）。2つの使い方を切り替える。

  - 原稿（既定）：data の下のフォルダ（要旨・論文など）を、選んだ GitHub のアカウント・リポジトリ・ブランチへ上げる。
    GitHub への入り方は gh のデバイスコードでのログイン（ghauth.py）。push・取り込みのときだけ、そのアカウントの
    権限を git に渡す（git の全体の設定は変えない）。送り先などはそのフォルダのリポジトリの設定に覚える。
  - 本体：overleaf-compiler 自身のリポジトリ。本体は公開リポジトリを clone して使うものなので、push は
    ログインした人自身の GitHub のリポジトリ（送り先 mine）へ送り、元のリポジトリ（origin）には送らない。
    「最新版に更新」は元のリポジトリ（origin）から取り込む。

守ること
  - Overleaf の Git（git.overleaf.com）には上げない（Overleaf は操作しない）
  - 強制 push はしない。push の前に、送り先と送るコミットを画面で見せる
  - 公開リポジトリ（本体・公開の原稿のリポジトリ）では、コミットの前に個人名などが無いか調べる
  - 本体では、data/ の下は data/sample 以外コミットできない
  - 自動で書いたメッセージから Co-Authored-By などの署名を取り除く
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ghauth
from .install import CONFIG, REPO, config

MAX_DIFF = 40000   # 自動作成に渡す差分の長さの上限（文字）
DATA: Path | None = None   # data の場所（server.py の serve が入れる）
NAME = re.compile(r"[A-Za-z0-9._/\-]+")
GITIGNORE = """# LaTeX の中間生成物（overleaf-compiler が作った .gitignore）
*.aux
*.bbl
*.bcf
*.blg
*.dvi
*.fdb_latexmk
*.fls
*.log
*.nav
*.out
*.run.xml
*.snm
*.synctex.gz
*.synctex(busy)
*.toc
*.lof
*.lot
*.xdv
*-SAVE-ERROR
# overleaf-compiler の作業用のファイル
*.overleaf-compiler-tmp
.overleaf-compiler-serve.json
"""


class GitError(Exception):
    pass


class Ctx:
    """どのリポジトリを扱うか。p の mode が tool なら本体、それ以外は data の下の dir のフォルダ。"""

    def __init__(self, p: dict | None):
        p = p or {}
        self.mode = "tool" if p.get("mode") == "tool" else "data"
        # push の送り先。原稿は origin、本体は自分の GitHub（mine。origin は元の公開リポジトリで、取り込みにだけ使う）
        self.remote = "mine" if self.mode == "tool" else "origin"
        if self.mode == "tool":
            self.root, self.rel = REPO, ""
            return
        if DATA is None:
            raise GitError("data の場所が分からない")
        self.rel = str(p.get("dir", "")).strip("/")
        if not self.rel:
            raise GitError("GitHub に上げるフォルダを選ぶ")
        d = (DATA / self.rel).resolve()
        if d == DATA or DATA not in d.parents or not d.is_dir():
            raise GitError(f"{self.rel} は data の中のフォルダではない")
        self.root = d

    def git(self, *args: str, check: bool = True, timeout: float = 60, auth: bool = False, input: str | None = None) -> str:
        cmd, env = ["git", "-C", str(self.root)], None
        if auth:   # 選んだ GitHub のアカウントの権限を、このときだけ渡す
            user = self.cfg("account")
            if not user:
                raise GitError("GitHub のアカウントが選ばれていない")
            try:
                tok = ghauth.token(user)
            except ghauth.GhError as e:
                raise GitError(str(e))
            env = {**os.environ, "OC_GH_TOKEN": tok, "GIT_TERMINAL_PROMPT": "0"}
            cmd += ["-c", "credential.helper=", "-c",
                    'credential.helper=!f() { echo username=x-access-token; echo "password=$OC_GH_TOKEN"; }; f']
        try:
            r = subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=timeout, env=env, input=input)
        except FileNotFoundError:
            raise GitError("git が見つからない")
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} が終わらない（ネットワークか認証を確かめる）")
        if check and r.returncode:
            raise GitError((r.stderr or r.stdout).strip()[:1500] or f"git {args[0]} に失敗した")
        return r.stdout

    def is_repo(self) -> bool:
        return (self.root / ".git").exists()

    def cfg(self, key: str) -> str:
        return self.git("config", "--get", f"overleaf-compiler.{key}", check=False).strip() if self.is_repo() else ""

    def set_cfg(self, key: str, value: str) -> None:
        self.git("config", f"overleaf-compiler.{key}", value)

    def forbidden(self, path: str) -> bool:
        """本体では、原稿（data/ の下。data/sample は除く）はコミットさせない。"""
        if self.mode != "tool":
            return False
        p = path.replace("\\", "/")
        return p.startswith("data/") and not p.startswith("data/sample/") and p != "data/.gitkeep"

    def public(self) -> bool:
        """公開リポジトリか（個人名などを調べる）。本体はいつも公開とみなす。"""
        return self.mode == "tool" or self.cfg("private") == "false"


def _overleaf(url: str) -> bool:
    return "overleaf.com" in (url or "").lower()


# ---- 状態 ----
def status(q: dict | None = None) -> dict:
    c = Ctx(q)
    base = {"mode": c.mode, "dir": c.rel, "repo": c.root.name}
    if not c.is_repo():
        if c.mode == "tool":
            raise GitError(f"{REPO} は Git のリポジトリではない")
        inner = c.git("rev-parse", "--show-toplevel", check=False).strip()   # 外側のリポジトリ（本体）は使わない
        return {**base, "is_repo": False, "outer": bool(inner) and Path(inner).resolve() != c.root}
    branch = c.git("branch", "--show-current").strip() or "(detached)"
    target = c.cfg("branch") or branch
    url = c.git("remote", "get-url", c.remote, check=False).strip()
    upstream = f"{c.remote}/{target}" if c.git("rev-parse", "--verify", "-q", f"{c.remote}/{target}", check=False).strip() else ""
    ahead = behind = 0
    has_head = bool(c.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip())
    if upstream and has_head:
        a, _, b = c.git("rev-list", "--left-right", "--count", f"HEAD...{upstream}", check=False).strip().partition("\t")
        ahead, behind = int(a or 0), int(b or 0)
    elif has_head:
        ahead = len([x for x in c.git("rev-list", "HEAD", check=False).split() if x])
    # 本体：元の公開リポジトリ（origin）に、取り込める新しいコミットがあるか
    updates = 0
    if c.mode == "tool" and has_head and c.git("rev-parse", "--verify", "-q", f"origin/{branch}", check=False).strip():
        updates = int(c.git("rev-list", "--count", f"HEAD..origin/{branch}", check=False).strip() or 0)
        if not url:
            behind = updates
    files = []
    items = c.git("status", "--porcelain=v1", "-z", "-uall").split("\0")
    i = 0
    while i < len(items):
        e = items[i]
        i += 1
        if len(e) < 4:
            continue
        xy, path = e[:2], e[3:]
        if xy[0] in "RC":   # 名前の変更は、次の項目が元の名前
            i += 1
        kind = "?" if xy == "??" else "U" if "U" in xy or xy in ("AA", "DD") else "D" if "D" in xy else "A" if "A" in xy else "R" if "R" in xy else "M"
        files.append({"path": path, "kind": kind, "forbidden": c.forbidden(path)})
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    head_pushed = bool(upstream and has_head and not ahead)   # 今のコミットは GitHub にもある
    return {**base, "is_repo": True, "has_head": has_head, "head_pushed": head_pushed, "op": _op(c),
            "conflicts": [f["path"] for f in files if f["kind"] == "U"], "branch": branch, "target": target, "upstream": upstream, "ahead": ahead,
            "behind": behind, "files": files, "remote_url": url, "remote": m.group(1) if m else "",
            "account": c.cfg("account"), "private": c.cfg("private") != "false", "public_check": c.public(),
            "updates": updates, "origin_url": c.git("remote", "get-url", "origin", check=False).strip() if c.mode == "tool" else url,
            "last": c.git("log", "-1", "--format=%h %s", check=False).strip() if has_head else ""}


def local_branches(q: dict) -> dict:
    c = Ctx(q)
    if not c.is_repo():
        return {"current": "", "local": []}
    local = [b for b in c.git("for-each-ref", "--format=%(refname:short)", "refs/heads").split("\n") if b]
    return {"current": c.git("branch", "--show-current").strip(), "local": local}


def folders(_=None) -> dict:
    """data の下で、すでに Git で管理しているフォルダ（原稿のリポジトリ）。"""
    if DATA is None:
        return {"folders": []}
    out = []
    for g in sorted(DATA.rglob(".git")):
        d = g.parent
        if d != DATA and not any(x.startswith(".") for x in d.relative_to(DATA).parts):
            out.append(str(d.relative_to(DATA)))
        if len(out) > 200:
            break
    return {"folders": out}


def diff(q: dict) -> dict:
    c = Ctx(q)
    path = q.get("path", "")
    if not path:
        raise GitError("ファイルを選ぶ")
    has_head = bool(c.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip())
    tracked = c.git("ls-files", "--", path).strip() if has_head else ""
    if tracked:
        text = c.git("diff", "HEAD", "--", path)
    else:   # まだ Git に入っていないファイルは、全部が足した行
        f = (c.root / path).resolve()
        if c.root not in f.parents or not f.is_file():
            raise GitError("そのファイルは無い")
        try:
            body = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            body = "（文字ではないファイル）"
        text = "".join(f"+{line}\n" for line in body.splitlines()[:2000])
    return {"path": path, "diff": text[:200000]}


# ---- 原稿のフォルダの準備と、送り先（アカウント・リポジトリ・ブランチ）----
def init(body: dict) -> dict:
    """このフォルダを Git で管理する（git init と、LaTeX 用の .gitignore）。"""
    c = Ctx(body)
    if c.mode != "data":
        raise GitError("本体はもう Git で管理している")
    if not c.is_repo():
        c.git("init", "-q", "-b", "main")
    gi = c.root / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE + ("" if body.get("include_pdf") else "# 組んだ PDF（入れるなら消す）\n*.pdf\n"))
    return status(body)


def connect(body: dict) -> dict:
    """送り先を決める：どのアカウントで、どのリポジトリの、どのブランチへ。"""
    c = Ctx(body)
    if not c.is_repo():
        raise GitError("先にこのフォルダを Git で管理する")
    user, full, branch = str(body.get("account", "")), str(body.get("repo", "")), str(body.get("branch", "") or "main")
    if not user or not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", full):
        raise GitError("アカウントとリポジトリを選ぶ")
    if not NAME.fullmatch(branch):
        raise GitError("ブランチの名前に使えない文字がある")
    url = f"https://github.com/{full}.git"
    if _overleaf(url):
        raise GitError("Overleaf の Git には上げない")
    if c.git("remote", "get-url", c.remote, check=False).strip():
        c.git("remote", "set-url", c.remote, url)
    else:
        c.git("remote", "add", c.remote, url)
    c.set_cfg("account", user)
    c.set_cfg("branch", branch)
    c.set_cfg("private", "true" if body.get("private", True) else "false")
    # コミットする人の名前が無ければ、GitHub のアカウント（メールは公開されない noreply）にする
    if not c.git("config", "user.email", check=False).strip():
        try:
            u = ghauth.user_info(user)
            c.git("config", "user.name", u.get("name") or u["login"])
            c.git("config", "user.email", f"{u['id']}+{u['login']}@users.noreply.github.com")
        except (ghauth.GhError, KeyError):
            pass
    return status(body)


def disconnect(body: dict) -> dict:
    """このフォルダの送り先を外す（GitHub のリポジトリやコミットはそのまま）。"""
    c = Ctx(body)
    if not c.is_repo():
        raise GitError("送り先は無い")
    c.git("remote", "remove", c.remote, check=False)
    for k in ("account", "branch", "private"):
        c.git("config", "--unset", f"overleaf-compiler.{k}", check=False)
    return status(body)


# ---- ブランチ・取り込み ----
def checkout(body: dict) -> dict:
    c = Ctx(body)
    name = str(body.get("branch", "")).strip()
    if not NAME.fullmatch(name) or name.startswith(("-", "/")):
        raise GitError("ブランチの名前に使えない文字がある")
    has_head = bool(c.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip())
    if has_head:
        c.git("switch", *(["-c"] if body.get("create") else []), name)
    else:   # まだコミットが無いときは、名前だけ変える
        c.git("symbolic-ref", "HEAD", f"refs/heads/{name}")
    c.set_cfg("branch", name)
    return status(body)


def fetch(body: dict | None = None) -> dict:
    c = Ctx(body)
    if c.mode == "tool":   # 元の公開リポジトリは、ログインなしで見られる
        c.git("fetch", "--prune", "origin", timeout=120, check=False)
    if c.git("remote", "get-url", c.remote, check=False).strip():
        c.git("fetch", "--prune", c.remote, timeout=120, auth=True)
    elif c.mode == "data":
        raise GitError("送り先が決まっていない")
    return status(body)


def pull(body: dict | None = None) -> dict:
    c = Ctx(body)
    st = status(body)
    if c.mode == "tool":   # 本体の最新版は、元の公開リポジトリ（origin）から取り込む
        out = c.git("pull", "--ff-only", "origin", st["branch"], timeout=180)
        return {**status(body), "message": out.strip()[-800:] or "最新になっている"}
    target = st.get("target") or st.get("branch")
    c.git("fetch", "origin", timeout=120, auth=True)
    if not c.git("rev-parse", "--verify", "-q", f"origin/{target}", check=False).strip():
        return {**status(body), "message": "GitHub 側にまだ何も無い"}
    out = c.git("merge", "--ff-only", f"origin/{target}", timeout=120)
    return {**status(body), "message": out.strip()[-800:] or "最新になっている"}


# ---- 個人情報などの確認（公開リポジトリのとき）----
# 既定の「公開前に調べる言葉」は例。使う人が自分の名前・学籍番号・所属などに書き換える
DEFAULT_WORDS = ["山田太郎", "yamada.taro", "〇〇大学", "A1234567"]
DEFAULT_ALLOW = ["github.com/your-account"]


def _private_words() -> tuple[list[str], list[str]]:
    cf = config()
    words = cf.get("private_words", DEFAULT_WORDS)
    allow = cf.get("private_allow", DEFAULT_ALLOW)
    return [w for w in words if w], [a for a in allow if a]


def set_private(body: dict) -> dict:
    """調べる言葉（1行に1つ）と、出てきても良い書き方を、リポジトリの外の設定に置く。"""
    from .install import set_config
    words = [w.strip() for w in str(body.get("words", "")).splitlines() if w.strip()]
    allow = [w.strip() for w in str(body.get("allow", "")).splitlines() if w.strip()]
    set_config(private_words=words, private_allow=allow)
    return {"words": words, "allow": allow}


def get_private(_=None) -> dict:
    words, allow = _private_words()
    return {"words": words, "allow": allow, "where": str(CONFIG)}


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def scan(p: dict, paths: list[str]) -> list[dict]:
    """これから入る変更（足した行）に、調べる言葉やメールアドレスが無いか。見つかった所を返す。"""
    words, allow = _private_words()
    hits = []
    for path in paths:
        text = diff({**p, "path": path})["diff"]
        line_no = 0
        for line in text.splitlines():
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", line)
            if m:
                line_no = int(m.group(1)) - 1
                continue
            if line.startswith(("+++", "---")):
                continue
            if line.startswith("+"):
                line_no += 1
                body = line[1:]
                checked = body
                for a in allow:
                    checked = checked.replace(a, "")
                found = [w for w in words if w.lower() in checked.lower()]
                found += [e for e in EMAIL.findall(checked) if "noreply" not in e and "example." not in e]
                if found:
                    hits.append({"path": path, "line": line_no, "words": sorted(set(found)), "text": body.strip()[:200]})
            elif not line.startswith("-"):
                line_no += 1
    return hits


# ---- コミット・push ----
TRAILER = re.compile(r"^\s*(Co-Authored-By|Generated[- ]with|🤖)[^\n]*$", re.I | re.M)


def clean_message(msg: str) -> str:
    """署名（Co-Authored-By: Claude など）と、前後の余分な空行・コードの囲みを取り除く。"""
    msg = re.sub(r"^```[a-z]*\n|\n```$", "", msg.strip())
    msg = TRAILER.sub("", msg)
    lines = msg.strip().split("\n")
    if len(lines) > 1 and lines[1].strip():   # 1行目（要約）のあとは空行を1つ置く（git の決まり）
        lines.insert(1, "")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def commit(body: dict) -> dict:
    c = Ctx(body)
    paths = [p for p in body.get("paths", []) if isinstance(p, str)]
    msg = clean_message(str(body.get("message", "")))
    if not c.is_repo():
        raise GitError("先にこのフォルダを Git で管理する")
    if not paths:
        raise GitError("コミットするファイルを選ぶ")
    if not msg:
        raise GitError("コミットメッセージが空")
    bad = [p for p in paths if c.forbidden(p)]
    if bad:
        raise GitError("原稿（data/ の下）は本体にコミットできない: " + ", ".join(bad[:5]))
    if c.public() and not body.get("force_private"):
        hits = scan(body, paths)
        if hits:
            return {"private": hits}
    if c.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip():
        c.git("reset", "-q")   # 選んだものだけを入れる
    existing = [p for p in paths if (c.root / p).exists()]
    removed = [p for p in paths if not (c.root / p).exists()]
    if existing:
        c.git("add", "--", *existing)
    if removed:
        c.git("rm", "-q", "--cached", "--ignore-unmatch", "--", *removed)
    if not c.git("diff", "--cached", "--name-only").strip():   # 画面の一覧が古い（もうコミットしてある）
        return {**status(body), "nothing": True}
    c.git("commit", "-q", "-F", "-", input=msg)
    return {**status(body), "committed": c.git("log", "-1", "--format=%h %s").strip()}


# ---- 取り消し・途中の取り込みをやめる ----
_OPS = {"MERGE_HEAD": ("merge", "取り込み（merge）"), "rebase-merge": ("rebase", "付け替え（rebase）"),
        "rebase-apply": ("rebase", "付け替え（rebase）"), "CHERRY_PICK_HEAD": ("cherry-pick", "コミットの取り込み（cherry-pick）"),
        "REVERT_HEAD": ("revert", "打ち消し（revert）")}


def _op(c: Ctx) -> dict | None:
    """途中で止まっている操作（コンフリクトなど）。"""
    gd = Path(c.git("rev-parse", "--absolute-git-dir", check=False).strip() or c.root / ".git")
    for f, (cmd, label) in _OPS.items():
        if (gd / f).exists():
            return {"cmd": cmd, "label": label}
    return None


def undo(body: dict) -> dict:
    """直前のコミット（と、そのときの git add）を取り消す。ファイルの中身には一切触らない。

    コミットを無かったことにして、入れた変更を一覧（まだ add していない状態）に戻すだけ（git reset --soft と git reset）。
    GitHub に送ったコミットは取り消さない（取り消すと GitHub と食い違い、強制 push が要るため）。
    """
    c = Ctx(body)
    st = status(body)
    if not st.get("has_head"):
        raise GitError("取り消すコミットが無い")
    if st.get("op"):
        raise GitError(f"{st['op']['label']}の途中。先に「やめて元に戻す」を押す")
    if st["head_pushed"]:
        raise GitError("直前のコミットはもう GitHub に送ってあるので、取り消せない")
    msg = c.git("log", "-1", "--format=%B").strip()
    if c.git("rev-parse", "--verify", "-q", "HEAD~1", check=False).strip():
        c.git("reset", "-q", "--soft", "HEAD~1")
    else:   # 最初のコミット
        c.git("update-ref", "-d", "HEAD")
    c.git("reset", "-q", check=False)   # git add も取り消す（ファイルの中身はそのまま）
    return {**status(body), "undone": msg}


def last_commit(q: dict) -> dict:
    """取り消す前に見せる、直前のコミットのメッセージと入っているファイル。"""
    c = Ctx(q)
    if not c.is_repo() or not c.git("rev-parse", "--verify", "-q", "HEAD", check=False).strip():
        return {"sha": ""}
    files = [l for l in c.git("show", "--name-status", "--format=", "HEAD").splitlines() if l]
    return {"sha": c.git("rev-parse", "--short", "HEAD").strip(), "message": c.git("log", "-1", "--format=%B").strip(),
            "files": files[:200], "nfiles": len(files)}


def abort(body: dict) -> dict:
    """途中で止まった取り込み・付け替えなどをやめて、始める前の状態に戻す。"""
    c = Ctx(body)
    op = _op(c)
    if not op:
        raise GitError("途中の操作は無い")
    c.git(op["cmd"], "--abort")
    return {**status(body), "aborted": op["label"]}


def outgoing(q: dict) -> dict:
    """push で送るコミット（送り先にまだ無いもの）と、送り先。"""
    c = Ctx(q)
    st = status(q)
    target = q.get("branch") or st.get("target") or st["branch"]
    base = f"{c.remote}/{target}" if c.git("rev-parse", "--verify", "-q", f"{c.remote}/{target}", check=False).strip() else ""
    log = c.git("log", "--format=%h %s", f"{base}..HEAD" if base else "HEAD", "-n", "50", check=False).strip()
    return {"remote_url": st["remote_url"], "account": st.get("account", ""), "branch": target,
            "commits": [l for l in log.split("\n") if l], "new_branch": not base, "private": st.get("private", True)}


def push(body: dict) -> dict:
    c = Ctx(body)
    st = status(body)
    url = st.get("remote_url", "")
    if not url:
        raise GitError("送り先（リポジトリ）が決まっていない")
    if _overleaf(url):
        raise GitError("Overleaf の Git には上げない")
    target = str(body.get("branch") or st.get("target") or st["branch"]).strip()
    if not NAME.fullmatch(target):
        raise GitError("ブランチの名前に使えない文字がある")
    if c.mode == "tool" and url == c.git("remote", "get-url", "origin", check=False).strip() \
            and c.cfg("account") and f"/{c.cfg('account')}/" not in url.replace("github.com:", "github.com/") + "/":
        raise GitError("元の公開リポジトリには送らない。自分の GitHub のリポジトリを送り先に選ぶ")
    args = ["push", "-u", c.remote, f"HEAD:refs/heads/{target}"]   # 強制 push はしない
    try:
        c.git(*args, timeout=180, auth=True)
    except GitError as e:
        if "rejected" in str(e) or "non-fast-forward" in str(e) or "fetch first" in str(e):
            raise GitError("GitHub 側に、ここに無いコミットがある。先に取り込むか、"
                           "空のリポジトリ（新しく作る）を送り先にする\n" + str(e)[:400])
        raise
    c.git("branch", f"--set-upstream-to={c.remote}/{target}", check=False)
    return {**status(body), "pushed": target}


# ---- コミットメッセージの自動作成 ----
def generate(body: dict) -> dict:
    """選んだファイルの変更から、コミットメッセージを書かせる（Claude Code・Codex・Copilot）。"""
    c = Ctx(body)
    paths = [p for p in body.get("paths", []) if isinstance(p, str) and not c.forbidden(p)]
    if not paths:
        raise GitError("コミットするファイルを選ぶ")
    changes = "\n".join(f"### {p}\n{diff({**body, 'path': p})['diff']}" for p in paths)
    changes = changes if len(changes) <= MAX_DIFF else changes[:MAX_DIFF] + "\n…（長いので省いた）"
    recent = c.git("log", "-8", "--format=%s%n%b%n---", check=False) if c.is_repo() else ""
    what = "LaTeX の原稿" if c.mode == "data" else "ソフトウェア"
    prompt = (f"次の変更（{what}）のための git のコミットメッセージを1つ書いて。メッセージだけを出力する（前置き・説明・コードの囲みは不要）。\n"
              "1行目に日本語の短い要約、空行、そのあと「- 」で始まる箇条書きで主な変更。最近のコミットがあれば、その書き方に合わせる。\n"
              "Co-Authored-By などの署名は付けない。\n\n"
              f"## 最近のコミット\n{recent[:3000] or '（まだ無い）'}\n\n## 変更\n{changes}")
    engine = body.get("engine", "claude")
    if engine == "codex":
        from .codex import find_codex
        exe = find_codex()
        if not exe:
            raise GitError("codex コマンドが見つからない")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "msg.txt"
            r = subprocess.run([exe, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
                                "--color", "never", "-o", str(out), "-"], input=prompt, capture_output=True, text=True,
                               timeout=240, cwd=tmp)
            text = out.read_text() if out.exists() else ""
            if not text.strip():
                raise GitError((r.stderr or r.stdout).strip()[-800:] or "Codex が書けなかった")
    elif engine == "copilot":
        exe = shutil.which("copilot")
        if not exe:
            raise GitError("GitHub Copilot の CLI（copilot）が入っていない")
        r = subprocess.run([exe, "-p", prompt], capture_output=True, text=True, timeout=240, cwd=tempfile.gettempdir())
        text = r.stdout
        if r.returncode or not text.strip():
            raise GitError((r.stderr or r.stdout).strip()[-800:] or "Copilot が書けなかった")
    else:
        from .claude import find_claude
        exe = find_claude()
        if not exe:
            raise GitError("claude コマンドが見つからない")
        r = subprocess.run([exe, "-p", "--tools", "", "--no-session-persistence", "--model", "sonnet",
                            "--output-format", "text"], input=prompt, capture_output=True, text=True, timeout=240,
                           cwd=tempfile.gettempdir())
        text = r.stdout
        if r.returncode or not text.strip():
            raise GitError((r.stderr or r.stdout).strip()[-800:] or "Claude Code が書けなかった")
    return {"message": clean_message(text)}


def engines(_=None) -> dict:
    from .claude import find_claude
    from .codex import find_codex
    return {"claude": bool(find_claude()), "codex": bool(find_codex()), "copilot": bool(shutil.which("copilot"))}


# ---- 画面とのやり取り（server.py から呼ぶ）----
GET = {"status": status, "branches": local_branches, "diff": diff, "private": get_private, "engines": engines,
       "outgoing": outgoing, "folders": folders, "last_commit": last_commit}
POST = {"init": init, "connect": connect, "disconnect": disconnect, "checkout": checkout, "fetch": fetch,
        "pull": pull, "commit": commit, "undo": undo, "abort": abort, "push": push, "generate": generate, "private": set_private}
