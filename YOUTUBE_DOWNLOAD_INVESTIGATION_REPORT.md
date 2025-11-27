# YouTube動画ダウンロード調査レポート

**日付**: 2025年11月27日  
**目的**: YouTube動画の403 Forbiddenエラーを解決し、Playwrightフォールバックを実装する  
**結果**: **失敗 - 現在の技術では実用的な解決が不可能**

---

## 1. 問題の概要

### 主要な問題
- RapidAPI (`yt-api.p.rapidapi.com`) を使用した動画ダウンロードで **403 Client Error: Forbidden** が発生
- ストリームURLへのアクセス時に、YouTube側が自動ダウンロードツールとして検出・ブロック
- 2024年後半～2025年にかけて、YouTubeが大幅にBot対策を強化

### 当初の目標
1. RapidAPIの再試行ロジック改善
2. PlaywrightによるブラウザエミュレーションでのURL取得
3. 取得したURLを使った確実なダウンロード

---

## 2. 試行した方法と結果

### 2.1 RapidAPI + requests (ヘッダー・Cookie強化)
**試行内容**:
- `User-Agent`, `Referer`, `Origin` ヘッダーの追加
- `cookies.txt` からのCookie読込み
- リトライロジックの実装

**結果**: ❌ 失敗
```
Status: 403
Response: Forbidden
```
- ヘッダーとCookieを追加しても403エラーが継続
- YouTubeはUser-Agent以外の要素（TLS fingerprint、HTTP/2など）も検証している

---

### 2.2 yt-dlp (公式ツール)
**試行内容**:
- 最新版yt-dlp (2025.10.14) を使用
- `--cookies cookies.txt` オプションでCookie渡し
- `--extractor-args "youtube:player_client=default,web_safari"` など各種オプション

**結果**: ❌ 失敗
```
ERROR: unable to download video data: HTTP Error 403: Forbidden
```
- Cookieを使用しても403エラー
- `player_client` の変更も効果なし
- YouTubeがyt-dlpの挙動パターンを検出している可能性

---

### 2.3 Playwright (ブラウザ自動化) - URLキャプチャ + requests
**試行内容**:
- Playwrightで実際のChromiumブラウザを起動
- `page.on("request")` でストリームURLをキャプチャ
- URLから `range` パラメータを削除
- キャプチャしたCookieとヘッダーを `requests` に渡してダウンロード

**結果**: ❌ 失敗
```
Downloaded: 31 bytes
Content: sabr.malformed_config
```
- URLのキャプチャは成功
- しかし `requests` でアクセスすると `sabr.malformed_config` エラー
- URLの署名・セッション情報が `requests` では無効化される

**原因分析**:
- YouTubeのURL署名はブラウザセッションと紐付き
- Playwright（Chromium）と requests（Python）では **TLS fingerprint** が異なる
- HTTP/2の使用有無、リクエスト順序なども検証されている

---

### 2.4 Playwright (レスポンスボディ直接取得)
**試行内容**:
- `page.on("response")` でレスポンスボディを直接取得
- `response.body()` でデータを取得

**結果**: ⚠️ 部分的成功（短い動画のみ）
```
Captured 514,944 bytes (0.49 MB) - 短い動画（Me at the zoo）
Captured 907,480 bytes (0.87 MB) - ターゲット動画の一部
```

**問題点**:
- 取得したデータは YouTubeの独自フォーマット **UMP (Unified Media Payload)**
- 標準のMP4ではなく、再生不可
- ストリーミング再生のため、最初のチャンクしか取得できない
- 長時間動画では全データの取得が不可能

---

### 2.5 Playwright (全チャンク収集)
**試行内容**:
- 動画をシーク操作して全チャンクをロード
- すべてのレスポンスを収集して結合

**結果**: ❌ 失敗
```
Collected 1 video chunks
Video assembled: 999,092 bytes (0.95 MB)
File: 再生不可能（UMPフォーマット）
```

**問題点**:
- シークしても新しいチャンクがリクエストされない
- YouTubeはオンデマンドで必要な部分のみロード
- 取得したデータはUMPフォーマットで変換不可

---

### 2.6 Invidious API (プライバシー重視のYouTubeプロキシ)
**試行内容**:
- 公開Invidiousインスタンス (`inv.nadeko.net`, `yewtu.be` など) のAPI使用
- `/api/v1/videos/{video_id}` エンドポイントでメタデータ取得

**結果**: ❌ 失敗
```
https://inv.nadeko.net: 403 Forbidden
https://yewtu.be: 403 Forbidden  
https://invidious.nerdvpn.de: 401 Unauthorized
```
- すべての公開インスタンスがYouTubeにブロックされている
- 2024年後半からInvidiousへの規制が強化

---

## 3. 失敗の根本原因

### 3.1 YouTubeの防御メカニズム (2025年時点)

#### A. Bot検出の高度化
- **TLS Fingerprinting**: クライアントのTLS接続パターンを解析
- **HTTP/2 要件**: HTTP/1.1のrequestsライブラリでは弾かれる
- **リクエストパターン分析**: アクセス順序、タイミング、ヘッダーの組み合わせ
- **User-Agent以外の検証**: Sec-Ch-UA, Sec-Fetch-\* などのヘッダー群

#### B. 独自プロトコル・フォーマット
- **UMP (Unified Media Payload)**: 独自のコンテナフォーマット
- **動的URL署名**: セッション、IP、時刻に基づく署名
- **短命なURL**: 数分で無効化されるストリームURL
- **PO Token (Proof of Origin)**: JavaScriptで生成される証明トークン

#### C. プロキシサービスへの規制
- Invidiousインスタンスの組織的ブロック
- レート制限とIP禁止
- APIエンドポイントの頻繁な変更

---

### 3.2 技術的な壁

