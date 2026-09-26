<a name="readme-top"></a>

# overleaf-compiler

Overleaf からダウンロードした LaTeX の原稿を，**ローカルの PC で Overleaf と同じ画面のまま編集・コンパイル**し，
Overleaf へ戻す zip を作るツールです．

Docker も sudo も使いません．Python とホームディレクトリに入れる TeX Live だけで動きます．

<details>
  <summary>目次</summary>
  <ol>
    <li><a href="#どんなものか">どんなものか</a></li>
    <li><a href="#画面">画面</a></li>
    <li><a href="#動作環境">動作環境</a></li>
    <li><a href="#使いはじめる">使いはじめる</a></li>
    <li><a href="#使い方">使い方</a></li>
    <li><a href="#しくみ">しくみ</a></li>
    <li><a href="#コンパイルの設定">コンパイルの設定</a></li>
    <li><a href="#コマンド一覧">コマンド一覧</a></li>
    <li><a href="#ファイル構成">ファイル構成</a></li>
    <li><a href="#git管理上の注意">Git管理上の注意</a></li>
    <li><a href="#うまくいかないとき">うまくいかないとき</a></li>
    <li><a href="#関連資料">関連資料</a></li>
    <li><a href="#作成者">作成者</a></li>
    <li><a href="#ライセンス">ライセンス</a></li>
  </ol>
</details>

## どんなものか

Overleaf はブラウザの中のエディタなので，手元のエディタや Claude Code などのツールから直接ファイルを直せません．
このツールは，Overleaf の zip を手元に展開し，**Overleaf と同じ操作感で直して，同じ結果の PDF を確かめ，
Overleaf へ戻す zip を作る**ところまでを受け持ちます．

- **Overleaf と同じ画面**：ファイルツリー・タブ付きのエディタ・PDF を横に並べ，メニューやショートカットも Overleaf に合わせています
- **保存するとすぐ PDF が変わる**：保存から PDF の更新まで 1〜2 秒ほど（6 ページの和文原稿の例）
- **ローカルのエディタと同時に使える**：VS Code などでファイルを直すと，ブラウザの画面にも約 1 秒で反映されます
- **PDF と行き来できる**：PDF をダブルクリックするとソースの該当行へ移り，PDF の文字を選んでその場で書き換えることもできます
- **変更履歴**：ファイルの前の版を残し，差分を見て戻せます．消したファイルも戻せます
- **Overleaf へ戻す**：Overleaf の「Upload Project」にそのまま入れられる zip を作ります

Overleaf とのやり取りは，**人が手で行う「ダウンロード」と「アップロード」の2回だけ**です．
このツールが Overleaf に接続したり，Overleaf を操作したりすることはありません．

**このリポジトリに原稿のデータは含まれていません．** 原稿は利用者が `data/` に置きます（Git の管理対象外です）．

> **補足**
> このツールは Overleaf の公式のものではありません．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 画面

```text
┌ overleaf-compiler  ファイル 編集 表示 ヘルプ    data / 学会2026 / 論文A / main.tex      エディタ|両方|PDF ┐
│📁│ ファイル  📄＋ 📁＋ ⤒  │ main.tex | 01_intro.tex        │→│ [リコンパイル] ログ ⤓   1/6  − ＋ 幅に合わせる │
│🔍│ ▾ 📂 chapter            │  1 \documentclass{...}          │←│                                                │
│🕘│   │ 📄 01_intro.tex  ⋮  │  …                              │ │                      PDF                       │
│  │ ▾ アウトライン           │                                 │ │                                                │
└──┴─────────────────────────┴─────────────────────────────────┴─┴────────────────────────────────────────────────┘
```

