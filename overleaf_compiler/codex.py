"""右のチャット欄で Codex と話す（VS Code の Codex 拡張と同じく `codex app-server` を子プロセスで動かす）。

claude.py の Chat と同じ受け口（send・stop・reset・start・set・permission・control・sessions・resume・rewind）と、
同じ形の出来事（k: 種類）を画面に渡す。画面は同じチャット欄を、Codex 用の項目に差し替えて使う。

app-server とは JSON-RPC（1行に1つの JSON）でやり取りする。原稿ごとに1つ起動し、その中のスレッド（会話）を1つ使う。
承認の問い合わせ（item/commandExecution/requestApproval など）は画面に出して、押された答えを返す。
ログインは Codex のもの（~/.codex）をそのまま使う。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .claude import ClaudeError, WAIT, _last_sessions, LAST_SESSIONS

EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# 承認のモード（拡張の「How should Codex actions be approved?」）→ app-server の設定
MODES = {
    "ask": {"approvalPolicy": "on-request", "sandbox": "workspace-write", "approvalsReviewer": "user"},
    "auto": {"approvalPolicy": "on-request", "sandbox": "workspace-write", "approvalsReviewer": "auto_review"},
    "full": {"approvalPolicy": "never", "sandbox": "danger-full-access", "approvalsReviewer": "user"},
    "custom": {},   # config.toml のまま
}
CONTROLS = {"mcpServerStatus/list", "account/rateLimits/read", "model/list", "skills/list", "hooks/list"}


def find_codex() -> str | None:
    """PATH の codex。無ければ VS Code の Codex 拡張に入っているもの（版の新しい方）。"""
    if p := shutil.which("codex"):
        return p
    exts = sorted(Path.home().glob(".vscode/extensions/openai.chatgpt-*/bin/*/codex"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return str(exts[0]) if exts else None


def _instructions(tex: Path) -> str:
    return (f"あなたは overleaf-compiler（ローカルの Overleaf 風エディタ）の右のチャット欄から呼ばれている。"
            f"作業場所は LaTeX 原稿のフォルダで、主文書は {tex.name}。"
            "ファイルを書き換えると overleaf-compiler が自動で組み直し、エディタと PDF に反映する。"
            "latexmk などで自分で組む必要は無い。組版のエラーを見たいときは主文書と同じ名前の .log を読む。"
            "ユーザの発言の先頭に［エディタ］で始まる行があれば、ユーザが今エディタで見ている場所を表す。")


def _short_cmd(cmd: str) -> str:
    """/bin/bash -lc "..." の外側を外して見やすくする。"""
    m = re.match(r"""^/bin/(?:ba)?sh -lc (['"])(.*)\1$""", cmd or "", re.S)
    return m.group(2) if m else (cmd or "")


class CodexChat:
    def __init__(self, tex: Path, revert=None):
        self.tex = tex
        self.revert = revert   # 時刻 → その時点のファイルに戻す（overleaf-compiler の変更履歴。app.Project.revert_since）
        self.cwd = tex.parent
        self.lock = threading.Condition()
        self.events: list[dict] = []
        self.epoch = 0
        self.proc: subprocess.Popen | None = None
        self.thread: str | None = None     # 今の会話（スレッド）の番号
        self.turn: str | None = None       # 返答中のターンの番号（止めるときに使う）
        self.title = ""
        self.opts = {"model": "default", "effort": "", "mode": "ask", "thinking": True}
        self.busy = False
        self.info: dict = {}
        self.stderr: list[str] = []
        self.waits: dict[int, list] = {}
        self.next_id = 0
        self.perms: dict[str, dict] = {}   # 承認の問い合わせ（JSON-RPC の番号 → 中身）
        self.items: dict[str, dict] = {}   # ファイル変更の中身（承認の画面に出す）
        self.started_at = 0.0
        self._restore()

    # ---- 画面から ----
    def state(self) -> dict:
        return {"busy": self.busy, "session": self.thread, "title": self.title, "epoch": self.epoch,
                "opts": self.opts, "available": bool(find_codex())}

    def wait_events(self, q: dict) -> dict:
        after = int(q.get("after", 0))
        with self.lock:
            if int(q.get("epoch", -1)) != self.epoch:
                after = 0
            elif len(self.events) <= after:
                self.lock.wait(WAIT)
            return {"events": self.events[after:], "next": len(self.events), "from": after, **self.state()}

    def start(self, _=None) -> dict:
        self._ensure()
        if not self.info.get("models"):
            models = [m for m in self._call("model/list", {}).get("data", []) if not m.get("hidden")]
            self.info = {"models": [{"value": m["id"], "displayName": m["displayName"], "description": m.get("description", ""),
                                     "efforts": [e["reasoningEffort"] for e in m.get("supportedReasoningEfforts", [])],
                                     "defaultEffort": m.get("defaultReasoningEffort"), "isDefault": m.get("isDefault")}
                                    for m in models],
                         "commands": []}
            try:
                self._limits(self._call("account/rateLimits/read", {}).get("rateLimits") or {})
            except ClaudeError:
                pass
        return {**self.state(), **self.info}

    def set(self, body: dict) -> dict:
        """モデル・考える深さ・承認のモード。次に送るときに turn/start で渡す。"""
        o = self.opts
        if body.get("model"):
            o["model"] = str(body["model"])
        if body.get("effort") in EFFORTS or body.get("effort") == "":
            o["effort"] = body["effort"]
        if body.get("mode") in MODES:
            o["mode"] = body["mode"]
        with self.lock:
            self._push({"k": "opts", **o})
        return self.state()

    def send(self, body: dict) -> dict:
        content = body.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not content:
            raise ClaudeError("送る文が空")
        with self.lock:
            if self.busy:
                raise ClaudeError("まだ返答の途中（止めてから送る）")
        self._ensure()
        if not self.thread:
            r = self._call("thread/start", {"cwd": str(self.cwd), "developerInstructions": _instructions(self.tex),
                                            **self._policy(thread=True)}, 60)
            self.thread = r["thread"]["id"]
            self._remember()
        inputs = []
        for c in content:   # Anthropic の content ブロック → Codex の UserInput
            if c.get("type") == "text":
                inputs.append({"type": "text", "text": c["text"], "text_elements": []})
            elif c.get("type") == "image":
                s = c["source"]
                inputs.append({"type": "image", "url": f"data:{s['media_type']};base64,{s['data']}"})
            elif c.get("type") == "document":
                inputs.append({"type": "text", "text": f"（PDF「{c.get('title', '')}」は Codex に渡せないので省いた）", "text_elements": []})
        with self.lock:
            self._push({"k": "user", "text": str(body.get("show", "")), "ctx": str(body.get("ctx", "")),
                        "files": body.get("files") or []})
            self.busy, self.started_at = True, time.time()
        params = {"threadId": self.thread, "input": inputs, **self._policy()}
        if self.opts["model"] != "default":
            params["model"] = self.opts["model"]
        if self.opts["effort"]:
            params["effort"] = self.opts["effort"]
        try:
            r = self._call("turn/start", params, 60)
            self.turn = r.get("turn", {}).get("id")
            with self.lock:
                # 巻き戻しに使うターンの番号を、残しておく発言にも付ける（開き直した画面でも戻せるように）
                u = next((x for x in reversed(self.events) if x["k"] == "user"), None)
                if u is not None and not u.get("uuid"):
                    u["uuid"] = self.turn
                self._push({"k": "uuid", "uuid": self.turn})
        except ClaudeError as e:
            with self.lock:
                self.busy = False
                self._push({"k": "error", "text": str(e)})
        return self.state()

    def permission(self, body: dict) -> dict:
        rid = body.get("id", "")
        req = self.perms.pop(rid, None)
        if not req:
            raise ClaudeError("この問い合わせはもう終わっている")
        if req["method"] == "item/tool/requestUserInput":
            ans = (body.get("input") or {}).get("answers") or {}
            result = {"answers": {q["id"]: {"answers": [a for a in str(ans.get(q["question"], "")).split(", ") if a]}
                                  for q in req["params"].get("questions", [])}}
            behavior = "allow" if body.get("behavior") == "allow" else "deny"
        elif req["method"] in ("item/permissions/requestApproval", "mcpServer/elicitation/request"):
            behavior = body.get("behavior", "deny")
            result = {"decision": "accept" if behavior == "allow" else "decline"} \
                if req["method"] == "item/permissions/requestApproval" else {"action": "accept" if behavior == "allow" else "decline"}
        else:
            decision = body.get("decision") or ("acceptForSession" if body.get("always") else
                                                "accept" if body.get("behavior") == "allow" else "decline")
            result, behavior = {"decision": decision}, "allow" if decision.startswith("accept") else "deny"
        self._write({"id": req["id"], "result": result})
        with self.lock:
            self._push({"k": "permission_done", "id": rid, "behavior": behavior, "message": body.get("message", "")})
        if behavior == "deny" and body.get("message") and self.thread and self.turn:
            # 断ったうえで、どうしてほしいかを返答中のターンに足す（拡張の「tell Codex what to do differently」）
            try:
                self._call("turn/steer", {"threadId": self.thread, "expectedTurnId": self.turn,
                                          "input": [{"type": "text", "text": body["message"], "text_elements": []}]})
            except ClaudeError:
                pass
        return self.state()

    def control(self, body: dict) -> dict:
        m = body.get("method")
        if m not in CONTROLS:
            raise ClaudeError(f"{m} は問い合わせられない")
        self._ensure()
        return self._call(m, body.get("params") or {}, 60)

    def compact(self, _=None) -> dict:
        if not self.thread:
            raise ClaudeError("まだ会話が無い")
        self._ensure()
        with self.lock:
            self.busy = True
            self._push({"k": "note", "text": "会話を要約している（Compact）"})
        self._call("thread/compact/start", {"threadId": self.thread}, 60)
        return self.state()

    def fork(self, _=None) -> dict:
        """今の会話を複製して、そちらで続ける（Fork chat）。"""
        if not self.thread:
            raise ClaudeError("まだ会話が無い")
        self._ensure()
        r = self._call("thread/fork", {"threadId": self.thread}, 60)
        with self.lock:
            self.thread = r["thread"]["id"]
            self._push({"k": "note", "text": "会話を複製した（Fork chat）。ここから先は複製した方で続く"})
        self._remember()
        return self.state()

    def stop(self, _=None) -> dict:
        if self._alive() and self.busy and self.thread and self.turn:
            for rid in list(self.perms):
                self.permission({"id": rid, "behavior": "deny"})
            try:
                self._call("turn/interrupt", {"threadId": self.thread, "turnId": self.turn})
            except ClaudeError:
                pass
        return self.state()

    def reset(self, _=None) -> dict:
        with self.lock:
            self.events, self.epoch, self.perms = [], self.epoch + 1, {}
            self.thread, self.turn, self.title, self.busy = None, None, "", False
            self.lock.notify_all()
        self._remember()
        return self.state()

    def sessions(self, _=None) -> dict:
        self._ensure()
        r = self._call("thread/list", {"cwd": str(self.cwd), "limit": 60, "sortKey": "updated_at"}, 30)
        return {"sessions": [{"id": t["id"], "title": t.get("name") or (t.get("preview") or "").strip()[:80] or "(untitled)",
                              "mtime": t.get("updatedAt") or t.get("createdAt") or 0, "current": t["id"] == self.thread}
                             for t in r.get("data", []) if not t.get("ephemeral")]}

    def resume(self, body: dict) -> dict:
        tid = str(body.get("id", ""))
        self._ensure()
        r = self._call("thread/resume", {"threadId": tid, "cwd": str(self.cwd), **self._policy(thread=True)}, 60)
        th = r.get("thread") or {}
        if not th.get("turns"):
            th = self._call("thread/read", {"threadId": tid, "includeTurns": True}, 60).get("thread") or th
        evs = []
        for turn in th.get("turns") or []:
            for it in turn.get("items") or []:
                evs += self._item_events(it, done=True, turn=turn.get("id"))
        with self.lock:
            self.thread, self.title, self.turn = tid, th.get("name") or "", None
            self.events, self.epoch, self.busy = evs, self.epoch + 1, False
            self.lock.notify_all()
        self._remember()
        return self.state()

    def rewind(self, body: dict) -> dict:
        """発言（ターン）の前まで戻す。thread/revert は会話と、Codex が変えたファイルを戻す。"""
        turn = str(body.get("uuid", ""))
        if self.busy:
            raise ClaudeError("返答の途中は戻せない（止めてから）")
        if not self.thread or not turn:
            raise ClaudeError("戻す場所が分からない")
        self._ensure()
        self._call("thread/revert", {"threadId": self.thread, "beforeTurnId": turn}, 60)
        with self.lock:
            cut = next((i for i, e in enumerate(self.events) if e.get("k") == "user" and e.get("uuid") == turn), len(self.events))
            ev = self.events[cut] if cut < len(self.events) else {}
            self.events, self.epoch = self.events[:cut], self.epoch + 1
            self.lock.notify_all()
        # thread/revert が戻すのは Codex の編集機能で変えたファイルだけ。シェルで変えた分も、変更履歴から発言の前に戻す
        files = self.revert(ev["t"]) if self.revert and ev.get("t") else []
        return {**self.state(), "prompt": ev.get("text", ""), "files": files}

    def terminal(self, _=None) -> dict:
        exe = find_codex()
        term = next((t for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm") if shutil.which(t)), None)
        if not exe or not term:
            raise ClaudeError("端末か codex コマンドが見つからない")
        cmd = [exe, "resume", self.thread] if self.thread else [exe]
        args = [term, "--"] + cmd if term == "gnome-terminal" else [term, "-e"] + cmd
        subprocess.Popen(args, cwd=self.cwd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self.state()

    def close(self) -> None:
        p, self.proc = self.proc, None
        self.busy = False
        if p and p.poll() is None:
            try:
                p.stdin.close()
                p.terminate()
                p.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                p.kill()

    # ---- 原稿ごとの最後の会話 ----
    def _key(self) -> str:
        return f"codex:{self.tex}"

    def _restore(self) -> None:
        self._restore_id = _last_sessions().get(self._key())

    def _remember(self) -> None:
        d = _last_sessions()
        if self.thread:
            d[self._key()] = self.thread
        else:
            d.pop(self._key(), None)
        try:
            LAST_SESSIONS.parent.mkdir(parents=True, exist_ok=True)
            LAST_SESSIONS.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        except OSError:
            pass

    # ---- 子プロセス（JSON-RPC）----
    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _policy(self, thread: bool = False) -> dict:
        m = dict(MODES.get(self.opts["mode"], {}))
        if not m:
            return {}
        if thread:
            return m
        sandbox = m.pop("sandbox")
        m["sandboxPolicy"] = {"type": "dangerFullAccess"} if sandbox == "danger-full-access" else \
            {"type": "workspaceWrite", "writableRoots": [str(self.cwd)], "networkAccess": False,
             "excludeTmpdirEnvVar": False, "excludeSlashTmp": False}
        return m

    def _ensure(self) -> None:
        if self._alive():
            return
        exe = find_codex()
        if not exe:
            raise ClaudeError("codex コマンドが見つからない（Codex CLI か、VS Code の Codex 拡張を入れる）")
        self.proc = subprocess.Popen([exe, "app-server"], cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.stderr = []
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_err, args=(self.proc,), daemon=True).start()
        self._call("initialize", {"clientInfo": {"name": "overleaf-compiler", "title": "overleaf-compiler", "version": "0.1.0"},
                                  "capabilities": None}, 30)
        self._write({"method": "initialized"})
        # 前に開いていた会話があれば、続きを出す
        rid, self._restore_id = getattr(self, "_restore_id", None), None
        if rid and not self.thread:
            try:
                self.resume({"id": rid})
            except ClaudeError:
                pass

    def _write(self, obj: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (OSError, AttributeError) as e:
            with self.lock:
                self.busy = False
                self._push({"k": "error", "text": f"codex に送れなかった: {e}"})

    def _call(self, method: str, params: dict, timeout: float = 20) -> dict:
        with self.lock:
            self.next_id += 1
            i = self.next_id
        box = [threading.Event(), None]
        self.waits[i] = box
        self._write({"id": i, "method": method, "params": params})
        if not box[0].wait(timeout):
            self.waits.pop(i, None)
            raise ClaudeError(f"{method} の答えが来ない")
        r = box[1] or {}
        if "error" in r:
            raise ClaudeError(f"{method}: {r['error'].get('message', r['error'])}")
        return r.get("result") or {}

    def _read_err(self, p: subprocess.Popen) -> None:
        for line in p.stderr:
            self.stderr = (self.stderr + [line.rstrip()])[-20:]

    def _read(self, p: subprocess.Popen) -> None:
        for line in p.stdout:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in o and "method" not in o:   # こちらの問い合わせへの答え
                box = self.waits.pop(o["id"], None)
                if box:
                    box[1] = o
                    box[0].set()
                continue
            if "id" in o:   # Codex からの問い合わせ（承認）
                self._from_server(o)
                continue
            evs = self._convert(o.get("method", ""), o.get("params") or {})
            if evs:
                with self.lock:
                    for e in evs:
                        self._push(e)
        p.wait()
        with self.lock:
            if self.proc is p:
                if self.busy or p.returncode:
                    tail = "\n".join(self.stderr[-8:])
                    self._push({"k": "error", "text": f"codex が終了した（{p.returncode}）\n{tail}".strip()})
                self.busy, self.proc = False, None
                self.lock.notify_all()

    def _push(self, e: dict) -> None:
        e.setdefault("t", time.time())
        self.events.append(e)
        self.lock.notify_all()

    def _rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.cwd) if os.path.isabs(path) else path
        except ValueError:
            return path

    # ---- Codex からの問い合わせ → 画面の許可の問い合わせ ----
    def _from_server(self, o: dict) -> None:
        m, p, rid = o["method"], o.get("params") or {}, str(o["id"])
        ev = {"k": "permission", "id": rid, "engine": "codex"}
        if m in ("item/commandExecution/requestApproval", "execCommandApproval"):
            cmd = _short_cmd(p.get("command") or " ".join(p.get("command", []) if isinstance(p.get("command"), list) else ""))
            ev.update({"name": "Bash", "title": "Run command", "input": {"command": cmd},
                       "description": p.get("reason") or "", "what": cmd,
                       "options": [["Yes", "accept"], ["Yes, and don't ask again this session", "acceptForSession"],
                                   ["No, and tell Codex what to do differently", "decline"]]})
        elif m in ("item/fileChange/requestApproval", "applyPatchApproval"):
            ch = self.items.get(p.get("itemId", ""), {})
            ev.update({"name": "Edit", "title": "Edit", "path": ch.get("path"), "diff": ch.get("diff", ""),
                       "description": p.get("reason") or "", "input": {},
                       "options": [["Yes", "accept"], ["Yes, and don't ask again this session", "acceptForSession"],
                                   ["No, and tell Codex what to do differently", "decline"]]})
        elif m == "item/tool/requestUserInput":
            qs = p.get("questions") or []
            ev.update({"name": "AskUserQuestion", "input": {"questions": [
                {"question": q.get("question", ""), "header": q.get("header", ""), "multiSelect": False,
                 "options": [{"label": x.get("label", ""), "description": x.get("description", "")} for x in (q.get("options") or [])]}
                for q in qs]}})
        elif m in ("item/permissions/requestApproval", "mcpServer/elicitation/request"):
            ev.update({"name": "Permission", "title": "Allow", "what": json.dumps(p, ensure_ascii=False)[:300], "input": {},
                       "options": [["Yes", "accept"], ["No", "decline"]]})
        else:
            self._write({"id": o["id"], "error": {"code": -32601, "message": "この画面では扱えない"}})
            return
        self.perms[rid] = {"id": o["id"], "method": m, "params": p}
        with self.lock:
            self._push(ev)

    # ---- 通知 → 画面向けの出来事 ----
    def _limits(self, rl: dict) -> list[dict]:
        pr, se = rl.get("primary") or {}, rl.get("secondary") or {}
        e = {"k": "limits"}
        if pr.get("usedPercent") is not None:
            e["five_hour"] = pr["usedPercent"] / 100
        if se.get("usedPercent") is not None:
            e["seven_day"] = se["usedPercent"] / 100
        return [e]

    def _item_events(self, it: dict, done: bool, turn: str | None = None) -> list[dict]:
        t = it.get("type")
        if t == "userMessage" and done:
            texts = [c.get("text", "") for c in it.get("content", []) if c.get("type") == "text"]
            from .claude import split_ctx
            ctx, body = split_ctx("\n".join(texts))
            files = [{"name": "image"} for c in it.get("content", []) if c.get("type") in ("image", "localImage")]
            return [{"k": "user", "text": body, "ctx": ctx, "files": files, "uuid": turn, "t": 0}]
        if t == "agentMessage":
            return [{"k": "text", "text": it.get("text", "")}] if done and it.get("text") else \
                [] if done else [{"k": "block", "kind": "text"}]
        if t == "reasoning" and done:
            text = "\n\n".join(it.get("summary") or it.get("content") or [])
            return [{"k": "thinking", "text": text}] if text.strip() else []
        if t == "commandExecution":
            cmd = _short_cmd(it.get("command", ""))
            if not done:
                return [{"k": "tool", "id": it["id"], "name": "Bash", "input": {"command": cmd}, "what": cmd}]
            ev = [] if not turn else [{"k": "tool", "id": it["id"], "name": "Bash", "input": {"command": cmd}, "what": cmd}]
            return ev + [{"k": "result", "id": it["id"], "error": it.get("status") == "failed" or (it.get("exitCode") or 0) != 0,
                          "text": (it.get("aggregatedOutput") or "")[:6000]}]
        if t == "fileChange":
            evs = []
            for i, c in enumerate(it.get("changes") or []):
                path = self._rel(c.get("path", ""))
                self.items[it["id"]] = {"path": path, "diff": c.get("diff", "")}
                if not done or turn:
                    evs.append({"k": "tool", "id": f"{it['id']}#{i}", "name": "Edit", "path": path, "what": path,
                                "diff": c.get("diff", "")[:8000], "input": {}})
                if done:
                    evs.append({"k": "result", "id": f"{it['id']}#{i}", "error": it.get("status") in ("failed", "declined"), "text": ""})
            return evs
        if t == "mcpToolCall":
            name = f"mcp__{it.get('server', '')}__{it.get('tool', '')}"
            if not done:
                return [{"k": "tool", "id": it["id"], "name": name, "what": json.dumps(it.get("arguments"), ensure_ascii=False)[:200], "input": {}}]
            res = it.get("result") or it.get("error") or ""
            return ([] if not turn else [{"k": "tool", "id": it["id"], "name": name, "what": "", "input": {}}]) + \
                [{"k": "result", "id": it["id"], "error": bool(it.get("error")), "text": json.dumps(res, ensure_ascii=False)[:6000]}]
        if t == "webSearch":
            return [{"k": "tool", "id": it["id"], "name": "WebSearch", "what": it.get("query", ""), "input": {}}] if not done or turn else []
        return []

    def _convert(self, m: str, p: dict) -> list[dict]:
        if m == "item/started":
            return self._item_events(p.get("item") or {}, done=False)
        if m == "item/completed":
            it = p.get("item") or {}
            return [] if it.get("type") == "userMessage" else self._item_events(it, done=True)
        if m == "item/agentMessage/delta":
            return [{"k": "delta", "text": p.get("delta", "")}]
        if m == "turn/plan/updated":
            steps = p.get("plan") or []
            return [{"k": "tool", "id": f"plan-{time.time()}", "name": "TodoWrite", "what": "", "input": {"todos": [
                {"content": s.get("step", ""), "status": {"completed": "completed", "inProgress": "in_progress"}.get(s.get("status"), "pending")}
                for s in steps]}}]
        if m == "turn/completed":
            turn = p.get("turn") or {}
            self.busy, self.turn = False, None
            st = turn.get("status")
            err = (turn.get("error") or {}).get("message", "") if isinstance(turn.get("error"), dict) else ""
            return [{"k": "done", "error": st == "failed", "subtype": "error_during_execution" if st == "interrupted" else st or "",
                     "stop": None if st == "interrupted" else st, "result": err,
                     "seconds": round((turn.get("durationMs") or (time.time() - self.started_at) * 1000) / 1000, 1)}]
        if m == "thread/tokenUsage/updated":
            u = p.get("tokenUsage") or {}
            last, win = (u.get("last") or {}).get("totalTokens", 0), u.get("modelContextWindow") or 0
            return [{"k": "usage", "used": last, "window": win}] if win else []
        if m == "account/rateLimits/updated":
            return self._limits(p.get("rateLimits") or {})
        if m == "thread/name/updated":
            self.title = p.get("name") or p.get("threadName") or self.title
            return [{"k": "title", "title": self.title}]
        if m == "thread/compacted":
            self.busy = False
            return [{"k": "note", "text": "会話を要約した（Compact）"}, {"k": "done", "error": False, "stop": "compacted", "seconds": 0}]
        if m in ("error", "warning", "configWarning"):
            err = p.get("error")
            msg = p.get("message") or (err.get("message") if isinstance(err, dict) else err)
            return [{"k": "error" if m == "error" else "note", "text": str(msg or p)[:1000]}]
        return []
