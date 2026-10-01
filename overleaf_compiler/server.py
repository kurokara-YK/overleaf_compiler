"""ローカルのブラウザで原稿を選び、Overleaf と同じ画面で直すためのサーバ（HTTP の受け口と起動）。

127.0.0.1 でしか待ち受けない。要求の中身は app.App が処理する。原稿ごとの要求には ?p=（data からの
主文書の相対パス）が付き、その原稿の app.Project が処理する。ブラウザのタブごとに別の原稿を開ける。
"""
from __future__ import annotations

import json
import os
import mimetypes
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import sync
from .app import App
from . import claude, launcher
from .claude import ClaudeError
from .project import ProjectError

STATIC = Path(__file__).parent / "static"
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("text/markdown", ".md")


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
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):   # 待っている間にタブが閉じられた（チャット欄の長いポーリングなど）
                pass

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _api(self, fn, arg=None):
            try:
                self._json(fn(arg))
            except (sync.SyncError, ProjectError, ClaudeError) as e:
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
                try:
                    pdf = app.project(q).tex.with_suffix(".pdf")
                except (sync.SyncError, ProjectError):
                    pdf = None
                if not pdf or not pdf.exists():
                    return self._json({"error": "PDF がまだ無い"}, 404)
                extra = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(pdf.name)}"} \
                    if q.get("download") else None
                return self._send(200, pdf.read_bytes(), "application/pdf", extra=extra)
            if u.path == "/raw":
                try:
                    data, ctype = app.project(q).raw(q.get("path", ""))
                except (sync.SyncError, ProjectError) as e:
                    return self._json({"error": str(e)}, 409)
                extra = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(Path(q['path']).name)}"} \
                    if q.get("download") else None
                return self._send(200, data, ctype, extra=extra)
            if u.path == "/export":
                return self._file(lambda: app.project(q).export(q.get("format", "zip")))
            if u.path == "/api/item_zip":   # 一覧の項目の ⋮ → ダウンロード
                return self._file(lambda: app.item_zip(q))
            routes = {"/api/info": app.info, "/api/status": app.status, "/api/browse": app.browse, "/api/fs_list": app.fs_list}
            if u.path in routes:
                return self._api(routes[u.path], q)
            # 原稿ごとの要求（?p= の原稿の Project が処理する）
            per = {"/api/tree": "tree", "/api/read": "read", "/api/search": "search",
                   "/api/goto_source": "goto_source", "/api/goto_pdf": "goto_pdf",
                   "/api/wordcount": "wordcount", "/api/history": "history_list",
                   "/api/history_diff": "history_diff", "/api/history_view": "history_view",
                   "/api/comments": "comments_list"}
            if u.path in per:
                return self._api(lambda arg: getattr(app.project(q), per[u.path])(arg), q)
            # 右のチャット欄。?c= のタブの会話（chats.py）。新しい出来事が出るまで待って返す
            if u.path == "/api/chat/events":
                return self._api(lambda _: app.project(q).chats.get(q.get("c")).wait_events(q))
            if u.path == "/api/chat/sessions":
                return self._api(lambda _: app.project(q).chats.get(q.get("c")).sessions())
            if u.path == "/api/chat/tabs":
                return self._api(lambda _: app.project(q).chats.list())
            if u.path.startswith("/claude-asset/"):   # チャット欄のアイコン。VS Code の拡張に入っているものを使う（同梱しない）
                f = claude.asset(u.path[len("/claude-asset/"):])
                if f:
                    return self._send(200, f.read_bytes(), "image/svg+xml", cache=True)
                return self._send(404, b"not found", "text/plain")
            if u.path.startswith("/static/"):
                f = (STATIC / u.path[len("/static/"):]).resolve()
                if f.is_file() and STATIC.resolve() in f.parents:
                    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                    return self._send(200, f.read_bytes(), ctype, cache=bool({"pdfjs", "pdflib", "fonts"} & set(f.parts)))
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/api/import":
                data = self._body()
                return self._api(lambda _: app.import_(q.get("path", ""), q.get("name", "overleaf.zip"), data))
            if u.path == "/api/upload":
                data = self._body()
                return self._api(lambda _: app.project(q).upload(q, data))
            try:
                body = json.loads(self._body() or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "JSON が壊れている"}, 400)
            if u.path == "/api/close":
                return self._api(app.close_tex, q)
            if u.path == "/api/rename_project":
                return self._api(lambda b: app.rename_project(q, b), body)
            routes = {"/api/open": app.open_api, "/api/rename_txt": app.rename_txt, "/api/mkdir": app.mkdir,
                      "/api/settle": app.settle, "/api/item_rename": app.item_rename, "/api/item_delete": app.item_delete,
                      "/api/fs_import": app.fs_import}
            if u.path in routes:
                return self._api(routes[u.path], body)
            # 原稿ごとの要求（?p= の原稿の Project が処理する）
            per = {"/api/write": "write", "/api/recompile": "recompile", "/api/newfile": "newfile",
                   "/api/newfolder": "newfolder", "/api/rename": "rename_file", "/api/delete": "delete",
                   "/api/replace": "replace", "/api/history_restore": "history_restore", "/api/comment": "comment",
                   "/api/history_label": "history_label", "/api/copy": "copy_project"}
            if u.path in per:
                return self._api(lambda arg: getattr(app.project(q), per[u.path])(arg), body)
            # 右のチャット欄。/api/chat/<名前>?c=<タブ> をそのタブの会話の同じ名前のメソッドへ
            if u.path in ("/api/chat/new", "/api/chat/close"):
                return self._api(lambda arg: getattr(app.project(q).chats, u.path[len("/api/chat/"):])(arg), body)
            chat = {"send", "stop", "reset", "start", "set", "permission", "control", "resume", "rewind", "terminal",
                    "compact", "fork", "account"}
            name = u.path[len("/api/chat/"):]
            if u.path.startswith("/api/chat/") and name in chat:
                def call(arg):
                    fn = getattr(app.project(q).chats.get(q.get("c")), name, None)
                    if fn is None:
                        raise ClaudeError(f"この会話では {name} は使えない")
                    return fn(arg)
                return self._api(call, body)
            self._send(404, b"not found", "text/plain")

    return Handler


