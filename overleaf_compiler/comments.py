"""PDF に付けるコメント（Acrobat の注釈に当たるもの）。

コメントは PDF の座標ではなく**ソースの文字列**に結びつけて、原稿のフォルダの隠しファイル
（.<主文書の名前>.comments.json）に残す。PDF は保存のたびに組み直されて位置が変わるが、
ソースの文字列は直されるまで変わらないため。画面・CLI（Claude Code）・コメント付き PDF の書き出しは、
どれもこのファイルを読み書きする。隠しファイルなので、Overleaf へ戻す zip には入らない。

1件のコメント:
  id       短い識別子（CLI で指定する）
  author   書いた人。created は ISO 8601
  kind     highlight（コメント）・strike（削除の提案）・replace（置換の提案）・insert（挿入の提案）・note（付箋）
  text     コメントの本文。suggest は置換・挿入の提案の文字
  quote    PDF 上で選んだ文字列（付箋・挿入では、その場所の近くの文字）
  page, rects  付けたときの PDF 上の位置（pt、左上が原点）。[ページ, x, y, 幅, 高さ] の並び
  pin      付箋・挿入の印の位置 [ページ, x, y]（quote は目印にする近くの文字）
  file, line   ソースのファイル（原稿のフォルダからの相対パス）と行
  src      quote に当たるソースの文字列。直されて見つからなくなったら「古い」コメントになる
  status   open（未解決）か resolved（解決済み）。replies は返信の一覧
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import sync
from .project import list_tree

KINDS = {"highlight": "コメント", "strike": "削除の提案", "replace": "置換の提案",
         "insert": "挿入の提案", "note": "付箋"}


def path_for(tex: Path) -> Path:
    return tex.parent / f".{tex.stem}.comments.json"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def mtime(tex: Path) -> str:
    p = path_for(tex)
    return sync.mtime(p) if p.exists() else ""


@contextmanager
def _locked(tex: Path):
    """読んで書き換えるあいだ、原稿のフォルダを占有する（画面と CLI が同時に書いても壊れない）。"""
    fd = os.open(tex.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read(tex: Path) -> list[dict]:
    p = path_for(tex)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise sync.SyncError(f"{p.name} が壊れている（{e}）")
    return data.get("comments", [])


def _write(tex: Path, comments: list[dict]) -> None:
    p = path_for(tex)
    tmp = p.with_name(p.name + ".overleaf-compiler-tmp")
    text = json.dumps({"version": 1, "comments": comments}, ensure_ascii=False, indent=1)
    # 位置（数の並び）は1行にまとめる。git で差分を見るときに読みやすい
    text = re.sub(r"\[\s+([-\d.,\s]+?)\s+\]", lambda m: "[" + ", ".join(m.group(1).split()).replace(",,", ",") + "]", text)
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(p)


_CJK = "\u3000-\u9fff\uff00-\uffef"


def tidy(t: str) -> str:
    """PDF から選んだ文字列の改行を除く（和文の途中の改行は詰め、欧文の改行は空白に）。

    行末のハイフンは残す（PDF の文字の層で探し直すとき、PDF 上の文字と揃っている必要がある）。
    """
    t = re.sub(r"-\n\s*", "-", t)
    t = re.sub(rf"([{_CJK}])\s*\n\s*(?=[{_CJK}])", r"\1", t)
    return re.sub(r"\s*\n\s*", " ", t).strip()


def _find(comments: list[dict], cid: str) -> dict:
    hits = [c for c in comments if c["id"] == cid] or [c for c in comments if c["id"].startswith(cid)]
    if len(hits) != 1:
        raise sync.SyncError(f"コメント {cid} が{'無い' if not hits else '複数ある（もっと長く指定する）'}")
    return hits[0]


# ---------------------------------------------------------------- ソースとの対応
def _sources(tex: Path) -> list[Path]:
    return [tex.parent / f["path"] for f in list_tree(tex)
            if not f["dir"] and f["path"].endswith(".tex")]


def _read_text(p: Path, root: Path) -> str | None:
    try:
        return sync.read_file(p, root)["text"]
    except (sync.SyncError, OSError):
        return None


def anchor(tex: Path, root: Path, page: int, x: float, y: float, quote: str) -> dict:
    """PDF 上の位置と文字列から、ソースのファイル・行・文字列を割り出す。

    SyncTeX が指したファイルの、指した行の近くで quote を探す。無ければ原稿の .tex を全部探す
    （別の版の PDF から取り込んだコメントは、位置がずれていることがあるため）。
    """
    src_path, line = None, 1
    try:
        src_path, line = sync.pdf_to_source(tex.with_suffix(".pdf"), page, x, y)
        src_path = sync.inside(src_path, root)
    except sync.SyncError:
        src_path = None
    cands = ([src_path] if src_path else []) + [p for p in _sources(tex) if p.resolve() != src_path]
    if quote.strip():
        for p in cands:
            text = _read_text(p, root)
            span = text is not None and sync.find_in_text(text, line if p == src_path else 1, quote)
            if span:
                s, e = span
                return {"file": _rel(tex, p), "line": text.count("\n", 0, s) + 1, "src": text[s:e]}
    if src_path:  # 文字列では見つからない（コマンドや数式を含む）。行だけ合わせ直す
        return {"file": _rel(tex, src_path), "line": sync.refine_line(src_path, line, quote[:12], root),
                "src": None}
    return {"file": None, "line": None, "src": None}


def _rel(tex: Path, p: Path) -> str:
    return os.path.relpath(p.resolve(), tex.parent.resolve())


def locate(tex: Path, root: Path, c: dict, cache: dict) -> dict:
    """今のソースのどこにあるか。{"found": 真偽（src が無ければ None）, "line", "range"}"""
    if not c.get("file") or not c.get("src"):
        return {"found": None, "line": c.get("line")}
    p = tex.parent / c["file"]
    if p not in cache:
        cache[p] = _read_text(p, root) if p.exists() else None
    text = cache[p]
    span = text is not None and sync.find_in_text(text, c.get("line") or 1, c["src"])
    if not span:
        return {"found": False, "line": c.get("line")}
    s, e = span
    pos = lambda i: (text.count("\n", 0, i), i - (text.rfind("\n", 0, i) + 1))
    (l1, c1), (l2, c2) = pos(s), pos(e)
    return {"found": True, "line": l1 + 1, "range": [l1, c1, l2, c2]}


# ---------------------------------------------------------------- 読み書き
def list_comments(tex: Path, root: Path) -> list[dict]:
    """全部のコメントに、今のソースの位置（found・line・range）を付けて返す。

    ソースが直されて行がずれていれば、ファイルの行番号も書き換えておく（次に探すときの目安）。
    """
    with _locked(tex):
        comments, cache, moved = _read(tex), {}, False
        out = []
        for c in comments:
            loc = locate(tex, root, c, cache)
            if loc["found"] and loc["line"] != c.get("line"):
                c["line"], moved = loc["line"], True
            out.append({**c, **loc})
        if moved:
            _write(tex, comments)
    return out


def _new_id(comments: list[dict]) -> str:
    ids = {c["id"] for c in comments}
    while (cid := secrets.token_hex(3)) in ids:
        pass
    return cid


def _clean(item: dict) -> dict:
    kind = item.get("kind", "highlight")
    if kind not in KINDS:
        raise sync.SyncError(f"コメントの種類 {kind} は無い")
    rects = [[int(r[0])] + [round(float(v), 2) for v in r[1:5]] for r in item.get("rects", [])]
    c = {"author": str(item.get("author") or "名無し").strip()[:80], "created": item.get("created") or now(),
         "kind": kind, "text": str(item.get("text", "")).strip(), "suggest": str(item.get("suggest", "")),
         "quote": tidy(str(item.get("quote", ""))), "page": int(item.get("page") or (rects[0][0] if rects else 1)),
         "rects": rects, "status": "resolved" if item.get("status") == "resolved" else "open",
         "replies": [{"author": str(r.get("author") or "名無し"), "created": r.get("created") or now(),
                      "text": str(r.get("text", "")).strip()} for r in item.get("replies", [])]}
    if c["status"] == "resolved":
        c["resolved_by"], c["resolved_at"] = str(item.get("resolved_by") or ""), item.get("resolved_at") or now()
    if pin := item.get("pin"):
        c["pin"] = [int(pin[0]), round(float(pin[1]), 2), round(float(pin[2]), 2)]
    return c


def add(tex: Path, root: Path, item: dict) -> dict:
    """PDF 上で選んだ文字列にコメントを付ける。item には page・x・y（ソースを引く位置）と quote を入れる。"""
    c = _clean(item)
    if not c["text"] and not c["suggest"] and c["kind"] == "highlight":
        raise sync.SyncError("コメントが空")
    c.update(anchor(tex, root, int(item.get("page", c["page"])), float(item.get("x", 0)),
                    float(item.get("y", 0)), str(item.get("quote", ""))))
    with _locked(tex):
        comments = _read(tex)
        c = {"id": _new_id(comments), **c}
        comments.append(c)
        _write(tex, comments)
    return c


def import_items(tex: Path, root: Path, items: list[dict]) -> dict:
    """コメント付き PDF（Acrobat など）から読んだ注釈をまとめて取り込む。

    同じコメントが既にあれば取り込まない（同じ PDF を2回入れても増えない）。同じとみなすのは、
    書いた人と作成日時（秒まで）が同じもの、または書いた人・本文・対象の文字が同じもの。
    コメント付きで書き出した PDF を取り込み直した場合も、作成日時で元のコメントと分かる。
    """
    anchored = []
    for item in items:
        c = _clean(item)
        c.update(anchor(tex, root, c["page"], float(item.get("x", 0)), float(item.get("y", 0)),
                        str(item.get("quote", ""))))
        anchored.append(c)
    def keys(c: dict) -> set:
        k = {("text", c["author"], c["text"], c["suggest"], "".join(c["quote"].split()))}
        try:
            k.add(("time", c["author"], int(datetime.fromisoformat(c["created"]).timestamp())))
        except (TypeError, ValueError):
            pass
        return k
    with _locked(tex):
        comments = _read(tex)
        have = set().union(*map(keys, comments)) if comments else set()
        added = 0
        for c in anchored:
            if keys(c) & have:
                continue
            comments.append({"id": _new_id(comments), **c})
            have |= keys(c)
            added += 1
        _write(tex, comments)
    return {"added": added, "skipped": len(anchored) - added,
            "unplaced": sum(1 for c in anchored if not c["file"])}


def change(tex: Path, cid: str, fn) -> dict:
    with _locked(tex):
        comments = _read(tex)
        c = _find(comments, cid)
        fn(c, comments)
        _write(tex, comments)
    return c


def edit(tex: Path, cid: str, text: str | None = None, suggest: str | None = None) -> dict:
    def f(c, _):
        if text is not None:
            c["text"] = text.strip()
        if suggest is not None:
            c["suggest"] = suggest
        c["edited"] = now()
    return change(tex, cid, f)


def reply(tex: Path, cid: str, author: str, text: str) -> dict:
    if not text.strip():
        raise sync.SyncError("返信が空")
    return change(tex, cid, lambda c, _: c.setdefault("replies", []).append(
        {"author": author or "名無し", "created": now(), "text": text.strip()}))


def set_status(tex: Path, cid: str, status: str, by: str = "") -> dict:
    def f(c, _):
        c["status"] = status
        if status == "resolved":
            c["resolved_by"], c["resolved_at"] = by or "名無し", now()
        else:
            c.pop("resolved_by", None)
            c.pop("resolved_at", None)
    return change(tex, cid, f)


def delete(tex: Path, cid: str) -> dict:
    return change(tex, cid, lambda c, comments: comments.remove(c))


# ---------------------------------------------------------------- 一覧の文章（CLI・Markdown での書き出し）
def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(iso or "")


def _one_line(s: str, n: int = 0) -> str:
    s = " ".join(s.split())
    return s[:n] + "…" if n and len(s) > n else s


def _where(c: dict) -> str:
    if not c.get("file"):
        return f"（ソースの場所が分からない）p.{c.get('page')}"
    return f"{c['file']}:{c.get('line') or '?'}"


def _state(c: dict) -> str:
    if c.get("status") == "resolved":
        return f"解決済み（{c.get('resolved_by', '')}）"
    if c.get("found") is False:
        return "対象の文字がソースに見つからない（直された可能性がある）"
    return ""


def format_text(comments: list[dict], title: str) -> str:
    """CLI の出力。Claude Code が読んで、file:line を開いて直せる形にする。"""
    if not comments:
        return f"{title}: 0 件\n"
    lines = [f"{title}: {len(comments)} 件", ""]
    for c in comments:
        head = f"[{c['id']}] {_where(c)}  {KINDS.get(c['kind'], c['kind'])}  {c['author']}（{_when(c['created'])}）"
        lines.append(head)
        if c.get("quote"):
            lines.append(f"    対象（PDF）: {_one_line(c['quote'], 120)}")
        if c.get("src") and _one_line(c["src"]) != _one_line(c.get("quote", "")):
            lines.append(f"    対象（ソース）: {_one_line(c['src'], 160)}")
        if c.get("suggest"):
            lines.append(f"    提案: {c['suggest']}")
        for i, t in enumerate((c.get("text") or "").splitlines()):
            lines.append(f"    {'コメント: ' if i == 0 else '          '}{t}")
        for r in c.get("replies", []):
            lines.append(f"    ↳ {r['author']}: {_one_line(r['text'])}")
        if s := _state(c):
            lines.append(f"    状態: {s}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_markdown(comments: list[dict], title: str) -> str:
    """「コメント一覧 (.md)」の書き出し。人にも AI にもそのまま渡せる形。"""
    out = [f"# {title} のコメント", "",
           f"未解決 {sum(c['status'] != 'resolved' for c in comments)} 件・"
           f"解決済み {sum(c['status'] == 'resolved' for c in comments)} 件", ""]
    for n, c in enumerate(sorted(comments, key=lambda c: (c["status"] == "resolved", c["page"],
                                                            c["rects"][0][2] if c["rects"] else 0)), 1):
        out.append(f"## {n}. {KINDS.get(c['kind'], c['kind'])}（{c['author']}、{_when(c['created'])}）"
                   f"{' — 解決済み' if c['status'] == 'resolved' else ''}")
        out.append("")
        out.append(f"- 場所: `{_where(c)}`（PDF の {c['page']} ページ）")
        if c.get("quote"):
            out.append(f"- 対象: {_one_line(c['quote'])}")
        if c.get("suggest"):
            out.append(f"- 提案: {c['suggest']}")
        if c.get("found") is False and c["status"] != "resolved":
            out.append("- 対象の文字がソースに見つからない（直された可能性がある）")
        if c.get("text"):
            out += ["", *[f"> {t}" if t else ">" for t in c["text"].splitlines()]]
        for r in c.get("replies", []):
            out += ["", f"- 返信（{r['author']}、{_when(r['created'])}）: {_one_line(r['text'])}"]
        out.append("")
    return "\n".join(out)
