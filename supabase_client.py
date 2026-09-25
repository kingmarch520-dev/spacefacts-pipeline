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
     status text default 'unlisted', -- unlisted | public | deleted
     topic text,
     category text,        -- 'space' | 'ocean'
     ending_style text,    -- 'loop' | 'joke'
     views bigint,         -- filled in later via log_manual_performance()
     created_at timestamp with time zone default now()
   );

   If you already have the table from before, instead run:

   alter table videos add column if not exists category text;
   alter table videos add column if not exists ending_style text;
   alter table videos add column if not exists views bigint;

3. In Project Settings -> API, copy:
     Project URL       -> SUPABASE_URL
     service_role key  -> SUPABASE_SERVICE_KEY (server-side only, keep secret)
4. Store both as GitHub secrets (used by the pipeline) AND as Vercel
   environment variables (used by the dashboard's API routes).

CHANGES IN THIS VERSION:
- log_video() now accepts and stores category and ending_style. These
  were previously tracked locally in the pipeline and printed to the
  console but never persisted — meaning the category-weighting system
  and the loop-vs-joke A/B test had no real data to learn from, ever,
  no matter how long the channel ran.
- Added get_video_performance(), used by main_spacefacts.py's
  get_category_weights() to pull real {category, views} rows once
  view counts have been logged via log_manual_performance().
- Added upsert_video_performance(), used by log_manual_performance()
  in main_spacefacts.py so you can hand-enter view counts you read
  off YouTube Studio without needing full YouTube Data API sync.
- Added Authorization: Bearer header alongside apikey. Supabase's
  REST API expects both — apikey alone can silently behave like an
  unauthenticated request under some project configs (e.g. RLS
  enabled on the table), which would make inserts fail or reads
  return nothing with no obvious error.
"""

import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def log_video(youtube_id: str, title: str, description: str,
               hashtags: list, thumbnail_url: str, topic: str,
               category: str = None, ending_style: str = None,
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
            "category": category,
            "ending_style": ending_style,
            "status": status,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_video_performance() -> list:
    """
    Returns rows of {title, category, ending_style, views} for every
    logged video that has a views count filled in (i.e. you've run
    log_manual_performance() at least once for it). Used by
    get_category_weights() in main_spacefacts.py to weight future
    topic selection toward whichever category is actually performing
    better, instead of relying on the seeded fallback forever.

    Returns an empty list (not an error) if the table has no rows
    with views set yet, or if the request fails — the caller already
    falls back to seeded weights in that case.
    """
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=HEADERS,
            params={
                "select": "title,category,ending_style,views",
                "views": "not.is.null",
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"      (get_video_performance failed: {e})")
        return []


def upsert_video_performance(title: str, category: str, views: int):
    """
    Updates the views (and category, in case it was missing or wrong)
    for the row matching this title. Matches on title since that's
    the identifier you'd read off YouTube Studio by eye — youtube_id
    isn't visible there without extra clicks. If no row matches, this
    silently does nothing rather than erroring, so a typo'd title in
    MANUAL_PERFORMANCE_LOG doesn't crash the whole logging pass.
    """
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/videos",
        headers=HEADERS,
        params={"title": f"eq.{title}"},
        json={"views": views, "category": category},
        timeout=20,
    )
    resp.raise_for_status()
    result = resp.json()
    if not result:
        print(f"      (no matching row found for title: '{title}')")
    return result