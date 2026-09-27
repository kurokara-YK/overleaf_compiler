"""ファイルの読み書きと、PDF 上の位置と .tex の行の対応（SyncTeX）。"""
from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

# エディタで開いて直せるファイル
EDITABLE_SUFFIXES = (".tex", ".bib", ".sty", ".cls", ".bst", ".bbx", ".cbx", ".cfg", ".def", ".clo",
                     ".ltx", ".txt", ".md")
EDITABLE_NAMES = ("latexmkrc", ".latexmkrc")
MAX_BYTES = 4 * 1024 * 1024


class SyncError(Exception):
    pass


class Conflict(SyncError):
    """開いたあとでファイルが外で変わっていた。今の内容を持たせて返す。"""

    def __init__(self, text: str, mtime: str):
        super().__init__("CONFLICT")
        self.text, self.mtime = text, mtime


def editable(path: Path) -> bool:
    return path.suffix in EDITABLE_SUFFIXES or path.name in EDITABLE_NAMES


def mtime(path: Path) -> str:
    """更新時刻（ナノ秒）。JavaScript の数値では桁が落ちるので文字列で渡す。"""
    return str(path.stat().st_mtime_ns)


def inside(path: Path, root: Path) -> Path:
    path = path.resolve()
    if root != path and root not in path.parents:
        raise SyncError(f"{path} は原稿のフォルダの外")
    return path


def read_file(path: Path, root: Path) -> dict:
    path = inside(path, root)
    if not editable(path):
        raise SyncError(f"{path.name} はエディタで開けない種類のファイル")
    if path.stat().st_size > MAX_BYTES:
        raise SyncError(f"{path.name} は大きすぎて開けない")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise SyncError(f"{path.name} は UTF-8 ではないので開けない（Overleaf は UTF-8 が前提）")
    return {"text": text, "mtime": mtime(path)}


def write_file(path: Path, text: str, base_mtime: str | None, root: Path) -> dict:
    """ファイル全体を書く。開いたときの更新時刻と違えば（外で直されていれば）書かずに Conflict。"""
    path = inside(path, root)
    if not editable(path):
        raise SyncError(f"{path.name} はエディタで開けない種類のファイル")
    if base_mtime is not None and path.exists() and mtime(path) != base_mtime:
        cur = read_file(path, root)
        raise Conflict(cur["text"], cur["mtime"])
    tmp = path.with_name(path.name + ".overleaf-compiler-tmp")
    tmp.write_bytes(text.encode("utf-8"))
    if path.exists():
        shutil.copymode(path, tmp)
    tmp.replace(path)  # 途中までしか書かれていないファイルを latexmk に読ませない
    return {"mtime": mtime(path)}


# ---------------------------------------------------------------- SyncTeX
def _synctex(args: list[str], cwd: Path) -> list[tuple[str, str]]:
    out = subprocess.run(["synctex", *args], cwd=cwd, capture_output=True, text=True,
                         errors="replace").stdout
    return [tuple(l.split(":", 1)) for l in out.splitlines() if ":" in l]  # type: ignore[misc]


def pdf_to_source(pdf: Path, page: int, x: float, y: float) -> tuple[Path, int]:
    """PDF のページ番号（1始まり）と左上原点の座標 [pt] から、.tex の絶対パスと行番号を返す。"""
    rec = dict(_synctex(["edit", "-o", f"{page}:{x:.2f}:{y:.2f}:{pdf.name}"], pdf.parent))
    if "Input" not in rec or "Line" not in rec:
        raise SyncError("この位置に対応するソースの行が無い（余白や図の中など）")
    return Path(rec["Input"]).resolve(), max(1, int(rec["Line"]))


def source_to_pdf(pdf: Path, src: Path, line: int) -> list[dict]:
    """.tex の1行が PDF 上のどこに出ているか（箱の一覧）を返す。"""
    boxes, cur = [], {}
    for k, v in _synctex(["view", "-i", f"{line}:0:{src}", "-o", pdf.name], pdf.parent):
        if k == "Page" and cur:
            boxes.append(cur)
            cur = {}
        if k in ("Page", "h", "v", "W", "H"):
            cur[k] = float(v)
    if cur:
        boxes.append(cur)
    # v はベースライン。上端 = v - H
    return [{"page": int(b["Page"]), "x": b["h"], "y": b["v"] - b["H"], "w": b["W"], "h": b["H"]}
            for b in boxes if {"Page", "h", "v", "W", "H"} <= b.keys() and b["W"] > 0]


