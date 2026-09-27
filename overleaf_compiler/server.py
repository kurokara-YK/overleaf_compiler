"""ローカルのブラウザで原稿を選び、Overleaf と同じ画面で直すためのサーバ（HTTP の受け口と起動）。

127.0.0.1 でしか待ち受けない。要求の中身は app.App が処理する。
"""
from __future__ import annotations

import json
import mimetypes
import signal
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import sync
from .app import App
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
                      "/api/history_diff": app.history_diff, "/api/comments": app.comments_list}
            if u.path in routes:
                return self._api(routes[u.path], q)
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
                return self._api(lambda _: app.upload(q, data))
            try:
                body = json.loads(self._body() or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "JSON が壊れている"}, 400)
            routes = {"/api/write": app.write, "/api/recompile": app.recompile, "/api/rename_txt": app.rename_txt,
                      "/api/close": app.close_tex, "/api/mkdir": app.mkdir, "/api/newfile": app.newfile,
                      "/api/newfolder": app.newfolder, "/api/rename": app.rename_file, "/api/delete": app.delete,
                      "/api/replace": app.replace, "/api/history_restore": app.history_restore,
                      "/api/comment": app.comment, "/api/settle": app.settle}
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
