# Kirinuki Generator

AIが動画の面白い部分を自動で分析・カットし、縦型のショート動画を生成するツールです。

---

## 全自動実行 (推奨)

YouTube動画IDを指定するだけで、ダウンロードから最終的なレンダリングまで、すべてを自動で行います。

```bash
# <YouTubeのビデオID> を置き換えて実行
python run_all.py <YouTubeのビデオID>
```

- AIの分析精度を上げるため、事前に `configs/video_concept.md` に動画のコンセプトを記述しておくことを強く推奨します。
- 処理が完了すると、`rendered` に完成した動画が出力されます。
- 途中で作られた作業ファイルは、次回の実行時に自動でクリーンアップされます。

---

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

## 手動実行 (ステップごと)

各工程を個別に実行したい場合は、以下の手順に従ってください。

### Step 1: 準備 (動画のダウンロードと文字起こし)

はじめに、切り抜き元になる動画ファイルと、その文字起こしデータを準備します。

-   **YouTube動画を使う場合 (推奨):**

    1.  **動画のダウンロード:**
        -   `download_video.py` を使って、YouTube動画をダウンロードします。
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
    -   出力先 (`--out`) には、Remotionとの連携のため `apps/remotion/public/out_clips` を指定することを推奨します。
    ```powershell
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out apps/remotion/public/out_clips
    ```

-   **💡 AIの精度を上げるには (動画コンセプトの指定):**
    -   `configs/video_concept.md` に動画のコンセプトやテーマを記述します。
    -   実行時に `--concept-file` でそのファイルを指定すると、AIが文脈をより深く理解し、生成精度が向上します。
    ```powershell
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out apps/remotion/public/out_clips `
      --concept-file configs/video_concept.md
    ```

### Step 3: レンダリング (縦型動画の作成)

生成されたクリップを、上下にテキストが入った最終的な縦型動画に仕上げます。このプロセスは2つのステップで構成されます。

**1. レンダリングの準備**

-   まず、AIが生成したクリップをRemotionで扱えるように、動画の最適化と設定ファイルの生成を行います。
-   `generate_clips.py`を実行する際に`--render`オプションを付けると、この準備ステップまでが自動的に実行されます。

    ```powershell
    # クリップ生成からレンダリング準備までを一括で実行
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out apps/remotion/public/out_clips `
      --render 
    ```
-   もしクリップ生成と準備を分けて行う場合は、以下のコマンドを実行します。
    ```powershell
    python -m apps.cli.render_clips --input-dir apps/remotion/public/out_clips
    ```

**2. 最終レンダリングの実行**

-   準備が完了したら、Remotionのスクリプトを実行して、最終的な `.mp4` ファイルを生成します。
-   以下のコマンドを**プロジェクトのルートディレクトリで**実行してください。

    ```powershell
    cd apps/remotion
    ./render_all.ps1
    ```
-   完了後、`rendered` フォルダに完成した動画が保存されます。

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