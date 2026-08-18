"""
YouTube upload module.

AUTH MODEL:
YouTube's API needs OAuth (not a simple API key) to upload video.
Since this runs headless in GitHub Actions, you generate a refresh
token ONCE on your phone, then store it as a GitHub secret. Every
run after that refreshes silently, no browser needed.

ONE-TIME SETUP (do this once, from your phone browser):
1. Go to https://console.cloud.google.com/apis/credentials
2. Create an OAuth 2.0 Client ID, type "Desktop app"
3. Enable the "YouTube Data API v3" for the project
4. Download the client_secret.json — you'll need client_id + client_secret
5. Run `get_refresh_token()` once (see bottom of this file) to get your
   refresh token. Paste the resulting values into GitHub repo secrets:
       YT_CLIENT_ID
       YT_CLIENT_SECRET
       YT_REFRESH_TOKEN

UPLOAD BEHAVIOR:
Videos upload as "private" by default. Nothing goes public until you
approve it via the Telegram bot (see telegram_notify.py). This matches
your existing privacy-status-randomization habit, but flips the
default to safe-until-approved for this new channel.
"""

import os
import json
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

YT_CLIENT_ID = os.environ.get("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "")


def get_access_token() -> str:
    """Exchanges the stored refresh token for a fresh access token."""
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": YT_CLIENT_ID,
            "client_secret": YT_CLIENT_SECRET,
            "refresh_token": YT_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload_video(
    file_path: str,
    title: str,
    description: str,
    tags: list,
    privacy_status: str = "private",
) -> dict:
    """
    Uploads a video to YouTube. Returns the API response JSON, which
    includes the new video's id (needed for the Telegram approve step).
    """
    access_token = get_access_token()

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": "27",  # Education — fits space/physics facts
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    # Resumable upload: init session, then send file bytes
    init_resp = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        data=json.dumps(metadata),
        timeout=30,
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    with open(file_path, "rb") as f:
        video_bytes = f.read()

    upload_resp = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4"},
        data=video_bytes,
        timeout=600,
    )
    upload_resp.raise_for_status()
    return upload_resp.json()


def set_privacy_status(video_id: str, privacy_status: str):
    """Used by the Telegram approve/skip buttons to flip a video
    from private -> public (approve) or private -> private, unchanged
    (skip, i.e. just leave it unlisted/private permanently)."""
    access_token = get_access_token()
    resp = requests.put(
        f"https://www.googleapis.com/youtube/v3/videos?part=status",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps({
            "id": video_id,
            "status": {"privacyStatus": privacy_status},
        }),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def delete_video(video_id: str):
    """Used by the Telegram 'skip' button to remove a rejected upload."""
    access_token = get_access_token()
    resp = requests.delete(
        f"https://www.googleapis.com/youtube/v3/videos?id={video_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    resp.raise_for_status()


# --------------------------------------------------------------
# ONE-TIME HELPER — run this locally/in Colab ONCE to get your
# refresh token. Not called automatically by the pipeline.
# --------------------------------------------------------------
def get_refresh_token(client_id: str, client_secret: str):
    """
    Run this once interactively (e.g. in a Colab cell) to obtain your
    refresh token. Prints the value — copy it into your GitHub secret
    YT_REFRESH_TOKEN.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": TOKEN_URL,
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            }
        },
        scopes=["https://www.googleapis.com/auth/youtube.upload",
                 "https://www.googleapis.com/auth/youtube"],
    )
    creds = flow.run_console()
    print("\nYOUR REFRESH TOKEN (save this as YT_REFRESH_TOKEN secret):")
    print(creds.refresh_token)
