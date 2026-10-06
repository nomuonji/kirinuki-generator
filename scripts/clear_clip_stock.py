import json
import os

from packages.shared.gdrive import get_drive_service, list_clip_files, delete_file


def main():
    folder_id = os.environ.get("GDRIVE_PARENT_FOLDER_ID")
    if not folder_id:
        raise SystemExit("GDRIVE_PARENT_FOLDER_ID is required")

    service = get_drive_service()
    clips = list_clip_files(service, folder_id)
    print(json.dumps({
        "folderId": folder_id,
        "clipCountBefore": len(clips),
        "names": [item.get("name") for item in clips],
    }, ensure_ascii=False))

    for item in clips:
        delete_file(service, item.get("id"))

    remaining = list_clip_files(service, folder_id)
    print(json.dumps({
        "clipCountAfter": len(remaining),
        "remaining": [item.get("name") for item in remaining],
    }, ensure_ascii=False))

    if remaining:
        raise SystemExit(f"Stock reset incomplete: {len(remaining)} clip(s) remain")


if __name__ == "__main__":
    main()
