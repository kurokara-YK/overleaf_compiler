"""セットアップの画面（Windows のインストーラーと同じ流れ）。実際の処理は overleaf_compiler.install にある。ここは画面と進行だけ。

ようこそ → 環境の確認 → 内容の選択 → 導入 → 完了
"""
from __future__ import annotations

import shutil
import subprocess
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QRadioButton, QTextEdit, QVBoxLayout,
    QWizard, QWizardPage,
)

from gui.common import REPO, body, card, run, status_row, title
from overleaf_compiler import install


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(title("overleaf-compiler セットアップ"))
        lay.addWidget(body("Overleaf からダウンロードした LaTeX の原稿を、このパソコンで Overleaf と同じ画面のまま\n"
                           "直して組めるようにします。右には Claude Code のチャット欄もあります。"))
        lay.addSpacing(16)
        lay.addWidget(body("このセットアップですること", "Section"))
        lay.addWidget(card(body(
            "1.  TeX Live（LaTeX を組むソフト）を入れます（入っていれば飛ばします）\n\n"
            "2.  pandoc（Word などへの書き出し）を入れます\n\n"
            "3.  端末で  overleaf-compiler  と打てば開けるようにします\n\n"
            "4.  アプリの一覧に登録します（アイコンは1つ。右クリックでサーバーを止める・設定）")))
        lay.addSpacing(12)
        lay.addWidget(body("パスワードの入力は必要ありません。すべてホームフォルダの中に入れます。\n"
                           "原稿は data フォルダに置きます。あとから削除しても原稿は消えません。", "Subtitle"))
        lay.addStretch()


class CheckPage(QWizardPage):
    """いま入っているものを見せる。足りないものは次の画面で入れられる。"""

    def __init__(self):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(title("環境の確認"))
        self.lay.addWidget(body("このパソコンに入っているものを調べました。"))
        self.lay.addSpacing(12)
        self.box = QVBoxLayout()
        self.lay.addWidget(card(self.box))
        self.lay.addSpacing(10)
        self.note = body("", "Subtitle")
        self.lay.addWidget(self.note)
        self.lay.addStretch()

    def initializePage(self) -> None:
        while self.box.count():
            it = self.box.takeAt(0)
            if it.layout():
                while it.layout().count():
                    w = it.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()
        s = install.status()
        self.box.addLayout(status_row("Python", True, s["python"]))
        self.box.addLayout(status_row("TeX Live", bool(s["latexmk"]), s["latexmk"] or "入っていない（次の画面で入れる。1.5 GB・10〜30 分）"))
        self.box.addLayout(status_row("pandoc", bool(s["pandoc"]), s["pandoc"] or "入っていない（Word・Markdown・HTML への書き出しに使う）"))
        self.box.addLayout(status_row("Claude Code", True if s["claude"] else None,
                                      s["claude"] or "無くてもよい。右のチャット欄を使うときは Claude Code か VS Code の拡張を入れる"))
        self.box.addLayout(status_row("Codex", True if s["codex"] else None,
                                      s["codex"] or "無くてもよい。右のチャット欄で Codex を使うときは Codex CLI か VS Code の Codex 拡張を入れる"))
        self.box.addLayout(status_row("コマンド", s["command"], "overleaf-compiler を使える" if s["command"] else "まだ（次の画面で作る）"))
        self.box.addLayout(status_row("アプリの一覧", s["launcher"], "登録済み" if s["launcher"] else "まだ（次の画面で登録する）"))
        missing = not s["latexmk"] or not s["pandoc"]
        self.note.setText("足りないものは、次の画面で選んで入れられます。" if missing else "必要なものはそろっています。")


