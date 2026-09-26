"""原稿の中の全ファイルを検索する（Overleaf の左の「検索」）。"""
from __future__ import annotations

import re
from pathlib import Path

MAX_HITS = 2000


def search(base: Path, files: list[str], q: str, case: bool = False, regex: bool = False,
           word: bool = False) -> dict:
    """files（原稿のフォルダからの相対パス）の中から q を探す。行ごとの一致位置を返す。"""
    if not q:
        return {"total": 0, "files": []}
    pat = q if regex else re.escape(q)
    if word:
        pat = rf"(?<!\w){pat}(?!\w)"
    try:
        rx = re.compile(pat, 0 if case else re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"正規表現が正しくない: {e}")
    out, total = [], 0
    for rel in files:
        try:
            lines = (base / rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        hits = []
        for n, line in enumerate(lines, 1):
            spans = [(m.start(), m.end()) for m in rx.finditer(line) if m.end() > m.start()]
            if spans:
                hits.append({"line": n, "text": line[:400], "spans": spans[:20]})
                total += len(spans)
        if hits:
            out.append({"path": rel, "hits": hits})
        if total >= MAX_HITS:
            break
    return {"total": total, "files": out, "truncated": total >= MAX_HITS}
