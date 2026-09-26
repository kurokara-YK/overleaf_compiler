"""変更履歴。ファイルの版を原稿フォルダの外（~/.local/share/overleaf-compiler/history/）に残す。

版を残すのは、ブラウザで保存したとき・ローカル（VS Code・Claude Code）で直されたとき・
削除したとき・前の版に戻したとき。自動保存で版が増えすぎないよう、同じファイルを同じ手段で
60 秒以内に続けて直した分は1つの版にまとめる。削除したファイルもここに残るので戻せる。
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "overleaf-compiler" / "history"
MERGE_SECONDS = 60
KEEP_PER_FILE = 300

KIND_LABEL = {"first": "最初の版", "browser": "ブラウザで編集", "outside": "ローカルで変更",
              "delete": "削除", "restore": "前の版に戻した", "upload": "アップロード", "new": "新規作成",
              "rename": "名前を変更"}


class History:
    def __init__(self, project_dir: Path):
        self.base = project_dir.resolve()
        self.dir = ROOT / hashlib.sha1(str(self.base).encode()).hexdigest()[:16]
        self.blobs = self.dir / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.index_file = self.dir / "index.json"
        self._lock = threading.Lock()
        try:
            self.entries: list[dict] = json.loads(self.index_file.read_text())
        except (OSError, ValueError):
            self.entries = []
        (self.dir / "project.txt").write_text(str(self.base))  # どの原稿の履歴か、人が見て分かるように

    # ---- 記録 ----
    def _save_index(self) -> None:
        tmp = self.index_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, ensure_ascii=False))
        tmp.replace(self.index_file)

    def _latest(self, rel: str) -> dict | None:
        return next((e for e in reversed(self.entries) if e["path"] == rel), None)

    def record(self, rel: str, data: bytes | None, kind: str) -> dict | None:
        """rel の今の中身 data を1つの版として残す。直前の版と同じ中身なら残さない。"""
        with self._lock:
            sha = hashlib.sha1(data).hexdigest() if data is not None else None
            last = self._latest(rel)
            if last and last["sha"] == sha and kind not in ("delete", "rename"):
                return None
            if sha and not (self.blobs / sha).exists():
                (self.blobs / sha).write_bytes(data)
            now = time.time()
            if (last and last["kind"] == kind == "browser" and now - last["time"] < MERGE_SECONDS
                    and self.entries and self.entries[-1] is last):
                last.update(sha=sha, time=now, size=len(data or b""))   # 自動保存の続きは1つの版にまとめる
                e = last
            else:
                e = {"id": f"{int(now * 1000)}-{len(self.entries)}", "time": now, "path": rel, "kind": kind,
                     "sha": sha, "size": len(data or b"")}
                self.entries.append(e)
                same = [x for x in self.entries if x["path"] == rel]
                for old in same[:-KEEP_PER_FILE]:
                    self.entries.remove(old)
            self._save_index()
            return e

    def baseline(self, files: list[Path]) -> None:
        """まだ版が無いファイルは、今の中身を「最初の版」として残す（原稿を開いたとき）。"""
        known = {e["path"] for e in self.entries}
        for f in files:
            rel = str(f.relative_to(self.base))
            if rel not in known and f.is_file() and f.stat().st_size < 4 * 1024 * 1024:
                self.record(rel, f.read_bytes(), "first")

    # ---- 読み出し ----
    def blob(self, e: dict) -> bytes | None:
        return (self.blobs / e["sha"]).read_bytes() if e.get("sha") and (self.blobs / e["sha"]).exists() else None

    def _prev(self, e: dict) -> dict | None:
        """同じファイルの1つ前の版（中身のあるもの）。"""
        i = self.entries.index(e)
        return next((x for x in reversed(self.entries[:i]) if x["path"] == e["path"] and x.get("sha")), None)

    def list(self, rel: str | None = None, limit: int = 400) -> list[dict]:
        out = []
        for e in reversed(self.entries):
            if rel and e["path"] != rel:
                continue
            if e["kind"] == "first" and not rel:
                continue  # 一覧を「最初の版」で埋めない（ファイルを絞ったときは出す）
            add, rem = self._counts(e)
            out.append({**e, "label": KIND_LABEL.get(e["kind"], e["kind"]), "add": add, "del": rem})
            if len(out) >= limit:
                break
        return out

    def _text(self, data: bytes | None) -> list[str] | None:
        if data is None:
            return []
        try:
            return data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return None

    def _counts(self, e: dict) -> tuple[int, int]:
        if "add" in e:
            return e["add"], e["del"]
        prev = self._prev(e)
        a, b = self._text(self.blob(prev) if prev else None), self._text(self.blob(e))
        if a is None or b is None:
            return 0, 0
        add = rem = 0
        for l in difflib.unified_diff(a, b, lineterm="", n=0):
            if l.startswith("+") and not l.startswith("+++"):
                add += 1
            elif l.startswith("-") and not l.startswith("---"):
                rem += 1
        e["add"], e["del"] = add, rem  # 次からは計算しない
        return add, rem

    def find(self, vid: str) -> dict:
        e = next((x for x in self.entries if x["id"] == vid), None)
        if not e:
            raise KeyError(vid)
        return e

    def diff(self, vid: str) -> dict:
        """その版で何が変わったか（1つ前の版との差分）。"""
        e = self.find(vid)
        prev = self._prev(e)
        a, b = self._text(self.blob(prev) if prev else None), self._text(self.blob(e))
        if a is None or b is None:
            return {"entry": e, "binary": True, "lines": []}
        lines = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op == "equal":
                chunk = list(range(i1, i2))
                # 変わっていない所は前後3行だけ見せる
                for k, i in enumerate(chunk):
                    if k < 3 or k >= len(chunk) - 3 or len(chunk) <= 7:
                        lines.append({"t": " ", "a": i + 1, "b": j1 + k + 1, "s": a[i]})
                    elif k == 3:
                        lines.append({"t": "…", "s": f"（変わっていない {len(chunk) - 6} 行）"})
            else:
                lines += [{"t": "-", "a": i + 1, "s": a[i]} for i in range(i1, i2)]
                lines += [{"t": "+", "b": j + 1, "s": b[j]} for j in range(j1, j2)]
        return {"entry": {**e, "label": KIND_LABEL.get(e["kind"], e["kind"])}, "binary": False, "lines": lines,
                "has_prev": prev is not None}
