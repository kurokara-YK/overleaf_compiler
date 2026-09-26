"""組版。1回だけ組む build と、保存のたびに組み直す常駐（Watcher）の2通り。

Watcher は速さのために、変更のたびの組版を「エンジン1回 ＋ PDF 化」にする。
- ファイルの更新を 0.25 秒ごとに見る。ブラウザで保存したときは poke() で待たずに始める
- プリアンブルを読み込んだ状態を保存した形式（mylatexformat）を使い、毎回の読み込みを省く
- 参照・文献の組み直しが要るとき（ログに出る）や .bib が変わったときだけ、続けて latexmk で組み直す
最初の1回と「リコンパイル」は latexmk で全部組む。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from .project import latexmk_args
from .report import summarize

_BASE = ["latexmk", "-synctex=1", "-interaction=nonstopmode", "-file-line-error"]
# -file-line-error の書式（./本文.tex:12: Undefined control sequence.）
_ERR = re.compile(r"^(?!Latexmk)(.+?\.(?:tex|sty|cls|bib|bbx|cbx)):(\d+): (.*)$")
# 参照・文献を組み直す必要があるときにログに出る文
_RERUN = re.compile(r"Rerun to get|Label\(s\) may have changed|Please \(re\)run Biber|Please \(re\)run BibTeX"
                    r"|Please rerun LaTeX|rerunfilecheck Warning|Rerun LaTeX")
# 保存した形式を使えるエンジン（LuaLaTeX・XeLaTeX はフォントを形式に保存できないので使わない）
_FMT_OK = {"pdflatex", "latex", "platex", "uplatex", "platex-dev", "uplatex-dev"}
# 組版が書き出すファイル。更新を見る対象から外す
_GENERATED = (".aux", ".bbl", ".bcf", ".blg", ".dvi", ".fdb_latexmk", ".fls", ".log", ".out", ".run.xml",
              ".synctex.gz", ".toc", ".lof", ".lot", ".nav", ".snm", ".xdv", ".fmt", "-tmp", "-tmp.pdf")
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "overleaf-compiler"


def _env() -> dict:
    # max_print_line: .log を折り返さない。bibtex / pbibtex も同じ値を読み、20000 以上だと
    # 「3 is a bad bad」で止まるので 10000 に留める
    return {**os.environ, "max_print_line": "10000"}


def build_once(tex: Path, quiet: bool = False) -> tuple[int, str]:
    """1回だけ組む。latexmk が前回の失敗を覚えていても組み直すよう -g を付ける。

    quiet なら出力を画面に出さずに返す（check が、TeX 以外で止まった理由を拾うため）。
    """
    cmd = _BASE + ["-g"] + latexmk_args(tex) + [tex.name]
    if not quiet:
        return subprocess.run(cmd, cwd=tex.parent, env=_env()).returncode, ""
    r = subprocess.run(cmd, cwd=tex.parent, env=_env(), capture_output=True, text=True, errors="replace")
    return r.returncode, r.stdout + r.stderr


def failure_lines(output: str) -> list[str]:
    """latexmk の出力から、止まった理由らしい行を拾う（文献処理・dvipdfmx など TeX 以外の失敗）。"""
    keep, prev_run = [], ""
    for l in output.splitlines():
        if l.startswith("Running '"):
            prev_run = l
        low = l.lower()
        if (("error" in low or " bad " in low or "not found" in low or "fatal" in low)
                and not l.startswith(("Latexmk: Sometimes", "  ", "Collected error summary", "Running '",
                                      "Latexmk: Errors, so", "Latexmk: Failure to make"))
                and not _ERR.match(l)):
            keep.append(f"{l}  （{prev_run[9:-1]}）" if prev_run and not l.startswith("Latexmk") else l)
    return keep[-6:]


def clean(tex: Path) -> int:
    return subprocess.run(["latexmk", "-c", tex.name], cwd=tex.parent).returncode


class Watcher:
    """原稿を常駐で組み直し、成否を状態として持つ。画面は version が増えたら PDF を読み直す。"""

    def __init__(self, tex: Path):
        self.tex = tex
        self.pdf = tex.with_suffix(".pdf")
        self.version = 0          # 組版が1回終わるたびに増える
        self.building = True
        self.ok = True
        self.errors: list[dict] = []
        self.mode = ""            # 直近の組版のしかた（画面の表示用）
        self.seconds = 0.0        # 直近の組版にかかった時間
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._engine: str | None = None      # ログから読んだエンジン（uplatex など）
        self._output = "pdf"                 # エンジンが書き出すもの（dvi / pdf / xdv）
        self._fmt: str | None = None         # 使える保存形式の名前
        self._fmt_key: str | None = None
        self._fmt_bad = False                # 保存形式が合わない原稿。以後は使わない
        self._fmt_verified = False           # 保存形式で一度でも組めたか
        self._bib_state: tuple = ()
        self._undef_cites: set[str] = set()
        self.on_change = None                # 外でファイルが変わったときに呼ぶ（変更履歴に残すため）

    # ---- 外から ----
    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def poke(self) -> None:
        """ブラウザで保存した。更新の確認を待たずに組み始める。"""
        self._wake.set()

    def status(self) -> dict:
        with self._lock:
            return {"version": self.version, "building": self.building, "ok": self.ok,
                    "errors": self.errors, "has_pdf": self.pdf.exists(),
                    "mode": self.mode, "seconds": round(self.seconds, 1)}

    # ---- 常駐の本体 ----
    def _loop(self) -> None:
        started = time.time_ns()
        self._full(force=True)
        snap = self._snapshot()
        while not self._stop.is_set():
            self._wake.wait(0.25)
            self._wake.clear()
            if self._stop.is_set():
                break
            now = self._snapshot()
            # 変わったファイル。組版で読み込むファイルが増えただけ（組版を始める前から有ったもの）は数えない
            changed = [k for k, m in now.items()
                       if (k in snap and m != snap[k]) or (k not in snap and (m or 0) > started)]
            snap = now  # 組んでいる間の変更は、次の周回で拾う
            if changed:
                started = time.time_ns()
                if self.on_change:
                    try:
                        self.on_change([Path(k) for k in changed])
                    except Exception:  # 履歴に残せなくても組版は続ける
                        pass
                self._incremental()

    def _run(self, cmd: list[str], env: dict | None = None) -> tuple[int, str]:
        if self._stop.is_set():
            return 1, ""
        self._proc = subprocess.Popen(cmd, cwd=self.tex.parent, env=env or _env(), stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                      errors="replace", start_new_session=True)
        out, _ = self._proc.communicate()
        return self._proc.returncode, out

    def _begin(self) -> float:
        with self._lock:
            self.building = True
        return time.monotonic()

    def _finish(self, ok: bool, errors: list[dict], mode: str, t0: float) -> None:
        with self._lock:
            self.ok, self.errors, self.mode = ok, errors[:30], mode
            self.seconds = time.monotonic() - t0
            self.building = False
            self.version += 1

    def _full(self, force: bool = False) -> None:
        """latexmk で全部組む（参照・文献まで）。"""
        t0 = self._begin()
        rc, out = self._run(_BASE + (["-g"] if force else []) + latexmk_args(self.tex) + [self.tex.name])
        if self._stop.is_set():
            return
        errs = self._log_errors()
        if rc != 0 and not errs:  # TeX 以外（文献処理・dvipdfmx など）で止まった
            errs = [{"file": None, "line": None, "msg": l} for l in failure_lines(out)] \
                or [{"file": None, "line": None, "msg": "組版に失敗した"}]
        self._learn_engine()
        self._bib_state = self._bibs()
        self._undef_cites = set(summarize(self.tex)["undefined_cites"])
        self._finish(rc == 0, errs, "全体", t0)
        if rc == 0:
            self._prepare_fmt()

    def _incremental(self) -> None:
        """変更のたびの組版。エンジン1回 ＋ PDF 化。要るときだけ続けて latexmk で組み直す。"""
        if not self._engine or self._bibs() != self._bib_state:
            return self._full()   # エンジンが分からない、または .bib が変わった
        t0 = self._begin()
        self._prepare_fmt()
        rc, out = self._single(use_fmt=bool(self._fmt))
        if rc != 0 and self._fmt and not self._fmt_verified:
            # 作ったばかりの形式のせいかもしれない。使わずに組み直して確かめる（形式ごとに最初の1回だけ）
            rc2, out2 = self._single(use_fmt=False)
            if rc2 == 0:
                self._fmt_bad, self._fmt = True, None
                rc, out = rc2, out2
        elif rc == 0 and self._fmt:
            self._fmt_verified = True
        if self._stop.is_set():
            return
        errs = self._log_errors()
        if rc != 0 and not errs:
            errs = [{"file": None, "line": None, "msg": l} for l in failure_lines(out)] \
                or [{"file": None, "line": None, "msg": "組版に失敗した"}]
        self._finish(rc == 0, errs, "高速" if self._fmt else "1回", t0)
        if rc == 0 and self._needs_settle():
            self._full()

    def _single(self, use_fmt: bool) -> tuple[int, str]:
        env = _env()
        cmd = [self._engine]
        if use_fmt and self._fmt:
            env["TEXFORMATS"] = f"{self._fmt_dir()}:{env.get('TEXFORMATS', '')}"
            cmd.append(f"-fmt={self._fmt}")
        cmd += ["-synctex=1", "-interaction=nonstopmode", "-file-line-error", "-recorder", self.tex.name]
        rc, out = self._run(cmd, env)
        if rc == 0 and self._output in ("dvi", "xdv"):
            tool = "xdvipdfmx" if self._output == "xdv" else "dvipdfmx"
            tmp = self.tex.with_name(f".{self.tex.stem}.overleaf-compiler-tmp.pdf")
            # 圧縮は -z 6。既定の -z 9 は画像の多い原稿で3倍遅く、大きさは3%しか変わらない。
            # 全体を組むとき（リコンパイル・参照の組み直し）は latexmkrc の設定のまま
            rc, out2 = self._run([tool, "-q", "-z", "6", "-o", str(tmp),
                                  self.tex.with_suffix("." + self._output).name])
            out += out2
            if rc == 0:
                tmp.replace(self.pdf)  # 書きかけの PDF を画面に読ませない
        return rc, out

    def _needs_settle(self) -> bool:
        log = self.tex.with_suffix(".log")
        text = log.read_text(errors="replace") if log.exists() else ""
        if _RERUN.search(text):
            return True
        cites = set(summarize(self.tex)["undefined_cites"])
        return bool(cites - self._undef_cites)   # 新しく \cite した文献がある

    # ---- 保存した形式（プリアンブルを読み込んだ状態）----
    def _fmt_dir(self) -> Path:
        return CACHE / "fmt" / hashlib.sha1(str(self.tex).encode()).hexdigest()[:16]

    def _preamble_key(self) -> str:
        src = self.tex.read_text(errors="replace")
        pre = src.split("\\begin{document}", 1)[0]
        h = hashlib.sha1((self._engine or "").encode() + pre.encode())
        for f in sorted(self.tex.parent.rglob("*")):
            if f.suffix in (".cls", ".sty", ".cfg", ".def", ".clo") and ".git" not in f.parts:
                h.update(f"{f}:{f.stat().st_mtime_ns}".encode())
        return h.hexdigest()[:12]

    def _prepare_fmt(self) -> None:
        """プリアンブルが変わっていれば形式を作り直す。作れない原稿では使わない。"""
        if self._fmt_bad or self._engine not in _FMT_OK or not shutil.which(self._engine):
            self._fmt = None
            return
        key = self._preamble_key()
        if key == self._fmt_key:
            return
        d = self._fmt_dir()
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.fmt"):
            old.unlink()
        name = f"oc{key}"
        rc, _ = self._run([self._engine, "-ini", f"-jobname={name}", f"-output-directory={d}",
                           "-interaction=batchmode", f"&{self._engine}", "mylatexformat.ltx", self.tex.name])
        for junk in d.glob(f"{name}.*"):
            if junk.suffix != ".fmt":
                junk.unlink()
        self._fmt_key = key
        self._fmt = name if rc == 0 and (d / f"{name}.fmt").exists() else None
        self._fmt_verified = False

    # ---- 補助 ----
    def _learn_engine(self) -> None:
        """ログの1行目（preloaded format=uplatex）と出力の種類から、エンジンを知る。"""
        log = self.tex.with_suffix(".log")
        if not log.exists():
            return
        text = log.read_text(errors="replace")
        m = re.search(r"\((?:preloaded )?format=([\w-]+)", text.split("\n", 1)[0])
        if m:
            self._engine = m.group(1)
        m = re.findall(r"Output written on .*?\.(dvi|pdf|xdv) \(", text)
        if m:
            self._output = m[-1]

    def _log_errors(self) -> list[dict]:
        base = self.tex.parent
        return [{"file": str((base / e["file"]).resolve()) if e["file"] else None,
                 "line": e["line"], "msg": e["msg"]} for e in summarize(self.tex)["errors"]]

    def _bibs(self) -> tuple:
        return tuple(sorted((str(f), f.stat().st_mtime_ns) for f in self.tex.parent.rglob("*.bib")))

    def _snapshot(self) -> dict:
        """原稿が読み込んでいるファイル（.fls に出る、原稿のフォルダの中のもの）と .bib の更新時刻。"""
        base, out = self.tex.parent.resolve(), self.pdf.resolve()
        files = {self.tex}
        fls = self.tex.with_suffix(".fls")
        if fls.exists():
            for l in fls.read_text(errors="replace").splitlines():
                if l.startswith("INPUT "):
                    p = (base / l[6:].strip()).resolve()
                    if p.is_relative_to(base) and p != out and not p.name.endswith(_GENERATED):
                        files.add(p)
        files.update(self.tex.parent.rglob("*.bib"))
        snap = {}
        for f in files:
            try:
                snap[str(f)] = f.stat().st_mtime_ns
            except OSError:
                snap[str(f)] = None
        return snap
