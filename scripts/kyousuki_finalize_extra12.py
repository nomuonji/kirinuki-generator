"""Promote 12 additional visually inspected episode 2/3 source clips without affecting the first 11."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from packages.shared.gdrive import get_drive_service
from scripts.kyousuki_stock_migration import children
from scripts.kyousuki_finalize_v4 import promote

EXTRA = {
    *(f"kyousuki_v2_ep2_clip_{i:03}.mp4" for i in range(1,7)),
    *(f"kyousuki_v2_ep3_clip_{i:03}.mp4" for i in range(1,7)),
}
INITIAL = {
    *(f"kyousuki_v2_ep4_clip_{i:03}.mp4" for i in range(1,6)),
    *(f"kyousuki_v2_ep5_clip_{i:03}.mp4" for i in range(1,7)),
}
LEDGER = "kyousuki_v4_additional12_final_migration.json"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--stock-folder",default="1Y0XEnzTMpQbBvQVD8Uzfc6xbZYRU6ss8")
    p.add_argument("--quarantine-folder",default="1hui3CPo2uA42GbN5puJpW6xkBvY1F-ZY")
    p.add_argument("--review-folder",default="14UnUSjyAK5BIeVOgEDSPt75EDzQSjlSa")
    args=p.parse_args()
    drive=get_drive_service()
    before={x["name"]:x for x in children(drive,args.stock_folder)}
    if not INITIAL.issubset(before):
        raise RuntimeError("Previously validated eleven episode 4/5 stock files missing")
    first_ids={name:before[name]["id"] for name in INITIAL}
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    result=promote(drive,args.stock_folder,args.review_folder,args.quarantine_folder,
                   manifest,expected=EXTRA,ledger_name=LEDGER)
    after={x["name"]:x for x in children(drive,args.stock_folder)}
    if any(name not in after or after[name]["id"] != id for name,id in first_ids.items()):
        raise RuntimeError("Existing episode 4/5 stock was modified")
    expected_active=EXTRA|INITIAL
    if not expected_active.issubset(after):
        raise RuntimeError("Not all 23 v4 clips are active")
    print("KYOUSUKI_EXTRA12_FINAL",json.dumps({"complete":result["complete"],
       "newPromoted":result["promotedOrPreviouslyActive"],
       "totalActiveV4":len(expected_active),
       "oldFirst11Untouched":True},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
