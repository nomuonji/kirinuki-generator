import json, pathlib, typing as T

def load_transcript(path: str) -> T.List[dict]:
    p = pathlib.Path(path)
    if p.suffix.lower() == ".jsonl":
        items = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line=line.strip()
                if not line: continue
                items.append(json.loads(line))
        return items
    elif p.suffix.lower() == ".json":
        return json.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError("Transcript must be .json or .jsonl with fields {start,end,text}")
