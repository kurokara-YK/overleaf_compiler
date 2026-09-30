"""画面の共通部品（見出し・本文・カード・状態の行）と、起動の手順。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def title(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("Title")
    lb.setWordWrap(True)
    return lb


def body(text: str, obj: str = "") -> QLabel:
    lb = QLabel(text)
    lb.setWordWrap(True)
    if obj:
        lb.setObjectName(obj)
    return lb


def card(*widgets, obj: str = "Card") -> QFrame:
    f = QFrame()
    f.setObjectName(obj)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    for w in widgets:
        lay.addWidget(w) if isinstance(w, QWidget) else lay.addLayout(w)
    return f


def status_row(name: str, ok: bool | None, detail: str) -> QHBoxLayout:
    """✅ 名前 … 詳細 の1行。ok が None なら「任意（無くてもよい）」。"""
    row = QHBoxLayout()
    mark = QLabel("✅" if ok else "—" if ok is None else "⚠️")
    mark.setFixedWidth(26)
    n = QLabel(name)
    n.setObjectName("RowOk" if ok else "RowOff" if ok is None else "RowWarn")
    n.setFixedWidth(150)
    d = QLabel(detail)
    d.setObjectName("Subtitle")
    d.setWordWrap(True)
    row.addWidget(mark)
    row.addWidget(n)
    row.addWidget(d, 1)
    return row


def restyle(*ws) -> None:
    """objectName を変えたあとに見た目を付け直す。"""
    for w in ws:
        w.style().unpolish(w)
        w.style().polish(w)


def run(window_cls) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("overleaf-compiler")
    app.setDesktopFileName("overleaf-compiler")
    icon = REPO / "share" / "overleaf-compiler.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    qss = Path(__file__).resolve().parent / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    w = window_cls()
    w.show()
    return app.exec()
