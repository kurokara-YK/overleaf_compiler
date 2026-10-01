"""画面の右のチャット欄から Claude Code と話す（VS Code の拡張と同じく claude CLI を子プロセスで動かす）。

原稿ごとに1つ。claude -p を stream-json の入出力で常駐させ、SDK と同じ制御のやり取り（control_request /
control_response）で、モデル・許可のモードの切り替え、使用量・状態・MCP の問い合わせ、ファイルの巻き戻しをする。
CLI からの許可の問い合わせ（can_use_tool）は画面に出して、押された答えを返す。

画面へは、stream-json の出来事を短い形（k: 種類）に直して溜めておき、/api/claude/events?after=番号 で、その番号より
後の出来事を待って渡す（長いポーリング）。会話を作り直したとき（新しい会話・再開・巻き戻し）は epoch を増やし、
画面は最初から受け取り直す。作業場所は原稿のフォルダ。ログインは Claude Code のもの（~/.claude）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

EFFORTS = ("low", "medium", "high", "xhigh", "max")
MODES = ("default", "acceptEdits", "plan", "auto", "bypassPermissions")
WAIT = 25   # 長いポーリングで待つ秒数
# 画面から送ってよい問い合わせ（CLI の control_request の subtype）
CONTROLS = {"initialize", "list_models", "get_usage", "get_status", "mcp_status", "mcp_toggle", "mcp_reconnect",
            "get_context_usage", "list_permission_rules", "get_hooks_listing", "get_memory_dialog",
            "get_skills_dialog", "get_settings", "get_session_cost", "rewind_files", "apply_flag_settings",
            "get_sandbox_dialog", "reload_plugins", "update_settings"}


class ClaudeError(Exception):
    pass


def find_claude() -> str | None:
    """PATH の claude。無ければ VS Code の拡張に入っているもの（版の新しい方）。"""
    if p := shutil.which("claude"):
        return p
    exts = sorted(Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return str(exts[0]) if exts else None


def asset(name: str) -> Path | None:
    """チャット欄に出すアイコン（Clawd・Claude と Codex のロゴ）。VS Code の拡張に入っているものを読む（同梱しない）。"""
    where = {"clawd.svg": ("anthropic.claude-code-*", "clawd.svg"),
             "claude-logo.svg": ("anthropic.claude-code-*", "claude-logo.svg"),
             "codex-logo.svg": ("openai.chatgpt-*", "blossom-white.svg")}.get(name)
    if not where:
        return None
    for d in sorted(Path.home().glob(f".vscode/extensions/{where[0]}/resources"), reverse=True):
        if (d / where[1]).is_file():
            return d / where[1]
    return None


def sessions_dir(cwd: Path) -> Path:
    """Claude Code が会話を残す場所（~/.claude/projects/<作業場所の英数字以外を - にしたもの>）。"""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def _prompt(tex: Path) -> str:
    return (f"あなたは overleaf-compiler（ローカルの Overleaf 風エディタ）の右のチャット欄から呼ばれている。"
            f"作業場所は LaTeX 原稿のフォルダで、主文書は {tex.name}。"
            "ファイルを書き換えると overleaf-compiler が自動で組み直し、エディタと PDF に反映する。"
            "latexmk などで自分で組む必要は無い。組版のエラーを見たいときは主文書と同じ名前の .log を読む。"
            "ユーザの発言の先頭に［エディタ］で始まる行があれば、ユーザが今エディタで見ている場所を表す。")


EDITOR_CTX = re.compile(r"\A(［エディタ］[^\n]*(?:\n```\n.*?\n```)?)\n\n", re.S)


def split_ctx(text: str) -> tuple[str, str]:
    """送った文の先頭に付けたエディタの場所を、表示のために分ける。"""
    m = EDITOR_CTX.match(text)
    if not m:
        return "", text
    first = m.group(1).split("\n", 1)[0].removeprefix("［エディタ］")
    return first, text[m.end():]


class Chat:
    def __init__(self, tex: Path, key: str | None = None):
        self.tex = tex
        self.key = key or str(tex)    # 最後の会話を覚える名前（タブごとに違う。chats.py）
        self.cwd = tex.parent
        self.lock = threading.Condition()
        self.events: list[dict] = []    # 画面へ渡す出来事。番号は events の添字 + 1
        self.epoch = 0                  # 会話を作り直すたびに増やす
        self.proc: subprocess.Popen | None = None
        self.session: str | None = None
        self.title = ""
        self.opts = {"model": "default", "effort": "medium", "mode": "auto", "thinking": True}
        self.started: dict | None = None   # 今の子プロセスを起動したときの effort と thinking
        self.resume_at: str | None = None  # 次の起動で、この発言のところまでで会話を切る（巻き戻し）
        self.busy = False
        self.info: dict = {}               # initialize の答え（コマンド・モデル・アカウント）
        self.stderr: list[str] = []
        self.waits: dict[str, list] = {}   # 送った問い合わせの番号 → [Event, 答え]
        self.perms: dict[str, dict] = {}   # CLI からの許可の問い合わせ（番号 → 中身）
        self._restore()

    # ---- 画面から ----
    def state(self) -> dict:
        return {"busy": self.busy, "session": self.session, "title": self.title, "epoch": self.epoch,
                "opts": self.opts, "available": bool(find_claude())}

    def wait_events(self, q: dict) -> dict:
        after = int(q.get("after", 0))
        with self.lock:
            if int(q.get("epoch", -1)) != self.epoch:
                after = 0
            elif len(self.events) <= after:
                self.lock.wait(WAIT)
            return {"events": self.events[after:], "next": len(self.events), "from": after, **self.state()}

    def start(self, _=None) -> dict:
        """チャット欄を開いたとき。CLI を起動して、コマンドとモデルの一覧を返す。"""
        self._ensure()
        if not self.info.get("models"):
            try:
                init = self._ask({"subtype": "initialize"}, 30)
            except ClaudeError:
                init = {}
            models = self._ask({"subtype": "list_models"}, 30).get("models") or init.get("models", [])
            # スラッシュコマンドから Skills を除く（VS Code の拡張と同じく、／の一覧に Skills は出さない）
            try:
                skills = self._ask({"subtype": "get_skills_dialog"}, 30).get("skills", [])
            except ClaudeError:
                skills = []
            names = {s.get("name") for s in skills} | {s.get("display_name") for s in skills} | _known_skills()
            self.all_commands = init.get("commands", [])
            self.info = {"commands": _without_skills(self.all_commands, names),
                         "models": models, "account": init.get("account", {}),
                         "fast": init.get("fast_mode_state"), "agents": init.get("agents", []),
                         "remote": {"available": init.get("remote_control_available") is not False,
                                    "default": bool(init.get("remote_control_auto_enable"))}}
        return {**self.state(), **self.info, "settings": self._settings()}

    def _settings(self) -> dict:
        """／メニューの切り替え（Switch models when a message is flagged・Enable Remote Control for all sessions）の今の値。"""
        try:
            eff = self._ask({"subtype": "get_settings"}, 20).get("effective", {})
        except ClaudeError:
            eff = {}
        return {"switchModelsOnFlag": eff.get("switchModelsOnFlag", True),
                "remoteControlAtStartup": eff.get("remoteControlAtStartup", self.info.get("remote", {}).get("default", False))}

    def account(self, body: dict) -> dict:
        """Switch account（別のアカウントでログイン）と Sign out（このパソコンの Claude からサインアウト）。"""
        exe = find_claude()
        if not exe:
            raise ClaudeError("claude コマンドが見つからない")
        if body.get("action") == "logout":
            r = subprocess.run([exe, "auth", "logout"], capture_output=True, text=True, timeout=60)
            self.close()
            self.info = {}
            if r.returncode:
                raise ClaudeError((r.stderr or r.stdout or "サインアウトできなかった").strip()[:300])
            return {"ok": True}
        # ログインはブラウザでの確認が要るので、端末で claude auth login を開く
        from .launcher import open_terminal
        if not open_terminal([exe, "auth", "login"]):
            raise ClaudeError("端末を開けなかった。端末で  claude auth login  を実行すること")
        self.close()
        self.info = {}
        return {"ok": True}

    def set(self, body: dict) -> dict:
        """モデル・許可のモード・考える深さ・Thinking を変える。モデルとモードはすぐ、深さと Thinking は次に送るとき。"""
        o = self.opts
        if body.get("model") and body["model"] != o["model"]:
            o["model"] = str(body["model"])
            if self._alive():
                self._ask({"subtype": "set_model", "model": None if o["model"] == "default" else o["model"]})
        if body.get("mode") in MODES and body["mode"] != o["mode"]:
            o["mode"] = body["mode"]
            if self._alive():
                self._ask({"subtype": "set_permission_mode", "mode": o["mode"]})
        if body.get("effort") in EFFORTS:
            o["effort"] = body["effort"]
        if "thinking" in body:
            o["thinking"] = bool(body["thinking"])
        with self.lock:
            self._push({"k": "opts", **o})
        return self.state()

    def send(self, body: dict) -> dict:
        """発言を送る。content は Anthropic の content ブロック（文字・画像・PDF）の並び。"""
        content = body.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not content:
            raise ClaudeError("送る文が空")
        with self.lock:
            if self.busy:
                raise ClaudeError("まだ返答の途中（止めてから送る）")
        self._ensure()
        with self.lock:
            self._push({"k": "user", "text": str(body.get("show", "")), "ctx": str(body.get("ctx", "")),
                        "files": body.get("files") or []})
            self.busy = True
        self._write({"type": "user", "message": {"role": "user", "content": content}})
        return self.state()

    def permission(self, body: dict) -> dict:
        """許可の問い合わせに答える。allow / deny、always なら同じものを以後は聞かない。"""
        rid = body.get("id", "")
        req = self.perms.pop(rid, None)
        if not req:
            raise ClaudeError("この問い合わせはもう終わっている")
        if body.get("behavior") == "allow":
            r = {"behavior": "allow", "updatedInput": body.get("input") or req.get("input", {})}
            if body.get("always") and req.get("permission_suggestions"):
                r["updatedPermissions"] = req["permission_suggestions"]
        else:
            r = {"behavior": "deny", "message": body.get("message") or "ユーザが断った", "interrupt": not body.get("message")}
        self._write({"type": "control_response",
                     "response": {"subtype": "success", "request_id": rid, "response": r}})
        with self.lock:
            self._push({"k": "permission_done", "id": rid, "behavior": r["behavior"],
                        "message": body.get("message", "")})
        return self.state()

    def control(self, body: dict) -> dict:
        """使用量・状態・MCP などの問い合わせ（CONTROLS のもの）をそのまま CLI に渡す。"""
        sub = body.get("subtype")
        if sub not in CONTROLS:
            raise ClaudeError(f"{sub} は問い合わせられない")
        self._ensure()
        return self._ask({k: v for k, v in body.items()}, 60)

    def stop(self, _=None) -> dict:
        """返答を途中で止める（会話は残る）。"""
        if self._alive() and self.busy:
            for rid in list(self.perms):
                self.permission({"id": rid, "behavior": "deny"})
            self._write({"type": "control_request", "request_id": uuid.uuid4().hex,
                         "request": {"subtype": "interrupt"}})
        return self.state()

    def reset(self, _=None) -> dict:
        """新しい会話にする（Clear conversation）。"""
        self.close()
        with self.lock:
            self._renew([])
            self.session, self.title, self.resume_at = None, "", None
        self._remember()
        return self.state()

    # ---- 会話の一覧・再開・巻き戻し ----
    def sessions(self, _=None) -> dict:
        d = sessions_dir(self.cwd)
        out = []
        for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]:
            title, first = "", ""
            try:
                with f.open(encoding="utf-8") as fh:
                    for line in fh:
                        if '"custom-title"' in line or '"ai-title"' in line or (not first and '"type":"user"' in line):
                            o = json.loads(line)
                            if o.get("type") == "custom-title":
                                title = o.get("customTitle", title)
                            elif o.get("type") == "ai-title" and not title:
                                title = o.get("aiTitle", "")
                            elif o.get("type") == "user" and not first and not o.get("isMeta"):
                                first = _user_text(o.get("message", {}).get("content"))
            except (OSError, json.JSONDecodeError):
                continue
            if not first and not title:
                continue
            out.append({"id": f.stem, "title": title or split_ctx(first)[1][:80], "mtime": f.stat().st_mtime,
                        "current": f.stem == self.session})
        return {"sessions": out}

    def resume(self, body: dict) -> dict:
        """前の会話を開き直す（Resume conversation）。"""
        sid = str(body.get("id", ""))
        f = sessions_dir(self.cwd) / f"{sid}.jsonl"
        if not re.fullmatch(r"[0-9a-f-]{36}", sid) or not f.is_file():
            raise ClaudeError("その会話が見つからない")
        self.close()
        evs, title = self._load(f)
        with self.lock:
            self.session, self.title, self.resume_at = sid, title, None
            self._renew(evs)
        self._remember()
        return self.state()

    def rewind(self, body: dict) -> dict:
        """発言の前まで戻す（Rewind）。what: both（会話とコード）/ conversation / code。"""
        uid, what = str(body.get("uuid", "")), body.get("what", "both")
        if self.busy:
            raise ClaudeError("返答の途中は戻せない（止めてから）")
        if not self.session or not uid:
            raise ClaudeError("戻す場所が分からない")
        r: dict = {}
        if what in ("both", "code"):
            self._ensure()
            r = self._ask({"subtype": "rewind_files", "user_message_id": uid}, 60)
            if r.get("error"):
                raise ClaudeError(f"ファイルを戻せなかった: {r['error']}")
        prompt = ""
        if what in ("both", "conversation"):
            f = sessions_dir(self.cwd) / f"{self.session}.jsonl"
            parent, prompt = _parent_of(f, uid)
            self.close()
            with self.lock:
                cut = next((i for i, e in enumerate(self.events) if e.get("k") == "user" and e.get("uuid") == uid),
                           len(self.events))
                if parent is None:   # 最初の発言まで戻す = 新しい会話
                    self.session, self.resume_at = None, None
                    self._renew([])
                else:
                    self.resume_at = parent
                    self._renew(self.events[:cut])
            self._remember()
        return {**self.state(), "prompt": split_ctx(prompt)[1], "files": r.get("filesChanged", [])}

    def terminal(self, _=None) -> dict:
        """この会話を端末の Claude Code で開く（Open Claude in Terminal）。"""
        from .launcher import open_terminal
        exe = find_claude()
        if not exe:
            raise ClaudeError("claude コマンドが見つからない")
        if not open_terminal([exe] + (["--resume", self.session] if self.session else []), self.cwd):
            raise ClaudeError("端末を開けなかった")
        return self.state()

    # ---- 原稿ごとの最後の会話（開き直したら続きを出す。VS Code の拡張と同じ）----
    def _restore(self) -> None:
        sid = _last_sessions().get(self.key)
        f = sessions_dir(self.cwd) / f"{sid}.jsonl" if sid else None
        if f and f.is_file():
            try:
                self.events, self.title = self._load(f)
                self.session = sid
            except OSError:
                pass

    def _remember(self) -> None:
        if _last_sessions().get(self.key) != self.session:
            set_last(self.key, self.session)

    def close(self) -> None:
        p, self.proc = self.proc, None
        self.busy = False
        if p and p.poll() is None:
            try:
                p.stdin.close()
                p.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                p.kill()

    # ---- 子プロセス ----
    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _renew(self, events: list[dict]) -> None:
        """self.lock を持って呼ぶ。出来事を入れ替え、画面に最初から受け取り直させる。"""
        self.events, self.epoch, self.perms = events, self.epoch + 1, {}
        self.lock.notify_all()

    def _ensure(self) -> None:
        """子プロセスが無いか、起動し直さないと変えられない設定（深さ・Thinking・巻き戻し）が変わったら起動する。"""
        want = {"effort": self.opts["effort"], "thinking": self.opts["thinking"]}
        if self._alive() and self.started == want and not self.resume_at:
            return
        exe = find_claude()
        if not exe:
            raise ClaudeError("claude コマンドが見つからない（Claude Code を入れるか、VS Code の拡張を入れる）")
        self.close()
        o = self.opts
        cmd = [exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages", "--replay-user-messages", "--permission-prompt-tool", "stdio",
               "--permission-mode", o["mode"], "--effort", o["effort"],
               "--thinking", "adaptive" if o["thinking"] else "disabled", "--append-system-prompt", _prompt(self.tex)]
        if o["model"] != "default":
            cmd += ["--model", o["model"]]
        if self.session:
            cmd += ["--resume", self.session]
            if self.resume_at:
                cmd += [f"--resume-session-at={self.resume_at}", "--fork-session"]
        self.resume_at = None
        self.proc = subprocess.Popen(cmd, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
                                     env={**os.environ, "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
                                          "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING": "true"})
        self.started, self.stderr = want, []
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_err, args=(self.proc,), daemon=True).start()

    def _write(self, obj: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (OSError, AttributeError) as e:
            with self.lock:
                self.busy = False
                self._push({"k": "error", "text": f"claude に送れなかった: {e}"})

    def _ask(self, req: dict, timeout: float = 20) -> dict:
        """CLI に問い合わせて答えを待つ。"""
        rid = uuid.uuid4().hex
        box = [threading.Event(), None]
        self.waits[rid] = box
        self._write({"type": "control_request", "request_id": rid, "request": req})
        if not box[0].wait(timeout):
            self.waits.pop(rid, None)
            raise ClaudeError(f"{req.get('subtype')} の答えが来ない")
        r = box[1] or {}
        if r.get("subtype") == "error":
            raise ClaudeError(r.get("error") or f"{req.get('subtype')} に失敗した")
        return r.get("response") or {}

    def _read_err(self, p: subprocess.Popen) -> None:
        for line in p.stderr:
            self.stderr = (self.stderr + [line.rstrip()])[-20:]

    def _read(self, p: subprocess.Popen) -> None:
        for line in p.stdout:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") == "control_response":
                r = o.get("response", {})
                box = self.waits.pop(r.get("request_id", ""), None)
                if box:
                    box[1] = r
                    box[0].set()
                continue
            if o.get("type") == "control_request":
                self._from_cli(o)
                continue
            evs = self._convert(o)
            if evs:
                with self.lock:
                    for e in evs:
                        if e["k"] == "uuid":   # 残しておく発言にも付ける（開き直した画面でも戻せるように）
                            u = next((x for x in reversed(self.events) if x["k"] == "user"), None)
                            if u is not None and not u.get("uuid"):
                                u["uuid"] = e["uuid"]
                        self._push(e)
        p.wait()
        with self.lock:
            if self.proc is p:   # close() で止めたときは知らせない
                if self.busy or p.returncode:
                    tail = "\n".join(self.stderr[-8:])
                    self._push({"k": "error", "text": f"claude が終了した（{p.returncode}）\n{tail}".strip()})
                self.busy = False
                self.proc = None
                self.lock.notify_all()

    def _from_cli(self, o: dict) -> None:
        """CLI からの問い合わせ。許可（can_use_tool）は画面に出し、それ以外は扱えないと答える。"""
        rid, req = o.get("request_id", ""), o.get("request", {})
        if req.get("subtype") == "can_use_tool":
            self.perms[rid] = req
            view = _tool_view(req.get("tool_name", ""), req.get("input") or {}, self._rel)
            with self.lock:
                self._push({"k": "permission", "id": rid, "name": req.get("tool_name"),
                            "title": req.get("title") or req.get("display_name") or req.get("tool_name"),
                            "description": req.get("description", ""), "input": req.get("input") or {},
                            "suggestions": req.get("permission_suggestions") or [], "tool_id": req.get("tool_use_id"),
                            **view})
            return
        self._write({"type": "control_response",
                     "response": {"subtype": "error", "request_id": rid, "error": "この画面では扱えない"}})

    def _push(self, e: dict) -> None:
        """self.lock を持って呼ぶ。"""
        e["t"] = time.time()
        self.events.append(e)
        self.lock.notify_all()

    # ---- stream-json → 画面向けの出来事 ----
    def _rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.cwd) if os.path.isabs(path) else path
        except ValueError:
            return path

    def _convert(self, o: dict) -> list[dict]:
        t, sub = o.get("type"), o.get("subtype")
        if o.get("parent_tool_use_id"):   # サブエージェントの中の動きは出さない
            return []
        if t == "system":
            if sub == "init":
                self.session = o.get("session_id") or self.session
                # 会話の始めに来る Skill の一覧（最初から入っている Skill も載る）を覚え、／の一覧から外す
                if o.get("skills") and _remember_skills(o["skills"]) and getattr(self, "all_commands", None):
                    self.info["commands"] = _without_skills(self.all_commands, _known_skills())
                    extra = [{"k": "commands", "commands": self.info["commands"]}]
                else:
                    extra = []
                self._remember()
                return [{"k": "init", "model": o.get("model", ""), "mode": o.get("permissionMode", ""),
                         "session": self.session}] + extra
            if sub == "session_title_changed" and o.get("title"):
                self.title = o["title"]
                return [{"k": "title", "title": self.title}]
            if sub == "compact_boundary":
                return [{"k": "note", "text": "会話を要約した（compact）"}]
            if sub == "api_retry":
                return [{"k": "note", "text": f"API を再試行している（{o.get('attempt', '')} 回目）"}]
            if sub == "status" and o.get("status") == "compacting":
                return [{"k": "status", "text": "要約している"}]
            return []
        if t == "stream_event":
            ev = o.get("event", {})
            if ev.get("type") == "content_block_start":
                kind = ev.get("content_block", {}).get("type")
                return [{"k": "block", "kind": kind}] if kind in ("text", "thinking") else []
            if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                return [{"k": "delta", "text": ev["delta"]["text"]}]
            return []
        if t == "assistant":
            return _assistant_events(o, self._rel)
        if t == "user":
            if o.get("isReplay") or _user_text(o.get("message", {}).get("content")):
                # 送った発言が CLI から戻ってきた。巻き戻しに使う番号（uuid）を画面の発言に付ける
                return [{"k": "uuid", "uuid": o.get("uuid")}] if o.get("uuid") else []
            return _result_events(o)
        if t == "result":
            self.session = o.get("session_id") or self.session
            self._remember()
            self.busy = False
            u = o.get("usage") or {}
            title = self._saved_title()
            extra = [{"k": "title", "title": title}] if title and title != self.title else []
            if extra:
                self.title = title
            return extra + [{"k": "done", "error": bool(o.get("is_error")), "subtype": sub or "",
                     "seconds": round(o.get("duration_ms", 0) / 1000, 1), "cost": o.get("total_cost_usd"),
                     "stop": o.get("stop_reason"), "result": o.get("result", "") if o.get("is_error") else "",
                     "tokens": (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                                + u.get("cache_creation_input_tokens", 0))}]
        if t == "rate_limit_event":
            w = o.get("rate_limit_info", {}).get("unifiedWindows", {})
            return [{"k": "limits", **{k: v.get("utilization") for k, v in w.items() if isinstance(v, dict)}}]
        return []

    def _saved_title(self) -> str:
        """会話の記録に Claude Code が付けた題名（ai-title・custom-title）。"""
        f = sessions_dir(self.cwd) / f"{self.session}.jsonl"
        title = ""
        try:
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    if '"custom-title"' in line or '"ai-title"' in line:
                        o = json.loads(line)
                        title = o.get("customTitle") or o.get("aiTitle") or title
        except (OSError, json.JSONDecodeError):
            pass
        return title

    def _load(self, f: Path) -> tuple[list[dict], str]:
        """残っている会話（jsonl）を、画面向けの出来事にする（Resume のとき）。"""
        evs, title = [], ""
        for line in f.open(encoding="utf-8"):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = o.get("type")
            if t == "custom-title":
                title = o.get("customTitle", title)
            elif t == "ai-title" and not title:
                title = o.get("aiTitle", "")
            if o.get("isSidechain") or o.get("isMeta") or t not in ("user", "assistant"):
                continue
            if t == "assistant":
                evs += _assistant_events(o, self._rel)
                continue
            text = _user_text(o.get("message", {}).get("content"))
            if text:
                if text.startswith(("<local-command", "<command-", "Caveat:")):
                    continue
                ctx, body = split_ctx(text)
                files = [c.get("source", {}).get("media_type", "file")
                         for c in o["message"]["content"] if isinstance(c, dict) and c.get("type") in ("image", "document")] \
                    if isinstance(o["message"].get("content"), list) else []
                evs.append({"k": "user", "text": body, "ctx": ctx, "files": [{"name": m} for m in files],
                            "uuid": o.get("uuid"), "t": 0})
            else:
                evs += _result_events(o)
        return evs, title


LAST_SESSIONS = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "overleaf-compiler" / "claude-sessions.json"


SKILLS_CACHE = LAST_SESSIONS.parent / "claude-skills.json"


def _known_skills() -> set[str]:
    """前に会話の始めで知った Skill の名前（get_skills_dialog には最初から入っている Skill が載らないため）。"""
    try:
        return set(json.loads(SKILLS_CACHE.read_text()))
    except (OSError, ValueError):
        return set()


def _remember_skills(names: list[str]) -> bool:
    """Skill の名前を覚える。新しく増えたら True。"""
    known = _known_skills()
    new = known | {n for n in names if isinstance(n, str)} | {n.split(":", 1)[1] for n in names if isinstance(n, str) and ":" in n}
    if new == known:
        return False
    try:
        SKILLS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        SKILLS_CACHE.write_text(json.dumps(sorted(new), ensure_ascii=False))
    except OSError:
        pass
    return True


def _without_skills(commands: list[dict], skills: set[str]) -> list[dict]:
    """スラッシュコマンドから Skill（と内部用の __ で始まるもの）を除く。"""
    return [c for c in commands if c.get("name") not in skills and not c.get("name", "").startswith("__")
            and not any(a in skills for a in c.get("aliases") or [])]


_LAST_LOCK = threading.Lock()


def _last_sessions() -> dict:
    """タブの名前（原稿の絶対パスと番号）→ 最後に使った会話の番号。ほかに tabs:<原稿> にタブの並び。"""
    try:
        return json.loads(LAST_SESSIONS.read_text())
    except (OSError, ValueError):
        return {}


def set_last(key: str, value) -> None:
    """1つの値を書き換える（None なら消す）。複数の会話が同時に書くので、読み書きをまとめて排他する。"""
    with _LAST_LOCK:
        d = _last_sessions()
        if value is None:
            d.pop(key, None)
        else:
            d[key] = value
        try:
            LAST_SESSIONS.parent.mkdir(parents=True, exist_ok=True)
            tmp = LAST_SESSIONS.with_suffix(".tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
            tmp.replace(LAST_SESSIONS)
        except OSError:
            pass


def _user_text(content) -> str:
    """人が書いた発言の文字（道具の結果は除く）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
            return ""
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _parent_of(f: Path, uid: str) -> tuple[str | None, str]:
    """発言（uuid）の1つ前の記録と、その発言の文。巻き戻しで、ここまでで会話を切る。"""
    try:
        for line in f.open(encoding="utf-8"):
            if uid in line:
                o = json.loads(line)
                if o.get("uuid") == uid:
                    return o.get("parentUuid"), _user_text(o.get("message", {}).get("content"))
    except (OSError, json.JSONDecodeError):
        pass
    raise ClaudeError("戻す発言が会話の記録に見つからない")


