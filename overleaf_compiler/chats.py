"""右のチャット欄のタブ。原稿ごとに、Claude Code と Codex の会話をいくつでも並べて、同時に動かせる。

タブ1つが会話1つ（claude.Chat か codex.CodexChat）。タブの並びは ~/.local/share/overleaf-compiler/claude-sessions.json の
tabs:<主文書> に残し、原稿を開き直したら同じタブと会話が戻る。会話の中身は Claude Code・Codex の記録から読み直す。
画面とのやり取りは /api/chat/<名前>?c=<タブの番号>（server.py）。
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from .claude import Chat, ClaudeError, _last_sessions, set_last
from .codex import CodexChat

ENGINES = ("claude", "codex")


class ChatTabs:
    def __init__(self, tex: Path, revert=None):
        self.tex, self.revert = tex, revert
        self.lock = threading.Lock()
        self.objs: dict[str, Chat | CodexChat] = {}
        saved = _last_sessions()
        self.tabs: list[dict] = [t for t in saved.get(self._key(), []) if t.get("engine") in ENGINES]
        if not self.tabs:
            # 前の版（タブが1つずつだったころ）の会話を、最初のタブとして引き継ぐ
            if saved.get(str(tex)):
                self.tabs.append({"id": "c1", "engine": "claude", "key": str(tex)})
            if saved.get(f"codex:{tex}"):
                self.tabs.append({"id": "x1", "engine": "codex", "key": f"codex:{tex}"})
            self._save()

    def _key(self) -> str:
        return f"tabs:{self.tex}"

    def _save(self) -> None:
        set_last(self._key(), self.tabs)

    def get(self, cid: str | None) -> Chat | CodexChat:
        with self.lock:
            t = next((t for t in self.tabs if t["id"] == cid), None)
            if not t:
                raise ClaudeError("そのタブはもう閉じられている")
            obj = self.objs.get(cid)
            if obj is None:
                obj = Chat(self.tex, key=t["key"]) if t["engine"] == "claude" else \
                    CodexChat(self.tex, revert=self.revert, key=t["key"])
                self.objs[cid] = obj
            return obj

    # ---- 画面から ----
    def list(self, _=None) -> dict:
        out = []
        for t in list(self.tabs):
            o = self.get(t["id"])
            out.append({"id": t["id"], "engine": t["engine"], "title": o.title, "busy": o.busy, "session": o.state()["session"],
                        "count": len(o.events)})
        return {"tabs": out}

    def new(self, body: dict) -> dict:
        eng = body.get("engine") if body.get("engine") in ENGINES else "claude"
        cid = uuid.uuid4().hex[:8]
        key = f"{self.tex}#{cid}" if eng == "claude" else f"codex:{self.tex}#{cid}"
        with self.lock:
            self.tabs.append({"id": cid, "engine": eng, "key": key})
            self._save()
        return {"id": cid, "engine": eng}

    def close(self, body: dict) -> dict:
        cid = body.get("id")
        with self.lock:
            t = next((t for t in self.tabs if t["id"] == cid), None)
            if not t:
                return {"ok": True}
            self.tabs.remove(t)
            obj = self.objs.pop(cid, None)
            self._save()
        if obj:
            obj.close()
        set_last(t["key"], None)   # 会話そのものは Claude Code・Codex の記録に残る（過去の会話から開ける）
        return {"ok": True}

    def close_all(self) -> None:
        for o in list(self.objs.values()):
            o.close()
        self.objs.clear()
