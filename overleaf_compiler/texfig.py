"""Word・HTML・Markdown に書き出す前の下ごしらえ（pandoc が読めない部分を、読める形にする）。

  - \\input・\\include を展開する（章ファイルの中の図や表も扱えるように）
  - TikZ の図と、複雑な表（\\multicolumn・\\multirow・\\shortstack を使うもの）は、同じ文書クラスとプリアンブルで
    その部分だけを LaTeX に組ませて PNG にし、\\includegraphics に置き換える（見出しの \\caption・\\label は残す）
  - 簡単な数式（$\\pm$・$-$ など）と \\, を普通の文字にする
  - よくある学会のクラスの題目・著者・概要の命令（\\name・\\abst など）を、pandoc が分かる形にする
組んだ PNG は中身が変わるまで使い回す（~/.cache/overleaf-compiler/word/figs）。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .project import latexmk_args

failed = 0   # 直前の figures_to_images で組めなかった図・表の数（Word の表示を作り置きするか決める）
FIG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "overleaf-compiler" / "word" / "figs"
_SIMPLE_MATH = {r"\pm": "±", "-": "−", "+": "+", r"\times": "×", r"\mp": "∓", r"\sim": "〜", r"\circ": "°",
                r"\degree": "°", r"\cdot": "・", r"\leq": "≤", r"\geq": "≥", r"\le": "≤", r"\ge": "≥", r"\approx": "≈"}
_COMPLEX_TABLE = re.compile(r"\\(?:multicolumn|multirow|shortstack|makecell)\b")


def group(text: str, i: int) -> int:
    """text[i] の { に対応する } の次の位置。対応しなければ -1。"""
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def expand_inputs(text: str, base: Path, depth: int = 0) -> str:
    if depth > 8:
        return text
    def rep(m):
        name = m.group(2).strip()
        for cand in (base / name, base / f"{name}.tex"):
            if cand.is_file():
                return expand_inputs(strip_comments(cand.read_text(errors="replace")), base, depth + 1)
        return m.group(0)
    return re.sub(r"\\(input|include)\s*\{([^}]+)\}", rep, text)


def simple_text(text: str) -> str:
    """$\\pm$ のような1記号だけの数式と、\\, などの空白を普通の文字にする（Word の数式にすると崩れて見えるため）。"""
    for k, v in _SIMPLE_MATH.items():
        text = text.replace(f"${k}$", v).replace(f"${{{k}}}$", v)
    text = re.sub(r"\$\\pm\s*(\d+(?:\.\d+)?)\$", r"±\1", text)
    return text.replace("\\,", "\u2009").replace("\\;", " ").replace("\\:", " ")


def title_macros(text: str) -> str:
    """学会のクラスにある題目・著者・概要の命令を、pandoc が分かる \\author・abstract にする。"""
    if not re.search(r"\\author\s*[\[{]", text):
        m = re.search(r"\\(?:name|jname|authors?jp)\s*\{", text)
        if m:
            e = group(text, m.end() - 1)
            if e > 0:
                text = text[:m.start()] + "\\author{" + text[m.end():e - 1] + "}" + text[e:]
    if "\\begin{abstract}" not in text:
        m = re.search(r"\\(?:abst|jabstract|abstractjp)\s*\{", text.split("\\begin{document}")[-1])
        if m:
            off = text.find("\\begin{document}") + len("\\begin{document}") if "\\begin{document}" in text else 0
            s, e = off + m.start(), group(text, off + m.end() - 1)
            if e > 0:
                body = text[off + m.end():e - 1]
                text = text[:s] + text[e:]
                text = re.sub(r"\\maketitle", lambda _: "\\maketitle\n\\begin{abstract}\n" + body + "\n\\end{abstract}\n", text, count=1) \
                    if "\\maketitle" in text else text.replace("\\begin{document}", "\\begin{document}\n\\begin{abstract}\n" + body + "\n\\end{abstract}\n", 1)
    return text


def _render(tex: Path, preamble: str, body: str) -> Path | None:
    """preamble の文書で body だけを組んで、余白を切った PNG にする。組めなければ None。"""
    h = hashlib.sha1((preamble + "\0" + body + "\0" + _assets_sig(tex.parent, body)).encode()).hexdigest()[:20]
    png = FIG_CACHE / f"{h}.png"
    if png.exists():
        return png
    FIG_CACHE.mkdir(parents=True, exist_ok=True)
    out = FIG_CACHE / f"build-{h}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    # 原稿のフォルダには何も書かない。キャッシュの中で組み、原稿のフォルダ（画像・クラスファイル）は TEXINPUTS で読む
    src = out / f"ocfig-{h}.tex"
    src.write_text(preamble + "\n\\begin{document}\n\\pagestyle{empty}\\thispagestyle{empty}\n\\noindent\n"
                   + body + "\n\\end{document}\n")
    rc = tex.parent / "latexmkrc"
    env = {**os.environ, "max_print_line": "10000", "TEXINPUTS": f"{tex.parent}//:" + os.environ.get("TEXINPUTS", ""),
           "BIBINPUTS": f"{tex.parent}:"}
    try:
        subprocess.run(["latexmk", "-g", "-interaction=nonstopmode", *(["-r", str(rc)] if rc.is_file() else []),
                        *latexmk_args(tex), src.name], cwd=out, capture_output=True, timeout=180, env=env)
        pdf = out / f"{src.stem}.pdf"
        if not pdf.exists():
            return None
        crop = out / "crop.pdf"
        subprocess.run(["pdfcrop", "--margins", "4", str(pdf), str(crop)], capture_output=True, timeout=60, cwd=out)
        subprocess.run(["pdftoppm", "-png", "-singlefile", "-f", "1", "-l", "1", "-r", "300",
                        str(crop if crop.exists() else pdf), str(png.with_suffix(""))], capture_output=True, timeout=60)
        return png if png.exists() else None
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _assets_sig(base: Path, body: str) -> str:
    """図の中で使っている画像の更新時刻（画像を差し替えたら組み直す）。"""
    sig = []
    for name in re.findall(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", body):
        for f in base.glob(name + "*") if "*" not in name else []:
            if f.is_file():
                sig.append(f"{f}:{f.stat().st_mtime_ns}")
    return "|".join(sorted(sig))


def figures_to_images(tex: Path, text: str) -> str:
    """TikZ の図と複雑な表を、組んだ PNG の \\includegraphics に置き換える。"""
    global failed
    failed = 0
    preamble = tex.read_text(errors="replace").split("\\begin{document}")[0]
    if "\\documentclass" not in preamble:
        return text
    jobs = []   # (始まり, 終わり, 環境の名前, 中身, caption と label)
    for m in re.finditer(r"\\begin\{(figure\*?|table\*?)\}(\[[^\]]*\])?", text):
        env = m.group(1)
        end = text.find(f"\\end{{{env}}}", m.end())
        if end < 0:
            continue
        inner = text[m.end():end]
        is_fig = env.startswith("figure")
        if is_fig and "tikzpicture" not in inner:
            continue
        if not is_fig and not _COMPLEX_TABLE.search(inner):
            continue
        keep, body = [], inner
        for cmd in ("caption", "label"):   # 見出しと参照の名前は Word 側に残す（図の中からは外す）
            for cm in list(re.finditer(rf"\\{cmd}\s*(\[[^\]]*\])?\{{", body))[::-1]:
                e = group(body, cm.end() - 1)
                if e > 0:
                    keep.insert(0, body[cm.start():e])
                    body = body[:cm.start()] + body[e:]
        jobs.append((m.start(), end + len(f"\\end{{{env}}}"), env, body, keep))
    if not jobs:
        return text
    with ThreadPoolExecutor(4) as ex:
        pngs = list(ex.map(lambda j: _render(tex, preamble, j[3]), jobs))
    failed = pngs.count(None)
    for (s, e, env, _body, keep), png in sorted(zip(jobs, pngs), key=lambda x: -x[0][0]):
        if not png:
            continue
        caps = "\n".join(k for k in keep if k.startswith("\\caption")) + "\n" + "\n".join(k for k in keep if k.startswith("\\label"))
        img = f"\\centering\n\\includegraphics[width=\\linewidth]{{{png}}}\n"
        new = f"\\begin{{{env}}}\n" + (caps + "\n" + img if env.startswith("table") else img + caps) + f"\n\\end{{{env}}}"
        text = text[:s] + new + text[e:]
    return text


def prepare(tex: Path, text: str) -> str:
    text = expand_inputs(text, tex.parent)
    text = title_macros(text)
    text = figures_to_images(tex, text)
    return simple_text(text)
