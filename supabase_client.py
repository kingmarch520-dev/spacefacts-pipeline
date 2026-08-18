"""
Supabase logging for the spacefacts pipeline.

ONE-TIME SETUP:
1. Go to https://supabase.com, create a free project (from phone browser)
2. In the SQL editor, run:

    create table videos (
      id bigint generated always as identity primary key,
      youtube_id text not null,
      title text not null,
      description text,
      hashtags text,
      thumbnail_url text,
      status text default 'unlisted',   -- unlisted | public | deleted
      topic text,
      created_at timestamp with time zone default now()
    );

3. In Project Settings -> API, copy:
     Project URL       -> SUPABASE_URL
     service_role key  -> SUPABASE_SERVICE_KEY  (server-side only, keep secret)
4. Store both as GitHub secrets (used by the pipeline) AND as Vercel
   environment variables (used by the dashboard's API routes).
"""

import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def log_video(youtube_id: str, title: str, description: str,
              hashtags: list, thumbnail_url: str, topic: str,
              status: str = "unlisted"):
    """Inserts a new row into the videos table after a successful upload."""
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/videos",
        headers=HEADERS,
        json={
            "youtube_id": youtube_id,
            "title": title,
            "description": description,
            "hashtags": " ".join(hashtags),
            "thumbnail_url": thumbnail_url,
            "topic": topic,
            "status": status,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()
