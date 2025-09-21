# Kirinuki Generator

AIが動画の面白い部分を自動で分析・カットし、縦型のショート動画を生成するツールです。

## セットアップ (Setup)

1.  **必要ツールの準備**
    -   Python (3.10+)
    -   FFmpeg (`ffmpeg`コマンドが実行できるようにパスを通してください)

2.  **ライブラリのインストール**
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

## 基本的な使い方 (Usage)

### Step 1: 文字起こし (Transcription)

まず、動画の文字起こしデータ (`tmp/transcript.json`) を作成します。

-   **ローカル動画の場合:**
    1.  `tmp` フォルダに動画ファイル (例: `video.mp4`) を置きます。
    2.  以下のコマンドを実行します。
        ```bash
        python transcribe.py
        ```

-   **YouTube動画の場合:**
    ```bash
    # <YouTubeのビデオID> を置き換えて実行
    python transcribe_rapidapi.py <YouTubeのビデオID>
    ```

### Step 2: クリップ生成 (Generate Clips)

文字起こしデータを元に、AIが動画を分析し、クリップを生成します。

-   **基本コマンド:**
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

### Step 3: レンダリング (Rendering)

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

-   **手動レンダリング:**
    1.  レンダリングの準備をします。
        ```powershell
        python -m apps.cli.render_clips --input-dir out_clips
        ```
    2.  Remotionで一括レンダリングを実行します。
        ```powershell
        cd apps/remotion
        ./render_all.ps1
        ```

---

## オプション機能 (Options)

### 字幕の生成

`generate_clips.py` 実行時に以下のオプションを追加します。

-   `--subs`: 字幕ファイル (`.srt`または`.ass`) を別途生成します (ソフトサブ)。
-   `--burn`: 動画に字幕を直接焼き付けます (ハードサブ)。
    -   `.ass`形式 (`--subs-format ass`) の利用を推奨します。

**例 (ハードサブ):**
```powershell
python -m apps.cli.generate_clips `
  --transcript tmp/transcript.json `
  --video tmp/video.mp4 `
  --out out_clips `
  --burn --subs-format ass
```
