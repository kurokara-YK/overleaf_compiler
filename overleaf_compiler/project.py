"""原稿のディレクトリの扱い：主文書の特定、組版エンジンの推定、TeX Live の場所。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Overleaf へ出す zip に入れないもの（中間生成物・バックアップ・zip）
EXCLUDE_SUFFIXES = (
    ".aux", ".bbl", ".bcf", ".blg", ".dvi", ".fdb_latexmk", ".fls", ".log",
    ".out", ".run.xml", ".synctex.gz", ".synctex(busy)", ".toc", ".lof", ".lot",
    ".nav", ".snm", ".xdv", ".bak", "-SAVE-ERROR", ".zip",
)

_DOCCLASS = re.compile(r"^[ \t]*\\documentclass\s*(\[[^\]]*\])?\s*\{([^}]*)\}", re.M)


class ProjectError(Exception):
    pass


def ensure_texlive() -> None:
    """latexmk が PATH に無ければ ~/texlive/<年>/bin/<arch> を前に足す。"""
    if shutil.which("latexmk"):
        return
    bins = sorted(Path.home().glob("texlive/*/bin/*"), reverse=True)
    for b in bins:
        if (b / "latexmk").exists():
            os.environ["PATH"] = f"{b}{os.pathsep}{os.environ['PATH']}"
            return
    raise ProjectError("latexmk が見つからない。TeX Live を入れること（README 参照）")


def is_main(tex: Path) -> bool:
    try:
        return bool(_DOCCLASS.search(tex.read_text(errors="ignore")))
    except OSError:
        return False


def find_main(path: str | Path) -> Path:
    """.tex ならそれを、ディレクトリなら \\documentclass を持つ .tex を1つ探す。"""
    p = Path(path).expanduser().resolve()
    if p.is_file():
        if p.suffix != ".tex":
            raise ProjectError(f"{p} は .tex ではない")
        return p
    if not p.is_dir():
        raise ProjectError(f"{p} が無い")
    cands = [t for t in sorted(p.glob("*.tex")) if is_main(t) and not t.name.startswith("_")]
    if not cands:  # 直下に無ければ1段下まで探す（zip がフォルダで包まれている場合）
        cands = [t for t in sorted(p.glob("*/*.tex")) if is_main(t) and not t.name.startswith("_")]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        raise ProjectError(f"{p} に \\documentclass を含む .tex が無い")
    names = "\n".join(f"  {c.relative_to(p)}" for c in cands)
    raise ProjectError(f"主文書の候補が複数ある。ファイルで指定すること:\n{names}")


def has_latexmkrc(d: Path) -> bool:
    return (d / "latexmkrc").is_file() or (d / ".latexmkrc").is_file()


def detect_engine(tex: Path) -> str:
    """latexmkrc が無いときに本文から推定する（Overleaf のコンパイラ設定は zip に入らないため）。"""
    src = tex.read_text(errors="ignore")
    code = "\n".join(l.split("%", 1)[0] for l in src.splitlines())  # コメントを除く
    m = _DOCCLASS.search(code)
    opts, cls = ((m.group(1) or ""), m.group(2).strip()) if m else ("", "")
    if "luatexja" in code or cls.startswith("ltj"):
        return "lualatex"
    if re.search(r"\\usepackage(\[[^\]]*\])?\{[^}]*(fontspec|xeCJK|zxjatype)", code):
        return "xelatex"
    if "uplatex" in opts or re.fullmatch(r"u[a-z]*(article|report|book)", cls) \
            or cls == "jlreq" or cls.startswith("bxjs"):
        return "uplatex"
    if re.fullmatch(r"(js|j|t)[a-z]*(article|report|book)", cls):
        return "platex"
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", code):
        return "lualatex"  # 和文があるのに和文クラスでない → LuaLaTeX なら通ることが多い
    return "pdflatex"


_DVIPDF = "$dvipdf = 'dvipdfmx %O -o %D %S';"

# latexmkrc が無い原稿を Overleaf へ出すときに同梱する設定（Overleaf も latexmkrc を読む）
LATEXMKRC = {
    "uplatex": "$latex = 'uplatex %O %S';\n$bibtex = 'upbibtex %O %B';\n" + _DVIPDF + "\n$pdf_mode = 3;\n",
    "platex": "$latex = 'platex %O %S';\n$bibtex = 'pbibtex %O %B';\n" + _DVIPDF + "\n$pdf_mode = 3;\n",
    "lualatex": "$pdf_mode = 4;\n",
    "xelatex": "$pdf_mode = 5;\n",
}


def latexmk_args(tex: Path) -> list[str]:
    """latexmk に渡すエンジン指定。latexmkrc があればそちらに任せる。"""
    if has_latexmkrc(tex.parent):
        return []
    eng = detect_engine(tex)
    if eng in ("uplatex", "platex"):
        bib = "upbibtex" if eng == "uplatex" else "pbibtex"
        return [f"-latex={eng}", "-e", _DVIPDF, "-e", f"$bibtex = '{bib} %O %B';", "-pdfdvi"]
    return {"lualatex": ["-lualatex"], "xelatex": ["-xelatex"]}.get(eng, ["-pdf"])


def edit_root(tex: Path) -> Path:
    """ブラウザから書き換えてよい範囲。git の中ならリポジトリ全体、そうでなければ主文書のディレクトリ。"""
    try:
        out = subprocess.run(["git", "-C", str(tex.parent), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return Path(out).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return tex.parent


# ---------------------------------------------------------------- ワークスペースの中の原稿の一覧
_SKIP_DIRS = {"node_modules", "__pycache__", "overleaf_compiler"}
_GENERATED = re.compile(r"直接編集しない|DO NOT EDIT|do not edit", re.I)


def _walk(root: Path, depth: int = 6):
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return
    for p in entries:
        if p.name.startswith((".", "_")):
            continue
        if p.is_dir():
            if depth > 0 and p.name not in _SKIP_DIRS and not p.name.endswith(".bak"):
                yield from _walk(p, depth - 1)
        else:
            yield p


def list_tree(tex: Path) -> list[dict]:
    """原稿のフォルダのファイルツリー（Overleaf の左のファイル一覧に当たる）。

    人が入れたファイルだけを出す。中間生成物・組んだ PDF・バックアップ・隠しファイルは出さない。
    """
    from .sync import editable
    base = tex.parent
    outputs = {m.with_suffix(".pdf") for m in base.glob("*.tex") if is_main(m)}
    items: list[dict] = []

    def walk(d: Path, depth: int) -> None:
        for p in sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if p.name.startswith(".") and p.name != ".latexmkrc":
                continue
            rel = str(p.relative_to(base))
            if p.is_dir():
                if p.name in _SKIP_DIRS:
                    continue
                items.append({"path": rel, "dir": True})
                if depth > 0:
                    walk(p, depth - 1)
            elif not (p.name.endswith(EXCLUDE_SUFFIXES) or p in outputs
                      or p.name.endswith(".overleaf-compiler-tmp")):
                items.append({"path": rel, "dir": False, "editable": editable(p)})

    walk(base, 6)
    return items


# ---------------------------------------------------------------- ワークスペースの中の原稿フォルダの一覧
def _main_info(t: Path) -> dict:
    head = t.read_text(errors="ignore")[:4000]
    return {"tex": str(t), "name": t.name, "generated": bool(_GENERATED.search(head)),
            "engine": "latexmkrc" if has_latexmkrc(t.parent) else detect_engine(t)}


def _default_main(folder: Path, mains: list[Path]) -> Path | None:
    """主文書が複数あるときに、どれを開くかを決められれば返す。決められなければ None（人が選ぶ）。"""
    if len(mains) == 1:
        return mains[0]
    for m in mains:  # Overleaf の既定の名前と、フォルダと同じ名前
        if m.name == "main.tex" or m.stem == folder.name:
            return m
    return None


def list_folders(workspace: Path) -> list[dict]:
    """ワークスペースの中の原稿フォルダを挙げる。Overleaf の1プロジェクト＝1フォルダとして扱う。

    - 直下に主文書（\\documentclass を含む .tex）があるフォルダ
    - ワークスペース直下のフォルダは、主文書が無くても挙げる（中身が分かるように）
    """
    mains_by_dir: dict[Path, list[Path]] = {}
    for t in _walk(workspace):
        if t.suffix == ".tex" and is_main(t):
            mains_by_dir.setdefault(t.parent, []).append(t)
    dirs = set(mains_by_dir)
    for d in sorted(workspace.iterdir()) if workspace.is_dir() else []:
        if d.is_dir() and not d.name.startswith((".", "_")) and d.name not in _SKIP_DIRS \
                and not any(x == d or x.is_relative_to(d) for x in mains_by_dir):
            dirs.add(d)
    return [_folder_info(d, workspace, sorted(mains_by_dir.get(d, []))) for d in sorted(dirs)]


def _folder_info(d: Path, base: Path, mains: list[Path] | None = None) -> dict:
    """原稿のフォルダ1つの情報。パスは base からの相対パスで返す（画面に絶対パスを出さない）。"""
    if mains is None:
        mains = [t for t in sorted(d.glob("*.tex")) if is_main(t) and not t.name.startswith("_")]
    default = _default_main(d, mains)
    # 拡張子が .tex でない LaTeX 文書（.txt に貼り付けたものなど）
    other = [f for f in sorted(d.glob("*")) if f.is_file() and f.suffix in (".txt", ".ltx", ".latex")
             and is_main(f)] if not mains else []
    files = [f for f in d.iterdir() if f.is_file()]
    rel = lambda p: str(p.relative_to(base))
    return {
        "dir": rel(d) if d != base else "", "name": d.name,
        "mains": [{**_main_info(m), "tex": rel(m)} for m in mains],
        "default": rel(default) if default else None,
        "not_tex": [{"file": rel(f), "name": f.name} for f in other],
        "mtime": max((f.stat().st_mtime for f in files), default=d.stat().st_mtime),
    }


def browse(data: Path, rel: str) -> dict:
    """data の中の1つのフォルダの中身。原稿のフォルダ（主文書がある）と、ただのフォルダを分けて返す。"""
    data = data.resolve()
    d = (data / rel).resolve() if rel else data
    if d != data and data not in d.parents:
        raise ProjectError(f"{rel} は data の外")
    if not d.is_dir():
        raise ProjectError(f"{rel} が無い")
    entries = []
    for p in sorted(d.iterdir(), key=lambda p: p.name.lower()):
        if not p.is_dir() or p.name.startswith((".", "_")) or p.name in _SKIP_DIRS:
            continue
        info = _folder_info(p, data)
        if info["mains"] or info["not_tex"]:
            entries.append({**info, "kind": "project"})
        else:
            inner = [f for f in list_folders(p) if f["mains"] or f["not_tex"]]
            entries.append({**info, "kind": "folder", "count": len(inner),
                            "mtime": max([f["mtime"] for f in inner] + [info["mtime"]])})
    return {"path": str(d.relative_to(data)) if d != data else "", "entries": entries}


def rename_to_tex(path: Path, workspace: Path) -> Path:
    """LaTeX の中身を持つ .txt などを .tex に名前を変える（画面のボタンを押したときだけ）。"""
    path = path.resolve()
    if not path.is_relative_to(workspace.resolve()) or not path.is_file() or not is_main(path):
        raise ProjectError(f"{path.name} は LaTeX の文書ではない")
    dest = path.with_suffix(".tex")
    if dest.exists():
        raise ProjectError(f"{dest.name} は既にある")
    path.rename(dest)
    return dest
