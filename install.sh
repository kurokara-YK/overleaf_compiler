#!/bin/bash
# overleaf-compiler のセットアップ（端末用）。sudo も Docker も使わない。何度実行してもよい。
#
#   1. TeX Live を ~/texlive/<年> に入れる（既に latexmk があれば飛ばす）
#   2. 追加の TeX パッケージを入れる（足りないものだけ）
#   3. pandoc を ~/.local/bin に入れる（Word・Markdown・HTML への書き出しに使う。既にあれば飛ばす）
#      gh（GitHub CLI）も ~/.local/bin に入れる（Git の画面で GitHub にログインするのに使う）
#   4. overleaf-compiler コマンドを ~/.local/bin に作る
#   5. ~/.bashrc に TeX Live の PATH を足す（既にあれば飛ばす）
#   6. アプリの一覧に登録する（--no-launcher で登録しない）
#
# 実際の処理は overleaf_compiler/install.py にある。セットアップ画面（setup.sh）も同じものを呼ぶ。
# 画面で使うもの（pdf.js・pdf-lib・CodeMirror・marked・フォント）はプログラムに同梱してあるので、入れる必要は無い。
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || { echo "Python 3.10 以上が必要"; exit 1; }

exec python3 -m overleaf_compiler.install install "$@"
