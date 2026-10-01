"""画面の裏で動く本体。ワークスペースの置き場（data）と、開いている原稿（複数）を持ち、画面の要求を処理する。

HTTP の受け口は server.py。画面とのやり取りでは、パスはすべて data（または原稿のフォルダ）からの
相対パスで渡し、絶対パスは出さない。書き換えられるのは開いた原稿の、data の1段目のフォルダの中だけ。

原稿はブラウザのタブごとに開ける（タブの URL の ?p= が原稿）。原稿を見ているタブが無くなったら、
その原稿の組版を止める。タブは状態の問い合わせにタブの番号（t）を付けてくるので、それで見ているかを数える。
"""
from __future__ import annotations

import itertools
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from . import comments, pandoc, sync
from .chats import ChatTabs
from .builder import Watcher
from .history import History
from .overleaf import export_zip, import_zip
from .project import ProjectError, browse, edit_root, is_main, list_folders, list_tree, rename_to_tex, search_tree
from .search import search

# serve が原稿を開いている間、原稿のフォルダに置く印（check が、組んでいるサーバを見つけるため）
STATE_FILE = ".overleaf-compiler-serve.json"
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')
VIEWER_TIMEOUT = 30   # この秒数だけ問い合わせの無いタブは、もう見ていないとみなす
OPEN_GRACE = 60       # 開いてからこの秒数は、見ているタブが無くても組版を止めない（起動直後・開き直し）
_ids = itertools.count(1)


def _safe_name(name: str, fallback: str = "") -> str:
    name = _BAD_NAME.sub("_", name).strip().lstrip(".")
    return name or fallback


