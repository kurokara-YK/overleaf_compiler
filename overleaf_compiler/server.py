"""ローカルのブラウザで原稿を選び、Overleaf と同じ画面で直すためのサーバ。

127.0.0.1 でしか待ち受けない。画面とのやり取りでは、パスはすべて data（または原稿のフォルダ）からの
相対パスで渡し、絶対パスは出さない。書き換えられるのは開いた原稿の、data の1段目のフォルダの中だけ。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import sync
from .builder import Watcher
from .history import History
from .overleaf import export_zip, import_zip
from .project import ProjectError, browse, list_tree, rename_to_tex
from .search import search

STATIC = Path(__file__).parent / "static"
STATE_FILE = ".overleaf-compiler-serve.json"
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/markdown", ".md")
_BAD_NAME = re.compile(r'[\\/:*?"<>|]')
# pandoc で書き出す形式（Overleaf の「ダウンロード」と同じ並び）
EXPORTS = {"docx": ("docx", ".docx", []), "md": ("gfm", ".md", []),
           "html": ("html5", ".html", ["--standalone", "--embed-resources", "--mathjax"])}


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
        """書き換えてよい範囲。data の中の原稿なら data の1段目のフォルダ、外なら原稿のフォルダ。"""
        tex = self._need()
        if tex.is_relative_to(self.data):
            return self.data / tex.relative_to(self.data).parts[0]
        return tex.parent

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
                "rel": rel, "has_pandoc": bool(shutil.which("pandoc")),
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
        st = {"session": self.session, "open": True, **self.watcher.status()}
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
        if fmt == "zip":
            with tempfile.TemporaryDirectory() as d:
                out = Path(d) / f"{tex.parent.name}_overleaf.zip"
                export_zip(tex.parent, out)
                return out.name, out.read_bytes(), "application/zip"
        if fmt not in EXPORTS:
            raise sync.SyncError(f"{fmt} には書き出せない")
        if not shutil.which("pandoc"):
            raise sync.SyncError("pandoc が無いので書き出せない（bash install.sh で入る）")
        to, ext, extra = EXPORTS[fmt]
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / (tex.stem + ext)
            r = subprocess.run(["pandoc", "-f", "latex", "-t", to, *extra, "--resource-path=.", "-o", str(out),
                                tex.name], cwd=tex.parent, capture_output=True, text=True, errors="replace")
            if r.returncode != 0 or not out.exists():
                raise sync.SyncError("pandoc で書き出せなかった: " + (r.stderr.strip().splitlines() or [""])[-1])
            return out.name, out.read_bytes(), mimetypes.guess_type(out.name)[0] or "application/octet-stream"


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # アクセスログは出さない
            pass

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _api(self, fn, arg=None):
            try:
                self._json(fn(arg))
            except (sync.SyncError, ProjectError) as e:
                self._json({"error": str(e)}, HTTPStatus.CONFLICT)
            except (KeyError, ValueError) as e:
                self._json({"error": f"不正な要求: {e}"}, HTTPStatus.BAD_REQUEST)

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", 0)))

        def _file(self, fn):
            try:
                name, data, ctype = fn()
            except (sync.SyncError, ProjectError) as e:
                return self._json({"error": str(e)}, 409)
            self._send(200, data, ctype, extra={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/":
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/pdf":
                pdf = app.tex.with_suffix(".pdf") if app.tex else None
                if not pdf or not pdf.exists():
                    return self._json({"error": "PDF がまだ無い"}, 404)
                extra = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(pdf.name)}"} \
                    if q.get("download") else None
                return self._send(200, pdf.read_bytes(), "application/pdf", extra=extra)
            if u.path == "/raw":
                try:
                    data, ctype = app.raw(q.get("path", ""))
                except (sync.SyncError, ProjectError) as e:
                    return self._json({"error": str(e)}, 409)
                extra = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(Path(q['path']).name)}"} \
                    if q.get("download") else None
                return self._send(200, data, ctype, extra=extra)
            if u.path == "/export":
                return self._file(lambda: app.export(q.get("format", "zip")))
            routes = {"/api/info": app.info, "/api/status": app.status, "/api/browse": app.browse,
                      "/api/tree": app.tree, "/api/read": app.read, "/api/search": app.search,
                      "/api/goto_source": app.goto_source, "/api/goto_pdf": app.goto_pdf,
                      "/api/wordcount": app.wordcount, "/api/history": app.history_list,
                      "/api/history_diff": app.history_diff}
            if u.path in routes:
                return self._api(routes[u.path], q)
            if u.path.startswith("/static/"):
                f = (STATIC / u.path[len("/static/"):]).resolve()
                if f.is_file() and STATIC.resolve() in f.parents:
                    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                    return self._send(200, f.read_bytes(), ctype, cache=bool({"pdfjs", "fonts"} & set(f.parts)))
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/api/import":
                data = self._body()
                return self._api(lambda _: app.import_(q.get("path", ""), q.get("name", "overleaf.zip"), data))
            if u.path == "/api/upload":
                data = self._body()
                return self._api(lambda _: app.upload(q, data))
            try:
                body = json.loads(self._body() or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "JSON が壊れている"}, 400)
            routes = {"/api/write": app.write, "/api/recompile": app.recompile, "/api/rename_txt": app.rename_txt,
                      "/api/close": app.close_tex, "/api/mkdir": app.mkdir, "/api/newfile": app.newfile,
                      "/api/newfolder": app.newfolder, "/api/rename": app.rename_file, "/api/delete": app.delete,
                      "/api/replace": app.replace, "/api/history_restore": app.history_restore}
            if u.path == "/api/open":
                return self._api(lambda b: (app.open(app._data_path(b["tex"])), app.info())[1], body)
            if u.path in routes:
                return self._api(routes[u.path], body)
            self._send(404, b"not found", "text/plain")

    return Handler


def serve(data: Path, start: str, tex: Path | None, port: int, open_browser: bool) -> None:
    app = App(data, start=start)
    httpd = None
    for p in range(port, port + 20):  # 使用中なら次の番号
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), make_handler(app))
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"ポート {port}〜{port + 19} が全部使用中")
    app.port = httpd.server_port
    if tex:
        app.open(tex)
    # kill（SIGTERM）で止められても latexmk を残さない
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    url = f"http://127.0.0.1:{httpd.server_port}/"
    print(f"overleaf-compiler: {url}   （Ctrl+C で終了）")
    if tex:
        print(f"        原稿 {tex.name}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
        httpd.server_close()
