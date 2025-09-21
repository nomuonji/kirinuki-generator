# clipcut-monorepo

Transcript → **Gemini API** → edit points (JSON) → **FFmpeg** cut → **Remotion** vertical render.

## アプローチの哲学 (Philosophy of the Approach)

このプロジェクトは、高品質な切り抜き動画を半自動で生成するために、以下の2つのアプローチを組み合わせています。

1.  **Geminiによる意味理解と提案:**
    AI（Google Gemini）に対して、単に「面白い部分」を尋ねるのではなく、「話のまとまり」「会話の自然な区切り」「話者の交代」といった、人間が編集する際に考慮する複数の要素を詳細な指示（プロンプト）として与えます。これにより、AIは文脈を深く理解し、創造的で質の高いクリップ候補を提案します。

2.  **スクリプトによる堅牢な仕上げ処理:**
    AIの提案は時に完璧ではありません。そのため、スクリプト側ではAIの提案を尊重しつつ、最終的な仕上げ処理を行います。特にクリップの終了点は、「AIが選んだ最後のセリフの、次のセリフが始まる直前」という明確なルールでカットすることにより、自然な「間」を確保し、品質を安定させます。AIの創造性とプログラムの正確性を組み合わせることが、本アプローチの鍵です。

---

## ワークフロー (Workflow)

このプロジェクトには、大きく分けて2つのワークフローがあります。

### A) 完全自動ワークフロー (推奨)

**コマンド一発**で、文字起こしから、上下にテキストの入った最終的な縦長ショート動画の生成までを全自動で行います。

1.  **セットアップと文字起こし:**
    - 下記の「クイックスタート」の「1. セットアップ」と「2. 文字起こしの実行」を完了させてください。

2.  **生成とレンダリングを一括実行:**
    - `generate_clips.py` に `--render` オプションを付けて実行します。

    ```powershell
    # Windows (PowerShell) の例
    python -m apps.cli.generate_clips `
      --transcript tmp/transcript.json `
      --video tmp/video.mp4 `
      --out out_clips `
      --render
    ```
    実行が完了すると、プロジェクトルートに `rendered` フォルダが作成され、その中に完成した動画が保存されます。

### B) ステップ実行ワークフロー

各工程を個別に実行します。テキストの内容を手動で修正したい場合などに使用します。

1.  **切り抜き動画の生成:**
    - `generate_clips.py` を（`--render`なしで）実行し、`out_clips` フォルダに動画（.mp4）とフックテキスト（_hooks.txt）を生成します。

2.  **(オプション) テキストの編集:**
    - `out_clips` 内の `_hooks.txt` ファイルを開き、Remotionで動画に合成したいテキストを手動で編集できます。

3.  **レンダリングの実行 (2ステップ):**
    - 準備スクリプトとレンダリングスクリプトを順番に実行します。

    **ステップ1: 準備**
    プロジェクトのルートディレクトリで、以下のコマンドを実行して、レンダリングに必要な動画の最適化と情報ファイルを生成します。
    ```powershell
    # 最適化を実行してから準備する場合（推奨）
    python -m apps.cli.render_clips --input-dir apps/remotion/public/out_clips

    # 最適化をスキップして準備する場合
    python -m apps.cli.render_clips --input-dir apps/remotion/public/out_clips --skip-optimization
    ```

    **ステップ2: 一括レンダリング**
    準備が完了したら、`apps/remotion` ディレクトリに移動し、一括レンダリングスクリプトを実行します。
    ```powershell
    cd apps/remotion
    .\render_all.ps1
    ```
    実行が完了すると、`rendered` フォルダに完成した動画が保存されます。


---

## クイックスタート (個別機能)

### 1. セットアップ

1. Python 3.10+ と FFmpeg がインストールされていることを確認します (`ffmpeg` コマンドが利用可能な状態).
2. 必要なPythonライブラリをインストールします。
   ```bash
   pip install -r requirements.txt
   ```
3. `.env.example` をコピーして `.env` ファイルを作成し、`GEMINI_API_KEY` を設定します。
   ```bash
   cp .env.example .env
   ```

### 2. 文字起こしの実行

(省略... 上記ワークフローのセクションを参照)

### 3. 切り抜き動画の生成 (Gemini + FFmpeg)

(省略... 上記ワークフローのセクションを参照)

### 4. 字幕の生成と焼き付け (オプション)

`generate_clips.py` または `render_clips.py` のコマンドに、字幕を生成するためのオプションを追加できます。

- **ソフトサブ**（動画ファイルとは別に`.srt`または`.ass`の字幕ファイルを生成）:
  - コマンドに `--subs` を追加します。
  ```powershell
  # Windows (PowerShell) の例
  python -m apps.cli.generate_clips --transcript tmp/transcript.json --video tmp/video.mp4 --out out_clips --subs
  ```

- **ハードサブ**（動画に字幕を直接焼き付ける）:
  - コマンドに `--burn` を追加します。焼き付けには`.ass`形式の字幕が推奨されます (`--subs-format ass`)。
  ```powershell
  # Windows (PowerShell) の例
  python -m apps.cli.generate_clips --transcript tmp/transcript.json --video tmp/video.mp4 --out out_clips --burn --subs-format ass
  ```

### 5. Remotion (縦型動画の高度なレンダリング)

(省略... 上記ワークフローのセクションを参照)
