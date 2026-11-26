"""
Uploads one finished Sticky News video to YouTube as private, using the
same youtube_upload.py and secrets your spacefacts pipeline already has.

Usage:
    python3 upload_sticky_news.py videos/video1_frog_bones.mp4 videos/video1_frog_bones.json

The JSON file is the metadata Claude gives you with each finished video:
    {"title": "...", "description": "...", "tags": [...],
     "category": "24", "privacy_status": "private"}

Logs the result as one line in upload_log.jsonl, in the same file your
Shorts pipeline already writes to.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from youtube_upload import upload_video  # already in this repo

LOG_PATH = Path(__file__).resolve().parent / "upload_log.jsonl"


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: python3 upload_sticky_news.py <video.mp4> <metadata.json>")

    video_path = Path(sys.argv[1])
    meta_path = Path(sys.argv[2])

    if not video_path.exists():
        sys.exit(f"Video file not found: {video_path}")
    if not meta_path.exists():
        sys.exit(f"Metadata file not found: {meta_path}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    required = ["title", "description", "tags"]
    missing = [k for k in required if k not in meta]
    if missing:
        sys.exit(f"Metadata is missing: {', '.join(missing)}")

    print(f"Uploading {video_path.name} ...")
    result = upload_video(
        file_path=str(video_path),
        title=meta["title"],
        description=meta["description"],
        tags=meta["tags"],
        privacy_status=meta.get("privacy_status", "private"),
    )

    entry = {
        "video_id": result["video_id"],
        "url": result["url"],
        "title": meta["title"],
        "channel": "sticky_news",
        "source_video": str(video_path),
        "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"Uploaded: {result['url']}")
    print("It is private. Review it in YouTube Studio, then publish when ready.")


if __name__ == "__main__":
    main()
