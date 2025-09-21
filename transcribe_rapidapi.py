
import os
import requests
import json
import argparse
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# RapidAPIキーを環境変数から取得
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")

def get_transcript_from_api1(video_id: str, lang: str = "ja"):
    """
    API 1 (youtube-captions-transcript-subtitles-video-combiner) を使って文字起こしを取得する
    """
    url = f"https://youtube-captions-transcript-subtitles-video-combiner.p.rapidapi.com/download-json/{video_id}"
    querystring = {"language": lang}
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "youtube-captions-transcript-subtitles-video-combiner.p.rapidapi.com"
    }
    try:
        print("API 1 (youtube-captions-transcript-subtitles-video-combiner) を試しています...")
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()  # HTTPエラーがあれば例外を発生させる
        data = response.json()
        if data:
            print("API 1 から文字起こしを取得しました。")
            return data
    except requests.exceptions.RequestException as e:
        print(f"API 1でエラーが発生しました: {e}")
    except json.JSONDecodeError:
        print("API 1からのレスポンスがJSON形式ではありません。")
    return None

def get_transcript_from_api2(video_id: str):
    """
    API 2 (youtube-transcript3) を使って文字起こしを取得する
    """
    url = "https://youtube-transcript3.p.rapidapi.com/api/transcript"
    querystring = {"videoId": video_id}
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "youtube-transcript3.p.rapidapi.com"
    }
    try:
        print("API 2 (youtube-transcript3) を試しています...")
        response = requests.get(url, headers=headers, params=querystring)
        response.raise_for_status()
        data = response.json()
        # APIのレスポンスが {'transcript': [...]} のような形式の場合、中のリストを返す
        if isinstance(data, dict) and 'transcript' in data:
            print("API 2 (youtube-transcript3) から整形済みの文字起こしを取得しました。")
            return data['transcript']
        if data:
            print("API 2 (youtube-transcript3) から文字起こしを取得しました。")
            return data
    except requests.exceptions.RequestException as e:
        print(f"API 2でエラーが発生しました: {e}")
    except json.JSONDecodeError:
        print("API 2からのレスポンスがJSON形式ではありません。")
    return None

def main():
    parser = argparse.ArgumentParser(description="YouTube動画の文字起こしを取得します。")
    parser.add_argument("video_id", help="YouTubeのビデオID")
    parser.add_argument("--lang", default="ja", help="文字起こしの言語 (API 1でのみ使用)")
    args = parser.parse_args()

    if not RAPIDAPI_KEY:
        print("エラー: 環境変数 `RAPIDAPI_KEY` が設定されていません。")
        print(".envファイルに `RAPIDAPI_KEY=YOUR_API_KEY` を追加してください。")
        return

    # API 1 を試す
    transcript = get_transcript_from_api1(args.video_id, args.lang)

    # API 1 が失敗したら API 2 を試す
    if not transcript:
        print("API 1 に失敗したため、API 2 を試します。")
        transcript = get_transcript_from_api2(args.video_id)

    if transcript:
        # 結果をファイルに保存
        output_path = "tmp/transcript.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
        print(f"文字起こしを {output_path} に保存しました。")
    else:
        print("両方のAPIで文字起こしの取得に失敗しました。")

if __name__ == "__main__":
    main()
