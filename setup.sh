#!/bin/bash
# overleaf-compiler のセットアップ画面。アプリの一覧の「overleaf-compiler セットアップ」から開く。
#
# 画面（PySide6）が使えればセットアップの画面を開く。使えない環境（SSH など）では端末版の install.sh と同じ処理をする。
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

command -v python3 >/dev/null || { echo "python3 が必要です。sudo apt install python3"; exit 1; }

if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && python3 -c "import PySide6" 2>/dev/null; then
    exec python3 -m gui.installer
fi

echo "画面を使えないため、コマンドライン版で導入します。"
echo "（画面版を使うには PySide6 が要る。Ubuntu なら  sudo apt install python3-pyside6.qtwidgets"
echo "  pip を使うなら  pip install --user --break-system-packages PySide6 ）"
echo
exec python3 -m overleaf_compiler.install install "$@"
