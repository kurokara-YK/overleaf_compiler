#!/bin/bash
# overleaf-compiler のセットアップを、アプリの一覧に登録して開く。最初の1回だけ実行すればよい。
# セットアップが終わると、このアイコンは本体の overleaf-compiler に置き換わる（アイコンは1つ）。
# 入れ直しと削除は、本体を右クリック →「設定・状態を確認する」から。
# 右クリック →「プログラムとして実行」でも、端末から  bash はじめにこれを実行.sh  でもよい。
#
# GNOME（Ubuntu）の Files は、任意のフォルダに置いた .desktop を実行しない。
# 正式な場所に登録したものだけがアプリとして起動できるので、まずここへ登録する。
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
HERE="$(pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$APPS" "$ICONS"
cp share/overleaf-compiler.svg "$ICONS/overleaf-compiler.svg"

command -v python3 >/dev/null || { echo "python3 が見つかりません。"; read -rp "Enterで閉じます"; exit 1; }

cat > "$APPS/overleaf-compiler-setup.desktop" <<INNER
[Desktop Entry]
Type=Application
Version=1.0
Name=overleaf-compiler セットアップ
Comment=overleaf-compiler を使えるようにします（TeX Live・pandoc・アプリの登録）
Exec=$HERE/setup.sh
Icon=overleaf-compiler
Terminal=false
Categories=Settings;
INNER

command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true

echo
echo "  登録しました。"
echo
echo "  「アプリケーションを表示する」（画面左下の点が9つ並んだボタン）を開き，"
echo "  「overleaf-compiler セットアップ」をクリックしてください。"
echo "  見つからないときは，検索欄に overleaf と入力してください。"
echo

# そのままセットアップを開く（端末から実行しても、右クリックで実行しても同じ動き）
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    echo "  続けてセットアップを開きます..."
    exec "$HERE/setup.sh"
elif command -v zenity >/dev/null 2>&1; then
    zenity --info --title="overleaf-compiler" --width=380 \
      --text="アプリ一覧に登録しました。\n\n「overleaf-compiler セットアップ」を開いてください。" 2>/dev/null &
fi