| 場所 | できること |
| --- | --- |
| 上のメニュー | ファイル（新規ファイル・新規フォルダ・アップロード・変更履歴・文字数・ダウンロード），編集，表示，ヘルプ |
| 📁 ファイル | ファイルツリー．各ファイルの **⋮** で名前の変更・ダウンロード・削除．下に `\section` などのアウトライン |
| 🔍 検索 | 原稿の全ファイルを検索（大文字小文字の区別・正規表現・単語単位） |
| 🕘 変更履歴 | ファイルの前の版と差分．「この版に戻す」「この変更の前に戻す」 |
| エディタ | 行番号と色分けの付いたエディタ．入力は自動で保存．`.md` は **Ctrl+Shift+V** で整えた表示に切り替え |
| PDF | リコンパイル・ログ（エラー数）・ダウンロード・ページ番号・拡大縮小．文字の選択とコピー |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 動作環境

| 項目 | 内容 |
| --- | --- |
| OS | Linux（Ubuntu 24.04 で確認） |
| Python | 3.10 以上（標準ライブラリだけで動きます） |
| ブラウザ | Chrome・Firefox など |
| TeX | TeX Live（`install.sh` がホームディレクトリに入れます） |

画面で使う部品（PDF 表示の pdf.js，エディタの CodeMirror，Markdown 表示の marked，フォント）は
リポジトリに同梱しているので，インターネットにつながっていなくても動きます．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 使いはじめる

```sh
git clone https://github.com/kurokara-YK/overleaf_compiler.git
cd overleaf_compiler
bash install.sh
```

`install.sh` は次のものを入れます．何度実行しても構いません（入っているものは飛ばします）．

| 入れるもの | 場所 |
| --- | --- |
| TeX Live（日本語・文献処理・TikZ などを含む） | `~/texlive/<年>`（sudo 不要．初回だけ 1.5 GB ほど・10〜30 分） |
| 追加の TeX パッケージ（論文でよく使うフォントと，コンパイルを速くする `mylatexformat`） | TeX Live の中 |
| pandoc（Word・Markdown・HTML への書き出し用） | `~/.local/bin` |
| `overleaf-compiler` コマンド | `~/.local/bin` |
| TeX Live の PATH | `~/.bashrc` に1行足します |

終わったら端末を開き直し，次のコマンドで起動します．

```sh
overleaf-compiler
```

ブラウザが開き，`data/` の一覧が表示されます．止めるときは端末で **Ctrl+C** を押します．

| 起動のしかた | 開くもの |
| --- | --- |
| `overleaf-compiler` | `data/` の一覧 |
| `overleaf-compiler data/学会2026/` | そのフォルダの一覧 |
| `overleaf-compiler data/学会2026/論文A/` | その原稿（主文書が1つのとき） |
| `overleaf-compiler --no-browser` | ブラウザを開かない（表示された URL を自分で開く） |
| `overleaf-compiler --port 9000` | ポート番号を変える（既定は 8765．使用中なら次の番号を使う） |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 使い方

### 1. Overleaf から原稿を持ってくる

Overleaf で原稿を開き，**File → ダウンロード → Download as source (.zip)** で zip を保存します．
その zip を，一覧画面の点線の枠へ**ドラッグ＆ドロップ**します（枠をクリックして選んでも構いません）．

- 一覧で**今いるフォルダ**に，zip と同じ名前のフォルダで展開されます（`data` の直下なら新しいワークスペースになります）
- 同じ名前があれば `_2` を付けて別に展開します．既存のものは上書きしません
- 「フォルダを作る」で，今いるフォルダの中に空のフォルダを作れます

### 2. 原稿を選ぶ

一覧は `data` のフォルダを階層どおりにたどります．📁 フォルダを押すと中へ入り，📄 原稿を押すと開きます．

```text
data  →  学会2026  →  論文A（原稿）
```

- 上部の `data / 学会2026` を押すと，その階層へ戻ります．パスはすべて `data` からの相対パスで表示します
- 主文書（`\documentclass` を含む `.tex`）が**複数ある**原稿は，カードの中のボタンで開くものを選びます
- `.tex` が無く，中身が LaTeX の `.txt` がある原稿には「`.tex` に名前を変えて開く」ボタンが出ます

### 3. 直す

