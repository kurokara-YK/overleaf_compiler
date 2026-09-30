"""設定・状態の画面（アプリの一覧の右クリック「設定・状態を確認する」）。
サーバーの起動・停止、必要なものがそろっているか、開き方、ログイン時の準備、原稿の置き場所。
"""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

from gui.common import REPO, body, card, restyle, run, status_row, title
from overleaf_compiler import install, launcher


class Settings(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("overleaf-compiler — 設定・状態")
        self.resize(640, 720)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        lay.addWidget(title("設定・状態"))
        lay.addSpacing(8)

        # ---- サーバー ----
        lay.addWidget(body("サーバー", "Section"))
        self.srv = QLabel()
        self.srv.setObjectName("Big")
        self.srv_detail = body("", "Subtitle")
        row = QHBoxLayout()
        self.b_open = self._btn("開く", lambda: self._launch("app"), "Primary")
        self.b_stop = self._btn("止める", self._stop)
        self.b_log = self._btn("ログ", lambda: subprocess.Popen(["xdg-open", str(launcher.LOG)]))
        for b in (self.b_open, self.b_stop, self.b_log):
            row.addWidget(b)
        row.addStretch()
        self.srv_card = card(self.srv, self.srv_detail, row)
        lay.addWidget(self.srv_card)
        lay.addSpacing(10)

        # ---- 必要なもの ----
        lay.addWidget(body("必要なもの", "Section"))
        self.req = QVBoxLayout()
        lay.addWidget(card(self.req))
        lay.addSpacing(10)

        # ---- 開き方 ----
        lay.addWidget(body("開き方", "Section"))
        self.app_win = QRadioButton("アプリのウィンドウ（タブもアドレス欄も無い、専用のウィンドウ）")
        self.tab_win = QRadioButton("いつものブラウザのタブ")
        grp = QButtonGroup(self)
        grp.addButton(self.app_win)
        grp.addButton(self.tab_win)
        (self.tab_win if install.config().get("window") == "tab" else self.app_win).setChecked(True)
        self.app_win.toggled.connect(lambda on: install.set_config(window="app" if on else "tab"))
        self.pin = QCheckBox("ドックにピン留めする")
        self.pin.setChecked(install.status()["pinned"])
        self.pin.setEnabled(install.status()["launcher"])
        self.pin.toggled.connect(lambda on: (install.set_pinned(on, lambda m: None), self.refresh()))
        self.autostart = QCheckBox("ログインしたら裏で準備しておく（開くのが速くなる）")
        self.autostart.setChecked(install.status()["autostart"])
        self.autostart.toggled.connect(lambda on: install.set_autostart(on, lambda m: None))
        lay.addWidget(card(self.app_win, self.tab_win, self.pin, self.autostart))
        lay.addSpacing(10)

        # ---- 原稿の置き場所 ----
        lay.addWidget(body("原稿の置き場所", "Section"))
        p = QLabel(str(REPO / "data"))
        p.setObjectName("Path")
        p.setWordWrap(True)
        prow = QHBoxLayout()
        prow.addWidget(self._btn("フォルダを開く", lambda: subprocess.Popen(["xdg-open", str(REPO / "data")])))
        prow.addStretch()
        lay.addWidget(card(p, prow))
        lay.addStretch()

        # ---- 下の並び ----
        foot = QHBoxLayout()
        foot.addWidget(self._btn("セットアップをやり直す", lambda: subprocess.Popen([str(REPO / "setup.sh")], start_new_session=True)))
        foot.addWidget(self._btn("削除する…", lambda: subprocess.Popen([str(REPO / "アンインストール.sh")], start_new_session=True), "Danger"))
        foot.addStretch()
        foot.addWidget(self._btn("閉じる", self.close))
        outer.addLayout(foot)

        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_server)
        self.timer.start(2000)

    def _btn(self, text: str, fn, obj: str = "Small") -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj if obj != "Primary" and obj != "Danger" else obj)
        b.clicked.connect(fn)
        return b

    def _launch(self, *args: str) -> None:
        subprocess.Popen([str(REPO / "overleaf_compiler.sh"), *args], start_new_session=True)
        QTimer.singleShot(1500, self._refresh_server)

    def _stop(self) -> None:
        launcher.stop_server()
        self._refresh_server()

    def refresh(self) -> None:
        while self.req.count():
            it = self.req.takeAt(0)
            if it.layout():
                while it.layout().count():
                    w = it.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        s = install.status()
        self.req.addLayout(status_row("TeX Live", bool(s["latexmk"]), s["latexmk"] or "入っていない（セットアップで入れる）"))
        self.req.addLayout(status_row("pandoc", bool(s["pandoc"]), s["pandoc"] or "入っていない（Word などへの書き出しだけが使えない）"))
        self.req.addLayout(status_row("Claude Code", True if s["claude"] else None, s["claude"] or "無くてもよい（右のチャット欄に使う）"))
        self.req.addLayout(status_row("Codex", True if s["codex"] else None, s["codex"] or "無くてもよい（右のチャット欄で Codex を使う）"))
        self.req.addLayout(status_row("コマンド", s["command"], "端末で overleaf-compiler を使える" if s["command"] else "まだ（セットアップで作る）"))
        self.req.addLayout(status_row("アプリの一覧", s["launcher"], "登録済み" if s["launcher"] else "まだ（セットアップで登録する）"))
        self.req.addLayout(status_row("ドック", s["pinned"] or None, "ピン留めしている" if s["pinned"] else "ピン留めしていない（下の「開き方」で切り替える）"))
        self._refresh_server()

    def _refresh_server(self) -> None:
        s = launcher.server_info()
        if s:
            self.srv.setObjectName("BigOk")
            self.srv.setText("✅  動いています")
            self.srv_detail.setText(f"http://127.0.0.1:{s['port']}/   （番号 {s['pid']}）")
            self.srv_card.setObjectName("CardOk")
        else:
            self.srv.setObjectName("Big")
            self.srv.setText("止まっています")
            self.srv_detail.setText("「開く」を押すと起動します。")
            self.srv_card.setObjectName("Card")
        self.b_stop.setEnabled(bool(s))
        restyle(self.srv, self.srv_card)


def main() -> int:
    return run(Settings)


if __name__ == "__main__":
    sys.exit(main())
