"""overleaf-compiler — Overleaf の原稿をローカルで組み、PDF をクリックして直し、Overleaf へ戻す。

  overleaf-compiler                                  アプリとして data/ のワークスペース一覧を開く（Ctrl+C で閉じる）
  overleaf-compiler --web                            ブラウザのタブで開く（今までの開き方）
  overleaf-compiler import <overleaf.zip> [展開先]   Overleaf で Download した zip を data/ へ展開する
  overleaf-compiler serve  [原稿 | ワークスペース]   ブラウザで PDF を開く。文をクリックすると LaTeX を直せる
  overleaf-compiler check  <原稿>                    組んで、エラー・未定義の参照・はみ出しを file:line で出す
  overleaf-compiler comments <原稿>                  PDF に付いた未解決のコメントを file:line で出す
  overleaf-compiler comments <原稿> --resolve ID -m 何を直したか
                                                     直したコメントを解決済みにして、返信を残す
  overleaf-compiler build  <原稿>                    1回だけ組む（latexmk の出力をそのまま出す）
  overleaf-compiler export <原稿> [-o 出力.zip]      Overleaf の Upload Project に入れる zip を作る
  overleaf-compiler clean  <原稿>                    中間生成物を消す
  overleaf-compiler app [--tab]                      アプリとして開く（サーバを裏で動かす。アプリの一覧から使う）
  overleaf-compiler stop                             裏で動いているサーバを止める

<原稿> は主文書の .tex か、それを含むディレクトリ。
ワークスペースは data/ の下のフォルダ。その中に Overleaf から取り込んだ原稿を置く。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .project import ProjectError, detect_engine, ensure_texlive, find_main, has_latexmkrc


# ワークスペースの置き場。パッケージの隣の data/（overleaf_compiler/data）
DATA = Path(__file__).resolve().parent.parent / "data"


def _data(a) -> Path:
    return Path(a.data).expanduser().resolve() if getattr(a, "data", None) else DATA


def _main_of(a) -> Path:
    """引数の原稿（主文書かそのフォルダ）の主文書。

    「data/…」が今いる場所に無ければ、overleaf_compiler の data/ の中を指すとみなす
    （画面がコピーする依頼文は、この書き方で原稿を指す）。
    """
    p = a.path
    if not Path(p).expanduser().exists() and Path(p).parts[:1] == ("data",) and (DATA.parent / p).exists():
        p = str(DATA.parent / p)
    return find_main(p)


def _engine_note(tex: Path) -> str:
    if has_latexmkrc(tex.parent):
        return "latexmkrc に従う"
    return f"{detect_engine(tex)}（latexmkrc が無いので本文から推定）"


# ---------------------------------------------------------------- serve との連携
def _ask_serve(tex: Path, wait: bool) -> dict | None:
    """この原稿を serve が組んでいれば、その組版の状態を返す（組んでいなければ None）。

    wait なら、呼んだ時点までの変更（Claude Code が直したファイル）を組み終えるまで待つ。
    serve は原稿のフォルダに STATE_FILE（ポート番号）を置く。そのサーバが別の原稿を開いている・
    止まっている・別のものが待ち受けている場合は、断られるか繋がらないので None になる。
    """
    import json
    import urllib.request
    from .app import STATE_FILE
    try:
        port = int(json.loads((tex.parent / STATE_FILE).read_text())["port"])
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/settle", method="POST",
                                     data=json.dumps({"tex": str(tex), "wait": wait}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=620 if wait else 3) as r:
            st = json.load(r)
    except (OSError, ValueError, KeyError, TypeError):   # 断られた（HTTPError も OSError）・繋がらない・印が壊れている
        return None
    return st if "version" in st else None


def _refuse_if_serving(tex: Path, what: str) -> None:
    """serve が組んでいる原稿で、latexmk を別に走らせたり中間生成物を消したりしない（組版が壊れる）。"""
    if _ask_serve(tex, wait=False):
        raise ProjectError(f"この原稿は overleaf-compiler の画面が組んでいる。{what}")


# ---------------------------------------------------------------- コマンド
def cmd_import(a) -> None:
    from .overleaf import import_zip
    z = Path(a.zip).expanduser().resolve()
    dest = Path(a.dest).expanduser().resolve() if a.dest else _data(a) / z.stem
    mains = import_zip(z, dest)
    print(f"展開: {dest}")
    if mains:
        print("主文書:")
        for m in mains:
            print(f"  {m.relative_to(dest)}  … {_engine_note(m)}")
        target = mains[0] if len(mains) > 1 else dest
        print(f"\n次は  overleaf-compiler '{target}'")


def cmd_serve(a) -> None:
    from .project import is_main
    from .server import serve
    data = _data(a)
    data.mkdir(parents=True, exist_ok=True)
    start, tex = "", None
    if a.path:
        p = Path(a.path).expanduser().resolve()
        if p.is_file():
            tex = find_main(p)
            p = tex.parent
        elif not p.is_dir():
            raise ProjectError(f"{p} が無い")
        else:
            top = [t for t in sorted(p.glob("*.tex")) if is_main(t) and not t.name.startswith("_")]
            if len(top) == 1:  # 主文書が1つだけのフォルダなら、それを開く
                tex = top[0]
        if not p.is_relative_to(data):   # data の外なら、その親を置き場として扱う
            data = p.parent
        start = str(p.relative_to(data)) if p != data else ""
    # アプリとして裏で動いているサーバがあれば、2つ目は起動せずにそれを開く
    from .launcher import server_info
    s = server_info()
    if s and Path(s["data"]) == data and not a.no_browser:
        from urllib.parse import quote
        from .launcher import open_tab, open_window
        rel = str(tex.relative_to(data)) if tex and tex.is_relative_to(data) else ""
        url = f"http://127.0.0.1:{s['port']}/" + (f"?p={quote(rel)}" if rel else f"?dir={quote(start)}" if start else "")
        print(f"overleaf-compiler: 動いているサーバを開いた  {url}\n        （止めるには  overleaf-compiler stop）")
        if a.web:
            open_tab(url)
        else:
            open_window(url)
        return
    if tex:
        print(f"組版: {_engine_note(tex)}")
    serve(data, start, tex, a.port, not a.no_browser, app_window=not a.web, auto_stop=a.auto_stop)


def cmd_check(a) -> None:
    import json
    from .builder import build_once, failure_lines
    from .report import format_report, summarize
    tex = _main_of(a)
    # 画面（serve）が組んでいれば、その組版が今の変更を組み終えるのを待って結果を読む。
    # 二重に latexmk を走らせると中間生成物が壊れる
    st = _ask_serve(tex, wait=True)
    rc, output = (0, "") if st else build_once(tex, quiet=True)
    r = summarize(tex)
    # 組版は失敗したのに TeX のエラーが無い：文献処理や dvipdfmx などで止まっている
    if st and not st["ok"] and r["ok"]:
        r["ok"] = False
        r["other_failures"] = [e["msg"] for e in st["errors"] if not e.get("file")] or ["組版に失敗した（画面のログを見る）"]
    elif rc != 0:
        r["ok"] = False
        r["other_failures"] = failure_lines(output) or ["latexmk が失敗した（overleaf-compiler build で詳しい出力を見る）"]
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else format_report(r))
    sys.exit(0 if r["ok"] else 1)


def cmd_comments(a) -> None:
    import json
    from . import comments
    from .project import edit_root
    from .sync import SyncError
    tex = _main_of(a)
    try:
        done = []
        for cid in a.resolve or []:
            if a.message:
                comments.reply(tex, cid, a.author, a.message)
            done.append(f"[{comments.set_status(tex, cid, 'resolved', a.author)['id']}] 解決済みにした")
        for cid in a.reopen or []:
            done.append(f"[{comments.set_status(tex, cid, 'open')['id']}] 未解決に戻した")
        if a.reply:
            if not a.message:
                raise SyncError("--reply には -m で返信の文を付ける")
            done.append(f"[{comments.reply(tex, a.reply, a.author, a.message)['id']}] 返信した")
        if done:
            print("\n".join(done))
            return
        allc = comments.list_comments(tex, edit_root(tex, _data(a)))
        shown = allc if a.all else [c for c in allc if c["status"] != "resolved"]
        if a.json:
            print(json.dumps(shown, ensure_ascii=False, indent=1))
        else:
            title = f"{'コメント' if a.all else '未解決のコメント'}（{tex.name}）"
            print(comments.format_text(shown, title), end="")
            if not a.all and len(allc) > len(shown):
                print(f"\n解決済み {len(allc) - len(shown)} 件は --all で出る")
    except SyncError as e:
        sys.exit(f"overleaf-compiler: {e}")


def cmd_build(a) -> None:
    from .builder import build_once
    tex = _main_of(a)
    _refuse_if_serving(tex, "画面の「リコンパイル」を使うか、check で結果を見る")
    print(f"組版: {_engine_note(tex)}")
    rc, _ = build_once(tex)
    print(f"\n{'PDF' if rc == 0 else '失敗'}: {tex.with_suffix('.pdf')}")
    sys.exit(rc)


def cmd_export(a) -> None:
    from .overleaf import export_zip
    p = Path(a.path).expanduser().resolve()
    root = p if p.is_dir() else p.parent
    out = Path(a.output).expanduser().resolve() if a.output else root.parent / f"{root.name}_overleaf.zip"
    r = export_zip(root, out)
    print(f"作成: {r['out']}（{r['count']} ファイル・{r['size'] / 1e6:.1f} MB）")
    for eng in r["added_rc"]:
        print(f"  latexmkrc が無いので、{eng} で組む設定を zip に追加した")
    print("\nOverleaf: New Project → Upload Project にこの zip を入れる")
    if len(r["mains"]) > 1:
        print(f"  主文書が複数ある。Menu → Main document で選ぶこと: {', '.join(r['mains'])}")
    if r["nested_main"]:
        print("  注意: 主文書がサブフォルダにある。Overleaf は最上位の latexmkrc しか読まないので、"
              "主文書のあるディレクトリを export する方が確実")
    if r["too_big"]:
        print("  注意: 50 MB を超えている。Overleaf の Upload Project の上限を超える")


def cmd_clean(a) -> None:
    from .builder import clean
    tex = _main_of(a)
    _refuse_if_serving(tex, "画面で原稿を閉じてから消す")
    sys.exit(clean(tex))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="overleaf-compiler", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="\n".join(__doc__.split("\n")[2:]))
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("import", help="Overleaf の zip を展開する")
    s.add_argument("zip")
    s.add_argument("dest", nargs="?", help="展開先（省略時は data/<zip と同じ名前>）")
    s.add_argument("--data", help="ワークスペースの置き場（既定: overleaf_compiler/data）")
    s.set_defaults(fn=cmd_import)
    s = sub.add_parser("check", help="組んで、直すべき箇所を file:line で出す")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("--json", action="store_true", help="JSON で出す")
    s.set_defaults(fn=cmd_check)
    s = sub.add_parser("serve", help="ブラウザで PDF を開いて、クリックで直す")
    s.add_argument("path", nargs="?", help="原稿・原稿のフォルダ・ワークスペース（省略時はワークスペースの一覧）")
    s.add_argument("--data", help="ワークスペースの置き場（既定: overleaf_compiler/data）")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    s.add_argument("--web", action="store_true", help="アプリのウィンドウではなく、ブラウザのタブで開く")
    s.add_argument("--auto-stop", action="store_true", help="開いた画面が全部閉じたら終える（アプリから起こしたとき）")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("comments", help="PDF に付いたコメントを出す・解決済みにする")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("--all", action="store_true", help="解決済みのコメントも出す")
    s.add_argument("--json", action="store_true", help="JSON で出す")
    s.add_argument("--resolve", nargs="+", metavar="ID", help="解決済みにする（-m があれば返信も残す）")
    s.add_argument("--reopen", nargs="+", metavar="ID", help="未解決に戻す")
    s.add_argument("--reply", metavar="ID", help="返信する（-m で文を渡す）")
    s.add_argument("-m", "--message", help="返信の文（何をどう直したか）")
    s.add_argument("--author", default="Claude Code", help="返信・解決をした人の名前（既定: Claude Code）")
    s.add_argument("--data", help="ワークスペースの置き場（既定: overleaf_compiler/data）")
    s.set_defaults(fn=cmd_comments)
    s = sub.add_parser("build", help="1回だけ組む")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser("export", help="Overleaf に入れる zip を作る")
    s.add_argument("path", nargs="?", default=".")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("clean", help="中間生成物を消す")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_clean)
    from .launcher import cmd_app, cmd_stop
    s = sub.add_parser("app", help="アプリとして開く（サーバを裏で動かし、アプリのウィンドウで開く）")
    s.add_argument("--tab", action="store_true", help="ブラウザのタブで開く")
    s.add_argument("--background", action="store_true", help="サーバだけ起こしておく")
    s.set_defaults(fn=cmd_app)
    s = sub.add_parser("stop", help="裏で動いているサーバを止める")
    s.set_defaults(fn=cmd_stop)
    argv = sys.argv[1:] if argv is None else argv
    # サブコマンドを省いたら serve（引数なしなら data/ のワークスペース一覧を開く）
    if not argv or (argv[0] not in sub.choices and argv[0] not in ("-h", "--help")):
        argv = ["serve", *argv]
    a = ap.parse_args(argv)
    try:
        if a.cmd not in ("import", "stop"):
            ensure_texlive()
        a.fn(a)
    except ProjectError as e:
        sys.exit(f"overleaf-compiler: {e}")
