"""Word・Markdown・HTML への書き出し（pandoc に任せる。数式や表、独自のクラスの体裁は崩れることがある）。"""
from __future__ import annotations

import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path

from .sync import SyncError

# 書き出す形式（Overleaf の「ダウンロード」と同じ並び）。形式 → (pandoc の -t, 拡張子, 追加の引数)
EXPORTS = {"docx": ("docx", ".docx", []), "md": ("gfm", ".md", []),
           "html": ("html5", ".html", ["--standalone", "--embed-resources", "--mathjax"])}


def available() -> bool:
    return bool(shutil.which("pandoc"))


def export(tex: Path, fmt: str) -> tuple[str, bytes, str]:
    """主文書 tex を fmt に書き出し、(ファイル名, 中身, 種類) を返す。"""
    if fmt not in EXPORTS:
        raise SyncError(f"{fmt} には書き出せない")
    if not available():
        raise SyncError("pandoc が無いので書き出せない（bash install.sh で入る）")
    to, ext, extra = EXPORTS[fmt]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / (tex.stem + ext)
        r = subprocess.run(["pandoc", "-f", "latex", "-t", to, *extra, "--resource-path=.", "-o", str(out),
                            tex.name], cwd=tex.parent, capture_output=True, text=True, errors="replace")
        if r.returncode != 0 or not out.exists():
            raise SyncError("pandoc で書き出せなかった: " + (r.stderr.strip().splitlines() or [""])[-1])
        return out.name, out.read_bytes(), mimetypes.guess_type(out.name)[0] or "application/octet-stream"
