#!/usr/bin/env bash
# overleaf-compiler の起動スクリプト。インストール不要（依存ライブラリは無い）。
# ~/.local/bin/overleaf-compiler からシンボリックリンクで呼ばれても動くよう、実体の場所を辿る。
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m overleaf_compiler "$@"
