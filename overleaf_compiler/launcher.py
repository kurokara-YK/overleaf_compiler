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
import threading
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
    """裏で動いているサーバとして記録する。ほかに生きているサーバが記録されていれば、上書きしない
    （別の置き場で起動した2つ目のサーバが、アプリの一覧から開くサーバを奪わないように）。"""
    if server_info():
        return
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
                p = shutil.which(n)
                # Snap のブラウザは、専用のプロフィール（--user-data-dir）を自分の箱の外に作れず起動しない。タブで開く
                if p and not os.path.realpath(p).startswith("/snap/"):
                    return [p]
    return None


TAB_BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "firefox", "vivaldi-stable",
                "brave-browser", "microsoft-edge"]


def open_tab(url: str) -> bool:
    """ふつうのブラウザのタブで開く。xdg-open → gio → 見つかったブラウザ の順に試し、1つでも動けば True。
    （Python の webbrowser に任せると、環境によっては何も開かないことがあるため、自分で順に試す）"""
    tries = []
    if os.environ.get("BROWSER"):
        tries.append([os.environ["BROWSER"].split(":")[0], url])
    tries += [["xdg-open", url], ["gio", "open", url], ["sensible-browser", url]]
    tries += [[b, url] for b in TAB_BROWSERS]
    for cmd in tries:
        if not shutil.which(cmd[0]):
            continue
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            continue
        try:
            if p.wait(timeout=3) != 0:   # すぐ失敗して終わったら次を試す（xdg-open は開いたらすぐ 0 で終わる）
                continue
        except subprocess.TimeoutExpired:
            pass                         # ブラウザ本体が起動して動き続けている
        return True
    print(f"\n  ブラウザを自動で開けなかった。次の URL をブラウザで開くこと:\n\n    {url}\n", file=sys.stderr)
    return False


def open_window(url: str, tab: bool = False) -> bool:
    """アプリのウィンドウ（専用のブラウザ）で開く。タブで開いたときは False（閉じたことを見張れない）。"""
    b = None if tab or config().get("window") == "tab" else _default_browser()
    if not b:
        open_tab(url)
        return False
    PROFILE.mkdir(parents=True, exist_ok=True)
    if "app=1" not in url:   # 画面が、自分がアプリのウィンドウだと分かるように（「Web で開く」ボタンを出す）
        url += ("&" if "?" in url else "?") + "app=1"
    cmd = [*b, f"--user-data-dir={PROFILE}", f"--class={WM_CLASS}", "--no-first-run", "--no-default-browser-check",
           f"--app={url}"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        code = p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        return True                      # 専用のブラウザが動いている
    except OSError:
        code = 1
    if code == 0 and _browser_pid():     # すでに動いていた専用のブラウザに渡して、すぐ終わった
        return True
    open_tab(url)                        # アプリのウィンドウで開けなかった。ふつうのタブで開く
    return False


_detached = False   # 「アプリを閉じて Web で開く」を押した（ウィンドウを閉じても、サーバは Web のために動き続ける）


def detach() -> None:
    global _detached
    _detached = True


def watch_window(on_close) -> None:
    """アプリのウィンドウ（専用のブラウザ）が閉じられたら on_close を呼ぶ（端末から起動したとき、サーバも終える）。"""
    def run():
        for _ in range(200):   # ウィンドウが開くまで待つ（最大 20 秒）
            if _browser_pid():
                break
            time.sleep(0.1)
        else:
            return
        gone = 0
        while True:
            time.sleep(1)
            gone = gone + 1 if not _browser_pid() else 0
            if gone >= 2:
                if not _detached:
                    on_close()
                return
    threading.Thread(target=run, daemon=True).start()


def _browser_pid() -> int | None:
    """専用のプロフィールで動いているブラウザの番号（プロフィールの SingletonLock が「ホスト名-番号」を指す）。"""
    try:
        pid = int(os.readlink(PROFILE / "SingletonLock").rsplit("-", 1)[1])
        os.kill(pid, 0)
        # 終わったのに後始末されていないプロセス（ゾンビ）は、もう動いていないとみなす
        if " Z " in f" {Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[-1]} ":
            return None
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


# 端末（cmd を中で動かす書き方）。Ubuntu 26.04 では標準の端末が Ptyxis になる見込み。上から順に、動いたものを使う
TERMINALS = [("x-terminal-emulator", ["-e"]), ("ptyxis", ["--new-window", "--"]), ("gnome-terminal", ["--"]),
             ("kgx", ["--"]), ("konsole", ["-e"]), ("xfce4-terminal", ["-x"]), ("xterm", ["-e"])]


def open_terminal(cmd: list[str], cwd: Path | str | None = None) -> bool:
    """新しい端末の窓で cmd を動かす（Open Claude in Terminal・Switch account）。すぐ失敗した端末は飛ばして次を試す。"""
    for term, flag in TERMINALS:
        if not shutil.which(term):
            continue
        try:
            p = subprocess.Popen([term, *flag, *cmd], cwd=cwd, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if p.wait(timeout=2) != 0:
                continue
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            continue
        return True
    return False


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
