"""Word・Markdown・HTML への書き出し（pandoc に任せる。数式や表、独自のクラスの体裁は崩れることがある）。"""
from __future__ import annotations

import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import texfig
from .sync import SyncError

import hashlib
import os
import re
import zipfile

# 書き出す形式（Overleaf の「ダウンロード」と同じ並び）。形式 → (pandoc の -t, 拡張子, 追加の引数)
EXPORTS = {"docx": ("docx", ".docx", ["--number-sections"]), "md": ("gfm", ".md", []),
           "html": ("html5", ".html", ["--standalone", "--embed-resources", "--mathjax", "--number-sections"])}


_HEADS = r"(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph|maketitle)"


def source(tex: Path) -> str:
    r"""pandoc に渡す主文書の文字。原稿のフォルダにある自前の .sty は読ませない（\def\section{\@startsection…} などの
    体裁の定義を pandoc が展開して、見出しが「startsection section1@…」のような文字になるため）。
    見出しの命令を作り直している行も外す。"""
    text = tex.read_text(errors="replace")
    def pkg(m):
        names = [n.strip() for n in m.group(2).split(",")]
        local = [n for n in names if (tex.parent / f"{n}.sty").is_file()]
        if not local:
            return m.group(0)
        rest = [n for n in names if n not in local]
        return (f"\\usepackage{m.group(1) or ''}{{{','.join(rest)}}}" if rest else "") + f"% (overleaf-compiler: {','.join(local)} は pandoc に読ませない)"
    text = re.sub(r"\\usepackage(\[[^\]]*\])?\{([^}]*)\}", pkg, text)
    text = re.sub(r"^[^%\n]*\\(?:def|(?:re)?newcommand\*?\{?|let)\s*\\" + _HEADS + r"\b.*$", "% (overleaf-compiler: 見出しの定義は pandoc に読ませない)", text, flags=re.M)
    return texfig.prepare(tex, text)   # \input の展開・TikZ の図と複雑な表の画像化・簡単な数式など


def available() -> bool:
    return bool(shutil.which("pandoc"))


def export(tex: Path, fmt: str) -> tuple[str, bytes, str]:
    """主文書 tex を fmt に書き出し、(ファイル名, 中身, 種類) を返す。"""
    if fmt not in EXPORTS:
        raise SyncError(f"{fmt} には書き出せない")
    if not available():
        raise SyncError("pandoc が無いので書き出せない（bash install.sh で入る）")
    to, ext, extra = EXPORTS[fmt]
    if fmt == "docx":   # Word は、原稿の体裁（A4・2段組など）に寄せた .docx（右のプレビューと同じもの）
        with tempfile.TemporaryDirectory() as d:
            out = make_docx(tex, Path(d) / (tex.stem + ".docx"))
            return out.name, out.read_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / (tex.stem + ext)
        r = subprocess.run(["pandoc", "-f", "latex", "-t", to, *extra, "--resource-path=.", "-o", str(out)],
                           cwd=tex.parent, capture_output=True, text=True, errors="replace", input=source(tex))
        if r.returncode != 0 or not out.exists():
            raise SyncError("pandoc で書き出せなかった: " + (r.stderr.strip().splitlines() or [""])[-1])
        return out.name, out.read_bytes(), mimetypes.guess_type(out.name)[0] or "application/octet-stream"


# ---- 右のプレビュー（PDF の代わりに Word・Markdown・HTML で見る）----
_cache: dict[tuple, dict] = {}


def preview(tex: Path, fmt: str) -> dict:
    """主文書を fmt に変換して、画面に出す HTML（Markdown は Markdown の文字）を返す。原稿が変わるまで覚えておく。

    Word は一度 .docx にしてから HTML に戻す（Word で開いたときに入っている中身に近い）。画像は埋め込む。
    """
    if fmt not in EXPORTS:
        raise SyncError(f"{fmt} では見られない")
    if not available():
        raise SyncError("pandoc が無いので見られない（bash install.sh で入る）")
    sig = (str(tex), fmt, max((f.stat().st_mtime_ns for f in tex.parent.rglob("*") if f.suffix in (".tex", ".bib", ".sty", ".cls")
                               or f.suffix.lower() in (".png", ".jpg", ".jpeg")), default=0))
    if sig in _cache:
        return _cache[sig]
    run = lambda args, inp=None: subprocess.run(["pandoc", *args], cwd=tex.parent, capture_output=True, text=True,
                                                 errors="replace", input=inp, timeout=120)
    html_args = ["-t", "html5", "--standalone", "--embed-resources", "--mathml", "--resource-path=.", "--number-sections",
                 "--metadata", "pagetitle=preview"]
    with tempfile.TemporaryDirectory() as d:
        if fmt == "md":
            r = run(["-f", "latex", "-t", "gfm", "--resource-path=."], source(tex))
            out = {"markdown": r.stdout}
        elif fmt == "docx":
            docx = Path(d) / "out.docx"
            r = run(["-f", "latex", "-t", "docx", "--resource-path=.", "-o", str(docx)], source(tex))
            if r.returncode == 0:
                r = run(["-f", "docx", *html_args, str(docx)])
            out = {"html": r.stdout}
        else:
            r = run(["-f", "latex", *html_args], source(tex))
            out = {"html": r.stdout}
    if r.returncode != 0:
        raise SyncError("pandoc で変換できなかった: " + (r.stderr.strip().splitlines() or [""])[-1])
    out["warnings"] = [l for l in r.stderr.splitlines() if l.strip()][:20]
    _cache.clear()
    _cache[sig] = out
    return out


