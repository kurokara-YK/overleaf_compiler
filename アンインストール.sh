#!/bin/bash
# overleaf-compiler をパソコンから削除する。アプリの一覧の「overleaf-compiler の削除」か、右クリック →「プログラムとして実行」で使う。
# 原稿（data/）とこのフォルダは消さない。
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if ! command -v python3 >/dev/null; then
    command -v zenity >/dev/null && zenity --error --text="python3 が見つかりません"
    exit 1
fi

# 画面が使えるなら確認の画面を出す
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && python3 -c "import PySide6" 2>/dev/null; then
    exec python3 -m gui.uninstaller
fi

# 画面が無い環境。zenity があれば確認を取る
if command -v zenity >/dev/null 2>&1; then
    zenity --question --title="overleaf-compiler の削除" --width=380 \
      --text="overleaf-compiler をパソコンから削除します（原稿は消しません）。\n\nよろしいですか？" || exit 0
fi
python3 -m overleaf_compiler.install uninstall "$@"
command -v zenity >/dev/null 2>&1 && zenity --info --title="overleaf-compiler" --width=320 --text="削除しました。" 2>/dev/null || true
