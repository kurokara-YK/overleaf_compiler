"""GitHub との連携（Git の画面の「原稿」で使う）。GitHub 公式の gh（GitHub CLI）に任せる。

ログインはデバイスコード方式：画面に出た8文字のコードを、ブラウザの github.com/login/device に入れて許可する。
アプリはパスワードもトークンも保存しない。保存は gh が行う（システムの鍵束か ~/.config/gh）ので、アプリを閉じても覚えている。
「連携をやめる」は gh auth logout。gh が無ければ ~/.local/bin に入れる（sudo 不要）。
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import urllib.request
from urllib.parse import quote
from pathlib import Path

BIN = Path.home() / ".local" / "bin"
HOST = "github.com"


class GhError(Exception):
    pass


def find_gh() -> str | None:
    if p := shutil.which("gh"):
        return p
    return str(BIN / "gh") if (BIN / "gh").exists() else None


def install_gh(_=None) -> dict:
    """gh の公式のリリースを ~/.local/bin に入れる。"""
    if find_gh():
        return {"gh": find_gh()}
    arch = "arm64" if platform.machine() in ("aarch64", "arm64") else "amd64"
    try:
        with urllib.request.urlopen("https://api.github.com/repos/cli/cli/releases/latest", timeout=30) as r:
            tag = json.load(r)["tag_name"]
        url = f"https://github.com/cli/cli/releases/download/{tag}/gh_{tag[1:]}_linux_{arch}.tar.gz"
        with urllib.request.urlopen(url, timeout=300) as r, tarfile.open(fileobj=r, mode="r|gz") as tf:
            for m in tf:
                if m.name.endswith("/bin/gh"):
                    BIN.mkdir(parents=True, exist_ok=True)
                    (BIN / "gh").write_bytes(tf.extractfile(m).read())
                    (BIN / "gh").chmod(0o755)
                    break
    except Exception as e:
        raise GhError(f"gh を入れられなかった（{e}）")
    if not find_gh():
        raise GhError("gh を入れられなかった")
    return {"gh": find_gh()}


def _gh(*args: str, user: str | None = None, timeout: float = 60, input: str | None = None) -> str:
    exe = find_gh()
    if not exe:
        raise GhError("gh（GitHub CLI）が入っていない")
    env = {**os.environ, "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    if user:
        env["GH_TOKEN"] = token(user)
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=env, input=input)
    if r.returncode:
        raise GhError((r.stderr or r.stdout).strip()[:800] or f"gh {args[0]} に失敗した")
    return r.stdout


# ---- アカウント ----
def accounts(_=None) -> dict:
    """連携しているアカウント（gh に保存されているもの）。"""
    if not find_gh():
        return {"gh": False, "accounts": []}
    exe = find_gh()
    r = subprocess.run([exe, "auth", "status", "--hostname", HOST, "--json", "hosts"], capture_output=True, text=True,
                       timeout=30, env={**os.environ, "GH_PROMPT_DISABLED": "1"})
    try:
        hosts = json.loads(r.stdout or "{}").get("hosts", {}).get(HOST, [])
    except json.JSONDecodeError:
        hosts = []
    return {"gh": True, "accounts": [{"login": h.get("login"), "active": bool(h.get("active")), "ok": h.get("state") == "success",
                                      "scopes": h.get("scopes", "")} for h in hosts if h.get("login")],
            "login": _login_state()}


def token(user: str) -> str:
    exe = find_gh()
    r = subprocess.run([exe, "auth", "token", "--hostname", HOST, "--user", user], capture_output=True, text=True, timeout=30)
    if r.returncode or not r.stdout.strip():
        raise GhError(f"{user} の連携が切れている。もう一度ログインする")
    return r.stdout.strip()


def logout(body: dict) -> dict:
    """連携をやめる（gh に保存された、そのアカウントの権限を消す）。"""
    user = str(body.get("user", ""))
    exe = find_gh()
    if not exe or not user:
        raise GhError("アカウントを選ぶ")
    r = subprocess.run([exe, "auth", "logout", "--hostname", HOST, "--user", user], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise GhError((r.stderr or r.stdout).strip()[:500])
    return accounts()


# ---- デバイスコードでのログイン（裏で gh auth login --web を動かし、コードを画面に出す）----
_login: dict = {"proc": None, "code": "", "url": "", "state": "idle", "error": ""}


def _login_state() -> dict:
    p = _login["proc"]
    if p is not None and p.poll() is not None and _login["state"] == "waiting":
        _login["state"] = "done" if p.returncode == 0 else "error"
    return {k: _login[k] for k in ("code", "url", "state", "error")}


def login_start(_=None) -> dict:
    """新しいアカウントで連携する。"""
    return _device(["auth", "login", "--hostname", HOST, "--git-protocol", "https", "--web", "--skip-ssh-key",
                    "--scopes", "repo,read:org"])


def refresh_start(body: dict) -> dict:
    """そのアカウントに権限を足す（リポジトリの削除には delete_repo が要る。GitHub の決まり）。"""
    user, scopes = str(body.get("user", "")), str(body.get("scopes", "delete_repo"))
    if not re.fullmatch(r"[a-z_:,]+", scopes):
        raise GhError("権限の名前がおかしい")
    exe = find_gh()
    if user:   # gh auth refresh は、使っている（active な）アカウントにしか効かない
        subprocess.run([exe, "auth", "switch", "--hostname", HOST, "--user", user], capture_output=True, timeout=30)
    return _device(["auth", "refresh", "--hostname", HOST, "--scopes", scopes])


def _device(args: list[str]) -> dict:
    """デバイスコードの手続きを裏で動かし、コードが出るまで待って返す。"""
    exe = find_gh()
    if not exe:
        raise GhError("gh（GitHub CLI）が入っていない")
    old = _login["proc"]
    if old is not None and old.poll() is None:
        old.terminate()
    # BROWSER=true：gh 自身はブラウザを開かない（画面の「GitHub を開く」で開く）
    env = {**os.environ, "BROWSER": "true", "GH_PROMPT_DISABLED": "1"}
    p = subprocess.Popen([exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, env=env)
    _login.update(proc=p, code="", url="https://github.com/login/device", state="starting", error="")

    def read():
        tail = []
        for line in p.stdout:
            tail = (tail + [line.strip()])[-6:]
            if m := re.search(r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})", line):
                _login.update(code=m.group(1), state="waiting")
            if m := re.search(r"(https://github\.com/login/device\S*)", line):
                _login["url"] = m.group(1)
        p.wait()
        if p.returncode:
            _login.update(state="error", error=" ".join(t for t in tail if t and "clipboard" not in t.lower())[-400:])
        else:
            _login["state"] = "done"
    threading.Thread(target=read, daemon=True).start()
    for _ in range(100):   # コードが出るまで少し待つ
        if _login["code"] or _login["state"] == "error":
            break
        threading.Event().wait(0.1)
    return _login_state()


def login_cancel(_=None) -> dict:
    p = _login["proc"]
    if p is not None and p.poll() is None:
        p.terminate()
    _login.update(state="idle", code="")
    return _login_state()


# ---- リポジトリとブランチ ----
def owners(q: dict) -> dict:
    """新しいリポジトリを作れる所（自分と、所属する組織）。"""
    user = q.get("user", "")
    orgs = json.loads(_gh("api", "user/orgs", "--paginate", user=user) or "[]")
    return {"owners": [user] + [o["login"] for o in orgs]}


def repos(q: dict) -> dict:
    user = q.get("user", "")
    out = _gh("api", "user/repos?per_page=100&sort=updated&affiliation=owner,collaborator,organization_member",
              "--paginate", "--jq", ".[] | {full_name, private, default_branch, updated_at, description}", user=user,
              timeout=120)
    items = [json.loads(l) for l in out.splitlines() if l.strip()]
    return {"repos": items}


def create_repo(body: dict) -> dict:
    user, owner, name = body.get("user", ""), body.get("owner", ""), str(body.get("name", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
        raise GhError("リポジトリの名前は英数字と - _ . だけ（日本語は使えない）")
    path = "user/repos" if owner == user else f"orgs/{owner}/repos"
    priv = "true" if body.get("private", True) else "false"
    r = json.loads(_gh("api", "-X", "POST", path, "-f", f"name={name}", "-F", f"private={priv}",
                       "-f", f"description={body.get('description', '')}", user=user))
    return {"full_name": r["full_name"], "private": r["private"], "default_branch": r.get("default_branch") or "main"}


def branches(q: dict) -> dict:
    user, full = q.get("user", ""), q.get("repo", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", full):
        raise GhError("リポジトリを選ぶ")
    out = _gh("api", f"repos/{full}/branches?per_page=100", "--paginate", "--jq", ".[].name", user=user)
    info = json.loads(_gh("api", f"repos/{full}", user=user))
    return {"branches": [b for b in out.splitlines() if b], "default": info.get("default_branch") or "main",
            "private": info.get("private", True), "empty": info.get("size", 0) == 0 and not out.strip()}


# ---- リポジトリとブランチの管理（名前・公開／非公開・既定のブランチ・ブランチ・削除）----
FULL = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
BRANCH = re.compile(r"[A-Za-z0-9._/\-]+")


def _repo(body: dict) -> tuple[str, str]:
    user, full = str(body.get("user", "")), str(body.get("repo", ""))
    if not user or not FULL.fullmatch(full):
        raise GhError("アカウントとリポジトリを選ぶ")
    return user, full


def _branch(name: str) -> str:
    name = str(name or "").strip()
    if not BRANCH.fullmatch(name) or name.startswith(("-", "/")) or name.endswith("/") or ".." in name:
        raise GhError("ブランチの名前に使えない文字がある（英数字と - _ . /）")
    return name


def repo_info(q: dict) -> dict:
    user, full = _repo(q)
    r = json.loads(_gh("api", f"repos/{full}", user=user))
    names = _gh("api", f"repos/{full}/branches?per_page=100", "--paginate", "--jq", ".[].name", user=user)
    return {"full_name": r["full_name"], "private": r["private"], "default_branch": r.get("default_branch") or "",
            "branches": [b for b in names.splitlines() if b], "html_url": r.get("html_url", ""),
            "can_admin": bool((r.get("permissions") or {}).get("admin"))}


def repo_update(body: dict) -> dict:
    """名前の変更・公開／非公開・既定のブランチ（PATCH repos/{owner}/{repo}）。"""
    user, full = _repo(body)
    args = ["api", "-X", "PATCH", f"repos/{full}"]
    if body.get("name"):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", body["name"]):
            raise GhError("リポジトリの名前は英数字と - _ . だけ（日本語は使えない）")
        args += ["-f", f"name={body['name']}"]
    if "private" in body:
        args += ["-F", f"private={'true' if body['private'] else 'false'}"]
    if body.get("default_branch"):
        args += ["-f", f"default_branch={_branch(body['default_branch'])}"]
    r = json.loads(_gh(*args, user=user))
    return {"full_name": r["full_name"], "private": r["private"], "default_branch": r.get("default_branch")}


def branch_create(body: dict) -> dict:
    user, full = _repo(body)
    name, base = _branch(body.get("name")), _branch(body.get("from") or "main")
    sha = _gh("api", f"repos/{full}/git/ref/heads/{quote(base, safe='/')}", "--jq", ".object.sha", user=user).strip()
    _gh("api", "-X", "POST", f"repos/{full}/git/refs", "-f", f"ref=refs/heads/{name}", "-f", f"sha={sha}", user=user)
    return repo_info(body)


def branch_rename(body: dict) -> dict:
    user, full = _repo(body)
    old, new = _branch(body.get("branch")), _branch(body.get("name"))
    _gh("api", "-X", "POST", f"repos/{full}/branches/{quote(old, safe='')}/rename", "-f", f"new_name={new}", user=user)
    return repo_info(body)


def branch_delete(body: dict) -> dict:
    user, full = _repo(body)
    name = _branch(body.get("branch"))
    _gh("api", "-X", "DELETE", f"repos/{full}/git/refs/heads/{quote(name, safe='/')}", user=user)
    return repo_info(body)


def repo_delete(body: dict) -> dict:
    """リポジトリを削除する。GitHub と同じく、owner/repo を正確に打ち込んだときだけ。delete_repo の権限が要る。"""
    user, full = _repo(body)
    if str(body.get("confirm", "")).strip() != full:
        raise GhError(f"確認の欄に {full} と正確に打ち込む")
    scopes = next((a["scopes"] for a in accounts().get("accounts", []) if a["login"] == user), "")
    if "delete_repo" not in scopes:
        raise GhError("NEED_DELETE_SCOPE")
    _gh("api", "-X", "DELETE", f"repos/{full}", user=user)
    return {"deleted": full}


def user_info(user: str) -> dict:
    return json.loads(_gh("api", "user", user=user))


# ---- 共同編集者（持ち主の側）と、届いた招待（相手の側）----
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


def collaborators(q: dict) -> dict:
    """参加している人と、招待中の人。"""
    user, full = _repo(q)
    people = json.loads(_gh("api", f"repos/{full}/collaborators?affiliation=direct&per_page=100", user=user))
    invites = json.loads(_gh("api", f"repos/{full}/invitations?per_page=100", user=user))
    perm = lambda p: "編集できる" if p in ("write", "push", "admin", "maintain") or (isinstance(p, dict) and p.get("push")) else "見るだけ"
    return {"people": [{"login": u["login"], "avatar": u.get("avatar_url", ""), "perm": perm(u.get("permissions") or {}),
                        "admin": bool((u.get("permissions") or {}).get("admin"))} for u in people],
            "invites": [{"id": i["id"], "login": (i.get("invitee") or {}).get("login", ""), "avatar": (i.get("invitee") or {}).get("avatar_url", ""),
                         "perm": perm(i.get("permissions")), "created": i.get("created_at", "")} for i in invites],
            "invite_url": f"https://github.com/{full}/invitations"}


def find_users(q: dict) -> dict:
    """GitHub のユーザーを名前で探す（招待する相手を選ぶ）。"""
    user, name = q.get("user", ""), str(q.get("q", "")).strip()
    if not name:
        return {"users": []}
    out = []
    if _LOGIN.fullmatch(name):   # ちょうどその名前の人を先に
        try:
            u = json.loads(_gh("api", f"users/{name}", user=user))
            out.append({"login": u["login"], "name": u.get("name") or "", "avatar": u.get("avatar_url", "")})
        except GhError:
            pass
    try:
        r = json.loads(_gh("api", "-X", "GET", "search/users", "-f", f"q={name} in:login", "-f", "per_page=8", user=user))
        out += [{"login": u["login"], "name": "", "avatar": u.get("avatar_url", "")} for u in r.get("items", [])
                if u["login"].lower() not in {x["login"].lower() for x in out}]
    except GhError:
        pass
    return {"users": out[:8]}


def collab_invite(body: dict) -> dict:
    user, full = _repo(body)
    who = str(body.get("login", "")).strip().lstrip("@")
    if not _LOGIN.fullmatch(who):
        raise GhError("GitHub のユーザー名が正しくない")
    if who.lower() == user.lower():
        raise GhError("自分は招待できない")
    perm = "push" if body.get("perm", "push") == "push" else "pull"
    _gh("api", "-X", "PUT", f"repos/{full}/collaborators/{who}", "-f", f"permission={perm}", user=user)
    return collaborators({"user": user, "repo": full})


def collab_remove(body: dict) -> dict:
    """参加している人を外す。招待中なら招待を取り消す。"""
    user, full = _repo(body)
    if body.get("invite_id"):
        _gh("api", "-X", "DELETE", f"repos/{full}/invitations/{int(body['invite_id'])}", user=user)
    else:
        who = str(body.get("login", ""))
        if not _LOGIN.fullmatch(who):
            raise GhError("GitHub のユーザー名が正しくない")
        _gh("api", "-X", "DELETE", f"repos/{full}/collaborators/{who}", user=user)
    return collaborators({"user": user, "repo": full})


def invitations(q: dict) -> dict:
    """自分に届いている、リポジトリへの招待。"""
    user = q.get("user", "")
    r = json.loads(_gh("api", "user/repository_invitations?per_page=100", user=user))
    return {"invites": [{"id": i["id"], "repo": i["repository"]["full_name"], "private": i["repository"].get("private", True),
                         "from": (i.get("inviter") or {}).get("login", ""), "created": i.get("created_at", ""),
                         "description": i["repository"].get("description") or ""} for i in r]}


def invitation_answer(body: dict) -> dict:
    user, iid = body.get("user", ""), int(body.get("id", 0))
    _gh("api", "-X", "PATCH" if body.get("accept", True) else "DELETE", f"user/repository_invitations/{iid}", user=user)
    return invitations({"user": user})


GET = {"accounts": accounts, "owners": owners, "repos": repos, "branches": branches,
       "collaborators": collaborators, "users": find_users, "invitations": invitations}
GET["repo"] = repo_info
POST = {"install": install_gh, "login": login_start, "refresh": refresh_start, "login_cancel": login_cancel,
        "logout": logout, "create": create_repo, "update": repo_update, "branch_create": branch_create,
        "branch_rename": branch_rename, "branch_delete": branch_delete, "delete": repo_delete,
        "invite": collab_invite, "uninvite": collab_remove, "answer": invitation_answer}
