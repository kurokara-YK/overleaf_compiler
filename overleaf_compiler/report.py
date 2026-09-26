"""コンパイル結果の要約。.log と .blg から、直すべき箇所を file:line の形で拾う。

Claude Code などのエージェントが原稿を直したあとに `overleaf-compiler check` で読む。
"""
from __future__ import annotations

import re
from pathlib import Path

_ERR = re.compile(r"^(\S.*?\.(?:tex|sty|cls|bib)):(\d+): (.*)$", re.M)
_REF = re.compile(r"LaTeX Warning: Reference `([^']+)' on page (\d+) undefined")
_CITE = re.compile(r"(?:LaTeX|Package natbib) Warning: Citation `([^']+)' on page (\d+) undefined")
_BLX_CITE = re.compile(r"Package biblatex Warning: The following entry could not be found\s*\(biblatex\)\s*in the database:\s*\(biblatex\)\s*(\S+)")
_OVER = re.compile(r"^Overfull \\hbox \(([\d.]+)pt too wide\) (?:in paragraph|in alignment|detected) at lines? (\d+)(?:--(\d+))?", re.M)
_PAGES = re.compile(r"Output written on .*?\((\d+) pages?")
# 開き括弧はすべて積む（.cls や "(265.0pt too wide)" も閉じ括弧と対になるため）
_FILE_TOKEN = re.compile(r"\(([^\s()]*)|\)")


def _file_at(log: str, pos: int, base: Path) -> str | None:
    """log の pos の時点で読んでいた .tex を、括弧の入れ子から推定する。"""
    stack: list[str] = []
    for m in _FILE_TOKEN.finditer(log, 0, pos):
        if m.group(0) == ")":
            if stack:
                stack.pop()
        else:
            stack.append(m.group(1))
    for f in reversed(stack):
        if f.endswith(".tex"):
            p = (base / f).resolve()
            if p.exists():
                return str(p)
    return None


def summarize(tex: Path) -> dict:
    log_p, blg_p, pdf = tex.with_suffix(".log"), tex.with_suffix(".blg"), tex.with_suffix(".pdf")
    log = log_p.read_text(errors="replace") if log_p.exists() else ""
    base = tex.parent

    def rel(f: str | None) -> str | None:
        if not f:
            return None
        p = (base / f).resolve()
        return str(p.relative_to(base)) if p.is_relative_to(base) else str(p)

    errors = [{"file": rel(m.group(1)), "line": int(m.group(2)), "msg": m.group(3)}
              for m in _ERR.finditer(log)]
    refs = sorted({m.group(1) for m in _REF.finditer(log)})
    cites = sorted({m.group(1) for m in _CITE.finditer(log)} | {m.group(1) for m in _BLX_CITE.finditer(log)})
    over = []
    for m in _OVER.finditer(log):
        f = _file_at(log, m.start(), base)
        over.append({"file": rel(f) if f else None, "line": int(m.group(2)),
                     "end": int(m.group(3) or m.group(2)), "pt": float(m.group(1))})
    bib = []
    if blg_p.exists():
        bib = [l.strip() for l in blg_p.read_text(errors="replace").splitlines()
               if l.startswith(("WARN", "ERROR", "Warning--", "I couldn't", "I found no"))]
    pages = _PAGES.findall(log)
    return {
        "pdf": str(pdf), "has_pdf": pdf.exists(), "size": pdf.stat().st_size if pdf.exists() else 0,
        "pages": int(pages[-1]) if pages else None,
        "errors": errors, "undefined_refs": refs, "undefined_cites": cites,
        "overfull": over, "bib_warnings": bib[:30],
        "ok": not errors and pdf.exists(),
    }


def format_report(r: dict) -> str:
    out = []
    if r["ok"]:
        out.append(f"✓ コンパイル成功  {r['pages']} ページ・{r['size'] / 1e6:.2f} MB  {Path(r['pdf']).name}")
    else:
        n = len(r["errors"]) + len(r.get("other_failures", []))
        out.append(f"✗ コンパイル失敗  エラー {n} 件")
    for e in r["errors"]:
        out.append(f"  エラー  {e['file']}:{e['line']}: {e['msg']}")
    for l in r.get("other_failures", []):
        out.append(f"  エラー  {l}")
    if r["undefined_refs"]:
        out.append(f"  未定義の参照 {len(r['undefined_refs'])} 件: {', '.join(r['undefined_refs'])}")
    if r["undefined_cites"]:
        out.append(f"  未定義の文献 {len(r['undefined_cites'])} 件: {', '.join(r['undefined_cites'])}")
    if r["overfull"]:
        out.append(f"  はみ出し（Overfull \\hbox）{len(r['overfull'])} 件")
        for o in r["overfull"]:
            where = f"{o['file'] or '?'}:{o['line']}" + (f"-{o['end']}" if o["end"] != o["line"] else "")
            out.append(f"    {where}  {o['pt']:.1f}pt")
    for w in r["bib_warnings"]:
        out.append(f"  文献処理  {w}")
    if r["ok"] and not (r["undefined_refs"] or r["undefined_cites"] or r["overfull"] or r["bib_warnings"]):
        out.append("  警告なし")
    return "\n".join(out)
