# Kirinuki Generator

AIが動画の面白い部分を自動で分析・カットし、縦型のショート動画を生成するツールです。

## セットアップ (Setup)

1.  **必要ツールの準備**
    -   Python (3.10+)
    -   FFmpeg (`ffmpeg`コマンドが実行できるようにパスを通してください)

2.  **ライブラリのインストール**
    -   以下のコマンドを実行して、必要なライブラリをすべてインストールします。
    ```bash
    pip install -r requirements.txt
    ```

3.  **環境変数の設定**
    -   `.env.example` をコピーして `.env` ファイルを作成します。
        ```bash
        cp .env.example .env
        ```
    -   `.env` ファイルを開き、以下のAPIキーを設定します。
        -   `GEMINI_API_KEY`: AIによる分析に必須です。
        -   `RAPIDAPI_KEY`: YouTube動画の文字起こし機能を使う場合のみ必要です。

---

## 3ステップで動画を生成

### Step 1: 準備 (動画のダウンロードと文字起こし)

はじめに、切り抜き元になる動画ファイルと、その文字起こしデータを準備します。

-   **YouTube動画を使う場合 (推奨):**

    1.  **動画のダウンロード:**
        -   新しく追加した `download_video.py` を使って、YouTube動画をダウンロードします。
        -   `<YouTubeのビデオID>` の部分を対象の動画のものに置き換えて実行してください。
        ```bash
        # 動画を tmp/video.mp4 としてダウンロード
        python download_video.py <YouTubeのビデオID>
        ```

    2.  **文字起こし:**
        -   次に、ダウンロードした動画の文字起こしを `transcribe_rapidapi.py` で行います。
        ```bash
        python transcribe_rapidapi.py <YouTubeのビデオID>
        ```

-   **ローカルの動画ファイルを使う場合:**

    1.  **ファイルの配置:**
        -   お手持ちの動画ファイル (例: `my_video.mp4`) を `tmp` フォルダにコピーします。
    2.  **文字起こし:**
        -   `transcribe.py` を実行して文字起こしを行います。
        ```bash
        python transcribe.py
        ```

完了後、`tmp`フォルダに`video.mp4`（動画ファイル）と`transcript.json`（文字起こしデータ）が準備できている状態になります。

### Step 2: クリップ生成 (AIによる分析とカット)

文字起こしデータを元に、AIが動画を分析し、クリップを生成します。

-   **コマンド:**
    ```powershell
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out out_clips
    ```

-   **💡 AIの精度を上げるには (動画コンセプトの指定):**
    -   `configs/video_concept.md` に動画のコンセプトやテーマを記述します。
    -   実行時に `--concept-file` でそのファイルを指定すると、AIが文脈をより深く理解し、生成精度が向上します。
    ```powershell
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out out_clips `
      --concept-file configs/video_concept.md
    ```

### Step 3: レンダリング (縦型動画の作成)

生成されたクリップを、上下にテキストが入った最終的な縦型動画に仕上げます。

-   **全自動レンダリング (推奨):**
    -   `generate_clips.py` に `--render` オプションを追加すると、クリップ生成からレンダリングまで一括で行います。
    ```powershell
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out out_clips `
      --render
    ```
    -   完了後、ルートディレクトリに `rendered` フォルダが作成されます。

---

## オプション機能: 字幕の生成

`generate_clips.py` 実行時に以下のオプションを追加すると、字幕を生成できます。

-   `--subs`: 字幕ファイル (`.srt`または`.ass`) を別途生成します (ソフトサブ)。
-   `--burn`: 動画に字幕を直接焼き付けます (ハードサブ)。

**例 (ハードサブ):**
```powershell
python -m apps.cli.generate_clips `
  --transcript tmp/transcript.json `
  --video tmp/video.mp4 `
  --out out_clips `
  --burn --subs-format ass
```