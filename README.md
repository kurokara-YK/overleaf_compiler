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
- **PDF にコメントを付ける**：Acrobat のように PDF の文字を選んでコメントを付け，コメント付きの PDF で落とせます．
  Acrobat でもらったコメント付きの PDF も取り込め，Claude Code に「コメントを直して」と頼めばローカルで直せます
- **変更履歴**：ファイルの前の版を残し，差分を見て戻せます．消したファイルも戻せます
- **Overleaf へ戻す**：Overleaf の「Upload Project」にそのまま入れられる zip を作ります

Overleaf とのやり取りは，**人が手で行う「ダウンロード」と「アップロード」の2回だけ**です．
このツールが Overleaf に接続したり，Overleaf を操作したりすることはありません．

**このリポジトリに原稿のデータは含まれていません．** 原稿は利用者が `data/` に置きます（Git の管理対象外です）．
試しに使えるよう，`data/sample/overleaf_sample/` にだけサンプル原稿（LuaLaTeX．章ファイル・図・表・数式・文献を含む．個人情報なし）を入れています．

> **補足**
> このツールは Overleaf の公式のものではありません．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 画面

```text
┌ overleaf-compiler  ファイル 編集 表示 ヘルプ    data / 学会2026 / 論文A / main.tex      エディタ|両方|PDF ┐
│📁│ ファイル  📄＋ 📁＋ ⤒  │ main.tex | 01_intro.tex        │→│ [リコンパイル] ログ ⤓   1/6  − ＋ 幅に合わせる │
│🔍│ ▾ 📂 chapter            │  1 \documentclass{...}          │←│                                                │
│🕘│   │ 📄 01_intro.tex  ⋮  │  …                              │ │                      PDF                       │
│💬│ ▾ アウトライン           │                                 │ │                                                │
└──┴─────────────────────────┴─────────────────────────────────┴─┴────────────────────────────────────────────────┘
```