def _assistant_events(o: dict, rel) -> list[dict]:
    out = []
    for c in o.get("message", {}).get("content", []):
        if c.get("type") == "text" and c.get("text"):
            out.append({"k": "text", "text": c["text"]})
        elif c.get("type") == "thinking" and c.get("thinking"):
            out.append({"k": "thinking", "text": c["thinking"]})
        elif c.get("type") == "tool_use":
            out.append({"k": "tool", "id": c.get("id"), "name": c.get("name"), "input": c.get("input") or {},
                        **_tool_view(c.get("name", ""), c.get("input") or {}, rel)})
    return out


def _result_events(o: dict) -> list[dict]:
    content = o.get("message", {}).get("content")
    out = []
    for c in content if isinstance(content, list) else []:
        if isinstance(c, dict) and c.get("type") == "tool_result":
            r = c.get("content")
            if isinstance(r, list):
                r = "\n".join(x.get("text", "") for x in r if isinstance(x, dict))
            out.append({"k": "result", "id": c.get("tool_use_id"), "error": bool(c.get("is_error")),
                        "text": str(r or "")[:6000]})
    return out


def _tool_view(n: str, i: dict, rel) -> dict:
    """道具の呼び出しを、見出しの1行（what）と、あれば変更の中身（old / new）にする。"""
    path = rel(i["file_path"]) if isinstance(i.get("file_path"), str) else \
        rel(i["notebook_path"]) if isinstance(i.get("notebook_path"), str) else None
    v: dict = {"path": path} if path else {}
    if n == "Edit":
        v["old"], v["new"] = str(i.get("old_string", ""))[:6000], str(i.get("new_string", ""))[:6000]
    elif n == "MultiEdit":
        eds = i.get("edits") or []
        v["old"] = "\n…\n".join(str(e.get("old_string", "")) for e in eds)[:6000]
        v["new"] = "\n…\n".join(str(e.get("new_string", "")) for e in eds)[:6000]
    elif n == "Write":
        v["new"] = str(i.get("content", ""))[:6000]
    if path:
        v["what"] = path
    elif n == "Bash":
        v["what"] = str(i.get("description") or i.get("command", ""))
    elif "pattern" in i:
        v["what"] = str(i["pattern"]) + (f"  {rel(i['path'])}" if i.get("path") else "")
    elif "url" in i or "query" in i:
        v["what"] = str(i.get("url") or i.get("query"))
    elif "description" in i:
        v["what"] = str(i["description"])
    elif n in ("TodoWrite", "AskUserQuestion"):
        v["what"] = ""
    else:
        v["what"] = json.dumps(i, ensure_ascii=False)[:200]
    return v
