#!/bin/bash
# overleaf-compiler のセットアップ。sudo も Docker も使わない。何度実行してもよい。
#
#   1. TeX Live を ~/texlive/<年> に入れる（既に latexmk があれば飛ばす）
#   2. 追加の TeX パッケージを入れる（足りないものだけ）
#   3. pandoc を ~/.local/bin に入れる（Word・Markdown・HTML への書き出しに使う。既にあれば飛ばす）
#   4. overleaf-compiler コマンドを ~/.local/bin に作る
#   5. ~/.bashrc に TeX Live の PATH を足す（既にあれば飛ばす）
#
# 画面で使うもの（pdf.js・CodeMirror・marked・フォント）はプログラムに同梱してあるので、入れる必要は無い。
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
HERE="$PWD"

python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || { echo "Python 3.10 以上が必要"; exit 1; }

# ---------------------------------------------------------------- 1. TeX Live
tl_bin() { ls -d "$HOME"/texlive/*/bin/* 2>/dev/null | sort -r | head -1; }

if command -v latexmk >/dev/null || [ -x "$(tl_bin)/latexmk" ]; then
  echo "TeX Live: 導入済み（$(command -v latexmk || echo "$(tl_bin)/latexmk")）"
else
  echo "TeX Live を ~/texlive へ入れる（1.5 GB ほど。回線によって 10〜30 分）"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  curl -fsSL https://mirror.ctan.org/systems/texlive/tlnet/install-tl-unx.tar.gz \
    | tar xz -C "$work" --strip-components=1
  year="$(grep -oE 'version [0-9]{4}' "$work/release-texlive.txt" | grep -oE '[0-9]{4}')"
  cat > "$work/profile" <<EOF
selected_scheme scheme-custom
TEXDIR $HOME/texlive/$year
TEXMFLOCAL $HOME/texlive/texmf-local
TEXMFSYSCONFIG $HOME/texlive/$year/texmf-config
TEXMFSYSVAR $HOME/texlive/$year/texmf-var
TEXMFHOME ~/texmf
TEXMFCONFIG ~/.texlive$year/texmf-config
TEXMFVAR ~/.texlive$year/texmf-var
binary_x86_64-linux 1
collection-basic 1
collection-latex 1
collection-latexrecommended 1
collection-latexextra 1
collection-langjapanese 1
collection-langcjk 1
collection-fontsrecommended 1
collection-pictures 1
collection-bibtexextra 1
collection-binextra 1
collection-mathscience 1
collection-luatex 1
instopt_adjustpath 0
instopt_letter 0
tlpdbopt_install_docfiles 0
tlpdbopt_install_srcfiles 0
tlpdbopt_autobackup 0
EOF
  (cd "$work" && perl ./install-tl -profile "$work/profile" -no-interaction)
fi

# ---------------------------------------------------------------- 2. 追加の TeX パッケージ
# 上のコレクションに入らないもの。足りないものだけ入れる（ユーザー権限の TeX Live なら sudo 不要）
#   newtx txfonts fontaxes boondox kastrup : 論文のクラスがよく読む Times 系のフォント
#   mylatexformat                          : プリアンブルを保存した形式を作り、組版を速くする
EXTRA="newtx txfonts fontaxes boondox kastrup mylatexformat"
TLMGR="$(command -v tlmgr || echo "$(tl_bin)/tlmgr")"
if [ -x "$TLMGR" ]; then
  have="$("$TLMGR" info --only-installed --data name 2>/dev/null || true)"
  need=""
  for p in $EXTRA; do grep -qx "$p" <<<"$have" || need="$need $p"; done
  if [ -n "$need" ]; then
    echo "TeX パッケージを入れる:$need"
    "$TLMGR" install $need || echo "注意: 入れられなかった。TeX Live が sudo で入れたものなら sudo tlmgr install$need"
  else
    echo "TeX パッケージ: そろっている（$EXTRA）"
  fi
fi

# ---------------------------------------------------------------- 3. pandoc
mkdir -p "$HOME/.local/bin"
if command -v pandoc >/dev/null || [ -x "$HOME/.local/bin/pandoc" ]; then
  echo "pandoc: 導入済み"
else
  echo "pandoc を ~/.local/bin に入れる（Word・Markdown・HTML への書き出し用）"
  case "$(uname -m)" in aarch64|arm64) arch=arm64 ;; *) arch=amd64 ;; esac
  tag="$(curl -fsSL https://api.github.com/repos/jgm/pandoc/releases/latest \
         | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])' 2>/dev/null || true)"
  pwork="$(mktemp -d)"
  if [ -n "$tag" ] && curl -fsSL "https://github.com/jgm/pandoc/releases/download/$tag/pandoc-$tag-linux-$arch.tar.gz" \
       | tar xz -C "$pwork" --strip-components=1; then
    install -m 755 "$pwork/bin/pandoc" "$HOME/.local/bin/pandoc" && echo "pandoc $tag を入れた"
  else
    echo "注意: pandoc を入れられなかった。Word などへの書き出しだけが使えない（ほかは使える）"
  fi
  rm -rf "$pwork"
fi

# ---------------------------------------------------------------- 4. overleaf-compiler コマンド
ln -sfn "$HERE/overleaf_compiler.sh" "$HOME/.local/bin/overleaf-compiler"
echo "overleaf-compiler: $HOME/.local/bin/overleaf-compiler → $HERE/overleaf_compiler.sh"

# ---------------------------------------------------------------- 5. PATH
bin="$(tl_bin)"
if [ -n "$bin" ] && ! grep -q 'texlive/.*/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\n# TeX Live（ユーザー権限で ~/texlive に導入。overleaf-compiler の install.sh が追加）\nexport PATH="%s:$PATH"\n' "$bin" >> "$HOME/.bashrc"
  echo "~/.bashrc に PATH を足した。新しい端末から有効になる"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "注意: ~/.local/bin が PATH に無い。~/.bashrc に足すこと" ;; esac

echo
echo "完了。どこからでも  overleaf-compiler  を実行すると、ブラウザで data/ のワークスペース一覧が開く。"