class Project:
    """開いている原稿1つ。組版の常駐（Watcher）と変更履歴を持ち、エディタの要求を処理する。"""

    def __init__(self, tex: Path, data: Path, port: int):
        self.tex, self.data = tex, data
        self.session = next(_ids)     # 開くたびに変わる番号。画面はこれが変わったら作り直す
        self.opened = time.monotonic()
        self.viewers: dict[str, float] = {}   # 見ているタブの番号 → 最後に問い合わせた時刻
        self.history = History(tex.parent)
        self.watcher = Watcher(tex)
        self.watcher.on_change = self._outside_changed
        self.watcher.start()
        self.chats = ChatTabs(tex, revert=self.revert_since)   # 右のチャット欄のタブ（Claude Code・Codex）
        (tex.parent / STATE_FILE).write_text(json.dumps({"pid": os.getpid(), "port": port, "main": tex.name}))
        # まだ履歴に無いファイルは、今の中身を最初の版として残す（裏で）
        files = [tex.parent / f["path"] for f in list_tree(tex) if not f["dir"]]
        threading.Thread(target=self.history.baseline, args=(files,), daemon=True).start()

    def stop(self) -> None:
        self.watcher.stop()
        self.chats.close_all()
        (self.tex.parent / STATE_FILE).unlink(missing_ok=True)

    def seen(self, tab: str | None) -> None:
        if tab:
            self.viewers[tab] = time.monotonic()

    def watched(self) -> bool:
        now = time.monotonic()
        self.viewers = {t: s for t, s in self.viewers.items() if now - s < VIEWER_TIMEOUT}
        return bool(self.viewers) or now - self.opened < OPEN_GRACE

    # ---- 範囲 ----
    @property
    def root(self) -> Path:
        """書き換えてよい範囲（project.edit_root）。"""
        return edit_root(self.tex, self.data)

    def _proj(self) -> Path:
        return self.tex.parent

    def _path(self, rel: str) -> Path:
        """原稿のフォルダからの相対パス（ツリーやタブのパス）を、書き換えてよい範囲の中のパスにする。"""
        p = Path(rel)
        return sync.inside(p if p.is_absolute() else self._proj() / p, self.root)

    def _rel(self, p: Path) -> str:
        base = self._proj()
        return str(p.relative_to(base)) if p.is_relative_to(base) else os.path.relpath(p, base)

    def _in_proj(self, rel: str) -> Path:
        """ファイル操作（作成・削除・名前変更）は原稿のフォルダの中だけ。"""
        p = (self._proj() / rel).resolve()
        if p != self._proj() and self._proj() not in p.parents:
            raise sync.SyncError(f"{rel} は原稿のフォルダの外")
        return p

    def info(self, start: str) -> dict:
        t = self.tex
        rel = str(t.relative_to(self.data)) if t.is_relative_to(self.data) else t.name
        return {"session": self.session, "start": start, "main": t.name, "rel": rel,
                "has_pandoc": pandoc.available(),
                # VS Code で開くためだけに使う。画面には出さない
                "vscode_dir": str(t.parent)}

    # ---- エディタ ----
    def tree(self, _=None) -> dict:
        return {"main": self.tex.name, "files": list_tree(self.tex)}

    def read(self, q: dict) -> dict:
        p = self._path(q["path"])
        return {"path": self._rel(p), **sync.read_file(p, self.root)}

    def write(self, body: dict) -> dict:
        p = self._path(body["path"])
        try:
            r = {"path": self._rel(p), **sync.write_file(p, body["text"], body.get("mtime"), self.root)}
        except sync.Conflict as c:  # 外で直されていた。今の内容を返し、画面に選ばせる
            return {"conflict": True, "path": self._rel(p), "text": c.text, "mtime": c.mtime}
        self._record(p, "browser")
        self.watcher.poke()   # 更新の確認を待たずに組み始める
        return r

    def _record(self, p: Path, kind: str) -> None:
        if p.is_file() and p.is_relative_to(self._proj()):
            self.history.record(str(p.relative_to(self._proj())), p.read_bytes(), kind)

    def _outside_changed(self, paths: list[Path]) -> None:
        """組版の常駐が見つけた、外（VS Code・Claude Code）での変更を履歴に残す。"""
        for p in paths:
            if p.is_file() and p.stat().st_size < 4 * 1024 * 1024:
                self._record(p, "outside")

    def status(self, q=None) -> dict:
        st = {"session": self.session, "open": True, **self.watcher.status(),
              "comments_mtime": comments.mtime(self.tex)}
        # 開いているタブのファイルの更新時刻。外（VS Code など）で直されたら画面が読み直す
        if q and q.get("files"):
            st["mtimes"] = {}
            for rel in q["files"].split("\n"):
                try:
                    f = self._path(rel)
                    if f.is_file():
                        st["mtimes"][rel] = sync.mtime(f)
                except sync.SyncError:
                    pass
        return st

    def goto_source(self, q: dict) -> dict:
        """PDF の位置 → ソースのファイルと行（PDF をダブルクリックしたとき、← ボタン）。"""
        src, line = sync.pdf_to_source(self.tex.with_suffix(".pdf"), int(q["page"]), float(q["x"]), float(q["y"]))
        src = sync.inside(src, self.root)
        if q.get("text"):
            line = sync.refine_line(src, line, q["text"], self.root)
        return {"path": self._rel(src), "line": line}

    def goto_pdf(self, q: dict) -> dict:
        """ソースの行 → PDF 上の位置（→ ボタン）。"""
        boxes = sync.source_to_pdf(self.tex.with_suffix(".pdf"), self._path(q["path"]), int(q["line"]))
        if not boxes:
            raise sync.SyncError("この行は PDF に出ていない（コメントや設定の行など）")
        return {"boxes": boxes}

    def replace(self, body: dict) -> dict:
        """PDF 上で選んだ文字列を書き換える（Overleaf には無い操作）。場所は SyncTeX で引く。"""
        src, line = sync.pdf_to_source(self.tex.with_suffix(".pdf"), int(body["page"]),
                                       float(body["x"]), float(body["y"]))
        src = sync.inside(src, self.root)
        r = sync.replace_in_source(src, line, body["old"], body["new"], self.root)
        self._record(src, "browser")
        self.watcher.poke()
        return {"path": self._rel(src), **r}

    def settle(self) -> dict:
        """呼ばれた時点までの変更を組み終えるまで待って状態を返す。待っている間にリコンパイルしたら、やり直した方を待つ。"""
        while True:
            w = self.watcher
            st = w.settle()
            if self.watcher is w:
                return st

    def recompile(self, _=None) -> dict:
        """最初から組み直す（latexmk -g）。"""
        old = self.watcher
        old.stop()
        self.watcher = Watcher(self.tex)
        self.watcher.on_change = old.on_change
        self.watcher.start()
        return {"ok": True}

    def raw(self, rel: str) -> tuple[bytes, str]:
        """画像などを、そのまま返す（ファイルツリーから開いたとき）。"""
        p = self._path(rel)
        if not p.is_file():
            raise sync.SyncError(f"{rel} が無い")
        return p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream"

    # ---- コメント（PDF に付ける。Acrobat の注釈に当たる）----
    def comments_list(self, _=None) -> dict:
        return {"comments": comments.list_comments(self.tex, self.root), "mtime": comments.mtime(self.tex)}

    def comment(self, body: dict) -> dict:
        """コメントの追加・編集・返信・解決・削除・取り込み。action で分ける。"""
        tex, act = self.tex, body["action"]
        if act == "add":
            return {"comment": comments.add(tex, self.root, body)}
        if act == "import":
            return comments.import_items(tex, self.root, body["items"])
        cid = body["id"]
        if act == "edit":
            return {"comment": comments.edit(tex, cid, body.get("text"), body.get("suggest"))}
        if act == "reply":
            return {"comment": comments.reply(tex, cid, body.get("author", ""), body.get("text", ""))}
        if act in ("resolve", "reopen"):
            return {"comment": comments.set_status(tex, cid, "resolved" if act == "resolve" else "open",
                                                   body.get("author", ""))}
        if act == "delete":
            return {"comment": comments.delete(tex, cid)}
        raise sync.SyncError(f"{act} はできない")

    # ---- ファイル操作（Overleaf の「新規ファイル」「新規フォルダ」「アップロード」と ⋮ のメニュー）----
    def newfile(self, body: dict) -> dict:
        p = self._in_proj(body["path"])
        if p.exists():
            raise sync.SyncError(f"{body['path']} は既にある")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        self._record(p, "new")
        return {"path": self._rel(p)}

    def newfolder(self, body: dict) -> dict:
        p = self._in_proj(body["path"])
        if p.exists():
            raise sync.SyncError(f"{body['path']} は既にある")
        p.mkdir(parents=True)
        return {"path": self._rel(p)}

    def upload(self, q: dict, data: bytes) -> dict:
        name = _safe_name(q.get("name", ""))
        if not name:
            raise sync.SyncError("ファイル名が空")
        p = self._in_proj(str(Path(q.get("dir", "")) / name))
        if p.exists() and q.get("overwrite") != "1":
            raise sync.SyncError("EXISTS")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self._record(p, "upload")
        self.watcher.poke()
        return {"path": self._rel(p)}

    def rename_file(self, body: dict) -> dict:
        src, dst = self._in_proj(body["from"]), self._in_proj(body["to"])
        if not src.exists():
            raise sync.SyncError(f"{body['from']} が無い")
        if dst.exists():
            raise sync.SyncError(f"{body['to']} は既にある")
        if src == self.tex:
            raise sync.SyncError("主文書の名前は変えない（Overleaf の設定と合わなくなる）")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            self.history.record(self._rel(src), src.read_bytes(), "delete")
        src.rename(dst)
        self._record(dst, "rename")
        return {"path": self._rel(dst)}

    def delete(self, body: dict) -> dict:
        """消す前に中身を履歴に残す（履歴から戻せる）。フォルダは中のファイルを全部残してから消す。"""
        p = self._in_proj(body["path"])
        if p == self._proj() or p == self.tex:
            raise sync.SyncError("原稿のフォルダと主文書は消せない")
        if not p.exists():
            raise sync.SyncError(f"{body['path']} が無い")
        files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
        for f in files:
            if f.stat().st_size < 50 * 1024 * 1024:
                self.history.record(self._rel(f), f.read_bytes(), "delete")
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        return {"deleted": len(files)}

    # ---- 検索・文字数・履歴 ----
    def search(self, q: dict) -> dict:
        files = [f["path"] for f in list_tree(self.tex) if not f["dir"] and f["editable"]]
        return search(self._proj(), files, q.get("q", ""), q.get("case") == "1", q.get("regex") == "1",
                      q.get("word") == "1")

    def wordcount(self, _=None) -> dict:
        r = subprocess.run(["texcount", "-inc", "-utf8", "-japanese", "-sum", "-merge", self.tex.name],
                           cwd=self.tex.parent, capture_output=True, text=True, errors="replace")
        text = r.stdout.strip()
        m = re.search(r"Sum count: (\d+)", text)
        return {"sum": int(m.group(1)) if m else None, "text": text}

    def history_list(self, q: dict) -> dict:
        return {"entries": self.history.list(q.get("path") or None)}

    def history_diff(self, q: dict) -> dict:
        return self.history.diff(q["id"])

    def history_view(self, q: dict) -> dict:
        """履歴の画面：その版のファイル全体と、1つ前の版との違い。"""
        return self.history.view(q["id"])

    def history_label(self, body: dict) -> dict:
        e = self.history.set_label(body["id"], (body.get("name") or "").strip() or None)
        return {"entry": {k: e[k] for k in ("id", "path", "time")}, "labels": e.get("labels", [])}

    def history_restore(self, body: dict) -> dict:
        """その版の中身に戻す（今の中身も履歴に残るので、戻したことも取り消せる）。"""
        e = self.history.find(body["id"])
        if body.get("before"):   # 「この変更の前に戻す」＝1つ前の版に戻す
            prev = self.history._prev(e)
            if not prev:
                raise sync.SyncError("この版より前の版が無い（このとき新しく作られたファイル）")
            e = prev
        data = self.history.blob(e)
        if data is None:
            raise sync.SyncError("この版には中身が無い")
        p = self._in_proj(e["path"])
        if p.is_file():
            self._record(p, "outside")   # 戻す前の中身も残しておく
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".overleaf-compiler-tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
        self.history.record(e["path"], data, "restore")
        self.watcher.poke()
        return {"path": e["path"]}

    def revert_since(self, t: float) -> list[str]:
        """時刻 t より後に外（Codex・VS Code など）で変わったファイルを、t の直前の版に戻す（チャット欄の巻き戻し）。
        ブラウザで直した分は戻さない。戻す前の中身も履歴に残るので、戻したことも取り消せる。"""
        changed = {e["path"] for e in self.history.entries if e["time"] > t and e["kind"] == "outside"}
        done = []
        for rel in sorted(changed):
            before = next((e for e in reversed(self.history.entries) if e["path"] == rel and e["time"] <= t), None)
            try:
                p = self._in_proj(rel)
            except sync.SyncError:
                continue
            if before is None:   # t のあとに作られたファイル。中身を履歴に残してから消す
                if p.is_file():
                    self._record(p, "outside")
                    self.history.record(rel, None, "delete")
                    p.unlink()
                    done.append(rel)
                continue
            data = self.history.blob(before)
            if data is None or (p.is_file() and p.read_bytes() == data):
                continue
            if p.is_file():
                self._record(p, "outside")
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".overleaf-compiler-tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
            self.history.record(rel, data, "restore")
            done.append(rel)
        if done:
            self.watcher.poke()
        return done

    # ---- 原稿の複製（Overleaf の Make a copy）----
    def copy_project(self, body: dict) -> dict:
        """原稿のフォルダを、同じ階層に別の名前で写す。組版の中間生成物と印のファイルは写さない。"""
        name = _safe_name(body.get("name", "")) or f"{self._proj().name}_コピー"
        dest = self._proj().parent / name
        if dest.exists():
            raise sync.SyncError(f"{name} は既にある")
        skip = shutil.ignore_patterns(STATE_FILE, "*.aux", "*.log", "*.fls", "*.fdb_latexmk", "*.synctex.gz", "*.dvi",
                                      "*.bbl", "*.blg", "*.bcf", "*.run.xml", "*.out", "*.toc", "*.xdv", ".git")
        shutil.copytree(self._proj(), dest, ignore=skip)
        return {"tex": str((dest / self.tex.name).relative_to(self.data))}

    # ---- ダウンロード ----
    def export(self, fmt: str) -> tuple[str, bytes, str]:
        tex = self.tex
        if fmt == "comments":
            md = comments.to_markdown(comments.list_comments(tex, self.root), tex.name)
            return f"{tex.stem}_コメント.md", md.encode(), "text/markdown; charset=utf-8"
        if fmt == "zip":
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / f"{tex.parent.name}_overleaf.zip"
                export_zip(tex.parent, out)
                return out.name, out.read_bytes(), "application/zip"
        return pandoc.export(tex, fmt)   # Word・Markdown・HTML


