# 日本クラウドからの取得試験（本番未接続）

2026-10-20確認: primary Actions run 39372029916は在庫0、候補0、regionBlocked=42。
同日SaveTube run 39352693427は19秒の世界公開動画で映像・音声取得成功。
PR #32にはprimary対象でallowed=[JP]を実測した記録がある。
世界公開のテスト成功と、今日好きの対象動画取得成功を混同しない。

本人方針: 手元PCを使わずクラウドで完結する。
まずCloud Run Jobs東京で実際の対象動画を30秒だけ取得し、音声・映像・25〜45秒の長さ・全サンプルのデコードを検証する。
日本リージョンでもYouTubeのクラウドIP拒否はあり得る。成功未確認のまま候補除外や本番取得経路を変更しない。
サンプルは一時領域から消し、投稿・Drive転送・cookies保存は行わない。

## 実行に必要なもの

課金が有効なGCP project、ログイン済みgcloud、Cloud Build / Artifact Registry / Cloud Runの作成・実行権限。
既存YouTube/Drive OAuthはGCPインフラの作成権限を代替しない。
このPRだけではデプロイも定期実行も始まらない。
実行・イメージ保管・ビルドは課金対象になり得る。無料枠内を保証しない。

Google Cloud Shellでリポジトリを開き、project IDと対象video IDを設定して実行する。
VIDEO_IDには実際のprimary対象（30秒以上）を指定する。世界公開テスト動画だけで合格にしない。

```bash
PROJECT_ID='your-gcp-project'
VIDEO_ID='target_id11'
REGION='asia-northeast1'
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/kirinuki-probe/download:trial"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT_ID"
gcloud artifacts repositories create kirinuki-probe --repository-format=docker --location "$REGION" --project "$PROJECT_ID"
gcloud builds submit cloud/japan-download --tag "$IMAGE" --project "$PROJECT_ID"
gcloud run jobs deploy kirinuki-jp-download-probe --image "$IMAGE" --region "$REGION" --project "$PROJECT_ID" --cpu 1 --memory 1Gi --tasks 1 --parallelism 1 --max-retries 0 --task-timeout 600s --args "$VIDEO_ID"
gcloud run jobs execute kirinuki-jp-download-probe --region "$REGION" --project "$PROJECT_ID" --wait
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="kirinuki-jp-download-probe"' --project "$PROJECT_ID" --limit 20 --format json
```

既存のArtifact Registry repositoryがあればcreateを省く。自動再試行・cronは設定しない。
Docker buildにはネットワークが必要。依存バージョンはビルド時点の最新で、結果JSONにyt-dlp版を記録する。
認証要求の場合はその失敗を記録し、cookiesの投入や別経路への切替を自動で行わない。

## 合格後の本番接続

1. 同じ対象の全編取得と、Google側から見える実際の配信可否を確認する。
2. 日本側から原本を非公開ストレージへ保存し、短期URLで既存Actionsへ渡す。
3. APIのregionRestriction判定を、その原本取得を行う実環境に対応付ける。
4. 旧geo_restricted記録は全消去せず、取得経路変更に対して限定的に再試行する。
5. 実クリップがDriveへ到達してから復旧と報告する。

## 片付け

```bash
gcloud run jobs delete kirinuki-jp-download-probe --region "$REGION" --project "$PROJECT_ID"
gcloud artifacts repositories delete kirinuki-probe --location "$REGION" --project "$PROJECT_ID"
```

参考（公式）:
- https://docs.cloud.google.com/run/docs/create-jobs
- https://cloud.google.com/run/pricing
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
