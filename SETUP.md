# Spacefacts Pipeline + Dashboard — Full Setup

Everything here runs from your phone. No PC needed at any step.

## What this is

- **Pipeline** (`main_spacefacts.py` + friends): runs daily via GitHub
  Actions, generates a video, uploads it to YouTube as **unlisted**, and
  logs it to a database.
- **Dashboard** (`webapp/`): a website you open in your phone browser
  showing every generated video with Publish / Delete buttons. Publish
  flips the video to public on YouTube. Delete removes it entirely.

Nothing goes public automatically — every video sits as "unlisted"
until you approve it from the dashboard.

---

## Part 1 — Repo setup

1. Put `main_spacefacts.py`, `youtube_upload.py`, `supabase_client.py`,
   and the `.github/workflows/daily_spacefacts.yml` file into your
   AutoShorts GitHub repo (or a new repo for this channel — recommended,
   since it's a separate niche).
2. The workflow file must live at exactly:
   `.github/workflows/daily_spacefacts.yml`

## Part 2 — Supabase (the database)

1. Go to supabase.com → New project (free tier is enough).
2. Open the SQL editor and run the `create table videos (...)`
   statement from the top of `supabase_client.py`.
3. Go to Project Settings → API. Copy:
   - Project URL
   - `service_role` key (NOT the anon key — service_role is needed for
     writes from both the pipeline and the dashboard's API routes)

## Part 3 — YouTube API access

1. console.cloud.google.com → create a project → enable
   "YouTube Data API v3".
2. APIs & Services → Credentials → Create OAuth client ID →
   type "Desktop app". Note the client ID and client secret.
3. Run `youtube_upload.get_refresh_token(client_id, client_secret)`
   once, from a Colab cell — it'll print a link, you approve access
   with your YouTube account, and it prints a refresh token. Copy it.

## Part 4 — GitHub secrets (for the daily pipeline)

Repo → Settings → Secrets and variables → Actions → New repository
secret. Add all of these:

| Secret | From |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com/apikey |
| `PEXELS_API_KEY` | pexels.com/api |
| `YT_CLIENT_ID` | Part 3 |
| `YT_CLIENT_SECRET` | Part 3 |
| `YT_REFRESH_TOKEN` | Part 3 |
| `SUPABASE_URL` | Part 2 |
| `SUPABASE_SERVICE_KEY` | Part 2 |

Once these are set, the pipeline runs automatically every day at the
time set in the workflow file (`cron: "0 14 * * *"` = 14:00 UTC —
edit this line to whenever suits your posting schedule). You can also
trigger it manually anytime: repo → Actions → Daily Space Facts
Pipeline → Run workflow.

## Part 5 — Deploy the dashboard (Vercel)

1. Go to vercel.com → sign in with your GitHub account.
2. New Project → import the repo → set the **root directory** to
   `webapp` (since the dashboard lives in that subfolder).
3. In the project's Environment Variables, add:
   - `YT_CLIENT_ID`
   - `YT_CLIENT_SECRET`
   - `YT_REFRESH_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
4. Deploy. Vercel gives you a URL like `spacefacts-dashboard.vercel.app`
   — bookmark it on your phone home screen, it works like an app.

Every time you push to the repo, Vercel auto-redeploys. You never
touch a terminal for this part again.

## Daily flow, once everything's live

1. GitHub Actions runs overnight, uploads a new unlisted video, logs
   it to Supabase.
2. You open the dashboard on your phone, tap the thumbnail to preview
   on YouTube, then tap Publish or Delete.
3. Published videos go public immediately. Deleted ones are removed
   from YouTube and marked `deleted` in the dashboard so they drop out
   of your review queue.

## Costs

Everything above is on free tiers: GitHub Actions (2,000 free minutes/
month, this pipeline uses ~5-10 min/run), Supabase free tier, Vercel
free tier, Gemini free tier, Pexels free tier, Edge TTS (no cost, no
key), Pollinations (no cost, no key). The only thing that could
eventually cost money is Gemini or Pexels if you scale up volume a lot
— worth checking their current free-tier limits as you grow.