def refine_line(path: Path, line: int, snippet: str, root: Path) -> int:
    """SyncTeX の行を、ダブルクリックした場所の文字で合わせ直す。

    SyncTeX は段落の終わりの行を返すことが多い。クリックした場所の前後の文字（snippet）を、
    その行の近くから探し、見つかった行を返す。見つからなければ元の行のまま。
    """
    try:
        lines = read_file(path, root)["text"].splitlines()
    except SyncError:
        return line
    squeeze = lambda t: "".join(t.split())
    snip = squeeze(snippet)
    cands = [snip] + ([snip[:len(snip) // 2], snip[len(snip) // 2:]] if len(snip) >= 6 else [])
    lo, hi = max(1, line - 40), min(len(lines), line + 5)
    for c in cands:
        if len(c) < 3:
            continue
        hits = [n for n in range(lo, hi + 1) if c in squeeze(lines[n - 1])]
        if hits:  # 同じ文字が複数の行にあれば、SyncTeX の行に近く、その手前にある行を選ぶ
            return min(hits, key=lambda n: (abs(line - n), n > line))
    return line


# ---------------------------------------------------------------- PDF 上で選んだ文字列の置き換え
def _squeeze(text: str) -> tuple[str, list[int]]:
    """空白と改行を除き、文字を NFKC で正規化した文字列と、各文字の元の位置。

    PDF の文字列とソースでは、改行の位置（PDF の行末とソースの行末）と空白が一致しないため、
    それらを除いて突き合わせる。合字（ﬁ）や全角・半角の違いも NFKC で吸収する。
    """
    chars, idx = [], []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        for c in unicodedata.normalize("NFKC", ch):
            if not c.isspace():
                chars.append(c)
                idx.append(i)
    return "".join(chars), idx


# LaTeX で特別な意味を持つ文字。PDF 上の普通の文章として打たれたものはエスケープする
_SPECIAL = re.compile(r"(?<!\\)([%&#_])")


def find_in_text(text: str, line: int, old: str) -> tuple[int, int] | None:
    """PDF 上の文字列 old が、ソースの文字列 text のどこにあるか（始まりと終わりの位置）。

    空白・改行・全角半角の違いは無視して突き合わせる。同じ文字列が複数あれば、line 行に一番近いもの。
    見つからなければ None（\\cite や数式など、PDF とソースで文字が違う部分）。
    """
    comp, idx = _squeeze(text)
    here = sum(len(l) for l in text.splitlines(keepends=True)[:max(line - 1, 0)])
    for variant in (old, re.sub(r"-\s*\n\s*", "", old)):  # 2つ目は行末のハイフネーションを戻したもの
        q, _ = _squeeze(variant)
        if not q:
            return None
        hits, pos = [], comp.find(q)
        while pos != -1:
            hits.append(pos)
            pos = comp.find(q, pos + 1)
        if hits:
            h = min(hits, key=lambda h: abs(idx[h] - here))
            return idx[h], idx[h + len(q) - 1] + 1
    return None


def replace_in_source(path: Path, line: int, old: str, new: str, root: Path) -> dict:
    """PDF 上で選んだ文字列 old を、ソースの中で探して new に置き換える。

    同じ文字列が複数あれば、SyncTeX が指した行に一番近いものを置き換える。
    見つからなければ（\\cite や数式など、PDF とソースで文字が違う部分）SyncError("NOT_FOUND")。
    """
    path = inside(path, root)
    cur = read_file(path, root)
    text = cur["text"]
    if not _squeeze(old)[0]:
        raise SyncError("選んだ文字が空")
    span = find_in_text(text, line, old)
    if not span:
        raise SyncError("NOT_FOUND")
    s, e = span
    new_src = _SPECIAL.sub(r"\\\1", new)
    r = write_file(path, text[:s] + new_src + text[e:], cur["mtime"], root)
    return {"line": text.count("\n", 0, s) + 1, "mtime": r["mtime"]}
