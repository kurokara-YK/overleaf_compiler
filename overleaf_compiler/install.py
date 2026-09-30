"""導入と削除（セットアップ画面・削除画面・install.sh が同じものを呼ぶ）。sudo も Docker も使わない。何度実行してもよい。

導入するもの
  1. TeX Live を ~/texlive/<年> に入れる（既に latexmk があれば飛ばす）
  2. 追加の TeX パッケージを入れる（足りないものだけ）
  3. pandoc を ~/.local/bin に入れる（Word・Markdown・HTML への書き出しに使う。既にあれば飛ばす）
  4. overleaf-compiler コマンドを ~/.local/bin に作る
  5. ~/.bashrc に TeX Live の PATH を足す（既にあれば飛ばす）
  6. アプリの一覧に登録する（右クリックの項目・セットアップ・削除も）

削除では原稿（data/）には触れない。TeX Live と pandoc は、選んだときだけ消す（ほかでも使うため）。

  python3 -m overleaf_compiler.install [install | uninstall | status]
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]
APP = "overleaf-compiler"
REPO = Path(__file__).resolve().parent.parent
HOME = Path.home()
BIN = HOME / ".local" / "bin"
APPS = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "applications"
ICONS = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / "icons" / "hicolor" / "scalable" / "apps"
STATE = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share")) / APP     # サーバの記録・ログ
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / APP / "config.json"
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "autostart" / f"{APP}.desktop"
# 上のコレクションに入らないもの。論文のクラスがよく読む Times 系のフォントと、プリアンブルを保存した形式を作るもの
EXTRA_TEX = ["newtx", "txfonts", "fontaxes", "boondox", "kastrup", "mylatexformat"]
BASHRC_MARK = "# TeX Live（ユーザー権限で ~/texlive に導入。overleaf-compiler の install.sh が追加）"


def _log(cb: Progress | None, msg: str) -> None:
    (cb or print)(msg)


# ---- 今の状態 ----
def tl_bin() -> Path | None:
    bins = sorted(HOME.glob("texlive/*/bin/*"), reverse=True)
    return next((b for b in bins if (b / "latexmk").exists()), None)


def latexmk() -> str | None:
    if p := shutil.which("latexmk"):
        return p
    b = tl_bin()
    return str(b / "latexmk") if b else None


def pandoc() -> str | None:
    return shutil.which("pandoc") or (str(BIN / "pandoc") if (BIN / "pandoc").exists() else None)


def command_link() -> Path:
    return BIN / APP


def desktop_entry() -> Path:
    return APPS / f"{APP}.desktop"


def status() -> dict:
    """セットアップ画面・設定画面に出す、導入の状態。"""
    from .claude import find_claude
    from .codex import find_codex
    tl = latexmk()
    return {
        "python": sys.version.split()[0],
        "latexmk": tl,
        "texlive_user": str(tl_bin().parent.parent) if tl_bin() else None,
        "pandoc": pandoc(),
        "claude": find_claude(),
        "codex": find_codex(),
        "command": command_link().resolve() == (REPO / "overleaf_compiler.sh").resolve() if command_link().exists() else False,
        "launcher": desktop_entry().exists(),
        "pinned": pinned(),
        "autostart": AUTOSTART.exists(),
        "data": str(REPO / "data"),
    }


def config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def set_config(**kw) -> dict:
    c = {**config(), **kw}
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(c, ensure_ascii=False, indent=1))
    return c


# ---- 導入 ----
def _run(cmd: list[str], progress: Progress | None, cwd: Path | None = None) -> int:
    """外のコマンドを動かし、出力を1行ずつ progress へ流す。"""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            _log(progress, "  " + line)
    return p.wait()


def install_texlive(progress: Progress | None = None) -> None:
    if latexmk():
        _log(progress, f"TeX Live: 導入済み（{latexmk()}）")
        return
    _log(progress, "TeX Live を ~/texlive へ入れる（1.5 GB ほど。回線によって 10〜30 分）")
    with tempfile.TemporaryDirectory() as work:
        w = Path(work)
        with urllib.request.urlopen("https://mirror.ctan.org/systems/texlive/tlnet/install-tl-unx.tar.gz", timeout=120) as r:
            with tarfile.open(fileobj=r, mode="r|gz") as tf:
                for m in tf:
                    parts = Path(m.name).parts
                    if len(parts) < 2:
                        continue
                    m.name = str(Path(*parts[1:]))   # 先頭のフォルダを外す（--strip-components=1）
                    tf.extract(m, w, **({"filter": "tar"} if hasattr(tarfile, "tar_filter") else {}))
        year = re.search(r"version (\d{4})", (w / "release-texlive.txt").read_text()).group(1)
        (w / "profile").write_text(f"""selected_scheme scheme-custom