| 方法 | 取得可能な要素 | 取得不可能な要素 |
|------|----------------|------------------|
| requests | ヘッダー、Cookie | TLS fingerprint, HTTP/2 |
| yt-dlp | 最新の回避ロジック | YouTubeの検出回避（2025年時点） |
| Playwright | 完全なブラウザコンテキスト | UMPデコード、全チャンク収集 |
| Invidious | プライバシー保護 | YouTubeのブロック回避 |

---

## 4. 現在利用可能な選択肢

### A. 推奨: 有料APIサービスへの移行
RapidAPIで以下のような**より信頼性の高いサービス**を契約：
- **YouTube Media Downloader** (rapidapi.com)
- **YouTube Video and Shorts Downloader** (rapidapi.com)
- **4K Video Downloader+ API** (有料、企業向け)

**利点**: YouTube側との交渉・契約により合法的にアクセス可能  
**欠点**: 月額コストが高い（$50～$500/月）

---

### B. 妥協案: 音声のみ・字幕のみモード
動画ファイルのダウンロードを諦め、以下のみを使用：
- **字幕/トランスクリプト**: `youtube_transcript_api` (動作中)
- **音声抽出**: RapidAPIの音声専用エンドポイント（存在すれば）
- **静止画**: サムネイル画像 + 音声 + 字幕で切り抜き生成

**実装**:
```python
# 字幕は既に取得できている
transcript = youtube_transcript_api.get_transcript(video_id)

# 静止画（サムネイル）
thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

# これらを組み合わせて「音声+字幕テロップ+静止画」の動画を生成
```

---

### C. 手動運用
重要な動画のみ：
1. ブラウザ拡張機能（4K Video Downloader+、Video DownloadHelper）で手動ダウンロード
2. Google Driveにアップロード
3. GitHub ActionsからDrive経由で取得

**利点**: 確実  
**欠点**: 完全自動化不可、手間が大きい

---

### D. プロジェクトの方向転換
動画切り抜きではなく、以下に特化：
- **要約生成**: 字幕から重要部分を抽出してテキスト要約
- **Tweetbot**: 字幕からバズる発言を抽出してツイート
- **Podcast**: 音声のみの切り抜き配信

---

## 5. 教訓とベストプラクティス

### 学んだこと
1. **YouTubeのBot対策は2024年後半から劇的に強化**
   - 従来の方法（yt-dlp、Invidious）が軒並み無効化
   
2. **ブラウザ自動化でもURL取得後のダウンロードは困難**
   - URLの署名・セッション検証が厳格
   
3. **独自フォーマット（UMP）の導入**
   - 標準ツールでのデコードが不可能

### 今後のプロジェクトへの提言
- 外部サービス（YouTube）への依存を最小化
- APIが403を返す場合の代替プラン（フォールバック）を事前設計
- 有料APIサービスの予算を確保

---

## 6. 技術的詳細 (参考資料)

### 試行したコマンド・コード例

#### yt-dlp (失敗例)
```bash
yt-dlp --cookies cookies.txt \
  --extractor-args "youtube:player_client=default,web_safari" \
  "https://www.youtube.com/watch?v=NSsQit9zTiE"
# 結果: ERROR: HTTP Error 403: Forbidden
```

#### Playwright (部分的成功例)
```python
# response.body() で UMPデータを取得
body = response.body()  # 907,480 bytes
# しかし Content-Type: application/vnd.yt-ump
# → MP4ではなく再生不可
```

#### Invidious API (失敗例)
```python
response = requests.get("https://inv.nadeko.net/api/v1/videos/jNQXAC9IVRw")
# 結果: 403 Forbidden
```

---

## 7. 結論

### 最終判断
**YouTube動画の自動ダウンロードは、2025年11月時点では技術的に実用不可能**

理由：
1. YouTubeのBot対策（TLS fingerprinting、PO Token、UMP）が極めて高度
2. yt-dlpやInvidiousなどの既存ツールも無効化
3. Playwrightでも取得データがUMPフォーマットで変換不可
4. 有料APIサービス以外に確実な方法が存在しない

### 推奨する次のステップ
1. **有料APIサービスへの移行** （予算確保が必要）
2. **音声+字幕のみモード** （動画なしでも価値提供可能か検討）
3. **プロジェクトの一時休止** （YouTubeの仕様変更を待つ）

---

## 8. 参考リンク

- yt-dlp GitHub Issues: https://github.com/yt-dlp/yt-dlp/issues
  - PO Token問題: #10927
  - 403 Forbidden: 継続的な報告あり
  
- Invidious公式: https://invidious.io/
  - 公開インスタンスリスト（多くがダウン中）
  
- RapidAPI YouTube APIs:
  - https://rapidapi.com/hub (代替サービス検索)

---

**作成者**: AI Assistant  
**最終更新**: 2025-11-27 16:59

---

## 付録: 試行履歴

| 日時 | 方法 | 結果 | ファイルサイズ | メモ |
|------|------|------|---------------|------|
| 11/27 14:00 | RapidAPI + headers | 失敗 | 0 bytes | 403 Forbidden |
| 11/27 14:30 | yt-dlp + cookies | 失敗 | 0 bytes | 403 Forbidden |
| 11/27 15:00 | Playwright + requests | 失敗 | 31 bytes | sabr.malformed_config |
| 11/27 15:30 | Playwright response.body() | 部分成功 | 0.87 MB | UMPフォーマット、再生不可 |
| 11/27 16:00 | Playwright chunk collection | 失敗 | 0.95 MB | 1チャンクのみ、UMP |
| 11/27 16:30 | Invidious API | 失敗 | 0 bytes | 全インスタンス403/401 |

**試行総数**: 20回以上  
**成功率**: 0%  
**累計開発時間**: 約6時間
