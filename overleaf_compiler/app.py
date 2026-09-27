"""画面の裏で動く本体。ワークスペースの置き場（data）と、いま開いている原稿を持ち、画面の要求を処理する。

HTTP の受け口は server.py。画面とのやり取りでは、パスはすべて data（または原稿のフォルダ）からの
相対パスで渡し、絶対パスは出さない。書き換えられるのは開いた原稿の、data の1段目のフォルダの中だけ。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from . import comments, pandoc, sync
from .builder import Watcher
from .history import History
from .overleaf import export_zip, import_zip
from .project import ProjectError, browse, edit_root, list_tree, rename_to_tex
from .search import search

# serve が原稿を開いている間、原稿のフォルダに置く印（check が、組んでいるサーバを見つけるため）
STATE_FILE = ".overleaf-compiler-serve.json"
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')


def _safe_name(name: str, fallback: str = "") -> str:
    name = _BAD_NAME.sub("_", name).strip().lstrip(".")
    return name or fallback


class App:
    """ワークスペースの置き場（data）と、いま開いている原稿（tex）を持つ。"""

    def __init__(self, data: Path, port: int = 0, start: str = ""):
        self.data = data.resolve()
        self.port = port
        self.start = start            # 一覧画面で最初に開くフォルダ（data からの相対パス）
        self.tex: Path | None = None
        self.watcher: Watcher | None = None
        self.history: History | None = None
        self.session = 0              # 原稿を開く・閉じるたびに増える。画面はこれで読み直す
        self._lock = threading.Lock()

    # ---- 範囲 ----
    @property
    def root(self) -> Path:
        """書き換えてよい範囲（project.edit_root）。"""
        return edit_root(self._need(), self.data)

    def _need(self) -> Path:
        if not self.tex:
            raise sync.SyncError("原稿が開かれていない")
        return self.tex

    def _proj(self) -> Path:
        return self._need().parent

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

    def _data_path(self, rel: str) -> Path:
        p = (self.data / rel).resolve() if rel else self.data
        if p != self.data and self.data not in p.parents:
            raise ProjectError(f"{rel} は data の外")
        return p

    # ---- 一覧画面 ----
    def browse(self, q: dict) -> dict:
        return browse(self.data, q.get("path", ""))

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
    def open(self, tex: Path) -> None:
        tex = tex.resolve()
        if tex.suffix != ".tex" or not tex.is_file():
            raise sync.SyncError(f"{tex.name} は開けない")
        with self._lock:
            self._close()
            self.tex, self.watcher = tex, Watcher(tex)
            self.history = History(tex.parent)
            self.watcher.on_change = self._outside_changed
            self.watcher.start()
            self.session += 1
            (tex.parent / STATE_FILE).write_text(
                json.dumps({"pid": os.getpid(), "port": self.port, "main": tex.name}))
        # まだ履歴に無いファイルは、今の中身を最初の版として残す（裏で）
        files = [tex.parent / f["path"] for f in list_tree(tex) if not f["dir"]]
        threading.Thread(target=self.history.baseline, args=(files,), daemon=True).start()

    def close_tex(self, _=None) -> dict:
        with self._lock:
            self._close()
            self.session += 1
        return self.info()

    def _close(self) -> None:
        if self.watcher:
            self.watcher.stop()
        if self.tex:
            (self.tex.parent / STATE_FILE).unlink(missing_ok=True)
        self.tex = self.watcher = self.history = None

    def shutdown(self) -> None:
        with self._lock:
            self._close()

    def info(self, _=None) -> dict:
        t = self.tex
        rel = None
        if t:
            rel = str(t.relative_to(self.data)) if t.is_relative_to(self.data) else t.name
        return {"session": self.session, "start": self.start, "main": t.name if t else None,
                "rel": rel, "has_pandoc": pandoc.available(),
                # VS Code で開くためだけに使う。画面には出さない
                "vscode_dir": str(t.parent) if t else None}

    # ---- エディタ ----
    def tree(self, _=None) -> dict:
        return {"main": self._need().name, "files": list_tree(self._need())}

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
        if self.watcher:
            self.watcher.poke()   # 更新の確認を待たずに組み始める
        return r

    def _record(self, p: Path, kind: str) -> None:
        if self.history and p.is_file() and p.is_relative_to(self._proj()):
            self.history.record(str(p.relative_to(self._proj())), p.read_bytes(), kind)

    def _outside_changed(self, paths: list[Path]) -> None:
        """組版の常駐が見つけた、外（VS Code・Claude Code）での変更を履歴に残す。"""
        for p in paths:
            if p.is_file() and p.stat().st_size < 4 * 1024 * 1024:
                self._record(p, "outside")

    def status(self, q=None) -> dict:
        if not self.watcher:
            return {"session": self.session, "open": False}
        st = {"session": self.session, "open": True, **self.watcher.status(),
              "comments_mtime": comments.mtime(self._need())}
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
        tex = self._need()
        src, line = sync.pdf_to_source(tex.with_suffix(".pdf"), int(q["page"]), float(q["x"]), float(q["y"]))
        src = sync.inside(src, self.root)
        if q.get("text"):
            line = sync.refine_line(src, line, q["text"], self.root)
        return {"path": self._rel(src), "line": line}

    def goto_pdf(self, q: dict) -> dict:
        """ソースの行 → PDF 上の位置（→ ボタン）。"""
        boxes = sync.source_to_pdf(self._need().with_suffix(".pdf"), self._path(q["path"]), int(q["line"]))
        if not boxes:
            raise sync.SyncError("この行は PDF に出ていない（コメントや設定の行など）")
        return {"boxes": boxes}

    def replace(self, body: dict) -> dict:
        """PDF 上で選んだ文字列を書き換える（Overleaf には無い操作）。場所は SyncTeX で引く。"""
        tex = self._need()
        src, line = sync.pdf_to_source(tex.with_suffix(".pdf"), int(body["page"]),
                                       float(body["x"]), float(body["y"]))
        src = sync.inside(src, self.root)
        r = sync.replace_in_source(src, line, body["old"], body["new"], self.root)
        self._record(src, "browser")
        if self.watcher:
            self.watcher.poke()
        return {"path": self._rel(src), **r}

    def settle(self, body: dict) -> dict:
        """check から呼ばれる。body の原稿を組んでいれば、呼ばれた時点までの変更を組み終えるまで待って状態を返す。

        別の原稿を開いている（組んでいない）なら NOT_SERVING。check はそのとき自分で組む。
        待っている間にリコンパイルで組版をやり直したら、やり直した方を待つ。
        """
        while True:
            w = self.watcher
            if not w or not self.tex or self.tex != Path(body["tex"]).resolve():
                raise sync.SyncError("NOT_SERVING")
            if body.get("wait") is False:   # 組んでいるかどうかだけを知りたい（build・clean）
                return w.status()
            st = w.settle()
            if self.watcher is w:
                return st

    def recompile(self, _=None) -> dict:
        """最初から組み直す（latexmk -g）。"""
        tex = self._need()
        with self._lock:
            on_change = self.watcher.on_change if self.watcher else None
            if self.watcher:
                self.watcher.stop()
            self.watcher = Watcher(tex)
            self.watcher.on_change = on_change
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
        tex = self._need()
        return {"comments": comments.list_comments(tex, self.root), "mtime": comments.mtime(tex)}

    def comment(self, body: dict) -> dict:
        """コメントの追加・編集・返信・解決・削除・取り込み。action で分ける。"""
        tex, act = self._need(), body["action"]
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
        if self.watcher:
            self.watcher.poke()
        return {"path": self._rel(p)}

    def rename_file(self, body: dict) -> dict:
        src, dst = self._in_proj(body["from"]), self._in_proj(body["to"])
        if not src.exists():
            raise sync.SyncError(f"{body['from']} が無い")
        if dst.exists():
            raise sync.SyncError(f"{body['to']} は既にある")
        if src == self._need():
            raise sync.SyncError("主文書の名前は変えない（Overleaf の設定と合わなくなる）")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file() and self.history:
            self.history.record(self._rel(src), src.read_bytes(), "delete")
        src.rename(dst)
        self._record(dst, "rename")
        return {"path": self._rel(dst)}

    def delete(self, body: dict) -> dict:
        """消す前に中身を履歴に残す（履歴から戻せる）。フォルダは中のファイルを全部残してから消す。"""
        p = self._in_proj(body["path"])
        if p == self._proj() or p == self._need():
            raise sync.SyncError("原稿のフォルダと主文書は消せない")
        if not p.exists():
            raise sync.SyncError(f"{body['path']} が無い")
        files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
        for f in files:
            if self.history and f.stat().st_size < 50 * 1024 * 1024:
                self.history.record(self._rel(f), f.read_bytes(), "delete")
        shutil.rmtree(p) if p.is_dir() else p.unlink()
        return {"deleted": len(files)}

    # ---- 検索・文字数・履歴 ----
    def search(self, q: dict) -> dict:
        files = [f["path"] for f in list_tree(self._need()) if not f["dir"] and f["editable"]]
        return search(self._proj(), files, q.get("q", ""), q.get("case") == "1", q.get("regex") == "1",
                      q.get("word") == "1")

    def wordcount(self, _=None) -> dict:
        tex = self._need()
        r = subprocess.run(["texcount", "-inc", "-utf8", "-japanese", "-sum", "-merge", tex.name],
                           cwd=tex.parent, capture_output=True, text=True, errors="replace")
        text = r.stdout.strip()
        m = re.search(r"Sum count: (\d+)", text)
        return {"sum": int(m.group(1)) if m else None, "text": text}

    def history_list(self, q: dict) -> dict:
        return {"entries": self.history.list(q.get("path") or None) if self.history else []}

    def history_diff(self, q: dict) -> dict:
        if not self.history:
            raise sync.SyncError("履歴が無い")
        return self.history.diff(q["id"])

    def history_restore(self, body: dict) -> dict:
        """その版の中身に戻す（今の中身も履歴に残るので、戻したことも取り消せる）。"""
        if not self.history:
            raise sync.SyncError("履歴が無い")
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
        if self.watcher:
            self.watcher.poke()
        return {"path": e["path"]}

    # ---- ダウンロード ----
    def export(self, fmt: str) -> tuple[str, bytes, str]:
        tex = self._need()
        if fmt == "comments":
            md = comments.to_markdown(comments.list_comments(tex, self.root), tex.name)
            return f"{tex.stem}_コメント.md", md.encode(), "text/markdown; charset=utf-8"
        if fmt == "zip":
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / f"{tex.parent.name}_overleaf.zip"
                export_zip(tex.parent, out)
                return out.name, out.read_bytes(), "application/zip"
        return pandoc.export(tex, fmt)   # Word・Markdown・HTML