TEXDIR {HOME}/texlive/{year}
TEXMFLOCAL {HOME}/texlive/texmf-local
TEXMFSYSCONFIG {HOME}/texlive/{year}/texmf-config
TEXMFSYSVAR {HOME}/texlive/{year}/texmf-var
TEXMFHOME ~/texmf
TEXMFCONFIG ~/.texlive{year}/texmf-config
TEXMFVAR ~/.texlive{year}/texmf-var
binary_x86_64-linux 1
collection-basic 1
collection-latex 1
collection-latexrecommended 1
collection-latexextra 1
collection-langjapanese 1
collection-langcjk 1
collection-fontsrecommended 1
collection-pictures 1
collection-bibtexextra 1
collection-binextra 1
collection-mathscience 1
collection-luatex 1
instopt_adjustpath 0
instopt_letter 0
tlpdbopt_install_docfiles 0
tlpdbopt_install_srcfiles 0
tlpdbopt_autobackup 0
""")
        if _run(["perl", "./install-tl", "-profile", str(w / "profile"), "-no-interaction"], progress, cwd=w):
            raise RuntimeError("TeX Live を入れられなかった（上のログを見ること）")
    _log(progress, f"TeX Live を入れた: {tl_bin()}")


def install_tex_packages(progress: Progress | None = None) -> None:
    b = tl_bin()
    tlmgr = shutil.which("tlmgr") or (str(b / "tlmgr") if b else None)
    if not tlmgr:
        return
    have = subprocess.run([tlmgr, "info", "--only-installed", "--data", "name"], capture_output=True, text=True).stdout.split()
    need = [p for p in EXTRA_TEX if p not in have]
    if not need:
        _log(progress, f"TeX パッケージ: そろっている（{' '.join(EXTRA_TEX)}）")
        return
    _log(progress, f"TeX パッケージを入れる: {' '.join(need)}")
    if _run([tlmgr, "install", *need], progress):
        _log(progress, f"注意: 入れられなかった。TeX Live が sudo で入れたものなら sudo tlmgr install {' '.join(need)}")


def install_pandoc(progress: Progress | None = None) -> None:
    if pandoc():
        _log(progress, "pandoc: 導入済み")
        return
    _log(progress, "pandoc を ~/.local/bin に入れる（Word・Markdown・HTML への書き出し用）")
    arch = "arm64" if platform.machine() in ("aarch64", "arm64") else "amd64"
    try:
        with urllib.request.urlopen("https://api.github.com/repos/jgm/pandoc/releases/latest", timeout=30) as r:
            tag = json.load(r)["tag_name"]
        url = f"https://github.com/jgm/pandoc/releases/download/{tag}/pandoc-{tag}-linux-{arch}.tar.gz"
        with urllib.request.urlopen(url, timeout=300) as r, tarfile.open(fileobj=r, mode="r|gz") as tf:
            for m in tf:
                if m.name.endswith("/bin/pandoc"):
                    BIN.mkdir(parents=True, exist_ok=True)
                    (BIN / "pandoc").write_bytes(tf.extractfile(m).read())
                    (BIN / "pandoc").chmod(0o755)
                    break
        _log(progress, f"pandoc {tag} を入れた")
    except Exception as e:  # 書き出しだけが使えなくなる。導入は止めない
        _log(progress, f"注意: pandoc を入れられなかった（{e}）。Word などへの書き出しだけが使えない（ほかは使える）")


def install_command(progress: Progress | None = None) -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    link = command_link()
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(REPO / "overleaf_compiler.sh")
    _log(progress, f"overleaf-compiler: {link} → {REPO / 'overleaf_compiler.sh'}")


def add_path(progress: Progress | None = None) -> None:
    b = tl_bin()
    rc = HOME / ".bashrc"
    text = rc.read_text() if rc.exists() else ""
    if b and not re.search(r"texlive/.*/bin", text):
        with rc.open("a") as f:
            f.write(f'\n{BASHRC_MARK}\nexport PATH="{b}:$PATH"\n')
        _log(progress, "~/.bashrc に PATH を足した。新しい端末から有効になる")
    if str(BIN) not in os.environ.get("PATH", "").split(os.pathsep):
        _log(progress, "注意: ~/.local/bin が PATH に無い。~/.bashrc に足すこと")


def _desktop(name: str, exec_: str, comment: str, icon: str, extra: str = "") -> str:
    return (f"[Desktop Entry]\nType=Application\nVersion=1.0\nName={name}\nComment={comment}\n"
            f"Exec={exec_}\nIcon={icon}\nTerminal=false\n{extra}")


def install_launcher(progress: Progress | None = None) -> None:
    """アプリの一覧に登録する。アイコンは本体の1つだけ（Ubuntu のふつうの形）。
    セットアップのやり直しと削除は、本体の右クリック「設定・状態を確認する」の画面から。
    はじめにこれを実行.sh が出した「セットアップ」のアイコンは、本体を登録したら片付ける。"""
    APPS.mkdir(parents=True, exist_ok=True)
    ICONS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO / "share" / f"{APP}.svg", ICONS / f"{APP}.svg")
    run = REPO / "overleaf_compiler.sh"
    text = (REPO / "share" / f"{APP}.desktop.in").read_text(encoding="utf-8").replace("@EXEC@", str(run)).replace("@ICON@", APP)
    desktop_entry().write_text(text, encoding="utf-8")
    for extra in (APPS / f"{APP}-setup.desktop", APPS / f"{APP}-uninstall.desktop"):
        extra.unlink(missing_ok=True)
    for d in (APPS, ICONS.parent.parent):
        if shutil.which("update-desktop-database") and d == APPS:
            subprocess.run(["update-desktop-database", str(d)], capture_output=True, timeout=15)
        if shutil.which("gtk-update-icon-cache") and d != APPS:
            subprocess.run(["gtk-update-icon-cache", "-q", "-t", str(d)], capture_output=True, timeout=15)
    _log(progress, f"アプリの一覧に登録した: {desktop_entry()}")


def _favorites() -> list[str] | None:
    """GNOME のドックにピン留めされているアプリ（gsettings が無ければ None）。"""
    if not shutil.which("gsettings"):
        return None
    r = subprocess.run(["gsettings", "get", "org.gnome.shell", "favorite-apps"], capture_output=True, text=True, timeout=5)
    if r.returncode:
        return None
    return re.findall(r"'([^']+)'", r.stdout)


def pinned() -> bool:
    return f"{APP}.desktop" in (_favorites() or [])


def set_pinned(on: bool, progress: Progress | None = None) -> None:
    """ドック（画面の下・横のアプリの並び）にピン留めする／外す。"""
    fav = _favorites()
    if fav is None:
        return
    name = f"{APP}.desktop"
    if on == (name in fav):
        return
    fav = fav + [name] if on else [f for f in fav if f != name]
    value = "[" + ", ".join(f"'{f}'" for f in fav) + "]"
    subprocess.run(["gsettings", "set", "org.gnome.shell", "favorite-apps", value], capture_output=True, timeout=5)
    _log(progress, "ドックにピン留めした" if on else "ドックのピン留めを外した")


def set_autostart(on: bool, progress: Progress | None = None) -> None:
    """ログインしたら裏でサーバを起こしておく（ウィンドウは開かない）。"""
    if on:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(_desktop("overleaf-compiler（裏で準備）", f"{REPO / 'overleaf_compiler.sh'} app --background",
                                      "overleaf-compiler のサーバを起こしておく", APP, "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"))
        _log(progress, "ログインしたらサーバを起こしておくようにした")
    elif AUTOSTART.exists():
        AUTOSTART.unlink()
        _log(progress, "ログイン時の起動をやめた")


def install_all(opts: dict | None = None, progress: Progress | None = None) -> None:
    """opts: texlive / pandoc / command / launcher / pin / autostart（既定はすべて True、autostart だけ False）。"""
    o = {"texlive": True, "pandoc": True, "command": True, "launcher": True, "pin": True, "autostart": False, **(opts or {})}
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 以上が必要")
    if o["texlive"]:
        install_texlive(progress)
        install_tex_packages(progress)
    if o["pandoc"]:
        install_pandoc(progress)
    if o["command"]:
        install_command(progress)
    if o["texlive"]:
        add_path(progress)
    if o["launcher"]:
        install_launcher(progress)
        set_pinned(o["pin"], progress)
    set_autostart(o["autostart"], progress)
    STATE.mkdir(parents=True, exist_ok=True)
    _log(progress, "完了。アプリの一覧の overleaf-compiler か、端末の  overleaf-compiler  で開く。")


# ---- 削除 ----
def uninstall(opts: dict | None = None, progress: Progress | None = None) -> None:
    """opts: texlive / pandoc / history（既定は False。ほかでも使うため・戻せないため）。原稿（data/）には触れない。"""
    o = {"texlive": False, "pandoc": False, "history": False, **(opts or {})}
    from .launcher import stop_server
    if stop_server():
        _log(progress, "サーバを止めた")
    set_pinned(False, progress)
    for p in (desktop_entry(), APPS / f"{APP}-setup.desktop", APPS / f"{APP}-uninstall.desktop",
              ICONS / f"{APP}.svg", AUTOSTART):
        if p.exists():
            p.unlink()
            _log(progress, f"削除: {p}")
    link = command_link()
    if link.is_symlink() and link.resolve() == (REPO / "overleaf_compiler.sh").resolve():
        link.unlink()
        _log(progress, f"削除: {link}")
    # サーバの記録と設定だけ消す。変更履歴（STATE/history）は選んだときだけ
    for p in (STATE / "server.json", STATE / "server.log", STATE / "claude-sessions.json"):
        if p.exists():
            p.unlink()
            _log(progress, f"削除: {p}")
    if CONFIG.parent.exists():
        shutil.rmtree(CONFIG.parent, ignore_errors=True)
        _log(progress, f"削除: {CONFIG.parent}")
    if (STATE / "browser").exists():   # アプリのウィンドウ専用のブラウザのプロフィール
        shutil.rmtree(STATE / "browser", ignore_errors=True)
        _log(progress, f"削除: {STATE / 'browser'}")
    if o["history"] and (STATE / "history").exists():
        shutil.rmtree(STATE / "history", ignore_errors=True)
        _log(progress, f"削除（変更履歴）: {STATE / 'history'}")
    if STATE.exists() and not any(STATE.iterdir()):
        STATE.rmdir()
    if o["pandoc"] and (BIN / "pandoc").exists():
        (BIN / "pandoc").unlink()
        _log(progress, f"削除: {BIN / 'pandoc'}")
    if o["texlive"]:
        for d in [HOME / "texlive", *HOME.glob(".texlive20*")]:
            if d.exists():
                _log(progress, f"削除（時間がかかる）: {d}")
                shutil.rmtree(d, ignore_errors=True)
        rc = HOME / ".bashrc"
        if rc.exists():   # TeX Live の見出しの行と、~/texlive を指す export の行を消す
            lines = rc.read_text().split("\n")
            out = [x for x in lines if not (x.startswith("# TeX Live") or (x.startswith("export ") and "texlive/" in x))]
            if len(out) != len(lines):
                rc.write_text("\n".join(out))
                _log(progress, "~/.bashrc から TeX Live の PATH を消した")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(APPS)], capture_output=True, timeout=15)
    _log(progress, f"削除した。原稿（{REPO / 'data'}）とこのフォルダはそのまま残っている。")


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m overleaf_compiler.install", description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", default="install", choices=["install", "uninstall", "status"])
    ap.add_argument("--no-launcher", action="store_true", help="アプリの一覧に登録しない")
    ap.add_argument("--texlive", action="store_true", help="uninstall で TeX Live も消す")
    ap.add_argument("--pandoc", action="store_true", help="uninstall で pandoc も消す")
    ap.add_argument("--history", action="store_true", help="uninstall で変更履歴も消す")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "install":
            install_all({"launcher": not a.no_launcher})
        elif a.cmd == "uninstall":
            uninstall({"texlive": a.texlive, "pandoc": a.pandoc, "history": a.history})
        else:
            print(json.dumps(status(), ensure_ascii=False, indent=1))
    except Exception as e:
        sys.exit(f"overleaf-compiler: {e}")


if __name__ == "__main__":
    main()
