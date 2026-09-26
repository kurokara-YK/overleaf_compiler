"""Overleaf との受け渡し。Download した zip の展開と、Upload Project に入れる zip の作成。"""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

from .project import EXCLUDE_SUFFIXES, LATEXMKRC, ProjectError, detect_engine, has_latexmkrc, is_main

OVERLEAF_UPLOAD_LIMIT = 50 * 1024 * 1024  # Upload Project の上限（50 MB）


def import_zip(zip_path: Path, dest: Path) -> list[Path]:
    """zip を dest へ展開し、主文書の候補を返す。既にあるディレクトリには展開しない。"""
    if not zip_path.is_file():
        raise ProjectError(f"{zip_path} が無い")
    if dest.exists():
        raise ProjectError(f"{dest} は既にある。上書きはしないので、別名で展開して差分を見ること")
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():  # zip の外へ書き出す名前（../ など）を拒む
            if not (dest / n).resolve().is_relative_to(dest.resolve()):
                raise ProjectError(f"zip に不正なパスがある: {n}")
        dest.mkdir(parents=True)
        z.extractall(dest)
    return [t for t in sorted(dest.rglob("*.tex")) if is_main(t)]


def _files(root: Path) -> list[Path]:
    """zip に入れるファイル。git の中なら .gitignore に従う。"""
    try:
        # 外側のリポジトリが原稿のフォルダごと無視している（data/ など）なら、git の一覧は空になる
        if subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "."], capture_output=True).returncode == 0:
            raise FileNotFoundError
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "."],
            capture_output=True, check=True).stdout.decode()
        files = [root / f for f in out.split("\0") if f and (root / f).is_file()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = [f for f in root.rglob("*") if f.is_file()]
    return sorted(files)


def _excluded(rel: Path, outputs: set[Path]) -> bool:
    if any(part.startswith(".") and part not in (".latexmkrc",) for part in rel.parts):
        return True  # .git や隠しファイル（.latexmkrc だけは Overleaf が読むので入れる）
    if any(part == "__pycache__" for part in rel.parts):
        return True
    return rel.name.endswith(EXCLUDE_SUFFIXES) or rel in outputs


def export_zip(root: Path, out: Path) -> dict:
    """root の構成のまま zip にする。Overleaf の Upload Project にそのまま入れられる。"""
    root = root.resolve()
    files = [f for f in _files(root) if f.resolve() != out.resolve()]
    mains = [f for f in files if f.suffix == ".tex" and is_main(f) and not f.name.startswith("_")]
    outputs = {f.relative_to(root).with_suffix(".pdf") for f in mains}  # 組んだ PDF は入れない
    added_rc = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            rel = f.relative_to(root)
            if not _excluded(rel, outputs):
                z.write(f, rel.as_posix())  # 非ASCII の名前には zipfile が UTF-8 の旗を立てる
        # latexmkrc が無い和文原稿は、Overleaf の既定（pdfLaTeX）では通らない。設定を同梱する。
        # Overleaf が読むのはプロジェクト最上位の latexmkrc だけなので、最上位に置く
        engines = {detect_engine(m) for m in mains}
        if not has_latexmkrc(root) and len(engines) == 1 and (eng := engines.pop()) in LATEXMKRC:
            z.writestr("latexmkrc", f"# overleaf-compiler export が追加（{eng}）。Overleaf もこの設定で組む\n" + LATEXMKRC[eng])
            added_rc.append(eng)
        names = z.namelist()
    return {"out": out, "count": len(names), "size": out.stat().st_size,
            "mains": [m.relative_to(root).as_posix() for m in mains], "added_rc": added_rc,
            "nested_main": any(m.parent != root for m in mains),
            "too_big": out.stat().st_size > OVERLEAF_UPLOAD_LIMIT}