class App:
    """ワークスペースの置き場（data）と、開いている原稿（主文書のパス → Project）を持つ。"""

    def __init__(self, data: Path, port: int = 0, start: str = ""):
        self.data = data.resolve()
        self.port = port
        self.start = start            # 一覧画面で最初に開くフォルダ（data からの相対パス）
        self.projects: dict[Path, Project] = {}
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        threading.Thread(target=self._janitor, daemon=True).start()

    def _data_path(self, rel: str) -> Path:
        p = (self.data / rel).resolve() if rel else self.data
        if p != self.data and self.data not in p.parents:
            raise ProjectError(f"{rel} は data の外")
        return p

    # ---- どの原稿の要求か（画面は ?p= に data からの主文書の相対パスを付けてくる）----
    def project(self, q: dict | None) -> Project:
        rel = (q or {}).get("p")
        if not rel:
            raise sync.SyncError("原稿が開かれていない")
        pr = self.projects.get(self._data_path(rel))
        if not pr:
            raise sync.SyncError("原稿が開かれていない")
        pr.seen((q or {}).get("t"))
        return pr

    # ---- 一覧画面 ----
    def browse(self, q: dict) -> dict:
        if q.get("q", "").strip():   # 絞り込み：そのフォルダの下の階層をすべて探す
            return search_tree(self.data, q.get("path", ""), q["q"].strip())
        return browse(self.data, q.get("path", ""))

    # ---- 一覧の項目の ⋮（ダウンロード・名前の変更・削除）----
    def _item(self, rel: str) -> Path:
        p = self._data_path(rel)
        if p == self.data or not p.is_dir():
            raise sync.SyncError(f"{rel} は扱えない")
        return p

    def _close_inside(self, p: Path) -> None:
        """そのフォルダの中で開いている原稿を閉じる（組版を止める）。"""
        with self._lock:
            for pr in [pr for t, pr in self.projects.items() if t.is_relative_to(p)]:
                self._drop(pr)

    def item_zip(self, q: dict) -> tuple[str, bytes, str]:
        """原稿なら Overleaf に入れられる zip（組んだ PDF・中間生成物を除く）、ただのフォルダなら中身をそのまま zip にする。"""
        p = self._item(q.get("path", ""))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{p.name}.zip"
            if [t for t in p.glob("*.tex") if is_main(t)]:
                export_zip(p, out)
            else:
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(p.rglob("*")):
                        rel = f.relative_to(p)
                        if f.is_file() and not any(x.startswith(".") for x in rel.parts):
                            z.write(f, (Path(p.name) / rel).as_posix())
            return out.name, out.read_bytes(), "application/zip"

    def item_rename(self, body: dict) -> dict:
        p = self._item(body.get("path", ""))
        name = _safe_name(body.get("name", ""))
        if not name:
            raise sync.SyncError("名前が空")
        dest = p.parent / name
        if dest.exists():
            raise sync.SyncError(f"{name} は既にある")
        projects = [Path(f["dir"]) for f in list_folders(p) if f["mains"]] + ([Path(".")] if list(p.glob("*.tex")) else [])
        self._close_inside(p)
        p.rename(dest)
        for rel in projects:   # 中の原稿の変更履歴も新しい場所へ引き継ぐ
            History.move(p / rel, dest / rel)
        return {"path": str(dest.relative_to(self.data))}

    def item_delete(self, body: dict) -> dict:
        """ごみ箱へ移す（gio trash。ファイルマネージャのごみ箱から戻せる）。"""
        p = self._item(body.get("path", ""))
        self._close_inside(p)
        if shutil.which("gio") and subprocess.run(["gio", "trash", str(p)], capture_output=True).returncode == 0:
            return {"trash": True}
        trash = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Trash"
        (trash / "files").mkdir(parents=True, exist_ok=True)
        (trash / "info").mkdir(parents=True, exist_ok=True)
        dest, n = trash / "files" / p.name, 2
        while dest.exists():
            dest, n = trash / "files" / f"{p.name}.{n}", n + 1
        (trash / "info" / f"{dest.name}.trashinfo").write_text(
            f"[Trash Info]\nPath={p}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
        shutil.move(str(p), dest)
        return {"trash": True}

    # ---- 取り込む元を選ぶ窓（ホームフォルダの中。最初はダウンロード）----
    @staticmethod
    def _downloads() -> Path:
        try:
            d = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3).stdout.strip()
            if d and Path(d).is_dir():
                return Path(d)
        except (OSError, subprocess.SubprocessError):
            pass
        return Path.home() / "Downloads" if (Path.home() / "Downloads").is_dir() else Path.home()

    def _in_home(self, path: str) -> Path:
        home = Path.home().resolve()
        p = Path(path).expanduser().resolve() if path else self._downloads().resolve()
        if p != home and home not in p.parents:
            raise sync.SyncError("ホームフォルダの外は選べない")
        return p

    def fs_list(self, q: dict) -> dict:
        p = self._in_home(q.get("dir", ""))
        if not p.is_dir():
            raise sync.SyncError(f"{p.name} はフォルダではない")
        home = Path.home().resolve()
        entries = []
        for c in p.iterdir():
            if c.name.startswith("."):
                continue
            try:
                if c.is_dir():
                    tex = [t for t in list(c.glob("*.tex"))[:40] if is_main(t)]
                    entries.append({"name": c.name, "path": str(c), "kind": "dir", "project": bool(tex),
                                    "main": tex[0].name if tex else "", "mtime": c.stat().st_mtime})
                elif c.suffix.lower() == ".zip":
                    entries.append({"name": c.name, "path": str(c), "kind": "zip", "size": c.stat().st_size,
                                    "mtime": c.stat().st_mtime})
            except OSError:
                continue
        entries.sort(key=lambda e: -e["mtime"])   # ダウンロードは新しいものから
        rel = "~" if p == home else "~/" + str(p.relative_to(home))
        return {"dir": str(p), "label": rel, "parent": str(p.parent) if p != home else None,
                "downloads": str(self._downloads()), "home": str(home), "entries": entries}

    def fs_import(self, body: dict) -> dict:
        """選んだ zip を展開する、または展開済みのフォルダを写して取り込む（一覧で開いているフォルダへ）。"""
        src = self._in_home(body.get("src", ""))
        if src == self.data or self.data in src.parents or src in self.data.parents:
            raise sync.SyncError("data の中のものは取り込めない（もう一覧にある）")
        base = self._data_path(body.get("path", ""))
        if src.is_file() and src.suffix.lower() == ".zip":
            return self.import_(body.get("path", ""), src.name, src.read_bytes())
        if not src.is_dir():
            raise sync.SyncError(f"{src.name} は zip でもフォルダでもない")
        stem = _safe_name(src.name, "overleaf")
        dest, n = base / stem, 2
        while dest.exists():
            dest, n = base / f"{stem}_{n}", n + 1
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
        mains = [t for t in dest.rglob("*.tex") if is_main(t)]
        return {"dir": str(dest.relative_to(self.data)), "mains": len(mains)}

    def mkdir(self, body: dict) -> dict:
        name = _safe_name(body.get("name", ""))
        if not name:
            raise sync.SyncError("名前が空")
        d = self._data_path(body.get("path", "")) / name
        if d.exists():
            raise sync.SyncError(f"{name} は既にある")
        d.mkdir(parents=True)
        return {"path": str(d.relative_to(self.data))}

    def import_(self, path: str, name: str, data: bytes) -> dict:
        """ブラウザから受け取った zip を、一覧で開いているフォルダに展開する。同名があれば _2, _3 … を付ける。"""
        base = self._data_path(path)
        stem = _safe_name(Path(name).stem, "overleaf")
        dest, n = base / stem, 2
        while dest.exists():
            dest, n = base / f"{stem}_{n}", n + 1
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
            tmp.write(data)
            tmp.flush()
            mains = import_zip(Path(tmp.name), dest)
        return {"dir": str(dest.relative_to(self.data)), "mains": len(mains)}

    def rename_txt(self, body: dict) -> dict:
        p = self._data_path(body["file"])
        top = self.data / p.relative_to(self.data).parts[0]
        return {"tex": str(rename_to_tex(p, top).relative_to(self.data))}

    # ---- 原稿を開く・閉じる ----
    def open(self, tex: Path, tab: str | None = None) -> Project:
        """原稿を開く。既に開いていれば（別のタブが見ている）、同じものを使う。"""
        tex = tex.resolve()
        if tex.suffix != ".tex" or not tex.is_file():
            raise sync.SyncError(f"{tex.name} は開けない")
        with self._lock:
            pr = self.projects.get(tex)
            if not pr:
                pr = self.projects[tex] = Project(tex, self.data, self.port)
            pr.seen(tab)
            return pr

    def open_api(self, body: dict) -> dict:
        return self.open(self._data_path(body["tex"]), body.get("t")).info(self.start)

    def close_tex(self, q: dict) -> dict:
        """タブが原稿を閉じた（一覧へ戻った）。ほかに見ているタブが無ければ組版を止める。"""
        with self._lock:
            rel = q.get("p")
            pr = self.projects.get(self._data_path(rel)) if rel else None
            if pr:
                pr.viewers.pop(q.get("t"), None)
                pr.opened = 0   # 開いた直後の猶予も終わりにする
                if not pr.watched():
                    self._drop(pr)
        return self.info({})

    def rename_project(self, q: dict, body: dict) -> dict:
        """原稿のフォルダの名前を変える（Overleaf の Rename）。組版を止めてから名前を変え、新しい名前で開き直す。"""
        name = _safe_name(body.get("name", ""))
        if not name:
            raise sync.SyncError("名前が空")
        with self._lock:
            pr = self.project(q)
            old = pr.tex.parent
            dest = old.parent / name
            if dest.exists():
                raise sync.SyncError(f"{name} は既にある")
            self._drop(pr)
            old.rename(dest)
            History.move(old, dest)   # 変更履歴も新しい名前へ引き継ぐ
        return self.open(dest / pr.tex.name, q.get("t")).info(self.start)

    def _drop(self, pr: Project) -> None:
        pr.stop()
        self.projects.pop(pr.tex, None)

    def _janitor(self) -> None:
        """見ているタブが無くなった原稿（タブを閉じた）の組版を止める。"""
        while not self._stopping.wait(10):
            with self._lock:
                for pr in [p for p in self.projects.values() if not p.watched()]:
                    self._drop(pr)

    def shutdown(self) -> None:
        self._stopping.set()
        with self._lock:
            for pr in list(self.projects.values()):
                self._drop(pr)

    def info(self, q: dict) -> dict:
        try:
            return self.project(q).info(self.start)
        except (sync.SyncError, ProjectError):
            return {"session": 0, "start": self.start, "main": None, "rel": None,
                    "has_pandoc": pandoc.available(), "vscode_dir": None}

    def status(self, q: dict) -> dict:
        try:
            return self.project(q).status(q)
        except (sync.SyncError, ProjectError):
            return {"session": 0, "open": False}

    def settle(self, body: dict) -> dict:
        """check から呼ばれる。body の原稿を組んでいれば、呼ばれた時点までの変更を組み終えるまで待って状態を返す。

        その原稿を開いていない（組んでいない）なら NOT_SERVING。check はそのとき自分で組む。
        """
        pr = self.projects.get(Path(body["tex"]).resolve())
        if not pr:
            raise sync.SyncError("NOT_SERVING")
        if body.get("wait") is False:   # 組んでいるかどうかだけを知りたい（build・clean）
            return pr.watcher.status()
        return pr.settle()