エディタで直すと，入力が止まって 0.7 秒でファイルに保存され，PDF が組み直されます．

| 操作 | 内容 |
| --- | --- |
| PDF をダブルクリック | ソースの該当行へ移る |
| 境目の **→** | カーソルのある行を PDF 上で示す |
| 境目の **←** | PDF で選んだ文字（無ければ画面の中央）のソースへ移る |
| PDF の文字を選んで **✎ ここで直す** | その場で書き換えると，`.tex` の同じ文字が置き換わる（Overleaf には無い操作） |
| **リコンパイル**（Ctrl+Enter） | 最初から全部組み直す |
| **ログ** | エラーの一覧．行を押すとその箇所が開く |

`\cite` の番号や数式のように，PDF とソースで文字が違う部分は PDF の上では直せません．そのときはソースへ案内します．

**ローカルのエディタと同時に使えます．**

| どこで直すか | 何が起きるか |
| --- | --- |
| ブラウザのエディタ | すぐにローカルのファイルに書き込まれ，PDF が組み直される |
| ローカル（VS Code など） | 約 1 秒でブラウザのエディタの文面が置き換わり，PDF も組み直される |

両方で同じファイルを同時に直した場合は，どちらかを勝手に捨てず，
「外の内容を読み込む／こちらで上書き」を選ぶ表示が出ます．

### 4. 変更履歴を見る

左端の 🕘 に，いつ・どのファイルを・何行変えたかが並びます．押すと差分（緑が足した行，赤が消した行）が出ます．

- 版が残るのは，ブラウザで保存したとき・ローカルで直したとき・削除したとき・前の版に戻したときです
- 自動保存で版が増えすぎないよう，同じファイルを 60 秒以内に続けて直した分は1つの版にまとめます
- **削除したファイルも履歴に残る**ので，選んで「この版に戻す」で戻せます
- 履歴は原稿のフォルダの外（`~/.local/share/overleaf-compiler/history/`）に置くので，原稿のフォルダは汚れません

### 5. Overleaf へ戻す

**ファイル → ダウンロード → ソース (.zip)** で，Overleaf にそのまま入れられる zip が落ちます．

- **新しいプロジェクトとして上げる**：Overleaf の New Project → **Upload Project** に zip を入れる
- **今あるプロジェクトへ戻す**：変更したファイルを，Overleaf の **File → ファイルのアップロード** で上書きする
  （どのファイルを変えたかは 🕘 変更履歴で分かります）

zip には中間生成物・組んだ PDF・バックアップを入れません．
`latexmkrc` が無い和文の原稿には，Overleaf でも同じエンジンで組めるよう `latexmkrc` を足します．

同じ「ダウンロード」から，PDF と Word（.docx）・Markdown（.md）・HTML（.html）にも書き出せます．
Word などへの書き出しは pandoc に任せているので，数式や表，独自のクラスの体裁は崩れることがあります．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## しくみ

```text
Overleaf          … File → ダウンロード → Download as source (.zip)（人が行う）
    ↓
data/             … zip を展開した原稿（ローカル）
    ↓
overleaf-compiler … 127.0.0.1 だけで動くサーバ．保存のたびに TeX Live で組み直す
    ↓
ブラウザ           … Overleaf と同じ画面で編集し，PDF を確かめる
    ↓
Overleaf          … ソース (.zip) を Upload Project に入れる（人が行う）
```

**保存から PDF の更新までを短くするため，次のようにしています．**

- 保存したらすぐ組み始めます．ローカルでの変更も，原稿が読み込むファイルの更新時刻を 0.25 秒ごとに見て検出します
- 変更のたびの組版は1回だけにし，参照番号や文献が変わったときだけ続けて全体を組み直します（数秒後に番号がそろいます）
- プリアンブル（`\begin{document}` より前）を読み込んだ状態を保存しておき，毎回の読み込みを省きます．
  プリアンブルやクラスファイルを変えると自動で作り直します（pdfLaTeX・pLaTeX・upLaTeX のとき）
