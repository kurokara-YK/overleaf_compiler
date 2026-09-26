"""overleaf-compiler — Overleaf の原稿をローカルで組み、PDF をクリックして直し、Overleaf へ戻す。

  overleaf-compiler                                  ブラウザで data/ のワークスペース一覧を開く
  overleaf-compiler import <overleaf.zip> [展開先]   Overleaf で Download した zip を data/ へ展開する
  overleaf-compiler serve  [原稿 | ワークスペース]   ブラウザで PDF を開く。文をクリックすると LaTeX を直せる
  overleaf-compiler check  <原稿>                    組んで、エラー・未定義の参照・はみ出しを file:line で出す
  overleaf-compiler build  <原稿>                    1回だけ組む（latexmk の出力をそのまま出す）
  overleaf-compiler export <原稿> [-o 出力.zip]      Overleaf の Upload Project に入れる zip を作る
  overleaf-compiler clean  <原稿>                    中間生成物を消す

<原稿> は主文書の .tex か、それを含むディレクトリ。
ワークスペースは data/ の下のフォルダ。その中に Overleaf から取り込んだ原稿を置く。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .project import ProjectError, detect_engine, ensure_texlive, find_main, has_latexmkrc


def _engine_note(tex: Path) -> str:
    if has_latexmkrc(tex.parent):
        return "latexmkrc に従う"
    return f"{detect_engine(tex)}（latexmkrc が無いので本文から推定）"


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


# ワークスペースの置き場。パッケージの隣の data/（overleaf_compiler/data）
DATA = Path(__file__).resolve().parent.parent / "data"


def _data(a) -> Path:
    return Path(a.data).expanduser().resolve() if getattr(a, "data", None) else DATA


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
    if tex:
        print(f"組版: {_engine_note(tex)}")
    serve(data, start, tex, a.port, not a.no_browser)


def _serve_running(tex: Path) -> int | None:
    """この原稿を serve が組んでいれば、そのポート番号を返す。"""
    import json
    import urllib.request
    from .server import STATE_FILE
    st = tex.parent / STATE_FILE
    try:
        port = json.loads(st.read_text())["port"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=1) as r:
            return port if json.load(r).get("tex") == str(tex) else None
    except (OSError, ValueError, KeyError):
        return None


def cmd_check(a) -> None:
    import json
    import time
    import urllib.request
    from .builder import build_once, failure_lines
    from .report import format_report, summarize
    tex = find_main(a.path)
    port = _serve_running(tex)
    rc, output = 0, ""
    if port:  # serve が -pvc で組んでいる。二重に latexmk を走らせると中間ファイルが壊れる
        time.sleep(1.5)  # 保存を latexmk が検出するまで（$sleep_time = 1）
        t0 = time.time()
        while time.time() - t0 < 600:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2) as r:
                if not json.load(r).get("building"):
                    break
            time.sleep(0.5)
    else:
        rc, output = build_once(tex, quiet=True)
    r = summarize(tex)
    if rc != 0:  # latexmk が失敗した。TeX のエラーが無ければ、文献処理などで止まっている
        r["ok"] = False
        r["other_failures"] = failure_lines(output) or ["latexmk が失敗した（overleaf-compiler build で詳しい出力を見る）"]
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else format_report(r))
    sys.exit(0 if r["ok"] else 1)


def cmd_build(a) -> None:
    from .builder import build_once
    tex = find_main(a.path)
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
    sys.exit(clean(find_main(a.path)))


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
    s.set_defaults(fn=cmd_serve)
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
    argv = sys.argv[1:] if argv is None else argv
    # サブコマンドを省いたら serve（引数なしなら data/ のワークスペース一覧を開く）
    if not argv or (argv[0] not in sub.choices and argv[0] not in ("-h", "--help")):
        argv = ["serve", *argv]
    a = ap.parse_args(argv)
    try:
        if a.cmd != "import":
            ensure_texlive()
        a.fn(a)
    except ProjectError as e:
        sys.exit(f"overleaf-compiler: {e}")