def serve(data: Path, start: str, tex: Path | None, port: int, open_browser: bool, app_window: bool = False) -> None:
    """app_window なら、アプリのウィンドウ（専用のブラウザ）で開き、Ctrl+C でウィンドウも閉じる。
    ウィンドウを閉じたら、サーバも終える（アプリと同じ）。"""
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
    launcher.write_server(httpd.server_port, data)   # アプリの一覧から開くとき、動いているサーバを使う
    url = f"http://127.0.0.1:{httpd.server_port}/"
    if tex:
        pr = app.open(tex)
        url += "?p=" + quote(pr.info(app.start)["rel"])
    # kill（SIGTERM）で止められても latexmk を残さない。Ctrl+C（SIGINT）は、無視する設定で起動されても必ず受け取る
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    signal.signal(signal.SIGINT, signal.default_int_handler)
    windowed = False
    if open_browser and app_window:
        windowed = launcher.open_window(url)
        if windowed:   # ウィンドウを閉じたら、サーバも終える（serve_forever から抜けて、下の finally へ）
            launcher.watch_window(httpd.shutdown)
    elif open_browser:
        threading.Timer(0.5, lambda: launcher.open_tab(url)).start()
    print(f"overleaf-compiler: http://127.0.0.1:{httpd.server_port}/   "
          f"（{'Ctrl+C かウィンドウを閉じると終了' if windowed else 'Ctrl+C で終了'}）")
    if tex:
        print(f"        原稿 {tex.name}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if windowed:
            launcher.close_windows()
        launcher.clear_server()
        app.shutdown()
        httpd.server_close()