# ---- Word：原稿の体裁に寄せた .docx と、それをページに組んだ PDF ----
# pandoc は文書クラスの体裁（2段組・余白など）を持ってこないので、.docx の中身（XML）を直して寄せる。
#   用紙は A4、余白 20 mm。原稿が2段組（\documentclass の twocolumn か、原稿のフォルダのクラスファイル）なら、
#   最初の見出しより前（題目・著者・概要）は1段、そこから2段にする。字は BIZ UDP 明朝と Times New Roman、見出しは BIZ UDP ゴシックと Arial
#   （Windows にも入っているので、渡した相手の Word でも同じ字で出る）
MINCHO, GOTHIC = "BIZ UDP明朝", "BIZ UDPゴシック"   # 日本語。英数字は Times New Roman・Arial
WORD_VERSION = 4   # 作り方を変えたら上げる（前に組んだものを使わない）
WORD_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "overleaf-compiler" / "word"


def two_column(tex: Path) -> bool:
    head = tex.read_text(errors="ignore").split("\\begin{document}")[0]
    if re.search(r"\\documentclass\s*\[[^\]]*twocolumn", head) or "\\twocolumn" in head:
        return True
    m = re.search(r"\\documentclass\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}", head)
    cls = tex.parent / f"{m.group(1).strip()}.cls" if m else None
    return bool(cls and cls.is_file() and "twocolumn" in cls.read_text(errors="ignore"))


def _sect(cols: int, final: bool) -> str:
    c = f'<w:cols w:num="{cols}" w:space="454"/>' if cols > 1 else '<w:cols w:space="454"/>'
    return (f'<w:sectPr>{"" if not final else ""}<w:type w:val="continuous"/><w:pgSz w:w="11906" w:h="16838"/>'
            f'<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/>{c}</w:sectPr>')


def _fonts(face: str) -> str:
    latin = "Arial" if face == GOTHIC else "Times New Roman"
    return f'<w:rFonts w:ascii="{latin}" w:hAnsi="{latin}" w:eastAsia="{face}" w:cs="{latin}"/>'