- PDF にするときの圧縮を少し弱めています（画像の多い原稿で 3 倍速く，大きさは 3% ほど増えます）．
  提出用の PDF は「リコンパイル」を押してから落とすと，通常の圧縮になります

PDF の上に出る「（高速）」は保存した形式を使った組版，「（1回）」は使わない組版，「（全体）」は最初からの組版です．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## コンパイルの設定

Overleaf の Compiler の設定は zip に入らないので，次の順で決めます．

1. 主文書と同じフォルダの `latexmkrc`（Overleaf もこのファイルを読みます）
2. 無ければ本文から推定します

| 本文 | エンジン |
| --- | --- |
| `luatexja` を読む / `ltjs*` クラス | LuaLaTeX |
| `fontspec` / `xeCJK` を読む | XeLaTeX |
| `uplatex` オプション / `u*article` / `jlreq` / `bxjs*` | upLaTeX + dvipdfmx |
| `jsarticle` / `jarticle` など | pLaTeX + dvipdfmx |
| 上記以外で和文を含む | LuaLaTeX |
| それ以外 | pdfLaTeX |

推定が外れるときは `latexmkrc` を置いてください．Overleaf 側とローカルの結果がそろいます．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## コマンド一覧

画面を使わずに，端末から使うこともできます．

| コマンド | 内容 |
| --- | --- |
| `overleaf-compiler [場所]` | ブラウザで開く |
| `overleaf-compiler import <zip> [展開先]` | Overleaf の zip を展開する．展開先の既定は `data/<zip の名前>` |
| `overleaf-compiler check <原稿> [--json]` | 組んで，エラー・未定義の参照・はみ出しを `ファイル:行` で出す．失敗なら終了コード 1 |
| `overleaf-compiler export <原稿> [-o 出力.zip]` | Overleaf に入れる zip を作る |
| `overleaf-compiler build <原稿>` | 1回だけ組む（latexmk の出力をそのまま出す） |
| `overleaf-compiler clean <原稿>` | 中間生成物を消す |

`<原稿>` は主文書の `.tex` か，それを含むフォルダです．`--data <フォルダ>` で `data/` 以外の置き場を使えます．

`check` は，Claude Code などのツールに原稿を直させたあとの確認に使えます．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## ファイル構成

<details>
  <summary>各ファイルの説明を開く</summary>

| ファイル | 説明 |
| --- | --- |
| `install.sh` | 初回のセットアップ．TeX Live・追加のパッケージ・pandoc・コマンドを入れます |
| `overleaf_compiler.sh` | 起動スクリプト．`~/.local/bin/overleaf-compiler` はここへのリンクです |
| `pyproject.toml` | pip / pipx で入れる場合の定義（入れなくても動きます） |
| `overleaf_compiler/cli.py` | コマンド（serve / check / import / export / build / clean） |
| `overleaf_compiler/server.py` | ローカルのサーバ．127.0.0.1 でしか待ち受けません |
| `overleaf_compiler/builder.py` | 組版．保存のたびの速い組版と，latexmk による全体の組版 |
| `overleaf_compiler/project.py` | 主文書の特定，エンジンの推定，フォルダの一覧，ファイルツリー |
| `overleaf_compiler/sync.py` | ファイルの読み書き，SyncTeX による PDF とソースの対応，PDF 上での書き換え |
| `overleaf_compiler/history.py` | 変更履歴 |
| `overleaf_compiler/search.py` | 原稿の全ファイルの検索 |
| `overleaf_compiler/report.py` | ログから直すべき箇所を拾う（`check` で使う） |
| `overleaf_compiler/overleaf.py` | zip の展開と，Overleaf へ戻す zip の作成 |
| `overleaf_compiler/static/index.html` | 画面 |
| `overleaf_compiler/static/pdfjs/` | pdf.js（同梱） |
| `overleaf_compiler/static/codemirror/` | CodeMirror 5（同梱） |
| `overleaf_compiler/static/marked/` | marked（同梱） |
| `overleaf_compiler/static/fonts/` | Ubuntu Mono・Noto Sans（同梱） |
| `data/` | **原稿の置き場．** 中身は Git の管理対象外です |