| 場所 | できること |
| --- | --- |
| 上のメニュー | ファイル（新規ファイル・新規フォルダ・アップロード・変更履歴・文字数・ダウンロード），編集，表示，ヘルプ |
| 📁 ファイル | ファイルツリー．各ファイルの **⋮** で名前の変更・ダウンロード・履歴・**パスのコピー**（原稿のフォルダからの相対パス／`data/` からのパス／絶対パス）・削除．下に `\section` などのアウトライン |
| 🔍 検索 | 原稿の全ファイルを検索（大文字小文字の区別・正規表現・単語単位） |
| 🕘 変更履歴 | ファイルの前の版と差分．「この版に戻す」「この変更の前に戻す」 |
| 💬 コメント | PDF に付けたコメントの一覧（未解決の数を表示）．返信・解決・編集・削除，コメント付き PDF の取り込みと書き出し |
| エディタ | 行番号と色分けの付いたエディタ．入力は自動で保存．`.md` は **Ctrl+Shift+V** で整えた表示に切り替え |
| エディタのツールバー | Overleaf と同じ並び．元に戻す・見出しの種類・太字（Ctrl+B）・斜体（Ctrl+I）・数式・記号・リンク・参照（原稿の `\label` から選ぶ）・ラベル・引用（`.bib` の文献から選ぶ）・行のコメント・図・表・箇条書き・検索 |
| コード／ビジュアル | **ビジュアル**にすると，見出しは大きな太字，`\textbf` などは太字や斜体，`\cite` `\ref` `\label` は小さな札，`\item` は「•」，プリアンブルは折りたたんで表示する（文面は変えない）．カーソルを置いたところだけ元のコードに戻るので，そのまま直せる |
| ヘッダの原稿名 ▾ | PDF・ソース (.zip)・Word・Markdown・HTML のダウンロード，**複製を作る**，**名前を変更**（原稿のフォルダの名前．変更履歴も引き継ぐ） |
| 🕘 履歴 | Overleaf の History と同じ画面．左にファイル，中央に選んだ版の中身（足した行は緑，消した行は赤の取り消し線，行の中で変わった文字は濃い色），右に日付ごとの版の一覧と**ラベル**（版の ⋮ から付ける）．「この版に戻す」 |
| 表示 → テーマ | **ライト・ダーク・システムに合わせる**（Overleaf と同じ）．ブラウザに覚える |
| PDF | リコンパイル・ログ（エラー数）・ダウンロード・ページ番号・拡大縮小．文字の選択とコピー |
| **✳ Claude** / **Codex**（右上） | 右に Claude Code か Codex のチャット欄を出す（エディタ｜PDF｜チャット欄）．それぞれ VS Code の拡張と同じ操作（[7. Claude Code・Codex と話しながら直す](#7-claude-codecodex-と話しながら直す)） |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 動作環境

| 項目 | 内容 |
| --- | --- |
| OS | Linux（Ubuntu 24.04 で確認．Ubuntu 26.04 は Wayland の画面・Ptyxis の端末に合わせてあるが，まだ確かめていない） |
| Python | 3.10 以上（標準ライブラリだけで動きます） |
| ブラウザ | Chrome・Vivaldi・Chromium・Brave・Edge ならアプリのウィンドウで開く．Firefox などはタブで開く．開けなかったときは端末に URL を出す |
| TeX | TeX Live（`install.sh` がホームディレクトリに入れます） |
| PySide6 | セットアップ・削除・設定の画面に使います（無ければ端末で `install.sh` を使う） |
| Claude Code | 無くても動きます．右のチャット欄に使います（`claude` コマンドか，VS Code の Claude Code 拡張） |
| Codex | 無くても動きます．右のチャット欄で Codex を使うときに使います（`codex` コマンドか，VS Code の Codex 拡張） |

画面で使う部品（PDF 表示の pdf.js，エディタの CodeMirror，Markdown 表示の marked，フォント）は
リポジトリに同梱しているので，インターネットにつながっていなくても動きます．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 使いはじめる

### 画面でセットアップする

フォルダの **`はじめにこれを実行.sh`** を右クリック →「プログラムとして実行」（または端末で `bash はじめにこれを実行.sh`）．
アプリの一覧に「overleaf-compiler セットアップ」が登録され，続けてセットアップの画面が開きます．

セットアップの画面は，**ようこそ → 環境の確認 → 内容の選択 → 導入 → 完了** の順に進みます．
入れるものは下の `install.sh` と同じです（入っているものは飛ばします）．終わると，アプリの一覧に **overleaf-compiler** が出て，ドックにもピン留めされます（セットアップの画面か，設定・状態の画面で外せます）．

| アイコンの操作 | 内容 |
| --- | --- |
| クリック | 一覧を開く．サーバーは裏で動くので，端末は要りません |
| 右クリック → ブラウザのタブで開く | アプリのウィンドウではなく，いつものブラウザのタブで開く |
| 右クリック → サーバーを止める | 開いているウィンドウを閉じて，裏で動いているサーバーを止める |
| 右クリック → 設定・状態を確認する | サーバーの状態・必要なものがそろっているか・開き方・原稿の置き場所 |

既定のブラウザが Chromium 系（Vivaldi・Chrome・Chromium・Brave・Edge）なら，タブもアドレス欄も無い専用のウィンドウで開きます．
アプリの一覧に出るアイコンは本体の1つだけです（セットアップのアイコンは，導入が終わると本体に置き換わります）．
入れ直しと削除は，本体を右クリック →「設定・状態を確認する」の **セットアップをやり直す**／**削除する…** から．
**原稿（`data/`）と変更履歴は消しません**（変更履歴と TeX Live は，選んだときだけ消します）．

### 端末でセットアップする

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
| アプリの一覧への登録とドックへのピン留め（`--no-launcher` で登録しない） | `~/.local/share/applications` |

終わったら端末を開き直し，次のコマンドで起動します．

```sh
overleaf-compiler
```

アプリのウィンドウが開き，`data/` の一覧が表示されます．端末で **Ctrl+C** を押すか，ウィンドウを閉じると終わります．

| 起動のしかた | 開くもの |
| --- | --- |
| `overleaf-compiler` | `data/` の一覧（アプリのウィンドウ．既定のブラウザが Chromium 系のとき） |
| `overleaf-compiler --web` | ブラウザのタブで開く（今までの開き方．Ctrl+C でサーバーだけ止まる） |
| `overleaf-compiler data/学会2026/` | そのフォルダの一覧 |
| `overleaf-compiler data/学会2026/論文A/` | その原稿（主文書が1つのとき） |
| `overleaf-compiler --no-browser` | ブラウザを開かない（表示された URL を自分で開く） |
| `overleaf-compiler --port 9000` | ポート番号を変える（既定は 8765．使用中なら次の番号を使う） |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## 使い方

### 1. Overleaf から原稿を持ってくる

Overleaf で原稿を開き，**File → ダウンロード → Download as source (.zip)** で zip を保存します．
その zip を，一覧画面の点線の枠へ**ドラッグ＆ドロップ**します．
枠をクリックすると「取り込むものを選ぶ」窓が**ダウンロード**から開き，zip か，**展開済みの原稿のフォルダ**を選べます
（ダブルクリックでフォルダの中へ．ホームフォルダの中から選べる．ブラウザの窓で選ぶこともできる）．

- 一覧で**今いるフォルダ**に，zip と同じ名前のフォルダで取り込みます（`data` の直下なら新しいワークスペースになります）．フォルダを選んだときは写して取り込みます（元はそのまま）
- 同じ名前があれば `_2` を付けて別に取り込みます．既存のものは上書きしません
- 「フォルダを作る」で，今いるフォルダの中に空のフォルダを作れます
- 一覧の各項目の **⋮** から，**ダウンロード**（原稿は Overleaf に入れられる zip，フォルダは中身の zip），**名前を変更**（変更履歴は引き継ぐ），**削除**（ごみ箱へ．ファイルマネージャのごみ箱から戻せる）
- 「絞り込む」は，今いるフォルダの**下の階層まですべて**探します（フォルダ名・原稿名・主文書の名前）．結果には置き場所も出ます

### 2. 原稿を選ぶ

一覧は `data` のフォルダを階層どおりにたどります．📁 フォルダを押すと中へ入り，📄 原稿を押すと開きます．

```text
data  →  学会2026  →  論文A（原稿）
```

- 上部の `data / 学会2026` を押すと，その階層へ戻ります．パスはすべて `data` からの相対パスで表示します
- 主文書（`\documentclass` を含む `.tex`）が**複数ある**原稿は，カードの中のボタンで開くものを選びます
- **ブラウザの戻る・進むで，1つ前の画面へ戻れます．** 一覧のフォルダ（`?dir=`），原稿（`?p=`），変更履歴（`&view=history`）を URL に持つためです
- **ブラウザのタブごとに別の原稿を開けます．** タブを複製するか，新しいタブで `http://127.0.0.1:8765/` を開いて別の原稿を選びます．
  開いた原稿は URL（`?p=原稿`）に入るので，再読み込みやタブの複製でも同じ原稿が開きます．
  ローカルでの変更は，その原稿を開いているタブにだけ反映されます．見ているタブが無くなった原稿は，組版を止めます
- `.tex` が無く，中身が LaTeX の `.txt` がある原稿には「`.tex` に名前を変えて開く」ボタンが出ます

### 3. 直す

エディタで直すと，入力が止まって 0.7 秒でファイルに保存され，PDF が組み直されます．

| 操作 | 内容 |
| --- | --- |
| PDF をダブルクリック | ソースの該当行へ移る（「PDF」だけの表示のときは語を選ぶだけで，エディタは開かない） |
| 境目の **→** | カーソルのある行を PDF 上で示す |
| 境目の **←** | PDF で選んだ文字（無ければ画面の中央）のソースへ移る |
| PDF の文字を選んで **✎ ここで直す** | その場で書き換えると，`.tex` の同じ文字が置き換わる（Overleaf には無い操作） |
| PDF の文字を選んで **💬 コメント** | その文字にコメントを付ける（次の節） |
| **リコンパイル**（Ctrl+Enter） | 最初から全部組み直す |
| **ログ** | エラーの一覧．行を押すとその箇所が開く |
| 画像をエディタか PDF に**落とす**（画像を**貼り付け**ても） | 画像のフォルダ（`img/`・`figures/` など．無ければ `img/`）に保存して，落とした段落の後ろに `figure` 環境と `\label` を入れる．PDF に落とすとその場所のソースに入る．WebP・GIF などは PNG にして保存する |
| Excel・スプレッドシート・Web の表を**貼り付ける**（CSV を落としても） | `booktabs` の `table` 環境にする（1行目が見出し，数の列は右寄せ，`_` や `%` はエスケープ）．「そのまま貼る」で元の文字に戻せる |
| エディタの下の **📄** | 最後のページにあと何行入るかの目安．押して上限のページ数を決めると，上限まで何行か・何行こえているかを出す（2段組も見る） |

図と表で使う `graphicx`・`booktabs` がプリアンブルに無いときは，足すかを聞きます．

`\cite` の番号や数式のように，PDF とソースで文字が違う部分は PDF の上では直せません．そのときはソースへ案内します．

**ローカルのエディタと同時に使えます．**

| どこで直すか | 何が起きるか |
| --- | --- |
| ブラウザのエディタ | すぐにローカルのファイルに書き込まれ，PDF が組み直される |
| ローカル（VS Code など） | 約 1 秒でブラウザのエディタの文面が置き換わり，PDF も組み直される |

両方で同じファイルを同時に直した場合は，どちらかを勝手に捨てず，
「外の内容を読み込む／こちらで上書き」を選ぶ表示が出ます．

### 4. コメントを付ける（Acrobat と同じ）

PDF の文字を選んで **💬 コメント** を押すと，Acrobat の注釈のようにコメントを付けられます．

| 種類 | PDF 上の表示 | 使いどころ |
| --- | --- | --- |
| コメント | 黄色のハイライト | 指摘・質問 |
| 削除の提案 | 赤の取り消し線 | この文字を消す |
| 置換の提案 | 赤の取り消し線と，置き換える文字 | この文字をこう直す |

- 左端の 💬 に一覧が出ます（数字は未解決の件数）．押すと PDF のその場所へ移り，**返信・✓ 解決・編集・削除**ができます．
  カードの `ファイル:行` を押すと，ソースのその行が開きます
- PDF 上のハイライトを押すと，一覧でそのコメントが開きます．エディタでも，コメントの付いた文字に印が付きます
- 名前は初回に聞かれ，ブラウザに覚えます（一覧の下の「変更」で変えられます）

**コメントは PDF の位置ではなく，ソースの文字に付きます．** 本文を直して行の折り返しが変わっても，コメントは同じ文字に付いていきます．
コメントした文字そのものを直すと，カードに「対象の文字がソースに無い（直された可能性がある）」と出ます．

**コメント付きでダウンロードする．** **ファイル → ダウンロード** か一覧の ⤓ から選べます．

| 形式 | 中身 |
| --- | --- |
| PDF（コメント付き） | 今の PDF にコメントを PDF の注釈として書き込んだもの．Acrobat・ブラウザ・プレビューなどでコメントとして見えます．返信と解決の状態も入ります |
| コメント一覧 (.md) | コメントを `ファイル:行` 付きで並べたもの．AI や人にそのまま渡せます |

**Acrobat などでもらったコメントを取り込む．** 一覧の ⤒ を押すか，一覧へコメント付きの PDF をドロップします．
ハイライト・下線・取り消し線・テキストの置換と挿入・付箋・返信・完了の状態を取り込み，ソースの場所に結びつけます．
同じ PDF を2回入れても，同じコメントは増えません．

**Claude Code に直してもらう．** 画面を開いたままで，Claude Code に「コメントを直して」と頼めます
（一覧の下の **🤖 AI への依頼文をコピー** で依頼文を作れます）．Claude Code は次のように直します．

```bash
overleaf-compiler comments data/学会2026/論文A/main.tex          # 未解決のコメントを ファイル:行 付きで出す
overleaf-compiler check    data/学会2026/論文A/main.tex          # 直したら組んで確かめる
overleaf-compiler comments data/学会2026/論文A/main.tex --resolve 3f9a2c -m "例を1つ足した"   # 解決済みにして返信を残す
```

解決や返信はすぐに画面の一覧へ出ます．コメントは原稿のフォルダの隠しファイル（`.<主文書の名前>.comments.json`）に残ります．
隠しファイルなので，Overleaf へ戻す zip には入りません．

### 5. 変更履歴を見る

左端の 🕘 に，いつ・どのファイルを・何行変えたかが並びます．押すと差分（緑が足した行，赤が消した行）が出ます．

- 版が残るのは，ブラウザで保存したとき・ローカルで直したとき・削除したとき・前の版に戻したときです
- 自動保存で版が増えすぎないよう，同じファイルを 60 秒以内に続けて直した分は1つの版にまとめます
- **削除したファイルも履歴に残る**ので，選んで「この版に戻す」で戻せます
- 履歴は原稿のフォルダの外（`~/.local/share/overleaf-compiler/history/`）に置くので，原稿のフォルダは汚れません

### 6. Overleaf へ戻す

**ファイル → ダウンロード → ソース (.zip)** で，Overleaf にそのまま入れられる zip が落ちます．

- **新しいプロジェクトとして上げる**：Overleaf の New Project → **Upload Project** に zip を入れる
- **今あるプロジェクトへ戻す**：変更したファイルを，Overleaf の **File → ファイルのアップロード** で上書きする
  （どのファイルを変えたかは 🕘 変更履歴で分かります）

zip には中間生成物・組んだ PDF・バックアップを入れません．
`latexmkrc` が無い和文の原稿には，Overleaf でも同じエンジンで組めるよう `latexmkrc` を足します．

同じ「ダウンロード」から，PDF と Word（.docx）・Markdown（.md）・HTML（.html）にも書き出せます．
Word などへの書き出しは pandoc に任せているので，数式や表，独自のクラスの体裁は崩れることがあります．

### 7. Claude Code・Codex と話しながら直す

右上の **✳ Claude**（または **Ctrl+Shift+L**）で，右に Claude Code のチャット欄が開きます．
VS Code の Claude Code 拡張と同じ並び・同じ操作です．Claude Code のログインをそのまま使います（API キーは要りません）．

| 場所 | できること |
| --- | --- |
| 入力欄 | **Enter** で送る・**Shift+Enter** で改行・**Esc** で返答を止める・**Shift+Tab** でモードを切り替える．画像は貼り付け・ドロップで添付 |
| 👁 ファイル名 | 開いているファイルとカーソルの行（選んでいれば選んだ行）を添えて送る．押すと添えない |
| **＋** | Upload from computer（添付）・Add context（`@` でファイルを指す）・Browse the web |
| **／** | Filter actions…．Clear conversation・Rewind・Export conversation・Switch model・Account & usage・Thinking・Effort・MCP servers・Hooks・Permissions・Status・Memory・Instructions・Slash commands など．入力の先頭に `/` を打っても開く |
| モデル | Default・Opus・Sonnet・Fable・Haiku など（Claude Code が使えるもの）と Effort（考える深さ） |
| モード | Manual（毎回確認）・Edit automatically・Plan・Auto |
| 🎤 | 音声入力（ブラウザの音声認識．Vivaldi では使えないことがあり，Chrome なら使えます） |
| 上のタブ | 会話ごとのタブ．Claude と Codex を混ぜて並べられ，**同時に動かせる**．裏で返答中のタブは緑の点，終わったタブはオレンジの点．× か中クリックで閉じる．原稿を開き直しても同じタブが戻る |
| 🕘 / ⊕ | 過去の会話を開く（Resume）／新しいタブで新しい会話 |
| 自分の発言を押す | その発言の前まで戻す（Rewind．コードと会話・会話だけ・コードだけ） |

返答が伸びると，一番下を自動で追いかけます（上へスクロールして読んでいる間は追いかけず，一番下へ戻すとまた追いかける．VS Code と同じ）．
Claude がファイルを直すと，自動で組み直され，エディタと PDF に出ます．Manual や Auto で確認が要るときは，
入力欄の代わりに「Allow Claude to Edit …?」が出るので，**1 Yes / 2 Yes, allow all edits during this session / 3 No** から選びます．

右上の **Codex** を押すと，同じ場所が Codex のチャット欄に切り替わります（もう一度押すと閉じる）．
VS Code の Codex 拡張と同じ項目で，Codex のログイン（`~/.codex`）をそのまま使います．Claude と Codex の会話は別々に残ります．

| 場所 | できること |
| --- | --- |
| 入力欄 | Ask Codex anything．`@` でファイルを指す．画像は貼り付け・ドロップで添付 |
| モデル | Select model（GPT-6-Astra など，Codex が使えるもの）と Reasoning（Light・Medium・High・Extra High など） |
| 承認 | How should Codex actions be approved?：Ask for approval・Approve for me・Full access・Custom (config.toml) |
| **／** | New chat・Resume・Fork chat・Compact・Model・Reasoning・Permissions・Status・MCP・Init・Rewind・Export conversation |
| 確認の画面 | **1 Yes / 2 Yes, and don't ask again this session / 3 No, and tell Codex what to do differently** |
| 自分の発言を押す | その発言の前まで，会話と Codex が変えたファイルを戻す（Revert） |

### 8. GitHub に上げる（⎇ Git）

ヘッダ右端の **⎇ Git** で Git の画面を開きます．上の切り替えで，**原稿（data）**（既定）と **overleaf-compiler 本体**を選びます．
一覧の各項目の **⋮ → GitHub に上げる…** からも始められます．

| 手順 | 内容 |
| --- | --- |
| フォルダ | 上げる data の中のフォルダを選ぶ（原稿1つでも，まとまりでもよい）．まだなら「Git で管理する」（`git init` と LaTeX 用の `.gitignore`．組んだ PDF を入れるかも選べる） |
| アカウント | 「GitHub にログイン」→ 出たコードをブラウザの github.com/login/device に入れて許可する（デバイスコード．パスワードはアプリに渡さない）．gh（GitHub CLI）が無ければ `~/.local/bin` に入れる．**一度連携すると，アプリを閉じても覚えている**．「連携をやめる」で外せる |
| リポジトリ | **もうあるリポジトリから選ぶ**か**新しく作る**かをタブで分けている．新しく作るときは非公開・公開を選ぶ（**既定は非公開**．公開は確かめてから作る）．公開のリポジトリを選ぶと警告する．各リポジトリの **⚙ 設定**で，名前・公開範囲・既定のブランチ・ブランチの作成と名前の変更と削除，リポジトリの削除（GitHub と同じく名前を打ち込んで確かめる）ができる |
| ブランチ | 送り先のブランチ（既定はリポジトリの既定のブランチ）．新しく作ることもできる |
| コミット | 変わったファイルを選び，メッセージを書く．**✨ コミットメッセージを自動で作成**で Claude Code・Codex（・Copilot の CLI があれば Copilot）に書かせられる |
| 取り消し | **↶ コミットを取り消す**：直前のコミットとそのときの git add を取り消し，変更を一覧に戻す（ファイルの中身には触らない．メッセージは欄に戻る）．GitHub に送ったコミットは取り消さない．取り込みなどがコンフリクトで止まったら **やめて元に戻す** が出る |
| push | 送り先（アカウント・リポジトリ・ブランチ）と送るコミットを確かめてから送る．強制 push はしない |
| 編集履歴 | 上の **編集履歴** に切り替えると，ブランチのコミットを push ごと（まだ送っていない・今回・前回・前々回…）に並べる．選んだ回やコミットで変わったところを，**その版の PDF の上に赤い線**で示す（書き換えた文字に下線，変わった行の左の余白に線，消した場所に印）．右の一覧で変更を順に追える．比べる相手は選べる．**作業中（まだコミットしていない今の原稿）**も比べられる．**⤓ 赤線つき PDF** で，赤線を焼き込み，最後に修正箇所の一覧（番号ごとの前と後の文）を付けた PDF を書き出す（先生に送る「前回からの修正箇所」）．「文字」に切り替えると差分を文字で見る |

- Overleaf の Git（git.overleaf.com）には上げません
- 編集履歴の PDF は，その版を `~/.cache/overleaf-compiler/gitpdf/` に取り出して組みます（原稿のフォルダは触らない．版ごとに1回だけ組み，次からはすぐ出る）．push の区切りは，このパソコンから push・取り込みした記録から読みます
- 公開リポジトリ（本体・公開の原稿のリポジトリ）では，コミットの前に個人名などが入っていないか調べます（「公開前に調べる言葉…」．設定は `~/.config/overleaf-compiler/` に置き，リポジトリには入らない）
- 原稿のフォルダに作るリポジトリは本体とは別のもので，本体に原稿が入ることはありません
- **overleaf-compiler 本体**も同じく GitHub にログインし，**自分の GitHub のリポジトリ**を送り先に選んで push します（元の公開リポジトリには送りません）．「最新版に更新」は元の公開リポジトリから取り込みます

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
| `overleaf-compiler check <原稿> [--json]` | 組んで，エラー・未定義の参照・はみ出しを `ファイル:行` で出す．失敗なら終了コード 1．画面が組んでいる原稿なら，直したファイルを画面が組み終えるのを待って，その結果を出す |
| `overleaf-compiler comments <原稿> [--all] [--json]` | PDF に付いた未解決のコメントを `ファイル:行` で出す（`--all` で解決済みも） |
| `overleaf-compiler comments <原稿> --resolve ID … [-m 返信]` | コメントを解決済みにする．`-m` で何をどう直したかを返信に残す．`--reply ID -m …` は返信だけ，`--reopen ID` は未解決に戻す |
| `overleaf-compiler export <原稿> [-o 出力.zip]` | Overleaf に入れる zip を作る |
| `overleaf-compiler build <原稿>` | 1回だけ組む（latexmk の出力をそのまま出す）．画面が組んでいる原稿では断る |
| `overleaf-compiler clean <原稿>` | 中間生成物を消す．画面が組んでいる原稿では断る |
| `overleaf-compiler app [--tab]` | アプリとして開く（サーバーを裏で動かす．アプリの一覧のアイコンが使う） |
| `overleaf-compiler stop` | アプリのウィンドウを閉じて，裏で動いているサーバーを止める |
| `overleaf-compiler settings` | 設定・状態の画面を開く |

`<原稿>` は主文書の `.tex` か，それを含むフォルダです．`--data <フォルダ>` で `data/` 以外の置き場を使えます．

`check` は，Claude Code などのツールに原稿を直させたあとの確認に使えます．

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>

## ファイル構成

<details>
  <summary>各ファイルの説明を開く</summary>

| ファイル | 説明 |
| --- | --- |
| `install.sh` | 端末でのセットアップ．TeX Live・追加のパッケージ・pandoc・コマンド・アプリの一覧への登録 |
| `はじめにこれを実行.sh` | セットアップをアプリの一覧に登録し，セットアップの画面を開く（導入後は本体のアイコンに置き換わる） |
| `setup.sh` / `アンインストール.sh` | セットアップの画面／削除の画面を開く（設定・状態の画面のボタンから呼ばれる．画面が使えなければ端末で同じことをする） |
| `share/` | アプリの一覧に登録する `.desktop` のひな形（右クリックの項目）とアイコン |
| `gui/` | セットアップ・削除・設定の画面（PySide6）．処理は `overleaf_compiler/install.py` と `launcher.py` にある |
| `overleaf_compiler/install.py` | 導入と削除（`install.sh` とセットアップの画面が同じものを呼ぶ．TeX Live・pandoc・gh） |
| `overleaf_compiler/launcher.py` | アプリとして開く（サーバーを裏で1つだけ動かし，ブラウザのアプリのウィンドウで開く） |
| `overleaf_compiler/claude.py` | 右のチャット欄．Claude Code（`claude` CLI）を原稿のフォルダで動かし，画面とやり取りする |
| `overleaf_compiler/codex.py` | 右のチャット欄の Codex 版．`codex app-server` を原稿のフォルダで動かし，claude.py と同じ形で画面とやり取りする |
| `overleaf_compiler.sh` | 起動スクリプト．`~/.local/bin/overleaf-compiler` はここへのリンクです |
| `pyproject.toml` | pip / pipx で入れる場合の定義（入れなくても動きます） |
| `overleaf_compiler/cli.py` | コマンド（serve / check / comments / import / export / build / clean） |
| `overleaf_compiler/server.py` | ローカルのサーバ（HTTP の受け口と起動）．127.0.0.1 でしか待ち受けません |
| `overleaf_compiler/app.py` | サーバの本体．開いている原稿（タブごとに複数）を持ち，画面の要求（読み書き・ファイル操作・検索・履歴・コメント）を処理する |
| `overleaf_compiler/pandoc.py` | Word・Markdown・HTML への書き出し（pandoc） |
| `overleaf_compiler/builder.py` | 組版．保存のたびの速い組版と，latexmk による全体の組版 |
| `overleaf_compiler/project.py` | 主文書の特定，エンジンの推定，フォルダの一覧，ファイルツリー |
| `overleaf_compiler/sync.py` | ファイルの読み書き，SyncTeX による PDF とソースの対応，PDF 上での書き換え |
| `overleaf_compiler/history.py` | 変更履歴 |
| `overleaf_compiler/comments.py` | PDF に付けるコメント（ソースの文字との対応，一覧の出力） |
| `overleaf_compiler/search.py` | 原稿の全ファイルの検索 |
| `overleaf_compiler/report.py` | ログから直すべき箇所を拾う（`check` で使う） |
| `overleaf_compiler/overleaf.py` | zip の展開と，Overleaf へ戻す zip の作成 |
| `overleaf_compiler/static/index.html` | 画面の骨組み（HTML） |
| `overleaf_compiler/static/css/` | 画面の見た目（土台・編集画面・コメント） |
| `overleaf_compiler/static/js/` | 画面の動き．役割ごとのモジュールに分けている（入口は `main.mjs`．コメントは `comments/`，チャット欄は `claude/`） |
| `overleaf_compiler/static/pdfjs/` | pdf.js（同梱） |
| `overleaf_compiler/static/pdflib/` | pdf-lib（同梱）．コメント付き PDF の書き出しに使う |
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
| PDF が更新されない | 「ログ」にエラーが出ていないか確認する．自動で組み直すのはブラウザで開いている原稿だけなので，その原稿をタブで開いておく．サーバのプログラムを更新したら起動し直す |
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
| pdf-lib | MIT | `overleaf_compiler/static/pdflib/` |
| CodeMirror 5 | MIT | `overleaf_compiler/static/codemirror/` |
| marked | MIT | `overleaf_compiler/static/marked/` |
| Ubuntu Mono | Ubuntu Font Licence 1.0 | `overleaf_compiler/static/fonts/` |
| Noto Sans | SIL Open Font License 1.1 | `overleaf_compiler/static/fonts/` |

<p align="right">(<a href="#readme-top">上に戻る</a>)</p>
