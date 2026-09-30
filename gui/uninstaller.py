"""削除の確認画面。消す前に何が消えるか（何が残るか）を見せる。実際の処理は overleaf_compiler.install.uninstall。"""
from __future__ import annotations

import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout

from gui.common import REPO, body, card, run, title
from overleaf_compiler import install


class _Worker(QThread):
    line = Signal(str)
    done = Signal(bool)

    def __init__(self, opts: dict):
        super().__init__()
        self.opts = opts

    def run(self) -> None:
        try:
            install.uninstall(self.opts, self.line.emit)
            self.done.emit(True)
        except Exception as e:
            self.line.emit(f"エラー: {e}")
            self.done.emit(False)


class Uninstaller(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("overleaf-compiler の削除")
        self.resize(580, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(title("本当にアンインストールしますか？"))
        lay.addWidget(body("overleaf-compiler をパソコンから取り除きます。\n元に戻すには、もう一度セットアップしてください。", "Subtitle"))
        lay.addSpacing(12)
        lay.addWidget(card(body(
            "消えるもの\n\n"
            "  ・ アプリの一覧とドックのアイコン\n"
            "  ・ 端末の  overleaf-compiler  コマンド\n"
            "  ・ 裏で動いているサーバー（止めます）と、その記録・設定\n\n"
            "残るもの\n\n"
            f"  ・ 原稿（{REPO / 'data'}）\n"
            "  ・ 変更履歴（下で選んだときだけ消す）\n"
            f"  ・ このフォルダ（{REPO}）")))
        lay.addSpacing(8)
        s = install.status()
        self.texlive = QCheckBox("TeX Live も消す（~/texlive。ほかの LaTeX のソフトも使えなくなる）")
        self.texlive.setVisible(bool(s["texlive_user"]))
        self.pandoc = QCheckBox("pandoc も消す（~/.local/bin/pandoc）")
        self.pandoc.setVisible((install.BIN / "pandoc").exists())
        self.history = QCheckBox("変更履歴も消す（ファイルの前の版。消すと戻せない）")
        self.history.setVisible((install.STATE / "history").exists())
        lay.addWidget(self.texlive)
        lay.addWidget(self.pandoc)
        lay.addWidget(self.history)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        lay.addWidget(self.log)
        lay.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        self.cancel = QPushButton("やめる")
        self.cancel.clicked.connect(self.reject)
        self.run_btn = QPushButton("アンインストールする")
        self.run_btn.setObjectName("Danger")
        self.run_btn.clicked.connect(self._run)
        row.addWidget(self.cancel)
        row.addWidget(self.run_btn)
        lay.addLayout(row)
        self.worker: _Worker | None = None

    def _run(self) -> None:
        for w in (self.run_btn, self.texlive, self.pandoc, self.history):
            w.setEnabled(False)
        self.log.setVisible(True)
        self.worker = _Worker({"texlive": self.texlive.isChecked(), "pandoc": self.pandoc.isChecked(),
                               "history": self.history.isChecked()})
        self.worker.line.connect(self.log.append)
        self.worker.done.connect(self._finished)
        self.worker.start()

    def _finished(self, ok: bool) -> None:
        self.log.append("\n✅ 削除しました。" if ok else "\n❌ 途中で失敗しました（上を見ること）")
        self.cancel.setText("閉じる")
        self.run_btn.setVisible(False)


def main() -> int:
    return run(Uninstaller)


if __name__ == "__main__":
    sys.exit(main())
