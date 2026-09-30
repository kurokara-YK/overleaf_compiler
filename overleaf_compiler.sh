#!/usr/bin/env bash
# overleaf-compiler の起動スクリプト。インストール不要（依存ライブラリは無い）。
# ~/.local/bin/overleaf-compiler からシンボリックリンクで呼ばれても動くよう、実体の場所を辿る。
#   overleaf-compiler settings  設定・状態の画面（PySide6。アプリの一覧の右クリックから）
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
if [ "${1:-}" = "settings" ]; then
  cd "$here" && exec python3 -m gui.main
fi
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m overleaf_compiler "$@"