</details>

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## Git管理上の注意

`data/` の中身は `.gitignore` で除外しています．
**原稿には未発表の論文や個人名が含まれることが多いため，このリポジトリには含めないでください．**

原稿の履歴を残したい場合は，`data/` の中のフォルダごとに `git init` し，**非公開のリポジトリ**で管理してください．

> **注意**
> 原稿のフォルダには，参考文献として他人の論文の PDF を置くこともあります．
> 公開リポジトリに載せると著作権の問題になるので，原稿は非公開で管理してください．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## うまくいかないとき

| 症状 | 確認すること |
| --- | --- |
| `File 'xxx.sty' not found` | パッケージが足りません．`tlmgr install xxx` で入れます（sudo 不要） |
| `overleaf-compiler` が見つからない | 端末を開き直す．または `bash overleaf_compiler.sh` で起動する |
| ダブルクリックしても移らない | 図の中や余白は対応する行がありません．本文やキャプションをダブルクリックするか，ファイルツリーから開く |
| PDF が更新されない | 「ログ」にエラーが出ていないか確認する |
| 「外でも変更された」と出る | ブラウザとローカルで同じファイルを同時に直しました．どちらを残すか選びます |
| ポートが使用中 | 自動で次の番号を使います．表示された URL を開きます |
| Overleaf で組めない | Menu → Main document が主文書になっているか，`latexmkrc` が最上位にあるかを確認する |
| 文書の中から外部コマンドを実行する原稿が組めない | `\ShellEscape` などは安全のため実行しません |
| TeX Live を消したい | `~/texlive` と `~/.texlive<年>` を消し，`~/.bashrc` の該当行を消す |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 関連資料

- [Overleaf](https://www.overleaf.com/) ／ [Overleaf のソースコード（GitHub）](https://github.com/overleaf/overleaf)
- [Overleaf — Uploading a project](https://www.overleaf.com/learn/how-to/Uploading_a_project)
- [TeX Live](https://tug.org/texlive/) ／ [TeX Live のインストール（install-tl）](https://tug.org/texlive/quickinstall.html)
- [latexmk](https://www.ctan.org/pkg/latexmk)
- [SyncTeX](https://github.com/jlaurens/synctex)
- [mylatexformat](https://www.ctan.org/pkg/mylatexformat)
- [TeXcount](https://app.uio.no/ifi/texcount/)
- [pandoc](https://pandoc.org/)
- [PDF.js](https://mozilla.github.io/pdf.js/)
- [CodeMirror 5](https://codemirror.net/5/)
- [marked](https://marked.js.org/)
- [Ubuntu Mono](https://design.ubuntu.com/font) ／ [Noto Sans](https://fonts.google.com/noto/specimen/Noto+Sans)

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 作成者

| 項目 | 内容 |
| --- | --- |
| 作成者 | kurokara-YK |
| 連絡先 | kurokara1226@gmail.com |
| リンク集 | https://lit.link/kurokara |

不具合の報告や改善の提案は，Issues または上記のメールアドレスまでお願いします．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## ライセンス

このリポジトリのコードは自由に利用・改変してください．

同梱している次の部品は，それぞれのライセンスに従います．ライセンスの文面は各フォルダにあります．

| 部品 | ライセンス | 場所 |
| --- | --- | --- |
| PDF.js | Apache-2.0 | `overleaf_compiler/static/pdfjs/` |
| CodeMirror 5 | MIT | `overleaf_compiler/static/codemirror/` |
| marked | MIT | `overleaf_compiler/static/marked/` |
| Ubuntu Mono | Ubuntu Font Licence 1.0 | `overleaf_compiler/static/fonts/` |
| Noto Sans | SIL Open Font License 1.1 | `overleaf_compiler/static/fonts/` |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>
