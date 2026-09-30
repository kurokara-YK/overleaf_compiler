"""アプリとして開く（アプリの一覧・右クリックの項目から）。サーバを裏で1つだけ動かし、ブラウザをアプリのウィンドウで開く。

サーバは起動したら ~/.local/share/overleaf-compiler/server.json に番号（pid）とポートを書く（server.py の serve）。
既に動いていればそれを使い、無ければ裏で起動する（端末は要らない）。ウィンドウは、既定のブラウザが Chromium 系
（Vivaldi・Chrome・Chromium・Brave・Edge）ならタブもアドレス欄も無いアプリのウィンドウ（--app）で、それ以外は普通のタブで開く。

  overleaf-compiler app                 一覧を開く（サーバが無ければ起動する）
  overleaf-compiler app --tab           アプリのウィンドウではなく、ブラウザのタブで開く
  overleaf-compiler app --background    サーバだけ起こしておく（ログイン時）
  overleaf-compiler stop                裏のサーバを止める
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .install import REPO, STATE, config

SERVER = STATE / "server.json"
# アプリのウィンドウ専用のブラウザのプロフィール。普段のブラウザとは別のプロセスになるので、止めるときに閉じられる
PROFILE = STATE / "browser"
WM_CLASS = "overleaf-compiler"   # ドックがこのウィンドウを overleaf-compiler のものとして扱う（.desktop の StartupWMClass）
LOG = STATE / "server.log"
CHROMIUM = {"vivaldi": ["vivaldi-stable", "vivaldi"], "google-chrome": ["google-chrome", "google-chrome-stable"],
            "chromium": ["chromium", "chromium-browser"], "brave": ["brave-browser", "brave"],
            "microsoft-edge": ["microsoft-edge", "microsoft-edge-stable"]}


# ---- 動いているサーバ ----
def server_info() -> dict | None:
    """裏で動いているサーバ（{pid, port, data}）。応答が無ければ None。"""
    try:
        s = json.loads(SERVER.read_text())
        os.kill(s["pid"], 0)
        with urllib.request.urlopen(f"http://127.0.0.1:{s['port']}/api/info", timeout=2) as r:
            json.load(r)
        return s
    except (OSError, ValueError, KeyError):
        return None


def write_server(port: int, data: Path) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    SERVER.write_text(json.dumps({"pid": os.getpid(), "port": port, "data": str(data)}))


def clear_server() -> None:
    try:
        if json.loads(SERVER.read_text()).get("pid") == os.getpid():
            SERVER.unlink()
    except (OSError, ValueError):
        pass


def start_server(port: int = 8765) -> dict:
    """裏でサーバを起動し、応答するまで待つ。"""
    if s := server_info():
        return s
    STATE.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(REPO) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")}
    with LOG.open("a") as log:
        subprocess.Popen([sys.executable, "-m", "overleaf_compiler", "serve", "--no-browser", "--port", str(port)],
                         cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    for _ in range(100):
        time.sleep(0.15)
        if s := server_info():
            return s
    raise RuntimeError(f"サーバが起動しない（{LOG} を見ること）")


def stop_server() -> bool:
    """アプリのウィンドウを閉じて、裏のサーバを止める。"""
    close_windows()
    s = None
    try:
        s = json.loads(SERVER.read_text())
        os.kill(s["pid"], signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        return False
    for _ in range(40):
        time.sleep(0.1)
        try:
            os.kill(s["pid"], 0)
        except OSError:
            break
    SERVER.unlink(missing_ok=True)
    return True


# ---- ウィンドウ ----
def _default_browser() -> list[str] | None:
    """既定のブラウザが Chromium 系なら、その実行ファイル。"""
    try:
        d = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        d = ""
    for key, names in CHROMIUM.items():
        if key in d:
            for n in names:
                if p := shutil.which(n):
                    return [p]
    return None


def open_window(url: str, tab: bool = False) -> None:
    b = None if tab or config().get("window") == "tab" else _default_browser()
    if b:
        PROFILE.mkdir(parents=True, exist_ok=True)
        cmd = [*b, f"--user-data-dir={PROFILE}", f"--class={WM_CLASS}", "--no-first-run", "--no-default-browser-check",
               f"--app={url}"]
    else:
        cmd = ["xdg-open", url]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def _browser_pid() -> int | None:
    """専用のプロフィールで動いているブラウザの番号（プロフィールの SingletonLock が「ホスト名-番号」を指す）。"""
    try:
        pid = int(os.readlink(PROFILE / "SingletonLock").rsplit("-", 1)[1])
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError, IndexError):
        return None


def close_windows() -> bool:
    """アプリのウィンドウ（専用のブラウザ）を閉じる。ブラウザのタブで開いたものは閉じられない。"""
    pid = _browser_pid()
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except OSError:
            return True
    os.kill(pid, signal.SIGKILL)
    return True


def _notify(msg: str) -> None:
    """アプリの一覧から開いたときは端末が無いので、画面に出す。"""
    print(msg, file=sys.stderr)
    if not sys.stderr.isatty() and shutil.which("zenity"):
        subprocess.Popen(["zenity", "--error", "--title=overleaf-compiler", "--width=380", f"--text={msg}"])


def cmd_app(a) -> None:
    try:
        s = start_server()
    except RuntimeError as e:
        _notify(str(e))
        sys.exit(1)
    if a.background:
        return
    open_window(f"http://127.0.0.1:{s['port']}/", a.tab)


def cmd_stop(_a) -> None:
    if not stop_server() and not close_windows():
        print("裏で動いているサーバは無い")
    else:
        print("ウィンドウを閉じて、サーバを止めた")