def make_docx(tex: Path, out: Path) -> Path:
    if not available():
        raise SyncError("pandoc が無いので書き出せない（bash install.sh で入る）")
    r = subprocess.run(["pandoc", "-f", "latex", "-t", "docx", "--resource-path=.", "--number-sections", "-o", str(out)],
                       cwd=tex.parent, capture_output=True, text=True, errors="replace", timeout=120, input=source(tex))
    if r.returncode != 0 or not out.exists():
        raise SyncError("pandoc で書き出せなかった: " + (r.stderr.strip().splitlines() or [""])[-1])
    two = two_column(tex)
    with zipfile.ZipFile(out) as z:
        files = {n: z.read(n) for n in z.namelist()}
    doc = files["word/document.xml"].decode()
    # 本文の最後の節：A4・余白・段の数
    i = doc.rfind("<w:sectPr")
    if i >= 0:
        j = doc.find("/>", i) + 2 if doc.startswith("<w:sectPr />", i) or doc.startswith("<w:sectPr/>", i) else doc.find("</w:sectPr>", i) + 11
        doc = doc[:i] + _sect(2 if two else 1, True) + doc[j:]
    else:
        doc = doc.replace("</w:body>", _sect(2 if two else 1, True) + "</w:body>")
    if two:   # 最初の見出しの直前の段落で節を切り、そこまで（題目・概要）を1段にする
        h = re.search(r'<w:pStyle w:val="Heading\d"\s*/>', doc)
        if h:
            pstart = doc.rfind("<w:p>", 0, h.start())
            pstart = max(pstart, doc.rfind("<w:p ", 0, h.start()))
            prev_end = doc.rfind("</w:p>", 0, pstart)
            if prev_end > 0:
                prev_start = max(doc.rfind("<w:p>", 0, prev_end), doc.rfind("<w:p ", 0, prev_end))
                seg = doc[prev_start:prev_end]
                brk = _sect(1, False)
                if "<w:pPr>" in seg:
                    seg = seg.replace("</w:pPr>", brk + "</w:pPr>", 1) if "</w:pPr>" in seg else seg.replace("<w:pPr/>", f"<w:pPr>{brk}</w:pPr>", 1)
                else:
                    seg = re.sub(r"^(<w:p(?:\s[^>]*)?>)", lambda m: m.group(1) + f"<w:pPr>{brk}</w:pPr>", seg, count=1)
                doc = doc[:prev_start] + seg + doc[prev_end:]
    files["word/document.xml"] = doc.encode()
    st = files["word/styles.xml"].decode()
    st = re.sub(r"<w:rPrDefault>\s*<w:rPr>.*?</w:rPr>", lambda m: "<w:rPrDefault><w:rPr>" + _fonts(MINCHO)
                + f'<w:sz w:val="{19 if two else 21}"/><w:szCs w:val="{19 if two else 21}"/><w:lang w:val="en-US" w:eastAsia="ja-JP"/></w:rPr>',
                st, count=1, flags=re.S)
    st = st.replace('<w:spacing w:after="200" />', '<w:spacing w:after="40" w:line="300" w:lineRule="auto"/>', 1)

    def style(m):   # 見出し・題目はゴシックで黒、ほかの文字のテーマの字は明朝に
        blk = m.group(0)
        face = GOTHIC if re.search(r'w:styleId="(Heading\d|Title|Subtitle|Author|AbstractTitle)"', blk) else MINCHO
        blk = re.sub(r"<w:rFonts[^>]*/>", _fonts(face), blk)
        blk = re.sub(r"<w:color [^>]*/>", '<w:color w:val="000000"/>', blk)
        sid = re.search(r'w:styleId="([^"]+)"', blk).group(1)
        size = {"Title": 32, "Subtitle": 24, "Author": 22, "Heading1": 24, "Heading2": 21, "Heading3": 20}.get(sid)
        if size:   # 文字の大きさ（半ポイント）。題目・著者は真ん中に
            blk = re.sub(r"<w:szCs?\s[^>]*/>", "", blk)
            blk = blk.replace("</w:rPr>", f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>', 1) if "</w:rPr>" in blk \
                else blk.replace("</w:style>", f'<w:rPr><w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr></w:style>')
        if sid in ("Title", "Subtitle", "Author", "Date", "AbstractTitle"):
            blk = blk.replace("</w:pPr>", '<w:jc w:val="center"/></w:pPr>', 1) if "</w:pPr>" in blk \
                else blk.replace("<w:rPr>", '<w:pPr><w:jc w:val="center"/></w:pPr><w:rPr>', 1)
        if sid.startswith("Heading"):   # 見出しの前後の空きを詰める
            blk = re.sub(r'<w:spacing [^>]*/>', '<w:spacing w:before="160" w:after="60"/>', blk)
        return blk
    st = re.sub(r"<w:style [^>]*>.*?</w:style>", style, st, flags=re.S)
    files["word/styles.xml"] = st.encode()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return out


def word_pdf(tex: Path) -> Path:
    """原稿の体裁に寄せた .docx を、LibreOffice でページに組んだ PDF（Word で開いたときの見え方）。原稿が変わるまで使い回す。"""
    if not shutil.which("soffice"):
        raise SyncError("LibreOffice が無いので、Word の見え方を出せない（sudo apt install libreoffice）")
    sig = hashlib.sha1(repr((WORD_VERSION, str(tex), sorted((str(f), f.stat().st_mtime_ns) for f in tex.parent.rglob("*")
                                              if f.suffix in (".tex", ".bib", ".sty", ".cls", ".png", ".jpg", ".jpeg")))).encode()).hexdigest()[:16]
    d = WORD_CACHE / hashlib.sha1(str(tex).encode()).hexdigest()[:12]
    pdf = d / f"{sig}.pdf"
    if pdf.exists():
        return pdf
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    docx = make_docx(tex, d / f"{sig}.docx")
    prof = WORD_CACHE / "lo-profile"   # 開いている LibreOffice とぶつからないよう、専用の設定で動かす
    r = subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                        "--outdir", str(d), str(docx)], capture_output=True, text=True, timeout=180)
    if not pdf.exists():
        raise SyncError("LibreOffice で組めなかった: " + (r.stderr or r.stdout).strip()[-300:])
    if texfig.failed:   # 組めなかった図がある。作り置きにせず、次に開いたときもう一度組む
        part = pdf.with_name(f"{sig}-partial.pdf")
        pdf.replace(part)
        return part
    return pdf


def word_page(tex: Path, page: int, width: int) -> Path:
    """Word の見え方の1ページを PNG にする（poppler の pdftoppm）。
    LibreOffice の PDF は日本語の字を何組にも分けて埋め込み、pdf.js はそれを取り違えて化けるので、絵は poppler で描く。"""
    pdf = word_pdf(tex)
    width = max(200, min(4000, int(width) // 50 * 50))   # 幅は 50px 刻み（作り置きを使い回す）
    png = pdf.with_name(f"{pdf.stem}-p{int(page)}-w{width}.png")
    if not png.exists():
        r = subprocess.run(["pdftoppm", "-png", "-singlefile", "-f", str(int(page)), "-l", str(int(page)),
                            "-scale-to-x", str(width), "-scale-to-y", "-1", str(pdf), str(png.with_suffix(""))],
                           capture_output=True, text=True, timeout=60)
        if not png.exists():
            raise SyncError("ページの絵を作れなかった: " + r.stderr.strip()[-200:])
    return png