class OptionsPage(QWizardPage):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(title("セットアップの内容"))
        lay.addWidget(body("必要なものを選んでください。"))
        lay.addSpacing(10)
        self.cb = {}
        for key, label, note in (
            ("texlive", "TeX Live を入れる", "LaTeX を組むのに必要です（~/texlive に入れる。1.5 GB ほど）"),
            ("pandoc", "pandoc を入れる", "Word・Markdown・HTML への書き出しに使います"),
            ("command", "端末のコマンドを作る", "端末で  overleaf-compiler  と打つと開けます（今までどおり）"),
            ("launcher", "アプリの一覧に追加する", "アプリの一覧やドックから開けます。右クリックでサーバーを止める・設定を開く"),
            ("pin", "ドックにピン留めする", "画面の下（横）のアプリの並びに、いつも置いておきます"),
            ("autostart", "ログインしたら裏で準備しておく", "開くのが速くなります（ウィンドウは開きません）"),
        ):
            cb = QCheckBox(label)
            cb.setChecked(key != "autostart")
            self.cb[key] = cb
            lay.addWidget(cb)
            lay.addWidget(body(f"        {note}", "Subtitle"))
            lay.addSpacing(2)
        lay.addSpacing(10)
        lay.addWidget(body("開き方", "Section"))
        self.app_win = QRadioButton("アプリのウィンドウで開く（タブもアドレス欄も無い、専用のウィンドウ）")
        self.tab_win = QRadioButton("いつものブラウザのタブで開く")
        grp = QButtonGroup(self)
        grp.addButton(self.app_win)
        grp.addButton(self.tab_win)
        lay.addWidget(self.app_win)
        lay.addWidget(self.tab_win)
        lay.addStretch()
        lay.addWidget(body(f"置き場所: {REPO}（原稿は {REPO / 'data'}）", "Subtitle"))

    def initializePage(self) -> None:
        s = install.status()
        for key, have in (("texlive", s["latexmk"]), ("pandoc", s["pandoc"])):
            if have:   # 入っているものは選べなくして、入っていることを見せる
                self.cb[key].setChecked(True)
                self.cb[key].setEnabled(False)
                self.cb[key].setText(self.cb[key].text().replace("を入れる", "（入っている）"))
        self.cb["autostart"].setChecked(s["autostart"])
        self.cb["launcher"].toggled.connect(self.cb["pin"].setEnabled)   # 一覧に無いとピン留めできない
        (self.tab_win if install.config().get("window") == "tab" else self.app_win).setChecked(True)

    def opts(self) -> dict:
        return {k: cb.isChecked() for k, cb in self.cb.items()}


class _Worker(QThread):
    """導入を裏で動かす（画面を固めないため）。"""
    line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, opts: dict):
        super().__init__()
        self.opts = opts

    def run(self) -> None:
        try:
            install.install_all(self.opts, self.line.emit)
            self.done.emit(True, "")
        except Exception as e:
            self.done.emit(False, str(e))


class ProgressPage(QWizardPage):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(title("セットアップしています"))
        lay.addWidget(body("しばらくお待ちください。TeX Live を入れるときは 10〜30 分かかります。"))
        lay.addSpacing(10)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)
        row = QHBoxLayout()
        row.addStretch()
        self.retry = QPushButton("もう一度試す")
        self.retry.setObjectName("Primary")
        self.retry.setVisible(False)
        self.retry.clicked.connect(self.initializePage)
        row.addWidget(self.retry)
        lay.addLayout(row)
        self._done = self._ok = False
        self.worker: _Worker | None = None

    def initializePage(self) -> None:
        self._done = self._ok = False
        self.retry.setVisible(False)
        self.log.clear()
        self.bar.setRange(0, 0)
        page = self.wizard().options
        install.set_config(window="tab" if page.tab_win.isChecked() else "app")
        self.worker = _Worker(page.opts())
        self.worker.line.connect(self.log.append)
        self.worker.done.connect(self._finish)
        self.worker.start()

    def _finish(self, ok: bool, err: str) -> None:
        self._done, self._ok = True, ok
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if ok:
            self.log.append("\n✅ セットアップが終わりました。")
        else:
            self.log.append(f"\n❌ うまくいきませんでした\n\n{err}")
            self.retry.setVisible(True)   # 失敗したまま先へ進ませない
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._done and self._ok


class DonePage(QWizardPage):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(title("使えるようになりました"))
        lay.addWidget(body(
            "開き方\n\n"
            "  ● アプリの一覧（またはドック）の  overleaf-compiler\n"
            "  ● 端末で  overleaf-compiler\n\n"
            "アイコンを右クリックすると、次のことができます。\n\n"
            "  ● ブラウザのタブで開く\n"
            "  ● サーバーを止める\n"
            "  ● 設定・状態を確認する\n\n"
            "Overleaf の zip（Download as source）は、開いた画面にドロップすると取り込めます。"))
        lay.addStretch()
        self.open_now = QCheckBox("今すぐ overleaf-compiler を開く")
        self.open_now.setChecked(True)
        lay.addWidget(self.open_now)


class InstallerWizard(QWizard):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("overleaf-compiler セットアップ")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.resize(700, 640)
        self.options = OptionsPage()
        self.done_page = DonePage()
        for page in (WelcomePage(), CheckPage(), self.options, ProgressPage(), self.done_page):
            self.addPage(page)
        self.setButtonText(QWizard.NextButton, "次へ  ›")
        self.setButtonText(QWizard.BackButton, "‹  戻る")
        self.setButtonText(QWizard.FinishButton, "完了")
        self.setButtonText(QWizard.CancelButton, "中止")
        self.button(QWizard.NextButton).setObjectName("Primary")
        self.button(QWizard.FinishButton).setObjectName("Primary")
        self.finished.connect(self._after)

    def _after(self, result: int) -> None:
        if result and self.done_page.open_now.isChecked():
            subprocess.Popen([str(REPO / "overleaf_compiler.sh"), "app"], start_new_session=True)


def main() -> int:
    return run(InstallerWizard)


if __name__ == "__main__":
    sys.exit(main())
