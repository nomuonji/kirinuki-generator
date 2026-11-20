# RapidAPI字幕取得キーの管理（2026-11-21）

対象: `RAPIDAPI_KEY`（RapidAPIの字幕ダウンロード経路用の既存Secret）。

## 正本・利用場所

- **Secretの保存先:** このリポジトリ `nomuonji/kirinuki-generator` の GitHub **Settings → Secrets and variables → Actions → Repository secrets** にある `RAPIDAPI_KEY`。
- **通常の利用:** `.github/workflows/main.yml`（スケジュール / 手動）および `.github/workflows/manual-run.yml`（手動）は、`secrets.RAPIDAPI_KEY` を実行ステップの環境変数として `transcribe_rapidapi.py` に渡す。
- **字幕診断:** `.github/workflows/probe-existing-youtube-captions.yml` は **`workflow_dispatch` での手動起動専用**。`video_id` は11文字のYouTube ID以外受け付けない。PR・push・cronをトリガーにしない。同時多重実行を抑える`concurrency`を設定。APIリクエストは最大2つの既存字幕プロバイダを順に照会する（先にYouTubeの直接取得を試す）。
- **成功の実測:** 2026-11-21の診断（[Actions run 44802685690](https://github.com/nomuonji/kirinuki-generator/actions/runs/44802685690)）ではSecretが使用可能で、動画 `4YSXNotY8QU` の候補字幕1,533件を第一RapidAPIフォールバックから取得した。**Secretの値自体・実際のプラン・月間残枠・請求状況は検証していない**。字幕の真正性は別の問題。

## 秘密情報の扱い

1. APIキーは**コード・Git履歴・PRコメント・標準出力・Actions artifact・フロントエンド・JSON教材**に書かない。認証Cookieと一緒に保存・転送しない。
2. `transcribe_rapidapi.py` は`RAPIDAPI_KEY`を環境から読み取り、HTTPSリクエストの `x-rapidapi-key` ヘッダーにだけ入れる。キーをURLクエリ、CLI引数、トレースログへ渡さない。
3. **Secretを使うWorkflowでPRの未レビューコードを実行しない。** フォーク元PRには通常GitHub Secretsが渡らないが、同一リポジトリのPRではSecretsを利用できる場合がある。診断ジョブは2026-11-21に手動起動専用へ変更した。一般の開発PRではAPIキーを一切注入しない。
4. **The Annotated Worldへ同じ値を複製しない。** GitHub Repository Secretは他リポジトリから通常読めない。新規教材の候補字幕診断はこのリポジトリの手動Actionsを使い、出力は本文・認証情報を含まない件数・時刻・ハッシュのみ。記事制作に使う原本は、元YouTube字幕との照合と権利条件の確認後、非公開作業領域へ保存する。本文を公開Gitへ持ち込むのは許可の範囲だけ。
5. Secretの値を見せる必要はない。漏洩が疑われた場合はRapidAPI側でキーをローテートし、GitHubのRepository Secretも同時更新して、使用履歴を確認する。GitHubの古いコミットやログに漏洩した値がある場合、更新だけで履歴が消えるわけではない。

## 料金・クォータの確認

RapidAPIのAPIごとにプランと超過料金は異なる。**今の契約プラン・無料枠・超過課金の有無・残り回数はGitHub Actionsの成功ログからは分からない。** そのため「無料で無制限」とは扱わない。

- [RapidAPI Developer Dashboard](https://rapidapi.com/developer) の **Subscriptions / Usage / Pricing** で、字幕API 2経路それぞれの契約・上限・超過課金条件・請求履歴を確認する。
- RapidAPIはレスポンスに残枠を示すヘッダーを返す場合がある。将来利用量を自動計測するなら**キーや字幕本文はログに書かず、使用枠・429/403・リセット時刻だけ**を集計する。
- クォータの実測・予算上限を確認するまでは、記事候補を無制限に試す自動ジョブを追加せず、**明示的な手動検証だけ**にする。既存の定期切り抜きパイプラインが同じキーを使っているため、その消費も含めて判断する。
- 公式ドキュメント: https://docs.rapidapi.com/docs/subscriptions-and-usage 、https://docs.rapidapi.com/docs/response-headers 。超過費用が発生するプランもある。

## 手動の診断手順（キーのコピー不要）

1. GitHub `nomuonji/kirinuki-generator` → **Actions** → **Probe existing YouTube captions for an exact video ID (no ASR)** → **Run workflow**。
2. `video_id` に11文字のIDを指定。キー自体は入力不要。手動起動後、実行結果で `EXISTING_RAPIDAPI_CREDENTIAL=present`、`SOURCE_PROVIDER`、`CUE_COUNT`、`COVERAGE_PLAUSIBLE` を確認する。
3. `PROVEN_YOUTUBE_ORIGINAL_TRACK=false` は、RapidAPIの候補字幕がYouTube原本だと独立確認できていないことを表す。記事本文へ採用する前に照合する。
4. `EXISTING_CAPTION_PIPELINE_RESULT=NO_DATA` なら成功と扱わない。APIキー未設定・契約/クォータ・元動画IP制限・字幕が存在しない場合を区別する。

**メディアの所有や転載許可と、字幕取得APIの認証・課金管理はそれぞれ独立したゲート。**
